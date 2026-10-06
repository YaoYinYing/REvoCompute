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
import threading
from typing import Any

#: Public path prefix for the MCP surface.  The streamable-HTTP endpoint is at
#: ``/k/mcp``; the prefix is short and does not collide with an existing route.
MCP_PATH = "/k"

#: Internal port of the companion MCP listener.  Bound inside the web container
#: and proxied by the deployment gateway, which also fronts the HTTP API port.
#: The deployment publishes neither directly.
DEFAULT_MCP_PORT = 8081

_LOGGER = logging.getLogger(__name__)


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


def start_companion_listener() -> threading.Thread | None:
    """Start the MCP ASGI listener in a daemon thread of this process.

    The listener shares this process's memory, so the canonical rate limiter,
    the loaded application, and every in-process admission decision are the same
    objects the HTTP API uses.  Returns ``None`` when MCP is disabled or the
    optional ASGI stack is missing, so the HTTP API is never affected by an
    absent extra.
    """
    import os

    from revocompute.config import env_bool, env_int

    # Opt-in: the listener is off unless the deployment turns it on, so an
    # ordinary import (a worker, a maintenance process, a test) never binds a
    # port or spawns a thread.
    if not env_bool("MCP_ENABLED", False):
        return None
    try:
        import uvicorn
    except ImportError:
        _LOGGER.info("MCP listener not started: the optional 'mcp' extra is not installed")
        return None

    host = os.environ.get("MCP_HOST", "0.0.0.0")  # noqa: S104 - container-internal bind
    port = env_int("MCP_PORT", DEFAULT_MCP_PORT)
    config = uvicorn.Config(mcp_asgi(), host=host, port=port, log_level=os.environ.get("MCP_LOG_LEVEL", "warning"))
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="mcp-asgi", daemon=True)
    thread.start()
    _LOGGER.info("MCP surface listening on %s:%s%s", host, port, MCP_PATH)
    return thread


__all__ = ["DEFAULT_MCP_PORT", "MCP_PATH", "mcp_asgi", "serve", "start_companion_listener"]
