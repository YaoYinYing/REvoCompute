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
FAMILY = ROOT / "docker/runners/foundry"
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


def _write_fake_foundry(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
args = sys.argv[1:]
Path(os.environ['FOUNDRY_CALL_LOG']).write_text(json.dumps(args), encoding='utf-8')
if os.environ.get('FOUNDRY_FAKE_FAIL') == '1':
    raise SystemExit(29)
out = Path(next(item.split('=', 1)[1] for item in args if item.startswith('out_dir=')))
if os.environ.get('FOUNDRY_FAKE_NO_STRUCTURE') != '1':
    (out / 'sample_model_0.cif').write_text('data_foundry\\n', encoding='utf-8')
(out / 'sample_model_0.json').write_text('{}\\n', encoding='utf-8')
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _runner_env(tmp_path: Path, task_type: str, params: dict) -> tuple[dict[str, str], Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = ROOT / "tests/data/foundry/rf3_monomer.json"
    specification = tmp_path / "input.json"
    specification.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    manifest = tmp_path / "task.json"
    manifest.write_text(json.dumps({"files": [{"path": str(specification)}], "params": params}), encoding="utf-8")
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    asset_id = {"foundry_rfd3_design": "rfd3", "foundry_rfd3na_design": "rfd3na", "foundry_rf3_fold": "rf3"}[task_type]
    filename = {
        "rfd3": "rfd3_latest.ckpt",
        "rfd3na": "rfd3na_1190.ckpt",
        "rf3": "rf3_foundry_01_24_latest_remapped.ckpt",
    }[asset_id]
    checkpoint = asset_root / filename
    checkpoint.write_bytes(b"foundry-test-checkpoint")
    operator_manifest = asset_root / "model-assets.json"
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    operator_manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": [{"id": asset_id, "filename": filename, "size": checkpoint.stat().st_size, "sha256": digest}],
            }
        ),
        encoding="utf-8",
    )
    fake = tmp_path / "fake_foundry.py"
    _write_fake_foundry(fake)
    call_log = tmp_path / "call.json"
    env = {
        **os.environ,
        "TASK_TYPE": task_type,
        "FOUNDRY_ASSET_ROOT": str(asset_root),
        "FOUNDRY_OPERATOR_ASSET_MANIFEST": str(operator_manifest),
        "FOUNDRY_CHECKPOINT_REGISTRY": str(FAMILY / "checkpoint-registry.json"),
        "FOUNDRY_ASSET_VALIDATOR": str(FAMILY / "validate_assets.py"),
        "FOUNDRY_LAUNCHER": str(FAMILY / "launch.py"),
        "FOUNDRY_SOURCE_ROOT": str(tmp_path),
        "FOUNDRY_EXECUTABLE": str(fake),
        "FOUNDRY_CALL_LOG": str(call_log),
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


def test_foundry_plugin_owns_three_stable_offline_workflows() -> None:
    with _RegistryContext():
        discover_plugins(str(ROOT / "docker/runners"), {"foundry"})
        task_ids = ("foundry_rfd3_design", "foundry_rfd3na_design", "foundry_rf3_fold")
        loaded = [task_types.get(task_id) for task_id in task_ids]
        assert all(task.gpus and not task.requires_network for task, _ in loaded)
        assert all(task.runtime.name == "foundry" for task, _ in loaded)
        assert all(task.schema["additionalProperties"] is False for task, _ in loaded)
        assert loaded[0][1] == loaded[1][1] == loaded[2][1]
        runner = loaded[0][1]
        assert runner.mounts[0].host_path == "/mnt/db/weights/revocompute/foundry"
        assert runner.mounts[0].mode == "ro"
        assert loaded[0][0].citation_dois[0][1] == "10.1101/2025.09.18.676967"
        assert loaded[2][0].citation_dois[0][1] == "10.1101/2025.08.14.670328"


def test_foundry_definition_pins_official_source_and_frozen_dependencies() -> None:
    definition = (FAMILY / "foundry.def").read_text(encoding="utf-8")
    provenance = json.loads((FAMILY / "upstream.json").read_text(encoding="utf-8"))
    plugin = yaml.safe_load((FAMILY / "plugin.yaml").read_text(encoding="utf-8"))
    assert "From: nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04" in definition
    assert "https://github.com/RosettaCommons/foundry.git" in definition
    assert "b02eed6a6bdf8f44d14a80cc36e3da13c9f2291c" in definition
    assert "uv sync --frozen --no-dev --extra rfd3 --extra rfd3na --extra rf3" in definition
    assert "foundry install" not in definition
    assert "mirror" not in definition.lower()
    assert provenance["code_license"] == "BSD-3-Clause"
    assert provenance["upstream_publishes_checkpoint_digests"] is False
    assert not any("mpnn" in task for task in plugin["tasks"])


def test_checkpoint_registry_records_official_unverified_assets() -> None:
    registry = json.loads((FAMILY / "checkpoint-registry.json").read_text(encoding="utf-8"))
    assert {asset["id"] for asset in registry["assets"]} == {"rfd3", "rfd3na", "rf3"}
    assert all(asset["url"].startswith("https://files.ipd.uw.edu/") for asset in registry["assets"])
    assert all(asset["sha256"] is None and asset["license"] is None for asset in registry["assets"])


def test_rfd3_wrapper_maps_only_bounded_parameters(tmp_path: Path) -> None:
    params = {
        "num_designs": 2,
        "diffusion_steps": 7,
        "num_recycles": 3,
        "seed": 19,
        "low_memory_mode": True,
        "dump_trajectories": True,
    }
    env, manifest, call_log = _runner_env(tmp_path, "foundry_rfd3_design", params)
    output = tmp_path / "result"
    completed = _run(env, manifest, output)
    assert completed.returncode == 0, completed.stderr
    call = json.loads(call_log.read_text(encoding="utf-8"))
    assert call[0] == "design"
    assert "diffusion_batch_size=2" in call
    assert "inference_sampler.num_timesteps=7" in call
    assert "inference_sampler.n_recycle=3" in call
    assert "seed=19" in call
    assert "low_memory_mode=True" in call
    assert "dump_trajectories=True" in call
    assert (output / "foundry-run.json").is_file()
    assert (output / "foundry-model-assets.json").is_file()
    assert (output / "task_finished").is_file()


def test_rf3_wrapper_maps_fold_controls(tmp_path: Path) -> None:
    params = {
        "num_designs": 2,
        "diffusion_steps": 9,
        "num_recycles": 4,
        "seed": 13,
        "early_stopping_plddt_threshold": 0.25,
        "dump_trajectories": False,
    }
    env, manifest, call_log = _runner_env(tmp_path, "foundry_rf3_fold", params)
    completed = _run(env, manifest, tmp_path / "result")
    assert completed.returncode == 0, completed.stderr
    call = json.loads(call_log.read_text(encoding="utf-8"))
    assert call[0] == "fold"
    assert "diffusion_batch_size=2" in call
    assert "num_steps=9" in call
    assert "n_recycles=4" in call
    assert "early_stopping_plddt_threshold=0.25" in call


def test_wrapper_fails_closed_on_bad_checksum_before_inference(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(tmp_path, "foundry_rfd3na_design", {})
    operator_manifest = Path(env["FOUNDRY_OPERATOR_ASSET_MANIFEST"])
    content = json.loads(operator_manifest.read_text(encoding="utf-8"))
    content["assets"][0]["sha256"] = "0" * 64
    operator_manifest.write_text(json.dumps(content), encoding="utf-8")
    completed = _run(env, manifest, tmp_path / "result")
    assert completed.returncode != 0
    assert "SHA-256 mismatch" in completed.stderr
    assert not call_log.exists()


def test_rf3_wrapper_accepts_upstream_ranking_only_early_stop(tmp_path: Path) -> None:
    env, manifest, _ = _runner_env(tmp_path, "foundry_rf3_fold", {})
    fake = Path(env["FOUNDRY_EXECUTABLE"])
    fake.write_text(
        """#!/usr/bin/env python3
from pathlib import Path
import sys
out = Path(next(item.split('=', 1)[1] for item in sys.argv if item.startswith('out_dir=')))
result = out / 'minimal_rf3'
result.mkdir()
(result / 'minimal_rf3_ranking_scores.csv').write_text('early_stopped\\ntrue\\n', encoding='utf-8')
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    completed = _run(env, manifest, tmp_path / "result")

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "result/task_finished").is_file()


def test_foundry_wrapper_rejects_unknown_task_parameters(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(
        tmp_path, "foundry_rfd3_design", {"early_stopping_plddt_threshold": 0.5}
    )

    completed = _run(env, manifest, tmp_path / "result")

    assert completed.returncode != 0
    assert "Unsupported foundry_rfd3_design parameters: early_stopping_plddt_threshold" in completed.stderr
    assert not call_log.exists()


def test_smoke_manifest_covers_all_three_models_with_tiny_cases() -> None:
    smoke = yaml.safe_load((FAMILY / "test.yaml").read_text(encoding="utf-8"))
    cases = smoke["collections"]["smoke"]["cases"]
    assert {case["task"] for case in cases} == {"foundry_rfd3_design", "foundry_rfd3na_design", "foundry_rf3_fold"}
    assert all(case["parameters"]["num_designs"] == 1 for case in cases)
    assert all(case["parameters"]["diffusion_steps"] == 2 for case in cases)
    assert all((ROOT / case["input"]["files"][0]).is_file() for case in cases)
