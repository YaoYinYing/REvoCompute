# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Typed CAVER start-point selection through the server and Runner boundary.

One test follows the same values end to end: the server normalizes a typed
selection against the owning `task.yaml`, the Runner resolves it against the
reference PDB, the rendered config carries the resolved point, and provenance
records the identity and method that produced it.
"""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

import pytest

from revocompute.schemas import TaskSubmissionRequest
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[2]
TASK = next((ROOT / "docker" / "runners").glob("*/tasks/caver/task.yaml"))
FAMILY = TASK.parents[2]
FIXTURE = FAMILY / "tests" / "fast" / "fixtures" / "selection.pdb"


@pytest.fixture(scope="module")
def runner(tmp_path_factory):
    # The installed-fleet collection may read the production tree, but the
    # Runner modules are still imported from a private copy so no other test
    # can observe them through a shared module name.
    copy = tmp_path_factory.mktemp("caver") / "family"
    shutil.copytree(FAMILY, copy)
    sys.path.insert(0, str(copy))
    try:
        yield importlib.import_module("pdb_selection"), importlib.import_module("caver_config")
    finally:
        sys.path.remove(str(copy))
        for name in ("pdb_selection", "caver_config"):
            sys.modules.pop(name, None)


@pytest.fixture(scope="module")
def server():
    with isolated_discovery(str(ROOT / "docker" / "runners")):
        yield


def _params(server, params: dict) -> dict:
    return TaskSubmissionRequest.model_validate({"task_type": "caver", "params": params}).coerce_params()


def test_centroid_selection_reaches_the_generated_config_and_provenance(server, runner) -> None:
    pdb_selection, caver_config = runner
    atoms = pdb_selection.parse_pdb(FIXTURE)
    params = _params(
        server,
        {
            "start_point_mode": "point",
            "start_point_source": "centroid",
            "start_x": 2.0,
            "start_y": 1.0,
            "start_z": 1.0,
            "start_selected_residues": "A:1",
            "start_selected_serials": "1-3",
            "start_reference_sha256": "a" * 64,
        },
    )
    point = pdb_selection.resolve_start_point(atoms, params)
    config = caver_config.render_config(params, point)

    assert "starting_point_coordinates 2.000 1.000 1.000" in config.splitlines()
    assert point.provenance["source"] == "centroid"
    assert point.provenance["selected_residues"] == ["A:1"]
    assert point.provenance["selected_atom_serials"] == [1, 2, 3]
    assert point.provenance["coordinate_verified"] is True
    assert params["start_reference_sha256"] == "a" * 64


def test_group_selection_uses_the_canonical_directive_without_a_residue_number(server, runner) -> None:
    pdb_selection, caver_config = runner
    atoms = pdb_selection.parse_pdb(FIXTURE)
    params = _params(server, {"start_point_mode": "group", "start_group": "A:1-2"})
    point = pdb_selection.resolve_start_point(atoms, params)
    config = caver_config.render_config(params, point)

    assert "starting_point_residue A:1 A:2" in config.splitlines()
    assert point.provenance["source"] == "group"
    assert params.get("start_residue_number") is None


def test_hetero_ligand_selection_reaches_the_residue_directive(server, runner) -> None:
    pdb_selection, caver_config = runner
    atoms = pdb_selection.parse_pdb(FIXTURE)
    params = _params(
        server,
        {
            "start_point_mode": "ligand",
            "start_chain": "B",
            "start_residue_number": 600,
            "start_residue_name": "CPZ",
        },
    )
    point = pdb_selection.resolve_start_point(atoms, params)
    config = caver_config.render_config(params, point)

    assert "starting_point_residue B:600" in config.splitlines()
    assert point.provenance["source"] == "ligand"
    assert point.provenance["residue_name"] == "CPZ"


def test_include_filters_render_alongside_excludes(server, runner) -> None:
    pdb_selection, caver_config = runner
    params = _params(
        server,
        {
            "start_point_mode": "residue",
            "start_chain": "A",
            "start_residue_number": 1,
            "include_residue_names": "ALA",
            "include_atom_numbers": "1-3",
            "exclude_residue_names": "HOH",
        },
    )
    point = pdb_selection.resolve_start_point(pdb_selection.parse_pdb(FIXTURE), params)
    config = caver_config.render_config(params, point).splitlines()
    assert "include_residue_names ALA" in config
    assert "include_atom_numbers 1-3" in config
    assert "exclude_residue_names HOH" in config
    assert config.index("include_residue_names ALA") < config.index("exclude_residue_names HOH")
