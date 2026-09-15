# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Reusable logical input profiles, separate from file-format parsing."""

from __future__ import annotations

from revocompute.input_validators.common import _read_text


def validate_logical_input(path: str, format_name: str, logical_type: str) -> str | None:
    if logical_type == "protein_structure":
        text, error = _read_text(path, kind="protein structure")
        if error:
            return error
        if format_name in {"pdb", "pdbqt"} and not any(
            line.startswith("ATOM  ") for line in text.splitlines()
        ):
            return "Protein structure contains no protein ATOM records"
        if format_name in {"cif", "mmcif"} and "_atom_site." not in text:
            return "Protein structure contains no atom-site records"
    elif logical_type == "alignment" and format_name in {"a3m", "fa", "faa", "fas", "fasta"}:
        text, error = _read_text(path, kind="alignment")
        if error:
            return error
        sequences = [
            "".join(line for line in record.splitlines()[1:] if line.strip())
            for record in text.split(">")
            if record.strip()
        ]
        widths = {
            len("".join(char for char in sequence if not char.islower() and char not in "."))
            for sequence in sequences
        }
        if len(sequences) < 2 or len(widths) != 1 or 0 in widths:
            return "Alignment must contain at least two equal-length sequences"
    return None
