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
FAMILY = ROOT / "docker/runners/geodock"
RUNNER = FAMILY / "run.sh"
FIXTURES = ROOT / "tests/data/geodock"
ASSETS = ("dips_0.3.ckpt", "esm2_t33_650M_UR50D.pt", "esm2_t33_650M_UR50D-contact-regression.pt")


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


def _write_fake_predictor(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
args = sys.argv[1:]
Path(os.environ['GEODOCK_CALL_LOG']).write_text(json.dumps(args), encoding='utf-8')
if os.environ.get('GEODOCK_FAKE_FAIL') == '1':
    raise SystemExit(31)
output = Path(args[args.index('--output-dir') + 1])
output.mkdir(parents=True, exist_ok=True)
output.joinpath('geodock_raw.pdb').write_text(
    'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 81.50           C\\nEND\\n',
    encoding='ascii',
)
output.joinpath('geodock-confidence.json').write_text('{"mean":81.5}\\n', encoding='utf-8')
if '--refine' in args:
    output.joinpath('geodock_refined.pdb').write_text('ATOM\\n', encoding='ascii')
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _runner_env(tmp_path: Path, params: dict, *, files: list[Path] | None = None) -> tuple[dict[str, str], Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    predictor = tmp_path / "fake_predict.py"
    _write_fake_predictor(predictor)
    inputs = files or [FIXTURES / "partner_a.pdb", FIXTURES / "partner_b.pdb"]
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps({"files": [{"path": str(path)} for path in inputs], "params": params}), encoding="utf-8"
    )
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    lines = []
    for name in ASSETS:
        payload = ("fake-" + name).encode()
        (asset_root / name).write_bytes(payload)
        lines.append(f"{hashlib.sha256(payload).hexdigest()}  {name}\n")
    asset_manifest = tmp_path / "model-assets.sha256"
    asset_manifest.write_text("".join(lines), encoding="ascii")
    call_log = tmp_path / "call.json"
    env = {
        **os.environ,
        "TASK_TYPE": "geodock",
        "GEODOCK_ASSET_ROOT": str(asset_root),
        "GEODOCK_ASSET_MANIFEST": str(asset_manifest),
        "GEODOCK_LAUNCHER": str(FAMILY / "launch.py"),
        "GEODOCK_PREDICTOR": str(predictor),
        "GEODOCK_PYTHON": "python3",
        "GEODOCK_UPSTREAM_PYTHON": "python3",
        "GEODOCK_CALL_LOG": str(call_log),
    }
    return env, manifest, call_log


def _run(env: dict[str, str], manifest: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output)],
        env=env, text=True, capture_output=True, check=False,
    )


def test_geodock_plugin_exposes_ordered_offline_docking_contract() -> None:
    with _RegistryContext():
        discover_plugins(str(ROOT / "docker/runners"), {"geodock"})
        task, runner = task_types.get("geodock")

        assert task.display_name == "GeoDock protein-protein docking"
        assert task.runtime.name == "geodock"
        assert task.gpus is True
        assert task.max_input_files == 2
        assert task.schema["additionalProperties"] is False
        assert [doi for _, doi, _ in task.citation_dois] == [
            "10.1002/pro.4862", "10.1126/science.ade2574", "10.1371/journal.pcbi.1005659",
        ]
        assert len(runner.mounts) == 1
        assert runner.mounts[0].host_path == "/mnt/db/weights/revocompute/geodock"
        assert runner.mounts[0].mode == "ro"


def test_definition_pins_direct_source_cuda_pyg_and_hashed_dependencies() -> None:
    definition = (FAMILY / "geodock.def").read_text(encoding="utf-8")
    lock = (FAMILY / "requirements.lock").read_text(encoding="utf-8")
    provenance = json.loads((FAMILY / "upstream.json").read_text(encoding="utf-8"))

    assert "From: nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04" in definition
    assert "https://github.com/Graylab/GeoDock.git" in definition
    assert "df8d1f4c24ae2946655f27e7411ba2ffabf3d350" in definition
    assert "https://github.com/openmm/pdbfixer.git" in definition
    assert "6bf10e138f6475f6f1850dae78d7bf1b420a1612" in definition
    assert "--require-hashes" in definition
    assert "https://data.pyg.org/whl/torch-2.0.1+cu118.html" in definition
    assert "torch==2.0.1+cu118" in lock
    assert "torch-geometric==2.3.1" in lock
    assert "--hash=sha256:" in lock
    assert "load_model_and_alphabet_local" in (FAMILY / "predict.py").read_text(encoding="utf-8")
    assert provenance["code_license"] == "MIT"
    assert provenance["upstream_publishes_checkpoint_digest"] is False


def test_wrapper_maps_safe_refinement_parameters_and_records_provenance(tmp_path: Path) -> None:
    params = {
        "refine": True,
        "refinement_stiffness": 12.5,
        "refinement_tolerance": 1.5,
    }
    env, manifest, call_log = _runner_env(tmp_path, params)
    output = tmp_path / "output"
    completed = _run(env, manifest, output)

    assert completed.returncode == 0, completed.stderr
    args = json.loads(call_log.read_text(encoding="utf-8"))
    assert args[args.index("--partner-a") + 1].endswith("partner_a.pdb")
    assert args[args.index("--partner-b") + 1].endswith("partner_b.pdb")
    assert args[args.index("--refinement-stiffness") + 1] == "12.5"
    assert args[args.index("--refinement-tolerance") + 1] == "1.5"
    assert "--refine" in args
    run = json.loads((output / "geodock-run.json").read_text(encoding="utf-8"))
    assert [partner["role"] for partner in run["partners"]] == ["A", "B"]
    assert run["runtime_network"] is False
    assert run["parameters"] == params
    assert (output / "geodock_raw.pdb").is_file()
    assert (output / "geodock_refined.pdb").is_file()
    assert (output / "geodock-model-assets.sha256").is_file()
    assert (output / "task_finished").is_file()


def test_wrapper_rejects_bad_inputs_and_parameters_before_prediction(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(tmp_path / "one", {}, files=[FIXTURES / "partner_a.pdb"])
    completed = _run(env, manifest, tmp_path / "one/output")
    assert completed.returncode != 0
    assert "exactly two ordered" in completed.stderr
    assert not call_log.exists()

    env, manifest, call_log = _runner_env(tmp_path / "unsafe", {"refinement_stiffness": 1000})
    completed = _run(env, manifest, tmp_path / "unsafe/output")
    assert completed.returncode != 0
    assert "refinement_stiffness must be between" in completed.stderr
    assert not call_log.exists()


def test_wrapper_fails_closed_for_asset_predictor_and_output_failures(tmp_path: Path) -> None:
    env, manifest, call_log = _runner_env(tmp_path / "asset", {})
    (tmp_path / "asset/assets/dips_0.3.ckpt").write_bytes(b"changed")
    completed = _run(env, manifest, tmp_path / "asset/output")
    assert completed.returncode != 0
    assert "asset integrity verification failed" in completed.stderr
    assert not call_log.exists()

    env, manifest, _ = _runner_env(tmp_path / "predictor", {})
    env["GEODOCK_FAKE_FAIL"] = "1"
    completed = _run(env, manifest, tmp_path / "predictor/output")
    assert completed.returncode == 31
    assert not (tmp_path / "predictor/output/task_finished").exists()


def test_smoke_case_is_minimal_and_refinement_is_opt_in() -> None:
    smoke = yaml.safe_load((FAMILY / "test.yaml").read_text(encoding="utf-8"))
    case = smoke["collections"]["smoke"]["cases"][0]
    assert case["task"] == "geodock"
    assert case["input"]["files"] == [
        "tests/data/geodock/partner_a.pdb", "tests/data/geodock/partner_b.pdb",
    ]
    assert case["parameters"]["refine"] is False
