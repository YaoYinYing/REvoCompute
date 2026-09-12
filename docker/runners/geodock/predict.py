#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def _confidence_from_pdb(path: Path) -> dict[str, object]:
    residues: dict[tuple[str, str, str], float] = {}
    with path.open("r", encoding="ascii") as handle:
        for line in handle:
            if line.startswith("ATOM  ") and line[12:16].strip() == "CA":
                residues[(line[21:22].strip(), line[22:26].strip(), line[26:27].strip())] = float(line[60:66])
    if not residues:
        raise RuntimeError("GeoDock output contains no CA confidence records")
    values = list(residues.values())
    chains: dict[str, list[float]] = {}
    records = []
    for (chain, residue, insertion), value in residues.items():
        chains.setdefault(chain, []).append(value)
        records.append({"chain": chain, "residue": residue + insertion, "confidence": value})
    return {
        "metric": "predicted_lddt_ca",
        "scale": [0, 100],
        "mean": sum(values) / len(values),
        "chain_means": {chain: sum(scores) / len(scores) for chain, scores in chains.items()},
        "residues": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--partner-a", required=True, type=Path)
    parser.add_argument("--partner-b", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--esm-checkpoint", required=True, type=Path)
    parser.add_argument("--refine", action="store_true")
    parser.add_argument("--refinement-stiffness", required=True, type=float)
    parser.add_argument("--refinement-tolerance", required=True, type=float)
    args = parser.parse_args()

    import esm
    import torch
    from esm.inverse_folding.util import load_coords
    from geodock.model.GeoDock import GeoDock
    from geodock.utils.docking import dock
    from geodock.utils.embed import embed

    regression = args.esm_checkpoint.with_name(args.esm_checkpoint.stem + "-contact-regression.pt")
    if not regression.is_file():
        raise SystemExit(f"ESM2 contact-regression sidecar is missing: {regression}")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type != "cuda":
        raise SystemExit("GeoDock requires a CUDA device")

    esm_model, alphabet = esm.pretrained.load_model_and_alphabet_local(str(args.esm_checkpoint))
    esm_model.eval().to(device)
    model = GeoDock.load_from_checkpoint(str(args.checkpoint), map_location=device).eval().to(device)
    coords_a, seq_a = load_coords(str(args.partner_a), chain=None)
    coords_b, seq_b = load_coords(str(args.partner_b), chain=None)
    model_input = embed(
        seq_a, seq_b, torch.nan_to_num(torch.from_numpy(coords_a)), torch.nan_to_num(torch.from_numpy(coords_b)),
        esm_model, alphabet.get_batch_converter(), device,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    dock("geodock_raw", seq_a, seq_b, model_input, model, do_refine=False, use_openmm=True)
    raw_pose = args.output_dir / "geodock_raw.pdb"
    if not raw_pose.is_file():
        raise RuntimeError("GeoDock did not write the expected raw pose")
    (args.output_dir / "geodock-confidence.json").write_text(
        json.dumps(_confidence_from_pdb(raw_pose), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.refine:
        from geodock.refine.openmm_ref import refine

        refined = args.output_dir / "geodock_refined.pdb"
        shutil.copy2(raw_pose, refined)
        refine(
            str(refined), stiffness=args.refinement_stiffness, tolerance=args.refinement_tolerance,
            use_gpu=False,
        )


if __name__ == "__main__":
    main()
