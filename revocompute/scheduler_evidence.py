# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Where scheduler evidence is produced, and who may ask for it.

``scontrol`` is the only authority for what a Slurm allocation actually did, and
the shipped deployment mounts it — with the Slurm libraries and MUNGE — into the
*worker* and nowhere else.  The maintenance scheduler is a separate process with
no scheduler boundary at all, so a reconciliation that ran there would answer
every question with "the scheduler is unavailable" and leave real allocations
unsettled while reporting, at best, a review it could never resolve itself.

So the question is *dispatched* to the worker over the same broker every other
worker task uses, and this module owns that contract in one place: the task name,
the bounded wait, and the dispatch itself.  The maintenance pass and any
operator-facing caller share it, so there is exactly one spelling of "ask the
worker for scheduler evidence".

Unavailability is reported honestly rather than as a zero.  A dispatch that
cannot reach the worker, or whose answer never arrives, returns the number of
allocations still awaiting evidence: those rows stay unsettled — admission still
sees them — and no scheduler-owned reservation is released, because releasing
one requires the evidence that could not be fetched.  Settlement itself is
idempotent per ``(unit, slurm_job_id)``, so neither a retry nor a pass running
alongside the worker can double-charge.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from celery import Celery

#: The worker-owned reconciliation task, named once.  ``task_runtime`` registers
#: a Celery task under exactly this name.
SCHEDULER_EVIDENCE_TASK = "reconcile_slurm_allocations"

#: Bounded wait for the worker to answer.  The maintenance interval is an
#: operator-chosen cadence, not a scheduler-recovery deadline, so an unavailable
#: or busy worker must never wedge the maintenance loop: the pass reports the
#: allocations as unknown (still unsettled) and retries on its next interval.
SCHEDULER_EVIDENCE_WAIT_SECONDS = 30.0

#: The outcome of a dispatch that could not obtain an answer from the worker.
#: ``review`` is the unknown count — never a fabricated zero — and no reservation
#: is released, because that requires the evidence this dispatch did not get.
UNAVAILABLE_OUTCOME: dict[str, int] = {
    "settled": 0,
    "review": 0,
    "active": 0,
    "reservations_released": 0,
}


def scheduler_evidence_app() -> Celery:
    """A producer bound to this deployment's broker, built without the worker app.

    ``task_runtime`` constructs the worker's Celery application — and discovers
    the whole deployed Runner plugin tree — at import time, which a maintenance
    or web process must not do to ask one question.  The broker and backend come
    from the same environment variables the worker reads, so this producer
    reaches the same queue.
    """
    password = os.environ.get("REDIS_PASSWORD", "")
    auth = f":{password}@" if password else ""
    redis_url = os.environ.get("REDIS_URL", f"redis://{auth}localhost:6379/0")
    return Celery(
        "revocompute-scheduler-evidence",
        broker=os.environ.get("BROKER_URL", redis_url),
        backend=os.environ.get("RESULT_BACKEND", redis_url),
    )


def unavailable_outcome(unsettled: int) -> dict[str, int]:
    """What an unanswered scheduler question reports: unknown, never zero."""
    return {**UNAVAILABLE_OUTCOME, "review": max(0, int(unsettled))}


def dispatch_scheduler_evidence(*, unsettled: int = 0, app: Celery | None = None) -> dict[str, int] | None:
    """Ask the worker to reconcile, returning its result or ``None``.

    ``None`` means the question is unanswered — no broker, no worker, a timeout,
    or an error — which is a different fact from any result the worker could
    return.  ``unsettled`` is the number of allocations awaiting evidence, so a
    caller can report the unknown quantity without re-reading the store.
    Requests expire within the same usefulness window: a busy worker discards
    unanswered old questions when capacity returns instead of executing a
    backlog of stale maintenance work.
    """
    try:
        outcome = (app or scheduler_evidence_app()).send_task(
            SCHEDULER_EVIDENCE_TASK, expires=SCHEDULER_EVIDENCE_WAIT_SECONDS,
        ).get(
            timeout=SCHEDULER_EVIDENCE_WAIT_SECONDS
        )
    except Exception as exc:  # pylint: disable=broad-except
        logging.warning(
            "Scheduler-evidence reconciliation could not reach the worker (%s); "
            "%d unsettled allocation(s) remain unknown this pass",
            exc,
            unsettled,
        )
        return None
    if not isinstance(outcome, dict):
        logging.warning("Worker returned no reconciliation result; allocations remain unknown")
        return None
    return {
        "settled": int(outcome.get("settled", 0)),
        "review": int(outcome.get("review", 0)),
        "active": int(outcome.get("active", 0)),
        "reservations_released": int(outcome.get("reservations_released", 0)),
    }


def fetch_scheduler_evidence(store: Any, *, app: Celery | None = None) -> dict[str, int]:
    """The dispatch, with the unknown case already shaped for reconciliation.

    This is the boundary the maintenance pass calls: it never raises (an
    unreachable worker is a fact to report, not an exception that would abort the
    rest of the pass) and it never reports a settled or released count it did not
    receive.
    """
    unsettled = len(store.list_unsettled_allocations())
    outcome = dispatch_scheduler_evidence(unsettled=unsettled, app=app)
    return unavailable_outcome(unsettled) if outcome is None else outcome
