# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from revocompute.input_validators import small_molecule, validate_input_file


def test_small_molecule_formats_are_parsed(tmp_path):
    malformed = tmp_path / "ligand.sdf"
    malformed.write_text("this is not an SDF\n", encoding="utf-8")
    assert validate_input_file(str(malformed), malformed.name)

    mol2 = tmp_path / "ligand.mol2"
    mol2.write_text("@<TRIPOS>MOLECULE\nligand\n1 0\n@<TRIPOS>ATOM\n1 C1 1.0 2.0 3.0 C\n", encoding="utf-8")
    assert validate_input_file(str(mol2), mol2.name) is None

    pdbqt = tmp_path / "ligand.pdbqt"
    pdbqt.write_text("HETATM    1  C1  LIG A   1       1.000   2.000   3.000  0.00  0.00    0.000 C\n")
    assert validate_input_file(str(pdbqt), pdbqt.name) is None


def test_sdf_v3000_molecule_is_parsed(tmp_path):
    sdf = tmp_path / "ligand.sdf"
    sdf.write_text(
        "ligand\n"
        "  REvoCompute\n"
        "\n"
        "  0  0  0     0  0            999 V3000\n"
        "M  V30 BEGIN CTAB\n"
        "M  V30 COUNTS 2 1 0 0 0\n"
        "M  V30 BEGIN ATOM\n"
        "M  V30 1 C 0.0 0.0 0.0 0\n"
        "M  V30 2 O 1.2 0.0 0.0 0\n"
        "M  V30 END ATOM\n"
        "M  V30 BEGIN BOND\n"
        "M  V30 1 1 1 2\n"
        "M  V30 END BOND\n"
        "M  V30 END CTAB\n"
        "M  END\n"
        "$$$$\n",
        encoding="utf-8",
    )

    assert validate_input_file(str(sdf), sdf.name) is None


def test_sdf_v3000_rejects_incomplete_atom_block(tmp_path):
    sdf = tmp_path / "ligand.sdf"
    sdf.write_text(
        "ligand\n  REvoCompute\n\n  0  0  0     0  0            999 V3000\n"
        "M  V30 BEGIN CTAB\nM  V30 COUNTS 2 0 0 0 0\nM  V30 BEGIN ATOM\n"
        "M  V30 1 C 0.0 0.0 0.0 0\nM  V30 END ATOM\nM  V30 END CTAB\nM  END\n$$$$\n",
        encoding="utf-8",
    )

    assert validate_input_file(str(sdf), sdf.name) == "SDF V3000 molecule record is incomplete"


def test_sdf_rejects_excessive_molecule_count(monkeypatch, tmp_path):
    monkeypatch.setattr(small_molecule, "MAX_SDF_MOLECULES", 2)
    sdf = tmp_path / "ligands.sdf"
    sdf.write_text("ligand\nserver\n\n  1  0\n    0.0       0.0       0.0 C\nM  END\n$$$$\n" * 3)

    assert "more than 2 molecule records" in validate_input_file(str(sdf), sdf.name)


def test_small_molecule_formats_reject_non_finite_coordinates(tmp_path):
    mol2 = tmp_path / "ligand.mol2"
    mol2.write_text("@<TRIPOS>MOLECULE\nligand\n1 0\n@<TRIPOS>ATOM\n1 C1 nan 2.0 3.0 C\n")
    pdbqt = tmp_path / "ligand.pdbqt"
    pdbqt.write_text("HETATM    1  C1  LIG A   1         nan   2.000   3.000  0.00  0.00    0.000 C\n")

    assert "finite" in validate_input_file(str(mol2), mol2.name)
    assert "finite" in validate_input_file(str(pdbqt), pdbqt.name)


def test_small_molecule_atom_and_record_limits(monkeypatch, tmp_path):
    monkeypatch.setattr(small_molecule, "MAX_SMALL_MOLECULE_ATOMS", 1)
    mol2 = tmp_path / "ligand.mol2"
    mol2.write_text(
        "@<TRIPOS>MOLECULE\nligand\n2 0\n@<TRIPOS>ATOM\n"
        "1 C1 1.0 2.0 3.0 C\n2 C2 2.0 3.0 4.0 C\n"
    )
    assert "more than 1 atoms" in validate_input_file(str(mol2), mol2.name)

    monkeypatch.setattr(small_molecule, "MAX_SMALL_MOLECULE_RECORD_LENGTH", 20)
    pdbqt = tmp_path / "ligand.pdbqt"
    pdbqt.write_text("HETATM " + "X" * 30 + "\n")
    assert "record longer than 20" in validate_input_file(str(pdbqt), pdbqt.name)
