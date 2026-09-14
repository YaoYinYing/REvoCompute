# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Ephemeral Tool call identities and SQLite lifecycle state."""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Column, Float, Index, Integer, MetaData, String, Table, Text, create_engine, func, select, update

TOOL_CALL_ID_PATTERN = re.compile(r"tool_call_[A-Za-z0-9_-]{32}\Z")
ACTIVE_STATUSES = ("queued", "preparing", "running")
TERMINAL_STATUSES = ("finished", "failed")
VALID_STATUSES = frozenset((*ACTIVE_STATUSES, *TERMINAL_STATUSES))


class ToolAdmissionError(RuntimeError):
    """A retryable outstanding-work or storage admission rejection."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ToolCallReservation:
    call: dict[str, Any]
    created: bool


def new_tool_call_id() -> str:
    return f"tool_call_{secrets.token_urlsafe(24)}"


def normalize_tool_call_id(value: Any) -> str | None:
    candidate = str(value or "").strip()
    return candidate if TOOL_CALL_ID_PATTERN.fullmatch(candidate) else None


class ToolCallDatabase:
    """Lifecycle store isolated from durable Task rows in the deployment database."""

    def __init__(self, path: str) -> None:
        self.engine = create_engine(
            f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False, "timeout": 30}
        )
        self.metadata = MetaData()
        self.table = Table(
            "tool_calls",
            self.metadata,
            Column("tool_call_id", String(42), primary_key=True),
            Column("tool_type", String(64), nullable=False),
            Column("runtime_family", String(64), nullable=False),
            Column("runtime_identity", String(64), nullable=False),
            Column("submitted_by_user_id", Integer, nullable=False),
            Column("username", String, nullable=False),
            Column("status", String(16), nullable=False),
            Column("created_at", Float, nullable=False),
            Column("started_at", Float),
            Column("finished_at", Float),
            Column("expires_at", Float),
            Column("idempotency_key", String(255)),
            Column("parameter_json", Text, nullable=False),
            Column("input_manifest_json", Text, nullable=False),
            Column("result_manifest_json", Text),
            Column("workspace_bytes", Integer, nullable=False, default=0),
            Column("celery_task_id", String),
            Column("error_class", String(32)),
            Column("error", Text),
        )
        Index("idx_tool_calls_user_status", self.table.c.submitted_by_user_id, self.table.c.status)
        Index("idx_tool_calls_expiry", self.table.c.expires_at)
        Index("idx_tool_calls_terminal_age", self.table.c.status, self.table.c.finished_at)
        Index(
            "uq_tool_calls_idempotency",
            self.table.c.submitted_by_user_id,
            self.table.c.tool_type,
            self.table.c.idempotency_key,
            unique=True,
        )
        with self.engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA busy_timeout=30000")
            self.metadata.create_all(conn, checkfirst=True)

    @staticmethod
    def _row(row: Any) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def reserve(
        self,
        *,
        tool_call_id: str,
        tool_type: str,
        runtime_family: str,
        runtime_identity: str,
        user_id: int,
        username: str,
        parameter_json: str,
        input_manifest_json: str,
        idempotency_key: str | None,
        per_user_limit: int,
        global_limit: int,
        workspace_bytes: int = 0,
        storage_max_bytes: int | None = None,
        created_at: float | None = None,
    ) -> ToolCallReservation:
        if normalize_tool_call_id(tool_call_id) is None:
            raise ValueError("Invalid Tool call id")
        if per_user_limit < 1 or global_limit < 1:
            raise ValueError("Tool admission limits must be positive")
        if workspace_bytes < 0 or (storage_max_bytes is not None and storage_max_bytes < 1):
            raise ValueError("Tool storage admission values are invalid")
        now = time.time() if created_at is None else created_at
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                if idempotency_key:
                    existing = conn.execute(
                        select(self.table).where(
                            self.table.c.submitted_by_user_id == user_id,
                            self.table.c.tool_type == tool_type,
                            self.table.c.idempotency_key == idempotency_key,
                        )
                    ).mappings().first()
                    if existing is not None:
                        conn.commit()
                        return ToolCallReservation(dict(existing), False)
                global_active = conn.execute(
                    select(func.count()).select_from(self.table).where(self.table.c.status.in_(ACTIVE_STATUSES))
                ).scalar_one()
                if global_active >= global_limit:
                    raise ToolAdmissionError("global_limit")
                user_active = conn.execute(
                    select(func.count()).select_from(self.table).where(
                        self.table.c.submitted_by_user_id == user_id,
                        self.table.c.status.in_(ACTIVE_STATUSES),
                    )
                ).scalar_one()
                if user_active >= per_user_limit:
                    raise ToolAdmissionError("user_limit")
                if storage_max_bytes is not None:
                    reserved_bytes = conn.execute(
                        select(func.coalesce(func.sum(self.table.c.workspace_bytes), 0))
                    ).scalar_one()
                    if int(reserved_bytes) + workspace_bytes > storage_max_bytes:
                        raise ToolAdmissionError("storage_limit")
                values = {
                    "tool_call_id": tool_call_id,
                    "tool_type": tool_type,
                    "runtime_family": runtime_family,
                    "runtime_identity": runtime_identity,
                    "submitted_by_user_id": user_id,
                    "username": username,
                    "status": "queued",
                    "created_at": now,
                    "idempotency_key": idempotency_key,
                    "parameter_json": parameter_json,
                    "input_manifest_json": input_manifest_json,
                    "workspace_bytes": workspace_bytes,
                }
                conn.execute(self.table.insert().values(**values))
                conn.commit()
                return ToolCallReservation(values, True)
            except Exception:
                conn.rollback()
                raise

    def get(self, tool_call_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self.table).where(self.table.c.tool_call_id == tool_call_id)
            ).mappings().first()
        return self._row(row)

    def get_owned(self, tool_call_id: str, user_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self.table).where(
                    self.table.c.tool_call_id == tool_call_id,
                    self.table.c.submitted_by_user_id == user_id,
                )
            ).mappings().first()
        return self._row(row)

    def transition(self, tool_call_id: str, *, expected: tuple[str, ...], status: str, **fields: Any) -> bool:
        if status not in VALID_STATUSES or any(item not in VALID_STATUSES for item in expected):
            raise ValueError("Invalid Tool call lifecycle status")
        if status in TERMINAL_STATUSES and ("finished_at" not in fields or "expires_at" not in fields):
            raise ValueError("Terminal Tool calls require finish and expiry times")
        statement = (
            update(self.table)
            .where(self.table.c.tool_call_id == tool_call_id, self.table.c.status.in_(expected))
            .values(status=status, **fields)
        )
        with self.engine.begin() as conn:
            return conn.execute(statement).rowcount == 1

    def update(self, tool_call_id: str, **fields: Any) -> bool:
        if "status" in fields:
            raise ValueError("Use transition() to change Tool call status")
        with self.engine.begin() as conn:
            return conn.execute(
                update(self.table).where(self.table.c.tool_call_id == tool_call_id).values(**fields)
            ).rowcount == 1

    def total_workspace_bytes(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.coalesce(func.sum(self.table.c.workspace_bytes), 0))).scalar_one())

    def cleanup_candidates(self, *, now: float, storage_pressure: bool = False) -> list[dict[str, Any]]:
        condition = self.table.c.status.in_(TERMINAL_STATUSES)
        if not storage_pressure:
            condition = condition & (self.table.c.expires_at <= now)
        statement = select(self.table).where(condition).order_by(self.table.c.finished_at, self.table.c.created_at)
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(statement).mappings().all()]

    def delete_terminal(self, tool_call_id: str) -> bool:
        with self.engine.begin() as conn:
            return conn.execute(
                self.table.delete().where(
                    self.table.c.tool_call_id == tool_call_id,
                    self.table.c.status.in_(TERMINAL_STATUSES),
                )
            ).rowcount == 1

    def active_by_family(self, family: str) -> int:
        with self.engine.connect() as conn:
            return int(
                conn.execute(
                    select(func.count()).select_from(self.table).where(
                        self.table.c.runtime_family == family,
                        self.table.c.status.in_(ACTIVE_STATUSES),
                    )
                ).scalar_one()
            )

    def fail_orphaned(self, *, finished_at: float, expires_at: float) -> int:
        """Fail active calls after the dedicated Tool worker generation restarts."""
        statement = (
            update(self.table)
            .where(self.table.c.status.in_(ACTIVE_STATUSES))
            .values(
                status="failed",
                finished_at=finished_at,
                expires_at=expires_at,
                celery_task_id=None,
                error_class="runtime_unavailable",
                error="Tool worker restarted before the call completed",
            )
        )
        with self.engine.begin() as conn:
            return conn.execute(statement).rowcount
