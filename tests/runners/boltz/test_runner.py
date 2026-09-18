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
FAMILY = ROOT / "docker/runners/boltz"
RUNNER = FAMILY / "run.sh"


class _RegistryContext:
    def __enter__(self):
        self.tasks = dict(task_types._registry)
        self.categories = dict(task_types._category_registry)
        return self

    def __exit__(self, *_):
        task_types._registry.clear()
        task_types._registry.update(self.tasks)
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
if os.environ.get('BOLTZ_FAKE_REQUIRE_LOCAL_MSA') == '1':
    assert 'msa: alignment.a3m' in input_path.read_text(encoding='utf-8')
    assert (input_path.parent / 'alignment.a3m').is_file()
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
                "inputs": {"specification": [{"path": str(source)}], "assets": []},
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
        "BOLTZ_PREPARE_INPUT": str(FAMILY / "prepare_input.py"),
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


def test_boltz_wrapper_maps_parameters_and_requires_offline_outputs(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(tmp_path)
    output = tmp_path / "result"

    completed = _run(env, manifest, output)

    assert completed.returncode == 0, completed.stderr
    args = json.loads(call_log.read_text(encoding="utf-8"))
    assert args[:2] == ["predict", str(output / "prepared_input/target.yaml")]
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
    assert (output / "prepared_input/target.yaml").is_file()


def test_boltz_wrapper_reconstructs_local_msa_reference(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(tmp_path)
    source = tmp_path / "target.yaml"
    source.write_text("sequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: alignment.a3m\n", encoding="utf-8")
    alignment = tmp_path / "stored-alignment.a3m"
    alignment.write_text(">query\nACDE\n", encoding="utf-8")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["inputs"]["specification"][0]["relative_path"] = "target.yaml"
    payload["inputs"]["assets"] = [{"path": str(alignment), "relative_path": "alignment.a3m"}]
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    env["BOLTZ_FAKE_REQUIRE_LOCAL_MSA"] = "1"
    output = tmp_path / "result"

    completed = _run(env, manifest, output)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(call_log.read_text(encoding="utf-8"))[1] == str(output / "prepared_input/target.yaml")
    assert (output / "prepared_input/alignment.a3m").read_text(encoding="utf-8") == ">query\nACDE\n"


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
