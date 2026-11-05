# Copyright (C) 2024-2026 The REvoDesign Developers.
# SPDX-License-Identifier: GPL-3.0-only
"""Resolve staged inputs from the server-written stage input document.

The Server writes this document only after it has resolved a producer stage's
verified output identity, copied the artifact into a confined stage input
directory, and checked its digest. The Runner re-checks every byte it consumes
against the document so it models exactly what the Server admitted.

``resolve`` returns the single file a one-artifact role names, with the same
semantics as ``gremlin_lh/stage_inputs.py``. ``materialize`` copies a role's
files below a destination, keeps the layout the Server staged, and verifies the
copied bytes; a consumer that must name a port's static prefix differently from
the producer passes ``flat`` to place a one-file role directly in the
destination directory.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

_FORMAT_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")


class StageInputError(ValueError):
    """The stage input document does not authorize a usable artifact."""


def _verified_file(path: Path, expected: str, size: int) -> Path:
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise StageInputError(f"stage input file {path} has no verified size")
    if path.is_symlink() or not path.is_file():
        raise StageInputError(f"stage input file is not a regular file: {path}")
    if path.stat().st_size != size:
        raise StageInputError(f"stage input file size does not match the server contract: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise StageInputError(f"stage input file digest does not match the server contract: {path}")
    return path


def _document(document_path: Path) -> dict:
    try:
        document = json.loads(document_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StageInputError(f"cannot read stage input document {document_path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("version") != _FORMAT_VERSION:
        raise StageInputError(f"stage input document must be version {_FORMAT_VERSION}")
    return document


def declares(document_path: Path, role: str) -> bool:
    """Whether the document declares ``role``.

    A full-mode model stage also runs with a stage input document, but it
    declares the in-graph ``features`` role rather than a reuse role. Consumers
    use this probe to tell "consume this staged artifact" from "use the tree
    this Task built"; a malformed document is an error rather than "absent".
    """
    inputs = _document(document_path).get("inputs")
    if not isinstance(inputs, dict):
        raise StageInputError("stage input document has no inputs")
    return role in inputs


def _files(document_path: Path, role: str) -> tuple[dict, list[dict]]:
    """Return the declared role entry and its verified file records."""
    document = _document(document_path)
    inputs = document.get("inputs")
    entry = inputs.get(role) if isinstance(inputs, dict) else None
    if not isinstance(entry, dict):
        raise StageInputError(f"stage input document does not declare role {role!r}")
    files = entry.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        raise StageInputError(f"stage input {role!r} has no verified file list")
    if not files:
        raise StageInputError(f"stage input {role!r} names no files")
    for item in files:
        raw_path = item.get("path")
        expected = item.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            raise StageInputError(f"stage input {role!r} file has no verified path and sha256")
    return entry, files


def resolve(document_path: Path, role: str) -> Path:
    """Return the verified path for a one-file ``role`` or raise :class:`StageInputError`."""
    entry, files = _files(document_path, role)
    if len(files) != 1:
        raise StageInputError(f"stage input {role!r} must name exactly one file, got {len(files)}")
    raw_path = files[0]["path"]
    if entry.get("path") != raw_path:
        raise StageInputError(f"stage input {role!r} path disagrees with its verified file list")
    return _verified_file(Path(raw_path), files[0]["sha256"], files[0].get("size"))


def _relative_path(raw_path: str, role: str) -> tuple[str, ...]:
    """The path below the role directory the Server staged the file under."""
    parts = tuple(raw_path.split("/"))
    if role not in parts:
        raise StageInputError(f"stage input path is outside the role directory {role!r}: {raw_path}")
    relative = parts[parts.index(role) + 1:]
    if not relative or any(part in {"", ".", ".."} for part in relative):
        raise StageInputError(f"stage input path is not stageable: {raw_path}")
    return relative


def materialize(document_path: Path, role: str, destination: Path, flat: bool = False) -> list[Path]:
    """Verify and copy ``role``'s files below ``destination``; return the copies.

    ``flat`` places the single file of a one-file role directly in
    ``destination``, for a consumer whose own naming (a job name derived from
    the consumer's input) must replace the producer's layout. Every copy is
    re-verified after it is written, so a short or altered copy is refused
    rather than consumed.
    """
    entry, files = _files(document_path, role)
    if flat and len(files) != 1:
        raise StageInputError(f"stage input {role!r} must name exactly one file to flatten, got {len(files)}")
    if len(files) == 1 and entry.get("path") != files[0]["path"]:
        raise StageInputError(f"stage input {role!r} path disagrees with its verified file list")
    verified: list[tuple[Path, Path, str, int]] = []
    for item in files:
        source = Path(item["path"])
        _verified_file(source, item["sha256"], item.get("size"))
        relative = (source.name,) if flat else _relative_path(item["path"], role)
        verified.append((source, destination.joinpath(*relative), item["sha256"], item.get("size")))
    copied: list[Path] = []
    for source, target, expected, size in verified:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.exists():
            target.unlink()
        shutil.copyfile(source, target)
        # A short or altered copy must never be modeled under this attempt.
        _verified_file(target, expected, size)
        copied.append(target)
    return copied


def main(argv: list[str]) -> int:
    usage = (
        "Usage: stage_inputs.py resolve <document> <role>\n"
        "       stage_inputs.py materialize <document> <role> <destination> [--flat]\n"
        "       stage_inputs.py declares <document> <role>\n"
    )
    try:
        if len(argv) == 3 and argv[0] == "resolve":
            print(resolve(Path(argv[1]), argv[2]))
            return 0
        if len(argv) == 3 and argv[0] == "declares":
            print("yes" if declares(Path(argv[1]), argv[2]) else "no")
            return 0
        if len(argv) in {4, 5} and argv[0] == "materialize" and (len(argv) == 4 or argv[4] == "--flat"):
            for path in materialize(Path(argv[1]), argv[2], Path(argv[3]), flat=len(argv) == 5):
                print(path)
            return 0
    except StageInputError as exc:
        sys.stderr.write(f"stage_inputs.py: {exc}\n")
        return 1
    sys.stderr.write(usage)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
