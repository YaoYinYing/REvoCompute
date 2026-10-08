# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The dispatch seam between a persisted placement plan and Slurm submission.

:mod:`revocompute.placement_policy` decides *what* a stage should request.
This module is the only place that couples that decision to *asking the
scheduler for it*, and it exists so the coupling is idempotent.

One rule carries the whole design:

    the request a stage dispatches is the request its persisted plan recorded.

Not "a request recomputed from the same inputs" — a stage that already has a
planned or submitted record dispatches *that* plan, byte for byte.  A policy
edit, a restart, or a retried dispatch therefore cannot change what the
scheduler is asked for, and cannot produce a second request for a stage whose
first one may already exist.

A dry run and a real dispatch consume the same code path up to that record, so
``explain`` cannot describe a decision dispatch would not make.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from revocompute.operational_events import emit_event
from revocompute.placement_policy import (
    PLACEMENT_ALREADY_SUBMITTED,
    PLACEMENT_SUBMISSION_UNRESOLVED,
    PLAN_STATE_SUBMITTED,
    PlacementDispatchRefused,
    PlacementPlan,
    PlacementPolicy,
    WorkloadRequirement,
    build_placement_plan,
    resolve_placement,
)
from revocompute.resource_policy import ResolvedResources

#: Re-exported under the dispatch seam's own names: these are the bounded
#: reasons a *submission* is refused, and callers that handle dispatch outcomes
#: name them from here rather than from the resolution vocabulary.
DISPATCH_ALREADY_SUBMITTED = PLACEMENT_ALREADY_SUBMITTED
DISPATCH_SUBMISSION_UNRESOLVED = PLACEMENT_SUBMISSION_UNRESOLVED


@dataclass(frozen=True, slots=True)
class StageDispatch:
    """The plan a dispatch will use, and whether it was newly resolved."""

    plan: PlacementPlan
    plan_id: int
    reused: bool

    @property
    def resolved(self) -> ResolvedResources:
        return self.plan.resolved

    @property
    def plan_digest(self) -> str:
        return self.plan.plan_digest


def plan_stage_for_dispatch(
    task_store: Any,
    *,
    task_id: str,
    stage_id: str,
    requirement: WorkloadRequirement,
    resolved: ResolvedResources,
    policy: PlacementPolicy | None,
    allowed_queues: Sequence[str] = (),
    at: float | None = None,
) -> StageDispatch:
    """Produce (or reuse) the one plan this stage will dispatch.

    Three outcomes, and no fourth:

    * a live plan exists — ``planned`` or ``submitted`` — and is reused.  A
      ``submitted`` plan is historical fact: its stage is not dispatched again.
      A ``planned`` plan whose submission was started but never recorded is an
      ambiguous outcome, and the caller is told to stop rather than to guess;
    * no live plan exists, so one is resolved and persisted now.

    Reuse is what makes policy changes affect future planning only, and what
    makes "the dry run and the dispatch agree" a property rather than a hope.
    """
    timestamp = time.time() if at is None else at
    live = task_store.get_live_placement_plan(task_id, stage_id)
    if live is not None:
        plan = PlacementPlan.from_record(live)
        if plan.state == PLAN_STATE_SUBMITTED:
            emit_event(
                "resource.placement.refused",
                level="WARNING",
                reason_code=DISPATCH_ALREADY_SUBMITTED,
                task_id=task_id,
                stage_id=stage_id,
                slurm_job_id=plan.slurm_job_id,
            )
            raise PlacementDispatchRefused(
                f"Stage {stage_id!r} already has a submitted placement plan "
                f"(Slurm job {plan.slurm_job_id}); a submitted request is never replanned or resubmitted",
                reason_code=DISPATCH_ALREADY_SUBMITTED,
            )
        if plan.submission_unresolved:
            emit_event(
                "resource.placement.refused",
                level="ERROR",
                reason_code=DISPATCH_SUBMISSION_UNRESOLVED,
                task_id=task_id,
                stage_id=stage_id,
            )
            raise PlacementDispatchRefused(
                f"Stage {stage_id!r} has an unresolved Slurm submission: a request may already exist "
                "and its outcome was never recorded. Resolve it with the scheduler before retrying.",
                reason_code=DISPATCH_SUBMISSION_UNRESOLVED,
            )
        return StageDispatch(plan=plan, plan_id=int(live["id"]), reused=True)

    decision = resolve_placement(requirement, resolved, policy, allowed_queues=allowed_queues)
    plan = build_placement_plan(
        decision, task_id=task_id, stage_id=stage_id, created_at=timestamp
    )
    stored = task_store.record_placement_plan(record=plan.to_record(), at=timestamp)
    emit_event(
        "resource.placement.planned",
        task_id=task_id,
        stage_id=stage_id,
        reason_code=plan.reason_code,
    )
    return StageDispatch(plan=PlacementPlan.from_record(stored), plan_id=int(stored["id"]), reused=False)


def begin_stage_submission(task_store: Any, dispatch: StageDispatch, *, at: float | None = None) -> None:
    """Record that this worker is about to ask the scheduler.

    Written before ``srun`` is launched, so the one window no transition can
    close — the process died between launching a request and recording its
    answer — is at least *readable* afterwards.  Best effort: a store failure
    here must not stop a dispatch whose plan is already durable.
    """
    try:
        task_store.mark_placement_plan_submission_started(dispatch.plan_id, at=at)
    except Exception:  # pragma: no cover - defence in depth; the plan is durable already
        import logging

        logging.exception("Could not record placement submission start for plan %s", dispatch.plan_id)


def confirm_stage_submitted(
    task_store: Any, dispatch: StageDispatch, *, slurm_job_id: str, at: float | None = None
) -> None:
    """Record that the scheduler owns this plan's request.

    The plan's ``planned -> submitted`` transition is the durable fact that a
    later dispatch of the same stage must not ask again.  It is best effort
    against the *task* outcome: the plan row is explanatory, while the
    allocation itself is recorded by the accounting path, so a store failure
    here must not fail a job the scheduler is running.
    """
    try:
        task_store.mark_placement_plan_submitted(dispatch.plan_id, slurm_job_id=str(slurm_job_id), at=at)
    except Exception:
        import logging

        logging.exception("Could not record placement submission for plan %s", dispatch.plan_id)


def abandon_stage_submission(task_store: Any, dispatch: StageDispatch) -> None:
    """Clear the submission stamp for a dispatch that provably never asked.

    Called only when the adapter reports that no scheduler process was ever
    started, so the plan returns to dispatchable rather than leaving the stage
    permanently blocked on an attempt that could not have created a job.  A
    raised dispatch that *did* reach the scheduler keeps its stamp, and the
    stage is resolved by an operator.
    """
    try:
        task_store.clear_placement_plan_submission(dispatch.plan_id)
    except Exception:  # pragma: no cover
        import logging

        logging.exception("Could not clear placement submission stamp for plan %s", dispatch.plan_id)


def stage_plan_record(task_store: Any, *, task_id: str, stage_id: str) -> Mapping[str, Any] | None:
    """The latest recorded plan for one stage, as stored.  Read-only."""
    return task_store.get_placement_plan(task_id, stage_id)


__all__ = [
    "DISPATCH_ALREADY_SUBMITTED",
    "DISPATCH_SUBMISSION_UNRESOLVED",
    "PlacementDispatchRefused",
    "StageDispatch",
    "abandon_stage_submission",
    "begin_stage_submission",
    "confirm_stage_submitted",
    "plan_stage_for_dispatch",
    "stage_plan_record",
]
