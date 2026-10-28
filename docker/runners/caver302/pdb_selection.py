# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Resolve a typed CAVER start point against one PDB structure.

CAVER needs a single point inside the protein from which tunnel exploration
starts. The Task exposes that point as typed controls (manual Angstrom
coordinates, one atom, one residue centroid, a residue group centroid, or a
ligand/cofactor centroid); this module turns those controls into the exact
coordinates CAVER receives and records how they were derived.

Only PDB is parsed here. Parsing is deliberately strict: a coordinate that is
not in the file, a residue number that matches several chains, or an atom name
that matches several alternate locations is an error, never a guess.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

#: A manual point may sit outside the deposited coordinates by at most this
#: margin. CAVER explores outward from a point inside the structure, so a
#: typo of one digit (hundreds of Angstroms away) must fail here instead of
#: silently producing zero tunnels.
POINT_BOUND_MARGIN_ANGSTROM = 10.0

#: Upper bound on residues one ``group`` selection may name, so a malformed
#: range cannot turn into a whole-structure centroid.
MAX_GROUP_RESIDUES = 1000

_GROUP_TERM = re.compile(r"^(?P<chain>[A-Za-z0-9_]):(?P<start>[0-9]+)(?:-(?P<end>[0-9]+))?$")


class SelectionError(ValueError):
    """The typed start-point controls do not identify one point in the structure."""


@dataclass(frozen=True)
class Atom:
    """One ATOM/HETATM coordinate record."""

    serial: int
    name: str
    altloc: str
    resname: str
    chain: str
    resseq: int
    icode: str
    x: float
    y: float
    z: float
    occupancy: float
    record: str

    @property
    def residue(self) -> tuple[str, int, str]:
        return (self.chain, self.resseq, self.icode)

    @property
    def identity(self) -> tuple[str, int, str, str]:
        """Topology identity, ignoring alternate-location labels."""
        return (self.chain, self.resseq, self.icode, self.name)


@dataclass(frozen=True)
class StartPoint:
    """The resolved CAVER start point and how it was produced.

    ``directives`` are the upstream ``starting_point_*`` config lines that
    reproduce this selection, so CAVER follows the selected atom or residue
    through a snapshot series instead of being pinned to the reference frame's
    coordinates.
    """

    x: float
    y: float
    z: float
    provenance: dict[str, object]
    directives: tuple[tuple[str, str], ...] = ()

    def as_config_value(self) -> str:
        return f"{self.x:.3f} {self.y:.3f} {self.z:.3f}"


def residue_identifier(chain: str, number: int, icode: str = "") -> str:
    """Render one upstream ``starting_point_residue`` / ``exclude_residue_ids`` identifier."""
    prefix = f"{chain}:" if chain else ""
    return f"{prefix}{number}{icode}"


def parse_pdb(path: Path) -> list[Atom]:
    """Parse the first model of a PDB file into coordinate records."""
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise SelectionError(f"cannot read structure {path.name}: {exc}") from exc
    atoms: list[Atom] = []
    in_model = False
    saw_model = False
    for line in lines:
        record = line[:6]
        if record.startswith("MODEL"):
            if saw_model:
                break
            saw_model = True
            in_model = True
            continue
        if record.startswith("ENDMDL"):
            break
        if not (record.startswith("ATOM") or record.startswith("HETATM")):
            continue
        if len(line) < 54:
            raise SelectionError(f"structure {path.name} contains a truncated coordinate record")
        try:
            atoms.append(
                Atom(
                    serial=int(line[6:11]),
                    name=line[12:16].strip(),
                    altloc=line[16:17].strip(),
                    resname=line[17:20].strip(),
                    chain=line[21:22].strip(),
                    resseq=int(line[22:26]),
                    icode=line[26:27].strip(),
                    x=float(line[30:38]),
                    y=float(line[38:46]),
                    z=float(line[46:54]),
                    occupancy=float(line[54:60]) if line[54:60].strip() else 1.0,
                    record=record.strip(),
                )
            )
        except ValueError as exc:
            raise SelectionError(f"structure {path.name} contains a malformed coordinate record") from exc
    if not atoms:
        raise SelectionError(f"structure {path.name} contains no ATOM or HETATM records")
    return atoms


def structure_bounds(atoms: list[Atom], margin: float = POINT_BOUND_MARGIN_ANGSTROM) -> tuple[float, float, float, float, float, float]:
    """Return the coordinate bounding box expanded by ``margin`` Angstrom."""
    return (
        min(atom.x for atom in atoms) - margin,
        min(atom.y for atom in atoms) - margin,
        min(atom.z for atom in atoms) - margin,
        max(atom.x for atom in atoms) + margin,
        max(atom.y for atom in atoms) + margin,
        max(atom.z for atom in atoms) + margin,
    )


def atom_topology(atoms: list[Atom]) -> list[tuple[str, int, str, str]]:
    """Sorted topology identity of every atom, ignoring alternate locations."""
    return sorted(atom.identity for atom in atoms)


def assert_snapshot_matches(reference: list[Atom], snapshot: list[Atom], name: str) -> None:
    """Reject a snapshot whose atom/residue mapping differs from the reference."""
    if len(reference) != len(snapshot):
        raise SelectionError(
            f"snapshot {name} has {len(snapshot)} atoms but the reference structure has {len(reference)}"
        )
    if atom_topology(reference) != atom_topology(snapshot):
        raise SelectionError(f"snapshot {name} does not share the reference structure's atom/residue mapping")


def _unique_atoms(atoms: list[Atom]) -> list[Atom]:
    """Keep one alternate location per residue atom, highest occupancy first."""
    chosen: dict[tuple[tuple[str, int, str], str], Atom] = {}
    for atom in atoms:
        key = (atom.residue, atom.name)
        current = chosen.get(key)
        if current is None:
            chosen[key] = atom
            continue
        best = max((current, atom), key=lambda item: (item.occupancy, item.altloc == "", -item.serial))
        chosen[key] = best
    return list(chosen.values())


def _centroid(atoms: list[Atom]) -> tuple[float, float, float]:
    kept = _unique_atoms(atoms)
    if not kept:
        raise SelectionError("selection resolved to no atoms")
    return (
        sum(atom.x for atom in kept) / len(kept),
        sum(atom.y for atom in kept) / len(kept),
        sum(atom.z for atom in kept) / len(kept),
    )


def _residues(atoms: list[Atom]) -> dict[tuple[str, int, str], list[Atom]]:
    residues: dict[tuple[str, int, str], list[Atom]] = {}
    for atom in atoms:
        residues.setdefault(atom.residue, []).append(atom)
    return residues


def _selection_fields(params: dict[str, object]) -> dict[str, object]:
    fields = (
        "start_chain",
        "start_residue_number",
        "start_insertion_code",
        "start_atom_name",
        "start_altloc",
        "start_residue_name",
        "start_group",
    )
    return {name: params.get(name) for name in fields if params.get(name) not in (None, "")}


def _manual_point(params: dict[str, object], atoms: list[Atom]) -> StartPoint:
    coordinates: list[float] = []
    for axis in ("start_x", "start_y", "start_z"):
        value = params.get(axis)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise SelectionError(f"{axis} must be a finite number in Angstrom")
        coordinates.append(float(value))
    x, y, z = coordinates
    x0, y0, z0, x1, y1, z1 = structure_bounds(atoms)
    if not (x0 <= x <= x1 and y0 <= y <= y1 and z0 <= z <= z1):
        raise SelectionError(
            f"start point ({x:.3f}, {y:.3f}, {z:.3f}) lies outside the structure bounds "
            f"({x0:.3f}..{x1:.3f}, {y0:.3f}..{y1:.3f}, {z0:.3f}..{z1:.3f})"
        )
    return StartPoint(
        x,
        y,
        z,
        {
            "mode": "point",
            "point_angstrom": [x, y, z],
            "units": "angstrom",
            "bounds_angstrom": [x0, y0, z0, x1, y1, z1],
        },
        (("starting_point_coordinates", f"{x:.3f} {y:.3f} {z:.3f}"),),
    )


def _single_atom(params: dict[str, object], atoms: list[Atom]) -> StartPoint:
    chain = str(params.get("start_chain") or "")
    number = params.get("start_residue_number")
    icode = str(params.get("start_insertion_code") or "")
    atom_name = str(params.get("start_atom_name") or "")
    altloc = str(params.get("start_altloc") or "")
    if not isinstance(number, int) or isinstance(number, bool):
        raise SelectionError("start_residue_number is required when the start point is a selected atom")
    if not atom_name:
        raise SelectionError("start_atom_name is required when the start point is a selected atom")
    residue_atoms = _residues(atoms).get((chain, number, icode))
    if residue_atoms is None:
        raise SelectionError(f"residue {chain or '_'}:{number}{icode} is absent from the structure")
    matches = [atom for atom in residue_atoms if atom.name == atom_name and (not altloc or atom.altloc == altloc)]
    if not matches:
        available = ", ".join(sorted({atom.name for atom in residue_atoms}))
        raise SelectionError(
            f"atom {atom_name!r} is absent from residue {chain or '_'}:{number}{icode}; available atoms: {available}"
        )
    if len({(atom.altloc, atom.serial) for atom in matches}) > 1 and not altloc:
        altlocs = ", ".join(sorted({atom.altloc or "<blank>" for atom in matches}))
        raise SelectionError(f"atom {atom_name!r} has several alternate locations ({altlocs}); set start_altloc")
    atom = max(matches, key=lambda item: (item.occupancy, -item.serial))
    return StartPoint(
        atom.x,
        atom.y,
        atom.z,
        {
            "mode": "atom",
            "point_angstrom": [atom.x, atom.y, atom.z],
            "units": "angstrom",
            "chain": atom.chain,
            "residue_number": atom.resseq,
            "insertion_code": atom.icode,
            "residue_name": atom.resname,
            "atom_name": atom.name,
            "altloc": atom.altloc,
            "atom_serial": atom.serial,
            "atom_count": 1,
        },
        (("starting_point_atom", str(atom.serial)),),
    )


def _residue_centroid(params: dict[str, object], atoms: list[Atom]) -> StartPoint:
    chain = str(params.get("start_chain") or "")
    number = params.get("start_residue_number")
    icode = str(params.get("start_insertion_code") or "")
    if not isinstance(number, int) or isinstance(number, bool):
        raise SelectionError("start_residue_number is required when the start point is a residue centroid")
    residue_atoms = _residues(atoms).get((chain, number, icode))
    if residue_atoms is None:
        raise SelectionError(f"residue {chain or '_'}:{number}{icode} is absent from the structure")
    x, y, z = _centroid(residue_atoms)
    return StartPoint(
        x,
        y,
        z,
        {
            "mode": "residue",
            "point_angstrom": [x, y, z],
            "units": "angstrom",
            "chain": chain,
            "residue_number": number,
            "insertion_code": icode,
            "residue_name": residue_atoms[0].resname,
            "atom_count": len(_unique_atoms(residue_atoms)),
            "residue_count": 1,
            "altloc_policy": "highest-occupancy conformer per atom name",
        },
        (("starting_point_residue", residue_identifier(chain, number, icode)),),
    )


def _ligand_centroid(params: dict[str, object], atoms: list[Atom]) -> StartPoint:
    resname = str(params.get("start_residue_name") or "").strip()
    if not resname:
        raise SelectionError("start_residue_name is required when the start point is a ligand or cofactor centre")
    chain = params.get("start_chain")
    number = params.get("start_residue_number")
    icode = str(params.get("start_insertion_code") or "")
    matched: dict[tuple[str, int, str], list[Atom]] = {}
    for atom in atoms:
        if atom.record != "HETATM" or atom.resname != resname:
            continue
        if chain not in (None, "") and atom.chain != chain:
            continue
        if isinstance(number, int) and not isinstance(number, bool) and atom.resseq != number:
            continue
        matched.setdefault(atom.residue, []).append(atom)
    if not matched:
        raise SelectionError(f"no HETATM residue named {resname!r} matches the ligand/cofactor selection")
    if len(matched) > 1:
        candidates = ", ".join(
            f"{key[0] or '_'}:{key[1]}{key[2]}" for key in sorted(matched)[:10]
        )
        raise SelectionError(
            f"{resname!r} matches {len(matched)} HETATM residues ({candidates}); "
            "set start_chain and start_residue_number"
        )
    ((residue_chain, residue_number, residue_icode), residue_atoms) = next(iter(matched.items()))
    x, y, z = _centroid(residue_atoms)
    return StartPoint(
        x,
        y,
        z,
        {
            "mode": "ligand",
            "point_angstrom": [x, y, z],
            "units": "angstrom",
            "chain": residue_chain,
            "residue_number": residue_number,
            "insertion_code": residue_icode,
            "residue_name": resname,
            "atom_count": len(_unique_atoms(residue_atoms)),
            "residue_count": 1,
            "altloc_policy": "highest-occupancy conformer per atom name",
        },
        (("starting_point_residue", residue_identifier(residue_chain, residue_number, residue_icode)),),
    )


def _parse_group(spec: str) -> list[tuple[str, int, int]]:
    """Parse ``CHAIN:START[-END]`` terms into (chain, first, last) residue ranges."""
    terms = [term.strip() for term in spec.split(",") if term.strip()]
    if not terms:
        raise SelectionError("start_group must name at least one chain:residue term")
    ranges: list[tuple[str, int, int]] = []
    total = 0
    for term in terms:
        match = _GROUP_TERM.fullmatch(term)
        if not match:
            raise SelectionError(f"start_group term {term!r} is not CHAIN:RESIDUE or CHAIN:START-END")
        chain = "" if match.group("chain") == "_" else match.group("chain")
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        if end < start:
            raise SelectionError(f"start_group term {term!r} has a descending residue range")
        total += end - start + 1
        ranges.append((chain, start, end))
    if total > MAX_GROUP_RESIDUES:
        raise SelectionError(f"start_group names {total} residues; the limit is {MAX_GROUP_RESIDUES}")
    return ranges


def _group_directive(ranges: list[tuple[str, int, int]]) -> str:
    terms = []
    for chain, start, end in ranges:
        identifier = residue_identifier(chain, start)
        terms.append(f"{identifier}-{end}" if end != start else identifier)
    return " ".join(terms)


def _group_centroid(params: dict[str, object], atoms: list[Atom]) -> StartPoint:
    spec = str(params.get("start_group") or "").strip()
    if not spec:
        raise SelectionError("start_group is required when the start point is a residue-group centroid")
    ranges = _parse_group(spec)
    by_key = _residues(atoms)
    selected: list[Atom] = []
    missing: list[str] = []
    for chain, start, end in ranges:
        for number in range(start, end + 1):
            residue_atoms = by_key.get((chain, number, ""))
            if residue_atoms is None:
                alternatives = sorted(key[2] for key in by_key if key[0] == chain and key[1] == number)
                if alternatives:
                    missing.append(f"{chain or '_'}:{number} (an insertion code is required)")
                else:
                    missing.append(f"{chain or '_'}:{number}")
                continue
            selected.extend(residue_atoms)
    if missing:
        raise SelectionError(f"start_group residues are absent from the structure: {', '.join(missing[:10])}")
    x, y, z = _centroid(selected)
    residue_count = len({atom.residue for atom in selected})
    return StartPoint(
        x,
        y,
        z,
        {
            "mode": "group",
            "point_angstrom": [x, y, z],
            "units": "angstrom",
            "group": spec,
            "residue_count": residue_count,
            "atom_count": len(_unique_atoms(selected)),
            "altloc_policy": "highest-occupancy conformer per atom name",
        },
        (("starting_point_residue", _group_directive(ranges)),),
    )


_RESOLVERS = {
    "point": _manual_point,
    "atom": _single_atom,
    "residue": _residue_centroid,
    "group": _group_centroid,
    "ligand": _ligand_centroid,
}


def resolve_start_point(atoms: list[Atom], params: dict[str, object]) -> StartPoint:
    """Resolve the typed start-point controls against parsed structure atoms."""
    mode = params.get("start_point_mode")
    resolver = _RESOLVERS.get(str(mode))
    if resolver is None:
        raise SelectionError(f"unknown start_point_mode {mode!r}; expected one of {', '.join(_RESOLVERS)}")
    point = resolver(params, atoms)
    point.provenance["parameters"] = _selection_fields(params)
    return point
