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
    (modules / "bioemu2").mkdir(parents=True)
    (modules / "bioemu2" / "__init__.py").write_text(FAKE_BIOEMU2, encoding="utf-8")
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
    role="sequence", extra_inputs=None,
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
        RUNNER, input_file, output_dir, env, params=params, role=role, extra_inputs=extra_inputs
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


def test_bioemu2_propagation_reports_an_atom_mismatch(tmp_path):
    asset_root, manifest, modules, _argv_capture, env = _propagation_workspace(tmp_path)
    starting = tmp_path / "starting.cif"
    starting.write_text("data_test\n", encoding="utf-8")

    completed, output_dir, _ = _run(
        tmp_path, asset_root, manifest, modules, starting,
        {"num_samples": 1, "lag_time_ns": 1},
        {**env, "BIOEMU2_CLI_FAIL": "--x0-cif atoms do not match the system: atom 3 is ('CA', 'C', 'ALA', 0), system has ('CB', 'C', 'ALA', 0)"},
        role="starting_structure",
    )

    assert completed.returncode != 0
    assert "atoms do not match the system" in completed.stderr
    assert not (output_dir / "task_finished").exists()


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
