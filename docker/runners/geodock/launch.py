#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

SOURCE_COMMIT = "df8d1f4c24ae2946655f27e7411ba2ffabf3d350"


def _die(message: str) -> None:
    raise SystemExit(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parameter(params: dict[str, Any], name: str, expected: type, default: Any) -> Any:
    value = params.get(name, default)
    if expected is bool and not isinstance(value, bool):
        _die(f"Parameter {name} must be a boolean")
    if expected is float and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        _die(f"Parameter {name} must be a number")
    if expected is str and not isinstance(value, str):
        _die(f"Parameter {name} must be a string")
    return value


def _load_manifest(path: Path) -> tuple[list[Path], dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _die(f"Invalid task manifest: {exc}")
    files = document.get("files")
    params = document.get("params", {})
    if not isinstance(files, list) or len(files) != 2 or not all(isinstance(item, dict) for item in files):
        _die("GeoDock requires exactly two ordered input PDB files")
    if not isinstance(params, dict):
        _die("Task params must be an object")
    paths = [Path(item.get("path", "")).resolve() for item in files]
    if paths[0] == paths[1]:
        _die("GeoDock partner inputs must be different files")
    for path in paths:
        if path.suffix.lower() != ".pdb" or not path.is_file():
            _die("Each GeoDock input must be an existing PDB file")
    return paths, params


def _validate_pdb(path: Path) -> int:
    residues: set[tuple[str, str, str]] = set()
    try:
        with path.open("r", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("ATOM  "):
                    residues.add((line[21:22], line[22:26], line[26:27]))
    except UnicodeDecodeError:
        _die(f"GeoDock input must be ASCII PDB text: {path.name}")
    if len(residues) < 3:
        _die(f"GeoDock partner must contain at least three protein residues: {path.name}")
    if len(residues) > 1022:
        _die(f"GeoDock partner exceeds the ESM2 limit of 1022 residues: {path.name}")
    return len(residues)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    args = parser.parse_args()

    partners, params = _load_manifest(args.manifest)
    unknown = sorted(set(params) - {"refine", "refinement_stiffness", "refinement_tolerance"})
    if unknown:
        _die(f"Unsupported GeoDock parameters: {', '.join(unknown)}")
    residue_counts = [_validate_pdb(path) for path in partners]
    if sum(residue_counts) > 1022:
        _die("GeoDock supports at most 1022 total residues across both partners")

    refine = _parameter(params, "refine", bool, False)
    stiffness = float(_parameter(params, "refinement_stiffness", float, 10.0))
    tolerance = float(_parameter(params, "refinement_tolerance", float, 2.39))
    if not 0.1 <= stiffness <= 100.0:
        _die("refinement_stiffness must be between 0.1 and 100")
    if not 0.1 <= tolerance <= 10.0:
        _die("refinement_tolerance must be between 0.1 and 10")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    asset_root = args.asset_root.resolve()
    checkpoint = asset_root / "dips_0.3.ckpt"
    esm_checkpoint = asset_root / "esm2_t33_650M_UR50D.pt"
    predictor = Path(os.environ.get("GEODOCK_PREDICTOR", "/app/revocompute/predict.py"))
    if not predictor.is_file():
        _die(f"GeoDock predictor is missing: {predictor}")
    command = [
        os.environ.get("GEODOCK_UPSTREAM_PYTHON", "python3"), str(predictor),
        "--partner-a", str(partners[0]), "--partner-b", str(partners[1]),
        "--output-dir", str(args.output_dir.resolve()), "--checkpoint", str(checkpoint),
        "--esm-checkpoint", str(esm_checkpoint), "--refinement-stiffness", f"{stiffness:g}",
        "--refinement-tolerance", f"{tolerance:g}",
    ]
    if refine:
        command.append("--refine")

    provenance = {
        "task_type": "geodock",
        "upstream_commit": SOURCE_COMMIT,
        "runtime_network": False,
        "partners": [
            {"role": role, "name": path.name, "sha256": _sha256(path), "residues": count}
            for role, path, count in zip(("A", "B"), partners, residue_counts, strict=True)
        ],
        "assets": {
            name: {"sha256": _sha256(asset_root / name)}
            for name in ("dips_0.3.ckpt", "esm2_t33_650M_UR50D.pt", "esm2_t33_650M_UR50D-contact-regression.pt")
        },
        "parameters": {
            "refine": refine,
            "refinement_stiffness": stiffness,
            "refinement_tolerance": tolerance,
        },
    }
    (args.output_dir / "geodock-run.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    completed = subprocess.run(command, cwd=args.output_dir, check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
