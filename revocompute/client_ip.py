# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Client-IP resolution shared by the rate limiter and the app.

Lives in its own leaf module so the limiter never has to import
``revocompute.app`` at request time — that would re-execute the application
module whenever it is absent from ``sys.modules`` (which the test loader
arranges deliberately), wiping the discovered plugin graph mid-request.
"""

from __future__ import annotations

import ipaddress
import os
from typing import Any

from flask import request

# Parsed at import time — a tuple of header names to try for client IP.
# ``X-Real-IP`` leads because both shipped proxies (the compose gateway and the
# documented host nginx site) overwrite it with the socket peer, whereas
# ``X-Forwarded-For`` is appended to and keeps the client-supplied element.
CLIENT_IP_HEADERS = tuple(
    h.strip().strip("'\"")
    for h in os.environ.get("CLIENT_IP_HEADERS", "X-Real-IP, X-Forwarded-For").split(",")
    if h.strip()
)
CLIENT_COUNTRY_HEADER = os.environ.get("CLIENT_COUNTRY_HEADER", "").strip().strip("'\"") or None
# Peers whose forwarding headers are believed; matches the gunicorn
# `--forwarded-allow-ips` trust set (loopback and the compose bridge).  A direct
# caller outside these ranges cannot mint a fresh rate-limit identity by
# rotating a header.
TRUSTED_PROXY_NETS: tuple[Any, ...] = tuple(
    ipaddress.ip_network(entry.strip(), strict=False)
    for entry in (os.environ.get("TRUSTED_PROXY_IPS") or "127.0.0.1,172.16.0.0/12").split(",")
    if entry.strip()
)


def client_ip() -> str | None:
    """Return the best-guess client IP from the configured forwarding headers."""
    for header in CLIENT_IP_HEADERS:
        value = request.headers.get(header, "").split(",")[0].strip()
        if value:
            return value
    remote = request.remote_addr
    return remote if remote else None


def peer_is_trusted_proxy(remote: str | None) -> bool:
    if not remote:
        return False
    try:
        address = ipaddress.ip_address(remote)
    except ValueError:
        return False
    return any(address in net for net in TRUSTED_PROXY_NETS)


def trusted_client_ip() -> str | None:
    """Return the client IP, trusting forwarding headers only from a known peer.

    A forwarding header is request-supplied data, so it is honored only when
    the connection actually came from a configured proxy (``TRUSTED_PROXY_IPS``).
    Otherwise a direct caller could forge a fresh ``X-Real-IP`` per request and
    mint a fresh rate-limit identity every time.  Falls back to the socket peer.
    """
    remote = request.remote_addr
    if peer_is_trusted_proxy(remote):
        return client_ip() or remote
    return remote if remote else None


def client_country() -> str | None:
    """Return the client country from ``CLIENT_COUNTRY_HEADER`` if configured."""
    if CLIENT_COUNTRY_HEADER is None:
        return None
    value = request.headers.get(CLIENT_COUNTRY_HEADER, "").strip()
    return value if value else None
