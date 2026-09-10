# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import json
from pathlib import Path

UPSTREAM_REVISION = "c7a5570a6be9f5c695126e27c804e77567209934"
ESM_REVISION = "2b369911bb5b4b0dda914521b9475cad1656b2ac"
ASSET_SHA256 = {
    "simplefold_1.6B.ckpt": "aaac2d73dcc59c61153c58a1d56e74a8ada9d6057d67000f7836f3c87325312b",
    "simplefold_3B.ckpt": "88d4c7a240bf3815cb35342b4ddc1128ac243a2ea0256eb8a4df1209125868b5",
    "plddt.ckpt": "cb32fa9cdc9e80406b793a8c09a929077534d9991a1d08f4c159d2e4ed81315f",
    "ccd.pkl": "2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--num-steps", required=True, type=int)
    parser.add_argument("--tau", required=True, type=float)
    parser.add_argument("--num-samples", required=True, type=int)
    parser.add_argument("--output-format", required=True, choices=("mmcif", "pdb"))
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--predict-plddt", required=True, choices=("true", "false"))
    parser.add_argument("--esm-model-sha256", required=True)
    parser.add_argument("--esm-regression-sha256", required=True)
    args = parser.parse_args()

    suffix = ".cif" if args.output_format == "mmcif" else ".pdb"
    structures = sorted(args.output_dir.glob(f"predictions_*/*_sampled_*{suffix}"))
    if len(structures) != args.num_samples:
        raise SystemExit(f"SimpleFold produced {len(structures)} structures; expected {args.num_samples}")
    if any(path.stat().st_size == 0 for path in structures):
        raise SystemExit("SimpleFold produced an empty structure file")
    confidence = sorted((args.output_dir / "confidence").glob("*.json"))
    if args.predict_plddt == "true" and len(confidence) != args.num_samples:
        raise SystemExit(f"SimpleFold produced {len(confidence)} confidence files; expected {args.num_samples}")
    if args.predict_plddt == "false" and confidence:
        raise SystemExit("SimpleFold produced confidence artifacts although pLDDT was disabled")
    if not (args.output_dir / "manifest.json").is_file() or not any((args.output_dir / "records").glob("*.json")):
        raise SystemExit("SimpleFold did not preserve its processed-input manifest and record")

    asset_sha256 = {
        f"{args.model}.ckpt": ASSET_SHA256[f"{args.model}.ckpt"],
        "ccd.pkl": ASSET_SHA256["ccd.pkl"],
        "esm2_t36_3B_UR50D.pt": args.esm_model_sha256,
        "esm2_t36_3B_UR50D-contact-regression.pt": args.esm_regression_sha256,
    }
    if args.predict_plddt == "true":
        asset_sha256["simplefold_1.6B.ckpt"] = ASSET_SHA256["simplefold_1.6B.ckpt"]
        asset_sha256["plddt.ckpt"] = ASSET_SHA256["plddt.ckpt"]
    metadata = {
        "runner": "simplefold",
        "upstream_revision": UPSTREAM_REVISION,
        "esm_revision": ESM_REVISION,
        "model": args.model,
        "parameters": {
            "num_steps": args.num_steps,
            "tau": args.tau,
            "num_samples": args.num_samples,
            "predict_plddt": args.predict_plddt == "true",
            "output_format": args.output_format,
            "seed": args.seed,
        },
        "asset_sha256": asset_sha256,
        "structures": [str(path.relative_to(args.output_dir)) for path in structures],
        "confidence": [str(path.relative_to(args.output_dir)) for path in confidence],
    }
    (args.output_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
