# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Serve the MCP streamable-HTTP endpoint from its own supervised process.

The MCP surface runs as the dedicated ``revocompute-mcp`` entrypoint
(:func:`serve`), declared as the ``mcp`` service of ``docker-compose.mcp.yml``.
That process imports the canonical application and invokes the canonical handlers
in process, so an MCP call terminates in exactly the code the HTTP API and the
Web application run: MCP is a protocol projection over one application, never a
second admission path and never a second authorization rule.

Why a dedicated process, and not a listener inside the Gunicorn web process: the
web service is started with ``--preload`` and two workers, so anything started at
import time happens in the master *before* it forks, and a running thread does not
survive a fork.  A listener started there would have its event loop in the master
(unsupervised, and re-forked on every worker recycle) while each worker held its
own pre-fork copy of the pre-fork objects.  The dedicated service has no fork in
its path at all, and Gunicorn never hosts an ASGI event loop.

What the two processes share is the truth that was never in memory: the
Redis-backed rate limiter (``revocompute.ratelimit``), and the SQLite stores
both read under the shared server directory -- user, Task, admin config, Tool
call, MCP handle, and Operator Job records.  What they do not share is the rate
limiter's in-memory fallback, which is per process by construction and used only
while Redis is unavailable (``revocompute.ratelimit`` documents it as not
distributed), and the canonical application's Operator Job restart pass, which
is a startup action the web service owns alone: :func:`serve` declares this
process's role before it imports the application, so starting or restarting the
MCP service cannot terminalize a job the web service is running.  That is the
whole list: no in-memory application state crosses the boundary, and nothing in
this module claims otherwise.

The ASGI stack is the optional ``mcp`` extra.  A deployment that never opts in
builds no image carrying it, layers no overlay, and writes no gateway route, so
it serves the HTTP API and Web application exactly as before.
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

#: Internal port of the MCP service.  Bound by the ``mcp`` service of
#: ``docker-compose.mcp.yml`` inside the compose network and proxied by the
#: deployment gateway, which also fronts the HTTP API port.  The deployment
#: publishes neither directly.
DEFAULT_MCP_PORT = 8081

#: Gateway route state, reconciled from ``MCP_ENABLED`` by ``run/restart.sh`` and
#: written under ``SERVER_DIR`` — the one directory both the deployment host and
#: the web process see.  The route is what turns the internal MCP service into the
#: public endpoint, so its absence is exactly the state in which an agent host
#: cannot reach the surface however healthy the service is.
GATEWAY_ROUTE_DIR = "mcp-gateway"
GATEWAY_ROUTE_FILE = "mcp.conf"

#: A route the gateway actually serves must declare the MCP location prefix.
#: Presence alone is not the fact: a truncated, empty, or unrelated file left
#: behind would otherwise be read as a live route.
_GATEWAY_ROUTE_RE = re.compile(r"^\s*location\s+/k/", re.MULTILINE)

#: The public endpoint every deployment serves the application on.  The gateway
#: route proxies ``/k/`` to the MCP service, so an agent host reaches the
#: surface at this same-origin public base joined with :data:`MCP_ENDPOINT` —
#: never at the service's container-internal port.  It is *public
#: deployment* identity: it holds no credential, no container-internal port and
#: no host path, and a process may hold it without owning any infrastructure
#: secret.
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

#: How long :func:`service_reachable` waits when it really reaches the MCP
#: service over the compose network.  Reaching out is a network call, so the
#: deadline is bounded and a timeout is a *negative* answer rather than a hang on
#: a capability request.
SERVICE_PROBE_TIMEOUT_SECONDS = 3.0

#: How long one MCP-service verdict stays fresh, on the same rule as
#: :data:`GATEWAY_PROBE_TTL_SECONDS`: a sustained capability read is mostly a
#: memory read, while a service that stops answering (or starts again) is
#: reported without a restart of the process that reads the capability.
SERVICE_PROBE_TTL_SECONDS = 30.0

#: The compose service the MCP surface runs as, and therefore the host the
#: canonical web process dials for the *service* fact.  It is deployment-owned
#: topology from the environment, never a caller-supplied destination, so no
#: request can point the readiness probe anywhere.
MCP_SERVICE_ENV = "MCP_SERVICE"

#: The name ``docker-compose.mcp.yml`` declares for that service.  A deployment
#: that renamed it sets :data:`MCP_SERVICE_ENV`; the default matches the shipped
#: overlay so the ordinary opt-in needs no extra setting.
DEFAULT_MCP_SERVICE = "mcp"

_LOGGER = logging.getLogger(__name__)

#: Result of the last MCP-*service* reach, keyed by the destination it was proven
#: against (host and port) and stamped with the ``time.monotonic()`` of the probe
#: that produced it, so the answer expires on :data:`SERVICE_PROBE_TTL_SECONDS`
#: rather than lasting for the life of the process.  ``None`` means "not probed
#: yet".
_SERVICE_PROBE: dict[str, Any] = {"target": None, "result": None, "at": None}

#: Single-flight guard for the MCP-service reach, on the same rule as
#: :data:`_GATEWAY_PROBE_LOCK`: one capability read refreshes an expired verdict,
#: and a concurrent read that finds it expired returns fail-closed rather than
#: piling a second bounded request onto a service that may already be down.
_SERVICE_PROBE_LOCK = threading.Lock()

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


def _service_target() -> tuple[str, int] | None:
    """The compose destination of the MCP service, or ``None`` when unset.

    Deployment-owned topology read from the environment: the service name and the
    container-internal port ``docker-compose.mcp.yml`` publishes to the compose
    network.  No part of it comes from a request, so a caller cannot choose where
    this process dials.
    """
    host = os.environ.get(MCP_SERVICE_ENV, "").strip() or DEFAULT_MCP_SERVICE
    try:
        port = int(os.environ.get("MCP_PORT", "").strip() or DEFAULT_MCP_PORT)
    except ValueError:
        port = DEFAULT_MCP_PORT
    return host, port


def service_reachable() -> bool | None:
    """Whether the MCP service answers an ``initialize`` on the compose network.

    The MCP surface is its own process, so "is it serving?" is a fact about
    another process that this one can only observe by asking it.  This drives the
    same pre-credential handshake an agent host performs first against the fixed,
    deployment-owned destination :func:`_service_target` resolves -- never a
    caller-supplied URL -- and reports it as ``True`` / ``False``, or ``None``
    when no destination is known or another read is already refreshing an expired
    verdict (fail-closed, exactly as :func:`gateway_reachable` does).

    A verdict is fresh only while it is younger than
    :data:`SERVICE_PROBE_TTL_SECONDS`, so a service that stops answering is
    reported not-ready and one that recovers is reported ready again, both without
    restarting the web process.  The refresh is single-flight.
    """
    target = _service_target()
    if target is None:
        return None
    at = _SERVICE_PROBE["at"]
    if (
        _SERVICE_PROBE["target"] == target
        and _SERVICE_PROBE["result"] is not None
        and at is not None
        and time.monotonic() - at < SERVICE_PROBE_TTL_SECONDS
    ):
        return bool(_SERVICE_PROBE["result"])
    if not _SERVICE_PROBE_LOCK.acquire(blocking=False):
        return None
    try:
        reachable, _ = probe_endpoint(f"http://{target[0]}:{target[1]}{MCP_ENDPOINT}")
        _SERVICE_PROBE.update({"target": target, "result": reachable, "at": time.monotonic()})
    finally:
        _SERVICE_PROBE_LOCK.release()
    if not reachable:
        _LOGGER.warning("MCP service %s:%s did not answer an initialize handshake", target[0], target[1])
    return reachable


def serve() -> None:
    """Run the MCP ASGI service (the ``revocompute-mcp`` entrypoint).

    This *is* the deployed MCP process: ``docker-compose.mcp.yml`` runs
    ``python -m revocompute.mcp`` as the ``mcp`` service, and the deployment
    gateway proxies ``/k/`` to the port bound here.  Importing the canonical
    application first is what makes a request that arrives over MCP terminate in
    the same application, authorization, admission, and persistence code the HTTP
    API runs.
    """
    import uvicorn

    from revocompute.config import env_int
    from revocompute.process_role import MCP_SERVICE, declare

    # Declare what this process is *before* importing the canonical application.
    # The application runs one startup pass that belongs to the service that owns
    # it -- terminalizing an Operator Job left RUNNING by a restart -- and this
    # process only projects another protocol over that application, so repeating
    # the pass here would fail a job the web service is legitimately running.
    declare(MCP_SERVICE)
    # Import the canonical application: this process serves the MCP protocol over
    # it, so the canonical handlers, user database, and Task store are the ones
    # every call reaches.  Gunicorn is not involved, so nothing here forks.
    import revocompute.app  # noqa: F401

    port = env_int("MCP_PORT", DEFAULT_MCP_PORT)
    # Binds all interfaces inside the compose network; the port is never
    # published and only the deployment gateway reaches it.
    uvicorn.run(mcp_asgi(), host="0.0.0.0", port=port, log_level=os.environ.get("MCP_LOG_LEVEL", "info"))  # nosec B104


def mcp_enabled() -> bool:
    """Whether this deployment opted in to serving the MCP surface.

    The switch is a deployment fact, so it is read from the environment directly
    rather than from a Flask app: the service and any capability this process
    reports must be decided by the same value, or the two can disagree.
    """
    from revocompute.config import env_bool

    return env_bool("MCP_ENABLED", False)


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
    deployment identity, not infrastructure: the MCP service's container-internal
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
    the same-origin public URL the gateway serves to an agent host.  Nothing here
    forwards a caller-supplied target, so no SSRF surface is introduced.

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
    deployment gateway an agent host would use.  An answering MCP service, or a
    route file on disk, are not that fact: a stale config, a gateway that never
    reloaded, or an upstream that is down all leave both true while nothing
    external answers.  So the capability reports each fact separately and gates
    ``operational`` on the *reach* alone:

    ``listener_ready``    the MCP service answered an ``initialize`` handshake at
                          the destination this deployment dials for it;
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
    caller-supplied URL.  The service reach is bounded in time on the same rule as
    the gateway reach, so a service that stops answering stops being reported
    ready, and one that recovers is reported ready again, both without restarting
    this process; the route is re-read on every call, because ``restart.sh``
    reconciles it without restarting this process and a long-lived answer must not
    outlive the route it describes.  While a refresh is in flight a concurrent
    read reports the refreshed fact as ``None``/not-ready and advertises nothing
    (see :func:`service_reachable` and :func:`gateway_reachable`).
    """
    # The default, and not a problem: nothing was asked for.
    if not mcp_enabled():
        return _capability(False, False, None, endpoint=None, detail=None)
    route_configured = gateway_route_configured()
    service = service_reachable()
    if service is not True:
        # Enabled, but nothing answers: the service is down, unbuilt, or a switch
        # set without a restart.  Never a silent "off".
        return _capability(False, route_configured, None, endpoint=None, detail=_listener_detail())
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
    """Assemble the capability document from the independent facts.

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
    """A fixed reason the MCP service is not answering.

    The destination and any transport error are operator detail and may name the
    service host and port, so they stay in the log and the log-only fields; the
    public capability carries one fixed sentence.
    """
    return "the MCP service is not answering on this deployment"


def probe_endpoint(endpoint: str, *, timeout: float = SERVICE_PROBE_TIMEOUT_SECONDS) -> tuple[bool, str]:
    """Drive one MCP ``initialize`` against one fixed, deployment-owned endpoint.

    The same pre-credential handshake an agent host sends first, over streamable
    HTTP, against a destination this deployment resolved itself -- the MCP
    service on the compose network, or this deployment's own public base URL
    through the gateway.  A caller never supplies the target, so no SSRF surface
    is introduced, and the request lands in the same application the HTTP API
    runs, so it is not a second admission path.
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
                "clientInfo": {"name": "revocompute-surface-probe", "version": "1"},
            },
        }
    ).encode("utf-8")

    async def _run() -> tuple[bool, str]:
        import httpx

        # ``trust_env=False``: a deployment's HTTP(S)_PROXY must not silently
        # redirect this readiness check off the host, and no caller can influence
        # the destination.
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(
                endpoint,
                content=body,
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            )
        return _initialize_result(response.status_code, response.headers.get("content-type", ""), response.text)

    try:
        return asyncio.run(_run())
    except Exception:  # noqa: BLE001 - reachability must never raise into a capability read
        return False, "the MCP endpoint did not answer an initialize handshake"


def probe_gateway(endpoint: str) -> tuple[bool, str]:
    """Drive one MCP ``initialize`` against the deployment's *public* endpoint.

    The service reach proves the MCP process answers inside the compose network;
    this proves the endpoint an agent host actually uses, through the deployment
    gateway.  It is :func:`probe_endpoint` against the fixed, deployment-owned URL
    :func:`gateway_endpoint` builds, on :data:`GATEWAY_PROBE_TIMEOUT_SECONDS`.
    """
    return probe_endpoint(endpoint, timeout=GATEWAY_PROBE_TIMEOUT_SECONDS)


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
    "DEFAULT_MCP_SERVICE",
    "GATEWAY_PROBE_ENV",
    "GATEWAY_PROBE_TIMEOUT_SECONDS",
    "GATEWAY_PROBE_TTL_SECONDS",
    "GATEWAY_ROUTE_DIR",
    "GATEWAY_ROUTE_FILE",
    "MCP_ENDPOINT",
    "MCP_PATH",
    "MCP_PROTOCOL_VERSION",
    "MCP_SERVICE_ENV",
    "PUBLIC_BASE_URL_ENV",
    "SERVICE_PROBE_TIMEOUT_SECONDS",
    "SERVICE_PROBE_TTL_SECONDS",
    "gateway_endpoint",
    "gateway_reachable",
    "gateway_route_configured",
    "mcp_asgi",
    "mcp_enabled",
    "probe_endpoint",
    "probe_gateway",
    "serve",
    "service_reachable",
    "surface_status",
]
