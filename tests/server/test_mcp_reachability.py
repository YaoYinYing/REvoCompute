# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The MCP capability must report an externally reachable endpoint, not a healthy listener.

The Home page offers "Connect an AI agent" only when the public capability says
the surface is reachable, so the capability is a *safety* projection: a
deployment whose switch is set but whose listener is missing, held, or broken
must report the surface absent rather than advertise an endpoint nothing answers.
And a healthy listener is not enough on its own — the endpoint Home advertises is
reached through the deployment gateway, so a listener that bound behind a missing
or stale gateway route is still not connectable from outside.

These tests hold the listener down on purpose, hold the *gateway route* down with
it, and assert the capability refuses to claim the surface in either case; then
they let a real listener bind against a route the gateway would serve, and assert
the capability appears only then.  The route is read from the deployment's own
state (``SERVER_DIR``), so a negative case is a real one: nothing about the
endpoint is inferred from a URL a caller supplied.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from conftest import _load_pssm_module

#: The route text the deployment controller writes for an opt-in — the same shape
#: the gateway includes, so a test route is one the gateway would really serve.
GATEWAY_ROUTE = (
    "location /k/ {\n"
    "    proxy_pass http://web:8081;\n"
    "    proxy_http_version 1.1;\n"
    '    proxy_set_header Connection "";\n'
    "}\n"
)


def _write_gateway_route(module, route_text: str | None) -> None:
    """Leave the deployment's gateway route in the state ``route_text`` describes.

    ``route_text`` is what the deployment host would have left under
    ``SERVER_DIR``: the controller writes it from ``MCP_ENABLED``.  ``None`` means
    no route was written — the state in which the listener has no public one.
    """
    route_dir = Path(module.CONFIG.server_dir) / "mcp-gateway"
    if route_text is None:
        if route_dir.is_dir():
            for stale in route_dir.iterdir():
                stale.unlink()
            route_dir.rmdir()
        return
    route_dir.mkdir(parents=True, exist_ok=True)
    (route_dir / "mcp.conf").write_text(route_text, encoding="utf-8")


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
        # Even with the gateway route present, no listener means nothing to reach.
        _write_gateway_route(module, GATEWAY_ROUTE)
        payload = module.app.test_client().get("/compute/api/mcp").get_json()
    finally:
        held.close()

    assert payload["enabled"] is False
    assert payload["endpoint"] is None
    # The operator gets an actionable reason, never a silent "disabled".
    assert payload["detail"]


def test_a_healthy_listener_behind_a_missing_gateway_route_is_not_advertised(monkeypatch, tmp_path):
    # The exact disagreement the review flagged: the companion listener really
    # bound and answers a real MCP initialize on loopback, but the deployment
    # gateway serves no /k/ route, so no agent host outside this container can
    # reach the endpoint Home would advertise. The public capability must reflect
    # the *external* endpoint, so it reports the surface absent rather than
    # offering a URL that is broken from the only place a client sits.
    from revocompute.mcp.asgi import _LISTENER, probe_surface

    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "MCP_ENABLED": "true", "MCP_PORT": "0"},
    )
    _write_gateway_route(module, None)

    payload = module.app.test_client().get("/compute/api/mcp").get_json()
    assert payload["enabled"] is False, "Home must not claim externally-connectable MCP while the gateway serves no route"
    assert payload["endpoint"] is None
    assert payload["detail"], "the operator gets a reason, not a silent off"

    # The listener is genuinely healthy: the reported reason is the gateway route,
    # not a broken listener. This is what makes the case a real disagreement rather
    # than a second listener-down test.
    ok, detail = probe_surface(_LISTENER["server"])
    assert ok, detail

    # The operator diagnostic agrees, over the public route a client uses: it is
    # served the real app, so the only thing missing is the gateway route.
    assert _operator_health(module) == 1


def test_the_capability_is_advertised_only_after_a_real_mcp_handshake(monkeypatch, tmp_path):
    # MCP_PORT=0 asks uvicorn for an ephemeral port, so the listener really binds,
    # mounts the transport, and answers without contending for a fixed port. With
    # the gateway route the controller would have written for the same opt-in, the
    # capability appears — and only then does Home offer the endpoint a client uses.
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "MCP_ENABLED": "true", "MCP_PORT": "0"},
    )
    _write_gateway_route(module, GATEWAY_ROUTE)
    client = module.app.test_client()
    assert client.get("/compute/api/mcp").get_json() == {"enabled": True, "endpoint": "/k/mcp", "detail": None}

    # And the readiness answer really came from the wire: the probe reports the
    # negotiated protocol and the server identity the surface advertises.
    from revocompute.mcp.asgi import _LISTENER, probe_surface

    ok, detail = probe_surface(_LISTENER["server"])
    assert ok, detail
    assert "protocol" in detail and "revocompute" in detail

    # The advertised endpoint is real end to end: the route can be withdrawn and
    # the capability follows it, so the answer tracks the route rather than the
    # listener or the switch that produced it.
    _write_gateway_route(module, None)
    assert client.get("/compute/api/mcp").get_json()["enabled"] is False


def test_a_stale_or_unrelated_route_file_is_not_a_served_route(monkeypatch, tmp_path):
    # A route file that exists is not a route the gateway serves: an emptied or
    # truncated file left by a partial write, or a file that declares something
    # else, must not be read as a live /k/ route. The listener is healthy in every
    # case, so only the route content decides.
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "MCP_ENABLED": "true", "MCP_PORT": "0"},
    )
    client = module.app.test_client()
    for route_text in ("", "# truncated by a partial write\n", "location /other/ { proxy_pass http://web:8081; }\n"):
        _write_gateway_route(module, route_text)
        payload = client.get("/compute/api/mcp").get_json()
        assert payload["enabled"] is False, route_text
        assert payload["endpoint"] is None
        assert payload["detail"]
    # The real route is the only thing that flips it.
    _write_gateway_route(module, GATEWAY_ROUTE)
    assert client.get("/compute/api/mcp").get_json()["enabled"] is True


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


def _operator_health(module) -> int:
    """Run the operator's ``mcp-status`` health walk against this application.

    The diagnostic consumes the deployment env file, so the test builds the same
    value object the deployment host would have, pointing ``SERVER_BASE_URL`` at a
    real server for the very app under test — never a stub that could agree with
    the capability read by construction.
    """
    from revocompute_ctl import mcp as controller_mcp
    from revocompute_ctl.env import EnvState

    server = make_server("127.0.0.1", 0, module.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        state = EnvState(
            str(Path(module.CONFIG.server_dir) / "deployment.env"),
            values={
                "SERVER_DIR": module.CONFIG.server_dir,
                "SERVER_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                "MCP_ENABLED": "true",
            },
        )
        return controller_mcp.mcp_health(state)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
