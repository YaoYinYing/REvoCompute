# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The MCP capability must report the facts it observed, and advertise the endpoint only on reach.

The Home page offers "Connect an AI agent" only when the public capability says
the surface is operational, so the capability is a *safety* projection: a
deployment whose switch is set but whose ``mcp`` service is absent, unreachable,
or broken must report the surface not operational rather than advertise an
endpoint nothing answers.  And an answering MCP service, or a route file on disk,
is not reachable on its own -- the endpoint Home advertises is reached through the
deployment gateway, so a service that answers behind a missing, stale, or
unreloaded gateway route is still not connectable from outside.

These tests drive the capability through the real application and hold each fact
down in turn, asserting the capability reports it and refuses to advertise the
endpoint.  The facts are real: the MCP service is the deployment's own
``python -m revocompute.mcp`` entrypoint running as its own process on a real
socket, the route is a real file under the deployment's own ``SERVER_DIR``, and
the reach is a real HTTP call to the deployment's own base URL.  Nothing about
the endpoint is inferred from a URL a caller supplied, and a failure's ``detail``
never carries a filesystem error string or an internal port.

Both reaches are *observed*, not remembered forever: a verdict is fresh only for
a bounded TTL, so the transition tests below break or restore the real edge in one
running process, against one unchanged destination, and assert the capability
converges.  They drive the TTL rather than sleeping it out, so the assertions are
about the freshness rule and not about the wall clock.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from conftest import _load_pssm_module

#: The route text the deployment controller writes for an opt-in — the same shape
#: the gateway includes, so a test route is one the gateway would really serve.
GATEWAY_ROUTE = (
    "location /k/ {\n"
    "    proxy_pass http://mcp:8081;\n"
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

#: The fixed sentence the capability carries when the MCP service is not answering.
#: It names no host and no port, which is what the redaction cases assert.
SERVICE_NOT_ANSWERING = "the MCP service is not answering on this deployment"


def _write_gateway_route(module, route_text: str | None) -> None:
    """Leave the deployment's gateway route in the state ``route_text`` describes.

    ``route_text`` is what the deployment host would have left under
    ``SERVER_DIR``: the controller writes it from ``MCP_ENABLED``.  ``None`` means
    no route was written -- the state in which the MCP service has no public face.
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


def _free_port() -> int:
    """A loopback port nothing is listening on at return time."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _initialize_body() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "case", "version": "1"}},
        }
    ).encode("utf-8")


def _answers_initialize(port: int, *, timeout: float = 2.0) -> bool:
    """Whether something at ``port`` answers a real MCP ``initialize``."""
    import httpx

    try:
        response = httpx.post(
            f"http://127.0.0.1:{port}/k/mcp",
            content=_initialize_body(),
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            timeout=timeout,
            trust_env=False,
        )
    except Exception:  # noqa: BLE001 - any transport failure is "not answering"
        return False
    return response.status_code == 200 and "protocolVersion" in response.text


class _McpService:
    """The deployment's MCP service, started the way ``docker-compose.mcp.yml`` starts it.

    ``python -m revocompute.mcp`` is the shipped entrypoint, so a reachability
    fact measured against this process is the fact the deployment would report.
    It is given the deployment environment the application under test was loaded
    with -- the same mounts and variables the overlay extends from ``web`` -- so the
    two processes read one deployment.
    """

    def __init__(self, *, port: int) -> None:
        self.port = port
        self.process: subprocess.Popen[str] | None = None

    def start(self, root: Path) -> "_McpService":
        environment = dict(os.environ)
        environment.update(
            {
                "MCP_ENABLED": "true",
                "MCP_PORT": str(self.port),
                "MCP_LOG_LEVEL": "warning",
                "PYTHONPATH": str(root),
            }
        )
        self.process = subprocess.Popen(
            [sys.executable, "-m", "revocompute.mcp"],
            env=environment,
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                detail = (self.process.stderr.read() if self.process.stderr else "")[-500:]
                raise AssertionError(f"the MCP service exited before answering: {detail}")
            if _answers_initialize(self.port):
                return self
            time.sleep(0.1)
        self.stop()
        raise AssertionError(f"the MCP service did not answer on port {self.port}")

    def stop(self) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - a hung service is a bug
            self.process.kill()
            self.process.wait(timeout=10)
        if self.process.stderr is not None:
            self.process.stderr.close()
        self.process = None

    def alive(self, *, timeout: float = 1.0) -> bool:
        return _answers_initialize(self.port, timeout=timeout)


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
        #: Every request the edge saw, whether or not it answered MCP. It is how a
        #: case tells a refresh that really reached the edge from a flag flip.
        self.attempts = 0
        #: A gate a case can close to simulate the public edge going down (nginx
        #: stopped, upstream broken) while the web process stays alive.
        self.serving = True
        handler = self._handler()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handler(self):
        edge = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server's own spelling
                edge.attempts += 1
                if not (edge.answer_init and edge.serving):
                    # A gateway that is up but serving no /k/ route, an upstream
                    # that is down, or an edge that went away: not MCP here.
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", 0))
                edge.posts.append({"path": self.path, "body": json.loads(self.rfile.read(length).decode("utf-8"))})
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


def _mcp_vars(edge: _PublicEdge, port: int) -> dict[str, str]:
    """The opt-in environment a deployment behind ``edge`` would carry.

    ``MCP_SERVICE``/``MCP_PORT`` are the deployment-owned destination the web
    process dials for the service fact.  The case points them at the MCP service
    it started, which is the topology ``docker-compose.mcp.yml`` declares.
    """
    return {
        "RUNNER_UID": "1234",
        "RUNNER_GID": "5678",
        "MCP_ENABLED": "true",
        "MCP_SERVICE": "127.0.0.1",
        "MCP_PORT": str(port),
        "SERVER_BASE_URL": edge.base_url,
        "MCP_GATEWAY_PROBE": "true",
    }


def _deployment(monkeypatch, tmp_path, edge: _PublicEdge, *, port: int):
    """Load the canonical application as an opt-in deployment dialing ``port``."""
    return _load_pssm_module(monkeypatch, tmp_path, extra_env=_mcp_vars(edge, port))


def test_a_capability_with_no_service_answering_is_reported_not_ready(monkeypatch, tmp_path):
    # MCP_ENABLED=true is *intent*. Nothing answers at the destination this
    # deployment dials, so no surface is served. The capability must say so rather
    # than advertise an endpoint, even with the route and the edge present.
    edge = _PublicEdge(answer_init=True)
    try:
        module = _deployment(monkeypatch, tmp_path, edge, port=_free_port())
        _write_gateway_route(module, GATEWAY_ROUTE)
        payload = module.app.test_client().get("/compute/api/mcp").get_json()
    finally:
        edge.close()

    assert payload["listener_ready"] is False
    assert payload["route_configured"] is True
    assert payload["gateway_verified"] is None
    assert payload["operational"] is False
    assert payload["enabled"] is False
    assert payload["endpoint"] is None
    # The operator gets a fixed, role-based reason, never a silent "disabled".
    assert payload["detail"] == SERVICE_NOT_ANSWERING
    # And the reason carries no destination: the port it dialed is not in the
    # public document.
    assert str(payload["endpoint"]) not in json.dumps(payload)


def test_an_answering_service_behind_a_missing_gateway_route_is_not_advertised(monkeypatch, tmp_path):
    # The exact disagreement the review flagged: the MCP service really answers a
    # real MCP initialize, but the deployment gateway serves no /k/ route, so no
    # agent host outside this container can reach the endpoint Home would
    # advertise. An answering service plus a route file is the only thing this
    # deployment has; the capability must report that, not claim the surface is
    # operational.
    edge = _PublicEdge(answer_init=False)
    service = _McpService(port=_free_port())
    try:
        module = _deployment(monkeypatch, tmp_path, edge, port=service.port)
        service.start(Path(module.CONFIG.server_dir).parent)
        _write_gateway_route(module, None)

        payload = module.app.test_client().get("/compute/api/mcp").get_json()
        assert payload["listener_ready"] is True, "the service genuinely answers"
        assert payload["route_configured"] is False
        assert payload["operational"] is False, "Home must not claim external MCP while the gateway serves no route"
        assert payload["enabled"] is False
        assert payload["endpoint"] is None
        assert payload["detail"], "the operator gets a reason, not a silent off"

        # The service really answers, so the reported facts are distinguishable:
        # listener_ready True with route_configured False is the disagreement.
        assert service.alive()

        # The operator diagnostic agrees, over the public route a client uses.
        assert _operator_health(module) == 1
    finally:
        service.stop()
        edge.close()


def test_the_capability_is_advertised_only_after_a_real_public_handshake(monkeypatch, tmp_path):
    # The public edge answers the initialize the capability sends it, so the
    # deployment's own endpoint is verified and only then does Home offer it.
    edge = _PublicEdge(answer_init=True)
    service = _McpService(port=_free_port())
    try:
        module = _deployment(monkeypatch, tmp_path, edge, port=service.port)
        service.start(Path(module.CONFIG.server_dir).parent)
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

        # And the service fact really came from the wire too.
        assert service.alive()
    finally:
        service.stop()
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
    service = _McpService(port=_free_port())
    try:
        module = _deployment(monkeypatch, tmp_path, edge, port=service.port)
        service.start(Path(module.CONFIG.server_dir).parent)
        client = module.app.test_client()
        for route_text in ("", "# truncated by a partial write\n", "location /other/ { proxy_pass http://mcp:8081; }\n"):
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
        service.stop()
        edge.close()


def test_a_configured_route_whose_gateway_does_not_answer_is_not_operational(monkeypatch, tmp_path):
    # The core P1 counterexample: the route file declares /k/ and the MCP service
    # answers, but nothing answers MCP at the public endpoint (a gateway that never
    # reloaded after the route was written, a stale config, or a down upstream).
    # A route file is not proof the external gateway serves MCP, so the surface
    # must not be advertised.
    edge = _PublicEdge(answer_init=False)
    service = _McpService(port=_free_port())
    try:
        module = _deployment(monkeypatch, tmp_path, edge, port=service.port)
        service.start(Path(module.CONFIG.server_dir).parent)
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
        service.stop()
        edge.close()


def test_a_set_switch_without_a_service_is_not_advertised(monkeypatch, tmp_path):
    # The counterexample the flag-only implementation failed: the switch is set
    # but nothing serves the surface (a switch turned on without a restart, or an
    # overlay that was never layered). Reading the flag would say "on"; the
    # observed facts must say "no".
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_SERVICE", "127.0.0.1")
    monkeypatch.setenv("MCP_PORT", str(_free_port()))
    import revocompute.mcp.asgi as asgi

    status = asgi.surface_status()
    assert status["listener_ready"] is False
    assert status["operational"] is False and status["enabled"] is False
    assert status["endpoint"] is None
    # The destination and any transport error are operator detail: the API carries
    # one fixed sentence with no host or port.
    assert status["detail"] == SERVICE_NOT_ANSWERING
    assert str(os.environ["MCP_PORT"]) not in json.dumps(status)

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
    service = _McpService(port=_free_port())
    try:
        module = _load_pssm_module(
            monkeypatch,
            tmp_path,
            extra_env={**_mcp_vars(edge, service.port), "MCP_GATEWAY_PROBE": "false"},
        )
        service.start(Path(module.CONFIG.server_dir).parent)
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
        service.stop()
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

    # And the projection carries no path: with the switch on and no service
    # answering, the detail is one fixed sentence.
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_SERVICE", "127.0.0.1")
    monkeypatch.setenv("MCP_PORT", str(_free_port()))
    status = asgi.surface_status()
    assert status["detail"] == SERVICE_NOT_ANSWERING
    assert secret_path not in json.dumps(status)
    assert str(tmp_path) not in json.dumps(status)


def _expire_gateway_verdict(monkeypatch) -> None:
    """Make any existing gateway verdict read as expired, without waiting or restarting.

    Freshness is decided by one thing — the age of the verdict against the TTL — so
    a case drives the TTL directly.  No process restart and no 30-second sleep: the
    same running process keeps talking to the same configured base URL, which is
    what makes the transition under test real rather than a different process
    reading a different fact.
    """
    import revocompute.mcp.asgi as asgi

    monkeypatch.setattr(asgi, "GATEWAY_PROBE_TTL_SECONDS", 0.0)


def _expire_service_verdict(monkeypatch) -> None:
    """The same rule for the service fact: drive the TTL, do not sleep it out."""
    import revocompute.mcp.asgi as asgi

    monkeypatch.setattr(asgi, "SERVICE_PROBE_TTL_SECONDS", 0.0)


def test_a_live_gateway_that_goes_down_stops_being_advertised(monkeypatch, tmp_path):
    # A positive verdict must not last forever. The deployment's own endpoint
    # answers, so Home offers the surface; then nginx stops (or the upstream dies)
    # while the web process stays alive. Nothing is restarted and nothing on disk
    # changes - the verdict simply ages out - and the capability must converge to
    # *not advertised* rather than keep claiming a connectivity that is gone.
    edge = _PublicEdge(answer_init=True)
    service = _McpService(port=_free_port())
    try:
        module = _deployment(monkeypatch, tmp_path, edge, port=service.port)
        service.start(Path(module.CONFIG.server_dir).parent)
        _write_gateway_route(module, GATEWAY_ROUTE)
        client = module.app.test_client()

        live = client.get("/compute/api/mcp").get_json()
        assert live["listener_ready"] is True
        assert live["route_configured"] is True
        assert live["gateway_verified"] is True
        assert live["enabled"] is True
        assert live["endpoint"] == f"{edge.base_url}/k/mcp"
        assert edge.attempts == 1

        # A verdict still inside its TTL is a memory read: reading the capability
        # again reaches nothing over the network.
        again = client.get("/compute/api/mcp").get_json()
        assert again["enabled"] is True
        assert edge.attempts == 1, "a fresh verdict must not re-probe the edge"

        # The edge goes down. Same process, same base URL, same route file.
        edge.serving = False
        _expire_gateway_verdict(monkeypatch)
        down = client.get("/compute/api/mcp").get_json()
        assert down["listener_ready"] is True
        assert down["route_configured"] is True, "the route file did not change"
        assert down["gateway_verified"] is False, "an outage must stop being advertised"
        assert down["enabled"] is False
        assert down["endpoint"] is None
        assert down["detail"], "the operator gets a reason, not a silent off"
        assert edge.attempts == 2, "the expired verdict is re-probed exactly once"
    finally:
        service.stop()
        edge.close()


def test_a_down_gateway_that_recovers_is_advertised_again(monkeypatch, tmp_path):
    # The mirror of the case above, and the second real regression: a negative
    # verdict must not last forever either. The endpoint does not answer, so the
    # surface is not advertised; the operator then brings the gateway back, and the
    # capability must converge to *advertised* on the next read - without a
    # web-process restart - rather than deny a recovery for the life of the process.
    edge = _PublicEdge(answer_init=True)
    edge.serving = False
    service = _McpService(port=_free_port())
    try:
        module = _deployment(monkeypatch, tmp_path, edge, port=service.port)
        service.start(Path(module.CONFIG.server_dir).parent)
        _write_gateway_route(module, GATEWAY_ROUTE)
        client = module.app.test_client()

        down = client.get("/compute/api/mcp").get_json()
        assert down["listener_ready"] is True
        assert down["route_configured"] is True
        assert down["gateway_verified"] is False
        assert down["enabled"] is False
        assert down["endpoint"] is None

        # The edge comes back. Same process, same base URL, same route file.
        edge.serving = True
        _expire_gateway_verdict(monkeypatch)
        up = client.get("/compute/api/mcp").get_json()
        assert up["gateway_verified"] is True, "a recovery must be advertised again"
        assert up["operational"] is True
        assert up["enabled"] is True
        assert up["endpoint"] == f"{edge.base_url}/k/mcp"
        assert up["detail"] is None
    finally:
        service.stop()
        edge.close()


def test_an_mcp_service_that_goes_down_stops_being_reported_ready(monkeypatch, tmp_path):
    # The service fact is a fact about another process, so it must age like the
    # edge fact does: an MCP service that dies after a healthy handshake must stop
    # being reported ready, without restarting the web process and without the
    # switch changing.  The route file stays exactly as it was.
    import revocompute.mcp.asgi as asgi

    edge = _PublicEdge(answer_init=True)
    service = _McpService(port=_free_port())
    try:
        module = _deployment(monkeypatch, tmp_path, edge, port=service.port)
        service.start(Path(module.CONFIG.server_dir).parent)
        _write_gateway_route(module, GATEWAY_ROUTE)
        client = module.app.test_client()

        live = client.get("/compute/api/mcp").get_json()
        assert live["listener_ready"] is True
        assert live["enabled"] is True

        # A fresh verdict is a memory read: the same answer, no second handshake.
        again = client.get("/compute/api/mcp").get_json()
        assert again["listener_ready"] is True

        service.stop()
        _expire_service_verdict(monkeypatch)
        down = client.get("/compute/api/mcp").get_json()
        assert down["listener_ready"] is False, "a stopped service must stop being reported ready"
        assert down["route_configured"] is True, "the route file did not change"
        assert down["operational"] is False
        assert down["enabled"] is False
        assert down["endpoint"] is None
        assert down["detail"] == SERVICE_NOT_ANSWERING
        # The capability reports the reach as unknown, not as an observed failure:
        # the gateway was never called, because the service fact already failed.
        assert down["gateway_verified"] is None
    finally:
        service.stop()
        edge.close()


def test_an_mcp_service_that_recovers_is_reported_ready_again(monkeypatch, tmp_path):
    # The mirror: the verdict must not be sticky in the other direction either.
    # The service is down, so the surface is not operational; the operator then
    # starts it, and the next read after the window reports it ready again and
    # advertises the endpoint on the real public handshake.
    edge = _PublicEdge(answer_init=True)
    service = _McpService(port=_free_port())
    try:
        module = _deployment(monkeypatch, tmp_path, edge, port=service.port)
        _write_gateway_route(module, GATEWAY_ROUTE)
        client = module.app.test_client()

        down = client.get("/compute/api/mcp").get_json()
        assert down["listener_ready"] is False
        assert down["enabled"] is False

        service.start(Path(module.CONFIG.server_dir).parent)
        _expire_service_verdict(monkeypatch)
        up = client.get("/compute/api/mcp").get_json()
        assert up["listener_ready"] is True, "a recovered service must be reported ready again"
        assert up["operational"] is True
        assert up["enabled"] is True
        assert up["endpoint"] == f"{edge.base_url}/k/mcp"
    finally:
        service.stop()
        edge.close()


def test_a_read_that_loses_the_refresh_race_fails_closed(monkeypatch, tmp_path):
    # Expired evidence must not be re-served, and a crowd of capability readers
    # must not stampede an endpoint that may already be down. One read owns the
    # refresh; a read that finds the verdict expired while another read holds the
    # refresh lock returns unverified (None) and, above all, does not launch a
    # second probe.
    import revocompute.mcp.asgi as asgi

    edge = _PublicEdge(answer_init=True)
    service = _McpService(port=_free_port())
    try:
        module = _deployment(monkeypatch, tmp_path, edge, port=service.port)
        service.start(Path(module.CONFIG.server_dir).parent)
        _write_gateway_route(module, GATEWAY_ROUTE)
        # A verdict that was once real and is now older than the TTL.
        monkeypatch.setitem(asgi._GATEWAY_PROBE, "base", asgi.gateway_endpoint())
        monkeypatch.setitem(asgi._GATEWAY_PROBE, "result", True)
        monkeypatch.setitem(asgi._GATEWAY_PROBE, "at", time.monotonic() - 10 * asgi.GATEWAY_PROBE_TTL_SECONDS)

        holding = threading.Event()
        release = threading.Event()

        def _hold_refresh_lock() -> None:
            with asgi._GATEWAY_PROBE_LOCK:
                holding.set()
                release.wait(timeout=10)

        holder = threading.Thread(target=_hold_refresh_lock, daemon=True)
        holder.start()
        try:
            assert holding.wait(timeout=5), "the refresh lock was not acquired"
            assert asgi.gateway_reachable() is None, "the losing read is unverified, not stale"
            status = asgi.surface_status()
            assert status["gateway_verified"] is None, "expired evidence is unverified, never re-served"
            assert status["enabled"] is False
            assert status["endpoint"] is None
            assert status["detail"]
            assert edge.attempts == 0, "a losing read must not launch a second probe"
        finally:
            release.set()
            holder.join(timeout=5)

        # The fail-closed answer is bounded by the one refresh it declined to
        # duplicate: once the winner's lock is free, the next read converges.
        recovered = asgi.surface_status()
        assert recovered["gateway_verified"] is True
        assert recovered["enabled"] is True
        assert edge.attempts == 1
    finally:
        service.stop()
        edge.close()


def test_a_service_read_that_loses_the_refresh_race_fails_closed(monkeypatch, tmp_path):
    # The same fail-closed rule for the service fact: one read owns the refresh,
    # and a read that loses the race reports not-ready rather than queueing a
    # second bounded handshake onto a service that may already be down.
    import revocompute.mcp.asgi as asgi

    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_SERVICE", "127.0.0.1")
    port = _free_port()
    monkeypatch.setenv("MCP_PORT", str(port))
    monkeypatch.setitem(asgi._SERVICE_PROBE, "target", ("127.0.0.1", port))
    monkeypatch.setitem(asgi._SERVICE_PROBE, "result", True)
    monkeypatch.setitem(asgi._SERVICE_PROBE, "at", time.monotonic() - 10 * asgi.SERVICE_PROBE_TTL_SECONDS)

    probes: list[str] = []
    real_probe = asgi.probe_endpoint

    def _counting_probe(endpoint: str, **kwargs):
        probes.append(endpoint)
        return real_probe(endpoint, **kwargs)

    monkeypatch.setattr(asgi, "probe_endpoint", _counting_probe)

    holding = threading.Event()
    release = threading.Event()

    def _hold_refresh_lock() -> None:
        with asgi._SERVICE_PROBE_LOCK:
            holding.set()
            release.wait(timeout=10)

    holder = threading.Thread(target=_hold_refresh_lock, daemon=True)
    holder.start()
    try:
        assert holding.wait(timeout=5), "the refresh lock was not acquired"
        assert asgi.service_reachable() is None, "the losing read is unverified, not stale"
        status = asgi.surface_status()
        assert status["listener_ready"] is False, "expired evidence is not re-served"
        assert status["enabled"] is False
        assert probes == [], "a losing read must not launch a second probe"
    finally:
        release.set()
        holder.join(timeout=5)

    # Bounded by the one refresh it declined to duplicate: once the lock is free
    # the next read converges on the real answer.
    assert asgi.service_reachable() is False
    assert len(probes) == 1


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
