# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Shared lazy Redis client for distributed rate limiting and CAPTCHA nonces.

Redis is an optional accelerator: when it is unavailable, callers fall back
to per-process in-memory state.  That fallback is documented as per-worker,
not distributed — a CAPTCHA token or rate-limit counter is local to one
gunicorn worker rather than shared across the fleet.  Availability beats
strictness: a Redis outage degrades, never breaks, the endpoints.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

import redis

_LOGGER = logging.getLogger(__name__)

_SOCKET_TIMEOUT = 1  # seconds — fail fast so requests don't pile up on a dead Redis


def redact_url(url: str) -> str:
    """Drop the password from a broker URL while keeping user, host, and port."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if not host:
            # Host-less forms (unix://) carry no network location to report.
            return url
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        # redis-py accepts the "redis://user:password@host" shorthand where the
        # userinfo is a password; a userinfo with no ":" therefore redacts.
        user = f"{parts.username}:" if parts.password is not None else ""
        return urlunsplit((parts.scheme, f"{user}@{host}", parts.path, parts.query, parts.fragment))
    except ValueError:
        return "<invalid broker URL>"


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis | None:
    """Return a Redis client for ``REDIS_URL``, or ``None`` if unavailable.

    The client (or the ``None`` failure) is cached for the process lifetime
    and the warning is logged once per process.  Call ``get_redis.cache_clear()``
    (e.g. after restarting Redis, or in tests) to re-probe.
    """
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client = redis.Redis.from_url(url, socket_timeout=_SOCKET_TIMEOUT, socket_connect_timeout=_SOCKET_TIMEOUT)
    try:
        client.ping()
    except Exception:
        # Never log the URL itself — it may carry the broker password.
        _LOGGER.warning(
            "Redis unavailable at %s — rate limiting and CAPTCHA fall back to per-process state", redact_url(url)
        )
        return None
    return client
