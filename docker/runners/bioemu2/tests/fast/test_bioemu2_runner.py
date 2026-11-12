# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""BioEmu2 adapter and entrypoint contract.

No GPU and no network: a fake ``bioemu2`` module on ``PYTHONPATH`` mirrors the
upstream system parser and CCD seams the adapter binds to, and a fake
``bioemu2`` executable on ``BIOEMU2_CLI`` records the command. It writes the
upstream output files, so the real ``run.sh`` is exercised end to end --
model-asset check, mode dispatch, and publication check -- against the calls it
actually makes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / "docker" / "runners" / "bioemu2"
RUNNER = FAMILY / "run.sh"

SYSTEM_YAML = """entities:
  - entity_type: protein
    asym_ids: [A]
    sequence: MEMDIRFRG
bonds: []
"""

LIGAND_SYSTEM_YAML = """entities:
  - entity_type: protein
    asym_ids: [A]
    sequence: MEMDIRFRG
  - entity_type: ligand
    asym_ids: [L]
    ccd_code: NAG
bonds: []
"""

FAKE_DATA_INTERFACE = """
import json
import os
from pathlib import Path

import yaml


class System:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return self._data


def load_system_and_contacts(path):
    capture = os.environ.get("BIOEMU2_CALL")
    if capture:
        Path(capture).write_text(json.dumps({"system": str(path)}))
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("entities"), list):
        raise ValueError("System YAML must contain an entities list")
    return System(data), None
"""

FAKE_TEMPLATES = """
import json
import os
from pathlib import Path

import requests

_CCD_URL = "https://files.rcsb.org/ligands/download/{ccd_code}.cif"


class CCDTemplateError(Exception):
    pass


def _get_ccd_path(ccd_code):
    capture = os.environ.get("BIOEMU2_CCD_CAPTURE")
    attempts = 0
    if capture:
        path = Path(capture)
        seen = json.loads(path.read_text()) if path.exists() else {}
        attempts = seen.get(ccd_code, 0) + 1
        seen[ccd_code] = attempts
        path.write_text(json.dumps(seen))
    failure = os.environ.get("BIOEMU2_CCD_FAIL")
    if failure == "missing":
        raise CCDTemplateError(f"CCD component {ccd_code!r} was not found at RCSB")
    if failure == "transient" and attempts <= int(os.environ.get("BIOEMU2_CCD_FAIL_TIMES", "1")):
        raise requests.exceptions.SSLError("EOF occurred in violation of protocol")
    return Path(f"{ccd_code}.cif")
"""

FAKE_CLI = """
import json
import os
import sys
from pathlib import Path

argv = sys.argv[1:]
Path(os.environ["BIOEMU2_CLI_CAPTURE"]).write_text(json.dumps(argv))
if failure := os.environ.get("BIOEMU2_CLI_FAIL"):
    sys.exit(failure)
out = Path(argv[argv.index("--out") + 1])
out.mkdir(parents=True, exist_ok=True)
num_samples = int(argv[argv.index("--num-samples") + 1])
omit = os.environ.get("BIOEMU2_OMIT_OUTPUT", "")
reject_first = os.environ.get("BIOEMU2_REJECT_FIRST") == "1"
report = [
    {
        "frame": frame,
        "status": "rejected" if reject_first and frame == 0 else "passed",
        "reason": "bad_bonds_sidechain" if reject_first and frame == 0 else None,
    }
    for frame in range(num_samples)
]
published = {
    "samples.xtc": b"xtc",
    "topology.cif": b"data_topology\\n",
    "system.yaml": b"entities: []\\n",
    "physicality.json": json.dumps(report).encode(),
    "command.txt": " ".join(argv).encode() + b"\\n",
}
for name, payload in published.items():
    if name != omit:
        (out / name).write_bytes(payload)
"""


def _adapter():
    spec = importlib.util.spec_from_file_location("bioemu2_sample", FAMILY / "sample.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path):
    """A fake checkpoint, its verified asset manifest, and the fake modules."""
    asset_root = tmp_path / "weights"
    checkpoint_dir = asset_root / "checkpoints" / "bioemu2-preview"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "checkpoint.ckpt").write_bytes(b"checkpoint")
    (checkpoint_dir / "config.yaml").write_text("model: test\n", encoding="utf-8")
    manifest = tmp_path / "model-assets.sha256"
    manifest.write_text(
        "".join(
            f"{hashlib.sha256((checkpoint_dir / name).read_bytes()).hexdigest()}  "
            f"checkpoints/bioemu2-preview/{name}\n"
            for name in ("checkpoint.ckpt", "config.yaml")
        ),
        encoding="utf-8",
    )
    modules = tmp_path / "modules"
    package = modules / "bioemu2"
    (package / "data_interface").mkdir(parents=True, exist_ok=True)
    (package / "structure").mkdir(exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "data_interface" / "__init__.py").write_text(FAKE_DATA_INTERFACE, encoding="utf-8")
    (package / "structure" / "__init__.py").write_text("", encoding="utf-8")
    (package / "structure" / "templates.py").write_text(FAKE_TEMPLATES, encoding="utf-8")
    cli = tmp_path / "bioemu2"
    cli.write_text(f"#!{sys.executable}\n{FAKE_CLI}", encoding="utf-8")
    cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
    system = tmp_path / "system.yaml"
    if not system.exists():
        system.write_text(SYSTEM_YAML, encoding="utf-8")
    starting = tmp_path / "starting.cif"
    if not starting.exists():
        starting.write_text("data_test\n_atom_site.id\n1\n", encoding="utf-8")
    return asset_root, manifest, modules, system, starting, cli


def _steering_fixture(tmp_path):
    steering = tmp_path / "steering.pkl"
    steering.write_bytes(b"steering dictionary")
    manifest = tmp_path / "steering.sha256"
    manifest.write_text(f"{hashlib.sha256(steering.read_bytes()).hexdigest()}  {steering}\n", encoding="utf-8")
    return steering, manifest


def _run(
    tmp_path, modules, input_file, params, extra_env=None, *,
    role="system", extra_inputs=None, empty_roles=(), capture_name="argv.json",
):
    from runner_protocol import run_with_manifest

    asset_root, manifest, _modules, _system, _starting, cli = _workspace(tmp_path)
    output_dir = tmp_path / "outputs"
    argv_capture = tmp_path / capture_name
    env = os.environ.copy()
    env.pop("BIOEMU2_STEERING_CCD", None)
    env.pop("BIOEMU2_STEERING_CCD_MANIFEST", None)
    env.update(
        {
            "BIOEMU2_PYTHON": sys.executable,
            "BIOEMU2_ASSET_ROOT": str(asset_root),
            "BIOEMU2_ASSET_MANIFEST": str(manifest),
            "BIOEMU2_CLI": str(cli),
            "BIOEMU2_CLI_CAPTURE": str(argv_capture),
            "RUNNER_RUNTIME_ROOT": str(ROOT / "docker" / "runners"),
            "PYTHONPATH": str(modules),
        }
    )
    env.update(extra_env or {})
    completed = run_with_manifest(
        RUNNER, input_file, output_dir, env, params=params, role=role,
        extra_inputs=extra_inputs, empty_roles=empty_roles,
    )
    return completed, output_dir, argv_capture


def _argv(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_equilibrium_mode_runs_the_upstream_equilibrium_command(tmp_path):
    asset_root, manifest, modules, system, _starting, _cli = _workspace(tmp_path)
    params = {
        "mode": "equilibrium",
        "num_samples": 3,
        "sampler": "edm_fk",
        "num_steps": 5,
        "batch_size": 2,
        "physicality_mode": "no_violations",
        "seed": 11,
    }

    completed, output_dir, capture = _run(tmp_path, modules, system, params)

    assert completed.returncode == 0, completed.stderr
    forwards = _argv(capture)
    assert forwards[0] == "sample-equilibrium"
    assert forwards[forwards.index("--system") + 1] == str(system)
    assert forwards[forwards.index("--num-samples") + 1] == "3"
    assert forwards[forwards.index("--sampler") + 1] == "edm_fk"
    assert forwards[forwards.index("--num-steps") + 1] == "5"
    assert forwards[forwards.index("--batch-size") + 1] == "2"
    assert forwards[forwards.index("--physicality-filter") + 1] == "no_violations"
    assert forwards[forwards.index("--seed") + 1] == "11"
    assert "--x0-cif" not in forwards
    assert "--lag-time-ns" not in forwards
    assert (output_dir / "topology.cif").is_file()
    assert (output_dir / "samples.xtc").is_file()
    assert (output_dir / "system.yaml").is_file()
    assert (output_dir / "physicality.json").is_file()
    assert (output_dir / "task_finished").is_file()


def test_structure_prediction_mode_runs_the_upstream_predict_command(tmp_path):
    asset_root, manifest, modules, system, _starting, _cli = _workspace(tmp_path)
    params = {"mode": "structure_prediction", "num_samples": 1, "num_steps": 4, "seed": 0}

    completed, output_dir, capture = _run(tmp_path, modules, system, params)

    assert completed.returncode == 0, completed.stderr
    forwards = _argv(capture)
    assert forwards[0] == "predict-structure"
    assert forwards[forwards.index("--system") + 1] == str(system)
    assert "--x0-cif" not in forwards
    assert (output_dir / "task_finished").is_file()


def test_propagate_mode_forwards_the_system_and_starting_structure(tmp_path):
    asset_root, manifest, modules, system, starting, _cli = _workspace(tmp_path)
    params = {"mode": "propagate", "num_samples": 2, "lag_time_ns": 1.5, "num_steps": 4, "seed": 3}

    completed, output_dir, capture = _run(
        tmp_path, modules, system, params, role="system",
        extra_inputs={"starting_structure": starting},
        extra_env={"BIOEMU2_STEERING_CCD": "", "BIOEMU2_STEERING_CCD_MANIFEST": ""},
    )

    assert completed.returncode == 0, completed.stderr
    forwards = _argv(capture)
    assert forwards[0] == "propagate"
    assert forwards[forwards.index("--system") + 1] == str(system)
    assert forwards[forwards.index("--x0-cif") + 1] == str(starting)
    assert forwards[forwards.index("--lag-time-ns") + 1] == "1.5"
    assert forwards[forwards.index("--num-samples") + 1] == "2"
    assert "upstream compares the starting CIF atoms and order before model load" in completed.stdout
    assert (output_dir / "samples.xtc").is_file()
    assert (output_dir / "task_finished").is_file()


def test_optional_flags_are_not_invented(tmp_path):
    asset_root, manifest, modules, system, _starting, _cli = _workspace(tmp_path)

    completed, _output_dir, capture = _run(
        tmp_path, modules, system, {"mode": "equilibrium", "num_samples": 1}
    )

    assert completed.returncode == 0, completed.stderr
    forwards = _argv(capture)
    for flag in ("--seed", "--num-steps", "--batch-size"):
        assert flag not in forwards


def test_a_malformed_system_fails_before_the_cli(tmp_path):
    asset_root, manifest, modules, _system, _starting, _cli = _workspace(tmp_path)
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("sequence: not-a-system\n", encoding="utf-8")

    completed, output_dir, capture = _run(
        tmp_path, modules, malformed, {"mode": "equilibrium", "num_samples": 1}
    )

    assert completed.returncode != 0
    assert "entities" in completed.stderr
    assert not capture.exists(), "a refused system must not reach upstream"
    assert not (output_dir / "task_finished").exists()


def test_propagate_requires_the_starting_structure_role(tmp_path):
    asset_root, manifest, modules, system, _starting, _cli = _workspace(tmp_path)

    completed, output_dir, capture = _run(
        tmp_path, modules, system, {"mode": "propagate", "num_samples": 1, "lag_time_ns": 1}
    )

    assert completed.returncode != 0
    assert "starting_structure" in completed.stderr
    assert not capture.exists()
    assert not (output_dir / "task_finished").exists()


def test_non_propagate_modes_refuse_a_starting_structure(tmp_path):
    asset_root, manifest, modules, system, starting, _cli = _workspace(tmp_path)

    completed, output_dir, capture = _run(
        tmp_path, modules, system, {"mode": "equilibrium", "num_samples": 1},
        extra_inputs={"starting_structure": starting},
    )

    assert completed.returncode != 0
    assert "does not accept a starting_structure" in completed.stderr
    assert not capture.exists()
    assert not (output_dir / "task_finished").exists()


def test_propagation_prewarms_ccd_components_before_the_cli(tmp_path):
    asset_root, manifest, modules, system, starting, _cli = _workspace(tmp_path)
    system.write_text(LIGAND_SYSTEM_YAML, encoding="utf-8")
    ccd_capture = tmp_path / "ccd.json"

    completed, output_dir, _capture = _run(
        tmp_path, modules, system, {"mode": "propagate", "num_samples": 1, "lag_time_ns": 1},
        extra_inputs={"starting_structure": starting},
        extra_env={"BIOEMU2_CCD_CAPTURE": str(ccd_capture), "BIOEMU2_STEERING_CCD": "", "BIOEMU2_STEERING_CCD_MANIFEST": ""},
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(ccd_capture.read_text(encoding="utf-8")) == {"NAG": 1}
    assert (output_dir / "task_finished").is_file()


def test_equilibrium_prewarms_ccd_components_too(tmp_path):
    asset_root, manifest, modules, system, _starting, _cli = _workspace(tmp_path)
    system.write_text(LIGAND_SYSTEM_YAML, encoding="utf-8")
    ccd_capture = tmp_path / "ccd.json"

    completed, output_dir, _capture = _run(
        tmp_path, modules, system, {"mode": "equilibrium", "num_samples": 1},
        extra_env={"BIOEMU2_CCD_CAPTURE": str(ccd_capture), "BIOEMU2_STEERING_CCD": "", "BIOEMU2_STEERING_CCD_MANIFEST": ""},
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(ccd_capture.read_text(encoding="utf-8")) == {"NAG": 1}
    assert (output_dir / "task_finished").is_file()


def test_propagation_retries_a_transient_ccd_failure(tmp_path):
    asset_root, manifest, modules, system, starting, _cli = _workspace(tmp_path)
    system.write_text(LIGAND_SYSTEM_YAML, encoding="utf-8")
    ccd_capture = tmp_path / "ccd.json"

    completed, output_dir, _capture = _run(
        tmp_path, modules, system, {"mode": "propagate", "num_samples": 1, "lag_time_ns": 1},
        extra_inputs={"starting_structure": starting},
        extra_env={
            "BIOEMU2_CCD_CAPTURE": str(ccd_capture),
            "BIOEMU2_CCD_FAIL": "transient",
            "BIOEMU2_CCD_FAIL_TIMES": "1",
            "BIOEMU2_STEERING_CCD": "",
            "BIOEMU2_STEERING_CCD_MANIFEST": "",
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(ccd_capture.read_text(encoding="utf-8")) == {"NAG": 2}
    assert "attempt 1/3" in completed.stderr
    assert (output_dir / "task_finished").is_file()


def test_steering_is_required_for_a_steered_sampler_in_any_mode(tmp_path):
    asset_root, manifest, modules, system, _starting, _cli = _workspace(tmp_path)
    system.write_text(LIGAND_SYSTEM_YAML, encoding="utf-8")

    completed, output_dir, capture = _run(
        tmp_path, modules, system,
        {"mode": "equilibrium", "num_samples": 1, "sampler": "edm_gd"},
        extra_env={"BIOEMU2_STEERING_CCD": "", "BIOEMU2_STEERING_CCD_MANIFEST": ""},
    )

    assert completed.returncode != 0
    assert "steering CCD dictionary" in completed.stderr
    assert not capture.exists()
    assert not (output_dir / "task_finished").exists()


def test_unsteered_edm_does_not_need_the_steering_dictionary(tmp_path):
    asset_root, manifest, modules, system, _starting, _cli = _workspace(tmp_path)
    system.write_text(LIGAND_SYSTEM_YAML, encoding="utf-8")

    completed, output_dir, _capture = _run(
        tmp_path, modules, system, {"mode": "equilibrium", "num_samples": 1, "sampler": "edm"},
        extra_env={"BIOEMU2_STEERING_CCD": "", "BIOEMU2_STEERING_CCD_MANIFEST": ""},
    )

    assert completed.returncode == 0, completed.stderr
    assert (output_dir / "task_finished").is_file()


def test_the_runner_verifies_the_steering_dictionary_identity(tmp_path):
    asset_root, manifest, modules, system, _starting, _cli = _workspace(tmp_path)
    system.write_text(LIGAND_SYSTEM_YAML, encoding="utf-8")
    steering, steering_manifest = _steering_fixture(tmp_path)

    completed, output_dir, _capture = _run(
        tmp_path, modules, system,
        {"mode": "equilibrium", "num_samples": 1, "sampler": "edm_gd"},
        extra_env={
            "BIOEMU2_STEERING_CCD": str(steering),
            "BIOEMU2_STEERING_CCD_MANIFEST": str(steering_manifest),
        },
    )
    assert completed.returncode == 0, completed.stderr
    assert f"BioEmu2 steering CCD: {steering}" in completed.stdout
    assert (output_dir / "task_finished").is_file()

    steering.write_bytes(b"tampered")
    (output_dir / "task_finished").unlink()
    completed, output_dir, _capture = _run(
        tmp_path, modules, system,
        {"mode": "equilibrium", "num_samples": 1, "sampler": "edm_gd"},
        extra_env={
            "BIOEMU2_STEERING_CCD": str(steering),
            "BIOEMU2_STEERING_CCD_MANIFEST": str(steering_manifest),
        },
    )
    assert completed.returncode != 0
    assert "steering CCD integrity verification failed" in completed.stderr
    assert not (output_dir / "task_finished").exists()


def test_a_missing_steering_dictionary_fails_before_the_cli(tmp_path):
    asset_root, manifest, modules, system, _starting, _cli = _workspace(tmp_path)
    system.write_text(LIGAND_SYSTEM_YAML, encoding="utf-8")

    completed, output_dir, capture = _run(
        tmp_path, modules, system,
        {"mode": "equilibrium", "num_samples": 1, "sampler": "edm_fk"},
        extra_env={
            "BIOEMU2_STEERING_CCD": str(tmp_path / "missing.pkl"),
            "BIOEMU2_STEERING_CCD_MANIFEST": str(tmp_path / "missing.sha256"),
        },
    )

    assert completed.returncode != 0
    assert "steering CCD dictionary is missing" in completed.stderr
    assert not capture.exists()
    assert not (output_dir / "task_finished").exists()


def test_a_propagation_atom_mismatch_fails_the_task(tmp_path):
    asset_root, manifest, modules, system, starting, _cli = _workspace(tmp_path)

    completed, output_dir, _capture = _run(
        tmp_path, modules, system,
        {"mode": "propagate", "num_samples": 1, "lag_time_ns": 1},
        extra_inputs={"starting_structure": starting},
        extra_env={
            "BIOEMU2_CLI_FAIL": (
                "--x0-cif atoms do not match the system: atom 3 is "
                "('CA', 'C', 'ALA', 0), system has ('CB', 'C', 'ALA', 0)"
            ),
            "BIOEMU2_STEERING_CCD": "",
            "BIOEMU2_STEERING_CCD_MANIFEST": "",
        },
    )

    assert completed.returncode != 0
    assert "atoms do not match the system" in completed.stderr
    assert not (output_dir / "task_finished").exists()


def test_missing_published_output_fails_the_task(tmp_path):
    asset_root, manifest, modules, system, _starting, _cli = _workspace(tmp_path)

    completed, output_dir, _capture = _run(
        tmp_path, modules, system, {"mode": "equilibrium", "num_samples": 1},
        extra_env={"BIOEMU2_OMIT_OUTPUT": "physicality.json"},
    )

    assert completed.returncode != 0
    assert "physicality.json" in completed.stderr
    assert not (output_dir / "task_finished").exists()


def test_the_optional_command_record_is_not_required(tmp_path):
    asset_root, manifest, modules, system, _starting, _cli = _workspace(tmp_path)

    completed, output_dir, _capture = _run(
        tmp_path, modules, system, {"mode": "equilibrium", "num_samples": 1},
        extra_env={"BIOEMU2_OMIT_OUTPUT": "command.txt"},
    )

    assert completed.returncode == 0, completed.stderr
    assert (output_dir / "task_finished").is_file()


def test_rejected_frames_are_reported_not_failed(tmp_path):
    asset_root, manifest, modules, system, _starting, _cli = _workspace(tmp_path)

    completed, output_dir, _capture = _run(
        tmp_path, modules, system, {"mode": "equilibrium", "num_samples": 2},
        extra_env={"BIOEMU2_REJECT_FIRST": "1"},
    )

    assert completed.returncode == 0, completed.stderr
    assert "BioEmu2 physicality: 1/2 frames accepted (bad_bonds_sidechain: 1), 1 rejected" in completed.stdout
    assert (output_dir / "task_finished").is_file()


def test_ccd_codes_are_collected_and_deduplicated():
    adapter = _adapter()
    system = {
        "entities": [
            {"entity_type": "ligand", "ccd_code": "A1L3H"},
            {"entity_type": "protein", "mods": [{"res_id": 3, "ccd_code": "SEP"}]},
            {"entity_type": "branched", "mon_seq": [{"ccd_code": "NAG"}, {"ccd_code": "A1L3H"}]},
            {"entity_type": "ligand", "smiles": "CC"},
        ],
        "bonds": [],
    }

    assert adapter._ccd_codes_in(system) == ["A1L3H", "SEP", "NAG"]


def test_steering_codes_mirror_upstream_ligand_only_rules():
    adapter = _adapter()

    class System:
        def model_dump(self):
            return {
                "entities": [
                    {"entity_type": "ligand", "ccd_code": "A1L3H"},
                    {"entity_type": "protein", "mods": [{"ccd_code": "SEP"}]},
                    {"entity_type": "ligand", "smiles": "CC"},
                ]
            }

    assert adapter.steered_ligand_ccd_codes(System(), "edm_gd") == ["A1L3H"]
    assert adapter.steered_ligand_ccd_codes(System(), "edm") == []


def test_ccd_prefetch_retries_transient_failures_with_backoff(monkeypatch):
    import requests

    adapter = _adapter()
    monkeypatch.setattr(adapter, "_ccd_url", lambda code: f"https://example.test/{code}.cif")
    calls: list[str] = []

    def fetch(code):
        calls.append(code)
        raise requests.exceptions.SSLError("EOF occurred in violation of protocol")

    sleeps: list[float] = []
    with pytest.raises(RuntimeError, match="after 3 attempts") as failure:
        adapter.prefetch_ccd(["A1L3H"], fetch, sleep=sleeps.append)

    assert calls == ["A1L3H"] * 3
    assert sleeps == [2.0, 4.0]
    assert "A1L3H" in str(failure.value)
    assert "https://example.test/A1L3H.cif" in str(failure.value)


def test_ccd_prefetch_stops_retrying_once_a_component_is_cached(monkeypatch):
    import requests

    adapter = _adapter()
    monkeypatch.setattr(adapter, "_ccd_url", lambda code: f"https://example.test/{code}.cif")
    calls: list[str] = []

    def fetch(code):
        calls.append(code)
        if calls.count("A1L3H") == 1:
            raise requests.exceptions.ConnectionError("reset by peer")

    adapter.prefetch_ccd(["A1L3H", "NAG"], fetch, sleep=lambda _: None)

    assert calls == ["A1L3H", "A1L3H", "NAG"]


def test_ccd_prefetch_does_not_retry_permanent_http_errors(monkeypatch):
    import requests

    adapter = _adapter()
    monkeypatch.setattr(adapter, "_ccd_url", lambda code: f"https://example.test/{code}.cif")
    response = requests.Response()
    response.status_code = 403
    calls: list[str] = []

    def fetch(code):
        calls.append(code)
        raise requests.exceptions.HTTPError("forbidden", response=response)

    with pytest.raises(RuntimeError, match="not retried"):
        adapter.prefetch_ccd(["A1L3H"], fetch, sleep=lambda _: pytest.fail("must not sleep"))

    assert calls == ["A1L3H"]


def test_ccd_prefetch_reports_upstream_errors_without_retry(monkeypatch):
    adapter = _adapter()
    monkeypatch.setattr(adapter, "_ccd_url", lambda code: f"https://example.test/{code}.cif")
    calls: list[str] = []

    class CCDTemplateError(Exception):
        pass

    def fetch(code):
        calls.append(code)
        raise CCDTemplateError(f"CCD component {code!r} was not found at RCSB")

    with pytest.raises(RuntimeError, match="not retried"):
        adapter.prefetch_ccd(["A1L3H"], fetch, sleep=lambda _: pytest.fail("must not sleep"))

    assert calls == ["A1L3H"]


def test_ccd_prefetch_does_not_consume_a_retry_for_invalid_urls(monkeypatch):
    import requests

    adapter = _adapter()
    monkeypatch.setattr(adapter, "_ccd_url", lambda code: f"https://example.test/{code}.cif")
    attempts = {"count": 0}

    def fetch(_code):
        attempts["count"] += 1
        raise requests.exceptions.InvalidURL("bad URL")

    with pytest.raises(RuntimeError, match="not retried"):
        adapter.prefetch_ccd(["A1L3H"], fetch, sleep=lambda _: pytest.fail("must not sleep"))
    assert attempts["count"] == 1


def test_transient_request_error_rejects_permanent_request_failures():
    import requests

    adapter = _adapter()
    for error in (
        requests.exceptions.InvalidURL("invalid"),
        requests.exceptions.InvalidSchema("schema"),
        requests.exceptions.MissingSchema("missing"),
        requests.exceptions.TooManyRedirects("redirects"),
    ):
        assert adapter._transient_request_error(error) is False, type(error).__name__
    for error in (
        requests.exceptions.ConnectionError("connection"),
        requests.exceptions.Timeout("timeout"),
        requests.exceptions.SSLError("tls"),
        requests.exceptions.ChunkedEncodingError("dropped body"),
    ):
        assert adapter._transient_request_error(error) is True, type(error).__name__

    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

    for status_code, transient in ((429, True), (500, True), (400, False)):
        error = requests.exceptions.HTTPError("http", response=Response(status_code))
        assert adapter._transient_request_error(error) is transient, status_code
    assert adapter._transient_request_error(requests.exceptions.HTTPError("no response")) is False


def test_configure_steering_cache_exposes_the_asset_to_the_offline_hf_lookup(tmp_path, monkeypatch):
    adapter = _adapter()
    asset = tmp_path / "ccd.pkl"
    asset.write_bytes(b"steering dictionary")
    monkeypatch.delenv("HF_HOME", raising=False)

    assert adapter.configure_steering_cache(tmp_path / "scratch", str(asset)) == asset

    repo = tmp_path / "scratch" / "huggingface" / "hub" / "models--boltz-community--boltz-1"
    snapshot = repo / "snapshots" / adapter.STEERING_CCD_REVISION
    assert (snapshot / "ccd.pkl").resolve() == asset.resolve()
    # ``try_to_load_from_cache`` reads this file verbatim; a trailing newline
    # would stop it resolving the snapshot directory.
    assert (repo / "refs" / "main").read_text(encoding="utf-8") == adapter.STEERING_CCD_REVISION
    assert os.environ["HF_HOME"] == str(tmp_path / "scratch" / "huggingface")


def test_configure_steering_cache_is_optional_and_rejects_a_missing_asset(tmp_path, monkeypatch):
    adapter = _adapter()
    monkeypatch.delenv("BIOEMU2_STEERING_CCD", raising=False)
    assert adapter.configure_steering_cache(tmp_path / "unused") is None
    with pytest.raises(RuntimeError, match="steering CCD dictionary is not configured"):
        adapter.configure_steering_cache(tmp_path / "scratch", required=True)

    with pytest.raises(RuntimeError, match="steering CCD dictionary not found"):
        adapter.configure_steering_cache(tmp_path / "scratch", str(tmp_path / "missing.pkl"))


def test_the_unified_task_and_legacy_descriptors_resolve(tmp_path):
    from revocompute.result_storyboard import contract_dir, expected_file_tree
    from revocompute.task_types import isolated_discovery

    with isolated_discovery(str(ROOT / "docker" / "runners"), enabled={"bioemu2"}) as manager:
        tasks = {task.name: task for _identifier, task in manager.contributions.items("tasks")}

    assert set(tasks) == {
        "bioemu2", "bioemu2_equilibrium", "bioemu2_structure_prediction", "bioemu2_propagate",
    }
    assert tasks["bioemu2"].display_name == "BioEmu2"
    assert not tasks["bioemu2"].deprecated
    for legacy in ("bioemu2_equilibrium", "bioemu2_structure_prediction", "bioemu2_propagate"):
        assert tasks[legacy].deprecated
    assert contract_dir(tasks["bioemu2"], str(ROOT)) == FAMILY / "tasks" / "bioemu2"

    tree = expected_file_tree(tasks["bioemu2"], str(ROOT))
    assert {key for key, entry in tree.items() if entry["required"]} == {
        "topology", "coordinates", "physicality", "system",
    }
    assert tree["command"]["required"] is False
    assert "sequence" not in tree
