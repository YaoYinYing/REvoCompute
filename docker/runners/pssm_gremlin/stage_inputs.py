# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
"""Resolve the composed stage input from the server-written document.

Mirrors ``gremlin_lh/stage_inputs.py``: both families implement the same
server-written document (format version 1).

The Server writes this document only after it has resolved a producer stage's
verified output identity, copied the artifact into a confined stage input
directory, and checked its digest. The Runner re-checks the digest before
fitting so the bytes it models are the bytes the Server admitted.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

_FORMAT_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")


class StageInputError(ValueError):
    """The stage input document does not authorize a usable artifact."""


def resolve(document_path: Path, role: str) -> Path:
    """Return the verified path for ``role`` or raise :class:`StageInputError`."""
    try:
        document = json.loads(document_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StageInputError(f"cannot read stage input document {document_path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("version") != _FORMAT_VERSION:
        raise StageInputError(f"stage input document must be version {_FORMAT_VERSION}")
    inputs = document.get("inputs")
    entry = inputs.get(role) if isinstance(inputs, dict) else None
    if not isinstance(entry, dict):
        raise StageInputError(f"stage input document does not declare role {role!r}")
    files = entry.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        raise StageInputError(f"stage input {role!r} has no verified file list")
    if len(files) != 1:
        raise StageInputError(f"stage input {role!r} must name exactly one file, got {len(files)}")
    raw_path = files[0].get("path")
    expected = files[0].get("sha256")
    if entry.get("path") != raw_path:
        raise StageInputError(f"stage input {role!r} path disagrees with its verified file list")
    if not isinstance(raw_path, str) or not isinstance(expected, str) or not _SHA256.fullmatch(expected):
        raise StageInputError(f"stage input {role!r} has no verified path and sha256")
    path = Path(raw_path)
    if path.is_symlink() or not path.is_file():
        raise StageInputError(f"stage input {role!r} is not a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise StageInputError(f"stage input {role!r} digest does not match the server contract")
    return path


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != "resolve":
        sys.stderr.write("Usage: stage_inputs.py resolve <document> <role>\n")
        return 2
    try:
        print(resolve(Path(argv[1]), argv[2]))
    except StageInputError as exc:
        sys.stderr.write(f"stage_inputs.py: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
