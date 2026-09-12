# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

UPSTREAM_COMMIT = "8d5ac0f93e9b6ea4c3a6545c253a6381c0f3694b"
UPSTREAM_VERSION = "0.6.1"


def _json_value(value: Any) -> Any:
    converted = value.tolist() if hasattr(value, "tolist") else value
    if isinstance(converted, list) and len(converted) == 1:
        return converted[0]
    return converted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pinned Chai-1 inference without network services")
    parser.add_argument("--fasta-file", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--msa-directory", type=Path)
    parser.add_argument("--constraint-path", type=Path)
    parser.add_argument("--use-esm-embeddings", action="store_true")
    parser.add_argument("--recycle-msa-subsample", required=True, type=int)
    parser.add_argument("--num-trunk-recycles", required=True, type=int)
    parser.add_argument("--num-diffusion-timesteps", required=True, type=int)
    parser.add_argument("--num-diffusion-samples", required=True, type=int)
    parser.add_argument("--num-trunk-samples", required=True, type=int)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--low-memory", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.environ["CHAI_DOWNLOADS_DIR"] = str(args.asset_root)

    import numpy as np
    from chai_lab.chai1 import run_inference
    from chai_lab.ranking.rank import get_scores

    args.output_dir.mkdir(parents=True, exist_ok=True)
    upstream_dir = args.output_dir / "upstream"
    upstream_dir.mkdir()
    candidates = run_inference(
        args.fasta_file,
        output_dir=upstream_dir,
        use_esm_embeddings=args.use_esm_embeddings,
        use_msa_server=False,
        msa_directory=args.msa_directory,
        constraint_path=args.constraint_path,
        use_templates_server=False,
        template_hits_path=None,
        recycle_msa_subsample=args.recycle_msa_subsample,
        num_trunk_recycles=args.num_trunk_recycles,
        num_diffn_timesteps=args.num_diffusion_timesteps,
        num_diffn_samples=args.num_diffusion_samples,
        num_trunk_samples=args.num_trunk_samples,
        seed=args.seed,
        device="cuda:0",
        low_memory=args.low_memory,
    ).sorted()

    ranked_dir = args.output_dir / "ranked"
    ranked_dir.mkdir()
    ranking: list[dict[str, Any]] = []
    for index, (cif_path, ranking_data) in enumerate(zip(candidates.cif_paths, candidates.ranking_data, strict=True)):
        ranked_path = ranked_dir / f"rank_{index}.model_idx_{cif_path.stem.rsplit('_', 1)[-1]}.cif"
        shutil.copyfile(cif_path, ranked_path)
        scores = {key: _json_value(value) for key, value in get_scores(ranking_data).items()}
        confidence_path = args.output_dir / f"confidence.rank_{index}.json"
        confidence_path.write_text(json.dumps(scores, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        np.save(args.output_dir / f"pae.rank_{index}.npy", candidates.pae[index].cpu().numpy())
        np.save(args.output_dir / f"pde.rank_{index}.npy", candidates.pde[index].cpu().numpy())
        np.save(args.output_dir / f"plddt.rank_{index}.npy", candidates.plddt[index].cpu().numpy())
        ranking.append({"rank": index, "structure": str(ranked_path.relative_to(args.output_dir)), **scores})

    if candidates.msa_coverage_plot_path is not None:
        shutil.copyfile(candidates.msa_coverage_plot_path, args.output_dir / "msa_depth.pdf")
    (args.output_dir / "ranking.json").write_text(
        json.dumps(ranking, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    metadata = {
        "runner": "chai1",
        "upstream_version": UPSTREAM_VERSION,
        "upstream_commit": UPSTREAM_COMMIT,
        "runtime_network": False,
        "parameters": {
            "use_esm_embeddings": args.use_esm_embeddings,
            "use_msa": args.msa_directory is not None,
            "use_restraints": args.constraint_path is not None,
            "recycle_msa_subsample": args.recycle_msa_subsample,
            "num_trunk_recycles": args.num_trunk_recycles,
            "num_diffusion_timesteps": args.num_diffusion_timesteps,
            "num_diffusion_samples": args.num_diffusion_samples,
            "num_trunk_samples": args.num_trunk_samples,
            "seed": args.seed,
            "low_memory": args.low_memory,
        },
    }
    (args.output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
