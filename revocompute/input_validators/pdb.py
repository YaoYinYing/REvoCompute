# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""PDB syntax and transport-safety validator."""

from __future__ import annotations

from revocompute.input_validators.common import MAX_PDB_LINES, MAX_PDB_RECORD_LENGTH, PDB_SNIFF_LINES, _read_text


def validate_pdb(path: str) -> str | None:
    """Return an error message if *path* is not a plausible PDB file.

    Lenient: only the first ``PDB_SNIFF_LINES`` lines are sniffed for the
    record keywords, so files that open with long REMARK/CRYST1 sections
    still pass.
    """
    text, error = _read_text(path, kind="PDB")
    if error is not None:
        return error
    lines = text.splitlines()
    if len(lines) > MAX_PDB_LINES:
        return f"PDB file contains more than {MAX_PDB_LINES} lines"
    if any(len(line) > MAX_PDB_RECORD_LENGTH for line in lines):
        return f"PDB file contains a line longer than {MAX_PDB_RECORD_LENGTH} characters"
    if not any(line.strip().startswith(("ATOM", "HETATM", "END")) for line in lines[:PDB_SNIFF_LINES]):
        return "PDB file must contain ATOM, HETATM, or END records near the start"
    return None
