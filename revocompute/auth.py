# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Token-based authentication and user management for the REvoCompute server.

Replaces the static ``users.txt`` HTTP Basic Auth model with a SQLite-backed
user store, Bearer-token authentication, and an optional registration workflow
gated by ``ENABLE_REGISTER``.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import logging
import os
import re
import secrets
import smtplib
import time
from collections.abc import Callable
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from typing import Any

import sqlalchemy as sa
from flask import current_app, g, jsonify, redirect, request, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from revocompute.config import env_bool as _env_bool
from revocompute.config import env_int as _env_int
from revocompute.config import env_str as _env_str
from revocompute.redis_util import get_redis
from revocompute.schema_epoch import require_current_schema
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

# Pre-computed dummy hash used for constant-time comparison when a login
# attempt targets a non-existent user — prevents timing-based username
# enumeration.  check_password_hash is intentionally slow (key derivation);
# skipping it for missing users leaks existence via response-time side-channel.
_DUMMY_PASSWORD_HASH = generate_password_hash("revodesign-dummy-never-matches-any-real-password")

# ---------------------------------------------------------------------------
# Resend email (optional extra — falls back to stdlib SMTP when not installed)
# ---------------------------------------------------------------------------

try:
    import resend as _resend_module

    _resend_key = os.environ.get("RESEND_API_KEY", "")
    if _resend_key:
        _resend_module.api_key = _resend_key
    _HAS_RESEND = True
except ImportError:
    _resend_module = None  # type: ignore[assignment]
    _resend_key = ""
    _HAS_RESEND = False

# ---------------------------------------------------------------------------
# User database
# ---------------------------------------------------------------------------

_metadata = sa.MetaData()

_users_table = sa.Table(
    "users",
    _metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("username", sa.String(128), nullable=False, unique=True, index=True),
    sa.Column("email", sa.String(256), nullable=False, unique=True),
    sa.Column("password_hash", sa.String(256), nullable=False),
    sa.Column("email_verified", sa.Boolean, nullable=False, default=False),
    sa.Column("created_at", sa.Float, nullable=False),
    # sha256 hex digest of the API key.  High-entropy keys need no slow KDF —
    # the digest is indexed so validation is one lookup, not O(users x KDF).
    sa.Column("api_key_digest", sa.String(64), nullable=True, index=True),
    sa.Column("full_name", sa.String(128), nullable=True),
    sa.Column("affiliation", sa.String(256), nullable=True),
    sa.Column("position", sa.String(64), nullable=True),
    sa.Column("pi_name", sa.String(128), nullable=True),
    sa.Column("terms_agreed", sa.Boolean, nullable=False, default=False),
    sa.Column("registration_status", sa.String(32), nullable=False, default="email_sent"),
    sa.Column("user_status", sa.String(32), nullable=False, default="pending"),
    sa.Column("approved_by", sa.Integer, nullable=True),
    sa.Column("approved_at", sa.Float, nullable=True),
    sa.Column("deleted", sa.Boolean, nullable=False, default=False),
    sa.Column("role", sa.String(32), nullable=False, default="user"),
    sa.Column("admin_notified", sa.Boolean, nullable=False, default=False),
    sa.Column("verification_resend_count", sa.Integer, nullable=False, default=0),
    sa.Column("verification_resend_at", sa.Float, nullable=True),
    sa.Column("registration_ip", sa.String(45), nullable=True),
    sa.Column("registration_country", sa.String(8), nullable=True),
    sa.Column("token_version", sa.Integer, nullable=False, default=0),
    sa.Column("allow_gpu_use", sa.Boolean, nullable=False, default=False),
    sa.Column("storage_key", sa.String(128), nullable=False, unique=True),
)

_access_requests_table = sa.Table(
    "access_requests",
    _metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("entitlement", sa.String(64), nullable=False, index=True),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("reason", sa.String(1000), nullable=False),
    sa.Column("requested_at", sa.Float, nullable=False),
    sa.Column("reviewed_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
    sa.Column("reviewed_at", sa.Float, nullable=True),
    sa.Column("review_note", sa.String(1000), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'cancelled')", name="valid_access_status"),
    sa.Index(
        "uq_pending_access_request",
        "user_id",
        "entitlement",
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
    ),
)

_user_entitlements_table = sa.Table(
    "user_entitlements",
    _metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("entitlement", sa.String(64), nullable=False, index=True),
    sa.Column("granted_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("granted_at", sa.Float, nullable=False),
    sa.Column("expires_at", sa.Float, nullable=True),
    sa.Column("basis", sa.String(32), nullable=False),
    sa.Column("note", sa.String(1000), nullable=True),
    sa.Column("source_request_id", sa.Integer, sa.ForeignKey("access_requests.id"), nullable=True),
    sa.Column("revoked_at", sa.Float, nullable=True),
    sa.Column("revoked_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
    sa.CheckConstraint(
        "basis IN ('lab_member', 'institutional_collaborator', 'individually_verified', 'other')",
        name="valid_entitlement_basis",
    ),
)

_runner_access_events_table = sa.Table(
    "runner_access_events",
    _metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("policy_id", sa.String(64), nullable=False, index=True),
    sa.Column("event_type", sa.String(64), nullable=False),
    sa.Column("task_type", sa.String(64), nullable=False),
    sa.Column("runtime_family", sa.String(64), nullable=False),
    sa.Column("outcome", sa.String(16), nullable=False),
    sa.Column("reason_code", sa.String(64), nullable=False),
    sa.Column("occurred_at", sa.Float, nullable=False, index=True),
    sa.Column("ip_address", sa.String(45), nullable=True),
    sa.Column("user_agent", sa.String(512), nullable=True),
    sa.Column("auth_method", sa.String(16), nullable=True),
    sa.Column("scope_type", sa.String(16), nullable=True),
    sa.Column("scope_id", sa.String(64), nullable=True),
    sa.CheckConstraint("outcome IN ('allowed', 'denied', 'suspended', 'blocked', 'cleared')", name="valid_runner_access_outcome"),
    sa.Index("ix_runner_access_events_policy_time", "policy_id", "occurred_at"),
)


def _new_user_storage_key(username: str) -> str:
    """Generate a readable storage key whose random suffix is immutable."""
    prefix = re.sub(r"[^A-Za-z0-9]+", "-", username).strip("-").lower()[:32] or "user"
    suffix = secrets.token_urlsafe(6).lower().replace("_", "-").replace("=", "")
    return f"{prefix}-{suffix}"


def _get_user_db_path() -> str:
    """Resolve the user database path.

    Uses ``USER_DB_PATH`` env var, falling back to the required
    ``{SERVER_DIR}/users.sqlite3``.
    """
    from_server_dir = os.environ.get("SERVER_DIR", "")
    default = (
        os.path.join(from_server_dir, "users.sqlite3")
        if from_server_dir
        else os.path.join(os.getcwd(), "users.sqlite3")
    )
    return _env_str("USER_DB_PATH", default)


class UserDatabase:
    """SQLite-backed store for user accounts."""

    def __init__(self, path: str | None = None):
        self.path = os.path.abspath(path or _get_user_db_path())
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass  # file does not exist yet — SQLAlchemy create_all will create it
        self.engine = sa.create_engine(
            f"sqlite:///{self.path}",
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        sa.event.listen(
            self.engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON")
        )
        self._initialize()

    def _initialize(self) -> None:
        with self.engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA busy_timeout=30000;")
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
            require_current_schema(
                conn,
                {"users": {column.name for column in _users_table.columns}},
                database_name="user database",
            )
            _metadata.create_all(conn, checkfirst=True)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # -- write helpers -------------------------------------------------------

    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        *,
        role: str = "user",
        full_name: str | None = None,
        affiliation: str | None = None,
        position: str | None = None,
        pi_name: str | None = None,
        terms_agreed: bool = False,
        registration_status: str = "email_sent",
        user_status: str = "pending",
        registration_ip: str | None = None,
        registration_country: str | None = None,
    ) -> dict[str, Any]:
        """Insert a new user.  Returns the row as a dict."""
        if role not in {"admin", "user", "guest"}:
            raise ValueError(f"Unsupported user role: {role!r}")
        now = time.time()
        stmt = sa.insert(_users_table).values(
            username=username,
            email=email.lower().strip(),
            password_hash=generate_password_hash(password),
            email_verified=False,
            role=role,
            created_at=now,
            full_name=full_name,
            affiliation=affiliation,
            position=position,
            pi_name=pi_name,
            terms_agreed=terms_agreed,
            registration_status=registration_status,
            registration_ip=registration_ip,
            registration_country=registration_country,
            user_status=user_status,
            storage_key=_new_user_storage_key(username),
        )
        with self.engine.begin() as conn:
            result = conn.execute(stmt)
            row_id = result.inserted_primary_key[0]
        return self.get_user(row_id)  # type: ignore[return-value]

    def verify_email(self, user_id: int) -> None:
        stmt = sa.update(_users_table).where(_users_table.c.id == user_id).values(email_verified=True)
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def update_user(self, user_id: int, **fields: Any) -> None:
        """Update allowed user fields in-place.

        Allowed keys: ``username``, ``email``, ``password_hash``,
        ``email_verified``, ``api_key_digest``,
        ``full_name``, ``affiliation``, ``position``, ``pi_name``,
        ``terms_agreed``, ``registration_status``,
        ``user_status``, ``approved_by``, ``approved_at``,
        ``allow_gpu_use``.
        Password and API key values must be pre-hashed by the caller.
        """
        _allowed = {
            "username",
            "email",
            "password_hash",
            "email_verified",
            "api_key_digest",
            "full_name",
            "affiliation",
            "position",
            "pi_name",
            "terms_agreed",
            "registration_status",
            "user_status",
            "approved_by",
            "approved_at",
            "deleted",
            "verification_resend_count",
            "verification_resend_at",
            "role",
            "allow_gpu_use",
        }
        values = {k: v for k, v in fields.items() if k in _allowed}
        if "is_admin" in fields:
            raise ValueError("is_admin was removed; update role instead")
        if "role" in values and values["role"] not in {"admin", "user", "guest"}:
            raise ValueError(f"Unsupported user role: {values['role']!r}")
        if not values:
            return
        stmt = sa.update(_users_table).where(_users_table.c.id == user_id).values(**values)
        with self.engine.begin() as conn:
            conn.execute(stmt)

    # -- API key helpers -----------------------------------------------------

    def generate_api_key(self, user_id: int) -> str:
        """Generate a new API key for *user_id*.

        Returns the *plaintext* key — store only its sha256 digest.  The
        caller is responsible for showing the plaintext once.
        """
        raw = "revodesign_" + os.urandom(32).hex()
        self.update_user(user_id, api_key_digest=hashlib.sha256(raw.encode("utf-8")).hexdigest())
        return raw

    def revoke_api_key(self, user_id: int) -> None:
        """Remove the API key for *user_id*."""
        self.update_user(user_id, api_key_digest=None)

    def validate_api_key(self, key: str) -> dict[str, Any] | None:
        """Return the user dict if *key* matches a stored API key, or ``None``."""
        if not key or not key.startswith("revodesign_"):
            return None
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        stmt = sa.select(_users_table).where(_users_table.c.api_key_digest == digest)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        # compare_digest is redundant for a 256-bit digest match but costs
        # nothing and keeps the comparison constant-time by form.
        if row is None or not hmac.compare_digest(row["api_key_digest"], digest):
            return None
        return dict(row)

    def increment_token_version(self, user_id: int) -> None:
        """Invalidate all existing bearer tokens for *user_id*."""
        stmt = (
            sa.update(_users_table)
            .where(_users_table.c.id == user_id)
            .values(token_version=_users_table.c.token_version + 1)
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    # -- read helpers --------------------------------------------------------

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        stmt = sa.select(_users_table).where(_users_table.c.id == user_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        return dict(row) if row else None

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        stmt = sa.select(_users_table).where(_users_table.c.username == username.strip())
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        stmt = sa.select(_users_table).where(_users_table.c.email == email.lower().strip())
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        return dict(row) if row else None

    # ponytail: full table scan — paginate or index if users exceed ~10k
    def list_users(self, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        """Return all users ordered by ``created_at`` descending.

        Soft-deleted users are excluded by default.
        """
        stmt = sa.select(_users_table).order_by(sa.desc(_users_table.c.created_at))
        if not include_deleted:
            stmt = stmt.where(_users_table.c.deleted == False)  # noqa: E712
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def user_count(self) -> int:
        stmt = sa.select(sa.func.count()).select_from(_users_table)
        with self.engine.connect() as conn:
            return conn.execute(stmt).scalar_one()

    def get_unnotified_registrations(self) -> list[dict[str, Any]]:
        """Return non-admin users who haven't been included in a digest yet."""
        stmt = (
            sa.select(_users_table)
            .where(
                _users_table.c.admin_notified == False,  # noqa: E712
                _users_table.c.role != "admin",
            )
            .order_by(sa.asc(_users_table.c.created_at))
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def mark_users_notified(self, user_ids: list[int]) -> None:
        """Mark a batch of users as included in an admin digest."""
        if not user_ids:
            return
        stmt = sa.update(_users_table).where(_users_table.c.id.in_(user_ids)).values(admin_notified=True)
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def unmark_users_notified(self, user_ids: list[int]) -> None:
        """Roll back the admin_notified flag so users appear in the next digest."""
        if not user_ids:
            return
        stmt = sa.update(_users_table).where(_users_table.c.id.in_(user_ids)).values(admin_notified=False)
        with self.engine.begin() as conn:
            conn.execute(stmt)

    # -- Runner access audit records ----------------------------------------

    @staticmethod
    def _effective_grant_clause(user_id: int, entitlement: str, now: float) -> Any:
        return sa.and_(
            _user_entitlements_table.c.user_id == user_id,
            _user_entitlements_table.c.entitlement == entitlement,
            _user_entitlements_table.c.revoked_at.is_(None),
            sa.or_(_user_entitlements_table.c.expires_at.is_(None), _user_entitlements_table.c.expires_at > now),
        )

    def grant_entitlement(
        self,
        user_id: int,
        entitlement: str,
        *,
        granted_by: int,
        basis: str,
        expires_at: float | None = None,
        note: str | None = None,
        source_request_id: int | None = None,
    ) -> dict[str, Any]:
        """Append a grant and atomically resolve a matching pending request."""
        now = time.time()
        if expires_at is not None and expires_at <= now:
            raise ValueError("Expiry must be in the future")
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                exists = conn.execute(
                    sa.select(_user_entitlements_table.c.id).where(
                        self._effective_grant_clause(user_id, entitlement, now)
                    )
                ).first()
                if exists:
                    raise ValueError("Entitlement is already active")
                pending_request = conn.execute(
                    sa.select(_access_requests_table).where(
                        _access_requests_table.c.user_id == user_id,
                        _access_requests_table.c.entitlement == entitlement,
                        _access_requests_table.c.status == "pending",
                    )
                ).mappings().first()
                linked_request_id = pending_request["id"] if pending_request else source_request_id
                result = conn.execute(
                    sa.insert(_user_entitlements_table).values(
                        user_id=user_id,
                        entitlement=entitlement,
                        granted_by=granted_by,
                        granted_at=now,
                        expires_at=expires_at,
                        basis=basis,
                        note=note,
                        source_request_id=linked_request_id,
                    )
                )
                if pending_request is not None:
                    conn.execute(
                        sa.update(_access_requests_table)
                        .where(
                            _access_requests_table.c.id == pending_request["id"],
                            _access_requests_table.c.status == "pending",
                        )
                        .values(
                            status="approved",
                            reviewed_by=granted_by,
                            reviewed_at=now,
                            review_note=note,
                        )
                    )
                grant_id = result.inserted_primary_key[0]
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_entitlement_grant(grant_id)  # type: ignore[return-value]

    def get_entitlement_grant(self, grant_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(_user_entitlements_table).where(_user_entitlements_table.c.id == grant_id)
            ).mappings().first()
        return dict(row) if row else None

    def revoke_entitlement(self, grant_id: int, *, revoked_by: int) -> bool:
        now = time.time()
        stmt = (
            sa.update(_user_entitlements_table)
            .where(
                _user_entitlements_table.c.id == grant_id,
                _user_entitlements_table.c.revoked_at.is_(None),
                sa.or_(_user_entitlements_table.c.expires_at.is_(None), _user_entitlements_table.c.expires_at > now),
            )
            .values(revoked_at=now, revoked_by=revoked_by)
        )
        with self.engine.begin() as conn:
            return bool(conn.execute(stmt).rowcount)

    def get_effective_entitlements(self, user_id: int | None, *, now: float | None = None) -> set[str]:
        if user_id is None:
            return set()
        effective_at = time.time() if now is None else now
        stmt = sa.select(_user_entitlements_table.c.entitlement).where(
            _user_entitlements_table.c.user_id == user_id,
            _user_entitlements_table.c.revoked_at.is_(None),
            sa.or_(
                _user_entitlements_table.c.expires_at.is_(None),
                _user_entitlements_table.c.expires_at > effective_at,
            ),
        )
        with self.engine.connect() as conn:
            return set(conn.execute(stmt).scalars())

    def has_entitlement(self, user_id: int, entitlement: str, *, now: float | None = None) -> bool:
        effective_at = time.time() if now is None else now
        stmt = sa.select(_user_entitlements_table.c.id).where(
            self._effective_grant_clause(user_id, entitlement, effective_at)
        )
        with self.engine.connect() as conn:
            return conn.execute(stmt).first() is not None

    def list_entitlement_grants(self, user_id: int) -> list[dict[str, Any]]:
        stmt = (
            sa.select(_user_entitlements_table)
            .where(_user_entitlements_table.c.user_id == user_id)
            .order_by(sa.desc(_user_entitlements_table.c.granted_at))
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings()]

    def create_access_requests(self, user_id: int, entitlements: tuple[str, ...], reason: str) -> list[dict[str, Any]]:
        """Create every missing, non-pending policy request atomically."""
        if not entitlements:
            raise ValueError("Runner access policy has no required entitlements")
        now = time.time()
        request_ids: list[int] = []
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                effective = set(
                    conn.execute(
                        sa.select(_user_entitlements_table.c.entitlement).where(
                            _user_entitlements_table.c.user_id == user_id,
                            _user_entitlements_table.c.entitlement.in_(entitlements),
                            _user_entitlements_table.c.revoked_at.is_(None),
                            sa.or_(
                                _user_entitlements_table.c.expires_at.is_(None),
                                _user_entitlements_table.c.expires_at > now,
                            ),
                        )
                    ).scalars()
                )
                missing = [entitlement for entitlement in entitlements if entitlement not in effective]
                if not missing:
                    raise ValueError("Runner access is already granted")
                pending = set(
                    conn.execute(
                        sa.select(_access_requests_table.c.entitlement).where(
                            _access_requests_table.c.user_id == user_id,
                            _access_requests_table.c.entitlement.in_(missing),
                            _access_requests_table.c.status == "pending",
                        )
                    ).scalars()
                )
                new_entitlements = [entitlement for entitlement in missing if entitlement not in pending]
                if not new_entitlements:
                    raise ValueError("Runner access request is already pending")
                for entitlement in new_entitlements:
                    result = conn.execute(
                        sa.insert(_access_requests_table).values(
                            user_id=user_id,
                            entitlement=entitlement,
                            status="pending",
                            reason=reason,
                            requested_at=now,
                        )
                    )
                    request_ids.append(result.inserted_primary_key[0])
                conn.commit()
            except IntegrityError as exc:
                conn.rollback()
                raise ValueError("Runner access request is already pending") from exc
            except Exception:
                conn.rollback()
                raise
        created = [self.get_access_request(request_id) for request_id in request_ids]
        return [request for request in created if request is not None]

    def create_access_request(self, user_id: int, entitlement: str, reason: str) -> dict[str, Any]:
        """Create one internal entitlement request (used by administrative integrations)."""
        return self.create_access_requests(user_id, (entitlement,), reason)[0]

    def get_access_request(self, request_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(_access_requests_table).where(_access_requests_table.c.id == request_id)
            ).mappings().first()
        return dict(row) if row else None

    def get_pending_access_requests(self, user_id: int) -> list[dict[str, Any]]:
        stmt = sa.select(_access_requests_table).where(
            _access_requests_table.c.user_id == user_id,
            _access_requests_table.c.status == "pending",
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings()]

    def list_access_requests(self, *, status: str | None = None) -> list[dict[str, Any]]:
        stmt = sa.select(
            _access_requests_table,
            _users_table.c.username,
            _users_table.c.full_name,
        ).join(_users_table, _users_table.c.id == _access_requests_table.c.user_id)
        if status is not None:
            stmt = stmt.where(_access_requests_table.c.status == status)
        stmt = stmt.order_by(sa.desc(_access_requests_table.c.requested_at))
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings()]

    def record_runner_access_event(
        self,
        user_id: int,
        policy_id: str,
        outcome: str,
        reason_code: str,
        *,
        task_type: str = "",
        runtime_family: str = "",
        ip_address: str | None = None,
        user_agent: str | None = None,
        auth_method: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        if outcome not in {"allowed", "denied", "suspended", "blocked", "cleared"}:
            raise ValueError("Invalid Runner access event outcome")
        event_type = {
            "allowed": "runner_access_allowed",
            "denied": "runner_access_denied",
            "suspended": "runner_access_suspended",
            "blocked": "runner_access_blocked_by_suspension",
            "cleared": "runner_access_suspension_cleared",
        }[outcome]
        now = time.time()
        with self.engine.begin() as conn:
            result = conn.execute(
                sa.insert(_runner_access_events_table).values(
                    user_id=user_id, policy_id=policy_id, event_type=event_type,
                    task_type=task_type[:64], runtime_family=runtime_family[:64], outcome=outcome,
                    reason_code=reason_code, occurred_at=now,
                    ip_address=(ip_address or "")[:45] or None, user_agent=(user_agent or "")[:512], auth_method=(auth_method or "")[:16] or None,
                    scope_type=scope_type, scope_id=(scope_id or "")[:64] or None,
                )
            )
            event_id = result.inserted_primary_key[0]
            row = conn.execute(sa.select(_runner_access_events_table).where(_runner_access_events_table.c.id == event_id)).mappings().first()
        return dict(row) if row else {}

    def list_runner_access_events(self, *, policy_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        stmt = sa.select(
            _runner_access_events_table,
            _users_table.c.username,
            _users_table.c.full_name,
        ).join(_users_table, _users_table.c.id == _runner_access_events_table.c.user_id)
        if policy_id:
            stmt = stmt.where(_runner_access_events_table.c.policy_id == policy_id)
        stmt = stmt.order_by(sa.desc(_runner_access_events_table.c.occurred_at)).limit(limit)
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings()]

    def reject_access_request(self, request_id: int, *, reviewed_by: int, review_note: str | None = None) -> bool:
        stmt = (
            sa.update(_access_requests_table)
            .where(_access_requests_table.c.id == request_id, _access_requests_table.c.status == "pending")
            .values(status="rejected", reviewed_by=reviewed_by, reviewed_at=time.time(), review_note=review_note)
        )
        with self.engine.begin() as conn:
            return bool(conn.execute(stmt).rowcount)

    def approve_access_request(
        self,
        request_id: int,
        *,
        reviewed_by: int,
        basis: str,
        expires_at: float | None = None,
        review_note: str | None = None,
    ) -> dict[str, Any]:
        """Atomically append a grant and approve its pending request."""
        now = time.time()
        if expires_at is not None and expires_at <= now:
            raise ValueError("Expiry must be in the future")
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                access_request = conn.execute(
                    sa.select(_access_requests_table).where(
                        _access_requests_table.c.id == request_id,
                        _access_requests_table.c.status == "pending",
                    )
                ).mappings().first()
                if access_request is None:
                    raise ValueError("Access request is not pending")
                if conn.execute(
                    sa.select(_user_entitlements_table.c.id).where(
                        self._effective_grant_clause(access_request["user_id"], access_request["entitlement"], now)
                    )
                ).first():
                    raise ValueError("Entitlement is already active")
                result = conn.execute(
                    sa.insert(_user_entitlements_table).values(
                        user_id=access_request["user_id"],
                        entitlement=access_request["entitlement"],
                        granted_by=reviewed_by,
                        granted_at=now,
                        expires_at=expires_at,
                        basis=basis,
                        note=review_note,
                        source_request_id=request_id,
                    )
                )
                conn.execute(
                    sa.update(_access_requests_table)
                    .where(_access_requests_table.c.id == request_id)
                    .values(status="approved", reviewed_by=reviewed_by, reviewed_at=now, review_note=review_note)
                )
                grant_id = result.inserted_primary_key[0]
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_entitlement_grant(grant_id)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Token serialiser
# ---------------------------------------------------------------------------

_SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "") or secrets.token_hex(32)

_TOKEN_MAX_AGE = _env_int("AUTH_TOKEN_MAX_AGE", 7 * 24 * 3600)  # 7 days

_serializer = URLSafeTimedSerializer(_SECRET_KEY, salt="revodesign-auth")


def generate_token(user_id: int, token_version: int = 0) -> str:
    """Return a signed, time-limited bearer token for *user_id*.

    The token is bound to *token_version* — incrementing the user's
    ``token_version`` column invalidates all previously issued tokens.
    """
    return _serializer.dumps({"uid": user_id, "ver": token_version})  # type: ignore[return-value]


def validate_token(token: str) -> dict | None:
    """Return the token payload (``{"uid": ..., "ver": ...}``) if valid, or ``None``.

    Callers MUST verify that ``payload["ver"]`` matches the user's current
    ``token_version`` — this function only checks the cryptographic signature
    and expiry.
    """
    try:
        payload = _serializer.loads(token, max_age=_TOKEN_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return None
    if "uid" not in payload:
        return None
    return payload


# ---------------------------------------------------------------------------
# Request-scoped current user
# ---------------------------------------------------------------------------


def _extract_bearer_token() -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    return auth_header[7:].strip()


def _is_account_blocked(user: dict[str, Any]) -> str | None:
    """Return an error message if *user* is not allowed to authenticate, or ``None``."""
    if user.get("deleted"):
        return "Account has been deleted"
    if user.get("user_status") == "banned":
        return "Account has been suspended"
    if user.get("user_status") != "active":
        return "Account is not yet active"
    # All active users must have a verified email address.  Admin-created
    # and admin-approved users get verify_email() called automatically in
    # the admin routes.
    if user.get("email_verified") is False:
        return "Email not verified"
    return None


def load_current_user() -> dict[str, Any] | None:
    """Resolve the authenticated user from the current request.

    Tries (in order):
    1. ``Authorization: Bearer <token>`` — web session token (time-limited).
    2. ``auth_token`` cookie — browser page navigations (same time-limited token).
    3. ``X-API-Key: <key>`` — long-lived API key (never expires).

    Returns the user dict or ``None``.
    """
    db: UserDatabase = current_app.config["user_db"]

    # 1. Bearer token (Authorization header — full privileges, CSRF-safe)
    token = _extract_bearer_token()
    if token:
        payload = validate_token(token)
        if payload is not None:
            user = db.get_user(payload["uid"])
            if (
                user is not None
                and _is_account_blocked(user) is None
                and payload.get("ver", 0) == user.get("token_version", 0)
            ):
                g.auth_method = "bearer"
                return user
    # 2. Cookie — browser page navigations after login (read-only; CSRF-prone)
    #    Guest accounts ARE permitted to use cookie-based web access.
    token = request.cookies.get("auth_token")
    if token:
        payload = validate_token(token)
        if payload is not None:
            user = db.get_user(payload["uid"])
            if (
                user is not None
                and _is_account_blocked(user) is None
                and payload.get("ver", 0) == user.get("token_version", 0)
            ):
                g.auth_method = "cookie"
                return user

    # 3. API key (programmatic access — restricted privileges)
    #    Guest accounts are not permitted to use API keys.
    api_key = request.headers.get("X-API-Key", "").strip()
    if api_key:
        user = db.validate_api_key(api_key)
        if user is not None and _is_account_blocked(user) is None and user.get("role") != "guest":
            g.auth_method = "api_key"
            return user

    return None


def require_web_login():
    """Return a 403 error if the current request was authenticated via API key.

    Call inside route handlers that need full web-login privileges
    (profile changes, admin actions, API key management).
    """
    if g.get("auth_method") == "api_key":
        return jsonify({"error": "API keys cannot perform this action — use web login"}), 403
    return None


def require_bearer_auth():
    """Return a 403 error if the current request was authenticated via cookie.

    CSRF gate: cookie-authenticated requests can be triggered cross-origin
    by top-level navigations.  State-changing endpoints must present a Bearer
    token in the ``Authorization`` header, which the browser same-origin
    policy prevents cross-origin requests from setting.
    """
    if g.get("auth_method") == "cookie":
        return jsonify({"error": "Bearer token required for this action"}), 403
    return None


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def login_required(f: Callable) -> Callable:
    """Decorator that requires a valid Bearer token.

    Browser requests (``Accept: text/html``) are redirected to the login
    page.  API requests receive a JSON error so JavaScript can handle it.
    """

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        user = load_current_user()
        if user is None:
            if "text/html" in request.headers.get("Accept", ""):
                return redirect(url_for("login_page", return_to=request.full_path.rstrip("?")))
            return (
                jsonify(
                    {
                        "error": "Authentication required",
                        "message": "Provide a valid Bearer token via the Authorization header",
                    }
                ),
                401,
            )
        g.current_user = user
        return f(*args, **kwargs)

    return decorated


def optional_user(f: Callable) -> Callable:
    """Decorator that resolves the current user if a token is present, but does not require one."""

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        user = load_current_user()
        g.current_user = user  # may be None
        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# Email delivery — Resend (optional pip extra) with SMTP fallback
# ---------------------------------------------------------------------------


def _smtp_config() -> dict[str, Any]:
    return {
        "host": _env_str("SMTP_HOST", "localhost"),
        "port": _env_int("SMTP_PORT", 587),
        "username": _env_str("SMTP_USERNAME", ""),
        "password": _env_str("SMTP_PASSWORD", ""),
        "use_tls": _env_bool("SMTP_USE_TLS", True),
        "from_addr": _env_str("SMTP_FROM_ADDR", "hello@revodesign.local"),
        "from_name": _env_str("SMTP_FROM_NAME", "REvoCompute Server"),
    }


def _use_resend() -> bool:
    """Return True if Resend is installed and configured."""
    return _HAS_RESEND and bool(_resend_key)


def _resend_from() -> str:
    name = _env_str("RESEND_FROM_NAME", "REvoCompute Server")
    addr = _env_str("RESEND_FROM_ADDR", "onboarding@resend.dev")
    return f"{name} <{addr}>"


def _send_email(*, to: str, subject: str, text: str, html_body: str | None = None) -> bool:
    """Send an email.  Uses Resend if available+configured, else SMTP.

    Returns ``True`` on success, ``False`` on failure (logged).
    """
    # Resend path (optional pip extra)
    if _use_resend():
        try:
            params: _resend_module.Emails.SendParams = {  # type: ignore[union-attr]
                "from": _resend_from(),
                "to": [to],
                "subject": subject,
                "text": text,
            }
            if html_body:
                params["html"] = html_body
            _resend_module.Emails.send(params)  # type: ignore[union-attr]
            return True
        except Exception:
            logging.exception("Resend failed for %s, trying SMTP fallback", to)

    # SMTP path (stdlib, always available)
    cfg = _smtp_config()
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{cfg['from_name']} <{cfg['from_addr']}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain"))
    if html_body:
        msg.attach(MIMEText(html_body, "html"))

    try:
        if cfg["use_tls"]:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=15)
        if cfg["username"] and cfg["password"]:
            server.login(cfg["username"], cfg["password"])
        server.send_message(msg)
        server.quit()
        return True
    except Exception:
        logging.exception("Failed to send email to %s", to)
        return False


# ---------------------------------------------------------------------------
# Shared HTML email wrapper — loaded from templates/email/base.html
# ---------------------------------------------------------------------------

_EMAIL_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "email", "base.html")
with open(_EMAIL_TEMPLATE_PATH, encoding="utf-8") as _f:
    _EMAIL_TEMPLATE = _f.read()


def _email_html(body_html: str) -> str:
    """Wrap *body_html* in the shared email layout."""
    # ponytail: str.replace, not .format() — body_html may contain curly braces
    # from f-string interpolation (e.g. CSS colours like #ffffff).
    return _EMAIL_TEMPLATE.replace("{body}", body_html)


# ---------------------------------------------------------------------------
# CAPTCHA — simple math challenge, signed token (5-min expiry)
# ---------------------------------------------------------------------------

_CAPTCHA_MAX_AGE = 300  # seconds

# ponytail: in-memory CAPTCHA-nonce store, used only when Redis is down.
# Per-process — not shared across gunicorn workers.  Bounded by CAPTCHA rate
# * 300 s (~3k entries at 10 req/s); purged on each fallback validation.
_used_captcha_nonces: dict[str, float] = {}


def _purge_expired_captcha_nonces(now: float) -> None:
    """Drop entries past their 5-min TTL so the set stays small."""
    stale = [n for n, exp in _used_captcha_nonces.items() if exp < now]
    for n in stale:
        del _used_captcha_nonces[n]


def generate_captcha() -> tuple[str, str]:
    """Return ``(question, token)`` for a math CAPTCHA challenge."""
    a = secrets.randbelow(10)
    b = secrets.randbelow(9) + 1  # avoid zero — makes the answer less trivial
    answer = a + b
    question = f"What is {a} + {b}?"
    jti = secrets.token_hex(16)
    token: str = _serializer.dumps({"answer": answer, "purpose": "captcha", "jti": jti})  # type: ignore[assignment]
    return question, token


def _consume_captcha_nonce(jti: str) -> bool:
    """Atomically consume a CAPTCHA nonce.  ``False`` = replay (already used).

    Redis-first: ``SET NX`` is atomic, so concurrent workers can never both
    consume the same nonce.  When Redis is unavailable the nonce is tracked
    in per-process memory instead (same guarantee, but only within one
    worker).
    """
    client = get_redis()
    if client is not None:
        try:
            return bool(client.set(f"captcha:{jti}", "1", nx=True, ex=_CAPTCHA_MAX_AGE))
        except Exception:
            pass  # Redis died — fall back to per-process memory
    now = time.time()
    _purge_expired_captcha_nonces(now)
    if jti in _used_captcha_nonces:
        return False  # replay
    _used_captcha_nonces[jti] = now + _CAPTCHA_MAX_AGE
    return True


def validate_captcha(token: str, answer: str) -> bool:
    """Validate a CAPTCHA token and answer.  Tokens expire after 5 minutes.

    Each token is single-use — the nonce (``jti``) is consumed once and
    rejected on replay.  The answer is checked before the nonce is consumed,
    so a wrong answer does not burn the token and the same challenge can be
    retried.
    """
    try:
        payload = _serializer.loads(token, max_age=_CAPTCHA_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return False
    if payload.get("purpose") != "captcha":
        return False
    try:
        if int(payload.get("answer", -1)) != int(answer.strip()):
            return False
    except (TypeError, ValueError):
        return False
    jti = payload.get("jti")
    if not jti:
        return True
    return _consume_captcha_nonce(jti)


def _public_base_url() -> str:
    """Return the public-facing base URL for email links.

    Always uses the configured ``SERVER_BASE_URL`` — never the request
    ``Host`` header, which an attacker can spoof to place valid tokens
    into links pointing at an attacker-controlled domain.
    """
    return _env_str("SERVER_BASE_URL", "http://localhost:8080").rstrip("/")


def send_verification_email(user: dict[str, Any]) -> bool:
    """Send an email-verification message to *user*.

    Returns ``True`` on success, ``False`` on failure (logged).
    """
    token = _serializer.dumps({"uid": user["id"], "purpose": "verify-email"})
    base_url = _public_base_url()
    verify_url = f"{base_url}/compute/user_verify?c={token}"

    text = (
        f"Hello {user['username']},\n"
        f"\n"
        f"Welcome to REvoCompute. Please confirm your email address to\n"
        f"activate your account.\n"
        f"\n"
        f"  {verify_url}\n"
        f"\n"
        f"This link expires in 2 days.\n"
        f"\n"
        f"If you did not create this account, you can ignore this message.\n"
        f"\n"
        f"— REvoCompute Server\n"
    )
    html_body = (
        f'<p>Hello {html.escape(user["username"])},</p>'
        f"<p>Welcome to REvoCompute. Please confirm your email address "
        f"to activate your account.</p>"
        f'<p style="margin:24px 0;">'
        f'<a href="{verify_url}" style="display:inline-block;padding:12px 24px;'
        f"background-color:#1a1a2e;color:#ffffff;text-decoration:none;"
        f'border-radius:6px;font-weight:600;">'
        f"Verify Email Address</a></p>"
        f"<p>Or copy this link:</p>"
        f'<p style="color:#6b7280;font-size:13px;word-break:break-all;">'
        f"{verify_url}</p>"
        f'<p style="color:#9ca3af;font-size:13px;">This link expires in 2 days.</p>'
        f"<p>If you did not create this account, you can ignore this message.</p>"
    )
    return _send_email(
        to=user["email"],
        subject="Verify your email — REvoCompute",
        text=text,
        html_body=_email_html(html_body),
    )


def validate_email_token(token: str) -> int | None:
    """Validate an email-verification token.  Returns *user_id* or ``None``."""
    try:
        payload = _serializer.loads(token, max_age=172800)  # 2-day expiry
    except (SignatureExpired, BadSignature):
        return None
    if payload.get("purpose") != "verify-email":
        return None
    return payload.get("uid")


# ---------------------------------------------------------------------------
# Password reset (same serializer, 1-hour expiry)
# ---------------------------------------------------------------------------


def send_password_reset_email(email: str, db: UserDatabase) -> bool:
    """Send a password-reset link to *email* if a user with that address exists.

    Returns ``True`` if an email was sent, ``False`` otherwise (no user, or
    delivery failure).  Does not reveal whether the email is registered.
    """
    user = db.get_user_by_email(email)
    if user is None:
        # Don't leak whether the email is registered — pretend success
        return True

    token = _serializer.dumps(
        {
            "uid": user["id"],
            "purpose": "reset-password",
            "ver": user.get("token_version", 0),
            "nonce": secrets.token_hex(16),
        }
    )
    base_url = _public_base_url()
    reset_url = f"{base_url}/compute/reset_password?c={token}"

    text = (
        f"Hello {user['username']},\n"
        f"\n"
        f"A password reset was requested for your account. Click the link\n"
        f"below to set a new password.\n"
        f"\n"
        f"  {reset_url}\n"
        f"\n"
        f"This link expires in 1 hour.\n"
        f"\n"
        f"If you did not request this, you can ignore this message — your\n"
        f"password will not change.\n"
        f"\n"
        f"— REvoCompute Server\n"
    )
    html_body = (
        f'<p>Hello {html.escape(user["username"])},</p>'
        f"<p>A password reset was requested for your account. "
        f"Click the button below to set a new password.</p>"
        f'<p style="margin:24px 0;">'
        f'<a href="{reset_url}" style="display:inline-block;padding:12px 24px;'
        f"background-color:#1a1a2e;color:#ffffff;text-decoration:none;"
        f'border-radius:6px;font-weight:600;">'
        f"Reset Password</a></p>"
        f"<p>Or copy this link:</p>"
        f'<p style="color:#6b7280;font-size:13px;word-break:break-all;">'
        f"{reset_url}</p>"
        f'<p style="color:#9ca3af;font-size:13px;">This link expires in 1 hour.</p>'
        f"<p>If you did not request this, you can ignore this message "
        f"&mdash; your password will not change.</p>"
    )
    return _send_email(
        to=email,
        subject="Reset your password — REvoCompute",
        text=text,
        html_body=_email_html(html_body),
    )


def send_approval_email(user: dict[str, Any]) -> bool:
    """Notify *user* that their registration has been approved."""
    base_url = _public_base_url()

    text = (
        f"Hello {user['username']},\n"
        f"\n"
        f"Your REvoCompute registration has been approved.\n"
        f"\n"
        f"  {base_url}/compute/login\n"
        f"\n"
        f"— REvoCompute Server\n"
    )
    html_body = (
        f'<p>Hello {html.escape(user["username"])},</p>'
        f"<p>Your REvoCompute registration has been approved.</p>"
        f'<p style="margin:24px 0;">'
        f'<a href="{base_url}/compute/login" style="display:inline-block;'
        f"padding:12px 24px;background-color:#1a1a2e;color:#ffffff;"
        f'text-decoration:none;border-radius:6px;font-weight:600;">'
        f"Log In</a></p>"
    )
    return _send_email(
        to=user["email"],
        subject="Registration approved — REvoCompute",
        text=text,
        html_body=_email_html(html_body),
    )


def send_rejection_email(user: dict[str, Any]) -> bool:
    """Notify *user* that their registration has been declined."""
    text = (
        f"Hello {user['username']},\n"
        f"\n"
        f"Your REvoCompute registration has been declined.\n"
        f"If you believe this is an error, please contact the\n"
        f"administrator who manages this server.\n"
        f"\n"
        f"— REvoCompute Server\n"
    )
    html_body = (
        f'<p>Hello {html.escape(user["username"])},</p>'
        f"<p>Your REvoCompute registration has been declined.</p>"
        f"<p>If you believe this is an error, please contact the "
        f"administrator who manages this server.</p>"
    )
    return _send_email(
        to=user["email"],
        subject="Registration update — REvoCompute",
        text=text,
        html_body=_email_html(html_body),
    )


def _admin_notify_emails() -> list[str]:
    """Return the list of admin email addresses to notify on registration."""
    raw = _env_str("ADMIN_NOTIFY_EMAIL", "")
    if not raw:
        return []
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def send_admin_digest() -> bool:
    """Send a digest email to admins listing all unnotified registrations.

    Reads ``ADMIN_NOTIFY_EMAIL`` (comma-separated).  Returns True if a
    digest was sent.
    """
    recipients = _admin_notify_emails()
    if not recipients:
        return False
    db = UserDatabase()
    new_users = db.get_unnotified_registrations()
    if not new_users:
        return False

    # Mark first, send second — prevents duplicate digests when multiple
    # gunicorn workers or celery processes race.  Unmark on failure so the
    # users appear in the next digest.
    user_ids = [u["id"] for u in new_users]
    db.mark_users_notified(user_ids)

    base_url = _env_str("SERVER_BASE_URL", "http://localhost:8080").rstrip("/")
    rows = []
    for u in new_users:
        created = datetime.fromtimestamp(u["created_at"]).strftime("%Y-%m-%d %H:%M") if u.get("created_at") else "?"
        rows.append(f"  {u['username']:<20} {u['email']:<32} {u.get('affiliation', '-') or '-':<24} {created}")

    text = (
        f"{len(new_users)} new registration(s) pending approval:\n\n"
        f"  {'Username':<20} {'Email':<32} {'Affiliation':<24} {'Registered'}\n"
        f"  {'-' * 20:<20} {'-' * 32:<32} {'-' * 24:<24} {'-' * 16}\n"
        + "\n".join(rows)
        + f"\n\n  Review: {base_url}/compute/user_control\n\n"
        f"— REvoCompute Server\n"
    )
    # Build HTML table rows
    html_rows = []
    for u in new_users:
        created = datetime.fromtimestamp(u["created_at"]).strftime("%Y-%m-%d %H:%M") if u.get("created_at") else "?"
        affil = u.get("affiliation") or "-"
        html_rows.append(
            f"<tr>"
            f'<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{html.escape(u["username"])}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{html.escape(u["email"])}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{html.escape(affil)}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{created}</td>'
            f"</tr>"
        )
    html_body = (
        f"<p>{len(new_users)} new registration(s) pending approval:</p>"
        f'<table style="width:100%;border-collapse:collapse;margin:16px 0;'
        f'font-size:14px;" cellpadding="0" cellspacing="0">'
        f'<thead><tr style="background-color:#f3f4f6;text-align:left;">'
        f'<th style="padding:8px 12px;">Username</th>'
        f'<th style="padding:8px 12px;">Email</th>'
        f'<th style="padding:8px 12px;">Affiliation</th>'
        f'<th style="padding:8px 12px;">Registered</th>'
        f"</tr></thead><tbody>" + "".join(html_rows) + "</tbody></table>"
        f'<p style="margin:24px 0;">'
        f'<a href="{base_url}/compute/user_control" style="display:inline-block;'
        f"padding:12px 24px;background-color:#1a1a2e;color:#ffffff;"
        f'text-decoration:none;border-radius:6px;font-weight:600;">'
        f"Review Registrations</a></p>"
    )
    any_sent = False
    subject = f"{len(new_users)} new registration(s) — REvoCompute"
    html_content = _email_html(html_body)
    for email in recipients:
        try:
            if _send_email(to=email, subject=subject, text=text, html_body=html_content):
                any_sent = True
        except Exception:
            logging.exception("Failed to send admin digest to %s", email)
    if not any_sent:
        db.unmark_users_notified(user_ids)
    return any_sent


def validate_reset_token(token: str, db: UserDatabase | None = None) -> int | None:
    """Validate a password-reset token.  Returns *user_id* or ``None``.

    When *db* is provided, also verifies that the user's current
    ``token_version`` matches the one embedded in the token, so
    incrementing ``token_version`` invalidates outstanding reset links.
    """
    try:
        payload = _serializer.loads(token, max_age=3600)  # 1-hour expiry
    except (SignatureExpired, BadSignature):
        return None
    if payload.get("purpose") != "reset-password":
        return None
    uid = payload.get("uid")
    if uid is None:
        return None
    if db is not None:
        user = db.get_user(uid)
        if user is None:
            return None
        if user.get("token_version", 0) != payload.get("ver"):
            return None
    return uid
