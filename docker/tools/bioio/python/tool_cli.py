# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import gemmi
from Bio import SeqIO

AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWYXBZJOU*")
MAX_RECORDS = 100_000


class ToolInputError(ValueError):
    pass


def _request(path: Path, expected_tool: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("tool") != expected_tool:
        raise ToolInputError("Tool request identity does not match the selected implementation")
    parameters = raw.get("parameters", {})
    inputs = raw.get("inputs", {})
    if not isinstance(parameters, dict) or not isinstance(inputs, dict):
        raise ToolInputError("Tool request parameters and inputs must be objects")
    return parameters, inputs


def _one_input(inputs: dict[str, Any], role: str) -> tuple[Path, str]:
    values = inputs.get(role)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ToolInputError(f"Input role {role!r} requires exactly one file")
    path = Path(str(values[0].get("path", "")))
    format_name = str(values[0].get("format", ""))
    if not path.is_file() or path.is_symlink():
        raise ToolInputError(f"Input role {role!r} is unavailable")
    return path, format_name


def _read_structure(path: Path) -> gemmi.Structure:
    try:
        structure = gemmi.read_structure(str(path))
    except Exception as exc:
        raise ToolInputError("Protein structure could not be parsed") from exc
    if len(structure) == 0:
        raise ToolInputError("Protein structure contains no models")
    structure.setup_entities()
    return structure


def _atom_count(structure: gemmi.Structure) -> int:
    return sum(1 for model in structure for chain in model for residue in chain for _atom in residue)


def _structure_atoms(structure: gemmi.Structure) -> list[tuple[tuple[str, ...], tuple[float, float, float]]]:
    return [
        (
            (
                str(model_index),
                chain.name,
                str(residue.seqid),
                residue.name,
                residue.het_flag,
                atom.name,
                str(atom.altloc).strip("\x00 "),
                atom.element.name,
            ),
            (atom.pos.x, atom.pos.y, atom.pos.z),
        )
        for model_index, model in enumerate(structure)
        for chain in model
        for residue in chain
        for atom in residue
    ]


def _verify_structure_conversion(before: gemmi.Structure, target: Path) -> None:
    original, converted = _structure_atoms(before), _structure_atoms(_read_structure(target))
    if len(original) != len(converted) or any(left[0] != right[0] for left, right in zip(original, converted, strict=True)):
        target.unlink(missing_ok=True)
        raise RuntimeError("Structure conversion changed atom identity")
    if any(
        abs(left_coordinate - right_coordinate) > 0.0011
        for left, right in zip(original, converted, strict=True)
        for left_coordinate, right_coordinate in zip(left[1], right[1], strict=True)
    ):
        target.unlink(missing_ok=True)
        raise RuntimeError("Structure conversion changed atom coordinates")


def structure_inspect(request_path: Path, output_dir: Path) -> dict[str, Any]:
    _parameters, inputs = _request(request_path, "structure_inspect")
    path, format_name = _one_input(inputs, "structure")
    structure = _read_structure(path)
    chains = sorted({chain.name for model in structure for chain in model})
    residues = [residue for model in structure for chain in model for residue in chain]
    atoms = [atom for residue in residues for atom in residue]
    waters = sum(1 for residue in residues if residue.is_water())
    hetero = sum(1 for residue in residues if residue.het_flag != "A" and not residue.is_water())
    polymer_chains = sorted(
        {
            chain.name
            for model in structure
            for chain in model
            if any(residue.entity_type == gemmi.EntityType.Polymer for residue in chain)
        }
    )
    finite_coordinates = all(math.isfinite(value) for atom in atoms for value in (atom.pos.x, atom.pos.y, atom.pos.z))
    payload = {
        "detected_format": format_name,
        "models": len(structure),
        "chains": chains,
        "polymer_chains": polymer_chains,
        "residue_count": len(residues),
        "atom_count": len(atoms),
        "hetero_residue_count": hetero,
        "water_count": waters,
        "alternate_locations": any(str(atom.altloc).strip("\x00 ") for atom in atoms),
        "coordinates_finite": finite_coordinates,
    }
    target = output_dir / "inspection.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"outputs": {"inspection": [{"path": target.name, "format": "json"}]}, "warnings": []}


def structure_convert(request_path: Path, output_dir: Path) -> dict[str, Any]:
    parameters, inputs = _request(request_path, "structure_convert")
    path, _format_name = _one_input(inputs, "structure")
    output_format = parameters.get("output_format")
    if output_format not in {"pdb", "mmcif"} or set(parameters) != {"output_format"}:
        raise ToolInputError("output_format must be pdb or mmcif")
    structure = _read_structure(path)
    warnings: list[dict[str, str]] = []
    if output_format == "pdb":
        if any(len(chain.name) != 1 for model in structure for chain in model):
            raise ToolInputError("Structure chain identifiers cannot be represented safely as PDB")
        if _atom_count(structure) > 99_999:
            raise ToolInputError("Structure atom count cannot be represented safely as PDB")
        target = output_dir / "structure.pdb"
        structure.write_pdb(str(target))
    else:
        target = output_dir / "structure.cif"
        structure.make_mmcif_document().write_file(str(target))
    _verify_structure_conversion(structure, target)
    return {"outputs": {"structure": [{"path": target.name, "format": output_format}]}, "warnings": warnings}


def structure_to_fasta(request_path: Path, output_dir: Path) -> dict[str, Any]:
    _parameters, inputs = _request(request_path, "structure_to_fasta")
    path, _format_name = _one_input(inputs, "structure")
    structure = _read_structure(path)
    records: list[tuple[str, str]] = []
    for model_index, model in enumerate(structure, start=1):
        for chain in model:
            sequence = "".join(
                residue_info.one_letter_code or "X"
                for residue in chain
                if (residue_info := gemmi.find_tabulated_residue(residue.name)).is_amino_acid()
            )
            if sequence:
                identity = chain.name or "unnamed"
                suffix = f" model={model_index}" if len(structure) > 1 else ""
                records.append((f"{identity}{suffix}", sequence))
    if not records:
        raise ToolInputError("Protein structure contains no observed amino-acid residues")
    target = output_dir / "sequence.fasta"
    target.write_text("".join(f">{identifier}\n{sequence}\n" for identifier, sequence in records), encoding="utf-8")
    return {"outputs": {"sequence": [{"path": target.name, "format": "fasta"}]}, "warnings": []}


def fasta_inspect(request_path: Path, output_dir: Path) -> dict[str, Any]:
    _parameters, inputs = _request(request_path, "fasta_inspect")
    path, _format_name = _one_input(inputs, "sequence")
    records = []
    try:
        for index, record in enumerate(SeqIO.parse(path, "fasta")):
            if index >= MAX_RECORDS:
                raise ToolInputError("FASTA record limit exceeded")
            sequence = str(record.seq).upper()
            records.append({"id": record.id, "length": len(sequence), "alphabet_valid": set(sequence) <= AMINO_ACIDS})
    except ToolInputError:
        raise
    except Exception as exc:
        raise ToolInputError("FASTA could not be parsed") from exc
    if not records:
        raise ToolInputError("FASTA contains no sequences")
    counts = Counter(item["id"] for item in records)
    payload = {
        "sequence_count": len(records),
        "records": records,
        "duplicate_ids": sorted(identifier for identifier, count in counts.items() if count > 1),
        "alphabet_valid": all(item["alphabet_valid"] for item in records),
    }
    target = output_dir / "inspection.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"outputs": {"inspection": [{"path": target.name, "format": "json"}]}, "warnings": []}


TOOLS = {
    "structure_inspect": structure_inspect,
    "structure_convert": structure_convert,
    "structure_to_fasta": structure_to_fasta,
    "fasta_inspect": fasta_inspect,
}


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
        structure = gemmi.read_pdb_string("ATOM      1  CA  GLY A   1       0.000   0.000   0.000  1.00 20.00           C\nEND\n")
        if _atom_count(structure) != 1:
            raise RuntimeError("Gemmi structure parser health probe failed")
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    response = TOOLS[args.tool](args.request, args.output)
    (args.output / ".tool-response.json").write_text(
        json.dumps(response, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
