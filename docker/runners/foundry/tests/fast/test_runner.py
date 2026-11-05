# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / "docker/runners/foundry"
RUNNER = FAMILY / "run.sh"

# The server materializes every parameter the owning task.yaml declares, with
# the schema default, before dispatch (revocompute/schemas.py::_resolved_params
# -> revocompute/routes.py manifest params), so these are the exact manifest
# parameter sets the adapter receives in production.
DEFAULT_PARAMS = {
    "foundry_rfd3_design": {
        "num_designs": 1,
        "diffusion_steps": 50,
        "num_recycles": 2,
        "seed": 0,
        "low_memory_mode": False,
        "dump_trajectories": False,
        "inference_mode": "fast",
        "sampler_step_scale": 1.5,
        "sampler_gamma_0": 0.6,
        "classifier_free_guidance": False,
        "centering": "all",
    },
    "foundry_rfd3na_design": {
        "num_designs": 1,
        "diffusion_steps": 50,
        "seed": 0,
        "low_memory_mode": False,
        "dump_trajectories": False,
        "sampler_step_scale": 1.5,
        "sampler_gamma_0": 0.6,
        "classifier_free_guidance": False,
        "centering": "all",
    },
    "foundry_rf3_fold": {
        "num_designs": 1,
        "diffusion_steps": 50,
        "num_recycles": 5,
        "seed": 0,
        "early_stopping_plddt_threshold": 0.5,
        "dump_trajectories": False,
        "template_noise_scale": 0.00001,
        "add_missing_atoms": True,
        "annotate_b_factor_with_plddt": True,
    },
}


def _params(task_type: str, **overrides: object) -> dict:
    return {**DEFAULT_PARAMS[task_type], **overrides}



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
    manifest.write_text(
        json.dumps({"inputs": {"specification": [{"path": str(specification)}], "assets": []}, "params": params}),
        encoding="utf-8",
    )
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
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    registry = asset_root / "checkpoint-registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_commit": "d078b24d6d0e6f8607e9a0311128f4a897f83953",
                "assets": [
                    {
                        "id": asset_id,
                        "filename": filename,
                        "size": checkpoint.stat().st_size,
                        "sha256": digest,
                        "license": "BSD-3-Clause",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    operator_manifest = asset_root / "model-assets.json"
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
        "FOUNDRY_CHECKPOINT_REGISTRY": str(registry),
        "FOUNDRY_ASSET_VALIDATOR": str(FAMILY / "validate_assets.py"),
        "FOUNDRY_LAUNCHER": str(FAMILY / "launch.py"),
        "FOUNDRY_UPSTREAM_MANIFEST": str(FAMILY / "upstream.json"),
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


def test_rfd3_wrapper_maps_every_declared_parameter_once(tmp_path: Path) -> None:
    params = {
        "num_designs": 2,
        "diffusion_steps": 7,
        "num_recycles": 3,
        "seed": 19,
        "low_memory_mode": True,
        "dump_trajectories": True,
        "inference_mode": "legacy",
        "sampler_step_scale": 2.5,
        "sampler_gamma_0": 0.2,
        "classifier_free_guidance": True,
        "centering": "motif",
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
    assert "inference_mode=legacy" in call
    assert "inference_sampler.step_scale=2.5" in call
    assert "inference_sampler.gamma_0=0.2" in call
    assert "inference_sampler.use_classifier_free_guidance=True" in call
    assert "inference_sampler.center_option=motif" in call
    # Exactly one override per declared parameter: nothing is dropped and no
    # parameter is forwarded twice.
    overridden = [item.split("=", 1)[0] for item in call if item.split("=", 1)[0] in {
        "diffusion_batch_size", "inference_sampler.num_timesteps", "inference_sampler.n_recycle",
        "seed", "low_memory_mode", "dump_trajectories", "inference_mode",
        "inference_sampler.step_scale", "inference_sampler.gamma_0",
        "inference_sampler.use_classifier_free_guidance", "inference_sampler.center_option",
    }]
    assert sorted(overridden) == [
        "diffusion_batch_size", "dump_trajectories", "inference_mode",
        "inference_sampler.center_option", "inference_sampler.gamma_0", "inference_sampler.n_recycle",
        "inference_sampler.num_timesteps", "inference_sampler.step_scale",
        "inference_sampler.use_classifier_free_guidance", "low_memory_mode", "seed",
    ]
    assert (output / "foundry-run.json").is_file()
    assert (output / "foundry-model-assets.json").is_file()
    assert (output / "task_finished").is_file()
    # The accepted values are recorded once, exactly as accepted.
    run_record = json.loads((output / "foundry-run.json").read_text(encoding="utf-8"))
    assert run_record["parameters"] == params
    assert run_record["upstream"] == {
        "commit": "d078b24d6d0e6f8607e9a0311128f4a897f83953",
        "distribution": "rc-foundry",
        "version": "1.0.0",
    }
    assert run_record["upstream_overrides"]["inference_sampler.step_scale"] == "2.5"
    assert run_record["upstream_overrides"]["n_batches"] == "1"


def test_rfd3_recycles_change_the_sampler_override(tmp_path: Path) -> None:
    """RFD3's sampler declares n_recycle, so the control reaches the CLI."""
    for recycles in (1, 20):
        case = tmp_path / f"recycles-{recycles}"
        env, manifest, call_log = _runner_env(
            case, "foundry_rfd3_design", _params("foundry_rfd3_design", num_recycles=recycles)
        )
        completed = _run(env, manifest, case / "result")
        assert completed.returncode == 0, completed.stderr
        call = json.loads(call_log.read_text(encoding="utf-8"))
        assert f"inference_sampler.n_recycle={recycles}" in call
    # The schema default is what the server sends when the user sets nothing.
    env, manifest, call_log = _runner_env(tmp_path / "default", "foundry_rfd3_design", DEFAULT_PARAMS["foundry_rfd3_design"])
    completed = _run(env, manifest, tmp_path / "default" / "result")
    assert completed.returncode == 0, completed.stderr
    assert "inference_sampler.n_recycle=2" in json.loads(call_log.read_text(encoding="utf-8"))


def test_rfd3na_never_forwards_a_recycling_override(tmp_path: Path) -> None:
    """RFD3NA's SampleDiffusionConfig has no n_recycle field.

    Hydra rejects ``inference_sampler.n_recycle`` for its config (and
    ``+inference_sampler.n_recycle`` only appends a key the sampler drops), so
    the adapter must never emit either form and the task exposes no control.
    """
    env, manifest, call_log = _runner_env(tmp_path, "foundry_rfd3na_design", DEFAULT_PARAMS["foundry_rfd3na_design"])
    completed = _run(env, manifest, tmp_path / "result")
    assert completed.returncode == 0, completed.stderr
    call = json.loads(call_log.read_text(encoding="utf-8"))
    assert call[0] == "design"
    assert "inference_sampler.num_timesteps=50" in call
    assert "inference_sampler.step_scale=1.5" in call
    assert "inference_sampler.gamma_0=0.6" in call
    assert "inference_sampler.use_classifier_free_guidance=False" in call
    assert "inference_sampler.center_option=all" in call
    assert all("n_recycle" not in item for item in call)


def test_rfd3na_rejects_the_removed_recycling_parameter(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(
        tmp_path, "foundry_rfd3na_design", _params("foundry_rfd3na_design", num_recycles=1)
    )
    completed = _run(env, manifest, tmp_path / "result")
    assert completed.returncode != 0
    assert "Unsupported foundry_rfd3na_design parameters: num_recycles" in completed.stderr
    assert not call_log.exists()


def test_rf3_recycles_use_the_fold_key(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(tmp_path, "foundry_rf3_fold", _params("foundry_rf3_fold", num_recycles=7))
    completed = _run(env, manifest, tmp_path / "result")
    assert completed.returncode == 0, completed.stderr
    call = json.loads(call_log.read_text(encoding="utf-8"))
    assert "n_recycles=7" in call
    assert all("inference_sampler.n_recycle" not in item for item in call)
    assert "n_recycles=5" not in call


def test_wrapper_fails_closed_when_a_declared_parameter_is_absent(tmp_path: Path) -> None:
    """Defaults live in task.yaml, not in the adapter."""
    env, manifest, call_log = _runner_env(tmp_path, "foundry_rfd3_design", {"num_designs": 1})
    completed = _run(env, manifest, tmp_path / "result")
    assert completed.returncode != 0
    assert "Missing diffusion_steps in the task manifest" in completed.stderr
    assert not call_log.exists()


def test_rf3_wrapper_maps_fold_controls(tmp_path: Path) -> None:
    params = {
        "num_designs": 2,
        "diffusion_steps": 9,
        "num_recycles": 4,
        "seed": 13,
        "early_stopping_plddt_threshold": 0.25,
        "dump_trajectories": False,
        "template_noise_scale": 0.00002,
        "add_missing_atoms": False,
        "annotate_b_factor_with_plddt": False,
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
    assert "template_noise_scale=2e-05" in call
    assert "add_missing_atoms=False" in call
    assert "annotate_b_factor_with_plddt=False" in call

def test_wrapper_fails_closed_on_bad_checksum_before_inference(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(tmp_path, "foundry_rfd3na_design", DEFAULT_PARAMS["foundry_rfd3na_design"])
    operator_manifest = Path(env["FOUNDRY_OPERATOR_ASSET_MANIFEST"])
    content = json.loads(operator_manifest.read_text(encoding="utf-8"))
    checkpoint = Path(env["FOUNDRY_ASSET_ROOT"]) / content["assets"][0]["filename"]
    checkpoint.write_bytes(b"Foundry-test-checkpoint")
    completed = _run(env, manifest, tmp_path / "result")
    assert completed.returncode != 0
    assert "SHA-256 mismatch" in completed.stderr
    assert not call_log.exists()


def test_wrapper_rejects_an_operator_asset_outside_the_pinned_registry(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(tmp_path, "foundry_rfd3_design", DEFAULT_PARAMS["foundry_rfd3_design"])
    operator_manifest = Path(env["FOUNDRY_OPERATOR_ASSET_MANIFEST"])
    content = json.loads(operator_manifest.read_text(encoding="utf-8"))
    content["assets"][0]["size"] += 1
    operator_manifest.write_text(json.dumps(content), encoding="utf-8")
    completed = _run(env, manifest, tmp_path / "result")
    assert completed.returncode != 0
    assert "does not match the pinned registry" in completed.stderr
    assert not call_log.exists()

def test_rf3_wrapper_accepts_upstream_ranking_only_early_stop(tmp_path: Path) -> None:
    env, manifest, _ = _runner_env(tmp_path, "foundry_rf3_fold", DEFAULT_PARAMS["foundry_rf3_fold"])
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
        tmp_path, "foundry_rfd3_design", _params("foundry_rfd3_design", early_stopping_plddt_threshold=0.5)
    )

    completed = _run(env, manifest, tmp_path / "result")

    assert completed.returncode != 0
    assert "Unsupported foundry_rfd3_design parameters: early_stopping_plddt_threshold" in completed.stderr
    assert not call_log.exists()
