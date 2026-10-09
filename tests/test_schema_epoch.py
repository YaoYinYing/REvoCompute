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


def test_current_task_database_adds_gpu_accounting_tables_without_resetting_tasks(
    tmp_path,
):
    path = tmp_path / "tasks.sqlite3"
    database = TaskDatabase(str(path))
    database.upsert_task(
        "a" * 32,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=1.0,
        status="pending",
        is_binary=0,
        task_type="demo",
        storage_key="alice",
        submitted_by_user_id=7,
        artifact_provenance="[]",
    )
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE resource_allocations")
        connection.exec_driver_sql("DROP TABLE resource_ledger")
    database.engine.dispose()

    reopened = TaskDatabase(str(path))

    assert reopened.get_task("a" * 32)["submitted_by_user_id"] == 7
    with reopened.engine.connect() as connection:
        tables = set(sa.inspect(connection).get_table_names())
    assert {"resource_ledger", "resource_allocations", "resource_policies"}.issubset(tables)


def test_released_resource_indexes_are_widened_in_place(tmp_path):
    """A database from the released revision gains the new index shape.

    ``(slurm_job_id, unit)`` is the allocation identity, because one Slurm
    allocation now records both its GPU and its CPU core-second facts: an index
    that still made the job id alone unique would refuse the second unit's row,
    and the live-reservation index has to cover both ownership modes or a queued
    Task could take a second reservation.
    """
    path = tmp_path / "tasks.sqlite3"
    database = TaskDatabase(str(path))
    database.upsert_task(
        "a" * 32,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=1.0,
        status="pending",
        is_binary=0,
        task_type="demo",
        storage_key="alice",
        submitted_by_user_id=7,
        artifact_provenance="[]",
    )
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX idx_resource_allocations_job_unit")
        connection.exec_driver_sql("DROP INDEX idx_resource_reservations_live_task")
    database.engine.dispose()

    reopened = TaskDatabase(str(path))

    with reopened.engine.connect() as connection:
        indexes = {
            index["name"]: index
            for index in sa.inspect(connection).get_indexes("resource_allocations")
        }
        reservation_indexes = {
            index["name"] for index in sa.inspect(connection).get_indexes("resource_reservations")
        }
    assert indexes["idx_resource_allocations_job_unit"]["column_names"] == [
        "slurm_job_id",
        "unit",
    ]
    assert indexes["idx_resource_allocations_job_unit"]["unique"] == 1
    assert "idx_resource_reservations_live_task" in reservation_indexes
    assert reopened.get_task("a" * 32)["submitted_by_user_id"] == 7


def test_a_released_publication_anchor_gains_the_charge_columns_as_pending(tmp_path):
    """A result_publications table from the released revision widens in place.

    The charge columns are additive and the migration is conservative: a
    publication that predates them was published, and whether it was charged is
    exactly what reconciliation must now establish, so it backfills to
    ``charge_bytes = NULL`` (an *unknown* amount, never a zero one) and
    ``charge_state = pending``.  The anchor's own identity columns are untouched,
    so a reader still verifies the same publication.
    """
    path = tmp_path / "tasks.sqlite3"
    database = TaskDatabase(str(path))
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO result_publications "
            "(task_id, manifest_sha256, manifest_size, revision, published_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("a" * 32, "f" * 64, 123, 1, 1.0),
        )
        connection.exec_driver_sql("ALTER TABLE result_publications DROP COLUMN charge_bytes")
        connection.exec_driver_sql("ALTER TABLE result_publications DROP COLUMN charge_state")
        connection.exec_driver_sql("ALTER TABLE result_publications DROP COLUMN charged_at")
    database.engine.dispose()

    reopened = TaskDatabase(str(path))

    with reopened.engine.connect() as connection:
        columns = {
            column["name"] for column in sa.inspect(connection).get_columns("result_publications")
        }
    assert {"charge_bytes", "charge_state", "charged_at"}.issubset(columns)
    row = reopened.get_result_publication("a" * 32)
    assert row["manifest_sha256"] == "f" * 64
    assert row["manifest_size"] == 123
    assert row["charge_bytes"] is None
    assert row["charge_state"] == "pending"


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
