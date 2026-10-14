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

#: The public endpoint every deployment serves the application on.  The gateway
#: route proxies ``/k/`` to the companion listener, so an agent host reaches the
#: surface at this same-origin public base joined with :data:`MCP_ENDPOINT` —
#: never at the listener's container-internal loopback.  It is *public
#: deployment* identity: it holds no credential, no container-internal port and
#: no host path, and the web process may hold it without owning any
#: infrastructure secret.
PUBLIC_BASE_URL_ENV = "SERVER_BASE_URL"

#: How long the surface waits when it really reaches for the public endpoint over
#: the gateway.  Reaching out is a network call, so the deadline is bounded and a
#: timeout is a *negative* answer rather than a hang on the capability request.
GATEWAY_PROBE_TIMEOUT_SECONDS = 3.0

#: How long one public-endpoint verdict stays fresh.  Short enough that a real
#: outage of the deployment gateway stops being advertised, and a recovered edge
#: is advertised again, without a web-process restart; long enough that a
#: sustained capability read stays mostly a memory read rather than one gateway
#: round trip per Home poll.
GATEWAY_PROBE_TTL_SECONDS = 30.0

#: The switch that decides whether the surface reaches for the public endpoint at
#: all.  Set it only in a deployment that can reach its own public address (a
#: direct deployment, a host loopback, or a network that resolves and reaches the
#: edge); an air-gapped or split-DNS deployment leaves it unset, and the surface
#: then reports the endpoint as unverified rather than attempting an outbound
#: call.  Either way a deployment that *can* reach the edge advertises the
#: surface on a real gateway handshake and never on a route file.
GATEWAY_PROBE_ENV = "MCP_GATEWAY_PROBE"

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

#: Last listener-readiness result, so the public capability is a memory read
#: rather than an outbound call per request.  ``None`` means "not probed yet".
_PROBE: dict[str, Any] = {"result": None}

#: Last public-endpoint (gateway) result, keyed by the base URL it was proven
#: against so a changed base re-probes instead of serving a stale answer, and
#: stamped with the ``time.monotonic()`` of the probe that produced it so the
#: answer expires on :data:`GATEWAY_PROBE_TTL_SECONDS` rather than lasting for the
#: life of the process.
_GATEWAY_PROBE: dict[str, Any] = {"base": None, "result": None, "at": None}

#: Single-flight guard for the outbound gateway probe.  A capability read that
#: finds the cached verdict expired tries to become the one that refreshes it; the
#: others return fail-closed rather than piling a second bounded request onto an
#: endpoint that may already be down.
_GATEWAY_PROBE_LOCK = threading.Lock()


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


#: Fixed, role-based reasons the public capability may carry.  They exist so a
#: failure is *named* without leaking deployment specifics: an ``OSError`` string
#: can carry the real absolute route path, so it is logged for the operator and
#: never placed in an API response.  A public ``detail`` is one of these or
#: ``None``.
DETAIL_ROUTE_NOT_CONFIGURED = "the deployment gateway is not configured to serve the MCP route"
DETAIL_GATEWAY_UNREACHABLE = "the MCP endpoint was not reached through the deployment gateway"
DETAIL_GATEWAY_UNVERIFIED = (
    "this deployment does not probe its public MCP endpoint, so external reachability is unverified"
)


def gateway_route_configured() -> bool:
    """Whether the deployment gateway is *configured* to serve this surface.

    Reads the route state ``run/restart.sh`` reconciles from ``MCP_ENABLED`` into
    ``SERVER_DIR``, the directory both the deployment host and this process share,
    so it answers "is the public endpoint wired" with no outbound call and without
    trusting a URL a caller supplied.  A route that only *exists* is not a route
    that is *served*: an empty, truncated, or unrelated file left behind would
    otherwise be read as live, so the file must declare the MCP location prefix.

    Configured is *not* reachable: a stale config, a gateway that never reloaded,
    or an upstream that is down all read as configured.  That is why the public
    capability reports this as one fact among several and never as ``enabled``.
    The reason an unconfigured route is unreadable is logged, never returned: an
    ``OSError`` string can contain the absolute route path.
    """
    server_dir = os.environ.get("SERVER_DIR", "").strip()
    if not server_dir:
        return False
    route = os.path.join(server_dir, GATEWAY_ROUTE_DIR, GATEWAY_ROUTE_FILE)
    try:
        with open(route, encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return False
    except OSError:
        _LOGGER.warning("MCP gateway route state at %s could not be read", route, exc_info=True)
        return False
    return _GATEWAY_ROUTE_RE.search(text) is not None


def gateway_endpoint() -> str | None:
    """The public URL an agent host reaches the surface at, or ``None``.

    The same-origin public base joined with :data:`MCP_ENDPOINT`.  It is public
    deployment identity, not infrastructure: the listener's container-internal
    port and host path are never part of it.
    """
    base = os.environ.get(PUBLIC_BASE_URL_ENV, "").strip().rstrip("/")
    return f"{base}{MCP_ENDPOINT}" if base else None


def gateway_reachable() -> bool | None:
    """Whether this process reached the MCP endpoint through the public gateway.

    ``True``  the deployment's own public endpoint answered a real MCP
              ``initialize`` handshake, so an agent host reaches the same surface;
    ``False`` the reach was attempted and the endpoint did not answer MCP;
    ``None``  the reach was not attempted: the deployment did not opt in to
              probing, or no public base URL is known, so reachability is
              *unverified* rather than asserted either way — or the reach was
              attempted while another read was already refreshing an expired
              verdict, which is fail-closed for the same reason.

    The destination is never caller-controlled: it is :func:`gateway_endpoint`,
    built from this deployment's own ``SERVER_BASE_URL`` and the fixed MCP path,
    reachable only because the listener shares this process's admitted traffic
    through the deployment gateway.  Nothing here forwards a caller-supplied
    target, so no SSRF surface is introduced.

    The verdict is memoized per base URL *and bounded in time*: a verdict is fresh
    only while it is younger than :data:`GATEWAY_PROBE_TTL_SECONDS`, so a read
    served from a fresh cache is a pure memory read, and a read of an expired (or
    absent, or changed-base) verdict refreshes it.  Freshness is deliberately
    symmetric — a positive and a negative verdict expire on the same TTL — so a
    gateway that goes down stops being advertised, and a gateway that recovers is
    advertised again, both without restarting the web process; a verdict that
    lasted forever would report connectivity that is no longer there (or deny
    connectivity that has returned) for the life of the process.

    The refresh is single-flight: one read wins ``_GATEWAY_PROBE_LOCK`` and drives
    the existing bounded :func:`probe_gateway` (its 3-second deadline,
    ``trust_env=False``, and fixed deployment-owned destination are unchanged);
    every concurrent read that finds the verdict expired but the lock held returns
    ``None`` — unverified, so the surface is not advertised — rather than start a
    second probe, because the only evidence it holds is expired.  An expiring
    verdict therefore degrades to *unverified* for the duration of one bounded
    refresh, never to a stale assertion.
    """
    from revocompute.config import env_bool

    if not env_bool(GATEWAY_PROBE_ENV, False):
        return None
    endpoint = gateway_endpoint()
    if endpoint is None:
        return None
    at = _GATEWAY_PROBE["at"]
    if (
        _GATEWAY_PROBE["base"] == endpoint
        and _GATEWAY_PROBE["result"] is not None
        and at is not None
        and time.monotonic() - at < GATEWAY_PROBE_TTL_SECONDS
    ):
        return bool(_GATEWAY_PROBE["result"])
    if not _GATEWAY_PROBE_LOCK.acquire(blocking=False):
        # Expired evidence and another read already refreshing it: fail closed
        # rather than stampede the endpoint or serve a verdict that has expired.
        return None
    try:
        reachable, _ = probe_gateway(endpoint)
        _GATEWAY_PROBE.update({"base": endpoint, "result": reachable, "at": time.monotonic()})
    finally:
        _GATEWAY_PROBE_LOCK.release()
    if not reachable:
        _LOGGER.warning("MCP public endpoint %s did not answer an initialize handshake", endpoint)
    return reachable


def surface_status() -> dict[str, Any]:
    """What *this process* can actually answer for the MCP surface.

    The canonical HTTP surface reads its capability through this, so a browser is
    told the surface is *operational* only when this deployment genuinely reached
    its own public MCP endpoint — a real MCP ``initialize`` handshake over the
    deployment gateway an agent host would use.  A healthy companion listener, or
    a route file on disk, are not that fact: a stale config, a gateway that never
    reloaded, or an upstream that is down all leave both true while nothing
    external answers.  So the capability reports each fact separately and gates
    ``operational`` on the *reach* alone:

    ``listener_ready``    the companion listener bound and answered an
                          ``initialize`` on loopback in this process;
    ``route_configured``  the deployment gateway route state declares the MCP
                          location (a route *file* is not a route *served*);
    ``gateway_verified``  ``True``/``False`` when this deployment reached its own
                          public endpoint, ``None`` when it does not probe (or
                          while an expired verdict is being refreshed);
    ``operational``       ``True`` only on ``gateway_verified is True``;
    ``enabled``           the legacy projection Home consumes: ``True`` only when
                          ``operational``, ``endpoint`` set and no ``detail``;
    ``endpoint``          the public URL when operational, else ``None``;
    ``detail``            a fixed role-based reason when not operational, else
                          ``None``.  Never a credential, host path, port, or
                          filesystem error string.

    It reports no host, port, or credential of its own, and reads no
    caller-supplied URL.  The listener's readiness is probed once per process (its
    binding and its fixed surface cannot change at runtime); the route is re-read
    on every call, because ``restart.sh`` reconciles it without restarting this
    process and a long-lived answer must not outlive the route it describes; and
    the gateway reach is re-read once its verdict is older than
    :data:`GATEWAY_PROBE_TTL_SECONDS`, so an outage eventually stops being
    advertised and a recovery eventually is, on the same TTL in both directions.
    While that refresh is in flight a concurrent read reports ``gateway_verified``
    as ``None`` and advertises nothing (see :func:`gateway_reachable`).
    """
    # The default, and not a problem: nothing was asked for.
    if not mcp_enabled():
        return _capability(False, False, None, endpoint=None, detail=None)
    route_configured = gateway_route_configured()
    server = _LISTENER["server"]
    if server is None or not getattr(server, "started", False):
        # Enabled, but this process cannot answer: a missing extra, a bind
        # failure, or a switch set without a restart.  Never a silent "off".
        return _capability(False, route_configured, None, endpoint=None, detail=_listener_detail())
    if _PROBE["result"] is None:
        _PROBE["result"] = probe_surface(server)
    listener_ready, listener_detail = _PROBE["result"]
    if not listener_ready:
        return _capability(False, route_configured, None, endpoint=None, detail=listener_detail)
    gateway_verified = gateway_reachable()
    if gateway_verified is None:
        # This deployment does not reach for its public edge, so external
        # reachability is unverified: the surface is not advertised on that.
        return _capability(True, route_configured, None, endpoint=None, detail=DETAIL_GATEWAY_UNVERIFIED)
    if not gateway_verified:
        detail = DETAIL_GATEWAY_UNREACHABLE if route_configured else DETAIL_ROUTE_NOT_CONFIGURED
        return _capability(True, route_configured, False, endpoint=None, detail=detail)
    return _capability(True, route_configured, True, endpoint=gateway_endpoint(), detail=None)


def _capability(
    listener_ready: bool,
    route_configured: bool,
    gateway_verified: bool | None,
    *,
    endpoint: str | None,
    detail: str | None,
) -> dict[str, Any]:
    """Assemble the capability document from the four independent facts.

    ``operational`` is the reach alone; ``enabled`` is the reduced projection Home
    consumes, so the public UI and any other reader agree on one meaning.
    """
    operational = gateway_verified is True and endpoint is not None
    return {
        "listener_ready": listener_ready,
        "route_configured": route_configured,
        "gateway_verified": gateway_verified,
        "operational": operational,
        "enabled": operational,
        "endpoint": endpoint if operational else None,
        "detail": None if operational else detail,
    }


def _listener_detail() -> str:
    """A fixed reason the listener is not answering.

    The stored listener error is operator text and may name the bound host and
    port, so it stays in the log; the capability carries one fixed sentence.
    """
    if _LISTENER["error"]:
        _LOGGER.warning("MCP listener not ready: %s", _LISTENER["error"])
    return "the MCP listener is not answering on this deployment"


def probe_gateway(endpoint: str) -> tuple[bool, str]:
    """Drive one MCP ``initialize`` against the deployment's *public* endpoint.

    The listener probe proves the surface inside the web container; this proves
    the endpoint an agent host actually uses, through the deployment gateway.  It
    is the same pre-credential handshake, sent to a fixed, deployment-owned URL
    (never a caller-supplied one), and it is not a second admission path: it lands
    in the same application the HTTP API does, so the canonical limiter and
    account rules still decide what a subsequent request may do.
    """
    import asyncio
    import json

    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "revocompute-gateway-probe", "version": "1"},
            },
        }
    ).encode("utf-8")

    async def _run() -> tuple[bool, str]:
        import httpx

        # ``trust_env=False``: a deployment's HTTP(S)_PROXY must not silently
        # redirect this readiness check off the host, and no caller can influence
        # the destination.
        async with httpx.AsyncClient(timeout=GATEWAY_PROBE_TIMEOUT_SECONDS, trust_env=False) as client:
            response = await client.post(
                endpoint,
                content=body,
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            )
        return _initialize_result(response.status_code, response.headers.get("content-type", ""), response.text)

    try:
        return asyncio.run(_run())
    except Exception:  # noqa: BLE001 - reachability must never raise into a capability read
        return False, "the public MCP endpoint did not answer an initialize handshake"


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


__all__ = [
    "DEFAULT_MCP_PORT",
    "GATEWAY_PROBE_ENV",
    "GATEWAY_PROBE_TIMEOUT_SECONDS",
    "GATEWAY_PROBE_TTL_SECONDS",
    "GATEWAY_ROUTE_DIR",
    "GATEWAY_ROUTE_FILE",
    "LISTENER_STARTUP_TIMEOUT_SECONDS",
    "MCP_ENDPOINT",
    "MCP_PATH",
    "MCP_PROTOCOL_VERSION",
    "PUBLIC_BASE_URL_ENV",
    "SURFACE_PROBE_TIMEOUT_SECONDS",
    "gateway_endpoint",
    "gateway_reachable",
    "gateway_route_configured",
    "mcp_asgi",
    "mcp_enabled",
    "probe_gateway",
    "probe_surface",
    "serve",
    "start_companion_listener",
    "surface_status",
]
