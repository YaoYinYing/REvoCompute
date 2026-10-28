# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Durable execution-stage vocabulary shared by Core, the store, and the API.

A StageRun is one allocation attempt of one manifest stage.  Attempt identity is
enforced by unique indexes; status transitions are accepted only when a guarded
UPDATE's predicate names a legal predecessor, so a late stdout marker or a stale
worker callback cannot regress an attempt that has already completed or been
cancelled.  stdout remains progress detail only.
"""

from __future__ import annotations

from typing import Any

from revocompute.execution_diagnostics import REASONS

NOT_STARTED = "NOT_STARTED"
QUEUED = "QUEUED"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
INTERRUPTED = "INTERRUPTED"

#: ``NOT_STARTED`` is what the API reports for a declared stage with no record;
#: every stored attempt opens directly in ``QUEUED``.
STATUSES = (NOT_STARTED, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED, INTERRUPTED)

ACTIVE_STATUSES = frozenset({QUEUED, RUNNING})
TERMINAL_STATUSES = frozenset({COMPLETED, FAILED, CANCELLED, INTERRUPTED})

TRANSITIONS: dict[str, frozenset[str]] = {
    NOT_STARTED: frozenset({QUEUED, CANCELLED}),
    # COMPLETED from QUEUED covers an allocation whose start observation was
    # missed (a very short run, or a backend that returns its outcome directly).
    # The completed outcome is stronger evidence than the absent start line.
    QUEUED: frozenset({RUNNING, COMPLETED, FAILED, CANCELLED, INTERRUPTED}),
    RUNNING: frozenset({COMPLETED, FAILED, CANCELLED, INTERRUPTED}),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
    INTERRUPTED: frozenset(),
}


def predecessors(status: str) -> frozenset[str]:
    """Every status that may legally move to ``status``."""
    if status not in STATUSES:
        raise ValueError(f"Unknown stage status {status!r}")
    return frozenset(source for source, targets in TRANSITIONS.items() if status in targets)


def active_status_predicate() -> str:
    """The SQL predicate for a live attempt, derived from ``ACTIVE_STATUSES``."""
    return "status IN (" + ", ".join(f"'{status}'" for status in sorted(ACTIVE_STATUSES)) + ")"


class Reason:
    """Lifecycle reasons Core adds beside the bounded diagnostics vocabulary."""

    COMPLETED = "completed"
    TASK_CANCELLED = "task_cancelled"
    WORKER_LOST = "worker_lost"
    TASK_DELETED = "task_deleted"


#: A terminal StageRun's reason is one of the diagnostics reasons or a Core
#: lifecycle reason.  Anything else is recorded as a generic allocation failure
#: rather than letting an unbounded string reach the API.
BOUNDED_REASON_CODES = frozenset(REASONS) | frozenset(
    {Reason.COMPLETED, Reason.TASK_CANCELLED, Reason.WORKER_LOST, Reason.TASK_DELETED}
)


def bounded_reason(value: Any, default: str = "allocation_failed") -> str:
    text = str(value or "")
    return text if text in BOUNDED_REASON_CODES else default


def planned_resources(resource_policy: Any) -> dict[str, Any] | None:
    """The request an attempt was dispatched with, or ``None`` when unknown."""
    if resource_policy is None:
        return None
    public_dict = getattr(resource_policy, "public_dict", None)
    if callable(public_dict):
        return public_dict()
    return None


def workflow_state_projection(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Project StageRun records into the historical ``workflow_state`` shape.

    The newest attempt of each stage wins.  This is the compatibility view
    written at Core boundaries for consumers that predate StageRun records; it
    is derived from the records and never read as their authority.
    """
    latest: dict[str, dict[str, Any]] = {}
    for run in sorted(runs, key=lambda item: (item["stage_index"], item["attempt"])):
        latest[str(run["stage_name"])] = run
    return {
        name: {
            "status": str(run["status"]).lower(),
            "job_id": run.get("slurm_job_id"),
            "started_at": run.get("started_at"),
            "finished_at": run.get("ended_at"),
            "attempt": run.get("attempt"),
            "reason_code": run.get("reason_code"),
        }
        for name, run in sorted(latest.items(), key=lambda item: item[1]["stage_index"])
    }


def workflow_state_mirror(
    runs: list[dict[str, Any]], legacy_state: dict[str, dict[str, Any]] | None
) -> dict[str, dict[str, Any]]:
    """Records projected into the mirror, plus historical entries they omit."""
    mirror = workflow_state_projection(runs)
    recorded = {str(run["stage_name"]) for run in runs}
    for name, step in (legacy_state or {}).items():
        if name not in recorded:
            mirror[name] = step
    return mirror
