# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pinned SimpleFold inference with provisioned assets only.")
    parser.add_argument("--fasta-path", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--checkpoint-dir", required=True, type=Path)
    parser.add_argument("--ccd-path", required=True, type=Path)
    parser.add_argument("--model", required=True, choices=("simplefold_1.6B", "simplefold_3B"))
    parser.add_argument("--num-steps", required=True, type=int)
    parser.add_argument("--tau", required=True, type=float)
    parser.add_argument("--num-samples", required=True, type=int)
    parser.add_argument("--output-format", required=True, choices=("mmcif", "pdb"))
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--plddt", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # SimpleFold's public inference helper otherwise downloads a CCD and an unused
    # Boltz confidence checkpoint. Route parsing directly to the provisioned CCD.
    from simplefold import inference

    process_fastas = inference.process_fastas

    def process_fastas_offline(*, data, out_dir, ccd_path) -> None:  # noqa: ARG001
        process_fastas(data=data, out_dir=out_dir, ccd_path=args.ccd_path)

    save_structure = inference.save_structure
    confidence_dir = args.output_dir / "confidence"

    def save_structure_with_confidence(structure, save_dir, outname, output_format="mmcif", plddts=None) -> None:
        save_structure(structure, save_dir, outname, output_format=output_format, plddts=plddts)
        if plddts is None:
            return
        values = plddts.detach().cpu().tolist() if hasattr(plddts, "detach") else list(plddts)
        confidence_dir.mkdir(parents=True, exist_ok=True)
        (confidence_dir / f"{outname}.json").write_text(
            json.dumps({"confidenceScore": values, "meanPlddt": sum(values) / len(values)}, indent=2) + "\n",
            encoding="utf-8",
        )

    inference.download_fasta_utilities = lambda cache: None
    inference.process_fastas = process_fastas_offline
    inference.save_structure = save_structure_with_confidence
    upstream_args = argparse.Namespace(
        simplefold_model=args.model,
        ckpt_dir=str(args.checkpoint_dir),
        output_dir=str(args.output_dir),
        num_steps=args.num_steps,
        tau=args.tau,
        no_log_timesteps=False,
        fasta_path=str(args.fasta_path),
        nsample_per_protein=args.num_samples,
        plddt=args.plddt,
        output_format=args.output_format,
        backend="torch",
        seed=args.seed,
    )
    inference.predict_structures_from_fastas(upstream_args)


if __name__ == "__main__":
    main()
