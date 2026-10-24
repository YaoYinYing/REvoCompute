# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Server-side projection of a published ResultManifest into a served response.

A Runner writes a ResultManifest to the task result root; the Server serves it
enriched for the frontend -- the serve-time envelope (status/terminal/error/
archive), a resolved renderer ``capability`` and per-artifact URLs, the
per-logical-file projection, and the storyboard entrypoint URL.

This is the single implementation of that projection. The
``GET /compute/api/results/<task_id>`` route owns authorization (which artifacts
and views a caller may see) and then calls :func:`project_result_manifest` to
produce the body, and the test-only replay harness calls the same function, so a
replayed result and a live result are projected by one function rather than two
that can drift.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from revocompute.ndarray import ArrayAccessError, MAX_PROJECTION_ELEMENTS, read_array_projection

#: The table route's response envelope ceilings.  ``_TABLE_PAGE_ENVELOPE_BYTES``
#: covers the fixed JSON keys around the page; the cell and page limits bound an
#: untrusted artifact's rows before any of them reach the browser.
MAX_TABLE_PAGE_BYTES = 8 * 1024 * 1024
MAX_TABLE_CELL_BYTES = 16 * 1024
MAX_TABLE_OFFSET = 10_000
MAX_TABLE_LIMIT = 500
_TABLE_PAGE_ENVELOPE_BYTES = 512
_TABLE_COLUMNS = 100
_TABLE_MATRIX_COLUMNS = 512 + 1
_BOUNDED_INTEGER = re.compile(r"(?:0|[1-9][0-9]{0,18})")


class ResultPreviewError(ValueError):
    """A result sub-resource page or projection is outside what the Server serves.

    The message is already client-facing; both the production result routes and
    the replay routes that serve recorded bytes refuse through this one type, so
    a replay cannot accept a page or projection the real route would reject.
    """


def artifact_capability(preview: str | None, logical_type: str | None = None) -> str:
    """Project a small renderer capability without Runner-specific inference."""
    declared = logical_type or preview
    if declared == "structure":
        return "molecular_structure"
    if declared in {"table", "plot", "image", "text", "archive"}:
        return declared
    if declared in {"alignment", "fasta", "json"}:
        return "text"
    if declared == "model" or declared is None:
        return "download_only"
    return "unknown"


def table_page_bounds(args: Mapping[str, Any]) -> tuple[int, int]:
    """Parse ``offset``/``limit`` exactly as the table route always has.

    The raw query values are converted the same way for a live artifact and a
    recorded replay, so neither accepts a page the other refuses.
    """
    try:
        return int(args.get("offset", 0)), int(args.get("limit", 100))
    except (TypeError, ValueError):
        raise ResultPreviewError("Invalid table page") from None


def read_table_page(
    stream: Any,
    *,
    name: str,
    offset: int,
    limit: int,
    matrix: bool,
    declared_table: bool,
) -> dict[str, Any]:
    """Page one table artifact stream under the route's cell, width, and byte caps.

    ``declared_table`` is the caller's manifest-derived fact: an artifact the
    manifest does not declare as a table is refused rather than parsed on the
    strength of its extension.  The text wrapper consumes ``stream``; the caller
    still owns closing the artifact descriptor it opened.  A parse failure is
    reported as ``ResultPreviewError("Table could not be previewed")`` with the
    original exception as its cause so the route can log the artifact defect.
    """
    if not declared_table:
        raise ResultPreviewError("Artifact is not a table")
    if offset < 0 or offset > MAX_TABLE_OFFSET or limit < 1 or limit > MAX_TABLE_LIMIT:
        raise ResultPreviewError("Table page is outside allowed bounds")
    delimiter = "\t" if name.lower().endswith(".tsv") else ","
    # A matrix page carries one extra leading column of row labels beside its
    # values, so the matrix cap allows that label column on top of the cap
    # itself; a plain preview keeps its tighter width limit.
    max_columns = _TABLE_MATRIX_COLUMNS if matrix else _TABLE_COLUMNS

    def row_cost(row: list[str]) -> int:
        if len(row) > max_columns:
            raise ValueError("Table row exceeds preview limits")
        cost = 2 + max(0, len(row) - 1)
        for cell in row:
            if len(cell.encode("utf-8")) > MAX_TABLE_CELL_BYTES:
                raise ValueError("Table cell exceeds preview limits")
            cost += len(json.dumps(cell, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
        return cost

    try:
        with io.TextIOWrapper(stream, encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            columns = next(reader, [])
            page_bytes = _TABLE_PAGE_ENVELOPE_BYTES + row_cost(columns)
            if page_bytes > MAX_TABLE_PAGE_BYTES:
                raise ValueError("Table page exceeds the response byte limit")
            rows: list[list[str]] = []
            has_more = False
            for index, row in enumerate(reader):
                if index < offset:
                    continue
                if len(rows) == limit:
                    has_more = True
                    break
                cost = row_cost(row)
                if page_bytes + cost > MAX_TABLE_PAGE_BYTES:
                    raise ValueError("Table page exceeds the response byte limit")
                page_bytes += cost
                rows.append(row)
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        raise ResultPreviewError("Table could not be previewed") from error
    return {"columns": columns, "rows": rows, "offset": offset, "limit": limit, "has_more": has_more}


def array_projection_query(args: Mapping[str, Any]) -> tuple[str | None, str, int]:
    """Validate the bounded array query the projection route serves.

    ``max_elements`` is required (its default of 0 is refused), a repeated or
    non-decimal value is refused, and only ``key``/``kind``/``max_elements`` are
    accepted, so a replay route cannot silently ignore a bound the live route
    enforces.
    """
    if set(args) - {"key", "kind", "max_elements"}:
        raise ResultPreviewError("Invalid array query")
    values = args.getlist("max_elements")
    raw = values[0] if values else "0"
    if len(values) > 1 or _BOUNDED_INTEGER.fullmatch(raw) is None:
        raise ResultPreviewError("Array projection is outside allowed bounds")
    max_elements = int(raw)
    keys = args.getlist("key")
    kinds = args.getlist("kind")
    if (
        max_elements < 1
        or max_elements > MAX_PROJECTION_ELEMENTS
        or len(keys) > 1
        or len(kinds) > 1
    ):
        raise ResultPreviewError("Array projection is outside allowed bounds")
    return (keys[0] if keys else None), (kinds[0] if kinds else "numeric"), max_elements


def read_bounded_array_projection(
    stream: Any,
    *,
    name: str,
    key: str | None,
    kind: str,
    max_elements: int,
) -> dict[str, Any]:
    """Project one array artifact under the route's element and byte bounds.

    Delegates to :func:`revocompute.ndarray.read_array_projection` -- the reader
    the live route serves through -- and restates its refusal in the route's own
    error type so both callers answer the same bounded 400.
    """
    try:
        return read_array_projection(stream, name=name, key=key, kind=kind, max_elements=max_elements)
    except ArrayAccessError as error:
        raise ResultPreviewError(str(error)) from error


def project_result_manifest(
    manifest: Mapping[str, Any],
    *,
    task_id: str,
    status: str,
    terminal: bool,
    error: str | None = None,
    archive: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the served response body for one published ResultManifest.

    ``manifest`` is the on-disk record, already narrowed by the caller to the
    artifacts and views the caller may see. The function adds the serve-time
    envelope and the URL/capability enrichment and replaces ``result.files``
    with the resolved logical-file projection.
    """
    payload = dict(manifest)
    payload.update(
        {
            "status": status,
            "terminal": terminal,
            "error": error,
            "archive": dict(archive) if archive is not None else {},
        }
    )
    for artifact in payload.get("artifacts", []):
        artifact.setdefault("capability", artifact_capability(artifact.get("preview"), artifact.get("logical_type")))
        encoded_path = quote(artifact["path"], safe="/")
        artifact["url"] = f"/compute/api/results/{task_id}/artifacts/{encoded_path}"
        if artifact["capability"] == "table":
            artifact["table_url"] = f"/compute/api/results/{task_id}/tables/{encoded_path}"
        if os.path.splitext(artifact["path"])[1].lower() in {".csv", ".json", ".npy", ".npz", ".tsv"}:
            artifact["ndarray_url"] = f"/compute/api/results/{task_id}/ndarrays/{encoded_path}"
    logical_files: dict[str, list[dict[str, Any]]] = {}
    for file_id, files in payload.get("result", {}).get("files", {}).items():
        logical_files[file_id] = [
            {
                "id": file_id,
                "name": os.path.basename(artifact["path"]),
                "path": artifact["path"],
                "media_type": artifact["media_type"],
                "size": artifact["size"],
                "role": artifact["role"],
                "cardinality": artifact["cardinality"],
                "viewer": artifact.get("logical_type") or artifact["preview"] or "download",
                "preview": artifact.get("logical_type") or artifact["preview"],
                "capability": artifact_capability(artifact.get("preview"), artifact.get("logical_type")),
                "url": f"/compute/api/results/{task_id}/files/{file_id}?index={index}",
                **(
                    {"confidence_encoding": "plddt_bfactor"}
                    if artifact.get("confidence_encoding") == "plddt_bfactor"
                    else {}
                ),
                **(
                    {"table_url": f"/compute/api/results/{task_id}/tables/{quote(artifact['path'], safe='/')}"}
                    if artifact_capability(artifact.get("preview"), artifact.get("logical_type")) == "table"
                    else {}
                ),
                **(
                    {"ndarray_url": f"/compute/api/results/{task_id}/ndarrays/{quote(artifact['path'], safe='/')}"}
                    if os.path.splitext(artifact["path"])[1].lower() in {".csv", ".json", ".npy", ".npz", ".tsv"}
                    else {}
                ),
            }
            for index, artifact in enumerate(files)
        ]
    payload["result"] = {"files": logical_files}
    if payload.get("storyboard"):
        payload["storyboard"]["entrypoint_url"] = (
            f"/compute/api/results/{task_id}/storyboard/{payload['storyboard']['entrypoint']}"
        )
    return payload
