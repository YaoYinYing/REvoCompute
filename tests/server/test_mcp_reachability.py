# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The MCP capability must report the facts it observed, and advertise the endpoint only on reach.

The Home page offers "Connect an AI agent" only when the public capability says
the surface is operational, so the capability is a *safety* projection: a
deployment whose switch is set but whose listener is missing, held, or broken
must report the surface not operational rather than advertise an endpoint
nothing answers.  And a healthy listener, or a route file on disk, is not
reachable on its own — the endpoint Home advertises is reached through the
deployment gateway, so a listener that bound behind a missing, stale, or
unreloaded gateway route is still not connectable from outside.

These tests drive the capability through the real application and hold each fact
down in turn, asserting the capability reports it and refuses to advertise the
endpoint.  The facts are real: the listener is a real bound socket, the route is
a real file under the deployment's own ``SERVER_DIR``, and the reach is a real
HTTP call to the deployment's own base URL.  Nothing about the endpoint is
inferred from a URL a caller supplied, and a failure's ``detail`` never carries a
filesystem error string.
"""

from __future__ import annotations

import http.server
import json
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

#: The facts every capability document carries, so a case states what it observed
#: rather than re-deriving the shape.
CAPABILITY_KEYS = {
    "listener_ready",
    "route_configured",
    "gateway_verified",
    "operational",
    "enabled",
    "endpoint",
    "detail",
}


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


class _PublicEdge:
    """A stand-in for the deployment's own public endpoint.

    The capability reaches the deployment's *own* base URL, so a case needs a
    server that either answers a real MCP ``initialize`` (the gateway is serving
    the surface) or answers something else (a stale gateway, a down upstream).
    It is the deployment's edge as this host sees it, never a caller-chosen
    destination.
    """

    def __init__(self, *, answer_init: bool) -> None:
        self.answer_init = answer_init
        self.posts: list[dict] = []
        handler = self._handler()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handler(self):
        edge = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server's own spelling
                length = int(self.headers.get("Content-Length", 0))
                edge.posts.append({"path": self.path, "body": json.loads(self.rfile.read(length).decode("utf-8"))})
                if not edge.answer_init:
                    # A gateway that is up but serving no /k/ route, or an upstream
                    # that is down: the path is not MCP here.
                    self.send_error(404)
                    return
                payload = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "revocompute", "version": "1.0.0"},
                        },
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args) -> None:  # noqa: D401 - silence the test server
                return

        return _Handler

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _reserve_port() -> tuple[socket.socket, int]:
    """Bind a loopback port and hold it, so the listener's own bind must fail."""
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    return held, int(held.getsockname()[1])


def _mcp_vars(edge: _PublicEdge) -> dict[str, str]:
    """The opt-in environment a deployment behind ``edge`` would carry."""
    return {
        "RUNNER_UID": "1234",
        "RUNNER_GID": "5678",
        "MCP_ENABLED": "true",
        "MCP_PORT": "0",
        "SERVER_BASE_URL": edge.base_url,
        "MCP_GATEWAY_PROBE": "true",
    }


# The held port makes uvicorn exit its listener thread by design; that SystemExit
# in a non-main thread is the behavior under test, so its pytest warning is noise.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_listener_that_cannot_bind_is_reported_not_ready(monkeypatch, tmp_path):
    # MCP_ENABLED=true is *intent*. Another process already holds the port the
    # listener would bind, so no surface is served. The capability must say so
    # rather than advertise an endpoint, even with the route and the edge present.
    held, port = _reserve_port()
    edge = _PublicEdge(answer_init=True)
    try:
        env = _mcp_vars(edge)
        env["MCP_PORT"] = str(port)
        module = _load_pssm_module(monkeypatch, tmp_path, extra_env=env)
        # Even with the gateway route present and the public edge answering, no
        # listener means nothing to reach.
        _write_gateway_route(module, GATEWAY_ROUTE)
        payload = module.app.test_client().get("/compute/api/mcp").get_json()
    finally:
        held.close()
        edge.close()

    assert payload["listener_ready"] is False
    assert payload["route_configured"] is True
    assert payload["gateway_verified"] is None
    assert payload["operational"] is False
    assert payload["enabled"] is False
    assert payload["endpoint"] is None
    # The operator gets a fixed, role-based reason, never a silent "disabled".
    assert payload["detail"]


def test_a_healthy_listener_behind_a_missing_gateway_route_is_not_advertised(monkeypatch, tmp_path):
    # The exact disagreement the review flagged: the companion listener really
    # bound and answers a real MCP initialize on loopback, but the deployment
    # gateway serves no /k/ route, so no agent host outside this container can
    # reach the endpoint Home would advertise. A listener plus a route file is the
    # only thing this deployment has; the capability must report that, not claim
    # the surface is operational.
    from revocompute.mcp.asgi import _LISTENER, probe_surface

    edge = _PublicEdge(answer_init=False)
    try:
        module = _load_pssm_module(monkeypatch, tmp_path, extra_env=_mcp_vars(edge))
        _write_gateway_route(module, None)

        payload = module.app.test_client().get("/compute/api/mcp").get_json()
        assert payload["listener_ready"] is True, "the listener is genuinely healthy"
        assert payload["route_configured"] is False
        assert payload["operational"] is False, "Home must not claim external MCP while the gateway serves no route"
        assert payload["enabled"] is False
        assert payload["endpoint"] is None
        assert payload["detail"], "the operator gets a reason, not a silent off"

        # The listener really answers, so the reported facts are distinguishable:
        # listener_ready True with route_configured False is the disagreement.
        ok, detail = probe_surface(_LISTENER["server"])
        assert ok, detail

        # The operator diagnostic agrees, over the public route a client uses.
        assert _operator_health(module) == 1
    finally:
        edge.close()


def test_the_capability_is_advertised_only_after_a_real_public_handshake(monkeypatch, tmp_path):
    # MCP_PORT=0 asks uvicorn for an ephemeral port, so the listener really binds.
    # The public edge answers the initialize the capability sends it, so the
    # deployment's own endpoint is verified and only then does Home offer it.
    from revocompute.mcp.asgi import _LISTENER, probe_surface

    edge = _PublicEdge(answer_init=True)
    try:
        module = _load_pssm_module(monkeypatch, tmp_path, extra_env=_mcp_vars(edge))
        _write_gateway_route(module, GATEWAY_ROUTE)
        client = module.app.test_client()
        payload = client.get("/compute/api/mcp").get_json()
        assert set(payload) == CAPABILITY_KEYS
        assert payload == {
            "listener_ready": True,
            "route_configured": True,
            "gateway_verified": True,
            "operational": True,
            "enabled": True,
            "endpoint": f"{edge.base_url}/k/mcp",
            "detail": None,
        }

        # The reach really happened over HTTP, at the endpoint a client uses.
        assert edge.posts and edge.posts[0]["path"] == "/k/mcp"
        assert edge.posts[0]["body"]["method"] == "initialize"

        # And the local readiness answer really came from the wire too.
        ok, detail = probe_surface(_LISTENER["server"])
        assert ok, detail
        assert "protocol" in detail and "revocompute" in detail
    finally:
        edge.close()


def test_a_stale_or_unrelated_route_file_is_not_configured(monkeypatch, tmp_path):
    # A route file that exists is not necessarily a route the gateway serves: an
    # emptied or truncated file left by a partial write, or a file that declares
    # something else, must not be read as a live /k/ route. Here the two facts
    # disagree the other way — the endpoint really answers, but the state on disk
    # declares no /k/ — and the capability keeps them separate: the route fact is
    # reported faithfully and the endpoint is advertised on the observed reach
    # alone, never on the file.
    edge = _PublicEdge(answer_init=True)
    try:
        module = _load_pssm_module(monkeypatch, tmp_path, extra_env=_mcp_vars(edge))
        client = module.app.test_client()
        for route_text in ("", "# truncated by a partial write\n", "location /other/ { proxy_pass http://web:8081; }\n"):
            _write_gateway_route(module, route_text)
            payload = client.get("/compute/api/mcp").get_json()
            assert payload["route_configured"] is False, route_text
            assert payload["gateway_verified"] is True, route_text
            assert payload["operational"] is True, route_text
            assert payload["enabled"] is True, route_text
            assert payload["endpoint"] == f"{edge.base_url}/k/mcp"
        # The real route is configured, and the reach is what advertises it.
        _write_gateway_route(module, GATEWAY_ROUTE)
        payload = client.get("/compute/api/mcp").get_json()
        assert payload["route_configured"] is True
        assert payload["enabled"] is True
    finally:
        edge.close()


def test_a_configured_route_whose_gateway_does_not_answer_is_not_operational(monkeypatch, tmp_path):
    # The core P1 counterexample: the route file declares /k/ and the listener is
    # healthy, but nothing answers MCP at the public endpoint (a gateway that never
    # reloaded after the route was written, a stale config, or a down upstream).
    # A route file is not proof the external gateway serves MCP, so the surface
    # must not be advertised.
    edge = _PublicEdge(answer_init=False)
    try:
        module = _load_pssm_module(monkeypatch, tmp_path, extra_env=_mcp_vars(edge))
        _write_gateway_route(module, GATEWAY_ROUTE)
        payload = module.app.test_client().get("/compute/api/mcp").get_json()
        assert payload["listener_ready"] is True
        assert payload["route_configured"] is True, "the route file is there"
        assert payload["gateway_verified"] is False
        assert payload["operational"] is False, "a route file alone must not advertise the endpoint"
        assert payload["enabled"] is False
        assert payload["endpoint"] is None
        assert payload["detail"], "the operator gets a reason"
    finally:
        edge.close()


def test_a_set_switch_without_a_listener_is_not_advertised(monkeypatch, tmp_path):
    # The counterexample the flag-only implementation failed: the switch is set
    # but this process has no listener (a switch turned on without a restart).
    # Reading the flag would say "on"; the observed facts must say "no".
    monkeypatch.setenv("MCP_ENABLED", "true")
    import revocompute.mcp.asgi as asgi

    # monkeypatch restores the process-global listener afterwards, so this case
    # never leaks into (or depends on) the order of the tests around it.
    monkeypatch.setitem(asgi._LISTENER, "server", None)
    monkeypatch.setitem(asgi._LISTENER, "error", "the listener did not bind 0.0.0.0:8081 within 10s")
    status = asgi.surface_status()
    assert status["listener_ready"] is False
    assert status["operational"] is False and status["enabled"] is False
    assert status["endpoint"] is None
    # The listener error is operator text and is not returned: the API carries one
    # fixed sentence with no host or port.
    assert status["detail"] == "the MCP listener is not answering on this deployment"
    assert "8081" not in str(status["detail"]) and "0.0.0.0" not in str(status["detail"])

    # With the switch off there is nothing to report and no reason to give.
    monkeypatch.setenv("MCP_ENABLED", "false")
    assert asgi.surface_status() == {
        "listener_ready": False,
        "route_configured": False,
        "gateway_verified": None,
        "operational": False,
        "enabled": False,
        "endpoint": None,
        "detail": None,
    }


def test_a_deployment_that_does_not_probe_reports_reachability_unverified(monkeypatch, tmp_path):
    # A deployment that cannot reach its own public edge (air-gapped, split DNS)
    # does not opt in to the outbound reach. Its facts are still reported, and its
    # reachability is *unverified* (None) rather than asserted false, so nothing
    # reads the absence of a probe as evidence the surface is down.
    edge = _PublicEdge(answer_init=True)
    env = _mcp_vars(edge)
    env["MCP_GATEWAY_PROBE"] = "false"
    try:
        module = _load_pssm_module(monkeypatch, tmp_path, extra_env=env)
        _write_gateway_route(module, GATEWAY_ROUTE)
        payload = module.app.test_client().get("/compute/api/mcp").get_json()
        assert payload["listener_ready"] is True
        assert payload["route_configured"] is True
        assert payload["gateway_verified"] is None
        assert payload["operational"] is False
        assert payload["enabled"] is False
        assert payload["endpoint"] is None
        assert payload["detail"]
        # No reach was attempted, so nothing was sent to the public edge.
        assert edge.posts == []
    finally:
        edge.close()


def test_a_filesystem_error_yields_a_fixed_reason_with_no_path(monkeypatch, tmp_path):
    # The P2 finding: a filesystem error string can carry the real absolute route
    # path, and the public capability must never return one. Simulate an OSError
    # whose text contains the path and assert the response is a fixed reason.
    import revocompute.mcp.asgi as asgi

    secret_path = str(tmp_path / "mcp-gateway" / "mcp.conf")
    monkeypatch.setenv("SERVER_DIR", str(tmp_path))
    monkeypatch.setenv("MCP_ENABLED", "false")

    real_open = open

    def _explode(path, *args, **kwargs):
        if str(path) == secret_path:
            raise PermissionError(f"[Errno 13] Permission denied: '{secret_path}'")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(asgi, "open", _explode, raising=False)
    assert asgi.gateway_route_configured() is False

    # And the projection carries no path: with the switch on and a listener that
    # reports not-ready, the detail is one fixed sentence.
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setitem(asgi._LISTENER, "server", None)
    monkeypatch.setitem(asgi._LISTENER, "error", f"the listener did not bind (route {secret_path})")
    status = asgi.surface_status()
    assert status["detail"] == "the MCP listener is not answering on this deployment"
    assert secret_path not in json.dumps(status)
    assert str(tmp_path) not in json.dumps(status)


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
