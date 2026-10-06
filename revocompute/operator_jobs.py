# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Operator Jobs: the durable lifecycle of a Web-triggered Runner action.

A long-running administrative action (a SIF build, a live validation) must not
hold an HTTP request open, and it is not a scientific Task — storing it as one
would give it scientific meaning it must never carry.  An Operator Job is its own
bounded record with an explicit lifecycle, durable enough that a server restart
neither loses a completed action nor silently re-runs an irreversible one.

The store also owns the two concurrency controls the control plane needs:
one exclusive lease per Runner family (so two builds cannot race), and an
idempotency key per request (so a retried click cannot duplicate a mutation).
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

import sqlalchemy as sa

from revocompute.operator_jobs_schema import operator_jobs_table

OPERATOR_JOB_ID_PATTERN = r"opjob_[A-Za-z0-9_-]{32}"


class OperatorJobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = frozenset(
    {OperatorJobStatus.SUCCEEDED, OperatorJobStatus.FAILED, OperatorJobStatus.CANCELLED}
)
#: The only transitions a job may make.  An impossible regression (a terminal
#: job returning to RUNNING, a queued job jumping to SUCCEEDED) is refused.
ALLOWED_TRANSITIONS: Mapping[OperatorJobStatus, frozenset[OperatorJobStatus]] = {
    OperatorJobStatus.QUEUED: frozenset({OperatorJobStatus.RUNNING, OperatorJobStatus.CANCELLED}),
    OperatorJobStatus.RUNNING: frozenset(
        {
            OperatorJobStatus.SUCCEEDED,
            OperatorJobStatus.FAILED,
            OperatorJobStatus.CANCELLING,
        }
    ),
    OperatorJobStatus.CANCELLING: frozenset({OperatorJobStatus.CANCELLED, OperatorJobStatus.FAILED}),
    OperatorJobStatus.SUCCEEDED: frozenset(),
    OperatorJobStatus.FAILED: frozenset(),
    OperatorJobStatus.CANCELLED: frozenset(),
}

#: Failure categories a job may record.  Closed so history stays queryable.
FAILURE_CATEGORIES = frozenset(
    {
        "executor_unavailable",
        "executor_failure",
        "operation_failed",
        "cancelled",
        "timeout",
        "stale_evidence",
        "orphaned_executor_restart",
        "conflicting_operation",
    }
)


class OperatorJobError(ValueError):
    """A rejected Operator Job operation; the message is operator-facing."""


class OperatorConflictError(OperatorJobError):
    """Another exclusive operation holds the family lease."""


def new_job_id() -> str:
    return f"opjob_{secrets.token_urlsafe(24)}"


@dataclass(frozen=True, slots=True)
class JobLease:
    """The exclusive operation scope a job holds while it runs."""

    scope: str
    job_id: str


class OperatorJobStore:
    """Durable Operator Job records, leases, and idempotency.

    Kept separate from the Task tables on purpose: an Operator Job is an
    administrative action, and (de)serializing it as a Task would expose it
    through scientific surfaces it does not belong to.
    """

    def __init__(self, path: str, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self.path = path
        self.engine = sa.create_engine(
            f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False, "timeout": 30}
        )
        self.metadata = sa.MetaData()
        self.table = operator_jobs_table(self.metadata)
        with self.engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA busy_timeout=30000")
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            self.metadata.create_all(conn, checkfirst=True)

    # -- reads ---------------------------------------------------------------

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(sa.select(self.table).where(self.table.c.job_id == job_id)).mappings().first()
        return dict(row) if row is not None else None

    def list_jobs(
        self,
        *,
        limit: int = 50,
        runner_family: str | None = None,
        actor_user_id: int | None = None,
        statuses: tuple[OperatorJobStatus, ...] | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        query = sa.select(self.table).order_by(self.table.c.created_at.desc()).limit(limit)
        if runner_family is not None:
            query = query.where(self.table.c.runner_family == runner_family)
        if actor_user_id is not None:
            query = query.where(self.table.c.actor_user_id == actor_user_id)
        if statuses:
            query = query.where(self.table.c.status.in_([item.value for item in statuses]))
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(query).mappings()]

    def active_exclusive(self, scope: str) -> dict[str, Any] | None:
        """The job currently holding an exclusive lease on ``scope``, if any."""
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    sa.select(self.table)
                    .where(
                        self.table.c.lease_scope == scope,
                        self.table.c.status.in_(
                            [
                                OperatorJobStatus.QUEUED.value,
                                OperatorJobStatus.RUNNING.value,
                                OperatorJobStatus.CANCELLING.value,
                            ]
                        ),
                    )
                    .order_by(self.table.c.created_at.asc())
                )
                .mappings()
                .first()
            )
        return dict(row) if row is not None else None

    # -- writes --------------------------------------------------------------

    def create(
        self,
        *,
        action: str,
        runner_family: str,
        actor_user_id: int,
        actor_username: str,
        tier: str,
        lease_scope: str,
        requested_intent: str,
        plan_digest: str,
        evidence_digest: str,
        parameters: Mapping[str, Any],
        idempotency_key: str | None,
        queue_limit: int = 64,
    ) -> tuple[dict[str, Any], bool]:
        """Reserve a job.  Returns ``(record, created)``.

        A repeated request with the same idempotency key and identical body
        returns the existing job (``created=False``); the same key with a
        different body is rejected.  An exclusive scope with a live holder is
        rejected rather than queued behind it, so a conflicting mutation cannot
        start.
        """
        if queue_limit < 1:
            raise OperatorJobError("Operator queue limit must be positive")
        body = json.dumps({"action": action, "runner_family": runner_family, "parameters": dict(parameters)}, sort_keys=True)
        now = self._clock()
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                if idempotency_key:
                    existing = (
                        conn.execute(
                            sa.select(self.table).where(
                                self.table.c.actor_user_id == actor_user_id,
                                self.table.c.idempotency_key == idempotency_key,
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if existing is not None:
                        if existing["requested_intent"] != requested_intent:
                            raise OperatorJobError("Idempotency key reused with a different request")
                        conn.commit()
                        return dict(existing), False
                active = conn.execute(
                    sa.select(sa.func.count())
                    .select_from(self.table)
                    .where(
                        self.table.c.status.in_(
                            [
                                OperatorJobStatus.QUEUED.value,
                                OperatorJobStatus.RUNNING.value,
                                OperatorJobStatus.CANCELLING.value,
                            ]
                        )
                    )
                ).scalar_one()
                if active >= queue_limit:
                    raise OperatorJobError("Operator queue is full; retry after an in-flight job finishes")
                if lease_scope != "read-only":
                    holder = (
                        conn.execute(
                            sa.select(self.table).where(
                                self.table.c.lease_scope == lease_scope,
                                self.table.c.status.in_(
                                    [
                                        OperatorJobStatus.QUEUED.value,
                                        OperatorJobStatus.RUNNING.value,
                                        OperatorJobStatus.CANCELLING.value,
                                    ]
                                ),
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if holder is not None:
                        raise OperatorConflictError(
                            f"Another operator job is already running for {runner_family}"
                        )
                job_id = new_job_id()
                conn.execute(
                    sa.insert(self.table).values(
                        job_id=job_id,
                        action=action,
                        runner_family=runner_family,
                        actor_user_id=actor_user_id,
                        actor_username=actor_username,
                        tier=tier,
                        lease_scope=lease_scope,
                        status=OperatorJobStatus.QUEUED.value,
                        requested_intent=requested_intent,
                        plan_digest=plan_digest,
                        evidence_digest=evidence_digest,
                        parameter_json=body,
                        idempotency_key=idempotency_key,
                        created_at=now,
                    )
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        record = self.get(job_id)
        assert record is not None
        return record, True

    def transition(
        self,
        job_id: str,
        *,
        expected: tuple[OperatorJobStatus, ...],
        new_status: OperatorJobStatus,
        stage: str | None = None,
        result: Mapping[str, Any] | None = None,
        effect: Mapping[str, Any] | None = None,
        failure_category: str | None = None,
        log_text: str | None = None,
    ) -> bool:
        """Compare-and-set a job's status.  Returns False when the job was not in an expected state.

        A concurrent transition therefore loses cleanly instead of corrupting the
        record, and an illegal transition is refused by the same check.
        """
        if failure_category is not None and failure_category not in FAILURE_CATEGORIES:
            raise OperatorJobError(f"Unknown failure category: {failure_category!r}")
        for source in expected:
            if new_status not in ALLOWED_TRANSITIONS[source]:
                raise OperatorJobError(f"Illegal operator transition {source.value} -> {new_status.value}")
        values: dict[str, Any] = {"status": new_status.value}
        if stage is not None:
            values["stage"] = stage
        if result is not None:
            values["result_json"] = json.dumps(result, sort_keys=True)
        if effect is not None:
            values["effect_json"] = json.dumps(effect, sort_keys=True)
        if failure_category is not None:
            values["failure_category"] = failure_category
        if log_text is not None:
            values["log_text"] = _bound_log(log_text)
        now = self._clock()
        if new_status is OperatorJobStatus.RUNNING:
            values["started_at"] = now
        if new_status in TERMINAL_STATUSES:
            values["finished_at"] = now
        with self.engine.begin() as conn:
            result_row = conn.execute(
                sa.update(self.table)
                .where(self.table.c.job_id == job_id, self.table.c.status.in_([item.value for item in expected]))
                .values(**values)
            )
        return result_row.rowcount == 1

    def request_cancel(self, job_id: str) -> bool:
        """Move a live job toward cancellation; only its own scope is affected."""
        record = self.get(job_id)
        if record is None:
            return False
        status = OperatorJobStatus(record["status"])
        if status is OperatorJobStatus.QUEUED:
            return self.transition(
                job_id,
                expected=(OperatorJobStatus.QUEUED,),
                new_status=OperatorJobStatus.CANCELLED,
                failure_category="cancelled",
            )
        if status is OperatorJobStatus.RUNNING:
            return self.transition(
                job_id, expected=(OperatorJobStatus.RUNNING,), new_status=OperatorJobStatus.CANCELLING
            )
        return False

    def reconcile_orphans(self) -> list[str]:
        """Terminalize jobs left RUNNING/CANCELLING by a server or executor restart.

        They are never restarted automatically: an irreversible operation must
        not be repeated without proof the earlier attempt had no effect.  The
        record keeps an explicit failure category so an administrator sees why,
        and recovery is a new job against a fresh plan.
        """
        reconciled: list[str] = []
        for status in (OperatorJobStatus.RUNNING, OperatorJobStatus.CANCELLING):
            with self.engine.connect() as conn:
                ids = [
                    row["job_id"]
                    for row in conn.execute(
                        sa.select(self.table.c.job_id).where(self.table.c.status == status.value)
                    ).mappings()
                ]
            for job_id in ids:
                if self.transition(
                    job_id,
                    expected=(status,),
                    new_status=OperatorJobStatus.FAILED,
                    failure_category="orphaned_executor_restart",
                    log_text="Reconciled after server/executor restart; no automatic retry.",
                ):
                    reconciled.append(job_id)
        return reconciled


def _bound_log(text: str, limit: int = 16384) -> str:
    """Bound and normalize an operator log before it is stored."""
    from revocompute.serialization import sanitized_mapping

    cleaned = sanitized_mapping(text) if isinstance(text, str) else str(text)
    return cleaned[:limit]


__all__ = [
    "ALLOWED_TRANSITIONS",
    "FAILURE_CATEGORIES",
    "JobLease",
    "OperatorConflictError",
    "OperatorJobError",
    "OperatorJobStatus",
    "OperatorJobStore",
    "TERMINAL_STATUSES",
    "new_job_id",
]
