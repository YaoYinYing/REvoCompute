# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Rate-limit identity must not be attacker-chosen.

A forwarding header is request-supplied data.  If it is trusted
unconditionally, a caller rotating one mints a fresh rate-limit identity per
request and every per-IP limit in the system stops binding.  Both forwarded
headers are rotated here so the property does not depend on which one the
configured header order tries first.
"""

from __future__ import annotations

import json

import pytest
from conftest import _load_pssm_module

# The compose default and the source default, so neither ordering is assumed.
_HEADER_ORDERS = ("X-Real-IP,X-Forwarded-For", "X-Forwarded-For,X-Real-IP")


@pytest.mark.parametrize("header_order", _HEADER_ORDERS)
def test_rotating_a_forwarding_header_does_not_refresh_the_rate_limit(monkeypatch, tmp_path, header_order):
    """A direct caller (not a trusted proxy) cannot rotate its limiter key."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "CLIENT_IP_HEADERS": header_order},
    )
    client = module.app.test_client()
    payload = json.dumps({"username": "nonexistent", "password": "wrong"})
    for i in range(6):
        resp = client.post(
            "/compute/api/auth/login",
            headers={
                "Content-Type": "application/json",
                "X-Real-IP": f"203.0.113.{i}",
                "X-Forwarded-For": f"198.51.100.{i}",
            },
            data=payload,
            environ_base={"REMOTE_ADDR": "192.0.2.7"},
        )
        expected = 429 if i == 5 else 401
        assert resp.status_code == expected, f"request {i}: {resp.status_code} != {expected}"


@pytest.mark.parametrize("header_order", _HEADER_ORDERS)
def test_a_header_from_a_trusted_proxy_peer_is_honored(monkeypatch, tmp_path, header_order):
    """Behind the gateway, the forwarded client address still keys the limit."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "CLIENT_IP_HEADERS": header_order},
    )
    client = module.app.test_client()
    payload = json.dumps({"username": "nonexistent", "password": "wrong"})
    for i in range(6):
        resp = client.post(
            "/compute/api/auth/login",
            headers={
                "Content-Type": "application/json",
                "X-Real-IP": "203.0.113.50",
                "X-Forwarded-For": "203.0.113.50",
            },
            data=payload,
            environ_base={"REMOTE_ADDR": "172.18.0.5"},  # compose bridge
        )
        expected = 429 if i == 5 else 401
        assert resp.status_code == expected, f"request {i}: {resp.status_code} != {expected}"


def test_a_rotated_header_from_a_trusted_peer_still_keys_the_forwarded_client(monkeypatch, tmp_path):
    """A trusted proxy's forwarded address is honored — including a rotation of
    the *appended* header, which is the one a client can influence through a
    correctly configured gateway."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    payload = json.dumps({"username": "nonexistent", "password": "wrong"})
    # Same forwarded client each time (as a real proxy would report), rotating
    # only the client-supplied trailing element the proxy appended to.
    for i in range(6):
        resp = client.post(
            "/compute/api/auth/login",
            headers={
                "Content-Type": "application/json",
                "X-Real-IP": "203.0.113.60",
                "X-Forwarded-For": f"203.0.113.60, 10.0.0.{i}",
            },
            data=payload,
            environ_base={"REMOTE_ADDR": "172.18.0.5"},
        )
        expected = 429 if i == 5 else 401
        assert resp.status_code == expected, f"request {i}: {resp.status_code} != {expected}"
