#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

SOURCE_REVISION = "e324f5f30dd0dae55d194ac6b4d18c772219c3ee"
ASSET_SHA256 = {
    "weights/ddg_regression/0.ckpt": "cdd2732dc88936270686bd52a52b7021f679055ead43baacc852e027578c08a8",
    "weights/ddg_regression/1.ckpt": "46d5353f33b29e63b75c98fab3c0aced687355cb399681fe75353bf5736f1313",
    "weights/ddg_regression/2.ckpt": "9a6f6b8b71e6e52f071fbe6e05b6ed9e0739641ed09973297b47d001e12bf54b",
    "weights/masked_modeling.ckpt": "3bc26cc5e6628cee5f9e28d59a5324598ec52ae68f687f404a9e240e6a2aa44c",
}
PPI_NAME = re.compile(r"^[A-Za-z0-9]{4}_[A-Za-z0-9]+_[A-Za-z0-9]+\.pdb$")
SUBSTITUTION = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY][A-Za-z0-9][+-]?[0-9]+[ACDEFGHIKLMNPQRSTVWY]$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_assets(asset_root: Path, mode: str) -> dict[str, str]:
    names = (
        ["weights/masked_modeling.ckpt"]
        if mode == "embed"
        else [f"weights/ddg_regression/{i}.ckpt" for i in range(3)]
    )
    checksums = {}
    for name in names:
        path = asset_root / name
        if not path.is_file():
            raise FileNotFoundError(f"PPIformer checkpoint is not provisioned: {path}")
        observed = sha256_file(path)
        if observed != ASSET_SHA256[name]:
            raise ValueError(f"SHA-256 mismatch for {path}: expected {ASSET_SHA256[name]}, got {observed}")
        checksums[name] = observed
    return checksums


def validate_ppi_path(path: Path) -> None:
    if not path.is_file() or path.suffix.lower() != ".pdb":
        raise ValueError("input must be one existing PDB file")
    if not PPI_NAME.fullmatch(path.name):
        raise ValueError("PDB filename must use <pdb-id>_<partner-1>_<partner-2>.pdb notation")


def parse_mutations(value: str) -> list[str]:
    variants = [item.strip() for item in re.split(r"[;\n]+", value) if item.strip()]
    if not variants:
        raise ValueError("at least one mutation variant is required")
    if len(variants) > 128:
        raise ValueError("at most 128 mutation variants are allowed")
    for variant in variants:
        substitutions = [item.strip() for item in variant.split(",")]
        if not 1 <= len(substitutions) <= 8 or any(not SUBSTITUTION.fullmatch(item) for item in substitutions):
            raise ValueError(f"invalid PPIformer mutation variant: {variant}")
    return variants


def pdb_residues(path: Path) -> list[tuple[str, str, str, str]]:
    residues = []
    seen = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 27 or line[16] not in {" ", "A"}:
            continue
        key = (line[21].strip(), line[22:26].strip(), line[26].strip())
        if key not in seen:
            seen.add(key)
            residues.append((*key, line[17:20].strip()))
    if not residues:
        raise ValueError("PDB contains no standard ATOM residues")
    return residues


def configure_cache(scratch_dir: Path) -> None:
    cache = scratch_dir / "pyg"
    cache.mkdir(parents=True, exist_ok=True)
    import ppiformer.data.dataset as dataset
    import ppiformer.definitions as definitions

    definitions.PPIFORMER_PYG_DATA_CACHE_DIR = cache
    dataset.PPIFORMER_PYG_DATA_CACHE_DIR = cache


def write_metadata(output_dir: Path, mode: str, input_path: Path, assets: dict[str, str], details: dict) -> None:
    metadata = {
        "mode": mode,
        "source_repository": "https://github.com/anton-bushuiev/PPIformer",
        "source_revision": SOURCE_REVISION,
        "model_record_doi": "10.5281/zenodo.12789167",
        "input": {"name": input_path.name, "sha256": sha256_file(input_path)},
        "checkpoint_sha256": assets,
        **details,
    }
    (output_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def run_ddg(args: argparse.Namespace) -> None:
    import torch
    from ppiformer.tasks.node import DDGPPIformer
    from ppiformer.utils.api import predict_ddg

    mutations = parse_mutations(args.mutations)
    checksums = validate_assets(args.asset_root, "ddg")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    models = [
        DDGPPIformer.load_from_checkpoint(
            args.asset_root / f"weights/ddg_regression/{index}.ckpt", map_location="cpu"
        )
        .eval()
        .to(device)
        for index in range(3)
    ]
    predictions = predict_ddg(models, args.input, mutations, impute=args.impute_missing).detach().cpu().numpy()
    with (args.output_dir / "ddg_predictions.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["mutation", "predicted_ddg_kcal_mol"])
        writer.writerows((mutation, float(value)) for mutation, value in zip(mutations, predictions, strict=True))
    write_metadata(
        args.output_dir,
        "ddg",
        args.input,
        checksums,
        {"device": str(device), "mutations": mutations, "impute_missing": args.impute_missing},
    )


def run_embed(args: argparse.Namespace) -> None:
    import numpy as np
    import torch
    from ppiformer.model.ppiformer import PPIformer
    from ppiformer.utils.api import embed

    checksums = validate_assets(args.asset_root, "embed")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = (
        PPIformer.load_from_checkpoint(args.asset_root / "weights/masked_modeling.ckpt", map_location="cpu")
        .eval()
        .to(device)
    )
    matrix = embed(model, ppi=args.input).detach().cpu().numpy()
    residues = pdb_residues(args.input)
    if matrix.ndim != 2 or matrix.shape[0] != len(residues):
        raise ValueError(f"embedding/residue row mismatch: {matrix.shape} versus {len(residues)} residues")
    np.save(args.output_dir / "residue_embeddings.npy", matrix, allow_pickle=False)
    pooled = matrix.mean(axis=0)
    np.save(args.output_dir / "interface_embedding.npy", pooled, allow_pickle=False)
    with (args.output_dir / "residue_index.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row", "chain", "residue_number", "insertion_code", "amino_acid", "embedding_norm"])
        for index, ((chain, number, insertion, amino_acid), vector) in enumerate(
            zip(residues, matrix, strict=True)
        ):
            writer.writerow([index, chain, number, insertion, amino_acid, float(np.linalg.norm(vector))])
    summary = {"residue_count": int(matrix.shape[0]), "embedding_dimension": int(matrix.shape[1]), "pooling": "mean"}
    (args.output_dir / "embedding_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_metadata(args.output_dir, "embed", args.input, checksums, {"device": str(device), **summary})


def parse_bool(value: str) -> bool:
    if value.lower() not in {"true", "false"}:
        raise argparse.ArgumentTypeError("expected true or false")
    return value.lower() == "true"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run PPIformer from provisioned checkpoints without network access.")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("ddg", "embed"):
        child = subparsers.add_parser(mode)
        child.add_argument("--input", type=Path, required=True)
        child.add_argument("--output-dir", type=Path, required=True)
        child.add_argument("--asset-root", type=Path, required=True)
        child.add_argument("--scratch-dir", type=Path, required=True)
    subparsers.choices["ddg"].add_argument("--mutations", required=True)
    subparsers.choices["ddg"].add_argument("--impute-missing", type=parse_bool, default=False)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    validate_ppi_path(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    configure_cache(args.scratch_dir)
    (run_ddg if args.mode == "ddg" else run_embed)(args)


if __name__ == "__main__":
    main()
