# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from revocompute import task_types
from revocompute.task_types import discover_plugins

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/chai1"
RUNNER = FAMILY / "run.sh"


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


def _load_chai1_registry():
    discover_plugins(str(ROOT / "docker/runners"), {"chai1"})
    return task_types.get("chai1_predict")


def _write_fake_predict(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with open(os.environ['CHAI1_CALL_LOG'], 'w', encoding='utf-8') as handle:
    json.dump(args, handle)
if os.environ.get('CHAI1_FAKE_FAIL') == '1':
    raise SystemExit(29)
out = Path(args[args.index('--output-dir') + 1])
(out / 'ranked').mkdir(parents=True)
if os.environ.get('CHAI1_FAKE_NO_STRUCTURE') != '1':
    (out / 'ranked/rank_0.model_idx_0.cif').write_text('data_chai1', encoding='utf-8')
(out / 'confidence.rank_0.json').write_text(
    '{"aggregate_score":0.8,"ptm":0.7,"iptm":0.6,"has_inter_chain_clashes":false}',
    encoding='utf-8',
)
for name in ('pae.rank_0.npy', 'pde.rank_0.npy', 'plddt.rank_0.npy'):
    (out / name).write_bytes(b'npy')
(out / 'ranking.json').write_text('[]', encoding='utf-8')
(out / 'run_metadata.json').write_text('{}', encoding='utf-8')
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _runner_env(tmp_path: Path, *, omit_asset: str | None = None) -> tuple[dict[str, str], Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake = tmp_path / "predict.py"
    _write_fake_predict(fake)
    assets = tmp_path / "assets"
    assets.mkdir()
    names = [
        "models_v2/feature_embedding.pt",
        "models_v2/bond_loss_input_proj.pt",
        "models_v2/token_embedder.pt",
        "models_v2/trunk.pt",
        "models_v2/diffusion_module.pt",
        "models_v2/confidence_head.pt",
        "esm/traced_sdpa_esm2_t36_3B_UR50D_fp16.pt",
        "conformers_v1.apkl",
    ]
    records = []
    for name in names:
        if name == omit_asset:
            continue
        path = assets / name
        path.parent.mkdir(parents=True, exist_ok=True)
        content = name.encode("ascii")
        path.write_bytes(content)
        records.append(
            {
                "path": name,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "url": f"https://assets.invalid/{name}",
                "etag": "test",
                "role": "test",
                "license": "test",
            }
        )
    asset_manifest = tmp_path / "model-assets.json"
    asset_manifest.write_text(json.dumps({"schema_version": 1, "assets": records}), encoding="utf-8")
    source = tmp_path / "target.fasta"
    source.write_text((ROOT / "tests/data/chai1/minimal.fasta").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "example.aligned.pqt").write_bytes(b"parquet")
    (tmp_path / "contacts.restraints").write_text("restraint_id\n", encoding="utf-8")
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": {
                    "entities": [{"path": str(source)}],
                    "alignments": [{"path": str(tmp_path / "example.aligned.pqt")}],
                    "restraints": [{"path": str(tmp_path / "contacts.restraints")}],
                },
                "params": {
                    "use_esm_embeddings": True,
                    "use_msa": True,
                    "use_restraints": True,
                    "recycle_msa_subsample": 32,
                    "num_trunk_recycles": 4,
                    "num_diffusion_timesteps": 100,
                    "num_diffusion_samples": 2,
                    "num_trunk_samples": 2,
                    "seed": 19,
                    "low_memory": True,
                },
            }
        ),
        encoding="utf-8",
    )
    call_log = tmp_path / "call.json"
    env = {
        **os.environ,
        "TASK_TYPE": "chai1_predict",
        "TASK_MANIFEST": str(manifest),
        "TASK_CONTEXT_SRC": str(ROOT / "docker/runners/common/task_context.sh"),
        "CHAI1_PYTHON": "python3",
        "CHAI1_SCRIPT": str(fake),
        "CHAI1_ASSET_ROOT": str(assets),
        "CHAI1_ASSET_MANIFEST": str(asset_manifest),
        "CHAI1_ASSET_VALIDATOR": str(FAMILY / "validate_assets.py"),
        "CHAI1_CALL_LOG": str(call_log),
    }
    return env, manifest, call_log


def _run(env: dict[str, str], manifest: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_chai1_wrapper_maps_advanced_offline_parameters(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"
    completed = _run(env, manifest, output)

    assert completed.returncode == 0, completed.stderr
    args = json.loads(call_log.read_text(encoding="utf-8"))
    assert args[args.index("--fasta-file") + 1] == str(tmp_path / "target.fasta")
    assert args[args.index("--asset-root") + 1] == str(tmp_path / "assets")
    assert args[args.index("--msa-directory") + 1] == str(tmp_path)
    assert args[args.index("--constraint-path") + 1] == str(tmp_path / "contacts.restraints")
    assert args[args.index("--recycle-msa-subsample") + 1] == "32"
    assert args[args.index("--num-trunk-recycles") + 1] == "4"
    assert args[args.index("--num-diffusion-timesteps") + 1] == "100"
    assert args[args.index("--num-diffusion-samples") + 1] == "2"
    assert args[args.index("--num-trunk-samples") + 1] == "2"
    assert args[args.index("--seed") + 1] == "19"
    assert "--use-esm-embeddings" in args
    assert "--low-memory" in args
    assert "--use-msa-server" not in args
    assert "--use-templates-server" not in args
    assert (output / "task_finished").is_file()
    assert (output / "chai1-model-assets.json").is_file()


def test_chai1_wrapper_fails_closed_on_missing_asset_before_inference(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(tmp_path, omit_asset="models_v2/trunk.pt")
    completed = _run(env, manifest, tmp_path / "result")

    assert completed.returncode != 0
    assert "trunk.pt" in completed.stderr
    assert not call_log.exists()


def test_chai1_wrapper_propagates_failure_and_rejects_missing_structure(tmp_path: Path) -> None:
    env, manifest, _ = _runner_env(tmp_path)
    env["CHAI1_FAKE_FAIL"] = "1"
    failed = _run(env, manifest, tmp_path / "failed")
    assert failed.returncode == 29
    assert not (tmp_path / "failed/task_finished").exists()

    env, manifest, _ = _runner_env(tmp_path / "second")
    env["CHAI1_FAKE_NO_STRUCTURE"] = "1"
    missing = _run(env, manifest, tmp_path / "missing")
    assert missing.returncode != 0
    assert "produced no ranked mmCIF structure" in missing.stderr
    assert not (tmp_path / "missing/task_finished").exists()
