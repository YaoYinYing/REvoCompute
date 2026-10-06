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
from revocompute.operational_events import emit_event

#: How long a ``PURGING`` row may sit before reconciliation treats it as a
#: crash to retry.  A purge is a bounded filesystem walk, so this is generous.
PURGE_STALE_SECONDS = 3600.0


def _emit(event: str, *, level: str = "INFO", **fields: Any) -> None:
    """Publish one lifecycle fact without risking the transition it describes.

    These events are the audit trail of an *authorized* transition, emitted next
    to the durable write that performs it.  They are not the transition itself:
    an unavailable log must never roll back a completed purge or turn a refused
    deletion into a 500, so emission is total.
    """
    try:
        emit_event(event, level=level, **fields)
    except Exception:  # defensive: emission never fails a lifecycle transition
        logging.exception("Could not emit lifecycle event %s", event)


def request_data_deletion(
    task_store: TaskDatabase,
    task: dict[str, Any],
    *,
    actor_user_id: int | None,
    at: float | None = None,
) -> bool:
    """Durably record one Task's deletion request before touching the files."""
    task_id = str(task["md5sum"])
    recorded = task_store.claim_data_deletion(
        task_id,
        user_id=int(task.get("submitted_by_user_id") or 0),
        actor_user_id=actor_user_id,
        at=at,
    )
    if recorded:
        _emit(
            "resource.lifecycle.requested",
            task_id=task_id,
            user_id=int(task.get("submitted_by_user_id") or 0) or None,
        )
    return recorded


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
        error = str(exc)
        task_store.mark_data_lifecycle_error(task_id, error=error, at=timestamp)
        _emit(
            "resource.lifecycle.error",
            level="ERROR",
            task_id=task_id,
            user_id=int(task.get("submitted_by_user_id") or 0) or None,
        )
        raise
    # Read the charged amount *before* completion zeroes it: the event reports
    # what this purge released, and that is a fact of the transition, not of the
    # row's end state.
    before = task_store.get_data_lifecycle(task_id) or {}
    released_bytes = max(0, int(before.get("accounted_bytes") or 0))
    subject_id = int(before.get("subject_id") or task.get("submitted_by_user_id") or 0)
    purged = task_store.complete_data_purge(task_id, at=timestamp)
    if purged:
        _emit("resource.lifecycle.purged", task_id=task_id, user_id=subject_id or None)
        if released_bytes:
            # Storage release is its own event, the mirror of the charge at
            # publication: how many bytes this deletion freed, and nothing about
            # which state machine ran.
            _emit(
                "resource.storage.released",
                task_id=task_id,
                user_id=subject_id or None,
                storage_bytes=released_bytes,
            )
    return purged


def _finish_orphan_purge(task_store: TaskDatabase, task_id: str, *, at: float) -> bool:
    """Complete the purge transaction for a Task row that no longer exists.

    A lifecycle row with no owning Task is unambiguous: there is no filesystem
    layout left to walk, so the interrupted transaction is finished and the
    quota it still charges is released — exactly the amount that was charged, so
    a row that never charged bytes releases nothing.  Without this, a purge
    interrupted after its Task row was hard-removed stays ``PURGING`` forever and
    keeps charging the subject.
    """
    record = task_store.get_data_lifecycle(task_id)
    if record is None:
        return False
    state = str(record["state"])
    if state == rloan.DataLifecycleState.ERROR.value:
        task_store.requeue_data_lifecycle(task_id, at=at)
        state = rloan.DataLifecycleState.DELETE_REQUESTED.value
    if state == rloan.DataLifecycleState.DELETE_REQUESTED.value:
        if not task_store.begin_data_purge(task_id, at=at):
            return False
    elif state != rloan.DataLifecycleState.PURGING.value:
        return False
    released_bytes = max(0, int(record.get("accounted_bytes") or 0))
    subject_id = int(record.get("subject_id") or 0)
    purged = task_store.complete_data_purge(task_id, at=at)
    if purged:
        _emit("resource.lifecycle.purged", task_id=task_id, user_id=subject_id or None)
        if released_bytes:
            # Storage release is its own event, the mirror of the charge at
            # publication: how many bytes this deletion freed, and nothing about
            # which state machine ran.
            _emit(
                "resource.storage.released",
                task_id=task_id,
                user_id=subject_id or None,
                storage_bytes=released_bytes,
            )
    return purged


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
            if _finish_orphan_purge(task_store, str(record["task_id"]), at=timestamp):
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
        states=(
            rloan.DataLifecycleState.DELETE_REQUESTED.value,
            rloan.DataLifecycleState.PURGING.value,
            rloan.DataLifecycleState.ERROR.value,
        ),
        limit=500,
    ):
        state = str(record["state"])
        task_id = str(record["task_id"])
        # A ``DELETE_REQUESTED`` row is included because an orphan whose Task row
        # was hard-removed has no other path to completion (``purge_requested_tasks``
        # skips it), and a reclaim races nothing: the state guard is the arbiter.
        if state == rloan.DataLifecycleState.PURGING.value:
            claimed_at = record.get("claimed_at") or record.get("updated_at") or 0.0
            if timestamp - float(claimed_at) < stale_seconds:
                # The claim is still fresh: its owner may be mid-purge right now,
                # so reclaiming it would hand the same Task to a second worker.
                continue
            # A fresh claim is a live purge; a stale one is a crash.  Recovery is
            # the reclaim itself, so a pass that reclaims but cannot finish leaves
            # a retryable row for the next pass instead of a permanent wedge.
            if not task_store.reclaim_stale_purge(task_id, at=timestamp):
                continue
        elif state == rloan.DataLifecycleState.ERROR.value:
            # ERROR goes back to DELETE_REQUESTED through the same guard the
            # first attempt used.
            if not task_store.requeue_data_lifecycle(task_id, at=timestamp):
                continue
        task = task_store.get_task(task_id)
        if task is None:
            if _finish_orphan_purge(task_store, task_id, at=timestamp):
                recovered += 1
            continue
        try:
            if purge_task_data(task_store, task, remove_artifacts=remove_artifacts, at=timestamp):
                recovered += 1
        except Exception:
            # Already re-marked ERROR with its charge intact; retry next pass.
            continue
    return {"recovered": recovered}


def detect_drift(
    task_store: TaskDatabase,
    *,
    now: float | None = None,
    owned_paths: Callable[[str], int | None] | None = None,
) -> list[rloan.ReconciliationDrift]:
    """Read-only consistency check between persisted facts and reality.

    Only unambiguous cases are reported here; the caller decides what to repair.

    ``owned_paths(task_id)`` answers a different question than the ledger can:
    how many bytes of a Task's durable data are actually *on disk* right now.
    It is injected because only the storage layer knows the layout, and it may
    return ``None`` for "not measurable" — which is reported as its own kind of
    drift rather than being read as zero, since unknown is not zero.  Accounting
    that disagrees with the filesystem in either direction is the drift this
    check exists to surface; repairing it needs a human decision about which
    side is wrong, so nothing here repairs it.
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
    if owned_paths is not None:
        for record in task_store.list_data_lifecycle(limit=5000):
            task_id = str(record["task_id"])
            state = str(record["state"])
            if state not in rloan.CHARGED_LIFECYCLE_STATES:
                continue
            on_disk = owned_paths(task_id)
            if on_disk is None:
                drift.append(
                    rloan.ReconciliationDrift(
                        kind="owned_bytes_unmeasurable",
                        subject=task_id,
                        detail="the Task owns bytes on paper but its storage could not be measured",
                    )
                )
                continue
            charged = int(record["accounted_bytes"])
            if charged and on_disk == 0:
                drift.append(
                    rloan.ReconciliationDrift(
                        kind="charged_bytes_missing_on_disk",
                        subject=task_id,
                        detail=(
                            f"{charged} bytes are charged to the subject but no owned data was found"
                        ),
                        repairable=True,
                    )
                )
            elif on_disk and not charged:
                drift.append(
                    rloan.ReconciliationDrift(
                        kind="filesystem_data_not_accounted",
                        subject=task_id,
                        detail=(
                            f"{on_disk} bytes of Task data are on disk but nothing is charged "
                            "to the subject"
                        ),
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
    owned_paths: Callable[[str], int | None] | None = None,
    now: float | None = None,
) -> rloan.ReconciliationReport:
    """Run one bounded reconciliation pass.  Safe to repeat.

    ``settle_allocations`` is the worker-side scheduler-evidence step (the
    ``scontrol`` recovery); it is optional so this pass is still meaningful on a
    host with no scheduler, and it is never allowed to charge an ambiguous
    allocation.  ``owned_paths`` is the storage-layout measurement the
    filesystem-vs-accounting drift checks need; without it those checks are
    skipped rather than guessed.
    """
    timestamp = time.time() if now is None else now
    settled = review = active = 0
    if settle_allocations is not None:
        outcome = settle_allocations() or {}
        settled = int(outcome.get("settled", 0))
        review = int(outcome.get("review", 0))
        active = int(outcome.get("active", 0))
    expired = task_store.expire_stale_reservations(now=timestamp)
    report = rloan.ReconciliationReport(
        settled_allocations=settled,
        review_allocations=review,
        active_allocations=active,
        expired_reservations=expired,
        drift=tuple(detect_drift(task_store, now=timestamp, owned_paths=owned_paths)),
    )
    _emit(
        "resource.reconciliation.completed",
        settled_allocations=report.settled_allocations,
        review_allocations=report.review_allocations,
        active_allocations=report.active_allocations,
        expired_reservations=report.expired_reservations,
        drift_records=len(report.drift),
    )
    return report
