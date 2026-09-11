# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from revocompute import task_types

ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "docker" / "runners" / "ppiformer"


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


def _load_adapter():
    spec = importlib.util.spec_from_file_location("ppiformer_predict", FAMILY / "predict.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ppiformer_discovers_distinct_ddg_and_embedding_contracts():
    with _RegistryContext():
        task_types.discover_plugins(str(ROOT / "docker" / "runners"), {"ppiformer"})
        ddg, runner = task_types.get("ppiformer_ddg")
        embedding, _ = task_types.get("ppiformer_embed")

        assert ddg.gpus is True and embedding.gpus is True
        assert ddg.schema["required"] == ["mutations"]
        assert ddg.schema["properties"]["mutations"]["maxLength"] == 8192
        assert ddg.schema["additionalProperties"] is False
        assert embedding.schema["properties"] == {}
        assert ddg.citation_dois == embedding.citation_dois
        assert ddg.citation_dois[0][1] == "10.48550/arXiv.2310.18515"
        assert ddg.citation_bibtex and embedding.citation_bibtex
        assert runner.mounts[0].mode == "ro"

    plugin = yaml.safe_load((FAMILY / "plugin.yaml").read_text(encoding="utf-8"))
    assert "ppiformer/model-assets.sha256" in plugin["runtime"]["build_inputs"]


def test_ppiformer_definition_pins_official_sources_and_keeps_weights_external():
    definition = (FAMILY / "ppiformer.def").read_text(encoding="utf-8")
    requirements = (FAMILY / "requirements.txt").read_text(encoding="utf-8")
    lock = (FAMILY / "requirements.lock").read_text(encoding="utf-8")
    adapter = (FAMILY / "predict.py").read_text(encoding="utf-8")
    wrapper = (FAMILY / "run.sh").read_text(encoding="utf-8")

    assert "From: nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04" in definition
    assert "https://github.com/anton-bushuiev/PPIformer.git" in definition
    assert "e324f5f30dd0dae55d194ac6b4d18c772219c3ee" in definition
    for revision in (
        "2a81808b72a6efc8ff1c809c0cc9d5b7cc0de386",
        "c3b99888c325c706a79371c084b066e6793edcbd",
        "a2a5b6d01f958acac39418bda1a5a9e3b4d71b53",
    ):
        assert revision in definition
    assert "uv pip sync" in definition
    assert "--require-hashes" in definition
    assert "https://download.pytorch.org/whl/cu118" in definition
    assert "--no-build-isolation" in definition
    assert "/mnt/db/weights/revocompute/ppiformer" not in definition.split("%post", 1)[1].split("%environment", 1)[0]
    assert "mirror" not in definition.lower()
    assert all("==" in line for line in requirements.splitlines() if line)
    assert "torch==2.1.2+cu118" in lock
    assert "torch-geometric==2.3.1" in lock
    assert lock.count("--hash=sha256:") >= 101
    assert "download_from_zenodo" not in adapter
    assert "requests.get" not in adapter
    assert "HF_HUB_OFFLINE=1" in wrapper


def test_ppiformer_official_asset_record_and_checksums_are_complete():
    assets = (FAMILY / "MODEL_ASSETS.md").read_text(encoding="utf-8")
    inventory = (FAMILY / "model-assets.sha256").read_text(encoding="utf-8").splitlines()

    assert "10.5281/zenodo.12789167" in assets
    assert "534,824,849" in assets
    assert "127844ea04063b1bc48a01c0eb92c42e" in assets
    assert "CC BY 4.0" in assets
    assert len(inventory) == 4
    assert all(len(line.split()[0]) == 64 for line in inventory)


@pytest.mark.parametrize("value", ["", "A1V", "AA1J", "AA1V,", ";", "AA1V;bad"])
def test_ppiformer_mutation_parser_rejects_invalid_or_ambiguous_syntax(value: str):
    with pytest.raises(ValueError):
        _load_adapter().parse_mutations(value)


def test_ppiformer_mutation_parser_preserves_combined_variants():
    assert _load_adapter().parse_mutations("AA1V,GB2A; AA2G\nGB3A") == ["AA1V,GB2A", "AA2G", "GB3A"]


def test_ppiformer_wrapper_dispatches_both_modes_and_requires_artifacts(tmp_path: Path):
    fake = tmp_path / "fake.py"
    fake.write_text(
        """#!/usr/bin/env python3
import json
from pathlib import Path
import sys
args = sys.argv[1:]
out = Path(args[args.index('--output-dir') + 1]); out.mkdir(parents=True, exist_ok=True)
if args[0] == 'ddg':
    (out / 'ddg_predictions.csv').write_text('mutation,predicted_ddg_kcal_mol\\nAA1V,0.0\\n')
else:
    names = ('residue_embeddings.npy', 'interface_embedding.npy', 'residue_index.csv', 'embedding_summary.json')
    for name in names:
        (out / name).write_bytes(b'x')
(out / 'run_metadata.json').write_text(json.dumps({'mode': args[0]}))
Path(sys.argv[sys.argv.index('--scratch-dir') + 1], 'call.json').write_text(json.dumps(args))
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    pdb = ROOT / "tests" / "data" / "ppiformer" / "1abc_A_B.pdb"
    cases = (("ppiformer_ddg", {"mutations": "AA1V", "impute_missing": False}), ("ppiformer_embed", {}))
    for task_type, params in cases:
        manifest = tmp_path / f"{task_type}.json"
        manifest.write_text(json.dumps({"files": [{"path": str(pdb)}], "params": params}), encoding="utf-8")
        output = tmp_path / task_type
        completed = subprocess.run(
            ["bash", str(FAMILY / "run.sh"), "-i", str(manifest), "-o", str(output)],
            env={
                **os.environ,
                "TASK_TYPE": task_type,
                "TASK_CONTEXT_SRC": str(ROOT / "docker" / "runners" / "common" / "task_context.sh"),
                "PPIFORMER_PREDICT_SCRIPT": str(fake),
                "PPIFORMER_PYTHON": "python3",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert (output / "task_finished").is_file()


def test_ppiformer_smoke_manifest_covers_both_programmatic_paths():
    smoke = yaml.safe_load((FAMILY / "test.yaml").read_text(encoding="utf-8"))
    cases = smoke["collections"]["smoke"]["cases"]
    assert {case["task"] for case in cases} == {"ppiformer_ddg", "ppiformer_embed"}
    for case in cases:
        fixture = ROOT / case["input"]["files"][0]
        assert fixture.is_file()
        assert fixture.name == "1abc_A_B.pdb"
