# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Restart-safe durable-data purge and resource reconciliation.

Deletion is a transaction, never "rm -rf, then mark deleted":

1. the Task is moved to ``DELETE_REQUESTED`` durably *before* any filesystem
   work, so a crash leaves a resumable deletion rather than an intact tree whose
   row still reads ``ACTIVE``;
2. a ``DELETE_REQUESTED`` row is claimed into ``PURGING`` by exactly one
   worker;
3. only after the owned bytes are actually gone does ``complete_data_purge``
   release the quota that was charged — and it releases exactly what was
   charged, once.

Reconciliation follows the same rule: everything here is safe to run
repeatedly, repairs only cases with unambiguous ownership, and surfaces
anything else as a drift record instead of guessing.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from revocompute import resource_ledger as rloan
from revocompute.db import TaskDatabase

#: How long a ``PURGING`` row may sit before reconciliation treats it as a
#: crash to retry.  A purge is a bounded filesystem walk, so this is generous.
PURGE_STALE_SECONDS = 3600.0


def request_data_deletion(
    task_store: TaskDatabase,
    task: dict[str, Any],
    *,
    actor_user_id: int | None,
    at: float | None = None,
) -> bool:
    """Durably record one Task's deletion request before touching the files."""
    return task_store.claim_data_deletion(
        str(task["md5sum"]),
        user_id=int(task.get("submitted_by_user_id") or 0),
        actor_user_id=actor_user_id,
        at=at,
    )


def purge_task_data(
    task_store: TaskDatabase,
    task: dict[str, Any],
    *,
    remove_artifacts: Callable[[dict[str, Any]], None],
    at: float | None = None,
) -> bool:
    """Claim, delete, complete one Task's durable data.

    ``remove_artifacts(task)`` performs the destructive work; it is injected so
    this module owns the transaction and the caller owns the storage layout.
    A failure inside it leaves the Task in ``ERROR`` with its bytes still
    charged, so a later pass retries instead of silently freeing quota.
    """
    task_id = str(task["md5sum"])
    timestamp = time.time() if at is None else at
    if not task_store.begin_data_purge(task_id, at=timestamp):
        return False
    try:
        remove_artifacts(task)
    except Exception as exc:
        # Destructive work failed: the owned bytes are still charged and the row
        # records the failure.  The exception propagates so the caller keeps its
        # own failure contract — a synchronous delete still reports 500 and
        # leaves its cleanup claim resumable, exactly as it did before this
        # transaction existed.
        logging.exception("Could not purge data for task %s", task_id)
        task_store.mark_data_lifecycle_error(task_id, error=str(exc), at=timestamp)
        raise
    return task_store.complete_data_purge(task_id, at=timestamp)


def purge_requested_tasks(
    task_store: TaskDatabase,
    *,
    remove_artifacts: Callable[[dict[str, Any]], None],
    limit: int = 100,
    now: float | None = None,
) -> dict[str, int]:
    """Purge every Task awaiting deletion.  Safe to run repeatedly."""
    timestamp = time.time() if now is None else now
    purged = failed = 0
    rows = task_store.list_data_lifecycle(
        states=(rloan.DataLifecycleState.DELETE_REQUESTED.value,),
        limit=limit,
    )
    for record in rows:
        task = task_store.get_task(str(record["task_id"]))
        if task is None:
            # No Task row owns this lifecycle row: the Task was hard-removed.
            # Finishing the purge releases nothing (nothing was charged to a
            # missing Task) and clears the orphan, which is unambiguous.
            task_store.begin_data_purge(str(record["task_id"]), at=timestamp)
            if task_store.complete_data_purge(str(record["task_id"]), at=timestamp):
                purged += 1
            continue
        try:
            if purge_task_data(task_store, task, remove_artifacts=remove_artifacts, at=timestamp):
                purged += 1
            else:
                failed += 1
        except Exception:
            # One Task's failed purge must not stop the pass; its row is already
            # marked ERROR and a later pass retries it.
            failed += 1
    return {"purged": purged, "failed": failed}


def retry_stale_purges(
    task_store: TaskDatabase,
    *,
    remove_artifacts: Callable[[dict[str, Any]], None],
    stale_seconds: float = PURGE_STALE_SECONDS,
    now: float | None = None,
) -> dict[str, int]:
    """Re-drive a purge whose worker died between claim and completion."""
    timestamp = time.time() if now is None else now
    recovered = 0
    for record in task_store.list_data_lifecycle(
        states=(rloan.DataLifecycleState.PURGING.value, rloan.DataLifecycleState.ERROR.value),
        limit=500,
    ):
        claimed_at = record.get("claimed_at") or record.get("updated_at") or 0.0
        if record["state"] == rloan.DataLifecycleState.PURGING.value and timestamp - float(claimed_at) < stale_seconds:
            continue
        task_id = str(record["task_id"])
        task = task_store.get_task(task_id)
        if task is None:
            if task_store.complete_data_purge(task_id, at=timestamp):
                recovered += 1
            continue
        # Re-enter the transaction from the durable request state.  ``ERROR``
        # goes back to ``PURGING`` through the same guard the first attempt used.
        if record["state"] == rloan.DataLifecycleState.ERROR.value:
            task_store.requeue_data_lifecycle(task_id, at=timestamp)
        try:
            if purge_task_data(task_store, task, remove_artifacts=remove_artifacts, at=timestamp):
                recovered += 1
        except Exception:
            # Already re-marked ERROR with its charge intact; retry next pass.
            continue
    return {"recovered": recovered}


def detect_drift(task_store: TaskDatabase, *, now: float | None = None) -> list[rloan.ReconciliationDrift]:
    """Read-only consistency check between persisted facts and reality.

    Only unambiguous cases are reported here; the caller decides what to repair.
    """
    timestamp = time.time() if now is None else now
    drift: list[rloan.ReconciliationDrift] = []
    for record in task_store.list_unsettled_allocations():
        task = task_store.get_task(str(record["task_id"]))
        if task is None:
            drift.append(
                rloan.ReconciliationDrift(
                    kind="allocation_without_task",
                    subject=str(record["slurm_job_id"]),
                    detail="an allocation row has no owning Task row",
                )
            )
            continue
        status = str(task.get("status") or "")
        if status in {"finished", "failed", "cancelled"} | set(task_store.DELETED_STATUSES):
            drift.append(
                rloan.ReconciliationDrift(
                    kind="terminal_task_unsettled_allocation",
                    subject=str(record["task_id"]),
                    detail=f"Task is {status} but allocation {record['slurm_job_id']} is {record['status']}",
                    repairable=True,
                )
            )
    for record in task_store.list_data_lifecycle(limit=5000):
        task_id = str(record["task_id"])
        state = str(record["state"])
        if state == rloan.DataLifecycleState.PURGED.value and (
            int(record["logical_bytes"]) or int(record["accounted_bytes"])
        ):
            drift.append(
                rloan.ReconciliationDrift(
                    kind="purged_with_owned_bytes",
                    subject=task_id,
                    detail="a PURGED row still reports owned or accounted bytes",
                )
            )
        if state == rloan.DataLifecycleState.PURGING.value:
            claimed_at = float(record.get("claimed_at") or record.get("updated_at") or 0.0)
            if timestamp - claimed_at >= PURGE_STALE_SECONDS:
                drift.append(
                    rloan.ReconciliationDrift(
                        kind="stale_purge",
                        subject=task_id,
                        detail="a purge claim has not completed and can be retried",
                        repairable=True,
                    )
                )
        if state in rloan.CHARGED_LIFECYCLE_STATES and task_store.get_task(task_id) is None:
            drift.append(
                rloan.ReconciliationDrift(
                    kind="lifecycle_without_task",
                    subject=task_id,
                    detail="a lifecycle row charges bytes for a Task that no longer exists",
                    repairable=True,
                )
            )
    for record in task_store.list_reservations(state=rloan.ReservationState.HELD.value, limit=2000):
        if float(record.get("expires_at") or 0.0) <= timestamp:
            drift.append(
                rloan.ReconciliationDrift(
                    kind="stale_reservation",
                    subject=str(record["task_id"]),
                    detail="an admission hold outlived its TTL",
                    repairable=True,
                )
            )
    return drift


def reconcile_resources(
    task_store: TaskDatabase,
    *,
    settle_allocations=None,
    now: float | None = None,
) -> rloan.ReconciliationReport:
    """Run one bounded reconciliation pass.  Safe to repeat.

    ``settle_allocations`` is the worker-side scheduler-evidence step (the
    ``scontrol`` recovery); it is optional so this pass is still meaningful on a
    host with no scheduler, and it is never allowed to charge an ambiguous
    allocation.
    """
    timestamp = time.time() if now is None else now
    settled = review = active = 0
    if settle_allocations is not None:
        outcome = settle_allocations() or {}
        settled = int(outcome.get("settled", 0))
        review = int(outcome.get("review", 0))
        active = int(outcome.get("active", 0))
    expired = task_store.expire_stale_reservations(now=timestamp)
    return rloan.ReconciliationReport(
        settled_allocations=settled,
        review_allocations=review,
        active_allocations=active,
        expired_reservations=expired,
        drift=tuple(detect_drift(task_store, now=timestamp)),
    )
