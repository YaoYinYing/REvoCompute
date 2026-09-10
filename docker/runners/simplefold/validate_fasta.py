# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import sys
from pathlib import Path

ALLOWED_RESIDUES = frozenset("ACDEFGHIKLMNPQRSTVWYX")
MAX_RESIDUES = 1022


def read_single_sequence(path: Path) -> str:
    records: list[tuple[str, list[str]]] = []
    header: str | None = None
    sequence: list[str] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if not line[1:].strip():
                raise ValueError(f"FASTA header on line {line_number} is empty")
            if header is not None:
                records.append((header, sequence))
            header = line[1:].strip()
            sequence = []
            continue
        if header is None:
            raise ValueError(f"sequence data precedes the FASTA header on line {line_number}")
        sequence.append("".join(line.split()).upper())
    if header is not None:
        records.append((header, sequence))
    if len(records) != 1:
        raise ValueError(f"SimpleFold requires exactly one FASTA record; found {len(records)}")
    value = "".join(records[0][1])
    if not value:
        raise ValueError("FASTA record contains no residues")
    invalid = sorted(set(value) - ALLOWED_RESIDUES)
    if invalid:
        raise ValueError(f"unsupported protein residue symbols: {''.join(invalid)}")
    if len(value) > MAX_RESIDUES:
        raise ValueError(f"sequence has {len(value)} residues; the supported maximum is {MAX_RESIDUES}")
    return value


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} <input.fasta>", file=sys.stderr)
        return 2
    try:
        sequence = read_single_sequence(Path(sys.argv[1]))
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Invalid SimpleFold FASTA: {exc}", file=sys.stderr)
        return 1
    print(len(sequence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
