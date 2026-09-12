#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

UPSTREAM_COMMIT = "b27d70054dec6ce2f5ceadf8977de3d3baf00663"
MODEL_NAME = "Pallatom"
CHECKPOINT_SHA256 = "57dff1c37cb1d99984ab664a7dc96e2a44afb100ea6f1f3c397dbe838124bc2f"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_checkpoint(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Pallatom checkpoint not found: {path}")
    actual = sha256_file(path)
    if actual != CHECKPOINT_SHA256:
        raise ValueError(f"Pallatom checkpoint SHA-256 mismatch: expected {CHECKPOINT_SHA256}, got {actual}")
    return actual


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic, offline Pallatom generation")
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--length", required=True, type=int, choices=range(16, 513), metavar="[16-512]")
    parser.add_argument("--num-samples", required=True, type=int, choices=range(1, 33), metavar="[1-32]")
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--diffusion-steps", required=True, type=int, choices=range(2, 501), metavar="[2-500]")
    parser.add_argument("--t-min", required=True, type=float)
    parser.add_argument("--t-max", required=True, type=float)
    parser.add_argument("--gamma", required=True, type=float)
    parser.add_argument("--step-scale", required=True, type=float)
    return parser


def validate_numeric_args(args: argparse.Namespace) -> None:
    if not 0 <= args.seed <= 4_294_967_295:
        raise ValueError("seed must be between 0 and 4294967295")
    if not 0 <= args.t_min < args.t_max <= 10:
        raise ValueError("noise levels must satisfy 0 <= t_min < t_max <= 10")
    if not 0 <= args.gamma <= 1:
        raise ValueError("gamma must be between 0 and 1")
    if not 0 < args.step_scale <= 10:
        raise ValueError("step_scale must be greater than 0 and at most 10")


def main() -> None:
    args = build_parser().parse_args()
    validate_numeric_args(args)
    checkpoint_sha256 = validate_checkpoint(args.checkpoint)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    import jax
    import numpy as np
    from alphafold.common.residue_constants import restypes_wo_x
    from modules.feature import save_all_pdb
    from modules.ref_features import atom14_to_atom37
    from modules.sampling import Sampler

    sampler = Sampler(
        T=args.diffusion_steps,
        sample_len=args.length,
        use_selfcond=True,
        add_noise_level=[args.t_min, args.t_max, args.gamma],
        step_scale=args.step_scale,
        is_training=False,
        params_dir=str(args.checkpoint.parent.parent),
        model_name=MODEL_NAME,
    )
    key = jax.random.PRNGKey(args.seed)
    aatype_to_residue = dict(enumerate(restypes_wo_x))
    fasta_lines: list[str] = []
    records: list[dict[str, object]] = []

    for sample_index in range(1, args.num_samples + 1):
        key, reference_key, sample_key = jax.random.split(key, 3)
        batch = sampler.prepare_batch(args.length)
        batch = sampler.SampleReference(batch, reference_key)
        _, trajectory = sampler.Sample(batch, key=sample_key)
        final_aa = np.asarray(jax.device_get(trajectory["seq_logits"][:, -1, :])).argmax(axis=-1)[: args.length]
        final_atom14 = np.asarray(jax.device_get(trajectory["px0"][:, -1, :]))[: args.length * 14]
        final_atom37 = atom14_to_atom37(final_aa, final_atom14.reshape(args.length, 14, 3))
        sequence = "".join(aatype_to_residue[int(index)] for index in final_aa)
        stem = f"design_{sample_index:04d}"
        pdb_path = Path(save_all_pdb(str(args.output_dir), final_aa, final_atom37, plddt_array=None, prefix=stem))
        fasta_lines.extend((f">{stem}|length={args.length}|seed={args.seed}", sequence))
        records.append(
            {
                "sample": sample_index,
                "sequence": sequence,
                "structure": pdb_path.name,
                "structure_sha256": sha256_file(pdb_path),
            }
        )

    (args.output_dir / "sample_seq.fasta").write_text("\n".join(fasta_lines) + "\n", encoding="utf-8")
    metadata = {
        "upstream_repository": "https://github.com/levinthal/Pallatom",
        "upstream_commit": UPSTREAM_COMMIT,
        "model_name": MODEL_NAME,
        "checkpoint_sha256": checkpoint_sha256,
        "parameters": {
            "length": args.length,
            "num_samples": args.num_samples,
            "seed": args.seed,
            "diffusion_steps": args.diffusion_steps,
            "t_min": args.t_min,
            "t_max": args.t_max,
            "gamma": args.gamma,
            "step_scale": args.step_scale,
        },
        "jax_version": jax.__version__,
        "backend": jax.default_backend(),
        "outputs": records,
    }
    (args.output_dir / "generation_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
