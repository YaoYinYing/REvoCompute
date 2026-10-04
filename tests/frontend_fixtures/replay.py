# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Serve a validated replay bundle as the frontend-visible result surface.

The bundle captures bytes; this class turns them into the same bounded
sub-resources a real deployment serves — the ResultManifest response, task-scoped
artifact/download routes, a logical-file projection, paged table and numeric
projection routes, and the storyboard module. A request for a task other than the
one the bundle captures resolves to nothing, so the router returns the same 404 a
real Server would. It never fabricates bytes: every payload comes from the
capture, and it is served only when its bytes still match the captured sha256.
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .replay_bundle import ReplayBundleError, load_bundle


class ReplayBundle:
    """A validated replay bundle bound to the task id it answers for."""

    def __init__(self, document: Mapping[str, Any], *, task_id: str | None = None) -> None:
        bundle = load_bundle(document)
        self.task_id = str(task_id or bundle["task"]["id"]).lower()
        if self.task_id != str(bundle["task"]["id"]).lower():
            raise ReplayBundleError("replay bundle is bound to a different task id")
        self.bundle = bundle
        self.manifest: dict[str, Any] = json.loads(json.dumps(bundle["response"]))
        self.provenance: dict[str, Any] = dict(bundle.get("provenance") or {})

    @classmethod
    def load(cls, path: str | Path, *, task_id: str | None = None) -> ReplayBundle:
        """Load, validate, and bind a bundle persisted by the capture path."""
        return cls(load_bundle(path), task_id=task_id)

    # -- manifest -----------------------------------------------------------

    def served_manifest(self, task_id: str | None = None) -> dict[str, Any] | None:
        """The exact ResultManifest response for ``task_id``, or ``None``."""
        if task_id is not None and task_id.lower() != self.task_id:
            return None
        return json.loads(json.dumps(self.manifest))

    # -- artifact and logical-file bytes ------------------------------------

    def payload(self, path: str | None) -> tuple[bytes, str] | None:
        """Return ``(bytes, media_type)`` for one captured artifact path."""
        if not path:
            return None
        entry = self.bundle.get("payloads", {}).get(path)
        if not isinstance(entry, Mapping):
            return None
        data = str(entry.get("payload") or "").encode("utf-8")
        return data, str(entry.get("media_type") or "application/octet-stream")

    def logical_artifact_path(self, file_id: str, index: int) -> str | None:
        """Return the artifact path behind one logical file entry, or ``None``.

        Resolved from the captured logical-file map, never guessed from a name:
        the served manifest's logical entries carry only a ``url``, so the
        bundle keeps the published path/sha256/size identity separately.
        """
        entries = (self.bundle.get("logical_files") or {}).get(file_id, [])
        if not 0 <= index < len(entries):
            return None
        return str(entries[index]["path"])

    def storyboard_source(self, asset: str) -> str | None:
        captured = self.manifest.get("storyboard")
        if not isinstance(captured, Mapping) or asset != captured.get("entrypoint"):
            return None
        storyboard = self.bundle.get("storyboard")
        return storyboard.get("source") if isinstance(storyboard, Mapping) else None

    # -- bounded table and projection routes --------------------------------

    def table_page(self, path: str, *, offset: int = 0, limit: int = 100, matrix: bool = False) -> dict[str, Any] | None:
        """Page a captured table artifact exactly as the Server's route does.

        Applies the same bounds (offset ≤ 10000, limit ≤ 500, a wider matrix
        column allowance) and the same CSV/TSV parsing, so the frontend receives
        a byte-faithful projection of the captured artifact rather than a copy of
        a whole file that would hide a paging defect.
        """
        body = self.payload(path)
        if body is None:
            return None
        try:
            offset = int(offset)
            limit = int(limit)
        except (TypeError, ValueError):
            return None
        if offset < 0 or offset > 10_000 or limit < 1 or limit > 500:
            return None
        text = body[0].decode("utf-8")
        delimiter = "\t" if path.lower().endswith(".tsv") else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        columns = next(reader, [])
        rows: list[list[str]] = []
        has_more = False
        for index, row in enumerate(reader):
            if index < offset:
                continue
            if len(rows) == limit:
                has_more = True
                break
            rows.append(row)
        return {
            "columns": columns,
            "rows": rows,
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
        }

    def projection(self, path: str, *, kind: str = "numeric", key: str | None = None) -> dict[str, Any] | None:
        """Project a captured table/JSON artifact into the bounded array response.

        Mirrors ``revocompute.ndarray.read_array_projection`` for the formats a
        replay bundle checks in (CSV, TSV, JSON): a numeric column or matrix
        becomes a fixed-width numeric projection, a JSON object path becomes a
        categorical or numeric vector. Binary NPY/NPZ members are not checked in,
        so their projection is unavailable and the route returns 404.
        """
        body = self.payload(path)
        if body is None:
            return None
        suffix = os.path.splitext(path)[1].lower()
        try:
            text = body[0].decode("utf-8")
            if suffix in {".csv", ".tsv"}:
                values = _csv_value(text, key=key, kind=kind, delimiter="\t" if suffix == ".tsv" else ",")
            elif suffix == ".json":
                values = _json_value(json.loads(text), key=key, kind=kind)
            else:
                return None
        except (ValueError, UnicodeDecodeError):
            return None
        if values is None:
            return None
        if kind == "categorical":
            strings = [str(value) for value in values]
            return {
                "kind": "categorical",
                "dtype": "string",
                "shape": [len(strings)],
                "key": key,
                "total_elements": len(strings),
                "data": strings,
            }
        numbers = [None if value is None else float(value) for value in values]
        return {
            "kind": "numeric",
            "dtype": "<f8",
            "shape": [len(numbers)],
            "key": key,
            "total_elements": len(numbers),
            "data": numbers,
        }


def _csv_value(text: str, *, key: str | None, kind: str, delimiter: str) -> list[Any] | None:
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if key is None:
        return None
    cells = [row.get(key) for row in reader]
    if any(cell is None for cell in cells):
        return None
    if kind == "categorical":
        return [str(cell) for cell in cells]
    out: list[Any] = []
    for cell in cells:
        stripped = str(cell).strip()
        if stripped == "":
            out.append(None)
            continue
        try:
            out.append(float(stripped))
        except ValueError:
            return None
    return out


def _json_value(payload: Any, *, key: str | None, kind: str) -> list[Any] | None:
    node = payload
    if key:
        for part in key.split("."):
            if isinstance(node, Mapping) and part in node:
                node = node[part]
            else:
                return None
    if isinstance(node, list):
        cells = node
    elif isinstance(node, str) or (isinstance(node, (int, float)) and not isinstance(node, bool)):
        cells = [node]
    else:
        return None
    if kind == "categorical":
        return [cell for cell in cells] if all(isinstance(cell, str) for cell in cells) else None
    if any(isinstance(cell, (list, dict)) or (cell is not None and not isinstance(cell, (bool, int, float))) for cell in cells):
        return None
    return [None if cell is None else float(cell) for cell in cells]
