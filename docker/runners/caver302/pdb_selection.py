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
_RESIDUE_TOKEN = re.compile(r"^(?:(?P<chain>[A-Za-z0-9]):)?(?P<number>[0-9]+)(?P<icode>[A-Za-z])?$")
_ATOM_TOKEN = re.compile(r"^(?P<first>[0-9]+)(?:-(?P<last>[0-9]+))?$")


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


def residue_identifier(chain: str, number: int) -> str:
    """Render one upstream ``starting_point_residue`` / ``exclude_residue_ids`` identifier."""
    prefix = f"{chain}:" if chain else ""
    return f"{prefix}{number}"


def parse_pdb(path: Path) -> list[Atom]:
    """Parse a single-model PDB file into coordinate records.

    CAVER itself reads only one structure per file, and a multi-model file
    would silently contribute its first model while a multi-model CIF is
    rejected, so both are refused here instead of being half-read.
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise SelectionError(f"cannot read structure {path.name}: {exc}") from exc
    atoms: list[Atom] = []
    saw_model = False
    for line in lines:
        record = line[:6]
        if record.startswith("MODEL"):
            if saw_model:
                raise SelectionError(
                    f"structure {path.name} contains several models; provide one model per PDB file"
                )
            saw_model = True
            continue
        if record.startswith("ENDMDL"):
            continue
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


def _centroid(atoms: list[Atom]) -> tuple[float, float, float]:
    """Arithmetic mean over every coordinate record of the selection.

    CAVER places the initial start point at the centre of gravity of the
    selected residues, computed over the atoms it reads from the file, so all
    alternate locations and hydrogens contribute. Averaging a deduplicated
    conformer set here would publish a point CAVER never uses.
    """
    if not atoms:
        raise SelectionError("selection resolved to no atoms")
    return (
        sum(atom.x for atom in atoms) / len(atoms),
        sum(atom.y for atom in atoms) / len(atoms),
        sum(atom.z for atom in atoms) / len(atoms),
    )


def _residues(atoms: list[Atom]) -> dict[tuple[str, int, str], list[Atom]]:
    residues: dict[tuple[str, int, str], list[Atom]] = {}
    for atom in atoms:
        residues.setdefault(atom.residue, []).append(atom)
    return residues


def _insertion_code_error(chain: str, number: int) -> SelectionError:
    label = f"{chain or '_'}:{number}"
    return SelectionError(
        f"residue {label} is only present with an insertion code; CAVER cannot address insertion-coded "
        "residues, so it cannot be selected"
    )


def _resolve_residue(
    by_key: dict[tuple[str, int, str], list[Atom]], chain: str, number: int
) -> tuple[tuple[str, int, str], list[Atom], dict[str, object]]:
    """Find one residue, mirroring CAVER's chain rules and refusing insertion codes.

    With an explicit chain the residue must exist as written. An empty chain
    follows the upstream rule: the identifier is taken to belong to the first
    chain, so the first chain in file order that contains the residue wins and
    is recorded. The caller always emits that resolved chain, so CAVER cannot
    start somewhere other than the point recorded in provenance.
    """
    if chain:
        key = (chain, number, "")
        if key in by_key:
            return key, by_key[key], {"chain_resolution": "explicit"}
        if any(candidate[0] == chain and candidate[1] == number for candidate in by_key):
            raise _insertion_code_error(chain, number)
        raise SelectionError(f"residue {chain}:{number} is absent from the structure")
    matches = [candidate for candidate in by_key if candidate[1] == number and not candidate[2]]
    if not matches:
        if any(candidate[1] == number for candidate in by_key):
            raise _insertion_code_error("", number)
        raise SelectionError(f"residue {number} is absent from the structure")
    key = matches[0]
    resolution: dict[str, object] = {
        "chain_resolution": "first chain containing the residue (upstream default)",
        "chain_candidates": [candidate[0] or "" for candidate in matches],
    }
    return key, by_key[key], resolution


def _selection_fields(params: dict[str, object]) -> dict[str, object]:
    fields = (
        "start_chain",
        "start_residue_number",
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
    atom_name = str(params.get("start_atom_name") or "")
    altloc = str(params.get("start_altloc") or "")
    if not isinstance(number, int) or isinstance(number, bool):
        raise SelectionError("start_residue_number is required when the start point is a selected atom")
    if not atom_name:
        raise SelectionError("start_atom_name is required when the start point is a selected atom")
    key, residue_atoms, resolution = _resolve_residue(_residues(atoms), chain, number)
    matches = [atom for atom in residue_atoms if atom.name == atom_name and (not altloc or atom.altloc == altloc)]
    if not matches:
        available = ", ".join(sorted({atom.name for atom in residue_atoms}))
        raise SelectionError(
            f"atom {atom_name!r} is absent from residue {key[0] or '_'}:{number}; available atoms: {available}"
        )
    # Highest occupancy wins; a blank alternate location breaks the tie, and
    # the chosen one is recorded so the selection is reproducible.
    atom = max(matches, key=lambda item: (item.occupancy, item.altloc == "", -item.serial))
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
            "residue_name": atom.resname,
            "atom_name": atom.name,
            "altloc": atom.altloc,
            "atom_serial": atom.serial,
            "atom_count": 1,
            "altloc_policy": "highest occupancy, blank alternate location preferred on ties",
            **resolution,
        },
        (("starting_point_atom", str(atom.serial)),),
    )


def _residue_centroid(params: dict[str, object], atoms: list[Atom]) -> StartPoint:
    chain = str(params.get("start_chain") or "")
    number = params.get("start_residue_number")
    if not isinstance(number, int) or isinstance(number, bool):
        raise SelectionError("start_residue_number is required when the start point is a residue centroid")
    key, residue_atoms, resolution = _resolve_residue(_residues(atoms), chain, number)
    x, y, z = _centroid(residue_atoms)
    return StartPoint(
        x,
        y,
        z,
        {
            "mode": "residue",
            "point_angstrom": [x, y, z],
            "units": "angstrom",
            "chain": key[0],
            "residue_number": number,
            "residue_name": residue_atoms[0].resname,
            "atom_count": len(residue_atoms),
            "residue_count": 1,
            "centroid_policy": "mean over all coordinate records, alternate locations included",
            **resolution,
        },
        (("starting_point_residue", residue_identifier(key[0], number)),),
    )


def _ligand_centroid(params: dict[str, object], atoms: list[Atom]) -> StartPoint:
    resname = str(params.get("start_residue_name") or "").strip()
    if not resname:
        raise SelectionError("start_residue_name is required when the start point is a ligand or cofactor centre")
    chain = params.get("start_chain")
    number = params.get("start_residue_number")
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
        candidates = ", ".join(f"{key[0] or '_'}:{key[1]}" for key in sorted(matched)[:10])
        raise SelectionError(
            f"{resname!r} matches {len(matched)} HETATM residues ({candidates}); "
            "set start_chain and start_residue_number"
        )
    ((residue_chain, residue_number, residue_icode), residue_atoms) = next(iter(matched.items()))
    if residue_icode:
        raise _insertion_code_error(residue_chain, residue_number)
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
            "residue_name": resname,
            "atom_count": len(residue_atoms),
            "residue_count": 1,
            "centroid_policy": "mean over all coordinate records, alternate locations included",
        },
        (("starting_point_residue", residue_identifier(residue_chain, residue_number)),),
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
    """Expand ranges into the individual identifiers CAVER's list parser accepts."""
    terms = []
    for chain, start, end in ranges:
        terms.extend(residue_identifier(chain, number) for number in range(start, end + 1))
    return " ".join(terms)


def _group_centroid(params: dict[str, object], atoms: list[Atom]) -> StartPoint:
    spec = str(params.get("start_group") or "").strip()
    if not spec:
        raise SelectionError("start_group is required when the start point is a residue-group centroid")
    ranges = _parse_group(spec)
    by_key = _residues(atoms)
    selected: list[Atom] = []
    resolved: list[tuple[str, int, int]] = []
    missing: list[str] = []
    for chain, start, end in ranges:
        for number in range(start, end + 1):
            try:
                (residue_chain, _, _), residue_atoms, _resolution = _resolve_residue(by_key, chain, number)
            except SelectionError as exc:
                missing.append(str(exc))
                continue
            selected.extend(residue_atoms)
            resolved.append((residue_chain, number, number))
    if missing:
        raise SelectionError(f"start_group cannot be resolved: {'; '.join(missing[:10])}")
    # CAVER weights each named residue equally: the initial point is the mean of
    # the residue centres, and each residue centre is the mean of all its
    # coordinate records.
    centres = [_centroid(by_key[key]) for key in {atom.residue for atom in selected}]
    x = sum(centre[0] for centre in centres) / len(centres)
    y = sum(centre[1] for centre in centres) / len(centres)
    z = sum(centre[2] for centre in centres) / len(centres)
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
            "atom_count": len(selected),
            "centroid_policy": "mean of residue centres, each residue centre the mean of all its coordinate records",
        },
        (("starting_point_residue", _group_directive(resolved)),),
    )


def parse_residue_token(token: str) -> tuple[str, int]:
    """Parse one ``exclude_residue_ids`` token, refusing insertion codes."""
    match = _RESIDUE_TOKEN.fullmatch(token)
    if match is None:
        raise SelectionError(f"residue identifier {token!r} is not CHAIN:NUMBER or NUMBER")
    if match.group("icode"):
        raise SelectionError(
            f"residue identifier {token!r} carries an insertion code; CAVER cannot address insertion-coded "
            "residues, so it cannot be excluded by identifier (use exclude_residue_names instead)"
        )
    return (match.group("chain") or ""), int(match.group("number"))


def _tokens(raw: object) -> list[str]:
    if not isinstance(raw, str):
        return []
    return [token for token in re.split(r"[,\s]+", raw.strip()) if token]


def validate_exclusions(params: dict[str, object], atoms: list[Atom]) -> None:
    """Reject exclusion tokens the structure cannot satisfy.

    A typo in an exclusion silently changes the science, because CAVER warns
    and keeps going. Every identifier must resolve against the reference
    structure before the run starts.
    """
    by_key = _residues(atoms)
    for token in _tokens(params.get("exclude_residue_ids")):
        chain, number = parse_residue_token(token)
        _resolve_residue(by_key, chain, number)
    names = {atom.resname for atom in atoms}
    for token in _tokens(params.get("exclude_residue_names")):
        if token not in names:
            raise SelectionError(f"exclude_residue_names names {token!r}, which is absent from the structure")
    serials = {atom.serial for atom in atoms}
    for token in _tokens(params.get("exclude_atom_numbers")):
        match = _ATOM_TOKEN.fullmatch(token)
        if match is None:
            raise SelectionError(f"atom number {token!r} is not an integer or a NUMBER-NUMBER range")
        first = int(match.group("first"))
        last = int(match.group("last") or first)
        if last < first:
            raise SelectionError(f"atom number range {token!r} is descending")
        if not any(first <= serial <= last for serial in serials):
            raise SelectionError(f"exclude_atom_numbers names {token!r}, which matches no atom serial")


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
