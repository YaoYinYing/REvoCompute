# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
from revocompute import task_types

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/evosplit"
RUNNER = FAMILY / "run.sh"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("evosplit_predict", FAMILY / "predict.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RegistryContext:
    def __enter__(self):
        self.tasks = dict(task_types._registry)
        self.runtimes = dict(task_types._runtime_registry)
        self.categories = dict(task_types._category_registry)
        return self

    def __exit__(self, *_):
        task_types._registry.clear()
        task_types._registry.update(self.tasks)
        task_types._runtime_registry.clear()
        task_types._runtime_registry.update(self.runtimes)
        task_types._category_registry.clear()
        task_types._category_registry.update(self.categories)


def _params(**updates):
    values = {
        "gap_cutoff": 0.25,
        "max_msa_depth": 1024,
        "top_l": 7.5,
        "cluster_method": "kmeans",
        "mean_cluster_size": 32,
        "dbscan_epsilon": 5.0,
        "dbscan_min_samples": 5,
        "seed": 0,
        "supervised": False,
        "reference_chain_1": "",
        "reference_chain_2": "",
        "contact_cutoff": 8.0,
    }
    values.update(updates)
    return values


def _write_assets(root: Path, adapter) -> Path:
    records = []
    for name in (f"checkpoints/{adapter.MODEL_NAME}.pt", f"checkpoints/{adapter.MODEL_NAME}-contact-regression.pt"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode("ascii"))
        records.append(
            {
                "path": name,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source_url": f"https://dl.fbaipublicfiles.com/fair-esm/{name}",
            }
        )
    manifest = root / "assets.json"
    manifest.write_text(
        json.dumps(
            {
                "model": adapter.MODEL_NAME,
                "model_code": {"revision": adapter.UPSTREAM_COMMIT},
                "assets": records,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_evosplit_alignment_validation_and_deterministic_subsampling(tmp_path: Path) -> None:
    adapter = _load_adapter()
    source = tmp_path / "input.a3m"
    source.write_text(">q\nACDE\n>a\nACdDE\n>b\nAC-E\n>c\nAC--\n", encoding="utf-8")
    names, sequences, depth = adapter.read_alignment(source, 0.5)
    assert names == ["q", "a", "b"]
    assert sequences == ["ACDE", "ACDE", "AC-E"]
    assert depth == 3
    assert adapter.select_diverse(names, sequences, 2) == (["q", "b"], ["ACDE", "AC-E"])

    source.write_text(">q\nACDE\n>a\nACD\n>b\nACDE\n", encoding="utf-8")
    with pytest.raises(ValueError, match="equal match-state length"):
        adapter.read_alignment(source, 1.0)


def test_evosplit_manifest_requires_reference_pair_only_in_supervised_mode(tmp_path: Path) -> None:
    adapter = _load_adapter()
    alignment = tmp_path / "input.a3m"
    alignment.write_text(">q\nACDE\n>a\nACDE\n>b\nACDE\n", encoding="utf-8")
    reference = tmp_path / "one.pdb"
    reference.write_text("END\n", encoding="utf-8")

    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": {"alignment": [{"path": str(alignment)}], "reference_structures": []},
                "params": _params(supervised=True),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exactly two"):
        adapter.read_task_manifest(manifest)

    manifest.write_text(
        json.dumps(
            {
                "inputs": {
                    "alignment": [{"path": str(alignment)}],
                    "reference_structures": [{"path": str(reference)}],
                },
                "params": _params(),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="require supervised mode"):
        adapter.read_task_manifest(manifest)


def test_evosplit_asset_validation_fails_closed_and_checks_content(tmp_path: Path) -> None:
    adapter = _load_adapter()
    manifest = _write_assets(tmp_path, adapter)
    model, document = adapter.validate_assets(tmp_path, manifest)
    assert model.name == f"{adapter.MODEL_NAME}.pt"
    assert len(document["assets"]) == 2

    model.write_bytes(b"changed")
    with pytest.raises(ValueError, match="unexpected size|SHA-256"):
        adapter.validate_assets(tmp_path, manifest)


def test_evosplit_attention_features_remove_the_model_batch_axis() -> None:
    torch = pytest.importorskip("torch")

    adapter = _load_adapter()
    depth, heads, length = 4, 12, 20
    results = {
        "contacts": torch.rand(1, length, length),
        "row_attentions": torch.rand(1, 12, heads, length + 1, length + 1),
        "row_attentions_all": torch.rand(depth, 1, heads, length + 1, length + 1),
    }
    alphabet = type("Alphabet", (), {"prepend_bos": True})()

    contacts, features, weighted = adapter.extract_attention_features(results, alphabet, 2.0)

    assert contacts.shape == (length, length)
    assert features.shape == (depth, length * (length - 1) // 2)
    assert weighted.shape == (depth, length, length)


def test_evosplit_adapter_writes_cluster_evidence_and_provenance(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("sklearn")
    import numpy as np

    adapter = _load_adapter()
    assets = tmp_path / "assets"
    asset_manifest = _write_assets(assets, adapter)
    alignment = ROOT / "tests/data/evosplit/minimal.a3m"
    task_manifest = tmp_path / "task.json"
    task_manifest.write_text(
        json.dumps(
            {
                "inputs": {"alignment": [{"path": str(alignment)}], "reference_structures": []},
                "params": _params(mean_cluster_size=2),
            }
        ),
        encoding="utf-8",
    )

    def fake_infer(names, sequences, model_path, top_l):
        assert model_path.name == f"{adapter.MODEL_NAME}.pt"
        assert top_l == 7.5
        depth = len(sequences)
        length = len(sequences[0])
        contacts = np.eye(length, dtype=np.float32)
        features = np.arange(depth * 4, dtype=np.float32).reshape(depth, 4)
        weighted = np.zeros((depth, length, length), dtype=np.float32)
        return contacts, features, weighted

    monkeypatch.setattr(adapter, "infer_features", fake_infer)
    output = tmp_path / "output"
    adapter.run(task_manifest, output, assets, asset_manifest)

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["upstream_commit"] == adapter.UPSTREAM_COMMIT
    assert summary["analyzed_depth"] == 6
    assert summary["alignment_length"] == 12
    assert summary["cluster_count"] == 3
    assert len(list((output / "clusters").glob("cluster_*.a3m"))) == 3
    assert (output / "contact_probabilities.png").stat().st_size > 0
    assignments = (output / "sequence_assignments.csv").read_text(encoding="utf-8")
    assert "sequence_index,sequence_id,unsupervised_cluster" in assignments
    assert "0,query,query" in assignments


def _write_fake_predict(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
from pathlib import Path
import sys

args = sys.argv[1:]
out = Path(args[args.index('--output-dir') + 1])
out.mkdir(parents=True, exist_ok=True)
(out / 'clusters').mkdir()
(out / 'clusters/cluster_0.a3m').write_text('>q\\nACDE\\n>a\\nACDE\\n')
for name, content in {
    'processed_alignment.a3m': '>q\\nACDE\\n>a\\nACDE\\n',
    'sequence_assignments.csv': 'sequence_index,sequence_id,unsupervised_cluster\\n0,q,query\\n',
    'contact_probabilities.csv': '0,1\\n1,0\\n',
    'contact_probabilities.png': 'png',
    'summary.json': '{}',
    'evosplit-model-assets.json': '{}',
}.items():
    (out / name).write_text(content)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_evosplit_wrapper_uses_manifest_and_accepts_complete_outputs(tmp_path: Path) -> None:
    fake = tmp_path / "predict.py"
    _write_fake_predict(fake)
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": {
                    "alignment": [{"path": str(ROOT / "tests/data/evosplit/minimal.a3m")}],
                    "reference_structures": [],
                },
                "params": _params(),
            }
        )
    )
    output = tmp_path / "output"
    completed = subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output)],
        env={
            **os.environ,
            "TASK_TYPE": "evosplit_cluster",
            "EVOSPLIT_PYTHON": "python3",
            "EVOSPLIT_SCRIPT": str(fake),
            "EVOSPLIT_ASSET_ROOT": str(tmp_path),
            "EVOSPLIT_ASSET_MANIFEST": str(tmp_path / "assets.json"),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "REVODESIGN_STAGE:evosplit_cluster" in completed.stdout
    assert (output / "task_finished").is_file()
