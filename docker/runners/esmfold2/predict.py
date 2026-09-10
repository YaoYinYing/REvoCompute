#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

UPSTREAM_COMMIT = "bf343ba264b650dff7a073643725f9aaa1fdbe8d"
MODEL_REVISIONS = {
    "standard": "8fc3ff471022fdce52c77030685eb775de0c00a3",
    "fast": "c6c7958d63f5f2f1f0fed0bb9462316f8ccceea6",
}
ESMC_REVISION = "45b0fa5d7fb06faefbd5e3b89bdcef35d564e79a"
MODEL_REQUIRED_FILES = ("config.json", "model.safetensors")
ESMC_REQUIRED_FILES = (
    "config.json",
    "model.safetensors.index.json",
    "model-00001-of-00006.safetensors",
    "model-00002-of-00006.safetensors",
    "model-00003-of-00006.safetensors",
    "model-00004-of-00006.safetensors",
    "model-00005-of-00006.safetensors",
    "model-00006-of-00006.safetensors",
)
ASSET_SPECS = {
    "ccd.pkl": (417306584, "9ff44b1927c6b9198e38ffe0928706827a09a350c15530beeeabebfa88038fc5"),
    "standard/config.json": (2337, "e9ec2496ec433a1dce18627ed4bf3785b4ce0c1d69e4bb4663dad1ab895da012"),
    "standard/model.safetensors": (
        939505228,
        "138fd4350d6892b81ce6be7ff9bf5a93ae9d4d3751f46a27438a3f9f0dcefa0e",
    ),
    "fast/config.json": (2338, "d24456b797ddcfb60ac6c53621b550db5e14b1575ee2d9ab5a380eb5b09902f2"),
    "fast/model.safetensors": (
        755416924,
        "60ca19f2898188beba92944365f7b909efd9c99212f5018af75cc47cd9a6184a",
    ),
    "esmc-6b/config.json": (341, "c5566fab6a17fd674141331fe75de917b7904d99fb7a410d2b1593c21e576913"),
    "esmc-6b/model.safetensors.index.json": (
        97349,
        "6846456e20e6ee2c37461f7bfc21d316d69bdaf165b925691afcb39e583244da",
    ),
    "esmc-6b/model-00001-of-00006.safetensors": (
        4864457920,
        "bd90149ff223e6ac1a0cac6147a5ae0df20d3a21df4f65356a1f19cd14f4aa8a",
    ),
    "esmc-6b/model-00002-of-00006.safetensors": (
        4971211344,
        "f75e2144d8269fe2eb4b3e0823fb089b94f176d8024153e85b8fb573a42294fa",
    ),
    "esmc-6b/model-00003-of-00006.safetensors": (
        4863752992,
        "f699f01ecc9691d9c6470492765fe54b8b5d2e9f277c139e89427433ffdfe0b2",
    ),
    "esmc-6b/model-00004-of-00006.safetensors": (
        4971211344,
        "46add1b7be098bbfdc3073884851ba3057f1b33ea23a158b650a37007dabd13d",
    ),
    "esmc-6b/model-00005-of-00006.safetensors": (
        4863752992,
        "1e1cb62f060a34e18f54a31a76683ef888b8cec59e73315f5b31d25d45a1f88c",
    ),
    "esmc-6b/model-00006-of-00006.safetensors": (
        873762296,
        "56c73e13ae96e777ce65eee99364056069ef93b646470f352f83c5f1037b1b18",
    ),
}
VALID_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWYX")
MAX_TOTAL_RESIDUES = 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_fasta(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    header: str | None = None
    sequence: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(sequence)))
            header = line[1:].strip().split()[0] if line[1:].strip() else f"chain_{len(records) + 1}"
            sequence = []
        elif header is None:
            raise ValueError("FASTA sequence data appears before its header")
        else:
            sequence.append(line)
    if header is not None:
        records.append((header, "".join(sequence)))
    if not records:
        raise ValueError("Protein FASTA contains no records")
    seen: set[str] = set()
    normalized: list[tuple[str, str]] = []
    for index, (name, sequence_text) in enumerate(records, start=1):
        chain_id = name or f"chain_{index}"
        if chain_id in seen:
            raise ValueError(f"Protein FASTA contains duplicate record id: {chain_id}")
        seen.add(chain_id)
        sequence_text = sequence_text.replace(" ", "").upper().rstrip("*_")
        if not sequence_text:
            raise ValueError(f"Protein FASTA record {chain_id!r} is empty")
        invalid = sorted(set(sequence_text) - VALID_AMINO_ACIDS)
        if invalid:
            raise ValueError(f"Protein FASTA record {chain_id!r} contains unsupported residues: {''.join(invalid)}")
        normalized.append((chain_id, sequence_text))
    total = sum(len(sequence) for _, sequence in normalized)
    if total > MAX_TOTAL_RESIDUES:
        raise ValueError(f"Protein input exceeds the {MAX_TOTAL_RESIDUES}-residue service limit")
    return normalized


def task_inputs(manifest_path: Path) -> tuple[Path, Path | None]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("Task manifest must contain at least one input file")
    paths = [Path(item["path"]) for item in raw_files]
    fasta = paths[0]
    if fasta.suffix.lower() not in {".fasta", ".fa", ".faa"}:
        raise ValueError("The primary ESMFold 2 input must be a FASTA file")
    if not fasta.is_file():
        raise FileNotFoundError(f"Protein FASTA not found: {fasta}")
    if len(paths) > 2:
        raise ValueError("ESMFold 2 accepts at most one FASTA and one optional A3M")
    msa = paths[1] if len(paths) == 2 else None
    if msa is not None and (msa.suffix.lower() != ".a3m" or not msa.is_file()):
        raise ValueError("The optional second ESMFold 2 input must be an existing A3M file")
    return fasta, msa


def validate_assets(asset_root: Path, variant: str) -> tuple[Path, Path, Path, dict[str, Any]]:
    model_dir = asset_root / variant
    esmc_dir = asset_root / "esmc-6b"
    ccd_path = asset_root / "ccd.pkl"
    manifest_path = asset_root / "assets.json"
    missing = [str(model_dir / name) for name in MODEL_REQUIRED_FILES if not (model_dir / name).is_file()]
    missing.extend(str(esmc_dir / name) for name in ESMC_REQUIRED_FILES if not (esmc_dir / name).is_file())
    if not ccd_path.is_file():
        missing.append(str(ccd_path))
    if not manifest_path.is_file():
        missing.append(str(manifest_path))
    if missing:
        raise FileNotFoundError("ESMFold 2 assets are incomplete; missing: " + ", ".join(missing))
    asset_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "upstream_commit": UPSTREAM_COMMIT,
        "esmc_revision": ESMC_REVISION,
        "model_revisions": MODEL_REVISIONS,
    }
    for key, value in expected.items():
        if asset_manifest.get(key) != value:
            raise ValueError(f"ESMFold 2 asset manifest has unexpected {key}")
    required_paths = ["ccd.pkl", *(f"{variant}/{name}" for name in MODEL_REQUIRED_FILES)]
    required_paths.extend(f"esmc-6b/{name}" for name in ESMC_REQUIRED_FILES)
    recorded_files = asset_manifest.get("files")
    if not isinstance(recorded_files, dict):
        raise ValueError("ESMFold 2 asset manifest has no file inventory")
    for relative_path in required_paths:
        expected_size, expected_sha256 = ASSET_SPECS[relative_path]
        if recorded_files.get(relative_path) != {"size": expected_size, "sha256": expected_sha256}:
            raise ValueError(f"ESMFold 2 asset manifest has unexpected metadata for {relative_path}")
        path = asset_root / relative_path
        if path.stat().st_size != expected_size:
            raise ValueError(f"ESMFold 2 asset has unexpected size: {relative_path}")
        if sha256(path) != expected_sha256:
            raise ValueError(f"ESMFold 2 asset failed SHA-256 verification: {relative_path}")
    return model_dir, esmc_dir, ccd_path, asset_manifest


def normalized_a3m_query(path: Path) -> str:
    sequence: list[str] = []
    reading_query = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith(">"):
            if reading_query:
                break
            reading_query = True
        elif reading_query:
            sequence.append(
                "".join(character for character in line if not character.islower() and character not in "-.")
            )
    normalized = "".join(sequence).upper()
    if not normalized:
        raise ValueError("A3M contains no query sequence")
    return normalized


def _tensor_list(value: Any) -> Any:
    return value.detach().float().cpu().tolist() if value is not None else None


def write_sample(output_dir: Path, index: int, result: Any, include_embeddings: bool) -> dict[str, Any]:
    import numpy as np

    prefix = f"sample_{index:03d}"
    cif_path = output_dir / f"{prefix}.cif"
    cif_path.write_text(result.complex.to_mmcif(), encoding="utf-8")
    plddt = _tensor_list(result.plddt)
    if not plddt:
        raise RuntimeError(f"ESMFold 2 sample {index} did not contain pLDDT values")
    with (output_dir / f"{prefix}_plddt.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("token_index", "plddt"))
        writer.writerows((token_index, value) for token_index, value in enumerate(plddt, start=1))
    pae = _tensor_list(result.pae)
    if pae is None:
        raise RuntimeError(f"ESMFold 2 sample {index} did not contain a PAE matrix")
    (output_dir / f"{prefix}_pae.json").write_text(
        json.dumps({"pae": pae}, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    confidence = {
        "sample": index,
        "mean_plddt": sum(plddt) / len(plddt),
        "ptm": result.ptm,
        "iptm": result.iptm,
        "num_tokens": len(plddt),
    }
    (output_dir / f"{prefix}_confidence.json").write_text(
        json.dumps(confidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if include_embeddings:
        pair = result.output_embedding_pair_pooled
        if pair is None:
            raise RuntimeError("ESMFold 2 was asked for embeddings but returned none")
        np.savez_compressed(output_dir / f"{prefix}_embeddings.npz", pair_pooled=pair.float().cpu().numpy())
    return confidence


def run(args: argparse.Namespace) -> None:
    fasta_path, msa_path = task_inputs(args.task_manifest)
    sequences = read_fasta(fasta_path)
    if msa_path is not None and len(sequences) != 1:
        raise ValueError("An A3M can only be attached when the FASTA contains exactly one protein chain")
    if msa_path is not None and args.model_variant != "standard":
        raise ValueError("MSA conditioning requires model_variant=standard")
    model_dir, esmc_dir, ccd_path, asset_manifest = validate_assets(args.asset_root, args.model_variant)

    import torch
    from esm.models.esmfold2 import (
        ESMFold2InputBuilder,
        EsmFold2Config,
        EsmFold2Model,
        MSA,
        ProteinInput,
        StructurePredictionInput,
    )
    from esm.models.esmfold2.config import default_module_flags

    if not torch.cuda.is_available():
        raise RuntimeError("ESMFold 2 requires a CUDA GPU")
    msa = None
    if msa_path is not None:
        if normalized_a3m_query(msa_path) != sequences[0][1]:
            raise ValueError("A3M query sequence does not match the FASTA protein sequence")
        msa = MSA.from_a3m(msa_path, max_sequences=args.msa_max_depth)
    inputs = [
        ProteinInput(id=name, sequence=sequence, msa=msa if index == 0 else None)
        for index, (name, sequence) in enumerate(sequences)
    ]

    config = EsmFold2Config.from_pretrained(model_dir, **default_module_flags(model_dir))
    config.esmc_id = str(esmc_dir)
    model = EsmFold2Model.from_pretrained(
        model_dir,
        config=config,
        device="cuda",
        dtype=torch.bfloat16,
        esmc_precision="bf16",
    ).eval()
    model.set_kernel_backend(None if args.kernel_backend == "reference" else args.kernel_backend)
    builder = ESMFold2InputBuilder(ccd_cache=ccd_path)
    prediction_input = StructurePredictionInput(sequences=inputs)
    result = builder.fold(
        model,
        prediction_input,
        num_loops=args.num_loops,
        num_sampling_steps=args.num_sampling_steps,
        num_diffusion_samples=args.num_diffusion_samples,
        seed=args.seed,
        lm_dropout=args.lm_dropout,
        lm_mask_pct=args.lm_mask_pct,
        msa_max_depth=args.msa_max_depth,
        msa_column_mask_rate=args.msa_column_mask_rate,
        include_embeddings=args.include_embeddings,
        complex_id="esmfold2_prediction",
    )
    results = result if isinstance(result, list) else [result]
    if len(results) != args.num_diffusion_samples:
        raise RuntimeError(f"ESMFold 2 returned {len(results)} samples; expected {args.num_diffusion_samples}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries = [
        write_sample(args.output_dir, index, item, args.include_embeddings)
        for index, item in enumerate(results, start=1)
    ]
    record = {
        "input": {
            "fasta": fasta_path.name,
            "fasta_sha256": sha256(fasta_path),
            "msa": msa_path.name if msa_path else None,
            "msa_sha256": sha256(msa_path) if msa_path else None,
        },
        "chains": [{"id": name, "length": len(sequence)} for name, sequence in sequences],
        "parameters": {
            key: value
            for key, value in vars(args).items()
            if key not in {"task_manifest", "output_dir", "asset_root"}
        },
        "software": {"repository": "https://github.com/Biohub/esm", "commit": UPSTREAM_COMMIT, "version": "3.4.1"},
        "models": {
            "variant_revision": MODEL_REVISIONS[args.model_variant],
            "esmc_revision": ESMC_REVISION,
            "asset_manifest_sha256": sha256(args.asset_root / "assets.json"),
        },
        "samples": summaries,
    }
    (args.output_dir / "prediction.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline ESMFold 2 prediction")
    parser.add_argument("--task-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--model-variant", choices=tuple(MODEL_REVISIONS), default="fast")
    parser.add_argument("--num-loops", type=int, default=3)
    parser.add_argument("--num-sampling-steps", type=int, default=50)
    parser.add_argument("--num-diffusion-samples", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--lm-dropout", type=float, default=0.0)
    parser.add_argument("--lm-mask-pct", type=float, default=0.0)
    parser.add_argument("--msa-max-depth", type=int, default=1024)
    parser.add_argument("--msa-column-mask-rate", type=float, default=0.1)
    parser.add_argument("--kernel-backend", choices=("reference", "cuequivariance"), default="cuequivariance")
    parser.add_argument("--include-embeddings", action="store_true")
    return parser


def main() -> None:
    run(build_parser().parse_args())


if __name__ == "__main__":
    main()
