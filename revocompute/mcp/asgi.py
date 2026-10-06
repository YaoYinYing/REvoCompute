# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Serve the MCP streamable-HTTP endpoint as a first-class process role.

The MCP surface is a protocol adapter over the same application the ``web`` and
``worker`` roles already run.  It is deployed exactly like them -- the same
image, the same environment, the same volumes, a different command -- so it is
not a new service with its own truth; it is another process over one code base.

The endpoint is reachable at ``/k/mcp`` once the deployment's gateway routes
``/k`` to this process.  Every request therefore keeps the deployment's existing
TLS and network boundary, and the bearer/API-key credentials the process
verifies are the canonical credentials verified by the canonical user database.
"""

from __future__ import annotations

from typing import Any

#: Public path prefix for the MCP surface.  The streamable-HTTP endpoint is at
#: ``/k/mcp``; the prefix is short and does not collide with an existing route.
MCP_PATH = "/k"

#: Default internal port for the MCP process.  Never published; the gateway
#: proxies to it inside the compose network, like the web role's port.
DEFAULT_MCP_PORT = 8081


def mcp_asgi() -> Any:
    """Return the ASGI application serving the MCP endpoint."""
    from starlette.applications import Starlette
    from starlette.routing import Mount

    from revocompute.mcp.server import build_server

    mcp_app = build_server().streamable_http_app()
    return Starlette(routes=[Mount(MCP_PATH, app=mcp_app)])


def serve() -> None:
    """Run the MCP ASGI endpoint (the ``revocompute-mcp`` console entrypoint)."""
    import os

    import uvicorn

    from revocompute.config import env_int

    port = env_int("MCP_PORT", DEFAULT_MCP_PORT)
    # Binds all interfaces inside the container; the port is never published and
    # only the deployment gateway reaches it, mirroring the web role.
    uvicorn.run(mcp_asgi(), host="0.0.0.0", port=port, log_level=os.environ.get("MCP_LOG_LEVEL", "info"))  # nosec B104


__all__ = ["DEFAULT_MCP_PORT", "MCP_PATH", "mcp_asgi", "serve"]
