# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Durable execution-stage vocabulary shared by Core, the store, and the API.

A StageRun is one allocation attempt of one manifest stage.  Its status is a
database-enforced state machine: the store only accepts legal transitions, so a
late stdout marker or a stale worker callback cannot regress an attempt that has
already completed or been cancelled.  stdout remains progress detail only.
"""

from __future__ import annotations

from typing import Any

NOT_STARTED = "NOT_STARTED"
READY = "READY"
QUEUED = "QUEUED"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
INTERRUPTED = "INTERRUPTED"
SKIPPED = "SKIPPED"

STATUSES = (NOT_STARTED, READY, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED, INTERRUPTED, SKIPPED)

ACTIVE_STATUSES = frozenset({READY, QUEUED, RUNNING})
TERMINAL_STATUSES = frozenset({COMPLETED, FAILED, CANCELLED, INTERRUPTED, SKIPPED})

TRANSITIONS: dict[str, frozenset[str]] = {
    NOT_STARTED: frozenset({READY, QUEUED, SKIPPED, CANCELLED}),
    READY: frozenset({QUEUED, SKIPPED, CANCELLED, FAILED}),
    # COMPLETED from QUEUED covers an allocation whose start observation was
    # missed (a very short run, or a backend that returns its outcome directly).
    # The completed outcome is stronger evidence than the absent start line.
    QUEUED: frozenset({RUNNING, COMPLETED, FAILED, CANCELLED, INTERRUPTED}),
    RUNNING: frozenset({COMPLETED, FAILED, CANCELLED, INTERRUPTED}),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
    INTERRUPTED: frozenset(),
    SKIPPED: frozenset(),
}


def predecessors(status: str) -> frozenset[str]:
    """Every status that may legally move to ``status``."""
    if status not in STATUSES:
        raise ValueError(f"Unknown stage status {status!r}")
    return frozenset(source for source, targets in TRANSITIONS.items() if status in targets)


class Reason:
    """Bounded Core vocabulary for why an attempt reached a terminal state."""

    COMPLETED = "completed"
    ALLOCATION_FAILED = "allocation_failed"
    ADMISSION_FAILED = "admission_failed"
    TASK_CANCELLED = "task_cancelled"
    WORKER_LOST = "worker_lost"
    SUBMISSION_FAILED = "submission_failed"
    PUBLICATION_FAILED = "publication_failed"


def planned_resources(resource_policy: Any) -> dict[str, Any] | None:
    """The request an attempt was dispatched with, or ``None`` when unknown."""
    if resource_policy is None:
        return None
    public_dict = getattr(resource_policy, "public_dict", None)
    if callable(public_dict):
        return public_dict()
    return None
