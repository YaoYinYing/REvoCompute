# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Owner-scoped gateway for an optional AtomWorks Studio editor service.

Studio keeps documents in memory and treats a session ID as its only access
control.  Exposing it directly would let any signed-in caller who guesses a
session ID read or edit another user's structure.  This module records the
caller-to-session binding and exposes the small, explicit route surface the
native editor actually uses; it is not a blanket reverse proxy.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from contextlib import contextmanager

import requests

DEFAULT_TTL_SECONDS = 2 * 60 * 60
MAX_PROXY_RESPONSE_BYTES = 64 * 1024 * 1024
PROXY_TIMEOUT_SECONDS = 60

_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
_SESSION_SUBPATH = re.compile(r"^/api/sessions/[A-Za-z0-9_-]{20,64}(?:/[A-Za-z0-9_/{}-]*)?$")
#: Read-only routes the editor shell itself uses.  They carry no private
#: document, so authentication is required but session ownership is not.
_PUBLIC_ROUTES = (
    re.compile(r"^/api/(?:health|ready|schema)$"),
    re.compile(r"^/api/examples(?:/[A-Za-z0-9_-]+)?(?:/cif)?$"),
    re.compile(r"^/api/import/inspect$"),
)


class AtomWorksSessionStore:
    """Expiring user-to-session bindings, independent of Studio's process state."""

    def __init__(self, path: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.path = os.path.abspath(path)
        self.ttl_seconds = ttl_seconds
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS atomworks_sessions ("
                "session_id TEXT PRIMARY KEY, "
                "user_id INTEGER NOT NULL, "
                "created_at REAL NOT NULL, "
                "expires_at REAL NOT NULL)"
            )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record(self, session_id: str, *, user_id: int) -> None:
        if not _SESSION_ID.fullmatch(session_id):
            return
        now = time.time()
        with self._connection() as connection:
            connection.execute("DELETE FROM atomworks_sessions WHERE expires_at <= ?", (now,))
            connection.execute(
                "INSERT OR REPLACE INTO atomworks_sessions "
                "(session_id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (session_id, int(user_id), now, now + self.ttl_seconds),
            )

    def owns(self, session_id: str, *, user_id: int, now: float | None = None) -> bool:
        if not _SESSION_ID.fullmatch(session_id):
            return False
        moment = time.time() if now is None else now
        with self._connection() as connection:
            row = connection.execute(
                "SELECT user_id, expires_at FROM atomworks_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None or row[1] <= moment:
                if row is not None:
                    connection.execute("DELETE FROM atomworks_sessions WHERE session_id = ?", (session_id,))
                return False
            return int(row[0]) == int(user_id)

    def forget(self, session_id: str) -> None:
        if not _SESSION_ID.fullmatch(session_id):
            return
        with self._connection() as connection:
            connection.execute("DELETE FROM atomworks_sessions WHERE session_id = ?", (session_id,))


def route_allowed(method: str, path: str) -> bool:
    """Whether the gateway forwards this method and upstream path at all."""
    if method == "POST" and path == "/api/sessions":
        return True
    if _SESSION_SUBPATH.fullmatch(path):
        return True
    if method == "GET" and any(pattern.fullmatch(path) for pattern in _PUBLIC_ROUTES):
        return True
    if method == "POST" and path == "/api/import/inspect":
        return True
    return False


def session_id_from_path(path: str) -> str | None:
    match = re.match(r"^/api/sessions/([A-Za-z0-9_-]{20,64})(?:/|$)", path)
    return match.group(1) if match else None


class AtomWorksProxyError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def forward(
    base_url: str,
    method: str,
    path: str,
    *,
    query: str = "",
    body: bytes | None = None,
    content_type: str | None = None,
    accept: str | None = None,
    timeout: int = PROXY_TIMEOUT_SECONDS,
) -> tuple[int, str, bytes, dict[str, str]]:
    """Forward one allowlisted request to the pinned Studio service.

    Only the body, content type and a bounded set of response headers travel.
    Host, cookies, authorization, and every client-supplied forwarding header
    stay on this side of the boundary.
    """
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url = f"{url}?{query}"
    headers = {"Accept": accept or "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    try:
        response = requests.request(
            method,
            url,
            data=body,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise AtomWorksProxyError(503, "The AtomWorks Studio service is unavailable.") from exc
    content = response.content
    if len(content) > MAX_PROXY_RESPONSE_BYTES:
        raise AtomWorksProxyError(502, "The AtomWorks Studio response exceeded the gateway limit.")
    passthrough: dict[str, str] = {}
    for name in ("Content-Type", "Content-Disposition", "Cache-Control", "ETag"):
        value = response.headers.get(name)
        if value:
            passthrough[name] = value
    return response.status_code, response.headers.get("Content-Type", "application/octet-stream"), content, passthrough
