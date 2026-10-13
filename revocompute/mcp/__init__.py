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
    """The MCP surface this process can actually answer, as a capability projection.

    The canonical HTTP surface reads its capability through this accessor, so the
    "deployed?" answer a browser is offered is the *listener's* readiness — the
    endpoint is advertised only when a listener really bound in this process —
    rather than the ``MCP_ENABLED`` switch that asked for one.  The import is
    local because ``revocompute.mcp.asgi`` pulls the ASGI stack the HTTP-only
    deployment deliberately does not install; a deployment without the stack has
    no listener and reports the surface absent.
    """
    from revocompute.mcp.asgi import surface_status

    return surface_status()
