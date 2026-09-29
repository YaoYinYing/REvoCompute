# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Bounded numeric projections from result JSON, CSV, NPY, and NPZ artifacts."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

MAX_SLICE_ELEMENTS = 16_384
MAX_SLICE_BYTES = 128 * 1024
MAX_JSON_FILE_BYTES = 64 * 1024 * 1024
MAX_JSON_ARRAY_ELEMENTS = 1_048_576
MAX_CSV_FILE_BYTES = 64 * 1024 * 1024
MAX_CSV_ROWS = 1_048_576
MAX_CSV_COLUMNS = 512
MAX_CSV_CELL_BYTES = 1024
MAX_NPZ_FILE_BYTES = 512 * 1024 * 1024
MAX_NPZ_ARRAY_BYTES = 64 * 1024 * 1024
_NPZ_KEY = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_JSON_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,127}")


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


def _read_json_array(path: str, key: str | None) -> np.ndarray[Any, Any]:
    if key is None or _JSON_KEY.fullmatch(key) is None:
        raise ArrayAccessError("A safe JSON field is required")
    if os.path.getsize(path) > MAX_JSON_FILE_BYTES:
        raise ArrayAccessError("JSON artifact exceeds the access limit")
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle, parse_constant=lambda _value: None)
    except (MemoryError, OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ArrayAccessError("Array artifact is invalid or unsupported") from error
    if not isinstance(payload, dict) or key not in payload:
        raise ArrayAccessError("JSON field was not found")
    value = payload[key]
    if not isinstance(value, list):
        raise ArrayAccessError("JSON field is not a numeric vector or matrix")
    rows = value if value and isinstance(value[0], list) else [value]
    matrix = bool(value and isinstance(value[0], list))
    columns = len(rows[0]) if rows else 0
    if matrix and any(not isinstance(row, list) or len(row) != columns for row in rows):
        raise ArrayAccessError("JSON matrix rows must have equal length")
    invalid_cell = any(
        isinstance(cell, (list, dict)) or (cell is not None and not isinstance(cell, (bool, int, float)))
        for row in rows
        for cell in row
    )
    if invalid_cell:
        raise ArrayAccessError("JSON array contains non-numeric values")
    element_count = len(rows) * columns
    if element_count > MAX_JSON_ARRAY_ELEMENTS:
        raise ArrayAccessError("JSON array exceeds the element limit")
    # Missing values use NaN internally and are projected back to JSON null,
    # matching the NPY/NPZ response contract for non-finite values.
    normalized = [[math.nan if cell is None else cell for cell in row] for row in rows]
    array = np.asarray(normalized, dtype=np.float64)
    return array if matrix else array.reshape(columns)


def _read_csv_column(path: str, key: str | None, *, delimiter: str) -> np.ndarray[Any, Any]:
    if key is None or _JSON_KEY.fullmatch(key) is None:
        raise ArrayAccessError("A safe CSV column is required")
    if os.path.getsize(path) > MAX_CSV_FILE_BYTES:
        raise ArrayAccessError("CSV artifact exceeds the access limit")
    values: list[float] = []
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration as error:
            raise ArrayAccessError("CSV artifact has no header") from error
        if not header or len(header) > MAX_CSV_COLUMNS or len(set(header)) != len(header):
            raise ArrayAccessError("CSV header is invalid or exceeds the column limit")
        if any(len(cell.encode("utf-8")) > MAX_CSV_CELL_BYTES for cell in header):
            raise ArrayAccessError("CSV cell exceeds the access limit")
        try:
            column = header.index(key)
        except ValueError as error:
            raise ArrayAccessError("CSV column was not found") from error
        for row_number, row in enumerate(reader, start=1):
            if row_number > MAX_CSV_ROWS:
                raise ArrayAccessError("CSV artifact exceeds the row limit")
            if len(row) != len(header):
                raise ArrayAccessError("CSV rows must match the header")
            cell = row[column].strip()
            if len(cell.encode("utf-8")) > MAX_CSV_CELL_BYTES:
                raise ArrayAccessError("CSV cell exceeds the access limit")
            if not cell:
                values.append(math.nan)
                continue
            try:
                value = float(cell)
            except ValueError as error:
                raise ArrayAccessError("CSV column contains non-numeric values") from error
            values.append(value if math.isfinite(value) else math.nan)
    return np.asarray(values, dtype=np.float64)


def read_ndarray_slice(
    path: str | Path,
    *,
    key: str | None,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """Return one bounded C-order numeric slice and storage-neutral metadata."""
    artifact_path = str(path)
    suffix = Path(artifact_path).suffix.lower()
    try:
        if suffix == ".json":
            array = _read_json_array(artifact_path, key)
        elif suffix in {".csv", ".tsv"}:
            array = _read_csv_column(artifact_path, key, delimiter="\t" if suffix == ".tsv" else ",")
        elif suffix == ".npy":
            if key is not None:
                raise ArrayAccessError("NPY artifacts do not accept a key")
            array = np.load(artifact_path, mmap_mode="r", allow_pickle=False)
        elif suffix == ".npz":
            if key is None or _NPZ_KEY.fullmatch(key) is None:
                raise ArrayAccessError("A safe NPZ key is required")
            array = _read_npz_member(artifact_path, key)
        else:
            raise ArrayAccessError("Artifact is not a JSON, CSV, NPY, or NPZ array")
    except ArrayAccessError:
        raise
    except (
        csv.Error,
        EOFError,
        MemoryError,
        OSError,
        OverflowError,
        UnicodeError,
        ValueError,
        zipfile.BadZipFile,
    ) as error:
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
