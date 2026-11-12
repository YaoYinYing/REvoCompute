# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Transport-safety validators for molecular-dynamics topology and trajectory files.

These checks prove the container is the declared serialization and bounded in
size and atom count.  They never interpret chemistry or coordinates as a
scientific decision: the pinned Tool parser owns the topology/atom mapping,
unit conversion and frame selection.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

from revocompute.input_validators.common import _read_text

MAX_MD_ATOMS = 99_999
MAX_GRO_BYTES = 8_000_000
MAX_XTC_BYTES = 100_000_000
_XTC_MAGIC = 1995


def validate_gro(path: str) -> str | None:
    """Validate the bounded fixed-width GROMACS GRO container."""
    text, error = _read_text(path, kind="GRO topology", max_bytes=MAX_GRO_BYTES)
    if error:
        return error
    assert text is not None
    lines = text.splitlines()
    if len(lines) < 3:
        return "GRO topology must contain a title, an atom count, at least one atom and a box line"
    try:
        atom_count = int(lines[1].strip())
    except ValueError:
        return "GRO topology atom-count line is not an integer"
    if not 1 <= atom_count <= MAX_MD_ATOMS:
        return f"GRO topology atom count must be between 1 and {MAX_MD_ATOMS}"
    expected = atom_count + 3
    if len(lines) < expected:
        return f"GRO topology declares {atom_count} atoms but carries fewer than {expected} lines"
    if any(line.strip() for line in lines[expected:]):
        return f"GRO topology declares {atom_count} atoms but carries content beyond its box line"
    atom_lines = lines[2 : 2 + atom_count]
    box_line = lines[2 + atom_count]
    if any(not line.strip() for line in atom_lines) or not box_line.strip():
        return "GRO topology contains a blank atom or box record"
    for line in atom_lines:
        if len(line) < 44:
            return "GRO topology contains a truncated atom record"
        try:
            values = (float(line[20:28]), float(line[28:36]), float(line[36:44]))
        except ValueError:
            return "GRO topology contains a malformed coordinate record"
        if not all(math.isfinite(value) for value in values):
            return "GRO topology contains a non-finite coordinate"
    box_fields = box_line.split()
    if len(box_fields) not in {3, 6, 9}:
        return "GRO topology box line must carry three, six or nine values"
    try:
        box = [float(value) for value in box_fields]
    except ValueError:
        return "GRO topology box line is malformed"
    if not all(math.isfinite(value) for value in box):
        return "GRO topology box line contains a non-finite value"
    if any(value < 0 for value in box[:3]):
        return "GRO topology box lengths cannot be negative"
    return None


def validate_xtc(path: str) -> str | None:
    """Validate the XTC magic, first-frame atom header and encoded size bound."""
    source = Path(path)
    try:
        size = source.stat().st_size
        if size > MAX_XTC_BYTES:
            return f"XTC trajectory exceeds the {MAX_XTC_BYTES} byte input limit"
        with source.open("rb") as stream:
            header = stream.read(16)
    except OSError as exc:
        return f"Could not read uploaded XTC trajectory: {exc}"
    if len(header) < 16:
        return "XTC trajectory is too short to carry a frame header"
    magic, atom_count, _step, _time = struct.unpack(">iiii", header)
    if magic != _XTC_MAGIC:
        return "XTC trajectory does not carry the XTC magic number"
    if not 1 <= atom_count <= MAX_MD_ATOMS:
        return f"XTC trajectory atom count must be between 1 and {MAX_MD_ATOMS}"
    # 16 header bytes, a 36-byte unit cell and one 12-byte coordinate per atom
    # are the minimum first-frame payload.  Full frame decoding stays with the
    # pinned Tool parser, which refuses a truncated or corrupt later frame.
    if size < 16 + 36 + 12 * atom_count:
        return "XTC trajectory is truncated before its first frame coordinates"
    return None
