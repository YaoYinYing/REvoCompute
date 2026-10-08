# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Result-retention maintenance task and shared artifact deletion helpers."""

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from revocompute import resource_lifecycle
from revocompute import resource_ledger as rloan
from revocompute.config import ComputeConfig, env_float
from revocompute.db import TaskDatabase
from revocompute.maintenance.model import PeriodicTask
from revocompute.storage import StorageResolver

_TASK_ID_PATTERN = re.compile(r"[a-fA-F0-9]{32}$")
_TERMINAL_RESULT_STATUSES = {"finished", "failed", "cancelled"}
_CLEANUP_CLAIMS = {
    "finished": ("deleting:finished", "cleaned:finished"),
    "failed": ("deleting:cancel", "cleaned:cancel"),
    "cancelled": ("deleting:cancel", "cleaned:cancel"),
}
_CLAIMED_CLEANUPS = dict(_CLEANUP_CLAIMS.values())


def _path_is_within(base_dir: str, candidate: str) -> bool:
    base_abs = os.path.abspath(base_dir)
    target_abs = os.path.abspath(candidate)
    try:
        common = os.path.commonpath([base_abs, target_abs])
    except ValueError:
        return False
    return common == base_abs


class ArtifactRemovalError(RuntimeError):
    """An owned artifact path was refused or could not be removed.

    The lifecycle treats this remover as transactional -- a completed purge
    frees exactly the bytes that were charged -- so a removal that cannot do
    what it claims must fail closed.  A refused unsafe path or an ``rmtree``
    that leaves bytes behind (a permission or I/O error) therefore raises
    instead of being logged and swallowed: the purge records ``ERROR``, keeps
    the charge, and a later pass retries, rather than releasing quota for data
    that is still on disk.
    """


def _remove_owned_tree(path: str, *, label: str) -> None:
    """Remove *path* completely, or raise.  Already-absent is idempotent success."""
    if not os.path.lexists(path):
        return
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        # A concurrent removal emptied it first: the bytes are gone.
        return
    except OSError as exc:
        raise ArtifactRemovalError(f"could not remove {label} {path}: {exc}") from exc
    if os.path.lexists(path):
        # A partial removal that left a locked entry behind would still return
        # normally; the bytes are what the charge describes, so their survival
        # is a failure.
        raise ArtifactRemovalError(f"{label} {path} survived its removal")


def delete_task_artifacts(task: dict[str, Any], results_folder: str, workspace_folder: str | None = None) -> None:
    """Safely remove one task's result tree, archive cache, and input snapshot.

    The destructive boundary fails closed.  A path outside the folders this
    deployment owns is refused, and a refusal or a failed removal raises
    :class:`ArtifactRemovalError` rather than leaving the purge to record
    success.  A path its owning folder does not contain is not this caller's to
    delete, so it is skipped: the lifecycle row records the Task's durable data,
    and an artifact this layout never owned is not part of it.
    """
    resolver = StorageResolver(
        workspace_dir=workspace_folder or os.path.join(os.path.dirname(results_folder), "workspaces"),
        results_dir=results_folder,
    )
    try:
        safe_result_dir = resolver.get_task_root(task)
    except ValueError as exc:
        raise ArtifactRemovalError(
            f"invalid storage identity for task {task.get('md5sum')}: {exc}"
        ) from exc
    if os.path.lexists(safe_result_dir):
        if safe_result_dir in {os.path.abspath(os.sep), os.path.abspath(os.path.expanduser("~"))}:
            raise ArtifactRemovalError(f"refusing to delete unsafe root-like directory {safe_result_dir}")
        if not _path_is_within(results_folder, safe_result_dir):
            raise ArtifactRemovalError(
                f"refusing to delete result directory {safe_result_dir} outside RESULTS_FOLDER"
            )
        _remove_owned_tree(safe_result_dir, label="result tree")

    task_id = str(task.get("md5sum") or "").strip().lower()
    if not _TASK_ID_PATTERN.fullmatch(task_id):
        raise ArtifactRemovalError(f"invalid task id for archive path: {task.get('md5sum')}")
    zip_path = resolver.get_archive_path(task)
    if _path_is_within(results_folder, zip_path) and os.path.lexists(zip_path):
        # A single file removes atomically, so its failure is a real one; a
        # missing file means the bytes are already gone.
        try:
            os.remove(zip_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ArtifactRemovalError(f"could not remove results archive {zip_path}: {exc}") from exc

    if workspace_folder:
        try:
            workspace_dir = resolver.get_input_root(task)
        except ValueError as exc:
            raise ArtifactRemovalError(
                f"invalid task input storage for task {task_id}: {exc}"
            ) from exc
        if _path_is_within(workspace_folder, workspace_dir):
            _remove_owned_tree(workspace_dir, label="input snapshot")


def cleanup_expired_task_artifacts(
    retention_days: float,
    *,
    task_store: TaskDatabase,
    results_folder: str,
    now: float | None = None,
) -> int:
    """Retire artifacts for terminal tasks older than *retention_days*.

    Retention *decides* which Task has aged out; it does not delete.  The
    deletion is the canonical data-lifecycle transaction — a durable request,
    then one purge owner that removes the bytes and releases exactly the charged
    logical bytes — because a retention path that deleted files on its own would
    leave the charged ``ACTIVE`` lifecycle row behind and keep the user's storage
    quota consumed forever for data that is gone.

    The status marker the UI and API present (``deleting:*`` while a deletion is
    in flight, ``cleaned:*`` once the bytes are gone) is *derived from the purge
    outcome* rather than maintained as a parallel cleanup state machine: it is
    claimed before the purge so a resubmission cannot be retired by mistake, and
    completed only once the purge reports the data is gone.
    """
    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    timestamp = time.time() if now is None else now
    cutoff = timestamp - retention_days * 86400
    workspace_folder = os.path.join(os.path.dirname(results_folder), "workspaces")
    remove_artifacts = _artifact_remover(results_folder, workspace_folder)
    cleaned = 0
    for task in task_store.list_tasks():
        status = str(task.get("status") or "").strip().lower()
        if status in _CLAIMED_CLEANUPS:
            # A deletion that was already claimed and interrupted: resume it
            # from the durable claim rather than deciding eligibility again.
            claim_status = status
            cleaned_status = _CLAIMED_CLEANUPS[status]
        elif status in _TERMINAL_RESULT_STATUSES:
            finished_at = task.get("finished_at")
            if finished_at is None or finished_at > cutoff:
                continue
            claim_status, cleaned_status = _CLEANUP_CLAIMS[status]
            if not task_store.claim_task_cleanup(
                task["md5sum"],
                expected_status=status,
                expected_finished_at=finished_at,
                claim_status=claim_status,
            ):
                continue
        else:
            continue
        if not _retire_expired_task(
            task, task_store=task_store, remove_artifacts=remove_artifacts, at=timestamp
        ):
            # The lifecycle row records the failure and keeps the charge, so the
            # next pass retries it; the claim stays in place meanwhile.
            continue
        if not task_store.complete_task_cleanup(
            task["md5sum"],
            claim_status=claim_status,
            cleaned_status=cleaned_status,
        ):
            logging.warning("Cleanup claim changed before completion for task %s", task["md5sum"])
            continue
        cleaned += 1
    return cleaned


def _artifact_remover(results_folder: str, workspace_folder: str) -> Callable[[dict[str, Any]], None]:
    def remove_artifacts(task: dict[str, Any]) -> None:
        delete_task_artifacts(task, results_folder, workspace_folder)

    return remove_artifacts


def _retire_expired_task(
    task: dict[str, Any],
    *,
    task_store: TaskDatabase,
    remove_artifacts: Callable[[dict[str, Any]], None],
    at: float,
) -> bool:
    """Drive one Task's retirement through the canonical lifecycle, idempotently.

    Returns whether the Task's durable data is gone — already, or as a result of
    this call.  Every step is the lifecycle's own transition, so a repeated pass
    (or a purge the maintenance task already completed) adds nothing.
    """
    task_id = str(task["md5sum"])
    # The durable request precedes any filesystem work: after it, a crash is a
    # resumable purge rather than an intact tree whose row still reads ACTIVE.
    resource_lifecycle.request_data_deletion(task_store, task, actor_user_id=None, at=at)
    record = task_store.get_data_lifecycle(task_id)
    if record is None:  # pragma: no cover - request_data_deletion always records one
        return False
    state = str(record["state"])
    if state == rloan.DataLifecycleState.PURGED.value:
        return True
    if state == rloan.DataLifecycleState.ERROR.value:
        # A purge that failed keeps its charge; re-queue it through the same
        # guarded transition the first attempt used rather than freeing quota.
        if not task_store.requeue_data_lifecycle(task_id, at=at):
            return False
    elif state == rloan.DataLifecycleState.PURGING.value:
        claimed_at = float(record.get("claimed_at") or record.get("updated_at") or 0.0)
        if at - claimed_at < resource_lifecycle.PURGE_STALE_SECONDS:
            # A live purge owns this Task right now.
            return False
        if not task_store.reclaim_stale_purge(task_id, at=at):
            return False
    try:
        return resource_lifecycle.purge_task_data(
            task_store, task, remove_artifacts=remove_artifacts, at=at
        )
    except Exception:
        # Already recorded as ERROR with its charge intact; a later pass retries.
        logging.exception("Retention purge failed for task %s", task_id)
        return False


def run_result_cleanup(retention_days: float) -> int:
    """Open the configured task store and run one result-retention pass."""
    config = ComputeConfig.from_env()
    task_store = TaskDatabase(config.db_path)
    cleaned = cleanup_expired_task_artifacts(
        retention_days,
        task_store=task_store,
        results_folder=config.results_folder,
    )
    if cleaned:
        logging.info("Removed expired result artifacts for %d task(s)", cleaned)
    return cleaned


class ResultCleanupTask(PeriodicTask):
    """Environment-configured terminal-result retention cleanup."""

    id = "result-retention-cleanup"

    @property
    def task_method(self) -> Callable[..., Any]:
        return run_result_cleanup

    def configure(self) -> None:
        retention_days = env_float("RESULT_RETENTION_DAYS", 0.0)
        self.env = {"RESULT_RETENTION_DAYS": retention_days}
        self._is_enabled = False
        self._args = {}

        if retention_days < 0:
            raise ValueError("RESULT_RETENTION_DAYS must be zero or positive")
        if retention_days == 0:
            return

        self._is_enabled = True
        self._args = {
            "trigger": "interval",
            "days": 1,
            "args": (retention_days,),
            "misfire_grace_time": 86400,
            "next_run_time": datetime.now(timezone.utc),
        }


result_cleanup_task = ResultCleanupTask()
