# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Capture a machine-generated production API acceptance receipt.

Composes the existing sources of truth — the task store row, the published
ResultManifest, the runner-written Slurm accounting, the deploy stamp, and the
immutable result artifacts — into one canonical receipt document. It replaces
the hand-copied acceptance narrative with observed state; it does not add a
second task database, a second manifest, or a Runner-specific path.

    REVODESIGN_SERVER_ENV=/path/server.env \
      bash run/restart.sh api-receipt --task <task-id> [--runner <family>]

Exit status is non-zero when the receipt is incomplete or inconsistent.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from revocompute.api_receipt import (
    ApiReceiptError,
    build_api_receipt,
    parse_api_receipt,
    receipt_failures,
    render_api_receipt_summary,
)
from revocompute.live_tests import atomic_write_json, sha256_file

_TASK_ID = re.compile("[a-fA-F0-9]{32}")
_RESOURCE_NAME = re.compile(r"\.resource\.json\Z")


class ApiReceiptCaptureError(RuntimeError):
    """The receipt could not be captured from the supplied state."""


def _read_json(path: str | Path) -> Mapping[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, Mapping) else None


def _read_task_row(db_path: str, task_id: str) -> dict[str, Any]:
    """Read one task row from the deployment's authoritative task store."""
    if not os.path.isfile(db_path):
        raise ApiReceiptCaptureError(f"task database not found: {db_path}")
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ApiReceiptCaptureError(f"task database cannot be opened: {exc}") from exc
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM tasks WHERE md5sum = ?", (task_id,)).fetchone()
    except sqlite3.Error as exc:
        raise ApiReceiptCaptureError(f"task store is not readable: {exc}") from exc
    finally:
        connection.close()
    if row is None:
        raise ApiReceiptCaptureError(f"task {task_id} is not in the task store")
    return dict(row)


def result_root_for(task_row: Mapping[str, Any], results_folder: str) -> str:
    """The authoritative result root, resolved from the task's stored identity."""
    from revocompute.storage import StorageResolver

    resolver = StorageResolver(results_folder, results_folder)
    return resolver.get_task_root(dict(task_row))


def _find_resource_payload(result_root: str) -> Mapping[str, Any] | None:
    """The executor's own Slurm accounting, written beside the results.

    Located by the runner's naming convention (``execution/*.resource.json``),
    not by the task type, so any family that runs under Slurm resolves here.
    """
    execution = Path(result_root) / "execution"
    try:
        candidates = sorted(
            path for path in execution.glob("*.resource.json") if _RESOURCE_NAME.search(path.name)
        )
    except OSError:
        return None
    for candidate in candidates:
        payload = _read_json(candidate)
        if payload is not None and payload.get("source") == "allocation_wrapper":
            return payload
    return None


def receipt_path(config_dir: str, task_id: str) -> Path:
    """Where the checked-in receipt for one task lives, under the deploy config."""
    return Path(config_dir) / "api-receipts" / f"{task_id}.json"


def _runner_sif_sha256(state, task_type: str) -> str | None:
    """The exact promoted SIF the task's Runner executed, hashed from disk.

    Resolved through the same deployed plugin tree the server reads, so the
    receipt records the container image that actually ran rather than a value
    copied from prose. Best-effort: an unreadable or absent image yields None.
    """
    from revocompute.task_types import discover_plugins, get

    runners_dir = state.get("RUNNERS_DIR") or os.path.join(state.server_dir(), "docker", "runners")
    images_root = os.path.join(state.server_dir(), "..", "images")
    try:
        discover_plugins(runners_dir)
        task_type_def, _runner = get(task_type)
        image = os.path.join(images_root, task_type_def.runtime.image_artifact)
        if not os.path.isfile(image):
            image = task_type_def.runtime.slurm_image
    except (KeyError, ValueError, OSError):
        return None
    if not image or not os.path.isfile(image):
        return None
    return sha256_file(image)


def capture_api_receipt(
    state,
    task_id: str,
    *,
    base_url: str = "",
    runtime_sif_sha256: str | None = None,
    status_evidence: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], Path]:
    """Build, validate, and persist the receipt for one completed submission."""
    task_id = str(task_id).strip().lower()
    if not _TASK_ID.fullmatch(task_id):
        raise ApiReceiptCaptureError(f"invalid task id: {task_id!r}")
    db_path = state.get("DB_PATH") or os.path.join(state.server_dir(), "revocompute.sqlite3")
    results_folder = state.get("RESULTS_FOLDER") or os.path.join(state.server_dir(), "results")
    task_row = _read_task_row(db_path, task_id)
    result_root = result_root_for(task_row, results_folder)
    manifest = _read_json(os.path.join(result_root, "manifest.json"))
    if manifest is None:
        raise ApiReceiptCaptureError(f"no published ResultManifest for task {task_id}")
    deployment_stamp = _read_json(os.path.join(state.config_dir(), ".deploy-stamp"))
    if runtime_sif_sha256 is None:
        runtime_sif_sha256 = _runner_sif_sha256(str(task_row.get("task_type") or ""))
    receipt = build_api_receipt(
        task_id=task_id,
        manifest=manifest,
        task_row=task_row,
        result_root=result_root,
        deployment_stamp=deployment_stamp,
        resource_payload=_find_resource_payload(result_root),
        runtime_sif_sha256=runtime_sif_sha256,
        status_evidence=status_evidence,
        base_url=base_url or state.get("SERVER_BASE_URL"),
    )
    persisted = parse_api_receipt(receipt)
    destination = receipt_path(state.config_dir(), task_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, persisted)
    return persisted, destination


def cmd_api_receipt(state, task_id: str, *, base_url: str = "") -> int:
    try:
        receipt, destination = capture_api_receipt(state, task_id, base_url=base_url)
    except ApiReceiptError as exc:
        print(f"Receipt could not be captured: {exc}")
        return 1
    print(render_api_receipt_summary(receipt))
    print(f"Receipt written to: {destination}")
    failures = receipt_failures(receipt)
    if failures:
        print(f"Receipt is INCOMPLETE ({len(failures)} problem(s)); see the receipt for details.")
        return 1
    return 0
