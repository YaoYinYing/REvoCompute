# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Small-molecule format parsers used at the Server input boundary."""

from __future__ import annotations

from revocompute.input_validators.common import _read_text


def validate_sdf(path: str) -> str | None:
    text, error = _read_text(path, kind="SDF")
    if error:
        return error
    records = [record for record in text.split("$$$$") if record.strip()]
    if not records:
        return "SDF file contains no molecule records"
    for record in records:
        lines = record.splitlines()
        if len(lines) < 4:
            return "SDF molecule record is missing its counts line"
        try:
            atom_count = int(lines[3][:3])
        except ValueError:
            return "SDF molecule record has an invalid atom count"
        if atom_count < 1 or len(lines) < 4 + atom_count or "M  END" not in lines:
            return "SDF molecule record is incomplete"
        for line in lines[4 : 4 + atom_count]:
            try:
                tuple(float(value) for value in (line[:10], line[10:20], line[20:30]))
            except ValueError:
                return "SDF atom has invalid coordinates"
    return None


def validate_mol2(path: str) -> str | None:
    text, error = _read_text(path, kind="MOL2")
    if error:
        return error
    lines = text.splitlines()
    try:
        start = lines.index("@<TRIPOS>ATOM") + 1
    except ValueError:
        return "MOL2 file must contain an ATOM section"
    atoms = []
    for line in lines[start:]:
        if line.startswith("@<TRIPOS>"):
            break
        if line.strip():
            atoms.append(line.split())
    if not atoms:
        return "MOL2 file contains no atoms"
    if any(len(atom) < 6 for atom in atoms):
        return "MOL2 atom record is incomplete"
    try:
        for atom in atoms:
            tuple(float(value) for value in atom[2:5])
    except ValueError:
        return "MOL2 atom has invalid coordinates"
    return None


def validate_pdbqt(path: str) -> str | None:
    text, error = _read_text(path, kind="PDBQT")
    if error:
        return error
    atoms = [line for line in text.splitlines() if line.startswith(("ATOM  ", "HETATM"))]
    if not atoms:
        return "PDBQT file contains no atoms"
    try:
        for atom in atoms:
            tuple(float(value) for value in (atom[30:38], atom[38:46], atom[46:54]))
    except ValueError:
        return "PDBQT atom has invalid coordinates"
    return None
