# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""``python -m revocompute.mcp`` -- run the MCP surface as its own process.

This is the deployed MCP service: ``docker-compose.mcp.yml`` declares it as the
``mcp`` service and the deployment gateway proxies ``/k/`` to the port it binds.
It is a separate process from the Gunicorn web service on purpose.  The web
service preloads the application and forks workers, so a listener started at
import time would leave its event loop in the master and be re-forked on every
worker recycle; running the MCP surface here means no fork ever sits between
starting it and serving on it, and Gunicorn never hosts an ASGI event loop.

The MCP process imports the canonical application and reaches the canonical
handlers in process, so the authorization, admission, readiness, quota, and
result rules are the ones the HTTP API enforces.  What it shares with the web
service is the durable truth: the Redis-backed rate limiter and the SQLite
stores both processes read under the shared server directory (user, Task, admin
config, Tool call, MCP handle, and Operator Job records).  The rate limiter's
in-memory fallback is per process, by construction, and is used only while Redis
is unavailable.  No in-memory application state is shared between the two
processes, and this process does not repeat the canonical application's startup
pass -- it declares its role before importing it, so starting or restarting the
MCP service cannot terminalize an Operator Job the web service is running.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"-h", "--help"}:
        print("Usage: python -m revocompute.mcp")
        return 0
    from revocompute.mcp.asgi import serve

    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
