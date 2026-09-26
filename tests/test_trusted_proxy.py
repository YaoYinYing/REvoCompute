# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Rate-limit identity must not be attacker-chosen.

A forwarding header is request-supplied data.  If it is trusted
unconditionally, a caller rotating ``X-Real-IP`` mints a fresh rate-limit
identity per request and every per-IP limit in the system stops binding.
"""

from __future__ import annotations

import json

from conftest import _load_pssm_module


def test_rotating_a_forwarding_header_does_not_refresh_the_rate_limit(monkeypatch, tmp_path):
    """A direct caller (not a trusted proxy) cannot rotate its limiter key."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    payload = json.dumps({"username": "nonexistent", "password": "wrong"})
    for i in range(6):
        resp = client.post(
            "/compute/api/auth/login",
            headers={"Content-Type": "application/json", "X-Real-IP": f"203.0.113.{i}"},
            data=payload,
            environ_base={"REMOTE_ADDR": "198.51.100.7"},
        )
        expected = 429 if i == 5 else 401
        assert resp.status_code == expected, f"request {i}: {resp.status_code} != {expected}"


def test_a_header_from_a_trusted_proxy_peer_is_honored(monkeypatch, tmp_path):
    """Behind the gateway, the forwarded client address still keys the limit."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    payload = json.dumps({"username": "nonexistent", "password": "wrong"})
    for i in range(6):
        resp = client.post(
            "/compute/api/auth/login",
            headers={"Content-Type": "application/json", "X-Real-IP": "203.0.113.50"},
            data=payload,
            environ_base={"REMOTE_ADDR": "172.18.0.5"},  # compose bridge
        )
        expected = 429 if i == 5 else 401
        assert resp.status_code == expected, f"request {i}: {resp.status_code} != {expected}"
