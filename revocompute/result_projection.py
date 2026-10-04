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

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote


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
