# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Mount the MCP streamable-HTTP endpoint beside the canonical HTTP API.

One process, one port, two protocol surfaces over one application truth.  In the
deployed configuration the MCP endpoint is served from the *same* process as the
Flask application, so the canonical rate limiter, admission path, and application
state are shared rather than replicated: an MCP caller and an HTTP caller from
one client address consume one budget, and MCP cannot become a second admission
path.

That is why the default deployment is a companion listener rather than a second
service role.  The ASGI stack starts only when the optional ``mcp`` extra is
installed; a deployment without it serves the HTTP API and Web application
exactly as before.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any

#: Public path prefix for the MCP surface.  The streamable-HTTP endpoint is at
#: ``/k/mcp``; the prefix is short and does not collide with an existing route.
MCP_PATH = "/k"

#: The MCP streamable-HTTP endpoint the deployment exposes and a client connects to.
MCP_ENDPOINT = f"{MCP_PATH}/mcp"

#: The protocol revision the readiness handshake negotiates.  The server also
#: accepts later/earlier revisions (the SDK negotiates); this is only what the
#: probe asks for, so a mismatch would surface as a genuine incompatibility.
MCP_PROTOCOL_VERSION = "2025-06-18"

#: Internal port of the companion MCP listener.  Bound inside the web container
#: and proxied by the deployment gateway, which also fronts the HTTP API port.
#: The deployment publishes neither directly.
DEFAULT_MCP_PORT = 8081

#: Gateway route state, reconciled from ``MCP_ENABLED`` by ``run/restart.sh`` and
#: written under ``SERVER_DIR`` — the one directory both the deployment host and
#: the web process see.  The route is what turns the internal listener into the
#: public endpoint, so its absence is exactly the state in which an agent host
#: cannot reach the surface however healthy the listener is.
GATEWAY_ROUTE_DIR = "mcp-gateway"
GATEWAY_ROUTE_FILE = "mcp.conf"

#: A route the gateway actually serves must declare the MCP location prefix.
#: Presence alone is not the fact: a truncated, empty, or unrelated file left
#: behind would otherwise be read as a live route.
_GATEWAY_ROUTE_RE = re.compile(r"^\s*location\s+/k/", re.MULTILINE)

#: How long :func:`start_companion_listener` waits for the listener to bind
#: before it reports the surface as not started.  The wait happens once, in the
#: process that will serve the endpoint, so a deployment knows at startup whether
#: its opt-in produced a surface rather than discovering it on first use.
LISTENER_STARTUP_TIMEOUT_SECONDS = 10.0

#: Deadline for the in-process readiness handshake :func:`probe_surface` drives
#: against the *bound* listener.  Short on purpose: a loopback listener in this
#: process answers ``initialize`` in milliseconds, and the probe bounds the
#: public capability request rather than the surface itself.
SURFACE_PROBE_TIMEOUT_SECONDS = 5.0

_LOGGER = logging.getLogger(__name__)

#: The one listener this process starts, if the deployment opted in.  Readiness
#: is a property of what the *bound socket answers*, not of the switch that asked
#: for it: a flag-only answer is what let a deployment advertise an endpoint whose
#: port was never bound.
_LISTENER: dict[str, Any] = {"server": None, "thread": None, "error": None}

#: Last readiness-handshake result, so the public capability is a memory read
#: rather than an outbound call per request.  ``None`` means "not probed yet".
_PROBE: dict[str, Any] = {"result": None}


def mcp_asgi() -> Any:
    """Return the ASGI application serving the MCP endpoint.

    The streamable-HTTP session manager owns a background task group that the
    ASGI lifespan must start, so the mount is wrapped in a lifespan that enters
    the MCP application's own lifespan context.  Without it the first request
    fails with "Task group is not initialized".
    """
    from contextlib import asynccontextmanager

    from starlette.applications import Starlette
    from starlette.routing import Mount

    from revocompute.mcp.server import build_server

    mcp_app = build_server().streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: Any):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    return Starlette(routes=[Mount(MCP_PATH, app=mcp_app)], lifespan=lifespan)


def serve() -> None:
    """Run the MCP ASGI listener (the standalone ``revocompute-mcp`` entrypoint).

    Used for interoperability testing and for a deployment that chooses to run
    the listener in its own process.  The deployed default is
    :func:`start_companion_listener` inside the web process, which keeps the
    canonical limiter shared.
    """
    import os

    import uvicorn

    from revocompute.config import env_int

    port = env_int("MCP_PORT", DEFAULT_MCP_PORT)
    # Binds all interfaces inside the container; the port is never published and
    # only the deployment gateway reaches it.
    uvicorn.run(mcp_asgi(), host="0.0.0.0", port=port, log_level=os.environ.get("MCP_LOG_LEVEL", "info"))  # nosec B104


def mcp_enabled() -> bool:
    """Whether this deployment opted in to serving the MCP surface.

    The switch is a deployment fact, so it is read from the environment directly
    rather than from a Flask app: the listener and any capability this process
    reports must be decided by the same value, or the two can disagree.
    """
    from revocompute.config import env_bool

    return env_bool("MCP_ENABLED", False)


def start_companion_listener() -> threading.Thread | None:
    """Start the MCP ASGI listener in a daemon thread of this process.

    The listener shares this process's memory, so the canonical rate limiter,
    the loaded application, and every in-process admission decision are the same
    objects the HTTP API uses.  Returns ``None`` when MCP is disabled, the
    optional ASGI stack is missing, or the listener failed to bind within
    :data:`LISTENER_STARTUP_TIMEOUT_SECONDS`; the HTTP API is never affected by
    any of those.  The deployment starts the web process with Gunicorn
    ``--preload``, so the listener lives in the master and its bound socket is
    inherited by every worker: one listener, one application, one admission
    path per container.
    """
    import os

    from revocompute.config import env_int

    # Opt-in: the listener is off unless the deployment turns it on, so an
    # ordinary import (a worker, a maintenance process, a test) never binds a
    # port or spawns a thread.
    if not mcp_enabled():
        return None
    try:
        import uvicorn
    except ImportError:
        _LOGGER.info("MCP listener not started: the optional 'mcp' extra is not installed")
        _LISTENER["error"] = "the optional 'mcp' extra is not installed"
        return None

    host = os.environ.get("MCP_HOST", "0.0.0.0")  # noqa: S104 - container-internal bind
    port = env_int("MCP_PORT", DEFAULT_MCP_PORT)
    config = uvicorn.Config(mcp_asgi(), host=host, port=port, log_level=os.environ.get("MCP_LOG_LEVEL", "warning"))
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="mcp-asgi", daemon=True)
    _LISTENER.update({"server": server, "thread": thread, "error": None})
    # A fresh listener invalidates any previous readiness answer.
    _PROBE["result"] = None
    thread.start()
    # The thread returning is not readiness: uvicorn sets ``started`` only after
    # ``create_server`` succeeds, so waiting for it (and for the thread to still
    # be alive, since a bind failure exits the process it runs in) is what
    # distinguishes "the listener answers" from "the switch was set".
    deadline = time.monotonic() + LISTENER_STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if getattr(server, "started", False):
            _LOGGER.info("MCP surface listening on %s:%s%s", host, port, MCP_ENDPOINT)
            return thread
        if not thread.is_alive():
            break
        time.sleep(0.05)
    _LISTENER["error"] = f"the listener did not bind {host}:{port} within {LISTENER_STARTUP_TIMEOUT_SECONDS:g}s"
    _LOGGER.error("MCP surface did not start: %s", _LISTENER["error"])
    return None


def gateway_route_served() -> tuple[bool, str]:
    """Whether the deployment gateway serves this surface, read from its own state.

    The listener answers on loopback inside the web container, but the endpoint a
    browser or an agent host is offered reaches it only through the deployment
    gateway.  The gateway's route is deployment state that ``run/restart.sh``
    reconciles from ``MCP_ENABLED`` into ``SERVER_DIR`` — the directory both the
    deployment host and this process share — so reading it here answers "does the
    public endpoint exist" without any outbound call and without trusting a URL a
    caller supplied.

    A route that only *exists* is not a route that is *served*: an empty, truncated,
    or unrelated file left behind would be read as live.  The check is therefore
    that the file declares the MCP location prefix the gateway needs, and that
    ``SERVER_DIR`` is resolvable at all.  ``(served, detail)`` — the reason is
    operator-facing and names no host, address, or port.
    """
    server_dir = os.environ.get("SERVER_DIR", "").strip()
    if not server_dir:
        return False, "the deployment server directory is not resolvable, so the gateway route cannot be confirmed"
    route = os.path.join(server_dir, GATEWAY_ROUTE_DIR, GATEWAY_ROUTE_FILE)
    try:
        with open(route, encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return False, "the deployment gateway serves no /k/ route; run `restart.sh restart` to reconcile it from MCP_ENABLED"
    except OSError as exc:  # noqa: BLE001 - readiness must never raise into a capability read
        return False, f"the deployment gateway route state could not be read: {exc}"
    if not _GATEWAY_ROUTE_RE.search(text):
        return False, "the deployment gateway route state does not declare the /k/ location"
    return True, ""


def surface_status() -> dict[str, Any]:
    """What *this process* can actually answer for the MCP surface.

    The canonical HTTP surface reads its capability through this, so a browser is
    told the surface is reachable only when *both* facts that make it reachable
    hold: the companion listener bound and answered a real MCP ``initialize``
    handshake in this process, and the deployment gateway serves the route that
    turns that internal listener into the public endpoint.  A flag-only answer
    advertised a dead endpoint; so would a listener-only answer, because an agent
    host reaches the surface through the gateway and not through the listener's
    loopback.

    It reports no host, port, or credential — only whether the surface is
    publicly reachable, and, when it is not, a short reason an operator can act
    on.  The listener's readiness is probed once per process (its binding and its
    fixed surface cannot change at runtime); the route is re-read on every call,
    because ``restart.sh`` reconciles it without restarting this process and a
    long-lived answer must not outlive the route it describes.
    """
    if not mcp_enabled():
        # The default, and not a problem: nothing was asked for.
        return {"enabled": False, "endpoint": None, "detail": None}
    server = _LISTENER["server"]
    if server is None or not getattr(server, "started", False):
        # Enabled, but this process cannot answer: a missing extra, a bind
        # failure, or a switch set without a restart.  Never a silent "off".
        detail = _LISTENER["error"] or "MCP is enabled but no listener is bound in this process; restart the deployment"
        return {"enabled": False, "endpoint": None, "detail": detail}
    if _PROBE["result"] is None:
        _PROBE["result"] = probe_surface(server)
    ok, detail = _PROBE["result"]
    if not ok:
        return {"enabled": False, "endpoint": None, "detail": detail}
    # The listener answers, but the public endpoint is only as real as the
    # gateway route that fronts it.  A listener that bound while the deployment
    # gateway serves no /k/ route is the exact case in which Home would otherwise
    # offer an endpoint nothing external can reach.
    served, route_detail = gateway_route_served()
    if not served:
        return {"enabled": False, "endpoint": None, "detail": route_detail}
    return {"enabled": True, "endpoint": MCP_ENDPOINT, "detail": None}


def probe_surface(server: Any) -> tuple[bool, str]:
    """Drive one real MCP ``initialize`` against the bound companion listener.

    Binding a port is not serving the protocol: the transport may have failed to
    start its session manager, the mount may be wrong, or the endpoint may 404.
    So readiness is proven by the same pre-credential handshake an agent host
    performs first — an unauthenticated ``initialize`` over streamable HTTP on
    the listener's own loopback — and reported as ``(reachable, detail)``.

    The request runs in a throwaway event loop on this thread rather than in the
    listener's, and is not a second listener or execution plane: it speaks to the
    one surface the deployment serves, which is also what makes it a real
    end-to-end check rather than an assertion about a flag.  ``server`` (the bound
    listener) is what makes the check meaningful — a caller only probes when one
    exists.
    """
    import asyncio
    import json

    port = _bound_port(server)
    if port is None:
        return False, "the MCP listener is not bound to a port"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "revocompute-surface-probe", "version": "1"},
            },
        }
    ).encode("utf-8")

    async def _run() -> tuple[bool, str]:
        import httpx

        # A loopback client of our own surface, on the port the listener actually
        # bound (never assumed from the environment).  The listener binds all
        # container interfaces, so 127.0.0.1 reaches it from here; the port is
        # deployment-internal and never leaves the capability projection.
        # ``trust_env=False`` so a deployment's HTTP(S)_PROXY can never redirect
        # this in-process loopback readiness check off the host.
        async with httpx.AsyncClient(timeout=SURFACE_PROBE_TIMEOUT_SECONDS, trust_env=False) as client:
            response = await client.post(
                f"http://127.0.0.1:{port}{MCP_ENDPOINT}",
                content=body,
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            )
        return _initialize_result(response.status_code, response.headers.get("content-type", ""), response.text)

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 - readiness must never raise into a capability read
        return False, f"the MCP endpoint did not answer an initialize handshake: {exc}"


def _bound_port(server: Any) -> int | None:
    """The TCP port the listener actually holds, or ``None`` if it holds none.

    Read from the bound socket rather than the environment, so an ephemeral
    ``MCP_PORT=0`` (or any port the environment overstated) is probed where the
    surface really is.
    """
    servers = getattr(server, "servers", None) or []
    for bound in servers:
        for sock in getattr(bound, "sockets", None) or []:
            try:
                address = sock.getsockname()
            except OSError:
                continue
            if isinstance(address, tuple) and len(address) >= 2 and isinstance(address[1], int):
                return address[1]
    return None


def _initialize_result(status: int, content_type: str, text: str) -> tuple[bool, str]:
    """Interpret one ``initialize`` response as ``(reachable, detail)``.

    The transport may answer as a single ``text/event-stream`` frame or as JSON;
    both are an MCP answer, so both are accepted.  A rejection (a 4xx with a
    body) still proves the route is served, but it is reported as not reachable
    because an agent host's first call would fail the same way.
    """
    import json

    if status != 200:
        return False, f"the MCP endpoint answered HTTP {status}"
    payload = text.strip()
    if "text/event-stream" in content_type.lower():
        for line in payload.splitlines():
            if line.startswith("data:"):
                payload = line[len("data:") :].strip()
                break
    try:
        decoded = json.loads(payload)
    except ValueError:
        return False, "the MCP endpoint did not answer a JSON-RPC response"
    result = decoded.get("result") if isinstance(decoded, dict) else None
    if not isinstance(result, dict) or "protocolVersion" not in result:
        return False, "the MCP endpoint answered without an initialize result"
    server = result.get("serverInfo") or {}
    return True, f"protocol {result['protocolVersion']}, server {server.get('name', 'unknown')}"


__all__ = [
    "DEFAULT_MCP_PORT",
    "GATEWAY_ROUTE_DIR",
    "GATEWAY_ROUTE_FILE",
    "LISTENER_STARTUP_TIMEOUT_SECONDS",
    "MCP_ENDPOINT",
    "MCP_PATH",
    "MCP_PROTOCOL_VERSION",
    "SURFACE_PROBE_TIMEOUT_SECONDS",
    "gateway_route_served",
    "mcp_asgi",
    "mcp_enabled",
    "probe_surface",
    "serve",
    "start_companion_listener",
    "surface_status",
]
