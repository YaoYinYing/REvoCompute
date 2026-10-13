# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""First-class MCP interface for REvoCompute.

MCP is a protocol projection of the canonical service, not a new execution
plane.  See :mod:`revocompute.mcp.server` for the primitive surface and
:mod:`revocompute.mcp.asgi` for the transport.
"""

from __future__ import annotations

__all__ = ["MCP_PATH", "surface"]


def __getattr__(name: str) -> object:
    if name == "MCP_PATH":
        from revocompute.mcp.asgi import MCP_PATH

        return MCP_PATH
    raise AttributeError(name)


def surface() -> dict[str, object]:
    """The MCP surface a client can actually reach, as a capability projection.

    The canonical HTTP surface reads its capability through this accessor, so the
    "deployed?" answer a browser is offered is the *reachable endpoint* — the
    listener bound and answered a real MCP ``initialize`` handshake in this
    process, and the deployment gateway serves the route that fronts it — rather
    than the ``MCP_ENABLED`` switch that asked for one.  A listener-only answer is
    not enough: the endpoint a browser or agent host is offered is reached through
    the gateway, so a healthy loopback listener behind a missing gateway route is
    still not connectable.  The import is local because ``revocompute.mcp.asgi``
    pulls the ASGI stack the HTTP-only deployment deliberately does not install; a
    deployment without the stack has no listener and reports the surface absent.
    """
    from revocompute.mcp.asgi import surface_status

    return surface_status()
