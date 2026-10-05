# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""The shared result projection is byte-identical to the pre-change route body.

The ``GET /compute/api/results`` route now builds its body through
``revocompute.result_projection.project_result_manifest`` instead of an inline
loop. This test pins the equivalence the route relies on: for the same inputs,
the shared function produces exactly the body the previous route produced -- in
both the full-results case and the narrowed (visibility-only) case. A divergence
in consumer-visible output fails here rather than reaching a frontend.
"""

from __future__ import annotations

from urllib.parse import quote

from revocompute.result_projection import project_result_manifest


def _legacy_serve_body(
    manifest: dict,
    task_id: str,
    *,
    status: str,
    terminal: bool,
    error: str | None,
    archive: dict,
) -> dict:
    """The exact body ``get_results`` produced before the projection was shared.

    A verbatim copy of the previous inline implementation, kept as the reference
    the shared function must reproduce. It is intentionally not refactored: its
    only purpose is to be the frozen pre-change behavior.
    """
    import os

    from revocompute.result_projection import artifact_capability

    payload = dict(manifest)
    payload.update(
        {
            "status": status,
            "terminal": terminal,
            "error": error,
            "archive": archive,
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
    logical_files: dict[str, list] = {}
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


TASK_ID = "0123456789abcdef0123456789abcdef"


def _manifest() -> dict:
    """A manifest spanning a table, a plain text artifact, a JSON matrix, and a storyboard."""
    return {
        "schema_version": 3,
        "task_id": TASK_ID,
        "task_type": "gremlin_lh_fit",
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": "finished",
        "terminal": True,
        "error": None,
        "run": {"method": {"id": "gremlin_lh_fit", "name": "GREMLIN_LH"}, "inputs": [], "parameters": []},
        "output_check": {"state": "passed", "checks": [], "problems": []},
        "limitations": [],
        "views": [
            {"id": "raw", "plugin": "matrix", "role": "primary", "title": "Raw", "sources": {"matrices": ["couplings/raw_scores.csv"]}},
            {"id": "logs", "plugin": "evidence-bundle", "role": "evidence", "title": "Logs", "sources": {"files": ["execution/slurm.stdout"]}},
        ],
        "artifacts": [
            {
                "path": "couplings/raw_scores.csv",
                "size": 30,
                "sha256": "a" * 64,
                "media_type": "text/csv",
                "preview": "table",
                "role": "primary",
                "confidence_encoding": "plddt_bfactor",
            },
            {
                "path": "execution/slurm.stdout",
                "size": 12,
                "sha256": "b" * 64,
                "media_type": "text/plain",
                "preview": "text",
                "role": "diagnostic",
            },
            {
                "path": "summary.json",
                "size": 20,
                "sha256": "c" * 64,
                "media_type": "application/json",
                "preview": "text",
                "role": "provenance",
            },
        ],
        "result": {
            "files": {
                "raw_matrix": [
                    {"path": "couplings/raw_scores.csv", "role": "primary", "cardinality": "one", "logical_type": "table",
                     "media_type": "text/csv", "preview": "table", "size": 30, "sha256": "a" * 64,
                     "confidence_encoding": "plddt_bfactor"},
                ],
                "summary": [
                    {"path": "summary.json", "role": "provenance", "cardinality": "one", "logical_type": "json",
                     "media_type": "application/json", "preview": "text", "size": 20, "sha256": "c" * 64},
                ],
            }
        },
        "storyboard": {"identifier": "demo", "entrypoint": "index.js", "requires": ["raw_matrix"], "optional": []},
        "outcome": "SUCCESS",
        "total_size": 62,
    }


def _manifest_without_diagnostics() -> dict:
    manifest = _manifest()
    manifest["artifacts"] = [artifact for artifact in manifest["artifacts"] if artifact["role"] != "diagnostic"]
    manifest["views"] = [view for view in manifest["views"] if view["id"] != "logs"]
    return manifest


ARCHIVE = {"ready": False, "request_url": f"/compute/api/results/{TASK_ID}/archive", "download_url": None}


def test_full_results_projection_matches_the_pre_change_route_body() -> None:
    manifest = _manifest()
    shared = project_result_manifest(
        manifest, task_id=TASK_ID, status="finished", terminal=True, error=None, archive=ARCHIVE
    )
    legacy = _legacy_serve_body(
        _manifest(), TASK_ID, status="finished", terminal=True, error=None, archive=dict(ARCHIVE)
    )
    assert shared == legacy
    # Spot-check the consumer-visible enrichments so a whole-body regression is legible.
    assert shared["artifacts"][0]["table_url"].endswith("/tables/couplings/raw_scores.csv")
    assert shared["artifacts"][0]["ndarray_url"].endswith("/ndarrays/couplings/raw_scores.csv")
    assert shared["result"]["files"]["raw_matrix"][0]["confidence_encoding"] == "plddt_bfactor"
    assert shared["storyboard"]["entrypoint_url"].endswith("/storyboard/index.js")


def test_narrowed_projection_matches_the_pre_change_route_body() -> None:
    """The visibility-only case: diagnostics removed before the projection."""
    narrowed = _manifest()
    narrowed["artifacts"] = [artifact for artifact in narrowed["artifacts"] if artifact["role"] != "diagnostic"]
    narrowed["views"] = [view for view in narrowed["views"] if view["id"] != "logs"]
    shared = project_result_manifest(
        narrowed, task_id=TASK_ID, status="finished", terminal=True, error=None, archive=dict(ARCHIVE)
    )
    # The reference is the same pre-change body, fed the same narrowed inputs the
    # route would have produced after its authorization filter.
    legacy = _legacy_serve_body(
        _manifest_without_diagnostics(), TASK_ID, status="finished", terminal=True, error=None, archive=dict(ARCHIVE)
    )
    assert shared == legacy
    assert {artifact["path"] for artifact in shared["artifacts"]} == {"couplings/raw_scores.csv", "summary.json"}


def test_a_failed_terminal_manifest_matches_the_pre_change_route_body() -> None:
    manifest = _manifest()
    manifest["status"] = "failed"
    manifest["error"] = "runner stopped"
    shared = project_result_manifest(
        manifest, task_id=TASK_ID, status="failed", terminal=True, error="runner stopped", archive=dict(ARCHIVE)
    )
    legacy = _legacy_serve_body(
        {**_manifest(), "status": "failed", "error": "runner stopped"},
        TASK_ID, status="failed", terminal=True, error="runner stopped", archive=dict(ARCHIVE),
    )
    assert shared == legacy
    assert shared["error"] == "runner stopped"
