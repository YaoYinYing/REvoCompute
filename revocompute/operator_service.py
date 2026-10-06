# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Admin operator service: one server-side surface over the control core.

The Web layer never reaches into the readiness evaluator, the executor, or the
job store directly.  It calls this service, which is the single place where a
request becomes an evaluated readiness row, a plan, a durable Operator Job, and
finally a typed host operation.  Keeping the sequence here — rather than in a
route handler — is what makes the Admin API and the CLI agree about a family's
state, and what makes stale-plan rejection and lease conflicts impossible to
bypass from the Web.

A *read* action runs inline: it holds no lease, changes no evidence, and
recording every status refresh as a job would bury the history that matters.  A
*mutation* action becomes a durable Operator Job and is dispatched off the
request, so a SIF build or live validation never holds an HTTP request open; the
Admin UI polls the job instead.

Execution is deliberately narrow.  A plan whose effective actions the host
boundary cannot run is refused, not approximated, and when the host controller
is unavailable the service fails closed while still serving readiness, capacity,
access, and history.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from revocompute.operator_actions import (
    ActionTier,
    get_action,
    lease_key,
    normalize_parameters,
)
from revocompute.operator_executor import (
    ExecutorUnavailable,
    UnsupportedOperation,
    availability,
    execute,
)
from revocompute.operator_jobs import (
    OperatorJobStatus,
    OperatorJobStore,
)
from revocompute.operator_plan import (
    OperatorPlan,
    StalePlanError,
    build_plan,
    verify_plan,
)
from revocompute.runner_admin_view import fleet_view
from revocompute.runner_host import HostPaths
from revocompute.runner_readiness import RunnerReadiness, evaluate_runner_readiness

#: Effective plan operations that map to a typed operator action the host
#: boundary can actually run.  An effective action absent here is refused.
_EFFECT_TO_ACTION = {
    "inspect": "runner.status",
    "live_test": "runner.live_test",
}


class OperatorServiceError(ValueError):
    """A rejected service operation; the message is operator-facing."""


class OperatorNotFound(OperatorServiceError):
    """The named family or job does not exist."""


def lease_key_for(runner_family: str) -> str:
    return f"runner/{runner_family}"


def _default_scheduler(work: Callable[[], None]) -> None:
    """Dispatch a bounded operation off the request thread."""
    threading.Thread(target=work, name="operator-job", daemon=True).start()


@dataclass(frozen=True, slots=True)
class SubmitOutcome:
    job: dict[str, Any]
    created: bool
    plan: OperatorPlan


class OperatorService:
    """Evaluate readiness, plan, and run bounded operator actions for the Admin Web."""

    def __init__(
        self,
        host: HostPaths,
        *,
        store: OperatorJobStore | None = None,
        database: Any = None,
        scheduler: Callable[[Callable[[], None]], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.host = host
        self.database = database
        self._clock = clock
        self._schedule = scheduler or _default_scheduler
        self.store = store or OperatorJobStore(os.path.join(host.server_dir(), "operator-jobs.sqlite"))

    # -- reads ---------------------------------------------------------------

    def readiness(self, runner_family: str) -> RunnerReadiness:
        """One family's derived readiness, or a fail-closed NOT_CONFIGURED row."""
        return evaluate_runner_readiness(self.host, runner_family)

    def executor_availability(self) -> dict[str, Any]:
        state = availability(self.host)
        return {"available": state.available, "reason": state.reason}

    def fleet(self, user_id: int | None) -> dict[str, Any]:
        """Every enabled family's readiness, capacity, access, and in-flight job."""
        rows = fleet_view(self.host, database=self.database, user_id=user_id)
        for row in rows:
            active = self.store.active_exclusive(lease_key_for(row["runner_family"]))
            row["in_flight"] = _job_summary(active) if active else None
        return {"runners": rows, "executor": self.executor_availability()}

    def detail(self, runner_family: str, user_id: int | None) -> dict[str, Any]:
        """One family's evidence, its in-flight job, and the actions it permits."""
        rows = [
            row
            for row in fleet_view(self.host, database=self.database, user_id=user_id)
            if row["runner_family"] == runner_family
        ]
        if not rows:
            raise OperatorNotFound("Unknown or disabled Runner family")
        row = rows[0]
        active = self.store.active_exclusive(lease_key_for(runner_family))
        row["in_flight"] = _job_summary(active) if active else None
        row["actions"] = self.available_actions(runner_family)
        return row

    def available_actions(self, runner_family: str) -> list[dict[str, Any]]:
        """The typed actions this family's current state permits, each with its plan.

        A state-aware list, so the UI offers "Validate now" for a stale
        validation and prepare/build/promote for a stale build instead of a
        generic button that would be rejected on submit.
        """
        from revocompute.operator_actions import list_actions

        offered: list[dict[str, Any]] = []
        for action in list_actions():
            schema = action.schema()
            try:
                plan = self.plan(action.id, runner_family)
            except OperatorServiceError:
                continue
            except ValueError:
                schema["available"] = False
                schema["unavailable_reason"] = "no_safe_plan_for_current_state"
                offered.append(schema)
                continue
            schema["available"] = True
            schema["plan"] = plan.as_dict()
            offered.append(schema)
        return offered

    def plan(
        self,
        action_id: str,
        runner_family: str,
        *,
        parameters: Mapping[str, Any] | None = None,
    ) -> OperatorPlan:
        """Produce the deterministic plan for one action against current evidence."""
        readiness = self.readiness(runner_family)
        return build_plan(
            action_id, runner_family=runner_family, readiness=readiness, parameters=dict(parameters or {})
        )

    def jobs(
        self,
        *,
        runner_family: str | None = None,
        actor_user_id: int | None = None,
        statuses: tuple[OperatorJobStatus, ...] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return [
            _job_view(row)
            for row in self.store.list_jobs(
                runner_family=runner_family, actor_user_id=actor_user_id, statuses=statuses, limit=limit
            )
        ]

    def history(self, runner_family: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Append-only operational history for one family, newest first."""
        return self.jobs(runner_family=runner_family, limit=limit)

    def job(self, job_id: str) -> dict[str, Any]:
        row = self.store.get(job_id)
        if row is None:
            raise OperatorNotFound("Unknown operator job")
        return _job_view(row)

    def reconcile(self) -> list[str]:
        """Terminalize jobs orphaned by a server/executor restart.  Never retries."""
        return self.store.reconcile_orphans()

    # -- writes --------------------------------------------------------------

    def submit(
        self,
        action_id: str,
        runner_family: str,
        *,
        plan_digest: str,
        actor_user_id: int,
        actor_username: str,
        parameters: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> SubmitOutcome:
        """Revalidate the plan, reserve a lease, and run the typed operation.

        A read action runs inline and returns its outcome with no job.  A
        mutation reserves a durable Operator Job first, then dispatches it off
        the request, so the caller gets the job identity immediately.
        """
        action = get_action(action_id)
        normalized = normalize_parameters(action, {**(parameters or {}), "runner_family": runner_family})
        readiness = self.readiness(runner_family)
        plan = build_plan(action_id, runner_family=runner_family, readiness=readiness, parameters=normalized)
        if plan.plan_digest != plan_digest:
            # The page was planned against evidence that has since moved.
            raise StalePlanError("State changed; review the new plan")
        verify_plan(plan, readiness)
        self._require_executable(plan)

        if action.tier is ActionTier.READ:
            result = execute(
                self.host, action_id=_EFFECT_TO_ACTION[plan.effective_actions[0]], runner_family=runner_family,
                parameters=normalized,
            )
            return SubmitOutcome(job=_inline_outcome(plan, result), created=False, plan=plan)

        if not availability(self.host).available:
            raise ExecutorUnavailable("Operator executor unavailable")
        record, created = self.store.create(
            action=action.id,
            runner_family=runner_family,
            actor_user_id=actor_user_id,
            actor_username=actor_username,
            tier=action.tier.value,
            lease_scope=lease_key(action, normalized),
            requested_intent=action.id,
            plan_digest=plan.plan_digest,
            evidence_digest=plan.evidence_digest,
            parameters=normalized,
            idempotency_key=idempotency_key,
        )
        if not created:
            return SubmitOutcome(job=self.job(record["job_id"]), created=False, plan=plan)
        job_id = record["job_id"]
        self._schedule(lambda: self.run_reserved_job(job_id, plan, normalized, readiness))
        return SubmitOutcome(job=self.job(job_id), created=True, plan=plan)

    def run_reserved_job(
        self,
        job_id: str,
        plan: OperatorPlan,
        parameters: Mapping[str, Any],
        before: RunnerReadiness,
    ) -> None:
        """Advance a reserved job through the bounded host operations it planned.

        Safe to run off-request; on a server or executor restart the record stays
        RUNNING and is terminalized by :meth:`reconcile` rather than re-executed.
        """
        if not self.store.transition(
            job_id, expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING
        ):
            return
        effects: list[str] = []
        for stage in plan.effective_actions:
            action_id = _EFFECT_TO_ACTION[stage]
            try:
                result = execute(self.host, action_id=action_id, runner_family=plan.runner_family, parameters=parameters)
            except ExecutorUnavailable as exc:
                self._finish(job_id, OperatorJobStatus.FAILED, effects, plan, before, "executor_unavailable", str(exc))
                return
            except UnsupportedOperation as exc:
                self._finish(job_id, OperatorJobStatus.FAILED, effects, plan, before, "executor_failure", str(exc))
                return
            effects.append(stage)
            self.store.record_progress(job_id, stage=stage, log_text=result.log_text)
            if not result.succeeded:
                self._finish(job_id, OperatorJobStatus.FAILED, effects, plan, before, "operation_failed", result.log_text)
                return
        self._finish(job_id, OperatorJobStatus.SUCCEEDED, effects, plan, before, None, None)

    def _finish(
        self,
        job_id: str,
        status: OperatorJobStatus,
        effects: list[str],
        plan: OperatorPlan,
        before: RunnerReadiness,
        failure_category: str | None,
        log_text: str | None,
    ) -> None:
        """Record the terminal state with a before/after snapshot and effective actions.

        The record keeps ``requested_intent`` beside ``effective_actions`` and a
        before snapshot, so history can answer "why is this not READY now" and
        "what did the operator actually run" without re-deriving them.
        """
        after = self.readiness(plan.runner_family)
        self.store.transition(
            job_id,
            expected=(OperatorJobStatus.RUNNING,),
            new_status=status,
            failure_category=failure_category,
            result={"status": after.status.value, "reason_code": after.reason_code},
            effect=_effect_record(plan, effects, before, after),
            log_text=log_text,
        )

    def _require_executable(self, plan: OperatorPlan) -> None:
        unsupported = [name for name in plan.effective_actions if name not in _EFFECT_TO_ACTION]
        if unsupported:
            raise UnsupportedOperation(
                f"This deployment cannot run {', '.join(unsupported)} from the Admin interface yet"
            )

    def cancel(self, job_id: str, *, actor_user_id: int) -> dict[str, Any]:
        """Request cancellation of a job the caller owns."""
        row = self.store.get(job_id)
        if row is None:
            raise OperatorNotFound("Unknown operator job")
        if int(row["actor_user_id"]) != int(actor_user_id):
            raise OperatorServiceError("Only the requesting operator may cancel this job")
        if not self.store.request_cancel(job_id):
            raise OperatorServiceError("This job is no longer cancellable")
        return self.job(job_id)


def _inline_outcome(plan: OperatorPlan, result: Any) -> dict[str, Any]:
    """A job-shaped result for a read action that ran without a durable record."""
    return {
        "job_id": None,
        "action": plan.action_id,
        "runner_family": plan.runner_family,
        "status": OperatorJobStatus.SUCCEEDED.value if result.succeeded else OperatorJobStatus.FAILED.value,
        "stage": None,
        "tier": plan.tier,
        "lease_scope": plan.lease_scope,
        "requested_intent": plan.requested_intent,
        "plan_digest": plan.plan_digest,
        "evidence_digest": plan.evidence_digest,
        "failure_category": None if result.succeeded else "operation_failed",
        "created_at": plan.evaluated_at,
        "started_at": plan.evaluated_at,
        "finished_at": plan.evaluated_at,
        "result": None,
        "effect": {"requested_intent": plan.requested_intent, "effective_actions": list(plan.effective_actions)},
        "log_text": result.log_text,
        "cancellable": False,
    }


def _effect_record(
    plan: OperatorPlan, effects: list[str], before: RunnerReadiness, after: RunnerReadiness
) -> dict[str, Any]:
    """Requested intent versus effective actions, with before/after snapshots.

    Audit history must show both what the operator asked for and what the
    control core actually executed, so a repair that ran only a live test is not
    collapsed into "repair succeeded".
    """
    return {
        "requested_intent": plan.requested_intent,
        "effective_actions": list(effects),
        "planned_actions": list(plan.effective_actions),
        "before": {"status": before.status.value, "reason_code": before.reason_code},
        "after": {"status": after.status.value, "reason_code": after.reason_code},
        "lease_scope": plan.lease_scope,
    }


def _job_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "job_id": row["job_id"],
        "action": row["action"],
        "status": row["status"],
        "stage": row.get("stage"),
        "actor": row["actor_username"],
        "created_at": row["created_at"],
    }


def _job_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """A bounded Admin view of one job: no host paths, no raw environment."""
    return {
        "job_id": row["job_id"],
        "action": row["action"],
        "runner_family": row["runner_family"],
        "actor_user_id": row["actor_user_id"],
        "actor_username": row["actor_username"],
        "tier": row["tier"],
        "lease_scope": row["lease_scope"],
        "status": row["status"],
        "stage": row.get("stage"),
        "requested_intent": row["requested_intent"],
        "plan_digest": row["plan_digest"],
        "evidence_digest": row["evidence_digest"],
        "failure_category": row.get("failure_category"),
        "created_at": row["created_at"],
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "result": _load_json(row.get("result_json")),
        "effect": _load_json(row.get("effect_json")),
        "log_text": row.get("log_text"),
        "cancellable": row["status"] in (OperatorJobStatus.QUEUED.value, OperatorJobStatus.RUNNING.value),
    }


def _load_json(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def build_operator_service(host: HostPaths, *, database: Any = None) -> OperatorService:
    """Build the Web process's operator service from its resolved host view."""
    return OperatorService(host, database=database)


__all__ = [
    "OperatorNotFound",
    "OperatorService",
    "OperatorServiceError",
    "SubmitOutcome",
    "build_operator_service",
    "lease_key_for",
]
