# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Resolve a typed CAVER start point against one PDB structure.

CAVER needs a single point inside the protein from which tunnel exploration
starts. The Task exposes that point as typed controls (manual Angstrom
coordinates, one atom, one residue centroid, a residue group centroid, or a
ligand/cofactor centroid); this module turns those controls into the exact
coordinates CAVER receives and records how they were derived.

Only single-model PDB is parsed here, and parsing is strict about everything
that would change the science: an absent coordinate, an insertion-coded residue
or an atom in an alternate conformation CAVER deletes is an error. Two places
follow CAVER rather than refusing: an empty chain means the first matching
named chain, which is resolved here and passed explicitly, and an empty
alternate location means the highest-occupancy conformer. Both choices are
recorded in provenance, and the initial point CAVER reports in
``data/origins.pdb`` is checked against the resolved point after the run.
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
    """Arithmetic mean over the atoms CAVER keeps for the selection.

    CAVER removes alternative conformations while reading the file, so the
    caller passes the retained atoms; averaging every record would publish a
    point CAVER never uses. Hydrogens do contribute.
    """
    if not atoms:
        raise SelectionError("selection resolved to no atoms")
    return (
        sum(atom.x for atom in atoms) / len(atoms),
        sum(atom.y for atom in atoms) / len(atoms),
        sum(atom.z for atom in atoms) / len(atoms),
    )


def _kept_conformer(residue_atoms: list[Atom]) -> tuple[str, list[Atom]]:
    """The non-blank alternate conformation CAVER keeps, or ``("", [])``."""
    conformers: dict[str, list[Atom]] = {}
    for atom in residue_atoms:
        if atom.altloc:
            conformers.setdefault(atom.altloc, []).append(atom)
    best: tuple[str, float, list[Atom]] | None = None
    for label in sorted(conformers):
        group = conformers[label]
        occupancy = sum(atom.occupancy for atom in group) / len(group)
        if best is None or occupancy > best[1]:
            best = (label, occupancy, group)
    return ("", []) if best is None else (best[0], best[2])


def retained_atoms(atoms: list[Atom]) -> list[Atom]:
    """Return the atoms CAVER keeps after alternate-conformation removal.

    CAVER's ``PdbFileFactory`` drops alternate conformations per residue: atoms
    with a blank alternate location are always kept, and among the labelled
    conformers only the one with the highest mean occupancy survives. The log
    line "removed conformation B" and ``data/origins.pdb`` confirm it.
    """
    keep = set()
    for residue_atoms in _residues(atoms).values():
        keep.update(id(atom) for atom in residue_atoms if not atom.altloc)
        _label, conformer = _kept_conformer(residue_atoms)
        keep.update(id(atom) for atom in conformer)
    return [atom for atom in atoms if id(atom) in keep]


def _removed_altlocs(atoms: list[Atom]) -> list[str]:
    """Alternate-conformation labels CAVER removes from this selection."""
    removed = []
    for residue_atoms in _residues(atoms).values():
        labels = {atom.altloc for atom in residue_atoms if atom.altloc}
        kept, _conformer = _kept_conformer(residue_atoms)
        removed.extend(sorted(label for label in labels if label != kept))
    return removed


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
    means the first chain of the structure, which the Task resolves here and
    always passes explicitly, so the point CAVER uses is the point provenance
    records. CAVER never resolves a chainless identifier to a blank chain while
    the structure has named chains, so such a resolution is refused instead of
    silently starting somewhere else.
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
    named = [candidate for candidate in matches if candidate[0]]
    if any(candidate[0] for candidate in by_key) and not named:
        raise SelectionError(
            f"residue {number} exists only in the blank chain, but CAVER resolves a chainless identifier "
            "to a named chain; this residue cannot be selected"
        )
    key = (named or matches)[0]
    resolution: dict[str, object] = {
        "chain_resolution": "first matching chain, passed explicitly",
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
    retained = {id(candidate) for candidate in retained_atoms(residue_atoms)}
    if id(atom) not in retained:
        kept_label, _conformer = _kept_conformer(residue_atoms)
        raise SelectionError(
            f"atom {atom_name!r} at alternate location {atom.altloc!r} is removed by CAVER, which keeps "
            f"conformation {kept_label or '<blank>'} of residue {key[0] or '_'}:{number}"
        )
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
            "altloc_policy": "highest occupancy, blank alternate location preferred on ties; the selected "
            "conformer must be the one CAVER keeps",
            "removed_altlocs": _removed_altlocs(residue_atoms),
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
    kept = retained_atoms(residue_atoms)
    x, y, z = _centroid(kept)
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
            "atom_count": len(kept),
            "residue_count": 1,
            "removed_altlocs": _removed_altlocs(residue_atoms),
            "centroid_policy": "mean over retained atoms; CAVER removes the lower-occupancy conformer",
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
    if not residue_chain and any(atom.chain for atom in atoms):
        raise SelectionError(
            f"{resname!r} matches only a blank-chain residue, but CAVER resolves a chainless identifier "
            "to a named chain; set start_chain explicitly with a named chain"
        )
    kept = retained_atoms(residue_atoms)
    x, y, z = _centroid(kept)
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
            "atom_count": len(kept),
            "residue_count": 1,
            "removed_altlocs": _removed_altlocs(residue_atoms),
            "centroid_policy": "mean over retained atoms; CAVER removes the lower-occupancy conformer",
            "chain_resolution": "explicit" if chain not in (None, "") else "single matching HETATM residue",
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
    # the residue centres, and each residue centre is the mean of the atoms it
    # keeps. Sorted iteration keeps floating-point summation order stable.
    centres = [_centroid(retained_atoms(by_key[key])) for key in sorted({atom.residue for atom in selected})]
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
            "atom_count": len(retained_atoms(selected)),
            "removed_altlocs": _removed_altlocs(selected),
            "centroid_policy": "mean of residue centres, each residue centre the mean of its retained atoms",
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
