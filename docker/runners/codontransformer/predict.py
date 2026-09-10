#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict
from pathlib import Path

MODEL_FILES = (
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
MAX_PROTEIN_RESIDUES = 2046


def read_single_fasta(path: Path) -> tuple[str, str]:
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
            header = line[1:].strip() or "protein"
            sequence = []
        elif header is None:
            raise ValueError("FASTA sequence data appears before its header")
        else:
            sequence.append(line)
    if header is not None:
        records.append((header, "".join(sequence)))
    if len(records) != 1:
        raise ValueError("Codon optimization requires exactly one FASTA record")
    name, protein = records[0]
    protein = protein.replace(" ", "").upper().rstrip("*_")
    if not protein:
        raise ValueError("Protein sequence cannot be empty")
    if len(protein) > MAX_PROTEIN_RESIDUES:
        raise ValueError(
            f"Protein sequence exceeds the upstream {MAX_PROTEIN_RESIDUES}-residue inference limit"
        )
    return name, protein


def validate_model_dir(model_dir: Path) -> None:
    missing = [name for name in MODEL_FILES if not (model_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"CodonTransformer model directory is incomplete; missing: {', '.join(missing)}")


def write_results(output_dir: Path, input_name: str, predictions: list[object], parameters: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    fasta_lines = []
    for index, prediction in enumerate(predictions, start=1):
        record = asdict(prediction)
        record["rank"] = index
        records.append(record)
        fasta_lines.extend((f">{input_name}|codontransformer_{index}|organism={record['organism']}", record["predicted_dna"]))
    (output_dir / "optimized_sequences.fasta").write_text("\n".join(fasta_lines) + "\n", encoding="utf-8")
    payload = {"input_name": input_name, "parameters": parameters, "predictions": records}
    (output_dir / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline CodonTransformer inference")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--organism", required=True)
    parser.add_argument("--attention-type", choices=("original_full", "block_sparse"), default="original_full")
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--num-sequences", type=int, default=1)
    parser.add_argument("--match-protein", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    validate_model_dir(args.model_dir)
    input_name, protein = read_single_fasta(args.input)
    if args.deterministic and args.num_sequences != 1:
        raise ValueError("Deterministic inference produces exactly one sequence")

    import torch
    from transformers import AutoTokenizer, BigBirdForMaskedLM
    from CodonTransformer.CodonPrediction import predict_dna_sequence

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True)
    model = BigBirdForMaskedLM.from_pretrained(args.model_dir, local_files_only=True).to(torch.device("cpu"))
    prediction = predict_dna_sequence(
        protein=protein,
        organism=args.organism,
        device=torch.device("cpu"),
        tokenizer=tokenizer,
        model=model,
        attention_type=args.attention_type,
        deterministic=args.deterministic,
        temperature=args.temperature,
        top_p=args.top_p,
        num_sequences=args.num_sequences,
        match_protein=args.match_protein,
    )
    predictions = prediction if isinstance(prediction, list) else [prediction]
    parameters = {
        "organism": args.organism,
        "attention_type": args.attention_type,
        "deterministic": args.deterministic,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "num_sequences": args.num_sequences,
        "match_protein": args.match_protein,
        "seed": args.seed,
    }
    write_results(args.output_dir, input_name, predictions, parameters)


if __name__ == "__main__":
    main()
