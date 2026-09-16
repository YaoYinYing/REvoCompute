# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""mmCIF content validator."""

from __future__ import annotations

import shlex

from revocompute.input_validators.common import CIF_SNIFF_LINES, MAX_CIF_ATOMS, MAX_CIF_RECORD_LENGTH, _read_text


def validate_mmcif(path: str) -> str | None:
    """Return an error message if *path* is not a plausible mmCIF file.

    Lenient: only the first ``CIF_SNIFF_LINES`` lines are sniffed for the
    ``data_`` / ``_atom_site.`` markers, and atom rows are counted with the
    real loop grammar (``loop_`` columns, then data rows).
    """
    text, error = _read_text(path, kind="mmCIF")
    if error is not None:
        return error
    lines = text.splitlines()
    if any(len(line) > MAX_CIF_RECORD_LENGTH for line in lines):
        return f"mmCIF file contains a line longer than {MAX_CIF_RECORD_LENGTH} characters"
    if not any(
        line.strip().startswith("data_") or line.strip().startswith("_atom_site.") for line in lines[:CIF_SNIFF_LINES]
    ):
        return "mmCIF file must contain a data_ block or _atom_site. columns near the start"
    atom_rows = 0
    in_loop = False
    loop_columns: list[str] = []
    loop_value_count = 0
    loop_has_values = False

    def finish_loop() -> str | None:
        nonlocal atom_rows
        if not loop_columns or not any(column.startswith("_atom_site.") for column in loop_columns):
            return None
        if not all(column.startswith("_atom_site.") for column in loop_columns):
            return "mmCIF atom-site loop mixes incompatible column categories"
        if loop_value_count % len(loop_columns):
            return "mmCIF atom-site loop has an incomplete data row"
        atom_rows += loop_value_count // len(loop_columns)
        if atom_rows > MAX_CIF_ATOMS:
            return f"mmCIF file contains more than {MAX_CIF_ATOMS} atoms"
        return None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "loop_":
            if error := finish_loop():
                return error
            loop_columns = []
            loop_value_count = 0
            loop_has_values = False
            in_loop = True
            continue
        if in_loop and loop_columns and loop_has_values and (
            stripped.startswith("_") or stripped.startswith("data_") or stripped == "stop_"
        ):
            if error := finish_loop():
                return error
            loop_columns = []
            loop_value_count = 0
            loop_has_values = False
            in_loop = False
            continue
        if in_loop and stripped.startswith("_") and not loop_has_values:
            loop_columns.append(stripped.split(maxsplit=1)[0])
            continue
        if in_loop and loop_columns:
            try:
                values = shlex.split(stripped, comments=False, posix=True)
            except ValueError:
                return "mmCIF atom-site loop contains malformed quoted data"
            loop_value_count += len(values)
            loop_has_values = True
    return finish_loop()
