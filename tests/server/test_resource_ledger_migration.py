# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Migration of pre-canonical GPU-credit history into the resource ledger.

The ledger is the system of record for what was consumed, so a deployment that
already has GPU history must keep every one of those facts — same quantity, same
kind, same actor, same reason, same timestamp — while gaining the canonical
``(subject, unit, resource class)`` shape.  These tests build a real
pre-canonical database, open it through the current code, and check the facts
survived and remain reachable through the canonical read path.
"""

from __future__ import annotations

import sqlite3

from revocompute.db import TaskDatabase

# The pre-canonical schema, exactly as the deployed revision created it.  Kept
# as literal DDL rather than imported from the current code because the point of
# the test is a database that no longer has a writer in this tree.
LEGACY_SCHEMA = """
CREATE TABLE gpu_credit_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    period VARCHAR(7) NOT NULL,
    kind VARCHAR NOT NULL,
    gpu_seconds INTEGER NOT NULL,
    task_id VARCHAR(32),
    stage_id VARCHAR,
    slurm_job_id VARCHAR,
    actor_user_id INTEGER,
    reason TEXT,
    idempotency_key VARCHAR NOT NULL UNIQUE,
    created_at FLOAT NOT NULL
);
CREATE TABLE gpu_credit_policies (
    user_id INTEGER PRIMARY KEY,
    monthly_gpu_seconds INTEGER NOT NULL,
    updated_by_user_id INTEGER NOT NULL,
    updated_at FLOAT NOT NULL
);
CREATE TABLE gpu_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    task_id VARCHAR(32) NOT NULL,
    stage_id VARCHAR NOT NULL,
    slurm_job_id VARCHAR NOT NULL UNIQUE,
    gpu_count INTEGER NOT NULL,
    started_at FLOAT NOT NULL,
    finished_at FLOAT,
    gpu_seconds INTEGER,
    status VARCHAR NOT NULL,
    ledger_entry_id INTEGER
);
"""

# (period, kind, gpu_seconds, task_id, slurm_job_id, reason, idempotency_key)
LEGACY_LEDGER_ROWS = (
    ("2026-08", "monthly_grant", 60_000, None, None, "UTC calendar-month allowance", "monthly_grant:7:2026-08"),
    ("2026-08", "usage", -900, "t" * 32, "8801", "Actual Slurm allocation time", "usage:8801"),
    ("2026-08", "admin_adjustment", -600, None, None, "Correct duplicate grant", "admin_adjustment:7:correction-a"),
    ("2026-08", "admin_reset", 1_500, None, None, "Quarterly refresh", "admin_reset:7:refresh-a"),
)

# (user_id, task, stage, job, gpus, started, finished, gpu_seconds, status)
LEGACY_ALLOCATION_ROWS = (
    (7, "t" * 32, "model", "8801", 3, 1_787_227_200.0, 1_787_228_500.0, 900, "settled"),
    (7, "u" * 32, "model", "8802", 1, 1_787_230_800.0, None, None, "active"),
)


def _build_legacy_database(path: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(LEGACY_SCHEMA)
        connection.executemany(
            "INSERT INTO gpu_credit_ledger "
            "(user_id, period, kind, gpu_seconds, task_id, slurm_job_id, actor_user_id, reason, "
            " idempotency_key, created_at) "
            "VALUES (7, ?, ?, ?, ?, ?, 9, ?, ?, ?)",
            [(*row, 1_787_227_200.0) for row in LEGACY_LEDGER_ROWS],
        )
        connection.execute(
            "INSERT INTO gpu_credit_policies (user_id, monthly_gpu_seconds, updated_by_user_id, updated_at) "
            "VALUES (7, 72000, 9, ?)",
            (1_787_227_200.0,),
        )
        connection.executemany(
            "INSERT INTO gpu_allocations "
            "(user_id, task_id, stage_id, slurm_job_id, gpu_count, started_at, finished_at, gpu_seconds, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            LEGACY_ALLOCATION_ROWS,
        )
        connection.commit()
    finally:
        connection.close()


def _tables(path: str) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()


def test_legacy_gpu_history_migrates_without_rewriting_facts(tmp_path):
    path = str(tmp_path / "tasks.sqlite3")
    _build_legacy_database(path)

    database = TaskDatabase(path)

    tables = _tables(path)
    assert "gpu_credit_ledger" not in tables
    assert "gpu_allocations" not in tables
    assert "gpu_credit_policies" not in tables
    assert {"resource_ledger", "resource_allocations", "resource_policies"} <= tables

    ledger = database.list_compute_ledger(7, period="2026-08")
    # Every recorded fact survives, with its quantity, kind, actor, reason, and
    # timestamp unchanged; only the subject pair, the unit, and the key spelling
    # are normalized.  The list is newest-first, so compare as a multiset.
    assert sorted((entry["kind"], entry["quantity"]) for entry in ledger) == [
        ("admin_adjustment", -600),
        ("admin_reset", 1_500),
        ("monthly_grant", 60_000),
        ("usage", -900),
    ]
    usage = next(entry for entry in ledger if entry["kind"] == "usage")
    assert usage["task_id"] == "t" * 32
    assert usage["slurm_job_id"] == "8801"
    assert usage["quantity"] == -900
    assert all(entry["subject_type"] == "user" and entry["subject_id"] == 7 for entry in ledger)
    assert all(entry["unit"] == "gpu_second" for entry in ledger)
    assert all(entry["created_at"] == 1_787_227_200.0 for entry in ledger)
    # The projection still sums to the balance the deployment last reported:
    # the migrated period grant, the migrated administrative adjustments (a
    # -600 correction and a +1_500 reset), and the migrated allocation as the
    # settled usage.  One allocation is still running, so it stays unsettled.
    entitlement = database.compute_entitlement(7, at=1_787_227_200.0)
    assert entitlement.allowance == 60_000 - 600 + 1_500
    assert entitlement.used == 900
    assert entitlement.unsettled == 1


def test_migrated_allocations_stay_visible_and_settle_in_place(tmp_path):
    path = str(tmp_path / "tasks.sqlite3")
    _build_legacy_database(path)

    database = TaskDatabase(path)

    unsettled = database.list_unsettled_allocations()
    assert [row["slurm_job_id"] for row in unsettled] == ["8802"]
    assert unsettled[0]["resource_count"] == 1
    assert unsettled[0]["quantity"] is None
    assert unsettled[0]["evidence_source"] == "allocation_lifecycle"

    # A migrated allocation settles through the canonical path like any other.
    settled = database.settle_allocation_elapsed("8802", elapsed_seconds=120, finished_at=1_787_233_200.0)
    assert settled["quantity"] == 120
    assert settled["status"] == "settled"
    assert database.compute_entitlement(7, at=1_787_233_200.0).used == 1_020


def test_migration_is_idempotent_across_a_second_start(tmp_path):
    path = str(tmp_path / "tasks.sqlite3")
    _build_legacy_database(path)

    TaskDatabase(path)
    second = TaskDatabase(path)

    # Reopening an already-migrated database appends nothing and drops nothing.
    assert len(second.list_compute_ledger(7)) == len(LEGACY_LEDGER_ROWS)
    assert second.compute_entitlement(7, at=1_787_227_200.0).used == 900


def test_migrated_ledger_is_still_append_only(tmp_path):
    path = str(tmp_path / "tasks.sqlite3")
    _build_legacy_database(path)
    TaskDatabase(path)

    connection = sqlite3.connect(path)
    try:
        for statement in (
            "UPDATE resource_ledger SET quantity = 0",
            "DELETE FROM resource_ledger",
        ):
            try:
                connection.execute(statement)
            except sqlite3.IntegrityError as exc:
                assert "append-only" in str(exc)
            else:  # pragma: no cover - the trigger is the guarantee under test
                raise AssertionError(f"append-only guard did not reject: {statement}")
    finally:
        connection.close()
