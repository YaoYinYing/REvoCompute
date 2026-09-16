# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Small-molecule format parsers used at the Server input boundary."""

from __future__ import annotations

import math

from revocompute.input_validators.common import _read_text

MAX_SDF_MOLECULES = 100_000
MAX_SMALL_MOLECULE_ATOMS = 1_000_000
MAX_SMALL_MOLECULE_RECORD_LENGTH = 100_000


def _record_limit_error(text: str, kind: str) -> str | None:
    if any(len(line) > MAX_SMALL_MOLECULE_RECORD_LENGTH for line in text.splitlines()):
        return f"{kind} file contains a record longer than {MAX_SMALL_MOLECULE_RECORD_LENGTH} characters"
    return None


def _coordinates_are_finite(values) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def validate_sdf(path: str) -> str | None:
    text, error = _read_text(path, kind="SDF")
    if error:
        return error
    if error := _record_limit_error(text, "SDF"):
        return error
    chunks = text.split("$$$$")
    if chunks[-1].strip():
        return "SDF molecule record is missing its $$$$ terminator"
    records = chunks[:-1]
    if not records or any(not record.strip() for record in records):
        return "SDF file contains no molecule records"
    if len(records) > MAX_SDF_MOLECULES:
        return f"SDF file contains more than {MAX_SDF_MOLECULES} molecule records"
    total_atoms = 0
    for record in records:
        lines = record.splitlines()
        if len(lines) < 4:
            return "SDF molecule record is missing its counts line"
        if lines[3].rstrip().endswith("V3000"):
            error = _validate_v3000_record(lines)
            if error:
                return error
            counts = next(line.split() for line in lines[4:] if line.startswith("M  V30 COUNTS "))
            total_atoms += int(counts[3])
            if total_atoms > MAX_SMALL_MOLECULE_ATOMS:
                return f"SDF file contains more than {MAX_SMALL_MOLECULE_ATOMS} atoms"
            continue
        try:
            atom_count = int(lines[3][:3])
        except ValueError:
            return "SDF molecule record has an invalid atom count"
        if atom_count < 1 or len(lines) < 4 + atom_count or "M  END" not in lines:
            return "SDF molecule record is incomplete"
        total_atoms += atom_count
        if total_atoms > MAX_SMALL_MOLECULE_ATOMS:
            return f"SDF file contains more than {MAX_SMALL_MOLECULE_ATOMS} atoms"
        for line in lines[4 : 4 + atom_count]:
            try:
                if not _coordinates_are_finite((line[:10], line[10:20], line[20:30])):
                    return "SDF atom coordinates must be finite numbers"
            except ValueError:
                return "SDF atom has invalid coordinates"
    return None


def _validate_v3000_record(lines: list[str]) -> str | None:
    counts = next((line.split() for line in lines[4:] if line.startswith("M  V30 COUNTS ")), None)
    if counts is None or len(counts) < 5:
        return "SDF V3000 molecule record has an invalid counts line"
    try:
        atom_count = int(counts[3])
    except ValueError:
        return "SDF V3000 molecule record has an invalid atom count"
    try:
        atom_start = lines.index("M  V30 BEGIN ATOM") + 1
        atom_end = lines.index("M  V30 END ATOM", atom_start)
    except ValueError:
        return "SDF V3000 molecule record is missing its atom block"
    atoms = [line.split() for line in lines[atom_start:atom_end] if line.startswith("M  V30 ")]
    if atom_count < 1 or len(atoms) != atom_count or "M  END" not in lines:
        return "SDF V3000 molecule record is incomplete"
    try:
        for atom in atoms:
            if len(atom) < 7 or int(atom[2]) < 1 or not atom[3]:
                return "SDF V3000 atom record is incomplete"
            if not _coordinates_are_finite(atom[4:7]):
                return "SDF V3000 atom coordinates must be finite numbers"
    except ValueError:
        return "SDF V3000 atom has invalid coordinates"
    return None


def validate_mol2(path: str) -> str | None:
    text, error = _read_text(path, kind="MOL2")
    if error:
        return error
    if error := _record_limit_error(text, "MOL2"):
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
    if len(atoms) > MAX_SMALL_MOLECULE_ATOMS:
        return f"MOL2 file contains more than {MAX_SMALL_MOLECULE_ATOMS} atoms"
    if any(len(atom) < 6 for atom in atoms):
        return "MOL2 atom record is incomplete"
    try:
        for atom in atoms:
            if not _coordinates_are_finite(atom[2:5]):
                return "MOL2 atom coordinates must be finite numbers"
    except ValueError:
        return "MOL2 atom has invalid coordinates"
    return None


def validate_pdbqt(path: str) -> str | None:
    text, error = _read_text(path, kind="PDBQT")
    if error:
        return error
    if error := _record_limit_error(text, "PDBQT"):
        return error
    atoms = [line for line in text.splitlines() if line.startswith(("ATOM  ", "HETATM"))]
    if not atoms:
        return "PDBQT file contains no atoms"
    if len(atoms) > MAX_SMALL_MOLECULE_ATOMS:
        return f"PDBQT file contains more than {MAX_SMALL_MOLECULE_ATOMS} atoms"
    try:
        for atom in atoms:
            if not _coordinates_are_finite((atom[30:38], atom[38:46], atom[46:54])):
                return "PDBQT atom coordinates must be finite numbers"
    except ValueError:
        return "PDBQT atom has invalid coordinates"
    return None
