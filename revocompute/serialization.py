# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Content-addressed serialization primitives.

Hashing, canonical JSON digests, and file writes shared by Runner contracts,
evidence records, and validation receipts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

_SECRET_KEY = re.compile(r"(secret|password|token|credential|private.?key)", re.IGNORECASE)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_digest(value: Any) -> str:
    """Return a stable content digest independent of key order or spacing."""
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def atomic_write_json(path: str | Path, value: Mapping[str, Any], *, shared_read: bool = False) -> None:
    """Write JSON so a reader never observes a partial file.

    Records are private (``0600``) by default.  ``shared_read`` opts a record
    into the least privilege needed by an artifact another identity must read:
    ``0640``, group-readable and nothing more.  The mode is applied with
    ``fchmod`` before the atomic replace, so the final inode carries it and an
    inherited ACL mask is reset to permit the group read bit.  This function
    never touches the parent directory mode or changes file ownership.

    Shared read requires every ancestor directory to be traversable by the
    reader, and either an inheritable default ACL naming the reader or a file
    group equal to the reader's group.  A ``0700`` directory with no default
    ACL cannot be repaired by a file mode alone.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(destination.parent), prefix=f".{destination.name}.", delete=False
    )
    try:
        os.fchmod(handle.fileno(), 0o640 if shared_read else 0o600)
        json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(handle.name, destination)
    except BaseException:
        handle.close()
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def sanitized_mapping(value: Any) -> Any:
    """Recursively strip secret-bearing keys and control characters."""
    if isinstance(value, Mapping):
        return {
            key: sanitized_mapping(item)
            for key, item in value.items()
            if not (isinstance(key, str) and _SECRET_KEY.search(key))
        }
    if isinstance(value, list):
        return [sanitized_mapping(item) for item in value]
    if isinstance(value, str):
        return _CONTROL_CHARS.sub("", value)
    return value


__all__ = ["atomic_write_json", "canonical_digest", "sanitized_mapping", "sha256_file"]
