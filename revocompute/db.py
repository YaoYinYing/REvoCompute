# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""SQLite task tracker for compute jobs."""

from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    desc,
    func,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError

from revocompute.schema_epoch import require_current_schema


DEFAULT_MONTHLY_GPU_SECONDS = 60_000


class GPUCreditUnavailableError(RuntimeError):
    """Raised when a user may not start another GPU allocation."""


class GPUAuthorizationUnavailableError(RuntimeError):
    """Raised when current projected authorization denies a GPU allocation."""


class TaskDatabase:
    """Minimal SQLite-based task tracker for compute jobs."""

    DELETED_STATUSES = {"deleted:finshed", "deleted:cancel"}
    CLEANUP_STATUSES = {"cleaned:finished", "cleaned:cancel"}
    CLEANUP_CLAIM_STATUSES = {"deleting:finished", "deleting:cancel"}
    TERMINAL_STATUSES = DELETED_STATUSES | CLEANUP_STATUSES | CLEANUP_CLAIM_STATUSES | {"cancelled"}

    VALID_STATUSES = {
        "pending",
        "queued",
        "running",
        "finished",
        "failed",
        "cancelled",
        "deleting:finished",
        "deleting:cancel",
        "cleaned:finished",
        "cleaned:cancel",
        "deleted:finshed",
        "deleted:cancel",
    }

    def __init__(
        self, path: str, *, monthly_gpu_seconds: int = DEFAULT_MONTHLY_GPU_SECONDS
    ):
        if monthly_gpu_seconds < 0:
            raise ValueError("monthly_gpu_seconds must be non-negative")
        self.path = os.path.abspath(path)
        self.monthly_gpu_seconds = monthly_gpu_seconds
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.path}",
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        self.metadata = MetaData()
        self.tasks_table = Table(
            "tasks",
            self.metadata,
            Column("md5sum", String(32), primary_key=True),
            Column("filename", String, nullable=False),
            Column("file_path", String, nullable=False),
            Column("uploaded_at", Float, nullable=False),
            Column("started_at", Float),
            Column("finished_at", Float),
            Column("walltime", Float),
            Column("status", String, nullable=False),
            Column("is_binary", Integer, nullable=False),
            Column("source_ip", String),
            Column("user_agent", String),
            Column("username", String),
            Column("local user", String, key="local_user"),
            Column("request_headers", Text),
            Column("run_stage", String),
            Column("error", Text),
            Column("celery_task_id", String),
            Column("task_type", String, nullable=False),
            Column("input_form", Text),
            Column("slurm_job_id", String),
            Column("container_id", String),
            Column("workflow_state", Text),
            Column("storage_key", String, nullable=False),
            Column("submitted_by_user_id", Integer, nullable=False),
            Column("artifact_provenance", Text, nullable=False, default="[]"),
        )
        Index("idx_tasks_uploaded_at", self.tasks_table.c.uploaded_at)
        Index("idx_tasks_submitter", self.tasks_table.c.submitted_by_user_id, self.tasks_table.c.uploaded_at)
        self.gpu_credit_ledger_table = Table(
            "gpu_credit_ledger",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("user_id", Integer, nullable=False),
            Column("period", String(7), nullable=False),
            Column("kind", String, nullable=False),
            Column("gpu_seconds", Integer, nullable=False),
            Column("task_id", String(32)),
            Column("stage_id", String),
            Column("slurm_job_id", String),
            Column("actor_user_id", Integer),
            Column("reason", Text),
            Column("idempotency_key", String, nullable=False, unique=True),
            Column("created_at", Float, nullable=False),
        )
        Index(
            "idx_gpu_credit_ledger_user_period",
            self.gpu_credit_ledger_table.c.user_id,
            self.gpu_credit_ledger_table.c.period,
            self.gpu_credit_ledger_table.c.id,
        )
        self.gpu_credit_policies_table = Table(
            "gpu_credit_policies",
            self.metadata,
            Column("user_id", Integer, primary_key=True),
            Column("monthly_gpu_seconds", Integer, nullable=False),
            Column("updated_by_user_id", Integer, nullable=False),
            Column("updated_at", Float, nullable=False),
        )
        self.gpu_allocations_table = Table(
            "gpu_allocations",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("user_id", Integer, nullable=False),
            Column("task_id", String(32), nullable=False),
            Column("stage_id", String, nullable=False),
            Column("slurm_job_id", String, nullable=False, unique=True),
            Column("gpu_count", Integer, nullable=False),
            Column("started_at", Float, nullable=False),
            Column("finished_at", Float),
            Column("gpu_seconds", Integer),
            Column("status", String, nullable=False),
            Column("ledger_entry_id", Integer),
        )
        Index(
            "idx_gpu_allocations_task_stage",
            self.gpu_allocations_table.c.task_id,
            self.gpu_allocations_table.c.stage_id,
        )
        Index(
            "idx_gpu_allocations_status",
            self.gpu_allocations_table.c.status,
            self.gpu_allocations_table.c.started_at,
        )
        self.gpu_authorizations_table = Table(
            "gpu_authorizations",
            self.metadata,
            Column("user_id", Integer, primary_key=True),
            Column("account_enabled", Integer, nullable=False),
            Column("allow_gpu_use", Integer, nullable=False),
            Column("entitlements", Text, nullable=False),
            Column("updated_at", Float, nullable=False),
        )
        self._initialize()

    def _initialize(self) -> None:
        with self.engine.begin() as conn:
            self._safe_apply_pragmas(conn)
            require_current_schema(
                conn,
                {"tasks": {column.name for column in self.tasks_table.columns}},
                database_name="task database",
                forbidden_columns={"tasks": {"scope_type", "scope_id"}},
            )
            try:
                self.metadata.create_all(conn, checkfirst=True)
                self._install_gpu_ledger_guards(conn)
            except OperationalError as exc:
                # Gunicorn can spawn multiple workers simultaneously which may try to
                # initialize the SQLite schema at the same time. The loser of that
                # race observes an "already exists" error; we can safely ignore it.
                if "already exists" not in str(exc).lower():
                    raise
                logging.warning("TaskDatabase metadata already present, skipping creation")

    @staticmethod
    def _install_gpu_ledger_guards(conn) -> None:
        for operation in ("UPDATE", "DELETE"):
            trigger = f"prevent_gpu_credit_ledger_{operation.lower()}"
            conn.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {operation} ON gpu_credit_ledger "
                "BEGIN SELECT RAISE(ABORT, 'gpu credit ledger is append-only'); END"
            )

    @staticmethod
    def _safe_apply_pragmas(conn) -> None:
        conn.exec_driver_sql("PRAGMA busy_timeout=30000;")
        # During dockerized server tests, concurrent web/worker startup can briefly
        # contend on the same SQLite file. Retrying PRAGMA setup avoids process
        # exit on transient lock without changing DB semantics.
        for attempt in range(3):
            try:
                conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
                conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
                return
            except OperationalError as exc:
                if "database is locked" not in str(exc).lower():
                    raise
                if attempt == 2:
                    logging.warning(
                        "SQLite pragma initialization is locked; proceeding with default pragmas for this process."
                    )
                    return
                time.sleep(0.2 * (attempt + 1))

    @staticmethod
    def _normalize_task_row(row: dict) -> dict:
        normalized = dict(row)
        if "local user" in normalized and "local_user" not in normalized:
            normalized["local_user"] = normalized["local user"]
        return normalized

    def _ensure_status(self, status: str) -> None:
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid task status {status}")

    @classmethod
    def _is_deleted_status(cls, status: Any) -> bool:
        return str(status or "").strip().lower() in cls.DELETED_STATUSES

    def upsert_task(self, task_id: str | None = None, **fields) -> None:
        supplied_id = fields.pop("md5sum", None)
        if task_id is not None and supplied_id is not None and task_id != supplied_id:
            raise ValueError("Conflicting task ids")
        md5sum = task_id or supplied_id
        if not md5sum:
            raise ValueError("Task id is required")
        if not fields:
            return
        status = fields.get("status")
        if status:
            self._ensure_status(status)
        stmt = sqlite_insert(self.tasks_table).values(md5sum=md5sum, **fields)
        stmt = stmt.on_conflict_do_update(
            index_elements=[self.tasks_table.c.md5sum],
            set_={col: getattr(stmt.excluded, col) for col in fields},
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def update_task(self, md5sum: str, **fields) -> bool:
        if not fields:
            return False
        status = fields.get("status")
        if status:
            self._ensure_status(status)
        stmt = update(self.tasks_table).where(self.tasks_table.c.md5sum == md5sum).values(**fields)
        # Terminal tasks (deleted / cancelled) must stay terminal.
        # Ignore late worker writes (running/finished/run_stage, etc.)
        # that would otherwise resurrect tasks after user deletion or
        # cancellation.
        if status is None or (not self._is_deleted_status(status)):
            stmt = stmt.where(self.tasks_table.c.status.notin_(tuple(self.TERMINAL_STATUSES)))
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def claim_task_recovery(self, md5sum: str, *, expected_status: str) -> bool:
        """Atomically move one orphaned active task out of recovery scans."""
        if expected_status not in {"queued", "running"}:
            return False
        stmt = (
            update(self.tasks_table)
            .where(
                self.tasks_table.c.md5sum == md5sum,
                self.tasks_table.c.status == expected_status,
            )
            .values(status="pending")
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def claim_task_cancellation(self, md5sum: str, **fields) -> bool:
        """Atomically cancel a task only while it remains active."""
        stmt = (
            update(self.tasks_table)
            .where(
                self.tasks_table.c.md5sum == md5sum,
                self.tasks_table.c.status.in_(("pending", "queued", "running")),
            )
            .values(status="cancelled", **fields)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def claim_task_cleanup(
        self,
        md5sum: str,
        *,
        expected_status: str,
        expected_finished_at: float,
        claim_status: str,
    ) -> bool:
        """Atomically claim one unchanged terminal task for artifact deletion."""
        if claim_status not in self.CLEANUP_CLAIM_STATUSES:
            raise ValueError(f"Invalid cleanup claim status {claim_status}")
        stmt = (
            update(self.tasks_table)
            .where(
                self.tasks_table.c.md5sum == md5sum,
                self.tasks_table.c.status == expected_status,
                self.tasks_table.c.finished_at == expected_finished_at,
            )
            .values(status=claim_status, celery_task_id=None)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def complete_task_cleanup(self, md5sum: str, *, claim_status: str, cleaned_status: str) -> bool:
        """Finish a claimed cleanup without overwriting a replacement task."""
        if claim_status not in self.CLEANUP_CLAIM_STATUSES:
            raise ValueError(f"Invalid cleanup claim status {claim_status}")
        if cleaned_status not in self.CLEANUP_STATUSES:
            raise ValueError(f"Invalid cleaned status {cleaned_status}")
        stmt = (
            update(self.tasks_table)
            .where(
                self.tasks_table.c.md5sum == md5sum,
                self.tasks_table.c.status == claim_status,
            )
            .values(status=cleaned_status, celery_task_id=None)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def get_task(self, md5sum: str) -> dict | None:
        stmt = select(self.tasks_table).where(self.tasks_table.c.md5sum == md5sum)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        return self._normalize_task_row(row) if row else None

    def list_tasks(self) -> list[dict]:
        stmt = select(self.tasks_table).order_by(desc(self.tasks_table.c.uploaded_at))
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [self._normalize_task_row(row) for row in rows]

    def count_user_active_tasks(self, user_id: int) -> int:
        """Count pending, queued, and running tasks for a user."""
        stmt = (
            select(func.count())
            .select_from(self.tasks_table)
            .where(
                self.tasks_table.c.submitted_by_user_id == user_id,
                self.tasks_table.c.status.in_(["pending", "queued", "running"]),
            )
        )
        with self.engine.connect() as conn:
            return conn.execute(stmt).scalar() or 0

    def project_gpu_authorization(
        self,
        user_id: int,
        *,
        account_enabled: bool,
        allow_gpu_use: bool,
        entitlements: dict[str, float | None],
        updated_at: float | None = None,
    ) -> None:
        """Publish auth-owned GPU eligibility for worker-side final checks."""
        stmt = sqlite_insert(self.gpu_authorizations_table).values(
            user_id=user_id,
            account_enabled=int(account_enabled),
            allow_gpu_use=int(allow_gpu_use),
            entitlements=json.dumps(entitlements, sort_keys=True, separators=(",", ":")),
            updated_at=time.time() if updated_at is None else updated_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[self.gpu_authorizations_table.c.user_id],
            set_={
                "account_enabled": stmt.excluded.account_enabled,
                "allow_gpu_use": stmt.excluded.allow_gpu_use,
                "entitlements": stmt.excluded.entitlements,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def deny_gpu_authorization(self, user_id: int) -> None:
        """Fail closed before an auth-side revoke, disable, or deletion."""
        self.project_gpu_authorization(
            user_id,
            account_enabled=False,
            allow_gpu_use=False,
            entitlements={},
        )

    def require_gpu_authorization(
        self,
        user_id: int,
        *,
        required_entitlements: tuple[str, ...] = (),
        at: float | None = None,
    ) -> None:
        """Require a current projected permission at GPU allocation time."""
        with self.engine.connect() as conn:
            self._require_gpu_authorization(conn, user_id, required_entitlements, at)

    def _require_gpu_authorization(
        self,
        conn,
        user_id: int,
        required_entitlements: tuple[str, ...],
        at: float | None,
    ) -> None:
        row = conn.execute(
            select(self.gpu_authorizations_table).where(
                self.gpu_authorizations_table.c.user_id == user_id
            )
        ).mappings().one_or_none()
        if row is None or not row["account_enabled"] or not row["allow_gpu_use"]:
            raise GPUAuthorizationUnavailableError("GPU access is not currently authorized")
        effective_at = time.time() if at is None else at
        try:
            entitlements = json.loads(row["entitlements"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise GPUAuthorizationUnavailableError("GPU authorization projection is invalid") from exc
        if not isinstance(entitlements, dict):
            raise GPUAuthorizationUnavailableError("GPU authorization projection is invalid")
        for entitlement in required_entitlements:
            if entitlement not in entitlements:
                raise GPUAuthorizationUnavailableError("Required Runner entitlement is unavailable")
            expires_at = entitlements[entitlement]
            if expires_at is not None and float(expires_at) <= effective_at:
                raise GPUAuthorizationUnavailableError("Required Runner entitlement has expired")

    def delete_task(self, md5sum: str) -> None:
        stmt = self.tasks_table.delete().where(self.tasks_table.c.md5sum == md5sum)
        with self.engine.begin() as conn:
            conn.execute(stmt)

    @staticmethod
    def _gpu_period(at: float | None = None) -> str:
        return datetime.fromtimestamp(
            time.time() if at is None else at, timezone.utc
        ).strftime("%Y-%m")

    def _ensure_monthly_gpu_grant(
        self, conn, user_id: int, period: str, created_at: float
    ) -> None:
        allowance = conn.execute(
            select(self.gpu_credit_policies_table.c.monthly_gpu_seconds).where(
                self.gpu_credit_policies_table.c.user_id == user_id
            )
        ).scalar_one_or_none()
        stmt = sqlite_insert(self.gpu_credit_ledger_table).values(
            user_id=user_id,
            period=period,
            kind="monthly_grant",
            gpu_seconds=self.monthly_gpu_seconds if allowance is None else int(allowance),
            task_id=None,
            stage_id=None,
            slurm_job_id=None,
            actor_user_id=None,
            reason="UTC calendar-month allowance",
            idempotency_key=f"monthly_grant:{user_id}:{period}",
            created_at=created_at,
        )
        conn.execute(
            stmt.on_conflict_do_nothing(
                index_elements=[self.gpu_credit_ledger_table.c.idempotency_key]
            )
        )

    def gpu_credit_summary(
        self, user_id: int, *, at: float | None = None
    ) -> dict[str, Any]:
        """Return a balance derived from append-only entries for one UTC month."""
        checked_at = time.time() if at is None else at
        period = self._gpu_period(checked_at)
        with self.engine.begin() as conn:
            self._ensure_monthly_gpu_grant(conn, user_id, period, checked_at)
            rows = conn.execute(
                select(
                    self.gpu_credit_ledger_table.c.kind,
                    func.sum(self.gpu_credit_ledger_table.c.gpu_seconds),
                )
                .where(
                    self.gpu_credit_ledger_table.c.user_id == user_id,
                    self.gpu_credit_ledger_table.c.period == period,
                )
                .group_by(self.gpu_credit_ledger_table.c.kind)
            ).all()
        totals = {str(kind): int(total or 0) for kind, total in rows}
        return {
            "user_id": user_id,
            "period": period,
            "monthly_grant_gpu_seconds": totals.get("monthly_grant", 0)
            + totals.get("allowance_adjustment", 0),
            "usage_gpu_seconds": -totals.get("usage", 0),
            "adjustment_gpu_seconds": totals.get("admin_adjustment", 0)
            + totals.get("reversal", 0),
            "remaining_gpu_seconds": sum(totals.values()),
        }

    def set_gpu_monthly_allowance(
        self,
        *,
        user_id: int,
        monthly_gpu_seconds: int,
        actor_user_id: int,
        idempotency_key: str,
        updated_at: float | None = None,
    ) -> dict[str, Any]:
        """Set current/future allowance while preserving an append-only ledger."""
        if monthly_gpu_seconds < 0 or monthly_gpu_seconds > 10_000_000:
            raise ValueError("monthly_gpu_seconds must be between 0 and 10000000")
        timestamp = time.time() if updated_at is None else updated_at
        period = self._gpu_period(timestamp)
        durable_key = f"allowance_adjustment:{user_id}:{idempotency_key}"
        reason = f"Monthly allowance set to {monthly_gpu_seconds} GPU-seconds"
        with self.engine.begin() as conn:
            prior = conn.execute(
                select(self.gpu_credit_ledger_table).where(
                    self.gpu_credit_ledger_table.c.idempotency_key == durable_key
                )
            ).mappings().one_or_none()
            if prior is not None:
                if prior["reason"] != reason or prior["actor_user_id"] != actor_user_id:
                    raise ValueError("idempotency_key was already used for a different allowance")
                return dict(prior)
            self._ensure_monthly_gpu_grant(conn, user_id, period, timestamp)
            current_allowance = conn.execute(
                select(func.sum(self.gpu_credit_ledger_table.c.gpu_seconds)).where(
                    self.gpu_credit_ledger_table.c.user_id == user_id,
                    self.gpu_credit_ledger_table.c.period == period,
                    self.gpu_credit_ledger_table.c.kind.in_(("monthly_grant", "allowance_adjustment")),
                )
            ).scalar_one() or 0
            delta = monthly_gpu_seconds - int(current_allowance)
            policy = sqlite_insert(self.gpu_credit_policies_table).values(
                user_id=user_id,
                monthly_gpu_seconds=monthly_gpu_seconds,
                updated_by_user_id=actor_user_id,
                updated_at=timestamp,
            ).on_conflict_do_update(
                index_elements=[self.gpu_credit_policies_table.c.user_id],
                set_={
                    "monthly_gpu_seconds": monthly_gpu_seconds,
                    "updated_by_user_id": actor_user_id,
                    "updated_at": timestamp,
                },
            )
            conn.execute(policy)
            result = conn.execute(
                sqlite_insert(self.gpu_credit_ledger_table).values(
                    user_id=user_id,
                    period=period,
                    kind="allowance_adjustment",
                    gpu_seconds=delta,
                    actor_user_id=actor_user_id,
                    reason=reason,
                    idempotency_key=durable_key,
                    created_at=timestamp,
                )
            )
            row = conn.execute(
                select(self.gpu_credit_ledger_table).where(
                    self.gpu_credit_ledger_table.c.id == result.inserted_primary_key[0]
                )
            ).mappings().one()
        return dict(row)

    def require_gpu_credit(
        self, user_id: int, *, at: float | None = None
    ) -> dict[str, Any]:
        """Fail when the current UTC-month balance cannot admit a new allocation."""
        summary = self.gpu_credit_summary(user_id, at=at)
        if summary["remaining_gpu_seconds"] <= 0:
            raise GPUCreditUnavailableError("GPU credit balance is exhausted")
        return summary

    def adjust_gpu_credit(
        self,
        *,
        user_id: int,
        gpu_seconds: int,
        actor_user_id: int,
        reason: str,
        idempotency_key: str,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        """Append an adjustment, returning the prior row on an identical retry."""
        if gpu_seconds == 0:
            raise ValueError("gpu_seconds must be non-zero")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("reason is required")
        timestamp = time.time() if created_at is None else created_at
        period = self._gpu_period(timestamp)
        durable_key = f"admin_adjustment:{user_id}:{idempotency_key}"
        stmt = sqlite_insert(self.gpu_credit_ledger_table).values(
            user_id=user_id,
            period=period,
            kind="admin_adjustment",
            gpu_seconds=gpu_seconds,
            task_id=None,
            stage_id=None,
            slurm_job_id=None,
            actor_user_id=actor_user_id,
            reason=normalized_reason,
            idempotency_key=durable_key,
            created_at=timestamp,
        ).on_conflict_do_nothing(index_elements=[self.gpu_credit_ledger_table.c.idempotency_key])
        with self.engine.begin() as conn:
            self._ensure_monthly_gpu_grant(conn, user_id, period, timestamp)
            conn.execute(stmt)
            row = conn.execute(
                select(self.gpu_credit_ledger_table).where(
                    self.gpu_credit_ledger_table.c.idempotency_key == durable_key
                )
            ).mappings().one()
        expected = (user_id, gpu_seconds, actor_user_id, normalized_reason)
        actual = (row["user_id"], row["gpu_seconds"], row["actor_user_id"], row["reason"])
        if actual != expected:
            raise ValueError("idempotency_key was already used for a different adjustment")
        return dict(row)

    def list_gpu_credit_ledger(
        self, user_id: int, *, period: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return recent immutable entries for one user, newest first."""
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        stmt = select(self.gpu_credit_ledger_table).where(self.gpu_credit_ledger_table.c.user_id == user_id)
        if period is not None:
            stmt = stmt.where(self.gpu_credit_ledger_table.c.period == period)
        stmt = stmt.order_by(desc(self.gpu_credit_ledger_table.c.id)).limit(limit)
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    def record_gpu_allocation_start(
        self,
        *,
        user_id: int,
        task_id: str,
        stage_id: str,
        slurm_job_id: str,
        gpu_count: int,
        started_at: float | None = None,
        required_entitlements: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Record the instant a real Slurm GPU allocation becomes observable."""
        if gpu_count < 1:
            raise ValueError("gpu_count must be positive")
        timestamp = time.time() if started_at is None else started_at
        stmt = sqlite_insert(self.gpu_allocations_table).values(
            user_id=user_id,
            task_id=task_id,
            stage_id=stage_id,
            slurm_job_id=slurm_job_id,
            gpu_count=gpu_count,
            started_at=timestamp,
            finished_at=None,
            gpu_seconds=None,
            status="active",
            ledger_entry_id=None,
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[self.gpu_allocations_table.c.slurm_job_id]
        )
        with self.engine.begin() as conn:
            existing = (
                conn.execute(
                    select(self.gpu_allocations_table).where(
                        self.gpu_allocations_table.c.slurm_job_id == slurm_job_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                expected = (user_id, task_id, stage_id, gpu_count)
                actual = (
                    existing["user_id"],
                    existing["task_id"],
                    existing["stage_id"],
                    existing["gpu_count"],
                )
                if actual != expected:
                    raise ValueError(
                        "Slurm job ID is already associated with a different GPU allocation"
                    )
                return dict(existing)
            if required_entitlements is not None:
                self._require_gpu_authorization(conn, user_id, required_entitlements, timestamp)
            period = self._gpu_period(timestamp)
            self._ensure_monthly_gpu_grant(conn, user_id, period, timestamp)
            balance = conn.execute(
                select(func.sum(self.gpu_credit_ledger_table.c.gpu_seconds)).where(
                    self.gpu_credit_ledger_table.c.user_id == user_id,
                    self.gpu_credit_ledger_table.c.period == period,
                )
            ).scalar()
            if int(balance or 0) <= 0:
                raise GPUCreditUnavailableError("GPU credit balance is exhausted")
            conn.execute(stmt)
            row = (
                conn.execute(
                    select(self.gpu_allocations_table).where(
                        self.gpu_allocations_table.c.slurm_job_id == slurm_job_id
                    )
                )
                .mappings()
                .one()
            )
        expected = (user_id, task_id, stage_id, gpu_count)
        actual = (row["user_id"], row["task_id"], row["stage_id"], row["gpu_count"])
        if actual != expected:
            raise ValueError(
                "Slurm job ID is already associated with a different GPU allocation"
            )
        return dict(row)

    def settle_gpu_allocation(
        self, slurm_job_id: str, *, finished_at: float | None = None
    ) -> dict[str, Any]:
        """Append actual GPU usage once and return the durable allocation record."""
        timestamp = time.time() if finished_at is None else finished_at
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self.gpu_allocations_table).where(
                    self.gpu_allocations_table.c.slurm_job_id == slurm_job_id
                )
            ).mappings().one_or_none()
        if row is None:
            raise ValueError(f"Unknown Slurm GPU allocation: {slurm_job_id}")
        elapsed_seconds = max(0, math.ceil(timestamp - float(row["started_at"])))
        return self.settle_gpu_allocation_elapsed(
            slurm_job_id,
            elapsed_seconds=elapsed_seconds,
            finished_at=timestamp,
        )

    def settle_gpu_allocation_elapsed(
        self,
        slurm_job_id: str,
        *,
        elapsed_seconds: int,
        finished_at: float | None = None,
    ) -> dict[str, Any]:
        """Settle once from an authoritative allocation elapsed duration."""
        if elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be non-negative")
        timestamp = time.time() if finished_at is None else finished_at
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    select(self.gpu_allocations_table).where(
                        self.gpu_allocations_table.c.slurm_job_id == slurm_job_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError(f"Unknown Slurm GPU allocation: {slurm_job_id}")
            if row["status"] == "settled":
                return dict(row)
            gpu_seconds = int(row["gpu_count"]) * elapsed_seconds
            ledger_stmt = (
                sqlite_insert(self.gpu_credit_ledger_table)
                .values(
                    user_id=row["user_id"],
                    period=self._gpu_period(float(row["started_at"])),
                    kind="usage",
                    gpu_seconds=-gpu_seconds,
                    task_id=row["task_id"],
                    stage_id=row["stage_id"],
                    slurm_job_id=slurm_job_id,
                    actor_user_id=None,
                    reason="Actual Slurm GPU allocation time",
                    idempotency_key=f"usage:{slurm_job_id}",
                    created_at=timestamp,
                )
                .on_conflict_do_nothing(
                    index_elements=[self.gpu_credit_ledger_table.c.idempotency_key]
                )
            )
            result = conn.execute(ledger_stmt)
            if result.rowcount:
                ledger_id = result.inserted_primary_key[0]
            else:
                ledger_id = conn.execute(
                    select(self.gpu_credit_ledger_table.c.id).where(
                        self.gpu_credit_ledger_table.c.idempotency_key
                        == f"usage:{slurm_job_id}"
                    )
                ).scalar_one()
            conn.execute(
                update(self.gpu_allocations_table)
                .where(self.gpu_allocations_table.c.id == row["id"])
                .values(
                    finished_at=timestamp,
                    gpu_seconds=gpu_seconds,
                    status="settled",
                    ledger_entry_id=ledger_id,
                )
            )
            settled = (
                conn.execute(
                    select(self.gpu_allocations_table).where(
                        self.gpu_allocations_table.c.id == row["id"]
                    )
                )
                .mappings()
                .one()
            )
        return dict(settled)

    def mark_gpu_allocation_for_review(self, slurm_job_id: str) -> bool:
        """Expose an allocation whose authoritative elapsed time is unavailable."""
        stmt = (
            update(self.gpu_allocations_table)
            .where(
                self.gpu_allocations_table.c.slurm_job_id == slurm_job_id,
                self.gpu_allocations_table.c.status != "settled",
            )
            .values(status="review")
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def list_unsettled_gpu_allocations(self) -> list[dict[str, Any]]:
        stmt = (
            select(self.gpu_allocations_table)
            .where(self.gpu_allocations_table.c.status.in_(("active", "review")))
            .order_by(self.gpu_allocations_table.c.started_at)
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]
