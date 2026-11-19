#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Stage the pinned BioNuTA workbench into a served static tree.

The upstream workbench is third-party Apache-2.0 code.  It is not committed to
this repository; this tool downloads the exact pinned commit archive, extracts
only the static files the editor needs, verifies a deterministic tree digest
from ``frontend/provenance/bionuta.json``, and swaps the staged tree into place
only after the check passes.

The archive is treated as untrusted data: no build, install or interpreter is
run inside it, and only regular files on an explicit allowlist are extracted.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "frontend" / "provenance" / "bionuta.json"
DEFAULT_DEST = ROOT / "vendor" / "bionuta"


def included(relative: str, lock: dict) -> bool:
    return relative in lock["include_files"] or any(
        relative.startswith(prefix) for prefix in lock["include_prefixes"]
    )


def tree_digest(root: Path, lock: dict) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    count = 0
    total = 0
    files = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and included(path.relative_to(root).as_posix(), lock)
    )
    for relative in files:
        data = (root / relative).read_bytes()
        count += 1
        total += len(data)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), count, total


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        if response.status != 200:
            raise SystemExit(f"Cannot fetch {url}: HTTP {response.status}")
        return response.read()


def stage(archive: bytes, destination: Path, lock: dict) -> None:
    temporary = Path(tempfile.mkdtemp(prefix=".bionuta-", dir=destination.parent))
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                parts = Path(member.name).parts
                # The archive has one top-level commit directory and must stay
                # inside it; a member that escapes is refused outright.
                if len(parts) < 2 or parts[0] in {"", ".", ".."}:
                    continue
                relative = Path(*parts[1:]).as_posix()
                if not included(relative, lock):
                    continue
                if "\\" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
                    raise SystemExit(f"Refusing unsafe archive member: {member.name!r}")
                source = tar.extractfile(member)
                if source is None:
                    continue
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read())
        digest, count, total = tree_digest(temporary, lock)
        if digest != lock["tree_sha256"]:
            raise SystemExit(
                f"BioNuTA tree digest mismatch: expected {lock['tree_sha256']}, received {digest}"
            )
        if count != lock["file_count"] or total != lock["bytes"]:
            raise SystemExit(
                f"BioNuTA tree shape mismatch: expected {lock['file_count']} files/{lock['bytes']} bytes, "
                f"received {count} files/{total} bytes"
            )
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--archive", type=Path, help="Use a local archive instead of downloading")
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    destination = args.destination.resolve()
    if args.archive:
        archive = args.archive.read_bytes()
    else:
        archive = download(
            f"https://codeload.github.com/YaoYinYing/JAAG/tar.gz/{lock['commit']}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage(archive, destination, lock)
    print(
        f"Staged BioNuTA {lock['commit'][:8]} ({lock['license']}, "
        f"{lock['file_count']} files) at {os.fspath(destination)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
