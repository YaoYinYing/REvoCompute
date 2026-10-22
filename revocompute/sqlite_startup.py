# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Reach WAL mode from a startup pass that other services may be running at once.

Every service of a multi-process deployment opens the same SQLite stores at
startup: the web service (``gunicorn --preload -w 2``), the MCP service
(``python -m revocompute.mcp``), the worker, and the maintenance manager all
import the canonical application, so each one runs the same pass over the same
shared server directory.  ``PRAGMA journal_mode=WAL`` is not a read: converting
a database to WAL needs a brief exclusive lock, and SQLite deliberately refuses
to make the caller wait for a lock *upgrade* (waiting could deadlock against a
peer that is already reading), so it raises ``OperationalError: database is
locked`` immediately even when ``busy_timeout`` is set.  The loser of that race
would otherwise exit the process on the first boot of a fresh deployment.

The retry is bounded and narrow on purpose: it tolerates exactly that transient
lock, and any other error -- a corrupt file, a permissions failure, a real I/O
fault -- still propagates, because those are not races and must not be hidden.
The exhausted-retry arm proceeds with the default pragmas rather than exit, which
is the same call :meth:`revocompute.db.TaskDatabase` already makes for the
identical case; the connection stays usable, it is simply not in WAL mode for
this process.
"""

from __future__ import annotations

import time
from collections.abc import Callable

#: Attempts made before giving up on WAL mode for this process.
JOURNAL_MODE_ATTEMPTS = 3


def enter_wal_mode(run_sql: Callable[[str], object], *, attempts: int = JOURNAL_MODE_ATTEMPTS) -> bool:
    """Set ``journal_mode=WAL`` and ``synchronous=NORMAL``, tolerating a peer's lock.

    *run_sql* executes one SQL string on the caller's own connection, so this
    works for a raw :mod:`sqlite3` connection (``conn.execute``) and for a
    SQLAlchemy connection (``conn.exec_driver_sql``) without either having to
    expose a second connection API.  Returns ``True`` when WAL mode was reached,
    ``False`` when a peer held the lock for every attempt.
    """
    for attempt in range(attempts):
        try:
            run_sql("PRAGMA journal_mode=WAL")
            run_sql("PRAGMA synchronous=NORMAL")
            return True
        except Exception as exc:  # noqa: BLE001 - classified by message below
            if "database is locked" not in str(exc).lower():
                raise
            if attempt == attempts - 1:
                return False
            time.sleep(0.2 * (attempt + 1))
    return False  # unreachable for attempts >= 1; keeps the contract explicit


__all__ = ["JOURNAL_MODE_ATTEMPTS", "enter_wal_mode"]
