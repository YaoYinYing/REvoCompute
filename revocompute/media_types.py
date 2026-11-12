# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Server-owned media type for a published or served file path.

The deployment image deliberately carries no host MIME database, so Python's
``mimetypes`` table alone classifies scientific formats as
``application/octet-stream``.  That would make every live PDB/mmCIF/GRO
response ineligible for gateway compression.  This table is the one
server-owned projection used when a result manifest is built, when an artifact
is delivered, and when a Task structure input is served.

Entries that are already compressed or non-textual stay
``application/octet-stream`` (or their existing binary type) so a gateway
allowlist can never recompress them.  The table is explicit rather than
environment-dependent: the same path yields the same type on every deployment.
"""

from __future__ import annotations

import mimetypes
import os

_APPLICATION_OCTET_STREAM = "application/octet-stream"

_MEDIA_TYPE_BY_SUFFIX = {
    ".txt": "text/plain",
    ".log": "text/plain",
    ".stdout": "text/plain",
    ".err": "text/plain",
    ".a3m": "text/x-a3m",
    ".fasta": "text/x-fasta",
    ".fa": "text/x-fasta",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".pdb": "chemical/x-pdb",
    ".ent": "chemical/x-pdb",
    ".cif": "chemical/x-cif",
    ".mmcif": "chemical/x-mmcif",
    ".gro": "chemical/x-gro",
    ".png": "image/png",
    ".zip": "application/zip",
    # Compressed or array containers must never be re-compressed by the
    # gateway, including a compound name such as ``model.pdb.gz`` whose last
    # suffix is the compression layer.
    ".gz": _APPLICATION_OCTET_STREAM,
    ".bz2": _APPLICATION_OCTET_STREAM,
    ".xz": _APPLICATION_OCTET_STREAM,
    ".zst": _APPLICATION_OCTET_STREAM,
    ".npy": _APPLICATION_OCTET_STREAM,
    ".npz": _APPLICATION_OCTET_STREAM,
    ".parquet": _APPLICATION_OCTET_STREAM,
    ".xtc": _APPLICATION_OCTET_STREAM,
    ".dcd": _APPLICATION_OCTET_STREAM,
}


def media_type_for_path(path: str) -> str:
    """Return the deterministic media type for one relative or absolute path."""
    suffix = os.path.splitext(str(path or ""))[1].lower()
    mapped = _MEDIA_TYPE_BY_SUFFIX.get(suffix)
    if mapped is not None:
        return mapped
    # Unknown text-like types may still be described by the platform table;
    # an unknown binary remains octet-stream rather than a guessed text type.
    return mimetypes.guess_type(str(path or ""))[0] or _APPLICATION_OCTET_STREAM
