# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    select,
)

# ---------------------------------------------------------------------------
# Opaque MCP operation handles
# ---------------------------------------------------------------------------
#
# A long-running scientific operation is identified to an MCP client by an
# opaque handle, never by REvoCompute's content-derived Task/ToolCall id.  The
# id is derived from submitted content, so it is guessable by anyone who can
# reconstruct the same inputs and it leaks scientific identity; the handle is
# high-entropy, user-scoped, and expires.
#
# The store keeps only the mapping the protocol needs: handle, owner, kind, the
# underlying canonical id, and an expiry.  It is deliberately not a second copy
# of the scientific lifecycle -- ownership is re-checked against the canonical
# record on every access, and the kind/handle live only here.

HANDLE_PREFIX = "mcp_op_"
_HANDLE_BYTES = 32  # secrets.token_urlsafe(32) -> 43 characters, ~256 bits

_DEFAULT_TTL_SECONDS = 86400
_MIN_TTL_SECONDS = 300
_MAX_TTL_SECONDS = 30 * 86400

#: Mint this many handles between opportunistic expiry sweeps, so an abandoned
#: handle cannot accumulate rows forever.
_PRUNE_EVERY_MINTS = 64

KIND_TASK = "task"
KIND_TOOL_CALL = "tool_call"


@dataclass(frozen=True)
class OperationHandle:
    handle: str
    operation_id: str
    user_id: int
    kind: str
    created_at: float
    expires_at: float


class OperationHandleStore:
    """Durable-enough, self-expiring mapping from an opaque handle to an operation.

    The mapping is not authoritative for anything except protocol identity and
    ownership scoping.  ``resolve`` is always scoped by ``user_id``: a handle
    that belongs to somebody else resolves to ``None`` exactly like a handle
    that never existed, so a caller cannot probe another user's operations.
    """

    def __init__(self, path: str, *, ttl_seconds: int = _DEFAULT_TTL_SECONDS):
        if not _MIN_TTL_SECONDS <= ttl_seconds <= _MAX_TTL_SECONDS:
            raise ValueError(f"handle TTL must be between {_MIN_TTL_SECONDS} and {_MAX_TTL_SECONDS} seconds")
        self.path = path
        self.ttl_seconds = ttl_seconds
        self._mints_since_prune = 0
        self.engine = create_engine(f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False})
        self.metadata = MetaData()
        self.table = Table(
            "mcp_operation_handles",
            self.metadata,
            Column("handle", String(64), primary_key=True),
            Column("operation_id", String(64), nullable=False, default=""),
            Column("user_id", Integer, nullable=False),
            Column("kind", String(16), nullable=False),
            Column("created_at", Float, nullable=False),
            Column("expires_at", Float, nullable=False),
        )
        self.metadata.create_all(self.engine)

    # -- lifecycle ---------------------------------------------------------

    def prune(self, *, now: float) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(delete(self.table).where(self.table.c.expires_at <= now))
            return int(result.rowcount or 0)

    def revoke(self, handle: str, *, user_id: int) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                delete(self.table).where(
                    (self.table.c.handle == handle) & (self.table.c.user_id == user_id)
                )
            )
            return bool(result.rowcount)

    # -- mapping -----------------------------------------------------------

    def mint(self, *, user_id: int, kind: str, now: float) -> str:
        """Mint an unbound handle.  ``bind`` attaches the canonical id."""
        import secrets

        handle = HANDLE_PREFIX + secrets.token_urlsafe(_HANDLE_BYTES)
        with self.engine.begin() as conn:
            conn.execute(
                self.table.insert().values(
                    handle=handle,
                    operation_id="",
                    user_id=user_id,
                    kind=kind,
                    created_at=now,
                    expires_at=now + self.ttl_seconds,
                )
            )
        # Expired rows are otherwise only removed when the exact handle is
        # resolved, which never happens for an abandoned handle.  Reaping
        # periodically on the write path bounds the table without a scheduler.
        self._mints_since_prune += 1
        if self._mints_since_prune >= _PRUNE_EVERY_MINTS:
            self._mints_since_prune = 0
            self.prune(now=now)
        return handle

    def bind(self, handle: str, operation_id: str, *, now: float) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                self.table.update()
                .where(self.table.c.handle == handle)
                .values(operation_id=operation_id, expires_at=now + self.ttl_seconds)
            )

    def resolve(self, handle: str, *, user_id: int, kind: str, now: float) -> OperationHandle | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(self.table).where((self.table.c.handle == handle) & (self.table.c.user_id == user_id))
            ).one_or_none()
        if row is None:
            return None
        mapping = row._mapping
        if str(mapping["kind"]) != kind:
            return None
        if not mapping["operation_id"]:
            # Minted but never bound: a submission that failed before the
            # canonical operation existed.  Fail closed.
            return None
        if float(mapping["expires_at"]) <= now:
            self.revoke(handle, user_id=user_id)
            return None
        return OperationHandle(
            handle=str(mapping["handle"]),
            operation_id=str(mapping["operation_id"]),
            user_id=int(mapping["user_id"]),
            kind=str(mapping["kind"]),
            created_at=float(mapping["created_at"]),
            expires_at=float(mapping["expires_at"]),
        )


# ---------------------------------------------------------------------------
# Canonical web-application accessors
# ---------------------------------------------------------------------------
#
# The MCP adapter owns no state that the web application already owns.  It
# resolves the deployed Flask application, its user database, and its handle
# store lazily, keyed by module identity, so a test that loads an isolated
# application copy gets an isolated handle store and no second source of truth.


_STATE_CACHE: dict[int, "_CanonicalState"] = {}


@dataclass(frozen=True)
class _CanonicalState:
    web: Any
    user_db: Any
    handles: OperationHandleStore


def _handle_ttl_seconds() -> int:
    raw = os.environ.get("MCP_HANDLE_TTL_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_TTL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_TTL_SECONDS
    return value if _MIN_TTL_SECONDS <= value <= _MAX_TTL_SECONDS else _DEFAULT_TTL_SECONDS


def canonical_state() -> _CanonicalState:
    """Return the canonical application, user database, and handle store.

    The runtime keys on ``web.app`` (not the module object), so a test that
    reloads the application module and swaps ``sys.modules["revocompute.app"]``
    -- as the repository's isolated-application fixture does -- gets a state
    built from *that* application rather than a stale one.
    """
    web = importlib.import_module("revocompute.app")
    key = id(web.app)
    cached = _STATE_CACHE.get(key)
    if cached is not None:
        return cached
    config = web.CONFIG
    handle_path = os.environ.get("MCP_HANDLE_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(config.db_path)), "mcp_handles.sqlite3"
    )
    state = _CanonicalState(
        web=web,
        user_db=web.app.config["user_db"],
        handles=OperationHandleStore(handle_path, ttl_seconds=_handle_ttl_seconds()),
    )
    # One live application at a time: drop any state built for a previous one so
    # the cache cannot grow or resolve to a replaced application.
    _STATE_CACHE.clear()
    _STATE_CACHE[key] = state
    return state
