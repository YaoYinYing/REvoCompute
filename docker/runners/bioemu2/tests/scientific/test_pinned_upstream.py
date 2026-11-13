# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Pinned-upstream acceptance for the unified BioEmu2 Task.

These checks execute the pinned SIF and its installed upstream code. They prove
that the submitted System YAML parses with the real upstream parser and that
the adapter's three mode commands are accepted by the real Click interface.

They are deliberately not a scientific result: no model is loaded, no GPU is
requested, and no ensemble is produced. Set ``BIOEMU2_SIF`` to the pinned image
to run them. An absent image fails rather than substituting a fake, because the
Runner acceptance lane treats a skip as a missing required test.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
UPSTREAM_COMMIT = "6d1ca744fa8ed285edafae7b98da65205bf00fd3"
SIF = os.environ.get("BIOEMU2_SIF")


@pytest.fixture(autouse=True)
def require_pinned_image():
    if not SIF or not Path(SIF).is_file():
        pytest.fail(
            "BIOEMU2_SIF must name the pinned bioemu2_v1.sif; pinned-upstream "
            "acceptance has no fake substitute",
            pytrace=False,
        )


def run_in_sif(script: str, binds: dict[Path, str]) -> str:
    """Run *script* in the pinned image with the requested read-only binds."""
    command = ["apptainer", "exec", "--containall", "--cleanenv"]
    for source, destination in binds.items():
        command += ["--bind", f"{source}:{destination}:ro"]
    command += [str(SIF), "python", "-"]
    completed = subprocess.run(
        command, input=script, text=True, capture_output=True, timeout=240, check=False
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    return completed.stdout


def result_line(output: str) -> dict:
    line = next(item for item in output.splitlines() if item.startswith("RESULT"))
    return json.loads(line.removeprefix("RESULT"))


def test_image_records_the_pinned_upstream_commit():
    output = run_in_sif("print(open('/opt/bioemu2-source-commit').read().strip())", {})
    assert output.strip() == UPSTREAM_COMMIT


def test_pinned_parser_accepts_jaag_systems():
    output = run_in_sif(
        """
import glob
import json
import os
from bioemu2 import paths
from bioemu2.data_interface import load_system_and_contacts

fixtures = {}
for name in ("equilibrium_system.yaml", "propagation_start.yaml", "ligand_system.yaml"):
    system, contacts = load_system_and_contacts(f"/data/{name}")
    fixtures[name] = {
        "entities": [entity["entity_type"] for entity in system.model_dump()["entities"]],
        "contacts": contacts,
    }
examples = {}
for path in sorted(glob.glob(os.path.join(paths.EXAMPLES_DIR, "systems", "*.yaml"))):
    system, _ = load_system_and_contacts(path)
    examples[os.path.basename(path)] = [
        entity["entity_type"] for entity in system.model_dump()["entities"]
    ]
print("RESULT" + json.dumps({"fixtures": fixtures, "examples": examples}))
""",
        {ROOT / "tests" / "data" / "bioemu2": "/data"},
    )
    parsed = result_line(output)
    assert parsed["fixtures"]["equilibrium_system.yaml"]["entities"] == ["protein"]
    assert parsed["fixtures"]["propagation_start.yaml"]["entities"] == ["protein"]
    assert parsed["fixtures"]["ligand_system.yaml"]["entities"] == ["protein", "ligand"]
    assert all(result["contacts"] is None for result in parsed["fixtures"].values())
    # The same pinned parser accepts the upstream-packaged examples, one of which
    # exercises ligand entities. A parser that only accepted our fixtures would
    # not be the upstream parser.
    assert any("ligand" in entities for entities in parsed["examples"].values())


def test_propagate_fixture_passes_real_atom_validation():
    output = run_in_sif(
        """
import json

import mdtraj
from bioemu2.cli import validate_x0
from bioemu2.data_interface import load_system_and_contacts

system, _ = load_system_and_contacts("/data/propagation_start.yaml")
trajectory = mdtraj.load("/data/propagation_start.cif")
validate_x0(trajectory, system)
print("RESULT" + json.dumps({
    "cif_residues": trajectory.topology.n_residues,
    "cif_atoms": trajectory.topology.n_atoms,
    "system_residues": len(system.model_dump()["entities"][0]["sequence"]),
}))
""",
        {ROOT / "tests" / "data" / "bioemu2": "/data"},
    )
    parsed = result_line(output)
    assert parsed["cif_residues"] == parsed["system_residues"] == 79
    assert parsed["cif_atoms"] == 646


def test_three_modes_are_accepted_by_the_pinned_cli():
    output = run_in_sif(
        """
import importlib.util
import json
from pathlib import Path

from bioemu2.cli import main as cli

spec = importlib.util.spec_from_file_location("bioemu2_adapter", "/adapter/sample.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

manifest = {
    "params": {
        "mode": "equilibrium",
        "num_samples": 2,
        "sampler": "edm",
        "physicality_mode": "high_quality",
        "seed": 7,
        "num_steps": 10,
        "batch_size": 1,
        "lag_time_ns": 1.0,
    },
    "inputs": {
        "system": [{"path": "/data/equilibrium_system.yaml"}],
        "starting_structure": [{"path": "/data/propagation_start.cif"}],
    },
}
system, contacts = adapter.load_system(Path("/data/ligand_system.yaml"))
steering = adapter.steered_ligand_ccd_codes(system, "edm_gd")
commands = {}
for mode, upstream_command in adapter.MODE_COMMANDS.items():
    assert upstream_command in cli.commands, (mode, upstream_command)
    argv = adapter.command_for_mode(
        mode,
        manifest,
        Path("/data/equilibrium_system.yaml"),
        Path("/ckpt/checkpoint.ckpt"),
        Path("/out"),
        Path("/data/propagation_start.cif"),
    )
    assert argv[:2] == ["bioemu2", upstream_command], argv
    context = cli.commands[upstream_command].make_context(upstream_command, argv[2:])
    declared = {
        option for parameter in cli.commands[upstream_command].params for option in parameter.opts
    }
    emitted = [item for item in argv[2:] if item.startswith("--")]
    commands[mode] = {
        "command": upstream_command,
        "undeclared": [flag for flag in emitted if flag not in declared],
        "params": sorted(context.params),
    }
print("RESULT" + json.dumps({"steering": steering, "commands": commands}))
""",
        {
            ROOT / "tests" / "data" / "bioemu2": "/data",
            ROOT / "docker" / "runners" / "bioemu2": "/adapter",
        },
    )
    parsed = result_line(output)
    assert parsed["steering"] == ["NAG"]
    assert set(parsed["commands"]) == {"equilibrium", "structure_prediction", "propagate"}
    assert all(command["undeclared"] == [] for command in parsed["commands"].values())
    assert parsed["commands"]["equilibrium"]["command"] == "sample-equilibrium"
    assert parsed["commands"]["structure_prediction"]["command"] == "predict-structure"
    assert parsed["commands"]["propagate"]["command"] == "propagate"
    assert "x0_cif" in parsed["commands"]["propagate"]["params"]


def test_steered_ligand_without_the_dictionary_fails_closed():
    output = run_in_sif(
        """
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("bioemu2_adapter", "/adapter/sample.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

# The steering check runs after topology CCD prefetch and before any model
# work. Stub only the network fetch; the asset gate under test is the real one.
adapter.prefetch_ccd = lambda codes: None
manifest = {
    "params": {"mode": "equilibrium", "num_samples": 1, "sampler": "edm_gd"},
    "inputs": {"system": [{"path": "/data/ligand_system.yaml"}]},
}
try:
    adapter.run_mode(
        "equilibrium", manifest, Path("/out"), Path("/ckpt/checkpoint.ckpt"), Path("/scratch")
    )
except RuntimeError as error:
    print("RESULT" + json.dumps({"error": str(error)}))
""",
        {
            ROOT / "tests" / "data" / "bioemu2": "/data",
            ROOT / "docker" / "runners" / "bioemu2": "/adapter",
        },
    )
    parsed = result_line(output)
    assert "steering CCD dictionary is not configured" in parsed["error"]
