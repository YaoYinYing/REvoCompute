# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic, dependency-free protein sequence statistics."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from typing import Iterable


# Average residue masses in a polypeptide chain, in daltons. Molecular weight
# adds one water molecule for the termini. Ambiguous symbols use constituent
# averages; X uses the unweighted average of the 20 canonical residues.
RESIDUE_MASSES = {
    "A": 71.0788,
    "C": 103.1388,
    "D": 115.0886,
    "E": 129.1155,
    "F": 147.1766,
    "G": 57.0519,
    "H": 137.1411,
    "I": 113.1594,
    "K": 128.1741,
    "L": 113.1594,
    "M": 131.1926,
    "N": 114.1038,
    "P": 97.1167,
    "Q": 128.1307,
    "R": 156.1875,
    "S": 87.0782,
    "T": 101.1051,
    "V": 99.1326,
    "W": 186.2132,
    "Y": 163.1760,
    "U": 150.0388,
    "O": 237.3018,
}
RESIDUE_MASSES["B"] = (RESIDUE_MASSES["D"] + RESIDUE_MASSES["N"]) / 2
RESIDUE_MASSES["Z"] = (RESIDUE_MASSES["E"] + RESIDUE_MASSES["Q"]) / 2
RESIDUE_MASSES["J"] = (RESIDUE_MASSES["I"] + RESIDUE_MASSES["L"]) / 2
RESIDUE_MASSES["X"] = sum(RESIDUE_MASSES[code] for code in "ACDEFGHIKLMNPQRSTVWY") / 20
WATER_MASS = 18.01528


def read_fasta(path: Path) -> list[tuple[str, str]]:
    """Read non-aligned protein FASTA records and return stable record IDs."""
    records: list[tuple[str, str]] = []
    identifier: str | None = None
    sequence: list[str] = []
    seen_ids: set[str] = set()

    def finish_record() -> None:
        if identifier is None:
            return
        joined = "".join(sequence).replace(" ", "").upper()
        if not joined:
            raise ValueError(f"FASTA record {identifier!r} contains no residues")
        unsupported = sorted(set(joined) - set(RESIDUE_MASSES))
        if unsupported:
            symbols = "".join(unsupported)
            raise ValueError(f"FASTA record {identifier!r} contains unsupported residue symbols: {symbols}")
        records.append((identifier, joined))

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            finish_record()
            header = line[1:].strip()
            if not header:
                raise ValueError(f"FASTA header on line {line_number} has no identifier")
            identifier = header.split()[0]
            if identifier in seen_ids:
                raise ValueError(f"FASTA identifier {identifier!r} is duplicated")
            seen_ids.add(identifier)
            sequence = []
        elif identifier is None:
            raise ValueError(f"Sequence data on line {line_number} precedes the first FASTA header")
        else:
            sequence.append("".join(line.split()))
    finish_record()
    if not records:
        raise ValueError("FASTA input contains no records")
    return records


def sequence_statistics(identifier: str, sequence: str, *, mass_precision: int) -> dict[str, object]:
    counts = Counter(sequence)
    composition = {code: counts[code] for code in sorted(counts)}
    molecular_weight = round(WATER_MASS + sum(RESIDUE_MASSES[code] for code in sequence), mass_precision)
    return {
        "sequence_id": identifier,
        "length": len(sequence),
        "molecular_weight_da": molecular_weight,
        "aa_composition": composition,
    }


def write_results(output_dir: Path, statistics: Iterable[dict[str, object]], *, mass_precision: int) -> None:
    rows = list(statistics)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "sequence_statistics.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("sequence_id", "length", "molecular_weight_da", "aa_composition"),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            composition = json.dumps(row["aa_composition"], sort_keys=True, separators=(",", ":"))
            writer.writerow({**row, "aa_composition": composition})
    lengths = [int(row["length"]) for row in rows]
    summary = {
        "schema_version": 1,
        "parameters": {"mass_precision": mass_precision},
        "sequence_count": len(rows),
        "total_residues": sum(lengths),
        "minimum_length": min(lengths),
        "maximum_length": max(lengths),
        "sequences": rows,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mass-precision", type=int, choices=range(0, 7), default=2)
    args = parser.parse_args(argv)
    records = read_fasta(args.input)
    statistics = [
        sequence_statistics(identifier, sequence, mass_precision=args.mass_precision)
        for identifier, sequence in records
    ]
    write_results(args.output_dir, statistics, mass_precision=args.mass_precision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
