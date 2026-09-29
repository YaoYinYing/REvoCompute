# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Bounded, pickle-free numeric access to result NPY and NPZ artifacts."""

from __future__ import annotations

import math
import os
import re
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

MAX_SLICE_ELEMENTS = 16_384
MAX_SLICE_BYTES = 128 * 1024
MAX_NPZ_FILE_BYTES = 512 * 1024 * 1024
MAX_NPZ_ARRAY_BYTES = 64 * 1024 * 1024
_NPZ_KEY = re.compile(r"[A-Za-z0-9_.-]{1,128}")


class ArrayAccessError(ValueError):
    """The requested artifact, key, or slice is not safe to expose."""


def _array_size(shape: tuple[int, ...], dtype: np.dtype[Any]) -> tuple[int, int]:
    if dtype.hasobject or dtype.fields is not None or dtype.kind not in "biuf" or dtype.itemsize > 8:
        raise ArrayAccessError("Only fixed-width numeric arrays are supported")
    elements = math.prod(shape)
    return elements, elements * dtype.itemsize


def _read_npz_member(path: str, key: str) -> np.ndarray[Any, Any]:
    if os.path.getsize(path) > MAX_NPZ_FILE_BYTES:
        raise ArrayAccessError("NPZ artifact exceeds the access limit")
    member_name = f"{key}.npy"
    with zipfile.ZipFile(path) as archive:
        members = [item for item in archive.infolist() if item.filename == member_name]
        if len(members) != 1:
            raise ArrayAccessError("NPZ key was not found")
        member = members[0]
        if member.file_size > MAX_NPZ_ARRAY_BYTES + 65_536:
            raise ArrayAccessError("NPZ array exceeds the access limit")
        with archive.open(member) as handle:
            version = np.lib.format.read_magic(handle)
            if version == (1, 0):
                shape, _, dtype = np.lib.format.read_array_header_1_0(handle)
            elif version in {(2, 0), (3, 0)}:
                shape, _, dtype = np.lib.format.read_array_header_2_0(handle)
            else:
                raise ArrayAccessError("Unsupported NPY format version")
        _, byte_count = _array_size(shape, dtype)
        if byte_count > MAX_NPZ_ARRAY_BYTES:
            raise ArrayAccessError("NPZ array exceeds the access limit")
        # ponytail: compressed members are materialized up to 64 MiB; stream to
        # a temporary mmap only if real published arrays exceed this ceiling.
        with archive.open(member) as handle:
            return np.lib.format.read_array(handle, allow_pickle=False)


def _json_values(array: np.ndarray[Any, Any], offset: int, stop: int) -> list[bool | int | float | None]:
    values: list[bool | int | float | None] = []
    for value in array.flat[offset:stop].tolist():
        if isinstance(value, float) and not math.isfinite(value):
            values.append(None)
        else:
            values.append(value)
    return values


def read_ndarray_slice(
    path: str | Path,
    *,
    key: str | None,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """Return one bounded C-order numeric slice and the array metadata."""
    artifact_path = str(path)
    suffix = Path(artifact_path).suffix.lower()
    try:
        if suffix == ".npy":
            if key is not None:
                raise ArrayAccessError("NPY artifacts do not accept a key")
            array = np.load(artifact_path, mmap_mode="r", allow_pickle=False)
        elif suffix == ".npz":
            if key is None or _NPZ_KEY.fullmatch(key) is None:
                raise ArrayAccessError("A safe NPZ key is required")
            array = _read_npz_member(artifact_path, key)
        else:
            raise ArrayAccessError("Artifact is not an NPY or NPZ array")
    except ArrayAccessError:
        raise
    except (EOFError, MemoryError, OSError, OverflowError, ValueError, zipfile.BadZipFile) as error:
        raise ArrayAccessError("Array artifact is invalid or unsupported") from error

    total_elements, _ = _array_size(array.shape, array.dtype)
    if offset > total_elements:
        raise ArrayAccessError("Array offset is outside allowed bounds")
    count = min(limit, total_elements - offset)
    if count * array.dtype.itemsize > MAX_SLICE_BYTES:
        raise ArrayAccessError("Array slice exceeds the byte limit")
    stop = offset + count
    return {
        "dtype": array.dtype.str,
        "shape": list(array.shape),
        "key": key,
        "offset": offset,
        "count": count,
        "total_elements": total_elements,
        "has_more": stop < total_elements,
        "data": _json_values(array, offset, stop),
    }
