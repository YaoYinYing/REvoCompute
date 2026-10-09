# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""``python -m revocompute.mcp`` — start the MCP surface in this container.

The deployed default serves the MCP endpoint as a companion listener inside the
canonical web process (``revocompute.app`` starts it), so the rate limiter and
admission path are shared.  This entrypoint exists for two cases: a deployment
that runs the MCP listener apart from the web process (interoperability testing,
or deliberate resource isolation), and a health check that only needs the
endpoint to answer.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"-h", "--help"}:
        print("Usage: python -m revocompute.mcp [--serve]")
        return 0
    from revocompute.mcp.asgi import serve

    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
