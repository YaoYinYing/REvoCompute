# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Behavior coverage for compute-database GPU credit accounting."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from revocompute.db import GPUCreditUnavailableError, TaskDatabase


def _timestamp(year: int, month: int, day: int = 1, second: int = 0) -> float:
    return datetime(year, month, day, 0, 0, second, tzinfo=timezone.utc).timestamp()


def test_monthly_grant_is_lazy_idempotent_and_uses_utc_period(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    september = _timestamp(2026, 9)

    first = database.gpu_credit_summary(17, at=september)
    second = database.gpu_credit_summary(17, at=september + 60)

    assert first == second
    assert first == {
        "user_id": 17,
        "period": "2026-09",
        "monthly_grant_gpu_seconds": 60_000,
        "usage_gpu_seconds": 0,
        "adjustment_gpu_seconds": 0,
        "remaining_gpu_seconds": 60_000,
    }
    with database.engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(database.gpu_credit_ledger_table)
            ).scalar_one()
            == 1
        )


def test_gpu_usage_settlement_is_actual_multi_gpu_time_and_idempotent(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    started_at = _timestamp(2026, 9, 2)
    database.gpu_credit_summary(23, at=started_at)
    database.record_gpu_allocation_start(
        user_id=23,
        task_id="a" * 32,
        stage_id="model",
        slurm_job_id="4217",
        gpu_count=2,
        started_at=started_at,
    )

    first = database.settle_gpu_allocation("4217", finished_at=started_at + 10.2)
    second = database.settle_gpu_allocation("4217", finished_at=started_at + 99)

    assert first["gpu_seconds"] == 22
    assert second == first
    assert (
        database.gpu_credit_summary(23, at=started_at)["remaining_gpu_seconds"]
        == 59_978
    )
    with database.engine.connect() as connection:
        usage_count = connection.execute(
            sa.select(sa.func.count())
            .select_from(database.gpu_credit_ledger_table)
            .where(database.gpu_credit_ledger_table.c.kind == "usage")
        ).scalar_one()
    assert usage_count == 1


def test_active_allocation_may_overdraft_but_next_allocation_is_denied(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=60)
    started_at = _timestamp(2026, 9, 3)
    assert database.require_gpu_credit(31, at=started_at)["remaining_gpu_seconds"] == 60
    database.record_gpu_allocation_start(
        user_id=31,
        task_id="b" * 32,
        stage_id="inference",
        slurm_job_id="5001",
        gpu_count=1,
        started_at=started_at,
    )

    database.settle_gpu_allocation("5001", finished_at=started_at + 75)

    assert (
        database.gpu_credit_summary(31, at=started_at)["remaining_gpu_seconds"] == -15
    )
    with pytest.raises(GPUCreditUnavailableError, match="exhausted"):
        database.require_gpu_credit(31, at=started_at + 80)
    with pytest.raises(GPUCreditUnavailableError, match="exhausted"):
        database.record_gpu_allocation_start(
            user_id=31,
            task_id="e" * 32,
            stage_id="inference",
            slurm_job_id="5002",
            gpu_count=1,
            started_at=started_at + 80,
        )


def test_new_utc_month_does_not_roll_over_prior_negative_balance(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=60)
    september = _timestamp(2026, 9, 30)
    database.record_gpu_allocation_start(
        user_id=41,
        task_id="c" * 32,
        stage_id="model",
        slurm_job_id="6001",
        gpu_count=1,
        started_at=september,
    )
    database.settle_gpu_allocation("6001", finished_at=september + 75)

    assert database.gpu_credit_summary(41, at=september)["remaining_gpu_seconds"] == -15
    assert (
        database.gpu_credit_summary(41, at=_timestamp(2026, 10))[
            "remaining_gpu_seconds"
        ]
        == 60
    )


def test_ledger_rows_cannot_be_updated_or_deleted(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    database.gpu_credit_summary(47, at=_timestamp(2026, 9))

    with pytest.raises(sa.exc.DatabaseError, match="append-only"):
        with database.engine.begin() as connection:
            connection.execute(
                sa.update(database.gpu_credit_ledger_table).values(gpu_seconds=0)
            )
    with pytest.raises(sa.exc.DatabaseError, match="append-only"):
        with database.engine.begin() as connection:
            connection.execute(sa.delete(database.gpu_credit_ledger_table))


def test_unsettled_allocations_remain_visible_for_reconciliation(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    database = TaskDatabase(str(path))
    database.record_gpu_allocation_start(
        user_id=53,
        task_id="d" * 32,
        stage_id="relax",
        slurm_job_id="7001",
        gpu_count=1,
        started_at=_timestamp(2026, 9, 4),
    )
    database.engine.dispose()

    reopened = TaskDatabase(str(path))

    assert reopened.list_unsettled_gpu_allocations() == [
        {
            "id": 1,
            "user_id": 53,
            "task_id": "d" * 32,
            "stage_id": "relax",
            "slurm_job_id": "7001",
            "gpu_count": 1,
            "started_at": _timestamp(2026, 9, 4),
            "finished_at": None,
            "gpu_seconds": None,
            "status": "active",
            "ledger_entry_id": None,
        }
    ]
