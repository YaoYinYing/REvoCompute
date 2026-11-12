# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""BioEmu2 adapter and entrypoint contract.

No GPU and no network: a fake ``bioemu2`` module on ``PYTHONPATH`` mirrors the
Python call seams the adapter binds to, and a fake ``bioemu2`` executable on
``BIOEMU2_CLI`` records the propagation argv. Each writes the upstream output
files, so the real ``run.sh`` is exercised end to end -- model-asset check,
mode dispatch, and publication check -- against the calls it actually makes.
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

FAKE_BIOEMU2 = """
import json
import os
from pathlib import Path


class System:
    @classmethod
    def from_description(cls, **kwargs):
        _capture("system", kwargs)
        return cls()

    @classmethod
    def from_cif(cls, path):
        _capture("system_from_cif", str(path))
        return cls()

    def model_dump(self):
        codes = [code for code in os.environ.get("BIOEMU2_FAKE_CCD_CODES", "").split(",") if code]
        return {"entities": [{"entity_type": "ligand", "ccd_code": code} for code in codes]}


def _capture(key, value):
    path = Path(os.environ["BIOEMU2_CALL"])
    calls = json.loads(path.read_text()) if path.exists() else {}
    calls[key] = value
    path.write_text(json.dumps(calls))


def load_model(*, checkpoint_path):
    _capture("checkpoint", str(checkpoint_path))
    return object()


def _publish(entry_point, output_dir, kwargs):
    _capture("entry_point", entry_point)
    _capture("sampling", kwargs)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    omit = os.environ.get("BIOEMU2_OMIT_OUTPUT", "")
    reject_first = os.environ.get("BIOEMU2_REJECT_FIRST") == "1"
    report = [
        {
            "frame": frame,
            "status": "rejected" if reject_first and frame == 0 else "passed",
            "reason": "bad_bonds_sidechain" if reject_first and frame == 0 else None,
        }
        for frame in range(kwargs["num_samples"])
    ]
    published = {
        "samples.xtc": b"xtc",
        "topology.cif": b"data_topology\\n",
        "system.yaml": b"entities: []\\n",
        "physicality.json": json.dumps(report).encode(),
    }
    for name, payload in published.items():
        if name != omit:
            (out / name).write_bytes(payload)
    return []


def sample_equilibrium(system, *, model, output_dir, **kwargs):
    return _publish("sample_equilibrium", output_dir, kwargs)


def predict_structure(system, *, model, output_dir, **kwargs):
    return _publish("predict_structure", output_dir, kwargs)
"""

FAKE_DATA_INTERFACE = """
from bioemu2 import System


def load_system_and_contacts(path):
    return System(), None
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

Path(os.environ["BIOEMU2_CLI_CAPTURE"]).write_text(json.dumps(sys.argv[1:]))
if failure := os.environ.get("BIOEMU2_CLI_FAIL"):
    sys.exit(failure)
out = Path(sys.argv[sys.argv.index("--out") + 1])
out.mkdir(parents=True, exist_ok=True)
(out / "samples.xtc").write_bytes(b"xtc")
(out / "topology.cif").write_bytes(b"data_topology\\n")
(out / "system.yaml").write_text("entities: []\\n", encoding="utf-8")
(out / "physicality.json").write_text(
    json.dumps([{"frame": 0, "status": "passed", "reason": None}]), encoding="utf-8"
)
(out / "command.txt").write_text("bioemu2 propagate\\n", encoding="utf-8")
"""


def _adapter():
    spec = importlib.util.spec_from_file_location("bioemu2_sample", FAMILY / "sample.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path, *, with_cli=False):
    """A fake checkpoint, its verified asset manifest, and the fake modules."""
    asset_root = tmp_path / "weights"
    checkpoint_dir = asset_root / "checkpoints" / "bioemu2-preview"
    checkpoint_dir.mkdir(parents=True)
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
    (package / "data_interface").mkdir(parents=True)
    (package / "structure").mkdir()
    (package / "__init__.py").write_text(FAKE_BIOEMU2, encoding="utf-8")
    (package / "data_interface" / "__init__.py").write_text(FAKE_DATA_INTERFACE, encoding="utf-8")
    (package / "structure" / "__init__.py").write_text("", encoding="utf-8")
    (package / "structure" / "templates.py").write_text(FAKE_TEMPLATES, encoding="utf-8")
    fasta = tmp_path / "input.fasta"
    fasta.write_text(">2KL8\nMEMDIRFRG\n", encoding="utf-8")
    if with_cli:
        cli = tmp_path / "bioemu2"
        cli.write_text(f"#!{sys.executable}\n{FAKE_CLI}", encoding="utf-8")
        cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
        return asset_root, manifest, modules, fasta, cli
    return asset_root, manifest, modules, fasta, None


def _run(
    tmp_path, asset_root, manifest, modules, input_file, params, extra_env=None,
    role="sequence", extra_inputs=None, empty_roles=(),
):
    from runner_protocol import run_with_manifest

    output_dir = tmp_path / "outputs"
    capture = tmp_path / "calls.json"
    env = os.environ.copy()
    env.update(
        {
            "BIOEMU2_PYTHON": sys.executable,
            "BIOEMU2_ASSET_ROOT": str(asset_root),
            "BIOEMU2_ASSET_MANIFEST": str(manifest),
            "BIOEMU2_CALL": str(capture),
            "RUNNER_RUNTIME_ROOT": str(ROOT / "docker" / "runners"),
            "PYTHONPATH": str(modules),
        }
    )
    env.update(extra_env or {})
    completed = run_with_manifest(
        RUNNER, input_file, output_dir, env, params=params, role=role,
        extra_inputs=extra_inputs, empty_roles=empty_roles,
    )
    return completed, output_dir, capture


def test_bioemu2_parameters_and_sequence_reach_upstream(tmp_path):
    asset_root, manifest, modules, fasta, _ = _workspace(tmp_path)
    params = {
        "num_samples": 3,
        "sampler": "edm_fk",
        "num_steps": 5,
        "batch_size": 2,
        "physicality_mode": "no_violations",
        "seed": 11,
    }

    completed, output_dir, capture = _run(tmp_path, asset_root, manifest, modules, fasta, params)

    assert completed.returncode == 0, completed.stderr
    calls = json.loads(capture.read_text(encoding="utf-8"))
    assert calls["entry_point"] == "sample_equilibrium"
    assert calls["system"] == {"proteins": ["MEMDIRFRG"]}
    assert calls["checkpoint"].endswith("checkpoints/bioemu2-preview/checkpoint.ckpt")
    assert calls["sampling"] == {
        "num_samples": 3,
        "sampler": "edm_fk",
        "num_steps": 5,
        "batch_size": 2,
        "physicality_mode": "no_violations",
        "seed": 11,
    }
    assert (output_dir / "topology.cif").is_file()
    assert not (output_dir / "topology.pdb").exists()
    assert (output_dir / "sequence.fasta").read_text(encoding="utf-8") == ">input\nMEMDIRFRG\n"
    assert (output_dir / "task_finished").is_file()


def test_bioemu2_structure_mode_calls_predict_structure(tmp_path):
    asset_root, manifest, modules, fasta, _ = _workspace(tmp_path)
    params = {"num_samples": 1, "num_steps": 4, "seed": 0}

    completed, output_dir, capture = _run(
        tmp_path,
        asset_root,
        manifest,
        modules,
        fasta,
        params,
        {"TASK_TYPE": "bioemu2_structure_prediction"},
    )

    assert completed.returncode == 0, completed.stderr
    calls = json.loads(capture.read_text(encoding="utf-8"))
    assert calls["entry_point"] == "predict_structure"
    assert calls["sampling"] == {"num_samples": 1, "num_steps": 4, "seed": 0}
    assert calls["system"] == {"proteins": ["MEMDIRFRG"]}
    assert (output_dir / "topology.cif").is_file()
    assert not (output_dir / "topology.pdb").exists()
    assert (output_dir / "sequence.fasta").is_file()
    assert (output_dir / "task_finished").is_file()


def test_bioemu2_propagation_forwards_resolved_flags_and_publishes_outputs(tmp_path):
    asset_root, manifest, modules, _fasta, cli = _workspace(tmp_path, with_cli=True)
    starting = tmp_path / "starting.cif"
    starting.write_text("data_test\n", encoding="utf-8")
    argv_capture = tmp_path / "argv.json"
    params = {
        "num_samples": 2,
        "lag_time_ns": 1.5,
        "seed": 3,
        "num_steps": 4,
        "batch_size": 2,
        "sampler": "edm_fk",
        "physicality_mode": "no_violations",
    }

    completed, output_dir, _ = _run(
        tmp_path,
        asset_root,
        manifest,
        modules,
        starting,
        params,
        {
            "TASK_TYPE": "bioemu2_propagate",
            "BIOEMU2_CLI": str(cli),
            "BIOEMU2_CLI_CAPTURE": str(argv_capture),
        },
        role="starting_structure",
    )

    assert completed.returncode == 0, completed.stderr
    forwards = json.loads(argv_capture.read_text(encoding="utf-8"))
    assert forwards == [
        "propagate",
        "--x0-cif",
        str(starting),
        "--checkpoint-path",
        str(asset_root / "checkpoints" / "bioemu2-preview" / "checkpoint.ckpt"),
        "--out",
        str(output_dir),
        "--num-samples",
        "2",
        "--lag-time-ns",
        "1.5",
        "--seed",
        "3",
        "--num-steps",
        "4",
        "--batch-size",
        "2",
        "--sampler",
        "edm_fk",
        "--physicality-filter",
        "no_violations",
    ]
    assert (output_dir / "topology.cif").is_file()
    assert not (output_dir / "topology.pdb").exists()
    assert (output_dir / "samples.xtc").is_file()
    assert (output_dir / "system.yaml").is_file()
    assert (output_dir / "physicality.json").is_file()
    assert not (output_dir / "sequence.fasta").exists()
    assert (output_dir / "task_finished").is_file()


def test_bioemu2_propagation_omits_unresolved_optional_flags(tmp_path):
    asset_root, manifest, modules, _fasta, cli = _workspace(tmp_path, with_cli=True)
    starting = tmp_path / "starting.cif"
    starting.write_text("data_test\n", encoding="utf-8")
    argv_capture = tmp_path / "argv.json"

    completed, output_dir, _ = _run(
        tmp_path,
        asset_root,
        manifest,
        modules,
        starting,
        {"num_samples": 1, "lag_time_ns": 1},
        {
            "TASK_TYPE": "bioemu2_propagate",
            "BIOEMU2_CLI": str(cli),
            "BIOEMU2_CLI_CAPTURE": str(argv_capture),
        },
        role="starting_structure",
    )

    assert completed.returncode == 0, completed.stderr
    forwards = json.loads(argv_capture.read_text(encoding="utf-8"))
    assert forwards == [
        "propagate",
        "--x0-cif",
        str(starting),
        "--checkpoint-path",
        str(asset_root / "checkpoints" / "bioemu2-preview" / "checkpoint.ckpt"),
        "--out",
        str(output_dir),
        "--num-samples",
        "1",
        "--lag-time-ns",
        "1",
    ]
    assert (output_dir / "topology.cif").is_file()


def _propagation_workspace(tmp_path):
    asset_root, manifest, modules, _fasta, cli = _workspace(tmp_path, with_cli=True)
    argv_capture = tmp_path / "argv.json"
    env = {
        "TASK_TYPE": "bioemu2_propagate",
        "BIOEMU2_CLI": str(cli),
        "BIOEMU2_CLI_CAPTURE": str(argv_capture),
    }
    return asset_root, manifest, modules, argv_capture, env


def test_bioemu2_propagation_accepts_a_ligand_that_inference_represents(tmp_path):
    asset_root, manifest, modules, argv_capture, env = _propagation_workspace(tmp_path)
    starting = tmp_path / "complex.cif"
    starting.write_text(
        "data_complex\n"
        "_pdbx_entity_nonpoly.entity_id 2\n"
        "_pdbx_entity_nonpoly.comp_id LIG\n"
        "loop_\n_atom_site.id\n1\n",
        encoding="utf-8",
    )

    completed, output_dir, _ = _run(
        tmp_path, asset_root, manifest, modules, starting,
        {"num_samples": 1, "lag_time_ns": 1}, env, role="starting_structure",
    )

    assert completed.returncode == 0, completed.stderr
    assert (output_dir / "task_finished").is_file()
    # Presence of a non-polymer entity is not by itself lossy: upstream infers
    # the ligand, so no explicit system is required.
    assert "--system" not in json.loads(argv_capture.read_text(encoding="utf-8"))
    assert "inferred from the starting CIF" in completed.stdout


def test_bioemu2_propagation_refuses_inference_loss_before_sampling(tmp_path):
    asset_root, manifest, modules, argv_capture, env = _propagation_workspace(tmp_path)
    cases = {
        "struct_conn.cif": ("_struct_conn.id 1\n", "_struct_conn connections"),
        "branched.cif": ("_pdbx_entity_branch.entity_id 2\n", "branched entities"),
    }
    for filename, (record, label) in cases.items():
        starting = tmp_path / filename
        starting.write_text(f"data_lossy\n{record}", encoding="utf-8")

        completed, output_dir, _ = _run(
            tmp_path, asset_root, manifest, modules, starting,
            {"num_samples": 1, "lag_time_ns": 1}, env, role="starting_structure",
        )

        assert completed.returncode != 0, filename
        assert label in completed.stderr, completed.stderr
        assert "system YAML" in completed.stderr
        assert not (output_dir / "task_finished").exists()
    assert not argv_capture.exists(), "a refused CIF must not reach upstream"


def test_bioemu2_inference_loss_scan_reads_cif_tokens_not_line_prefixes(tmp_path):
    adapter = _adapter()
    cases = {
        # Legal CIF forms that put the data name away from the line start.
        "loop_same_line.cif": "data_x\nloop_ _struct_conn.id _struct_conn.conn_type_id\n1 covale\n",
        "value_then_tag.cif": "data_x _struct_conn.id 1\n",
        "uppercase.cif": "data_x\n_STRUCT_CONN.ID 1\n",
        "nbsp_indent.cif": "data_x\n _struct_conn.id 1\n",
        "branched_same_line.cif": "data_x\n_pdbx_entity_branch.entity_id 2\n",
    }
    for filename, text in cases.items():
        path = tmp_path / filename
        path.write_text(text, encoding="utf-8")
        assert adapter.inference_losses(path), filename

    # Comments, quoted values, and semicolon text fields cannot carry a data
    # name, so their text is not a refusal.
    innocent = {
        "comment.cif": "data_x\n# _struct_conn.id 1\n",
        "quoted.cif": "data_x\n_note 'see _struct_conn.id below'\n",
        "text_field.cif": "data_x\n_descriptor\n; _struct_conn.id 1\n;\n",
    }
    for filename, text in innocent.items():
        path = tmp_path / filename
        path.write_text(text, encoding="utf-8")
        assert adapter.inference_losses(path) == [], filename


def test_bioemu2_propagation_forwards_an_explicit_system(tmp_path):
    asset_root, manifest, modules, argv_capture, env = _propagation_workspace(tmp_path)
    starting = tmp_path / "complex.cif"
    starting.write_text("data_complex\n_struct_conn.id 1\n", encoding="utf-8")
    declared = tmp_path / "system.yaml"
    declared.write_text("entities: []\n", encoding="utf-8")

    completed, output_dir, _ = _run(
        tmp_path, asset_root, manifest, modules, starting,
        {"num_samples": 1, "lag_time_ns": 1}, env,
        role="starting_structure", extra_inputs={"system": declared},
    )

    assert completed.returncode == 0, completed.stderr
    forwards = json.loads(argv_capture.read_text(encoding="utf-8"))
    assert forwards[forwards.index("--x0-cif") + 1] == str(starting)
    assert forwards[forwards.index("--system") + 1] == str(declared)
    assert "declared system YAML" in completed.stdout
    assert (output_dir / "task_finished").is_file()


def test_bioemu2_propagation_treats_a_declared_empty_system_role_as_absent(tmp_path):
    """The server manifest declares every role, leaving an optional one empty."""
    asset_root, manifest, modules, argv_capture, env = _propagation_workspace(tmp_path)
    starting = tmp_path / "starting.cif"
    starting.write_text("data_test\n", encoding="utf-8")

    completed, output_dir, _ = _run(
        tmp_path, asset_root, manifest, modules, starting,
        {"num_samples": 1, "lag_time_ns": 1}, env,
        role="starting_structure", empty_roles=("system",),
    )

    assert completed.returncode == 0, completed.stderr
    forwards = json.loads(argv_capture.read_text(encoding="utf-8"))
    assert "--system" not in forwards
    assert "inferred from the starting CIF" in completed.stdout
    assert (output_dir / "task_finished").is_file()


def test_bioemu2_propagation_reports_an_atom_mismatch(tmp_path):
    asset_root, manifest, modules, _argv_capture, env = _propagation_workspace(tmp_path)
    starting = tmp_path / "starting.cif"
    starting.write_text("data_test\n", encoding="utf-8")

    completed, output_dir, _ = _run(
        tmp_path, asset_root, manifest, modules, starting,
        {"num_samples": 1, "lag_time_ns": 1},
        {
            **env,
            "BIOEMU2_CLI_FAIL": (
                "--x0-cif atoms do not match the system: atom 3 is "
                "('CA', 'C', 'ALA', 0), system has ('CB', 'C', 'ALA', 0)"
            ),
        },
        role="starting_structure",
    )

    assert completed.returncode != 0
    assert "atoms do not match the system" in completed.stderr
    assert not (output_dir / "task_finished").exists()


def test_bioemu2_propagation_prewarms_ccd_components_before_the_cli(tmp_path):
    asset_root, manifest, modules, _argv, env = _propagation_workspace(tmp_path)
    starting = tmp_path / "starting.cif"
    starting.write_text("data_test\n", encoding="utf-8")
    ccd_capture = tmp_path / "ccd.json"

    completed, output_dir, _ = _run(
        tmp_path, asset_root, manifest, modules, starting,
        {"num_samples": 1, "lag_time_ns": 1},
        {
            **env,
            "BIOEMU2_FAKE_CCD_CODES": "A1L3H,NAG",
            "BIOEMU2_CCD_CAPTURE": str(ccd_capture),
        },
        role="starting_structure",
    )

    assert completed.returncode == 0, completed.stderr
    # One bounded fetch per distinct component, before the command runs.
    assert json.loads(ccd_capture.read_text(encoding="utf-8")) == {"A1L3H": 1, "NAG": 1}
    assert (output_dir / "task_finished").is_file()


def test_bioemu2_propagation_retries_a_transient_ccd_failure(tmp_path):
    asset_root, manifest, modules, _argv, env = _propagation_workspace(tmp_path)
    starting = tmp_path / "starting.cif"
    starting.write_text("data_test\n", encoding="utf-8")
    ccd_capture = tmp_path / "ccd.json"

    completed, output_dir, _ = _run(
        tmp_path, asset_root, manifest, modules, starting,
        {"num_samples": 1, "lag_time_ns": 1},
        {
            **env,
            "BIOEMU2_FAKE_CCD_CODES": "A1L3H",
            "BIOEMU2_CCD_FAIL": "transient",
            "BIOEMU2_CCD_FAIL_TIMES": "1",
            "BIOEMU2_CCD_CAPTURE": str(ccd_capture),
        },
        role="starting_structure",
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(ccd_capture.read_text(encoding="utf-8")) == {"A1L3H": 2}
    assert "attempt 1/3" in completed.stderr
    assert (output_dir / "task_finished").is_file()


def test_bioemu2_propagation_does_not_retry_a_missing_ccd_component(tmp_path):
    asset_root, manifest, modules, _argv, env = _propagation_workspace(tmp_path)
    starting = tmp_path / "starting.cif"
    starting.write_text("data_test\n", encoding="utf-8")
    ccd_capture = tmp_path / "ccd.json"

    completed, output_dir, _ = _run(
        tmp_path, asset_root, manifest, modules, starting,
        {"num_samples": 1, "lag_time_ns": 1},
        {
            **env,
            "BIOEMU2_FAKE_CCD_CODES": "A1L3H",
            "BIOEMU2_CCD_FAIL": "missing",
            "BIOEMU2_CCD_CAPTURE": str(ccd_capture),
        },
        role="starting_structure",
    )

    assert completed.returncode != 0
    assert json.loads(ccd_capture.read_text(encoding="utf-8")) == {"A1L3H": 1}
    assert "A1L3H" in completed.stderr
    assert "https://files.rcsb.org/ligands/download/A1L3H.cif" in completed.stderr
    assert "not retried" in completed.stderr
    assert not (output_dir / "task_finished").exists()


def test_bioemu2_ccd_codes_are_collected_and_deduplicated():
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


def test_bioemu2_ccd_prefetch_retries_transient_failures_with_backoff(monkeypatch):
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


def test_bioemu2_ccd_prefetch_stops_retrying_once_a_component_is_cached(monkeypatch):
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


def test_bioemu2_ccd_prefetch_does_not_retry_permanent_http_errors(monkeypatch):
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


def test_bioemu2_ccd_prefetch_reports_upstream_errors_without_retry(monkeypatch):
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


def test_bioemu2_propagation_requires_the_starting_structure_role(tmp_path):
    asset_root, manifest, modules, fasta, cli = _workspace(tmp_path, with_cli=True)

    completed, output_dir, _ = _run(
        tmp_path,
        asset_root,
        manifest,
        modules,
        fasta,
        {"num_samples": 1, "lag_time_ns": 1},
        {"TASK_TYPE": "bioemu2_propagate", "BIOEMU2_CLI": str(cli)},
        role="sequence",
    )

    assert completed.returncode != 0
    assert "starting_structure" in completed.stderr
    assert not (output_dir / "task_finished").exists()


def test_bioemu2_tasks_and_result_contracts_resolve(tmp_path):
    from revocompute.result_storyboard import contract_dir, expected_file_tree, storyboard_declaration
    from revocompute.task_types import isolated_discovery

    with isolated_discovery(str(ROOT / "docker" / "runners"), enabled={"bioemu2"}) as manager:
        tasks = {task.name: task for _identifier, task in manager.contributions.items("tasks")}

    assert set(tasks) == {"bioemu2_equilibrium", "bioemu2_structure_prediction", "bioemu2_propagate"}
    propagate_dir = FAMILY / "tasks" / "bioemu2_propagate"
    assert contract_dir(tasks["bioemu2_equilibrium"], str(ROOT)) == FAMILY
    assert contract_dir(tasks["bioemu2_structure_prediction"], str(ROOT)) == FAMILY
    assert contract_dir(tasks["bioemu2_propagate"], str(ROOT)) == propagate_dir

    shared = expected_file_tree(tasks["bioemu2_structure_prediction"], str(ROOT))
    assert set(shared) == {"topology", "coordinates", "sequence", "physicality", "system"}
    assert shared["topology"]["path"] == "topology.cif"
    propagated = expected_file_tree(tasks["bioemu2_propagate"], str(ROOT))
    assert {key for key, entry in propagated.items() if entry["required"]} == {
        "topology",
        "coordinates",
        "physicality",
        "system",
    }
    assert propagated["topology"]["path"] == "topology.cif"
    assert propagated["command"]["required"] is False
    assert "sequence" not in propagated

    for task_name, tree in (("bioemu2_structure_prediction", shared), ("bioemu2_propagate", propagated)):
        task = tasks[task_name]
        assert len(task.result_workspace) == 1
        view = task.result_workspace[0]
        assert view.plugin == "trajectory"
        required = {
            selector.value for selectors in view.sources.values() for selector in selectors if selector.required
        }
        assert required == {
            "topology.cif",
            "samples.xtc",
        }
        assert view.mapping["topology_format"] == "mmcif"
        for selectors in view.sources.values():
            assert {selector.value for selector in selectors} <= {entry["path"] for entry in tree.values()}

    assert storyboard_declaration(tasks["bioemu2_equilibrium"], str(ROOT), set(shared)) is not None
    assert storyboard_declaration(tasks["bioemu2_propagate"], str(ROOT), set(propagated)) is None


def test_bioemu2_missing_published_output_fails_the_task(tmp_path):
    asset_root, manifest, modules, fasta, _ = _workspace(tmp_path)

    completed, output_dir, _ = _run(
        tmp_path,
        asset_root,
        manifest,
        modules,
        fasta,
        {"num_samples": 1},
        {"BIOEMU2_OMIT_OUTPUT": "physicality.json"},
    )

    assert completed.returncode != 0
    assert "physicality.json" in completed.stderr
    assert not (output_dir / "task_finished").exists()


def test_bioemu2_publication_check_covers_every_required_contract_file(tmp_path):
    """The entrypoint fails when any file the fake upstream publishes is missing."""
    # The paths the fake upstream actually writes. sequence.fasta is written by
    # the adapter itself, so the fake has no seam to omit it; it is covered by
    # the success-path test.
    published = ["samples.xtc", "topology.cif", "system.yaml", "physicality.json"]
    for path in published:
        case = tmp_path / path
        case.mkdir()
        asset_root, manifest, modules, fasta, _ = _workspace(case)
        completed, output_dir, _ = _run(
            case,
            asset_root,
            manifest,
            modules,
            fasta,
            {"num_samples": 1},
            {"BIOEMU2_OMIT_OUTPUT": path},
        )
        assert completed.returncode != 0, path
        assert path in completed.stderr, completed.stderr
        assert not (output_dir / "task_finished").exists(), path


def test_bioemu2_rejected_frames_are_reported_not_failed(tmp_path):
    """A rejected ensemble still succeeds, and its counts must reach the log."""
    asset_root, manifest, modules, fasta, _ = _workspace(tmp_path)

    completed, output_dir, _ = _run(
        tmp_path,
        asset_root,
        manifest,
        modules,
        fasta,
        {"num_samples": 2},
        {"BIOEMU2_REJECT_FIRST": "1"},
    )

    assert completed.returncode == 0, completed.stderr
    assert "BioEmu2 physicality: 1/2 frames accepted (bad_bonds_sidechain: 1), 1 rejected" in completed.stdout
    assert (output_dir / "task_finished").is_file()


def test_bioemu2_sequence_framing(tmp_path):
    adapter = _adapter()
    fasta = tmp_path / "one.fasta"
    fasta.write_text(">query\nacdefg hik\n", encoding="utf-8")
    assert adapter.query_sequence(fasta) == "ACDEFGHIK"

    # A blank header is rejected on its own terms; a second record is rejected
    # as a second record even when its separator carries no header.
    fasta.write_text(">\nACDE\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty FASTA header"):
        adapter.query_sequence(fasta)

    fasta.write_text(">a\nACDE\n>b\nFGHI\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one protein sequence"):
        adapter.query_sequence(fasta)

    fasta.write_text(">a\nACDE\n>\nFGHI\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one protein sequence"):
        adapter.query_sequence(fasta)

    fasta.write_text(">a\nACDZ\n", encoding="utf-8")
    with pytest.raises(ValueError, match="residues Z"):
        adapter.query_sequence(fasta)


def test_bioemu2_optional_parameters_keep_upstream_defaults():
    adapter = _adapter()
    assert adapter.sampling_kwargs({"num_samples": 4}) == {"num_samples": 4}


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

    with pytest.raises(RuntimeError, match="steering CCD dictionary not found"):
        adapter.configure_steering_cache(tmp_path / "scratch", str(tmp_path / "missing.pkl"))


def test_bioemu2_runner_verifies_the_steering_ccd_identity(tmp_path):
    asset_root, manifest, modules, fasta, _ = _workspace(tmp_path)
    steering = tmp_path / "ccd.pkl"
    steering.write_bytes(b"steering dictionary")
    steering_manifest = tmp_path / "steering.sha256"
    steering_manifest.write_text(
        f"{hashlib.sha256(steering.read_bytes()).hexdigest()}  {steering}\n", encoding="utf-8"
    )
    env = {
        "BIOEMU2_STEERING_CCD": str(steering),
        "BIOEMU2_STEERING_CCD_MANIFEST": str(steering_manifest),
    }

    completed, _output_dir, _ = _run(
        tmp_path, asset_root, manifest, modules, fasta, {"num_samples": 1}, env
    )
    assert completed.returncode == 0, completed.stderr

    steering.write_bytes(b"tampered")
    completed, _output_dir, _ = _run(
        tmp_path, asset_root, manifest, modules, fasta, {"num_samples": 1}, env
    )
    assert completed.returncode != 0
    assert "steering CCD integrity verification failed" in completed.stderr
