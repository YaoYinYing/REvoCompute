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
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / "docker/runners/caver302"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FAMILY))

from pdb_selection import (  # noqa: E402
    SelectionError,
    altloc_policy,
    assert_snapshot_matches,
    difficult_conformations,
    parse_pdb,
    resolve_start_point,
    retained_atoms,
    validate_exclusions,
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


def test_selected_atom_honours_altloc_and_defaults_to_highest_occupancy() -> None:
    atoms = _atoms()
    # Empty altloc is documented as "highest occupancy", and that is what happens.
    default = resolve_start_point(
        atoms,
        {"start_point_mode": "atom", "start_chain": "A", "start_residue_number": 1, "start_atom_name": "CB"},
    )
    assert default.provenance["altloc"] == "A"
    assert default.provenance["atom_serial"] == 3
    assert default.directives == (("starting_point_atom", "3"),)

    # CAVER deletes conformation B, so selecting it must fail rather than
    # publish an origin CAVER never uses.
    with pytest.raises(SelectionError, match="removed by CAVER"):
        resolve_start_point(
            atoms,
            {
                "start_point_mode": "atom",
                "start_chain": "A",
                "start_residue_number": 1,
                "start_atom_name": "CB",
                "start_altloc": "B",
            },
        )

    with pytest.raises(SelectionError, match="is absent from residue"):
        resolve_start_point(
            atoms,
            {"start_point_mode": "atom", "start_chain": "A", "start_residue_number": 1, "start_atom_name": "ZZ"},
        )


def test_residue_centroid_uses_the_atoms_caver_retains() -> None:
    atoms = _atoms()
    residue = resolve_start_point(
        atoms, {"start_point_mode": "residue", "start_chain": "A", "start_residue_number": 1}
    )
    # CAVER removes conformation B before averaging, so only N, CA and CB(A) count.
    assert residue.provenance["point_angstrom"] == [2.0, 1.0, 1.0]
    assert residue.provenance["atom_count"] == 3
    assert residue.provenance["removed_altlocs"] == ["B"]
    assert residue.directives == (("starting_point_residue", "A:1"),)

    # An insertion-coded residue cannot be named by CAVER, so it is refused.
    with pytest.raises(SelectionError, match="insertion code"):
        resolve_start_point(
            atoms, {"start_point_mode": "residue", "start_chain": "A", "start_residue_number": 10}
        )


def test_residue_group_expands_ranges_into_individual_identifiers() -> None:
    atoms = _atoms()
    group = resolve_start_point(atoms, {"start_point_mode": "group", "start_group": "A:1-2"})
    # Mean of the two residue centres: A:1 = (2.0, 1.0, 1.0), A:2 = (1.5, 2.0, 1.5).
    assert group.provenance["point_angstrom"] == [1.75, 1.5, 1.25]
    assert group.provenance["residue_count"] == 2
    # Conformation B is removed from A:1, so five atoms are averaged.
    assert group.provenance["atom_count"] == 5
    # CAVER's start-point list has no range syntax, so the range is expanded.
    assert group.directives == (("starting_point_residue", "A:1 A:2"),)

    with pytest.raises(SelectionError, match="absent from the structure"):
        resolve_start_point(atoms, {"start_point_mode": "group", "start_group": "A:1,B:9"})
    with pytest.raises(SelectionError, match="insertion code"):
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


def test_empty_chain_resolves_to_the_first_chain_and_is_recorded() -> None:
    atoms = _atoms()
    resolved = resolve_start_point(atoms, {"start_point_mode": "residue", "start_residue_number": 1})
    assert resolved.provenance["chain"] == "A"
    assert resolved.provenance["chain_candidates"] == ["A", "B"]
    assert resolved.directives == (("starting_point_residue", "A:1"),)


def test_blank_chain_structure_uses_bare_identifiers() -> None:
    atoms = parse_pdb(FIXTURES / "blank_chain.pdb")
    resolved = resolve_start_point(atoms, {"start_point_mode": "residue", "start_residue_number": 2})
    assert resolved.provenance["chain"] == ""
    assert resolved.provenance["point_angstrom"] == [3.5, 2.0, 1.0]
    assert resolved.directives == (("starting_point_residue", "2"),)


def test_empty_chain_never_resolves_to_the_blank_chain_next_to_named_chains(tmp_path: Path) -> None:
    text = (FIXTURES / "selection.pdb").read_text(encoding="utf-8")
    blank = "ATOM      1    N ALA     9       7.000   7.000   7.000  1.00 20.00           N\n"
    mixed = tmp_path / "mixed.pdb"
    mixed.write_text(blank + text, encoding="utf-8")
    atoms = parse_pdb(mixed)
    # Residue 9 exists only in the blank chain while chain A/B are present;
    # CAVER would resolve a chainless identifier to a named chain.
    with pytest.raises(SelectionError, match="only in the blank chain"):
        resolve_start_point(atoms, {"start_point_mode": "residue", "start_residue_number": 9})
    # An explicitly named residue still resolves to that chain.
    resolved = resolve_start_point(atoms, {"start_point_mode": "residue", "start_residue_number": 1})
    assert resolved.provenance["chain"] == "A"


def test_equal_occupancy_keeps_the_highest_conformation_label() -> None:
    atoms = parse_pdb(FIXTURES / "tie.pdb")
    # CAVER kept conformation B on a 0.50/0.50 tie (verified in the SIF).
    kept = resolve_start_point(atoms, {"start_point_mode": "residue", "start_chain": "A", "start_residue_number": 9})
    assert kept.provenance["point_angstrom"] == [8 / 3, 1.0, 1.0]
    assert kept.provenance["removed_altlocs"] == ["A"]
    selected = resolve_start_point(
        atoms,
        {
            "start_point_mode": "atom",
            "start_chain": "A",
            "start_residue_number": 9,
            "start_atom_name": "CB",
            "start_altloc": "B",
        },
    )
    assert selected.provenance["point_angstrom"] == [5.0, 1.0, 1.0]
    # With start_altloc omitted the assistant must accept CAVER's conformer,
    # which is B on this 0.50/0.50 tie, not the first-listed A.
    default = resolve_start_point(
        atoms,
        {"start_point_mode": "atom", "start_chain": "A", "start_residue_number": 9, "start_atom_name": "CB"},
    )
    assert default.provenance["altloc"] == "B"
    assert default.provenance["point_angstrom"] == [5.0, 1.0, 1.0]
    with pytest.raises(SelectionError, match="keeps conformation B"):
        resolve_start_point(
            atoms,
            {
                "start_point_mode": "atom",
                "start_chain": "A",
                "start_residue_number": 9,
                "start_atom_name": "CB",
                "start_altloc": "A",
            },
        )


def test_equal_count_conformers_with_different_atoms_are_not_difficult() -> None:
    atoms = parse_pdb(FIXTURES / "equal_count.pdb")
    # CAVER compares per-conformer counts, so 1/1 is normal removal: B survives.
    assert difficult_conformations(atoms) is False
    assert len(retained_atoms(atoms, False)) == 3
    resolved = resolve_start_point(atoms, {"start_point_mode": "residue", "start_chain": "A", "start_residue_number": 9})
    assert resolved.provenance["point_angstrom"] == [8 / 3, 1.0, 1.0]
    assert resolved.provenance["removed_altlocs"] == ["A"]


def test_conformers_with_different_atom_counts_keep_every_atom() -> None:
    atoms = parse_pdb(FIXTURES / "difficult.pdb")
    # 2 atoms in A against 1 in B is CAVER's difficult case: nothing is removed.
    assert difficult_conformations(atoms) is True
    assert len(retained_atoms(atoms, True)) == 5
    assert altloc_policy(True).startswith("difficult case")
    resolved = resolve_start_point(atoms, {"start_point_mode": "residue", "start_chain": "A", "start_residue_number": 9})
    assert resolved.provenance["point_angstrom"] == [17 / 5, 1.0, 1.0]
    assert resolved.provenance["removed_altlocs"] == []


def test_difficult_residue_outside_the_selection_changes_the_whole_file(tmp_path: Path) -> None:
    text = (FIXTURES / "selection.pdb").read_text(encoding="utf-8")
    difficult = (FIXTURES / "difficult.pdb").read_text(encoding="utf-8")
    hard = [line for line in difficult.splitlines() if line.startswith("ATOM") and " A   9" in line]
    mixed = tmp_path / "hard_elsewhere.pdb"
    mixed.write_text("\n".join(hard) + "\n" + text, encoding="utf-8")
    atoms = parse_pdb(mixed)
    assert difficult_conformations(atoms) is True
    # Residue A:1 has altlocs A/B; a difficult residue elsewhere keeps both.
    resolved = resolve_start_point(atoms, {"start_point_mode": "residue", "start_chain": "A", "start_residue_number": 1})
    assert resolved.provenance["atom_count"] == 4
    assert resolved.provenance["removed_altlocs"] == []
    assert resolved.provenance["point_angstrom"] == [2.25, 1.25, 1.0]


def test_blank_occupancy_is_unknown_not_one() -> None:
    for atom in parse_pdb(FIXTURES / "tie.pdb"):
        assert atom.occupancy is not None
    blank = (
        "ATOM      1    N ALA A   9       1.000   1.000   1.000  1.00 20.00           N\n"
        "ATOM      2   CA ALA A   9       2.000   1.000   1.000         20.00           C\n"
    )
    path = Path(tempfile.mkdtemp()) / "blank_occ.pdb"
    path.write_text(blank + "END\n", encoding="utf-8")
    assert [atom.occupancy for atom in parse_pdb(path)] == [1.0, None]


def test_group_blank_chain_marker_is_explicit() -> None:
    atoms = parse_pdb(FIXTURES / "blank_chain.pdb")
    group = resolve_start_point(atoms, {"start_point_mode": "group", "start_group": "_:1-2"})
    assert group.directives == (("starting_point_residue", "1 2"),)
    assert group.provenance["point_angstrom"] == [2.5, 1.5, 1.0]

    text = (FIXTURES / "selection.pdb").read_text(encoding="utf-8")
    blank = "ATOM      1    N ALA     9       7.000   7.000   7.000  1.00 20.00           N\n"
    path = Path(tempfile.mkdtemp()) / "mixed.pdb"
    path.write_text(blank + text, encoding="utf-8")
    mixed_atoms = parse_pdb(path)
    with pytest.raises(SelectionError, match="blank chain"):
        resolve_start_point(mixed_atoms, {"start_point_mode": "group", "start_group": "_:9"})
    # A named chain in the same structure still resolves normally.
    named = resolve_start_point(mixed_atoms, {"start_point_mode": "group", "start_group": "B:1"})
    assert named.directives == (("starting_point_residue", "B:1"),)


def test_group_removed_altlocs_carry_the_residue_identity() -> None:
    atoms = _atoms()
    group = resolve_start_point(atoms, {"start_point_mode": "group", "start_group": "A:1-2"})
    assert group.provenance["removed_altlocs"] == ["A:1:B"]


def test_multi_model_pdb_is_rejected(tmp_path: Path) -> None:
    text = (FIXTURES / "blank_chain.pdb").read_text(encoding="utf-8")
    body = text.replace("TER\nEND", "")
    multi = tmp_path / "multi.pdb"
    multi.write_text(f"MODEL        1\n{body}ENDMDL\nMODEL        2\n{body}ENDMDL\nEND\n", encoding="utf-8")
    with pytest.raises(SelectionError, match="several models"):
        parse_pdb(multi)


def test_exclusions_are_validated_against_the_structure() -> None:
    atoms = _atoms()
    validate_exclusions(
        {"exclude_residue_ids": "A:1 B:1", "exclude_residue_names": "CPZ", "exclude_atom_numbers": "1-3 14"},
        atoms,
    )
    with pytest.raises(SelectionError, match="absent from the structure"):
        validate_exclusions({"exclude_residue_ids": "A:99"}, atoms)
    with pytest.raises(SelectionError, match="absent from the structure"):
        validate_exclusions({"exclude_residue_names": "ZZZ"}, atoms)
    with pytest.raises(SelectionError, match="matches no atom serial"):
        validate_exclusions({"exclude_atom_numbers": "900-999"}, atoms)
    with pytest.raises(SelectionError, match="insertion code"):
        validate_exclusions({"exclude_residue_ids": "A:10A"}, atoms)


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
