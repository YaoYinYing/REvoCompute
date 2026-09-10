# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml

from revocompute import task_types
from revocompute.task_types import discover_plugins

ROOT = Path(__file__).resolve().parents[1]
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
                "files": [
                    {"path": str(source)},
                    {"path": str(tmp_path / "example.aligned.pqt")},
                    {"path": str(tmp_path / "contacts.restraints")},
                ],
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


def test_chai1_plugin_owns_dedicated_offline_contract() -> None:
    with _RegistryContext():
        task, runner = _load_chai1_registry()

        assert task.display_name == "Chai-1 structure prediction"
        assert task.runtime.name == "chai1"
        assert task.gpus is True
        assert task.requires_network is False
        assert task.input_extensions == (".fasta", ".fa", ".faa", ".pqt", ".restraints", ".csv")
        assert task.primary_input_extensions == (".fasta", ".fa", ".faa")
        assert task.schema["additionalProperties"] is False
        assert set(task.schema["properties"]) == {
            "use_esm_embeddings",
            "use_msa",
            "use_restraints",
            "recycle_msa_subsample",
            "num_trunk_recycles",
            "num_diffusion_timesteps",
            "num_diffusion_samples",
            "num_trunk_samples",
            "seed",
            "low_memory",
        }
        assert task.citation_dois[0][1] == "10.1101/2024.10.10.615955"
        assert len(runner.mounts) == 1
        assert runner.mounts[0].host_path == "/mnt/db/weights/revocompute/chai1"
        assert runner.mounts[0].container_path == "/mnt/db/weights/revocompute/chai1"
        assert runner.mounts[0].mode == "ro"


def test_chai1_definition_and_asset_inventory_pin_upstream() -> None:
    definition = (FAMILY / "chai1.def").read_text(encoding="utf-8")
    requirements = (FAMILY / "requirements.lock").read_text(encoding="utf-8")
    provenance = json.loads((FAMILY / "upstream.json").read_text(encoding="utf-8"))
    asset_inventory = json.loads((FAMILY / "model-assets.json").read_text(encoding="utf-8"))
    assets = asset_inventory["assets"]

    assert "8d5ac0f93e9b6ea4c3a6545c253a6381c0f3694b" in definition
    assert "chai1/run.sh /app/revocompute/run.sh" in definition
    assert "common/task_context.sh /app/revocompute/task_context.sh" in definition
    assert "From: nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04" in definition
    assert "/opt/venv/bin/uv pip sync --python /opt/venv/bin/python" in definition
    assert "--require-hashes" in definition
    assert "-r /app/revocompute/requirements.lock" not in definition
    assert "torch==2.5.1+cu121" in requirements
    assert provenance["upstream_version"] == "0.6.1"
    assert provenance["upstream_commit"] == "8d5ac0f93e9b6ea4c3a6545c253a6381c0f3694b"
    assert provenance["code_license"] == "Apache-2.0"
    assert len(assets) == 8
    assert sum(asset["size"] for asset in assets) == 6_979_394_752
    assert asset_inventory["checksum_status"] == "verified"
    assert all(asset["url"].startswith("https://chaiassets.com/") for asset in assets)
    esm_asset = next(asset for asset in assets if asset["path"].startswith("esm/"))
    assert "/esm2/" in esm_asset["url"]
    assert all(len(asset["sha256"]) == 64 for asset in assets)
    assert "models_v2/trunk.pt" not in definition


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


def test_chai1_smoke_is_minimal_and_offline() -> None:
    smoke = yaml.safe_load((FAMILY / "test.yaml").read_text(encoding="utf-8"))
    [case] = smoke["collections"]["smoke"]["cases"]
    assert case["task"] == "chai1_predict"
    assert case["input"]["files"] == ["tests/data/chai1/minimal.fasta"]
    assert case["parameters"]["use_msa"] is False
    assert case["parameters"]["use_restraints"] is False
    assert case["parameters"]["num_diffusion_timesteps"] == 2
    assert case["parameters"]["num_diffusion_samples"] == 1
