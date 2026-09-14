# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from rdkit import Chem

MAX_MOLECULES = 10_000
METAL_ATOMIC_NUMBERS = frozenset(
    (*range(3, 5), *range(11, 14), *range(19, 33), *range(37, 52), *range(55, 85), *range(87, 119))
)


class ToolInputError(ValueError):
    pass


def _request(path: Path, expected_tool: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("tool") != expected_tool:
        raise ToolInputError("Tool request identity does not match the selected implementation")
    parameters, inputs = raw.get("parameters", {}), raw.get("inputs", {})
    if not isinstance(parameters, dict) or not isinstance(inputs, dict):
        raise ToolInputError("Tool request parameters and inputs must be objects")
    return parameters, inputs


def _one_input(inputs: dict[str, Any]) -> tuple[Path, str]:
    values = inputs.get("ligand")
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ToolInputError("Input role 'ligand' requires exactly one file")
    path = Path(str(values[0].get("path", "")))
    format_name = str(values[0].get("format", ""))
    if format_name not in {"sdf", "mol2"} or not path.is_file() or path.is_symlink():
        raise ToolInputError("Ligand input is unavailable or has an unsupported format")
    return path, format_name


def _read_molecules(path: Path, format_name: str) -> tuple[list[Chem.Mol], list[int]]:
    molecules: list[Chem.Mol] = []
    failures: list[int] = []
    if format_name == "sdf":
        supplier = Chem.SDMolSupplier(str(path), sanitize=True, removeHs=False, strictParsing=True)
        for index, molecule in enumerate(supplier):
            if index >= MAX_MOLECULES:
                raise ToolInputError("Ligand molecule record limit exceeded")
            if molecule is None:
                failures.append(index)
            else:
                molecules.append(molecule)
    else:
        molecule = Chem.MolFromMol2File(str(path), sanitize=True, removeHs=False, cleanupSubstructures=False)
        if molecule is None:
            failures.append(0)
        else:
            molecules.append(molecule)
    return molecules, failures


def _molecule_metadata(molecule: Chem.Mol) -> dict[str, Any]:
    atoms = tuple(molecule.GetAtoms())
    conformers = tuple(molecule.GetConformers())
    has_3d = bool(conformers and conformers[0].Is3D())
    finite = all(
        math.isfinite(value)
        for conformer in conformers
        for atom_index in range(molecule.GetNumAtoms())
        for value in tuple(conformer.GetAtomPosition(atom_index))
    )
    return {
        "atom_count": len(atoms),
        "heavy_atom_count": sum(atom.GetAtomicNum() > 1 for atom in atoms),
        "formal_charge": sum(atom.GetFormalCharge() for atom in atoms),
        "partial_charge_present": any(
            atom.HasProp("_TriposPartialCharge") and abs(atom.GetDoubleProp("_TriposPartialCharge")) > 1e-6
            for atom in atoms
        ),
        "has_3d_coordinates": has_3d,
        "coordinates_finite": finite,
        "metals": sorted({atom.GetSymbol() for atom in atoms if atom.GetAtomicNum() in METAL_ATOMIC_NUMBERS}),
    }


def _declare_uncharged_mol2(path: Path) -> None:
    """Correct Open Babel's stale charge-type label after its `none` model clears charges."""
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        molecule_header = lines.index("@<TRIPOS>MOLECULE")
        atom_header = lines.index("@<TRIPOS>ATOM")
    except ValueError as exc:
        raise RuntimeError("Converted MOL2 is missing required sections") from exc
    charge_type_index = molecule_header + 4
    if charge_type_index >= atom_header or lines[charge_type_index] not in {
        "GASTEIGER", "NO_CHARGES", "USER_CHARGES", "DEL_RE", "GASTEIGER-HUCKEL", "HUCKEL", "PULLMAN",
    }:
        raise RuntimeError("Converted MOL2 has an unsupported charge-type declaration")
    lines[charge_type_index] = "NO_CHARGES"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ligand_inspect(request_path: Path, output_dir: Path) -> dict[str, Any]:
    _parameters, inputs = _request(request_path, "ligand_inspect")
    path, format_name = _one_input(inputs)
    molecules, failures = _read_molecules(path, format_name)
    if not molecules:
        raise ToolInputError("No parseable ligand records were found")
    payload = {
        "detected_format": format_name,
        "molecule_count": len(molecules),
        "failed_record_indexes": failures,
        "molecules": [_molecule_metadata(molecule) for molecule in molecules],
    }
    target = output_dir / "inspection.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    warnings = [{"code": "record_parse_failed", "message": f"Record {index} could not be parsed"} for index in failures]
    return {"outputs": {"inspection": [{"path": target.name, "format": "json"}]}, "warnings": warnings}


def ligand_convert(request_path: Path, output_dir: Path) -> dict[str, Any]:
    parameters, inputs = _request(request_path, "ligand_convert")
    path, input_format = _one_input(inputs)
    output_format = parameters.get("output_format")
    if output_format not in {"sdf", "mol2"} or set(parameters) != {"output_format"}:
        raise ToolInputError("output_format must be sdf or mol2")
    if output_format == input_format:
        raise ToolInputError("Input and output formats must differ")
    molecules, failures = _read_molecules(path, input_format)
    if failures or len(molecules) != 1:
        raise ToolInputError("Neutral ligand conversion requires exactly one parseable molecule")
    before = _molecule_metadata(molecules[0])
    if not before["has_3d_coordinates"] or not before["coordinates_finite"]:
        raise ToolInputError("Ligand conversion requires existing finite 3D coordinates")
    if before["partial_charge_present"]:
        raise ToolInputError("Neutral ligand conversion does not accept an existing atom partial-charge model")
    target = output_dir / f"ligand.{output_format}"
    command = [
        "obabel", f"-i{input_format}", str(path), f"-o{output_format}", "-O", str(target),
        "--partialcharge", "none",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Open Babel conversion backend failed") from exc
    if completed.returncode != 0 or not target.is_file():
        raise RuntimeError("Open Babel could not convert the ligand representation")
    converted, converted_failures = _read_molecules(target, output_format)
    if converted_failures or len(converted) != 1:
        target.unlink(missing_ok=True)
        raise RuntimeError("Converted ligand did not pass parser verification")
    after = _molecule_metadata(converted[0])
    protected = (
        "atom_count", "heavy_atom_count", "formal_charge", "partial_charge_present",
        "has_3d_coordinates", "coordinates_finite",
    )
    if any(before[field] != after[field] for field in protected):
        target.unlink(missing_ok=True)
        raise RuntimeError("Conversion changed atom, charge, or coordinate semantics")
    if output_format == "mol2":
        _declare_uncharged_mol2(target)
    return {
        "outputs": {"ligand": [{"path": target.name, "format": output_format}]},
        "warnings": [],
        "backend": {"name": "openbabel", "version": "3.1.1", "mode": "representation_only"},
    }


TOOLS = {"ligand_inspect": ligand_inspect, "ligand_convert": ligand_convert}


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
        molecule = Chem.MolFromSmiles("CCO")
        completed = subprocess.run(["obabel", "-V"], capture_output=True, text=True, timeout=5, check=False)
        if molecule is None or completed.returncode != 0:
            raise RuntimeError("Chemistry parser/converter health probe failed")
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    response = TOOLS[args.tool](args.request, args.output)
    (args.output / ".tool-response.json").write_text(
        json.dumps(response, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
