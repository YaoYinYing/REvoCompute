# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Which role this server process runs, as a fact the process declares itself.

Two services import the canonical application (:mod:`revocompute.app`): the
Gunicorn web service and the MCP service (``python -m revocompute.mcp``, see
:mod:`revocompute.mcp.asgi`).  Importing it runs startup work that belongs to
exactly one of them -- the Operator Job pass that terminalizes a job left RUNNING
by a restart.  A second importer must not repeat that pass: merely starting the
MCP service would fail a job the web service is legitimately running.

The distinction is what a process *is*, not what a deployment configured, so the
MCP entrypoint declares its role here before it imports the application.  A role
is never inferred from the environment: ``MCP_ENABLED`` is set for both services,
and a caller-supplied switch could only ever be wrong.
"""

from __future__ import annotations

#: The MCP service: it projects a second protocol over the canonical
#: application, so it does not own that application's startup pass.
MCP_SERVICE = "mcp"

_role: str | None = None


def declare(role: str) -> None:
    """Record what this process is.  Called by a process entrypoint before it
    imports the canonical application."""
    global _role
    _role = role


def current() -> str | None:
    """The role this process declared, or ``None`` when it declared none."""
    return _role


def serves_canonical_application() -> bool:
    """Whether this process owns the canonical application's startup pass.

    ``True`` for the web service (the application's own home, including a
    process that imported it directly) and ``False`` for a process that imports
    it only to project another protocol over it.
    """
    return _role != MCP_SERVICE


__all__ = ["MCP_SERVICE", "current", "declare", "serves_canonical_application"]
