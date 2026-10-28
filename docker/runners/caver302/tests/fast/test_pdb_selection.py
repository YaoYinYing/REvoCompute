# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Selection-resolution behaviour of the CAVER Runner.

The fixture is a synthetic PDB with two chains, an insertion code, two alternate
locations and two HETATM residues. The tests assert only what the Runner owns:
that a typed selection resolves to the coordinates it names, and that ambiguous
or absent selections fail instead of guessing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / "docker/runners/caver302"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FAMILY))

from pdb_selection import (  # noqa: E402
    SelectionError,
    assert_snapshot_matches,
    parse_pdb,
    resolve_start_point,
)


def _atoms():
    return parse_pdb(FIXTURES / "selection.pdb")


def test_parse_pdb_keeps_altlocs_hetero_and_insertion_codes() -> None:
    atoms = _atoms()
    assert len(atoms) == 14
    assert [atom.altloc for atom in atoms if atom.name == "CB"] == ["A", "B"]
    assert any(atom.record == "HETATM" and atom.resname == "HEM" for atom in atoms)
    assert any(atom.resseq == 10 and atom.icode == "A" for atom in atoms)


def test_manual_point_accepts_inside_and_rejects_outside_or_non_finite() -> None:
    atoms = _atoms()
    point = resolve_start_point(atoms, {"start_point_mode": "point", "start_x": 4, "start_y": 4, "start_z": 4})
    assert point.provenance["point_angstrom"] == [4.0, 4.0, 4.0]
    assert point.directives == (("starting_point_coordinates", "4.000 4.000 4.000"),)

    with pytest.raises(SelectionError, match="outside the structure bounds"):
        resolve_start_point(atoms, {"start_point_mode": "point", "start_x": 500, "start_y": 4, "start_z": 4})
    with pytest.raises(SelectionError, match="finite"):
        resolve_start_point(
            atoms, {"start_point_mode": "point", "start_x": float("nan"), "start_y": 4, "start_z": 4}
        )


def test_selected_atom_uses_altloc_and_rejects_ambiguity() -> None:
    atoms = _atoms()
    selected = resolve_start_point(
        atoms,
        {
            "start_point_mode": "atom",
            "start_chain": "A",
            "start_residue_number": 1,
            "start_atom_name": "CB",
            "start_altloc": "B",
        },
    )
    assert selected.provenance["point_angstrom"] == [3.0, 2.0, 1.0]
    assert selected.directives == (("starting_point_atom", "4"),)

    with pytest.raises(SelectionError, match="several alternate locations"):
        resolve_start_point(
            atoms,
            {"start_point_mode": "atom", "start_chain": "A", "start_residue_number": 1, "start_atom_name": "CB"},
        )
    with pytest.raises(SelectionError, match="is absent from residue"):
        resolve_start_point(
            atoms,
            {"start_point_mode": "atom", "start_chain": "A", "start_residue_number": 1, "start_atom_name": "ZZ"},
        )


def test_residue_centroid_uses_highest_occupancy_conformer_and_insertion_code() -> None:
    atoms = _atoms()
    residue = resolve_start_point(
        atoms, {"start_point_mode": "residue", "start_chain": "A", "start_residue_number": 1}
    )
    assert residue.provenance["point_angstrom"] == [2.0, 1.0, 1.0]
    assert residue.provenance["atom_count"] == 3
    assert residue.directives == (("starting_point_residue", "A:1"),)

    insertion = resolve_start_point(
        atoms,
        {"start_point_mode": "residue", "start_chain": "A", "start_residue_number": 10, "start_insertion_code": "A"},
    )
    assert insertion.provenance["point_angstrom"] == [1.5, 3.0, 2.0]
    assert insertion.directives == (("starting_point_residue", "A:10A"),)


def test_residue_group_centroid_and_missing_residue() -> None:
    atoms = _atoms()
    group = resolve_start_point(atoms, {"start_point_mode": "group", "start_group": "A:1-2"})
    assert group.provenance["point_angstrom"] == [1.8, 1.4, 1.2]
    assert group.provenance["residue_count"] == 2
    assert group.directives == (("starting_point_residue", "A:1-2"),)

    with pytest.raises(SelectionError, match="absent from the structure"):
        resolve_start_point(atoms, {"start_point_mode": "group", "start_group": "A:1,B:9"})
    with pytest.raises(SelectionError, match="an insertion code is required"):
        resolve_start_point(atoms, {"start_point_mode": "group", "start_group": "A:10"})
    with pytest.raises(SelectionError, match="descending residue range"):
        resolve_start_point(atoms, {"start_point_mode": "group", "start_group": "A:5-1"})


def test_ligand_centroid_requires_one_matching_hetero_residue() -> None:
    atoms = _atoms()
    heme = resolve_start_point(
        atoms,
        {
            "start_point_mode": "ligand",
            "start_residue_name": "HEM",
            "start_chain": "A",
            "start_residue_number": 500,
        },
    )
    assert heme.provenance["point_angstrom"] == [4.25, 4.0, 4.0]
    assert heme.directives == (("starting_point_residue", "A:500"),)

    with pytest.raises(SelectionError, match="matches 2 HETATM residues"):
        resolve_start_point(atoms, {"start_point_mode": "ligand", "start_residue_name": "CPZ"})
    with pytest.raises(SelectionError, match="no HETATM residue"):
        resolve_start_point(atoms, {"start_point_mode": "ligand", "start_residue_name": "ZZZ"})


def test_unknown_start_mode_is_rejected() -> None:
    with pytest.raises(SelectionError, match="unknown start_point_mode"):
        resolve_start_point(_atoms(), {"start_point_mode": "pocket"})


def test_snapshot_topology_must_match_the_reference(tmp_path: Path) -> None:
    reference = _atoms()
    assert_snapshot_matches(reference, _atoms(), "same.pdb")
    truncated = tmp_path / "truncated.pdb"
    truncated.write_text(
        "\n".join((FIXTURES / "selection.pdb").read_text(encoding="utf-8").splitlines()[:-3]) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SelectionError, match="atoms but the reference structure"):
        assert_snapshot_matches(reference, parse_pdb(truncated), "truncated.pdb")
