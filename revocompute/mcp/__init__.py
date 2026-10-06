# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""First-class MCP interface for REvoCompute.

MCP is a protocol projection of the canonical service, not a new execution
plane.  See :mod:`revocompute.mcp.server` for the primitive surface and
:mod:`revocompute.mcp.asgi` for the transport.
"""

from __future__ import annotations

__all__ = ["MCP_PATH"]


def __getattr__(name: str) -> object:
    if name == "MCP_PATH":
        from revocompute.mcp.asgi import MCP_PATH

        return MCP_PATH
    raise AttributeError(name)
