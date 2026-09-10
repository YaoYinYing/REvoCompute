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
FAMILY = ROOT / "docker/runners/boltz"
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


def _load_boltz_registry():
    discover_plugins(str(ROOT / "docker/runners"), {"boltz"})
    return task_types.get("boltz_predict")


def _write_fake_boltz(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with open(os.environ['BOLTZ_CALL_LOG'], 'w', encoding='utf-8') as handle:
    json.dump(args, handle)
if os.environ.get('BOLTZ_FAKE_FAIL') == '1':
    raise SystemExit(23)
input_path = Path(args[1])
out_dir = Path(args[args.index('--out_dir') + 1]) / f'boltz_results_{input_path.stem}'
prediction = out_dir / 'predictions' / input_path.stem
prediction.mkdir(parents=True)
if os.environ.get('BOLTZ_FAKE_NO_STRUCTURE') != '1':
    (prediction / f'{input_path.stem}_model_0.cif').write_text('data_model', encoding='utf-8')
(prediction / f'confidence_{input_path.stem}_model_0.json').write_text(
    '{"confidence_score":0.8,"ptm":0.7,"iptm":0.0,"complex_plddt":0.9,"complex_pde":1.2}',
    encoding='utf-8',
)
(prediction / f'plddt_{input_path.stem}_model_0.npz').write_bytes(b'npz')
if '--write_full_pae' in args:
    (prediction / f'pae_{input_path.stem}_model_0.npz').write_bytes(b'npz')
if '--write_full_pde' in args:
    (prediction / f'pde_{input_path.stem}_model_0.npz').write_bytes(b'npz')
processed = out_dir / 'processed'
processed.mkdir()
(processed / 'manifest.json').write_text('{}', encoding='utf-8')
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _runner_env(tmp_path: Path, *, omit_checkpoint: bool = False) -> tuple[dict[str, str], Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake = tmp_path / "boltz"
    _write_fake_boltz(fake)
    assets = tmp_path / "assets"
    assets.mkdir()
    files = {"ccd.pkl": b"ccd"}
    if not omit_checkpoint:
        files["boltz1_conf.ckpt"] = b"checkpoint"
    for name, content in files.items():
        (assets / name).write_bytes(content)
    checksums = tmp_path / "model-assets.sha256"
    checksums.write_text(
        "".join(f"{hashlib.sha256(content).hexdigest()}  {assets / name}\n" for name, content in files.items()),
        encoding="ascii",
    )
    source = tmp_path / "target.yaml"
    source.write_text((ROOT / "tests/data/boltz/minimal.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [{"path": str(source)}],
                "params": {
                    "recycling_steps": 5,
                    "sampling_steps": 120,
                    "diffusion_samples": 2,
                    "preprocessing_workers": 3,
                    "seed": 17,
                    "write_full_pae": True,
                    "write_full_pde": True,
                },
            }
        ),
        encoding="utf-8",
    )
    call_log = tmp_path / "call.json"
    env = {
        **os.environ,
        "TASK_TYPE": "boltz_predict",
        "TASK_MANIFEST": str(manifest),
        "TASK_CONTEXT_SRC": str(ROOT / "docker/runners/common/task_context.sh"),
        "BOLTZ_CLI": str(fake),
        "BOLTZ_ASSET_ROOT": str(assets),
        "BOLTZ_ASSET_MANIFEST": str(checksums),
        "BOLTZ_CALL_LOG": str(call_log),
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


def test_boltz_plugin_owns_offline_multiformat_contract() -> None:
    with _RegistryContext():
        task, runner = _load_boltz_registry()

        assert task.display_name == "Boltz-1 structure prediction"
        assert task.runtime.name == "boltz"
        assert task.gpus is True
        assert task.input_extensions == (".yaml", ".yml", ".fasta", ".fa", ".fas", ".a3m", ".csv")
        assert task.primary_input_extensions == (".yaml", ".yml", ".fasta", ".fa", ".fas")
        assert task.schema["additionalProperties"] is False
        assert set(task.schema["properties"]) == {
            "recycling_steps",
            "sampling_steps",
            "diffusion_samples",
            "preprocessing_workers",
            "seed",
            "write_full_pae",
            "write_full_pde",
        }
        assert task.citation_dois[0][1] == "10.1101/2024.11.19.624167"
        assert len(runner.mounts) == 1
        assert runner.mounts[0].host_path == "/mnt/db/boltz"
        assert runner.mounts[0].container_path == "/mnt/db/boltz"
        assert runner.mounts[0].mode == "ro"


def test_boltz_definition_pins_release_and_excludes_model_assets() -> None:
    definition = (FAMILY / "boltz.def").read_text(encoding="utf-8")
    lock = (FAMILY / "requirements.lock").read_text(encoding="utf-8")
    plugin = yaml.safe_load((FAMILY / "plugin.yaml").read_text(encoding="utf-8"))
    provenance = json.loads((FAMILY / "upstream.json").read_text(encoding="utf-8"))

    assert "2355c62c957e95305527290112e9742d0565c458" in definition
    assert "torch==2.4.1" in lock
    assert "--hash=sha256:" in lock
    assert "torch==2.4.1" in (FAMILY / "requirements.lock").read_text(encoding="utf-8")
    assert "From: nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04" in definition
    assert "boltz1_conf.ckpt" not in definition
    assert "ccd.pkl" not in definition
    assert plugin["runtime"]["build_inputs"] == [
        "boltz/run.sh",
        "boltz/requirements.in",
        "boltz/requirements.lock",
        "boltz/model-assets.sha256",
        "boltz/upstream.json",
        "common/task_context.sh",
        "common/task_context.py",
    ]
    assert provenance["upstream_commit"] == "2355c62c957e95305527290112e9742d0565c458"
    assert provenance["upstream_version"] == "0.3.2"
    assert provenance["license"] == "MIT"


def test_boltz_wrapper_maps_parameters_and_requires_offline_outputs(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"

    completed = _run(env, manifest, output)

    assert completed.returncode == 0, completed.stderr
    args = json.loads(call_log.read_text(encoding="utf-8"))
    assert args[:2] == ["predict", str(tmp_path / "target.yaml")]
    assert "--cache" in args and args[args.index("--cache") + 1] == str(tmp_path / "assets")
    assert "--checkpoint" in args
    assert args[args.index("--checkpoint") + 1].endswith("/boltz1_conf.ckpt")
    assert args[args.index("--recycling_steps") + 1] == "5"
    assert args[args.index("--sampling_steps") + 1] == "120"
    assert args[args.index("--diffusion_samples") + 1] == "2"
    assert args[args.index("--num_workers") + 1] == "3"
    assert args[args.index("--seed") + 1] == "17"
    assert "--write_full_pae" in args
    assert "--write_full_pde" in args
    assert "--use_msa_server" not in args
    assert "--msa_server_url" not in args
    assert (output / "task_finished").is_file()
    assert (output / "boltz-model-assets.sha256").is_file()


def test_boltz_wrapper_fails_closed_before_cli_when_required_asset_is_missing(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(tmp_path, omit_checkpoint=True)
    completed = _run(env, manifest, tmp_path / "result")

    assert completed.returncode != 0
    assert "Missing Boltz-1 checkpoint" in completed.stderr
    assert not call_log.exists()


def test_boltz_wrapper_propagates_cli_failure_and_rejects_missing_structure(tmp_path: Path) -> None:
    env, manifest, _ = _runner_env(tmp_path)
    env["BOLTZ_FAKE_FAIL"] = "1"
    failed = _run(env, manifest, tmp_path / "failed")
    assert failed.returncode == 23
    assert not (tmp_path / "failed/task_finished").exists()

    env, manifest, _ = _runner_env(tmp_path / "second")
    env["BOLTZ_FAKE_NO_STRUCTURE"] = "1"
    missing = _run(env, manifest, tmp_path / "missing")
    assert missing.returncode != 0
    assert "produced no mmCIF structure" in missing.stderr
    assert not (tmp_path / "missing/task_finished").exists()
