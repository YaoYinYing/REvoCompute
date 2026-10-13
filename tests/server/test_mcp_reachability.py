# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The MCP capability must report reachability, never the opt-in flag.

The Home page offers "Connect an AI agent" only when the public capability says
the surface is served, so the capability is a *safety* projection: a deployment
whose switch is set but whose listener is missing, held, or broken must report
the surface absent rather than advertise an endpoint nothing answers.  These
tests hold the listener down on purpose and assert the capability refuses to
claim it, and then let a real listener bind and assert the capability only
appears after the surface proves it answers a real MCP ``initialize``.
"""

from __future__ import annotations

import socket

import pytest

from conftest import _load_pssm_module


def _reserve_port() -> tuple[socket.socket, int]:
    """Bind a loopback port and hold it, so the listener's own bind must fail."""
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    return held, int(held.getsockname()[1])


# The held port makes uvicorn exit its listener thread by design; that SystemExit
# in a non-main thread is the behavior under test, so its pytest warning is noise.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_listener_that_cannot_bind_is_reported_unreachable_not_enabled(monkeypatch, tmp_path):
    # MCP_ENABLED=true is *intent*. Another process already holds the port the
    # listener would bind, so no surface is served. The capability must say so
    # rather than advertise /k/mcp, or the Home page offers a dead endpoint.
    held, port = _reserve_port()
    try:
        module = _load_pssm_module(
            monkeypatch,
            tmp_path,
            extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "MCP_ENABLED": "true", "MCP_PORT": str(port)},
        )
        payload = module.app.test_client().get("/compute/api/mcp").get_json()
    finally:
        held.close()

    assert payload["enabled"] is False
    assert payload["endpoint"] is None
    # The operator gets an actionable reason, never a silent "disabled".
    assert payload["detail"]


def test_the_capability_is_advertised_only_after_a_real_mcp_handshake(monkeypatch, tmp_path):
    # MCP_PORT=0 asks uvicorn for an ephemeral port, so the listener really binds,
    # mounts the transport, and answers without contending for a fixed port. The
    # capability appears only then, and the endpoint it names is the one a client
    # connects to.
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "MCP_ENABLED": "true", "MCP_PORT": "0"},
    )
    client = module.app.test_client()
    assert client.get("/compute/api/mcp").get_json() == {"enabled": True, "endpoint": "/k/mcp", "detail": None}

    # And the readiness answer really came from the wire: the probe reports the
    # negotiated protocol and the server identity the surface advertises.
    from revocompute.mcp.asgi import _LISTENER, probe_surface

    ok, detail = probe_surface(_LISTENER["server"])
    assert ok, detail
    assert "protocol" in detail and "revocompute" in detail


def test_a_set_switch_without_a_listener_is_not_advertised(monkeypatch, tmp_path):
    # The counterexample the flag-only implementation failed: the switch is set
    # but this process has no listener (a switch turned on without a restart).
    # Reading the flag would say "on"; reachability must say "no", with a reason.
    monkeypatch.setenv("MCP_ENABLED", "true")
    import revocompute.mcp.asgi as asgi

    # monkeypatch restores the process-global listener afterwards, so this case
    # never leaks into (or depends on) the order of the tests around it.
    monkeypatch.setitem(asgi._LISTENER, "server", None)
    monkeypatch.setitem(asgi._LISTENER, "error", "the optional 'mcp' extra is not installed")
    status = asgi.surface_status()
    assert status["enabled"] is False
    assert status["endpoint"] is None
    assert "mcp" in str(status["detail"]).lower()

    # With the switch off there is nothing to report and no reason to give.
    monkeypatch.setenv("MCP_ENABLED", "false")
    assert asgi.surface_status() == {"enabled": False, "endpoint": None, "detail": None}
