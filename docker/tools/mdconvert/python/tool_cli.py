# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Bounded GROMACS GRO + XTC to CAVER PDB snapshot conversion.

The release supports one audited pair.  Amber, CHARMM/NAMD, LAMMPS and OpenMM
pairs stay disabled until their unit, atom-order and periodic-box contracts are
proven; every other format pair is refused here with a typed diagnostic rather
than guessed.  The parser is pinned in this Tool's own image, never the Server
or a Runner SIF.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import resource
import sys
import traceback
import warnings
from pathlib import Path
from typing import Any

import numpy as np

MAX_ATOMS = 99_999
MAX_SELECTED_FRAMES = 51
MAX_CAVER_SNAPSHOTS = 50
MAX_SOURCE_FRAMES = 1_000_000
MAX_OUTPUT_BYTES = 33_554_432
MANIFEST_HEADROOM_BYTES = 1_048_576
MAX_RSS_BYTES = 2 * 1024 * 1024 * 1024
MAX_CPU_SECONDS = 240.0

#: Coordinates written to PDB must round-trip to three decimals.  CAVER and the
#: Runner converter both use this same bound.
PDB_COORDINATE_TOLERANCE = 0.0011

SUPPORTED_PAIRS = {("gro", "xtc")}
OUTPUT_ADAPTER = "caver_pdb_snapshots"
TOPOLOGY_ROLE = "topology"
TRAJECTORY_ROLE = "trajectory"

_NAMED_SELECTIONS = frozenset({"all", "protein", "nucleic", "backbone"})
_TOKEN = re.compile(r"[A-Za-z0-9]{1,5}\Z")
_RESID_TERM = re.compile(r"(?P<first>[0-9]{1,6})(?:-(?P<last>[0-9]{1,6}))?\Z")


class ToolInputError(ValueError):
    """A typed refusal the caller can report without scraping prose."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _request(path: Path, expected_tool: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolInputError("request_invalid", "Tool request is not readable JSON") from exc
    if not isinstance(raw, dict) or raw.get("tool") != expected_tool:
        raise ToolInputError("request_invalid", "Tool request identity does not match the selected implementation")
    parameters = raw.get("parameters", {})
    inputs = raw.get("inputs", {})
    limits = raw.get("limits", {})
    if not isinstance(parameters, dict) or not isinstance(inputs, dict) or not isinstance(limits, dict):
        raise ToolInputError("request_invalid", "Tool request parameters, inputs and limits must be objects")
    return parameters, inputs, limits


def _one_input(inputs: dict[str, Any], role: str) -> tuple[Path, str]:
    values = inputs.get(role)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ToolInputError("input_missing", f"Input role {role!r} requires exactly one file")
    path = Path(str(values[0].get("path", "")))
    format_name = str(values[0].get("format", ""))
    if path.is_symlink() or not path.is_file():
        raise ToolInputError("input_missing", f"Input role {role!r} is unavailable")
    return path, format_name


def _integer(parameters: dict[str, Any], name: str, *, minimum: int | None = None) -> int | None:
    value = parameters.get(name)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or (minimum is not None and value < minimum):
        raise ToolInputError("parameters_invalid", f"Parameter {name!r} must be an integer")
    return value


def _check_limits(limits: dict[str, Any], inputs: dict[str, Path]) -> None:
    request_bytes = limits.get("request_bytes")
    per_role = limits.get("input_bytes") if isinstance(limits.get("input_bytes"), dict) else {}
    if request_bytes is not None and (not isinstance(request_bytes, int) or request_bytes < 1):
        raise ToolInputError("request_invalid", "Tool request budget is invalid")
    total = 0
    for role, path in inputs.items():
        size = path.stat().st_size
        total += size
        cap = per_role.get(role, request_bytes)
        if isinstance(cap, int) and size > cap:
            raise ToolInputError("input_size_limit", f"Input role {role!r} exceeds its decoded byte limit")
    if isinstance(request_bytes, int) and total > request_bytes:
        raise ToolInputError("input_size_limit", "Combined Tool inputs exceed the request byte limit")


def _selection_expression(value: Any) -> str:
    """Return the one MDAnalysis query the documented syntax names.

    The caller's string is never passed to the parser: it is parsed into a
    named term and a validated literal, then rebuilt, so an undocumented
    expression cannot smuggle in additional selection logic.
    """
    if not isinstance(value, str):
        raise ToolInputError("selection_invalid", "Selection must be one documented term")
    if value in _NAMED_SELECTIONS:
        return value
    if value.startswith("name "):
        name = value[5:]
        if _TOKEN.fullmatch(name) and len(name) <= 4:
            return f"name {name}"
    if value.startswith("resname "):
        name = value[8:]
        if _TOKEN.fullmatch(name) and len(name) <= 5:
            return f"resname {name}"
    if value.startswith("resid "):
        terms = value[6:].split(",")
        if 0 < len(terms) <= 200:
            for term in terms:
                match = _RESID_TERM.fullmatch(term)
                if match is None:
                    break
                if match.group("last") is not None and int(match.group("first")) > int(match.group("last")):
                    break
            else:
                return f"resid {','.join(terms)}"
    raise ToolInputError("selection_invalid", "Selection is outside the documented selection syntax")


def _parameters(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "output_adapter", "start", "stop", "stride", "frame_indices",
        "reference_frame", "selection", "pbc_treatment",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ToolInputError("parameters_invalid", f"Unsupported conversion parameters: {', '.join(unknown)}")
    adapter = raw.get("output_adapter", OUTPUT_ADAPTER)
    if adapter != OUTPUT_ADAPTER:
        raise ToolInputError("output_adapter_unknown", "Only the caver_pdb_snapshots output adapter is released")
    treatment = raw.get("pbc_treatment", "none")
    if treatment not in {"none", "unwrap"}:
        raise ToolInputError("parameters_invalid", "pbc_treatment must be none or unwrap")
    if treatment == "unwrap":
        raise ToolInputError(
            "pbc_unwrap_unsupported",
            "Unwrapping requires bond evidence that this topology does not carry; periodic wrapping is left unchanged",
        )
    parameters = dict(raw)
    parameters["selection"] = _selection_expression(raw.get("selection", "all"))
    _integer(raw, "start", minimum=0)
    _integer(raw, "stop", minimum=1)
    stride = _integer(raw, "stride", minimum=1)
    if stride is not None and stride > 1_000_000:
        raise ToolInputError("parameters_invalid", "Parameter 'stride' is too large")
    _integer(raw, "reference_frame", minimum=0)
    indices = raw.get("frame_indices")
    if indices is not None:
        if any(name in raw for name in ("start", "stop", "stride")):
            raise ToolInputError(
                "frame_selection_invalid", "frame_indices cannot be combined with start, stop or stride"
            )
        if (
            not isinstance(indices, list)
            or not indices
            or len(indices) > MAX_SELECTED_FRAMES
            or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in indices)
            or any(left >= right for left, right in zip(indices, indices[1:]))
        ):
            raise ToolInputError(
                "frame_selection_invalid",
                "frame_indices must be a strictly increasing list of at most 51 source frame indices",
            )
    return parameters


def _selection_indices(universe: Any, selection: str) -> np.ndarray:
    try:
        indices = np.asarray(universe.select_atoms(selection).indices, dtype=np.int64)
    except Exception as exc:
        raise ToolInputError("selection_invalid", "Selection could not be resolved against the topology") from exc
    if indices.size == 0:
        raise ToolInputError("selection_empty", "Selection matched no atoms")
    if np.any(indices[1:] <= indices[:-1]):
        raise ToolInputError("selection_invalid", "Selection did not preserve the source atom order")
    return indices


def _frame_selection(parameters: dict[str, Any], universe: Any) -> tuple[list[int], int, int]:
    try:
        frame_count = len(universe.trajectory)
    except Exception as exc:
        raise ToolInputError("trajectory_parse_failed", "Trajectory frames could not be enumerated") from exc
    if frame_count < 1:
        raise ToolInputError("trajectory_parse_failed", "Trajectory contains no frames")
    if frame_count > MAX_SOURCE_FRAMES:
        raise ToolInputError("frame_count_limit", "Trajectory exceeds the supported source frame count")
    if "frame_indices" in parameters:
        selected = list(parameters["frame_indices"])
    else:
        start = parameters.get("start", 0)
        stop = parameters.get("stop", frame_count)
        stride = parameters.get("stride", 1)
        if start >= stop:
            raise ToolInputError("frame_selection_invalid", "start must be smaller than stop")
        if stop > frame_count:
            raise ToolInputError("frame_selection_range", "Frame selection extends beyond the trajectory")
        selected = list(range(start, stop, stride))
    if not selected:
        raise ToolInputError("frame_selection_invalid", "Frame selection is empty")
    if len(set(selected)) != len(selected):
        raise ToolInputError("frame_selection_invalid", "Frame selection repeats a source frame")
    if len(selected) > MAX_SELECTED_FRAMES:
        raise ToolInputError(
            "frame_selection_invalid",
            f"At most {MAX_SELECTED_FRAMES} output frames (reference plus {MAX_CAVER_SNAPSHOTS} snapshots) are allowed",
        )
    if selected[-1] >= frame_count:
        raise ToolInputError("frame_selection_range", "Frame selection extends beyond the trajectory")
    reference = parameters.get("reference_frame", selected[0])
    if reference not in selected:
        raise ToolInputError("reference_frame_not_selected", "reference_frame must be one of the selected frames")
    return selected, reference, frame_count


def _representation_policy() -> dict[str, str]:
    return {
        "chain_ids": "MDAnalysis writes 'X' for atoms whose topology carries no chain identifier; GRO carries none",
        "alternate_locations": "blank; GRO carries no alternate locations",
        "insertion_codes": "blank; GRO carries none",
        "occupancy": "1.0 for every atom; GRO carries none",
        "record_type": "ATOM for every atom; GRO carries none",
        "element": "blank; GRO carries no element column, so no element identity is invented",
    }


def _ensure_representation(universe: Any) -> None:
    """Give the PDB writer explicit, documented representation defaults."""
    atoms = universe.atoms
    if "chainIDs" not in universe._topology.attrs:
        universe.add_TopologyAttr("chainIDs", [""] * atoms.n_atoms)
    universe.add_TopologyAttr("altLocs", [""] * atoms.n_atoms)
    universe.add_TopologyAttr("icodes", [""] * universe.residues.n_residues)
    universe.add_TopologyAttr("occupancies", [1.0] * atoms.n_atoms)
    universe.add_TopologyAttr("tempfactors", [0.0] * atoms.n_atoms)
    universe.add_TopologyAttr("record_types", ["ATOM"] * atoms.n_atoms)


def _check_representable(atom_group: Any) -> None:
    if atom_group.n_atoms > MAX_ATOMS:
        raise ToolInputError("atom_count_limit", f"At most {MAX_ATOMS} atoms can be represented as PDB")
    if any(not name or len(name) > 4 for name in (str(value) for value in atom_group.names)):
        raise ToolInputError("pdb_identity_unrepresentable", "An atom name cannot be represented in a PDB record")
    if any(not name or len(name) > 3 for name in (str(value) for value in atom_group.resnames)):
        raise ToolInputError("pdb_identity_unrepresentable", "A residue name cannot be represented in a PDB record")
    resids = np.asarray(atom_group.resids)
    if np.any(resids < 0) or np.any(resids > 9999):
        raise ToolInputError("pdb_identity_unrepresentable", "A residue number cannot be represented in a PDB record")
    identities = {
        (str(chain), int(resid), str(icode), str(name))
        for chain, resid, icode, name in zip(
            atom_group.chainIDs, resids, atom_group.icodes, atom_group.names, strict=True
        )
    }
    if len(identities) != atom_group.n_atoms:
        raise ToolInputError(
            "pdb_identity_unrepresentable",
            "Two selected atoms share a PDB chain, residue and atom identity; "
            "the CAVER snapshot map cannot distinguish them",
        )


def _guard_resources() -> None:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    if usage.ru_maxrss * 1024 > MAX_RSS_BYTES:
        raise ToolInputError("rss_limit", "Conversion exceeded its resident-memory limit")
    if usage.ru_utime + usage.ru_stime > MAX_CPU_SECONDS:
        raise ToolInputError("cpu_limit", "Conversion exceeded its CPU-time limit")


def _box(ts: Any, warnings_list: list[dict[str, str]], absent: list[bool]) -> list[float] | None:
    dimensions = ts.dimensions
    if dimensions is None or all(float(value) == 0.0 for value in dimensions[:3]):
        if not absent[0]:
            warnings_list.append(
                {
                    "code": "no_periodic_box",
                    "message": "A selected frame carries no unit cell; no periodic treatment was applied",
                }
            )
            absent[0] = True
        return None
    values = [float(value) for value in dimensions]
    if not all(math.isfinite(value) for value in values):
        raise ToolInputError("invalid_unit_cell", "A selected frame carries a non-finite unit cell")
    if any(value <= 0.0 for value in values[:3]) or any(not 0.0 < value <= 180.0 for value in values[3:]):
        raise ToolInputError("invalid_unit_cell", "A selected frame carries an invalid unit cell")
    return values


def _parse_written_pdb(path: Path) -> list[dict[str, Any]]:
    """Parse the fixed columns CAVER reads, refusing anything it would misread."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolInputError("pdb_write_failed", "Written PDB could not be read back") from exc
    atoms: list[dict[str, Any]] = []
    models = 0
    for line in lines:
        record = line[:6]
        if record.startswith("MODEL"):
            models += 1
            if models > 1:
                raise ToolInputError("pdb_write_failed", "Written PDB contains several models")
            continue
        if not (record.startswith("ATOM") or record.startswith("HETATM")):
            continue
        if len(line) < 54:
            raise ToolInputError("pdb_write_failed", "Written PDB contains a truncated coordinate record")
        try:
            atoms.append(
                {
                    "serial": int(line[6:11]),
                    "name": line[12:16].strip(),
                    "altloc": line[16:17].strip(),
                    "resname": line[17:20].strip(),
                    "chain": line[21:22].strip(),
                    "resseq": int(line[22:26]),
                    "icode": line[26:27].strip(),
                    "xyz": (float(line[30:38]), float(line[38:46]), float(line[46:54])),
                }
            )
        except ValueError as exc:
            raise ToolInputError("pdb_write_failed", "Written PDB contains a malformed coordinate record") from exc
    return atoms


def _write_frame(
    atom_group: Any, positions: np.ndarray, target: Path, box: list[float] | None
) -> list[tuple[str, int, str, str]]:
    import MDAnalysis as mda

    with mda.Writer(str(target), n_atoms=atom_group.n_atoms, multiframe=False) as writer:
        writer.write(atom_group)
    if box is None:
        # MDAnalysis invents a 1x1x1 cell when the frame carries none.  A
        # converted snapshot must not claim a periodic cell the source lacks.
        lines = target.read_text(encoding="utf-8").splitlines()
        cleaned = [
            line
            for line in lines
            if not line.startswith("CRYST1") and not (line.startswith("REMARK") and "285" in line)
        ]
        target.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
    written = _parse_written_pdb(target)
    if len(written) != atom_group.n_atoms:
        raise ToolInputError("pdb_write_failed", "Written PDB does not contain every selected atom")
    identities: list[tuple[str, int, str, str]] = []
    for index, (atom, expected) in enumerate(zip(written, atom_group, strict=True)):
        if not (
            atom["serial"] == index + 1
            and atom["name"] == str(expected.name)
            and atom["resname"] == str(expected.resname)
            and atom["resseq"] == int(expected.resid)
            and atom["altloc"] == ""
            and atom["icode"] == ""
        ):
            raise ToolInputError(
                "pdb_identity_unrepresentable", "The topology atom identity changed when written as PDB"
            )
        if any(
            not math.isfinite(value) or abs(value - float(source)) > PDB_COORDINATE_TOLERANCE
            for value, source in zip(atom["xyz"], positions[index], strict=True)
        ):
            raise ToolInputError("pdb_write_failed", "Written PDB coordinates do not match the selected frame")
        identities.append((atom["chain"], atom["resseq"], atom["icode"], atom["name"]))
    return identities


def _parser_versions() -> dict[str, str]:
    from importlib.metadata import version

    payload = {}
    for distribution in ("MDAnalysis", "numpy", "mda-xdrlib"):
        key = distribution.lower().replace("-", "_")
        try:
            payload[key] = version(distribution)
        except Exception:
            payload[key] = "unavailable"
    return payload


def _dedupe(warnings_list: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result = []
    for item in warnings_list:
        key = (item["code"], item["message"])
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def md_trajectory_convert(request_path: Path, output_dir: Path) -> dict[str, Any]:
    parameters, inputs, limits = _request(request_path, "md_trajectory_convert")
    parameters = _parameters(parameters)
    topology, topology_format = _one_input(inputs, TOPOLOGY_ROLE)
    trajectory, trajectory_format = _one_input(inputs, TRAJECTORY_ROLE)
    if (topology_format, trajectory_format) not in SUPPORTED_PAIRS:
        raise ToolInputError(
            "unsupported_format_pair",
            f"The pair {topology_format!r} + {trajectory_format!r} is not enabled; "
            "the released pair is GRO + XTC with the pinned parser",
        )
    _check_limits(limits, {TOPOLOGY_ROLE: topology, TRAJECTORY_ROLE: trajectory})
    topology_sha256, trajectory_sha256 = sha256_file(topology), sha256_file(trajectory)

    import MDAnalysis as mda

    parser_warnings: list[dict[str, str]] = []

    def capture(caught: list[Any]) -> None:
        for item in caught:
            message = str(item.message)[:300]
            if len(parser_warnings) < 20 and not any(item_["message"] == message for item_ in parser_warnings):
                parser_warnings.append({"code": "parser_warning", "message": message})

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            universe = mda.Universe(
                str(topology), str(trajectory), topology_format="GRO", format="XTC", convert_units=True
            )
            capture(caught)
    except Exception as exc:
        raise ToolInputError("trajectory_parse_failed", "Topology or trajectory could not be parsed") from exc

    atom_count = universe.atoms.n_atoms
    if atom_count < 1:
        raise ToolInputError("topology_parse_failed", "Topology contains no atoms")
    _ensure_representation(universe)
    selection = str(parameters["selection"])
    indices = _selection_indices(universe, selection)
    _check_representable(universe.atoms[indices])
    selected, reference_index, source_frames = _frame_selection(parameters, universe)

    reference_name = "reference.pdb"
    snapshot_frames = [frame for frame in selected if frame != reference_index]
    snapshot_names = [f"snapshot_{index:03d}.pdb" for index in range(1, len(snapshot_frames) + 1)]
    names = {reference_index: reference_name, **dict(zip(snapshot_frames, snapshot_names, strict=True))}
    warnings_list: list[dict[str, str]] = [
        {
            "code": "elements_not_representable",
            "message": "The GRO topology carries no element identity; PDB element columns are left blank",
        },
        {
            "code": "chain_identity_synthetic",
            "message": "The GRO topology carries no chain identifier; every atom is written to PDB chain X, "
                       "and duplicate chain/residue/atom identities are refused",
        },
    ]
    absent = [False]
    source_boxes: dict[int, list[float] | None] = {}
    source_times: dict[int, float] = {}
    frame_records: dict[int, dict[str, Any]] = {}
    transitions: list[dict[str, Any]] = []
    reference_identities: list[tuple[str, int, str, str]] | None = None
    previous_positions: np.ndarray | None = None
    previous_frame: int | None = None
    total_output = 0

    # Frames are read in source order so the recorded transitions and
    # discontinuities describe the trajectory, not the CAVER output order.
    for frame in selected:
        _guard_resources()
        try:
            universe.trajectory[frame]
            atom_group = universe.atoms[indices]
            positions = np.array(atom_group.positions, dtype=np.float64)
            time_value = float(universe.trajectory.ts.time)
        except Exception as exc:
            raise ToolInputError("trajectory_parse_failed", "A selected frame could not be read") from exc
        if not np.all(np.isfinite(positions)):
            raise ToolInputError("non_finite_coordinates", "A selected frame contains a non-finite coordinate")
        if positions.shape != (atom_group.n_atoms, 3):
            raise ToolInputError("atom_count_mismatch", "A selected frame coordinate count differs from the topology")
        if not math.isfinite(time_value):
            raise ToolInputError("missing_frame_time", "A selected frame carries no finite source time")
        box = _box(universe.trajectory.ts, warnings_list, absent)
        source_boxes[frame] = box
        source_times[frame] = time_value
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            identities = _write_frame(atom_group, positions, output_dir / names[frame], box)
            capture(caught)
        if reference_identities is None:
            reference_identities = identities
        elif identities != reference_identities:
            raise ToolInputError("atom_order_changed", "Atom identity differs between converted frames")
        output_path = output_dir / names[frame]
        size = output_path.stat().st_size
        total_output += size
        if total_output > MAX_OUTPUT_BYTES - MANIFEST_HEADROOM_BYTES:
            raise ToolInputError("output_size_limit", "Converted snapshots exceed the output byte limit")
        frame_records[frame] = {
            "output": names[frame],
            "source_frame_index": frame,
            "time_ps": time_value,
            "box_angstrom": box,
            "sha256": sha256_file(output_path),
            "size": size,
        }
        if previous_positions is not None:
            displacement = float(np.max(np.linalg.norm(positions - previous_positions, axis=1)))
            transitions.append(
                {
                    "from_source_frame_index": previous_frame,
                    "to_source_frame_index": frame,
                    "max_atom_displacement_angstrom": displacement,
                }
            )
            if box is not None and displacement > 0.5 * min(box[:3]):
                warnings_list.append(
                    {
                        "code": "possible_periodic_jump",
                        "message": "Consecutive frames move by more than half a unit-cell length; "
                                   "coordinates were not unwrapped",
                    }
                )
        previous_positions, previous_frame = positions, frame

    frames = [frame_records[reference_index], *[frame_records[frame] for frame in snapshot_frames]]

    if any(source_times[left] > source_times[right] for left, right in zip(selected, selected[1:])):
        warnings_list.append(
            {"code": "frame_times_nonmonotonic", "message": "Selected source frame times are not non-decreasing"}
        )
    boxes = [source_boxes[frame] for frame in selected]
    present = [box for box in boxes if box is not None]
    if present and len(present) != len(boxes):
        raise ToolInputError(
            "missing_pbc_box", "Some selected frames carry a unit cell and others do not"
        )
    elif present and any(
        any(abs(left - right) > 0.001 for left, right in zip(this, present[0], strict=True))
        for this in present[1:]
    ):
        warnings_list.append(
            {"code": "periodic_box_changes", "message": "The unit cell changes across selected frames"}
        )

    assert reference_identities is not None
    selected_atoms = universe.atoms[indices]
    selected_resnames = [str(value) for value in selected_atoms.resnames]
    atom_map = [
        [chain, resseq, icode, name, selected_resnames[index], ""]
        for index, (chain, resseq, icode, name) in enumerate(reference_identities)
    ]
    imported = _parser_versions()
    manifest = {
        "manifest_version": 1,
        "tool": {"id": "md_trajectory_convert", "version": "1", "output_adapter": OUTPUT_ADAPTER},
        "sources": {
            TOPOLOGY_ROLE: {"format": topology_format, "sha256": topology_sha256, "size": topology.stat().st_size},
            TRAJECTORY_ROLE: {
                "format": trajectory_format,
                "sha256": trajectory_sha256,
                "size": trajectory.stat().st_size,
                "frame_count": source_frames,
            },
        },
        "parser": imported,
        "units": {
            "source_coordinate_unit": "nm",
            "source_time_unit": "ps",
            "output_coordinate_unit": "angstrom",
            "conversion": "The MDAnalysis GRO reader converts nm to Angstrom; no additional scale was applied",
        },
        "atoms": {
            "topology_atom_count": atom_count,
            "selected_atom_count": int(indices.size),
            "selection": selection,
            "atom_map_identity_fields": ["chain", "resseq", "icode", "name", "resname", "altloc"],
            "atom_map_sha256": hashlib.sha256(
                json.dumps(atom_map, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "representation": _representation_policy(),
        },
        "pbc": {
            "treatment": "none",
            "coordinates": "source coordinates unchanged; no wrap or unwrap was applied",
            "box_unit": "angstrom",
        },
        "reference": frames[0],
        "snapshots": frames[1:],
        "frame_count": len(frames),
        "transitions": transitions,
        "warnings": _dedupe(warnings_list + parser_warnings),
        "output_hashes": {item["output"]: {"sha256": item["sha256"], "size": item["size"]} for item in frames},
    }
    manifest_path = output_dir / "conversion_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if total_output + manifest_path.stat().st_size > MAX_OUTPUT_BYTES:
        manifest_path.unlink(missing_ok=True)
        raise ToolInputError("output_size_limit", "Converted outputs exceed the output byte limit")

    return {
        "outputs": {
            "reference": [{"path": reference_name, "format": "pdb"}],
            "snapshots": [{"path": name, "format": "pdb"} for name in snapshot_names],
            "manifest": [{"path": "conversion_manifest.json", "format": "json"}],
        },
        "warnings": manifest["warnings"],
        "backend": {"name": "MDAnalysis", **imported, "operation": "representation_only"},
    }


def health() -> int:
    import MDAnalysis as mda
    from MDAnalysis.coordinates.XTC import XTCReader, XTCWriter  # noqa: F401

    universe = mda.Universe.empty(1, trajectory=True)
    if universe.atoms.n_atoms != 1:
        raise RuntimeError("MDAnalysis topology probe failed")
    return 0


TOOLS = {"md_trajectory_convert": md_trajectory_convert}


def _write_error(output: Path, code: str, message: str) -> None:
    try:
        output.mkdir(parents=True, exist_ok=True)
        (output / ".tool-error.json").write_text(
            json.dumps({"code": code, "message": message[:2000]}, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health")
    run = subparsers.add_parser("run")
    run.add_argument("--tool", choices=sorted(TOOLS), required=True)
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "health":
        return health()
    try:
        args.output.mkdir(parents=True, exist_ok=True)
        response = TOOLS[args.tool](args.request, args.output)
    except ToolInputError as exc:
        _write_error(args.output, exc.code, str(exc))
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 2
    except Exception:
        _write_error(
            args.output, "internal_conversion_failure", "Conversion failed while reading or writing the trajectory"
        )
        traceback.print_exc()
        return 2
    (args.output / ".tool-response.json").write_text(
        json.dumps(response, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
