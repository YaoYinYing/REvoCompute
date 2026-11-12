# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Signed, revocable, artifact-scoped download links.

A link is a bearer credential for one published artifact: it authorizes reading
that artifact's bytes until it expires or is revoked, and nothing else.  The
token carries the grant identity and its binding, but the binding is only
advisory -- every request rechecks the stored grant and the artifact's current
publication, so a signed token never outranks the Server's own state.

Tokens are signed with the same primitive sessions use (``itsdangerous``) under
a distinct salt and an optional dedicated secret.  A link token cannot be
validated as a session token or vice versa.  Rotating ``ARTIFACT_LINK_SECRET``
(or ``AUTH_SECRET_KEY`` when it is unset) invalidates every outstanding link;
revoking a grant invalidates exactly one.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from revocompute.auth import artifact_link_serializer

SCOPE = "read-bytes"
PURPOSE = "artifact-download"

#: The bearer retrieval path prefix.  Its token segment is the only secret this
#: module ever puts in a URL, and it is redacted from access-log paths.
_REDACTED_DOWNLOAD_PATH = "/compute/api/artifact-downloads/[redacted]"
_DOWNLOAD_PREFIX = "/compute/api/artifact-downloads/"

_DEFAULT_TTL_SECONDS = 60 * 60
_MAX_TTL_SECONDS = 24 * 60 * 60
_JTI = re.compile(r"[A-Za-z0-9_-]{16,64}\Z")


def _env_seconds(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def max_ttl_seconds() -> int:
    """The hard ceiling a caller cannot request past."""
    return _env_seconds("ARTIFACT_LINK_MAX_TTL_SECONDS", _MAX_TTL_SECONDS)


def default_ttl_seconds() -> int:
    """The TTL a request that names none receives, bounded by the hard ceiling."""
    return min(_env_seconds("ARTIFACT_LINK_TTL_SECONDS", _DEFAULT_TTL_SECONDS), max_ttl_seconds())


def _jti_hash(jti: str) -> str:
    return hashlib.sha256(jti.encode("utf-8")).hexdigest()


def _serializer() -> URLSafeTimedSerializer:
    # The import is a function-local lookup so a test or deployment that rotates
    # the secret sees the serializer built from the current module state.
    return artifact_link_serializer


def issue_download_link(
    *,
    task_id: str,
    artifact: dict[str, Any],
    owner_user_id: int,
    ttl_seconds: int | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Create one signed link bound to the artifact's verified publication identity.

    ``artifact`` must be the resolved manifest entry (``path``, ``sha256``,
    ``size``), not an unverified manifest line: the link promises those bytes.
    """
    ceiling = max_ttl_seconds()
    requested = default_ttl_seconds() if ttl_seconds is None else ttl_seconds
    if isinstance(requested, bool) or not isinstance(requested, int) or not 1 <= requested <= ceiling:
        raise ValueError(f"ttl_seconds must be an integer between 1 and {ceiling}")
    issued_at = time.time() if now is None else now
    expires_at = issued_at + requested
    jti = secrets.token_urlsafe(24)
    payload = {
        "purpose": PURPOSE,
        "scope": SCOPE,
        "jti": jti,
        "task": task_id,
        "path": str(artifact["path"]),
        "sha256": str(artifact["sha256"]),
        "size": int(artifact["size"]),
        "uid": int(owner_user_id),
        "exp": int(expires_at),
    }
    token = _serializer().dumps(payload)
    return {
        "id": jti,
        "token_id_hash": _jti_hash(jti),
        "token": token,
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "expires_at_epoch": expires_at,
        "issued_at_epoch": issued_at,
        "ttl_seconds": requested,
        "payload": payload,
    }


def validate_download_token(token: str, *, now: float | None = None) -> dict[str, Any] | None:
    """Return the signed payload of a well-formed, unexpired token, or ``None``.

    Signature and the hard maximum age are checked by ``itsdangerous``; the
    explicit ``exp`` claim is the per-link hard expiry.  Nothing about the token
    is logged or echoed on failure.
    """
    if not isinstance(token, str) or not token:
        return None
    try:
        payload = _serializer().loads(token, max_age=max_ttl_seconds())
    except (BadSignature, SignatureExpired):
        return None
    except Exception:  # noqa: BLE001 - a malformed token is indistinguishable from an invalid one
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("purpose") != PURPOSE or payload.get("scope") != SCOPE:
        return None
    jti = payload.get("jti")
    if not isinstance(jti, str) or not _JTI.fullmatch(jti):
        return None
    for key in ("task", "path", "sha256"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            return None
    if not isinstance(payload.get("size"), int) or isinstance(payload.get("size"), bool) or payload["size"] < 0:
        return None
    if not isinstance(payload.get("uid"), int) or isinstance(payload.get("uid"), bool):
        return None
    expires = payload.get("exp")
    if not isinstance(expires, int) or isinstance(expires, bool):
        return None
    current = time.time() if now is None else now
    if expires <= current:
        return None
    return payload


def token_id_hash(jti: str) -> str:
    """The stored identity of a grant: the token's unique id, hashed."""
    return _jti_hash(jti)


def redacted_request_path(path: str) -> str:
    """A log-safe form of a request path that may carry a bearer token."""
    if urlsplit(path).path.startswith(_DOWNLOAD_PREFIX):
        return _REDACTED_DOWNLOAD_PATH
    return path
