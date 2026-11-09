#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Convert one protein sequence into an upstream AlphaFold 3 JSON input.

The output describes a single protein chain with empty inline MSAs and no
templates, which selects the upstream single-sequence path: the pinned data
pipeline logs "Skipping MSA and template search" and materializes a
query-only MSA. Residue validation belongs to the Server's
``single_protein_sequence`` logical type and to upstream featurization; this
converter only parses the FASTA framing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def read_single_sequence(path: Path) -> str:
    """Return the residues of the one non-empty FASTA record in *path*."""
    headers = 0
    residues: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(">"):
            headers += 1
            if headers > 1:
                raise ValueError("input must contain exactly one FASTA record")
        else:
            if headers == 0:
                raise ValueError("sequence data appears before the first FASTA header")
            residues.append("".join(stripped.split()))
    if headers == 0:
        raise ValueError("input contains no FASTA record")
    sequence = "".join(residues)
    if not sequence:
        raise ValueError("the FASTA record has an empty sequence")
    return sequence


def output_name(path: Path) -> str:
    """Return a filesystem-safe job name derived from the FASTA stem."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem.strip()).strip("._-")
    return name or "sequence"


def build_document(sequence: str, name: str, model_seed: int) -> dict:
    return {
        "name": name,
        "modelSeeds": [model_seed],
        "sequences": [
            {
                "protein": {
                    "id": "A",
                    "sequence": sequence,
                    "unpairedMsa": "",
                    "pairedMsa": "",
                    "templates": [],
                }
            }
        ],
        "dialect": "alphafold3",
        "version": 1,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="single-record protein FASTA")
    parser.add_argument("output", type=Path, help="upstream AlphaFold 3 JSON to write")
    parser.add_argument("model_seed", type=int, help="model seed recorded in the JSON")
    args = parser.parse_args(argv)

    try:
        sequence = read_single_sequence(args.input)
    except (OSError, ValueError) as exc:
        print(f"sequence_to_json.py: {exc}", file=sys.stderr)
        return 1

    document = build_document(sequence, output_name(args.input), args.model_seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
