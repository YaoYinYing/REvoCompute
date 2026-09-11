#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

TASK_TYPES = {"rfdiffusion2_motif_scaffold", "rfdiffusion2_ligand_binder"}
CONTIG_RE = re.compile(r"(?:[0-9]+(?:-[0-9]+)?|[A-Za-z][1-9][0-9]*-[1-9][0-9]*)(?:,(?:[0-9]+(?:-[0-9]+)?|[A-Za-z][1-9][0-9]*-[1-9][0-9]*))*")
RESIDUE_RE = re.compile(r"[A-Za-z][1-9][0-9]*")
ATOM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9']{0,3}(?:,[A-Za-z0-9][A-Za-z0-9']{0,3})*")
LIGAND_RE = re.compile(r"[A-Za-z0-9]{1,3}(?:,[A-Za-z0-9]{1,3})*")


def _die(message: str) -> None:
    raise SystemExit(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parameter(params: dict[str, Any], name: str, expected: type, default: Any = None) -> Any:
    value = params.get(name, default)
    if expected is int and (not isinstance(value, int) or isinstance(value, bool)):
        _die(f"Parameter {name} must be an integer")
    if expected is float and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        _die(f"Parameter {name} must be a number")
    if expected is bool and not isinstance(value, bool):
        _die(f"Parameter {name} must be a boolean")
    if expected is str and not isinstance(value, str):
        _die(f"Parameter {name} must be a string")
    return value


def _load_manifest(path: Path) -> tuple[Path, dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _die(f"Invalid task manifest: {exc}")
    files = document.get("files")
    params = document.get("params", {})
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        _die("RFdiffusion2 requires exactly one input PDB")
    if not isinstance(params, dict):
        _die("Task params must be an object")
    input_path = Path(files[0].get("path", "")).resolve()
    if input_path.suffix.lower() != ".pdb" or not input_path.is_file():
        _die("RFdiffusion2 input must be an existing PDB file")
    return input_path, params


def _validate_pdb(path: Path) -> None:
    has_atom = False
    has_ori = False
    try:
        with path.open("r", encoding="ascii") as handle:
            for line in handle:
                if line.startswith(("ATOM  ", "HETATM")):
                    has_atom = True
                if line.startswith("HETATM") and (line[12:16].strip() == "ORI" or line[17:20].strip() == "ORI"):
                    has_ori = True
    except UnicodeDecodeError:
        _die("RFdiffusion2 input PDB must be ASCII text")
    if not has_atom:
        _die("RFdiffusion2 input PDB contains no atoms")
    if not has_ori:
        _die("RFdiffusion2 input PDB must contain an ORI HETATM centering token")


def _common_overrides(params: dict[str, Any], input_path: Path, output_dir: Path, checkpoint: Path) -> list[str]:
    num_designs = _parameter(params, "num_designs", int, 1)
    diffusion_steps = _parameter(params, "diffusion_steps", int, 100)
    num_recycles = _parameter(params, "num_recycles", int, 1)
    seed = _parameter(params, "seed", int, 0)
    write_trajectory = _parameter(params, "write_trajectory", bool, False)
    if not 1 <= num_designs <= 10:
        _die("num_designs must be between 1 and 10")
    if not 1 <= diffusion_steps <= 100:
        _die("diffusion_steps must be between 1 and 100")
    if not 1 <= num_recycles <= 4:
        _die("num_recycles must be between 1 and 4")
    if not 0 <= seed <= 2_147_483_647:
        _die("seed must be between 0 and 2147483647")
    return [
        f"inference.input_pdb={input_path}",
        f"inference.output_prefix={output_dir / 'design'}",
        f"inference.ckpt_path={checkpoint}",
        f"inference.num_designs={num_designs}",
        "inference.design_startnum=0",
        f"inference.seed_offset={seed}",
        "inference.deterministic=True",
        "inference.cautious=False",
        f"inference.num_recycles={num_recycles}",
        "inference.silent_out=False",
        "inference.write_trb=True",
        "inference.write_trb_indep=False",
        "inference.write_trb_trajectory=False",
        f"inference.write_trajectory={str(write_trajectory)}",
        "inference.idealize_sidechain_outputs=False",
        f"diffuser.T={diffusion_steps}",
    ]


def _motif_overrides(params: dict[str, Any]) -> list[str]:
    contig = _parameter(params, "contig", str)
    ligand = _parameter(params, "ligand", str, "")
    placement = _parameter(params, "motif_placement", str, "unindexed")
    contig_atoms = _parameter(params, "contig_atoms", str, "")
    if not CONTIG_RE.fullmatch(contig):
        _die("contig must be a comma-separated RFdiffusion2 contig specification")
    if ligand and not LIGAND_RE.fullmatch(ligand):
        _die("ligand must contain comma-separated one-to-three-character residue names")
    if placement not in {"indexed", "unindexed"}:
        _die("motif_placement must be indexed or unindexed")
    normalized_atoms: dict[str, str] = {}
    if len(contig_atoms) > 4096:
        _die("contig_atoms must contain at most 4096 characters")
    if contig_atoms:
        for entry in re.split(r";|\r?\n", contig_atoms):
            if ":" not in entry:
                _die("contig_atoms entries must use residue:atoms syntax such as A106:NE,CD,CZ")
            residue, atoms = entry.split(":", 1)
            if not RESIDUE_RE.fullmatch(residue):
                _die("contig_atoms residues must be chain-qualified identifiers such as A106")
            if not ATOM_RE.fullmatch(atoms):
                _die("contig_atoms atom selections must be comma-separated atom names")
            if residue in normalized_atoms:
                _die(f"contig_atoms contains duplicate residue {residue}")
            normalized_atoms[residue] = atoms
    overrides = [
        f"contigmap.contigs={json.dumps([contig], separators=(',', ':'))}",
        f"inference.contig_as_guidepost={str(placement == 'unindexed')}",
        "inference.guidepost_xyz_as_design=True",
        "inference.guidepost_xyz_as_design_bb=[True]",
    ]
    if ligand:
        overrides.append(f"inference.ligand={ligand.upper()}")
    if normalized_atoms:
        overrides.append(f"contigmap.contig_atoms={json.dumps(normalized_atoms, separators=(',', ':'))}")
    return overrides


def _binder_overrides(params: dict[str, Any]) -> list[str]:
    ligand = _parameter(params, "ligand", str)
    length = _parameter(params, "length", int, 150)
    relative_sasa = float(_parameter(params, "relative_sasa", float, 0.0))
    if not LIGAND_RE.fullmatch(ligand):
        _die("ligand must contain comma-separated one-to-three-character residue names")
    if not 40 <= length <= 256:
        _die("length must be between 40 and 256")
    if not 0.0 <= relative_sasa <= 1.0:
        _die("relative_sasa must be between 0 and 1")
    return [
        f"inference.ligand={ligand.upper()}",
        f"contigmap.contigs=[{length}]",
        f"contigmap.length={length}-{length}",
        "inference.contig_as_guidepost=False",
        "inference.conditions.relative_sasa_v2.active=True",
        f"inference.conditions.relative_sasa_v2.rasa={relative_sasa:g}",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-type", required=True, choices=sorted(TASK_TYPES))
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    args = parser.parse_args()

    input_path, params = _load_manifest(args.manifest)
    _validate_pdb(input_path)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    overrides = _common_overrides(params, input_path, args.output_dir.resolve(), args.checkpoint.resolve())
    if args.task_type == "rfdiffusion2_motif_scaffold":
        overrides.extend(_motif_overrides(params))
    else:
        overrides.extend(_binder_overrides(params))

    source_root = Path(os.environ.get("RFDIFFUSION2_SOURCE_ROOT", "/opt/rfdiffusion2")).resolve()
    inference_script = Path(os.environ.get("RFDIFFUSION2_INFERENCE", source_root / "rf_diffusion/run_inference.py"))
    if not inference_script.is_file():
        _die(f"RFdiffusion2 inference script is missing: {inference_script}")
    command = [os.environ.get("RFDIFFUSION2_UPSTREAM_PYTHON", "python3"), str(inference_script), "--config-name=aa", *overrides]
    provenance = {
        "task_type": args.task_type,
        "input": {"name": input_path.name, "sha256": _sha256(input_path)},
        "checkpoint": {"name": args.checkpoint.name, "sha256": _sha256(args.checkpoint)},
        "parameters": params,
        "upstream_commit": "d365cbf4db3958814a9f8e4f6f94fa309dfebc2b",
        "runtime_network": False,
    }
    (args.output_dir / "rfdiffusion2-run.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    completed = subprocess.run(command, cwd=source_root, check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
