# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Fresh-schema bootstrap and fail-fast personal-task epoch coverage."""

from __future__ import annotations

import sqlite3

import pytest
import sqlalchemy as sa
from revocompute.auth import UserDatabase
from revocompute.db import TaskDatabase


def test_fresh_empty_and_current_databases_boot_and_reopen(tmp_path):
    user_path = tmp_path / "users.sqlite3"
    task_path = tmp_path / "tasks.sqlite3"
    user_path.touch()
    task_path.touch()

    users = UserDatabase(str(user_path))
    user = users.create_user("alice", "alice@example.test", "password")
    tasks = TaskDatabase(str(task_path))
    users.engine.dispose()
    tasks.engine.dispose()

    reopened_users = UserDatabase(str(user_path))
    reopened_tasks = TaskDatabase(str(task_path))
    assert reopened_users.get_user(user["id"])["storage_key"] == user["storage_key"]
    assert reopened_tasks.list_tasks() == []


def test_current_user_database_adds_access_tables_without_resetting_accounts(tmp_path):
    path = tmp_path / "users.sqlite3"
    database = UserDatabase(str(path))
    user = database.create_user("alice", "alice@example.test", "password")
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE user_entitlements")
        connection.exec_driver_sql("DROP TABLE access_requests")
        connection.exec_driver_sql("DROP TABLE runner_access_events")
    database.engine.dispose()

    reopened = UserDatabase(str(path))
    assert reopened.get_user(user["id"])["username"] == "alice"
    with reopened.engine.connect() as connection:
        tables = set(sa.inspect(connection).get_table_names())
    assert {"users", "user_entitlements", "access_requests", "runner_access_events"}.issubset(tables)


def test_project_era_task_schema_fails_without_altering_rows(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    current = TaskDatabase(str(path))
    current.engine.dispose()
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE tasks ADD COLUMN scope_type VARCHAR")
    conn.execute("ALTER TABLE tasks ADD COLUMN scope_id VARCHAR")
    original_columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    conn.close()

    with pytest.raises(RuntimeError, match="(?s)personal-task ownership/storage schema epoch.*obsolete columns"):
        TaskDatabase(str(path))

    conn = sqlite3.connect(path)
    assert {row[1] for row in conn.execute("PRAGMA table_info(tasks)")} == original_columns
    conn.close()


def test_project_era_runner_audit_schema_fails_without_mutation(tmp_path):
    path = tmp_path / "users.sqlite3"
    database = UserDatabase(str(path))
    database.engine.dispose()
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE runner_access_events ADD COLUMN scope_type VARCHAR")
    conn.execute("ALTER TABLE runner_access_events ADD COLUMN scope_id VARCHAR")
    original_columns = {row[1] for row in conn.execute("PRAGMA table_info(runner_access_events)")}
    conn.close()

    with pytest.raises(RuntimeError, match="runner_access_events has obsolete columns"):
        UserDatabase(str(path))

    conn = sqlite3.connect(path)
    assert {row[1] for row in conn.execute("PRAGMA table_info(runner_access_events)")} == original_columns
    conn.close()
