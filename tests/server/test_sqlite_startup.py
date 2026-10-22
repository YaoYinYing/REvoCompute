# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The startup WAL conversion must lose a race benignly and fail closed otherwise.

Every service of a multi-process deployment (web, worker, maintenance, MCP)
imports the canonical application, so each one runs the same SQLite startup pass
over the same shared server directory.  Converting a database to WAL takes a
brief exclusive lock and SQLite will not wait for a lock *upgrade*, so a peer
holding it makes the statement raise ``database is locked`` immediately.  That
is a race, and it must be retried; a corrupt file, a permissions failure, or any
other error is not a race, and must reach the caller.

These cases drive the real helper with a connection double that raises exactly
the way SQLite does, so the classification -- which errors are retried and which
are re-raised -- is what is under test rather than a message string anywhere.
"""

from __future__ import annotations

import sqlite3

import pytest

from revocompute.sqlite_startup import JOURNAL_MODE_ATTEMPTS, enter_wal_mode


class _RunSql:
    """A ``run_sql`` double: fails as scripted, then records every statement."""

    def __init__(self, failures: list[BaseException]) -> None:
        self.failures = list(failures)
        self.statements: list[str] = []

    def __call__(self, statement: str) -> None:
        if self.failures:
            failed = self.failures.pop(0)
            if failed is not None:
                raise failed
        self.statements.append(statement)


def test_a_transient_lock_is_retried_until_wal_mode_is_reached():
    locked = sqlite3.OperationalError("database is locked")
    run_sql = _RunSql([locked, None])

    assert enter_wal_mode(run_sql) is True
    # First attempt lost the race, the retry reached WAL mode and set the
    # matching durability pragma.
    assert run_sql.statements == ["PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL"]


def test_a_lock_held_for_every_attempt_is_reported_not_raised():
    """Exhausting the retries is a "not in WAL mode", not a process exit."""
    run_sql = _RunSql([sqlite3.OperationalError("database is locked")] * JOURNAL_MODE_ATTEMPTS)

    assert enter_wal_mode(run_sql) is False
    assert run_sql.statements == []


def test_any_other_error_is_not_retried_and_reaches_the_caller():
    """Real breakage -- a corrupt or unreadable database -- must still fail closed."""
    attempts: list[str] = []

    def corrupt(statement: str) -> None:
        attempts.append(statement)
        raise sqlite3.DatabaseError("file is not a database")

    with pytest.raises(sqlite3.DatabaseError):
        enter_wal_mode(corrupt)
    assert attempts == ["PRAGMA journal_mode=WAL"], "a non-lock error must not be retried"


def test_a_lock_from_the_engine_layer_is_classified_by_its_message():
    """A SQLAlchemy ``OperationalError`` carries the sqlite text; it is retried too."""

    class _EngineLockError(Exception):
        def __str__(self) -> str:
            return "(sqlite3.OperationalError) database is locked"

    run_sql = _RunSql([_EngineLockError(), None])

    assert enter_wal_mode(run_sql) is True
    assert run_sql.statements == ["PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL"]
