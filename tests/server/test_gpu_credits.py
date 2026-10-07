# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Behavior coverage for compute-database GPU credit accounting."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from conftest import _load_pssm_module
from revocompute.access_control import project_effective_entitlements
from revocompute.db import GPUAuthorizationUnavailableError, GPUCreditUnavailableError, TaskDatabase
from revocompute.resource_ledger import AdmissionReason, ReservationState


def _timestamp(year: int, month: int, day: int = 1, second: int = 0) -> float:
    return datetime(year, month, day, 0, 0, second, tzinfo=timezone.utc).timestamp()


def _own_task(database: TaskDatabase, task_id: str, *, user_id: int) -> None:
    """A real Task row, so the reclaim pass sees an owning Task and only the
    scheduler identity decides whether the request still exists."""
    database.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/immutable/input.fasta",
        uploaded_at=900.0,
        status="queued",
        is_binary=0,
        username=f"user-{user_id}",
        submitted_by_user_id=user_id,
        storage_key=f"user-{user_id}",
        task_type="gremlin",
    )


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
                sa.select(sa.func.count()).select_from(database.resource_ledger_table)
            ).scalar_one()
            == 1
        )


def test_gpu_usage_settlement_is_actual_multi_gpu_time_and_idempotent(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    started_at = _timestamp(2026, 9, 2)
    database.gpu_credit_summary(23, at=started_at)
    database.record_allocation_start(
        user_id=23,
        task_id="a" * 32,
        stage_id="model",
        slurm_job_id="4217",
        gpu_count=2,
        cpu_cores=1,
        started_at=started_at,
    )

    first = database.settle_allocation("4217", finished_at=started_at + 10.2)
    second = database.settle_allocation("4217", finished_at=started_at + 99)

    assert first["quantity"] == 22
    assert second == first
    assert (
        database.gpu_credit_summary(23, at=started_at)["remaining_gpu_seconds"]
        == 59_978
    )
    with database.engine.connect() as connection:
        usage_count = connection.execute(
            sa.select(sa.func.count())
            .select_from(database.resource_ledger_table)
            .where(
                database.resource_ledger_table.c.kind == "usage",
                database.resource_ledger_table.c.unit == "gpu_second",
            )
        ).scalar_one()
    assert usage_count == 1


def test_active_allocation_may_overdraft_but_next_allocation_is_denied(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=60)
    started_at = _timestamp(2026, 9, 3)
    assert database.require_compute_entitlement(31, at=started_at)["remaining_gpu_seconds"] == 60
    database.record_allocation_start(
        user_id=31,
        task_id="b" * 32,
        stage_id="inference",
        slurm_job_id="5001",
        gpu_count=1,
        cpu_cores=1,
        started_at=started_at,
    )

    database.settle_allocation("5001", finished_at=started_at + 75)

    assert (
        database.gpu_credit_summary(31, at=started_at)["remaining_gpu_seconds"] == -15
    )
    with pytest.raises(GPUCreditUnavailableError, match="exhausted"):
        database.require_compute_entitlement(31, at=started_at + 80)
    denied = database.record_allocation_start(
        user_id=31,
        task_id="e" * 32,
        stage_id="inference",
        slurm_job_id="5002",
        gpu_count=1,
        cpu_cores=1,
        started_at=started_at + 80,
    )
    # The second allocation is refused the grant, but it is still an allocation:
    # the fact is recorded so what the wrapper held is settled, not erased.
    assert denied["granted"] is False
    assert denied["reason_code"] == AdmissionReason.COMPUTE_EXHAUSTED.value
    assert {row["slurm_job_id"] for row in database.list_task_allocations("e" * 32)} == {"5002"}


def test_cross_month_allocation_is_charged_to_its_start_month(tmp_path):
    """An allocation's whole usage belongs to the UTC month it started in."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=60)
    # Start 30 seconds before the September→October boundary and finish after it.
    september = _timestamp(2026, 10) - 30  # 2026-09-30 23:59:30 UTC
    october_start = september + 75  # 2026-10-01 00:00:45 UTC
    assert database._gpu_period(september) == "2026-09"
    assert database._gpu_period(october_start) == "2026-10"
    database.record_allocation_start(
        user_id=41,
        task_id="c" * 32,
        stage_id="model",
        slurm_job_id="6001",
        gpu_count=1,
        cpu_cores=1,
        started_at=september,
    )
    # The allocation finishes after the September→October boundary.
    database.settle_allocation("6001", finished_at=october_start)

    usage = next(
        entry
        for entry in database.list_compute_ledger(41, period="2026-09")
        if entry["kind"] == "usage"
    )
    assert usage["quantity"] == -75
    assert database.gpu_credit_summary(41, at=september)["remaining_gpu_seconds"] == -15
    october = database.gpu_credit_summary(41, at=october_start)
    assert october["usage_gpu_seconds"] == 0
    assert october["remaining_gpu_seconds"] == 60


def test_ledger_rows_cannot_be_updated_or_deleted(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    database.gpu_credit_summary(47, at=_timestamp(2026, 9))

    with pytest.raises(sa.exc.DatabaseError, match="append-only"):
        with database.engine.begin() as connection:
            connection.execute(
                sa.update(database.resource_ledger_table).values(quantity=0)
            )
    with pytest.raises(sa.exc.DatabaseError, match="append-only"):
        with database.engine.begin() as connection:
            connection.execute(sa.delete(database.resource_ledger_table))


def test_admin_adjustment_requires_reason_and_is_idempotent(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 5)

    first = database.adjust_compute_account(
        user_id=47,
        gpu_seconds=12_000,
        actor_user_id=3,
        reason="Approved collaboration run",
        idempotency_key="request-1",
        created_at=at,
    )
    retry = database.adjust_compute_account(
        user_id=47,
        gpu_seconds=12_000,
        actor_user_id=3,
        reason="Approved collaboration run",
        idempotency_key="request-1",
        created_at=at + 1,
    )

    assert retry == first
    assert database.gpu_credit_summary(47, at=at)["remaining_gpu_seconds"] == 72_000
    entries = database.list_compute_ledger(47, period="2026-09")
    assert [entry["kind"] for entry in entries] == ["admin_adjustment", "monthly_grant"]
    with pytest.raises(ValueError, match="different adjustment"):
        database.adjust_compute_account(
            user_id=47,
            gpu_seconds=-60,
            actor_user_id=3,
            reason="Changed request",
            idempotency_key="request-1",
            created_at=at + 2,
        )
    with pytest.raises(ValueError, match="reason is required"):
        database.adjust_compute_account(
            user_id=47,
            gpu_seconds=60,
            actor_user_id=3,
            reason="   ",
            idempotency_key="request-2",
            created_at=at,
        )


def test_per_user_monthly_allowance_is_immediate_future_and_idempotent(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    september = _timestamp(2026, 9, 5)
    assert database.gpu_credit_summary(49, at=september)["monthly_grant_gpu_seconds"] == 60_000

    first = database.set_compute_allowance(
        user_id=49,
        monthly_gpu_seconds=72_000,
        actor_user_id=3,
        idempotency_key="allowance-1",
        updated_at=september,
    )
    retry = database.set_compute_allowance(
        user_id=49,
        monthly_gpu_seconds=72_000,
        actor_user_id=3,
        idempotency_key="allowance-1",
        updated_at=september + 1,
    )

    assert retry == first
    assert database.gpu_credit_summary(49, at=september)["monthly_grant_gpu_seconds"] == 72_000
    assert database.gpu_credit_summary(49, at=_timestamp(2026, 10))["monthly_grant_gpu_seconds"] == 72_000
    entries = database.list_compute_ledger(49, period="2026-09")
    assert [entry["kind"] for entry in entries].count("allowance_adjustment") == 1


def test_unsettled_allocations_remain_visible_for_reconciliation(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    database = TaskDatabase(str(path))
    database.record_allocation_start(
        user_id=53,
        task_id="d" * 32,
        stage_id="relax",
        slurm_job_id="7001",
        gpu_count=1,
        cpu_cores=1,
        started_at=_timestamp(2026, 9, 4),
    )
    database.engine.dispose()

    reopened = TaskDatabase(str(path))

    # One Slurm allocation produces two facts — the GPUs it held and the CPU
    # cores it held — and both are unsettled until the authoritative elapsed
    # duration arrives, so reconciliation sees them without either unit standing
    # in for the other.
    unsettled = reopened.list_unsettled_allocations()
    assert [(row["unit"], row["resource_count"]) for row in unsettled] == [
        ("cpu_core_second", 1),
        ("gpu_second", 1),
    ]
    assert {row["slurm_job_id"] for row in unsettled} == {"7001"}
    assert {row["subject_id"] for row in unsettled} == {53}
    assert {row["task_id"] for row in unsettled} == {"d" * 32}
    assert {row["stage_id"] for row in unsettled} == {"relax"}
    assert all(row["status"] == "active" for row in unsettled)
    assert all(row["quantity"] is None and row["finished_at"] is None for row in unsettled)
    assert all(row["evidence_source"] == "allocation_lifecycle" for row in unsettled)
    assert all(row["started_at"] == _timestamp(2026, 9, 4) for row in unsettled)


def test_gpu_authorization_projection_checks_permission_entitlement_and_expiry(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    now = _timestamp(2026, 9, 4)

    with pytest.raises(GPUAuthorizationUnavailableError, match="not currently authorized"):
        database.require_gpu_authorization(57, at=now)

    database.project_gpu_authorization(
        57,
        account_enabled=True,
        allow_gpu_use=True,
        entitlements={"licensed_runner": now + 60},
        updated_at=now,
    )
    database.require_gpu_authorization(57, required_entitlements=("licensed_runner",), at=now)

    with pytest.raises(GPUAuthorizationUnavailableError, match="expired"):
        database.require_gpu_authorization(57, required_entitlements=("licensed_runner",), at=now + 60)
    database.deny_gpu_authorization(57)
    with pytest.raises(GPUAuthorizationUnavailableError, match="not currently authorized"):
        database.require_gpu_authorization(57, at=now)


def test_gpu_allocation_callback_checks_projected_authorization_before_recording(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    _dispatched, started, _finished = module.task_runtime._compute_allocation_callbacks(
        task_id="2" * 32,
        user_id=63,
        stage_id="prediction",
        resource_policy=SimpleNamespace(requires_gpu=True, gres="gpu:1", cpus=1),
        required_entitlements=("licensed_runner",),
    )

    with pytest.raises(GPUCreditUnavailableError, match="authorization_unavailable"):
        started("8901", _timestamp(2026, 9, 6))

    # The refusal is a grant decision: the allocation the wrapper held is still
    # recorded, and it is the fact that stays unsettled for settlement.
    denied = module.task_store.list_unsettled_allocations()
    assert {row["slurm_job_id"] for row in denied} == {"8901"}
    assert all(row["denial_reason"] for row in denied)
    task_id = "2" * 32
    module.task_store.project_gpu_authorization(
        63,
        account_enabled=True,
        allow_gpu_use=True,
        entitlements={"licensed_runner": None},
    )
    # The decision is recorded on the fact, so a duplicate callback for the same
    # allocation reads the recorded refusal instead of re-deciding against a
    # balance a second decision already moved.
    with pytest.raises(GPUCreditUnavailableError, match="authorization_unavailable"):
        started("8901", _timestamp(2026, 9, 6))
    unsettled = module.task_store.list_unsettled_allocations()
    assert {row["unit"] for row in unsettled} == {"gpu_second", "cpu_core_second"}
    assert len(unsettled) == 2

    # A different allocation for the same Task is admitted now that the runner
    # is authorized: the recorded refusal was about that one allocation only.
    _dispatched, started_again, _finished = module.task_runtime._compute_allocation_callbacks(
        task_id=task_id,
        user_id=63,
        stage_id="prediction",
        resource_policy=SimpleNamespace(requires_gpu=True, gres="gpu:1", cpus=1),
        required_entitlements=("licensed_runner",),
    )
    started_again("8901b", _timestamp(2026, 9, 6))
    assert "8901b" in {row["slurm_job_id"] for row in module.task_store.list_unsettled_allocations()}


def test_gpu_allocation_callback_rechecks_runner_readiness(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.task_store.project_gpu_authorization(
        67,
        account_enabled=True,
        allow_gpu_use=True,
        entitlements={},
    )
    monkeypatch.setattr(
        module.task_runtime,
        "resolve_submission_readiness",
        lambda server_dir, runner_family: SimpleNamespace(ready=False),
    )
    _dispatched, started, _finished = module.task_runtime._compute_allocation_callbacks(
        task_id="3" * 32,
        user_id=67,
        stage_id="prediction",
        resource_policy=SimpleNamespace(requires_gpu=True, gres="gpu:1", cpus=1),
        runner_family="licensed",
    )

    with pytest.raises(GPUCreditUnavailableError, match="runner_readiness_unavailable"):
        started("8902", _timestamp(2026, 9, 7))

    # The runner was not ready, so the command is refused — but the allocation
    # the wrapper already held is a fact and stays recorded and settleable.
    recorded = module.task_store.list_unsettled_allocations()
    assert {row["slurm_job_id"] for row in recorded} == {"8902"}
    assert all(row["denial_reason"] == "Runner readiness is unavailable" for row in recorded)


def test_reconciliation_settles_terminal_slurm_elapsed_time_once(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    started_at = _timestamp(2026, 9, 4)
    module.task_store.record_allocation_start(
        user_id=59,
        task_id="f" * 32,
        stage_id="inference",
        slurm_job_id="8801",
        gpu_count=2,
        cpu_cores=1,
        started_at=started_at,
    )
    monkeypatch.setattr(module.task_runtime.shutil, "which", lambda command: "/usr/bin/scontrol")
    monkeypatch.setattr(
        module.task_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="JobId=8801 JobState=COMPLETED RunTime=00:01:13 TimeLimit=01:00:00\n"
        ),
    )

    first = module.task_runtime._reconcile_slurm_allocations()
    second = module.task_runtime._reconcile_slurm_allocations()

    assert first == {"settled": 1, "active": 0, "review": 0}
    assert second == {"settled": 0, "active": 0, "review": 0}
    assert module.task_store.gpu_credit_summary(59, at=started_at)["usage_gpu_seconds"] == 146
    # The same authoritative elapsed duration also settles the CPU allocation
    # this Task held: 1 core x 73 s, recorded as its own unit.
    assert module.task_store.cpu_core_second_summary(59, at=started_at)["used_cpu_core_seconds"] == 73


def test_allocation_start_is_admitted_by_the_tasks_own_reservation(monkeypatch, tmp_path):
    """The callback the Slurm adapter calls must admit the Task that holds the last unit.

    Admission gave this submission the month's final GPU second, so the start
    re-deciding the balance on its own would refuse it.  The reservation is the
    Task's authority, and the decision is made inside the same transaction that
    records the allocation.
    """
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.task_store.project_gpu_authorization(
        64, account_enabled=True, allow_gpu_use=True, entitlements={}
    )
    database = module.task_store
    task_id = "7" * 32
    database.set_compute_allowance(
        user_id=64,
        monthly_gpu_seconds=1,
        actor_user_id=64,
        idempotency_key="final-unit",
        updated_at=_timestamp(2026, 9, 6),
    )
    reservation = database.reserve_compute_admission(
        user_id=64, task_id=task_id, at=_timestamp(2026, 9, 6)
    )
    assert reservation["allowed"] is True
    assert database.compute_entitlement(64, at=_timestamp(2026, 9, 6)).remaining == 0

    _dispatched, started, _finished = module.task_runtime._compute_allocation_callbacks(
        task_id=task_id,
        user_id=64,
        stage_id="prediction",
        resource_policy=SimpleNamespace(requires_gpu=True, gres="gpu:1", cpus=2),
    )
    started("8910", _timestamp(2026, 9, 6))

    allocation = database.list_task_allocations(task_id)
    assert {row["unit"]: row["resource_count"] for row in allocation} == {
        "gpu_second": 1,
        "cpu_core_second": 2,
    }
    assert database.list_task_reservations(task_id)[0]["state"] == "released"


def test_allocation_start_fails_closed_when_the_hold_is_gone_and_the_balance_is_spent(
    monkeypatch, tmp_path
):
    """No authority to start means no Runner: the gate is never released.

    The Task's reservation expired and another allocation took the balance, so
    the start transition refuses — the exception surfaces before the Slurm
    wrapper's approval file is written, which is what keeps an unpayable
    allocation from ever running.
    """
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    database = module.task_store
    project = module.task_store.project_gpu_authorization(
        65, account_enabled=True, allow_gpu_use=True, entitlements={}
    )
    assert project is None
    task_id = "6" * 32
    database.set_compute_allowance(
        user_id=65,
        monthly_gpu_seconds=60,
        actor_user_id=65,
        idempotency_key="closed",
        updated_at=_timestamp(2026, 9, 6),
    )
    assert database.reserve_compute_admission(
        user_id=65, task_id=task_id, at=_timestamp(2026, 9, 6), ttl_seconds=1
    )["allowed"] is True
    assert database.expire_stale_reservations(now=_timestamp(2026, 9, 6) + 10) == 1
    database.record_allocation_start(
        user_id=65,
        task_id="5" * 32,
        stage_id="prediction",
        slurm_job_id="8911",
        gpu_count=1,
        cpu_cores=1,
        started_at=_timestamp(2026, 9, 6) + 20,
    )
    database.settle_allocation_elapsed("8911", elapsed_seconds=60, finished_at=_timestamp(2026, 9, 6) + 80)

    _dispatched, started, _finished = module.task_runtime._compute_allocation_callbacks(
        task_id=task_id,
        user_id=65,
        stage_id="prediction",
        resource_policy=SimpleNamespace(requires_gpu=True, gres="gpu:1", cpus=1),
    )
    with pytest.raises(GPUCreditUnavailableError, match="compute_exhausted"):
        started("8912", _timestamp(2026, 9, 6) + 90)

    recorded = module.task_store.list_task_allocations(task_id)
    assert {row["slurm_job_id"] for row in recorded} == {"8912"}
    assert {row["unit"] for row in recorded} == {"gpu_second", "cpu_core_second"}
    assert all(row["denial_reason"] for row in recorded)


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("JobState=RUNNING RunTime=00:00:19\n", {"settled": 0, "active": 1, "review": 0}),
        ("JobState=RESIZING RunTime=00:00:19\n", {"settled": 0, "active": 0, "review": 1}),
        ("RunTime=00:00:19\n", {"settled": 0, "active": 0, "review": 1}),
        ("JobState=FAILED RunTime=unknown\n", {"settled": 0, "active": 0, "review": 1}),
        ("JobState=FAILED RunTime=-1\n", {"settled": 0, "active": 0, "review": 1}),
        ("JobState=FAILED RunTime=\n", {"settled": 0, "active": 0, "review": 1}),
        ("", {"settled": 0, "active": 0, "review": 1}),
    ],
)
def test_reconciliation_never_charges_ambiguous_slurm_evidence(monkeypatch, tmp_path, stdout, expected):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.task_store.record_allocation_start(
        user_id=61,
        task_id="1" * 32,
        stage_id="model",
        slurm_job_id="8802",
        gpu_count=1,
        cpu_cores=1,
        started_at=_timestamp(2026, 9, 5),
    )
    monkeypatch.setattr(module.task_runtime.shutil, "which", lambda command: "/usr/bin/scontrol")
    monkeypatch.setattr(
        module.task_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=stdout),
    )

    assert module.task_runtime._reconcile_slurm_allocations() == expected
    allocation = module.task_store.list_unsettled_allocations()[0]
    assert allocation["status"] == ("active" if expected["active"] else "review")
    assert module.task_store.gpu_credit_summary(61, at=_timestamp(2026, 9, 5))["usage_gpu_seconds"] == 0


def test_reconciliation_uses_scontrol_without_slurm_accounting(monkeypatch, tmp_path):
    """Recovery must not depend on sacct/SlurmDBD being configured."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.task_store.record_allocation_start(
        user_id=71,
        task_id="9" * 32,
        stage_id="relax",
        slurm_job_id="8803",
        gpu_count=1,
        cpu_cores=1,
        started_at=_timestamp(2026, 9, 5),
    )
    commands: list[list[str]] = []

    def fake_run(command, *args, **kwargs):
        commands.append(list(command))
        return SimpleNamespace(stdout="JobState=COMPLETED RunTime=01-00:00:10\n")

    monkeypatch.setattr(module.task_runtime.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(module.task_runtime.subprocess, "run", fake_run)

    assert module.task_runtime._reconcile_slurm_allocations() == {"settled": 1, "active": 0, "review": 0}
    assert commands == [["/usr/bin/scontrol", "show", "job", "8803"]]
    assert module.task_store.gpu_credit_summary(71, at=_timestamp(2026, 9, 5))["usage_gpu_seconds"] == 86_410


def test_reconciliation_never_frees_a_commitment_without_scheduler_evidence(monkeypatch, tmp_path):
    """A queued commitment is released by evidence, never by an absent identity.

    The reservation row carries the scheduler identity the dispatch wrote, so
    the reclaim pass can name the request.  A pass that instead read the Task
    row would see ``slurm_job_id`` as NULL during the dispatch window and free
    entitlement a live queued request is about to consume.
    """
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    at = _timestamp(2026, 9, 5)
    task_id = "9" * 32
    _own_task(module.task_store, task_id, user_id=91)
    module.task_store.reserve_compute_admission(user_id=91, task_id=task_id, at=at)
    module.task_store.record_reservation_dispatch(task_id=task_id, slurm_job_id="8805", at=at + 1)
    # The Task row's own handle has not been persisted yet: this is exactly the
    # window a Task-row read would mistake for "no request exists".
    assert (module.task_store.get_task(task_id) or {}).get("slurm_job_id") is None

    commands: list[list[str]] = []

    def fake_run(command, *args, **kwargs):
        commands.append(list(command))
        return SimpleNamespace(stdout="JobId=8805 JobState=PENDING\n")

    monkeypatch.setattr(module.task_runtime.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(module.task_runtime.subprocess, "run", fake_run)

    assert module.task_runtime._reclaim_abandoned_reservations(now=at + 10) == 0

    # The scheduler was asked about the queued request named on the row, and the
    # commitment is still there because the request still exists.
    assert commands == [["/usr/bin/scontrol", "show", "job", "8805"]]
    assert module.task_store.list_queued_reservations()[0]["state"] == ReservationState.QUEUED.value


def test_reconciliation_frees_a_queued_commitment_the_scheduler_proves_is_gone(monkeypatch, tmp_path):
    """A terminal scheduler answer is the evidence that frees the claim."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    at = _timestamp(2026, 9, 5)
    task_id = "8" * 32
    _own_task(module.task_store, task_id, user_id=92)
    module.task_store.reserve_compute_admission(user_id=92, task_id=task_id, at=at)
    module.task_store.record_reservation_dispatch(task_id=task_id, slurm_job_id="8806", at=at + 1)

    monkeypatch.setattr(module.task_runtime.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        module.task_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="JobId=8806 JobState=CANCELLED\n"),
    )

    assert module.task_runtime._reclaim_abandoned_reservations(now=at + 10) == 1
    assert module.task_store.list_queued_reservations() == []
    assert module.task_store.compute_entitlement(92, at=at + 10).remaining == 60_000


def test_reconciliation_never_frees_a_commitment_over_a_recorded_allocation(monkeypatch, tmp_path):
    """A wrapper-executed request keeps its commitment until evidence settles it.

    The crash window: the wrapper printed its own job id and the execution fact
    was persisted, then the process died before the grant decision.  The
    scheduler now reports the job terminal, so a naive reclaim pass would free the
    reservation as if nothing had ever been allocated.  The recorded allocation is
    the proof it must not: the request is settled from scheduler evidence, and the
    claim is consumed by that allocation rather than handed back.
    """
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    at = _timestamp(2026, 9, 5)
    task_id = "7" * 32
    _own_task(module.task_store, task_id, user_id=93)
    module.task_store.reserve_compute_admission(user_id=93, task_id=task_id, at=at)
    module.task_store.record_reservation_dispatch(task_id=task_id, slurm_job_id="8807", at=at + 1)
    # The wrapper's own observation, written before any grant decision.
    module.task_store.observe_allocation_start(
        user_id=93,
        task_id=task_id,
        stage_id="model",
        slurm_job_id="8807",
        gpu_count=1,
        cpu_cores=1,
        started_at=at + 2,
    )

    monkeypatch.setattr(module.task_runtime.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        module.task_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="JobId=8807 JobState=COMPLETED RunTime=00:00:45\n"),
    )

    assert module.task_runtime._reclaim_abandoned_reservations(now=at + 10) == 0

    # Settled from the one authoritative elapsed duration, not released as if
    # the request had never been allocated.
    assert module.task_runtime._reconcile_slurm_allocations() == {"settled": 1, "active": 0, "review": 0}
    assert module.task_store.gpu_credit_summary(93, at=at + 10)["usage_gpu_seconds"] == 45
    assert module.task_store.list_unsettled_allocations() == []


def _bearer(user: dict) -> dict[str, str]:
    from revocompute.auth import generate_token

    return {"Authorization": f"Bearer {generate_token(user['id'])}"}


def _active_user(database, username: str, *, role: str = "user") -> dict:
    user = database.create_user(
        username=username,
        email=f"{username}@test.local",
        password="password123",
        role=role,
        registration_status="approved",
        user_status="active",
    )
    database.verify_email(user["id"])
    return database.get_user(user["id"])


def test_user_gpu_credit_api_is_self_scoped_and_hides_admin_actor(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    users = module.app.config["user_db"]
    alice = _active_user(users, "credit-alice")
    bob = _active_user(users, "credit-bob")
    module.task_store.adjust_compute_account(
        user_id=alice["id"],
        gpu_seconds=600,
        actor_user_id=bob["id"],
        reason="Approved extension",
        idempotency_key="alice-extension",
    )

    response = module.app.test_client().get("/compute/api/gpu-credit", headers=_bearer(alice))

    assert response.status_code == 200
    assert response.json["user_id"] == alice["id"]
    assert response.json["remaining_credits"] == 1010
    assert response.json["credit_unit_gpu_seconds"] == 60
    assert all("actor_user_id" not in entry for entry in response.json["history"])
    assert bob["id"] not in [entry.get("user_id") for entry in response.json["history"]]


def test_admin_gpu_adjustment_requires_admin_and_is_idempotent(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    users = module.app.config["user_db"]
    admin = _active_user(users, "credit-admin", role="admin")
    target = _active_user(users, "credit-target")
    regular = _active_user(users, "credit-regular")
    path = f"/compute/api/auth/admin/users/{target['id']}/gpu-credit/adjustments"
    payload = {"gpu_seconds": -600, "reason": "Correct duplicate grant", "idempotency_key": "correction-1"}
    client = module.app.test_client()

    denied = client.post(path, headers={**_bearer(regular), "Content-Type": "application/json"}, json=payload)
    first = client.post(path, headers={**_bearer(admin), "Content-Type": "application/json"}, json=payload)
    retry = client.post(path, headers={**_bearer(admin), "Content-Type": "application/json"}, json=payload)

    assert denied.status_code == 403
    assert first.status_code == 201
    assert retry.status_code == 201
    assert first.json["entry_id"] == retry.json["entry_id"]
    assert first.json["gpu_credit"]["remaining_gpu_seconds"] == 59_400
    entries = module.task_store.list_compute_ledger(target["id"])
    assert [entry["kind"] for entry in entries].count("admin_adjustment") == 1
    detail = client.get(f"/compute/api/auth/admin/users/{target['id']}/gpu-credit", headers=_bearer(admin))
    assert detail.status_code == 200
    adjustment = next(entry for entry in detail.json["history"] if entry["kind"] == "admin_adjustment")
    assert adjustment["actor_user_id"] == admin["id"]


def test_admin_gpu_adjustment_rejects_missing_reason_zero_and_unknown_user(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    users = module.app.config["user_db"]
    admin = _active_user(users, "credit-validation-admin", role="admin")
    target = _active_user(users, "credit-validation-target")
    client = module.app.test_client()
    headers = {**_bearer(admin), "Content-Type": "application/json"}
    path = f"/compute/api/auth/admin/users/{target['id']}/gpu-credit/adjustments"

    assert client.post(path, headers=headers, json={"gpu_seconds": 60, "idempotency_key": "a"}).status_code == 400
    zero = client.post(
        path,
        headers=headers,
        json={"gpu_seconds": 0, "reason": "none", "idempotency_key": "b"},
    )
    assert zero.status_code == 400
    missing = client.post(
        "/compute/api/auth/admin/users/999999/gpu-credit/adjustments",
        headers=headers,
        json={"gpu_seconds": 60, "reason": "grant", "idempotency_key": "c"},
    )
    assert missing.status_code == 404


def test_admin_can_set_per_user_monthly_allowance(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    users = module.app.config["user_db"]
    admin = _active_user(users, "allowance-admin", role="admin")
    target = _active_user(users, "allowance-target")
    regular = _active_user(users, "allowance-regular")
    path = f"/compute/api/auth/admin/users/{target['id']}/gpu-credit/allowance"
    payload = {"monthly_gpu_seconds": 72_000, "idempotency_key": "allowance-web-1"}
    client = module.app.test_client()

    assert client.put(path, headers={**_bearer(regular), "Content-Type": "application/json"}, json=payload).status_code == 403
    first = client.put(path, headers={**_bearer(admin), "Content-Type": "application/json"}, json=payload)
    retry = client.put(path, headers={**_bearer(admin), "Content-Type": "application/json"}, json=payload)

    assert first.status_code == 200
    assert retry.status_code == 200
    assert first.json["entry_id"] == retry.json["entry_id"]
    assert first.json["gpu_credit"]["monthly_grant_credits"] == 1200
    assert first.json["gpu_credit"]["remaining_credits"] == 1200


def test_admin_gpu_reconciliation_requires_admin_bearer_and_returns_worker_result(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    users = module.app.config["user_db"]
    admin = _active_user(users, "reconciliation-admin", role="admin")
    regular = _active_user(users, "reconciliation-regular")
    path = "/compute/api/auth/admin/gpu-credit/reconciliation"
    calls = []

    class _Result:
        def get(self, timeout):
            assert timeout == 20
            return {"settled": 1, "active": 0, "review": 0}

    def _apply_async():
        calls.append(True)
        return _Result()

    monkeypatch.setattr(module.task_runtime.reconcile_slurm_allocations, "apply_async", _apply_async)
    client = module.app.test_client()

    denied = client.post(path, headers=_bearer(regular))
    visible = client.get(path, headers=_bearer(admin))
    reconciled = client.post(path, headers=_bearer(admin))

    assert denied.status_code == 403
    assert visible.status_code == 200
    assert visible.json == {"result": None, "allocations": []}
    assert reconciled.status_code == 200
    assert reconciled.json == {
        "result": {"settled": 1, "active": 0, "review": 0},
        "allocations": [],
    }
    assert calls == [True]


def test_effective_entitlement_projection_unions_overlapping_grants():
    now = 1_000.0
    grants = [
        # list_entitlement_grants returns newest-first.
        {"entitlement": "licensed", "revoked_at": None, "expires_at": now + 3_000},
        {"entitlement": "licensed", "revoked_at": None, "expires_at": now + 1_000},
        {"entitlement": "other", "revoked_at": None, "expires_at": None},
        {"entitlement": "revoked", "revoked_at": now, "expires_at": None},
        {"entitlement": "expired", "revoked_at": None, "expires_at": now - 1},
    ]

    assert project_effective_entitlements(grants, now=now) == {
        "licensed": now + 3_000,
        "other": None,
    }


def test_effective_entitlement_projection_keeps_indefinite_grant():
    now = 100.0
    grants = [
        {"entitlement": "licensed", "revoked_at": None, "expires_at": now + 10},
        {"entitlement": "licensed", "revoked_at": None, "expires_at": None},
    ]

    assert project_effective_entitlements(grants, now=now) == {"licensed": None}


def test_projected_union_grants_remain_authorized_after_shorter_expiry(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    now = _timestamp(2026, 9, 4)
    entitlements = project_effective_entitlements(
        [
            {"entitlement": "licensed", "revoked_at": None, "expires_at": now + 3_000},
            {"entitlement": "licensed", "revoked_at": None, "expires_at": now + 1_000},
        ],
        now=now,
    )
    database.project_gpu_authorization(
        57,
        account_enabled=True,
        allow_gpu_use=True,
        entitlements=entitlements,
        updated_at=now,
    )

    database.require_gpu_authorization(57, required_entitlements=("licensed",), at=now + 1_500)
    with pytest.raises(GPUAuthorizationUnavailableError, match="expired"):
        database.require_gpu_authorization(57, required_entitlements=("licensed",), at=now + 3_000)


def test_settlement_failure_keeps_allocation_recoverable(monkeypatch, tmp_path):
    """Accounting failure must not rewrite a completed scientific job."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.task_store.project_gpu_authorization(
        83,
        account_enabled=True,
        allow_gpu_use=True,
        entitlements={},
    )
    module.task_store.record_allocation_start(
        user_id=83,
        task_id="8" * 32,
        stage_id="prediction",
        slurm_job_id="8903",
        gpu_count=1,
        cpu_cores=1,
        started_at=_timestamp(2026, 9, 8),
    )
    _dispatched, _started, finished = module.task_runtime._compute_allocation_callbacks(
        task_id="8" * 32,
        user_id=83,
        stage_id="prediction",
        resource_policy=SimpleNamespace(requires_gpu=True, gres="gpu:1", cpus=1),
    )

    def failing_settlement(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(module.task_store, "settle_allocation", failing_settlement)

    # The finish callback must swallow the accounting failure instead of
    # escaping poll() and failing an already-completed Runner.
    finished("8903", _timestamp(2026, 9, 8, second=30))

    allocations = module.task_store.list_unsettled_allocations()
    assert {item["slurm_job_id"] for item in allocations} == {"8903"}
    # Every unit of the lost allocation stays recoverable, not just the first.
    assert {item["unit"] for item in allocations} == {"gpu_second", "cpu_core_second"}
    assert all(item["status"] == "review" for item in allocations)


# ---------------------------------------------------------------------------
# Administrative GPU-credit reset
# ---------------------------------------------------------------------------


def _seed_usage(database: TaskDatabase, user_id: int, *, seconds: int, at: float, job_id: str) -> None:
    database.record_allocation_start(
        user_id=user_id,
        task_id=f"{user_id:032d}",
        stage_id="model",
        slurm_job_id=job_id,
        gpu_count=1,
        cpu_cores=1,
        started_at=at,
    )
    database.settle_allocation(job_id, finished_at=at + seconds)


def test_reset_below_allowance_appends_positive_compensation(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    _seed_usage(database, 101, seconds=40_000, at=at, job_id="7201")

    result = database.reset_compute_account(
        user_id=101, actor_user_id=7, reason="Approved new allocation cycle", idempotency_key="reset-101", at=at + 60
    )

    assert result["changed"] is True
    assert result["previous_remaining_gpu_seconds"] == 20_000
    assert result["reset_delta_gpu_seconds"] == 40_000
    assert result["remaining_gpu_seconds"] == 60_000
    assert database.gpu_credit_summary(101, at=at + 60)["remaining_gpu_seconds"] == 60_000
    entry = next(e for e in database.list_compute_ledger(101) if e["kind"] == "admin_reset")
    assert entry["quantity"] == 40_000
    assert entry["actor_user_id"] == 7
    assert entry["reason"] == "Approved new allocation cycle"


def test_reset_above_allowance_appends_negative_compensation(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    database.gpu_credit_summary(102, at=at)
    database.adjust_compute_account(
        user_id=102, gpu_seconds=18_000, actor_user_id=1, reason="Approved extension", idempotency_key="top-up-102", created_at=at
    )

    result = database.reset_compute_account(
        user_id=102, actor_user_id=7, reason="Normalize to allowance", idempotency_key="reset-102", at=at + 60
    )

    assert result["previous_remaining_gpu_seconds"] == 78_000
    assert result["reset_delta_gpu_seconds"] == -18_000
    assert result["remaining_gpu_seconds"] == 60_000
    assert database.gpu_credit_summary(102, at=at + 60)["remaining_gpu_seconds"] == 60_000


def test_reset_at_allowance_writes_a_durable_noop_marker(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    database.gpu_credit_summary(103, at=at)

    first = database.reset_compute_account(
        user_id=103, actor_user_id=7, reason="Refresh", idempotency_key="reset-103", at=at + 60
    )
    second = database.reset_compute_account(
        user_id=103, actor_user_id=7, reason="Refresh", idempotency_key="reset-103", at=at + 120
    )

    assert first == second
    assert first["changed"] is False
    assert first["reset_delta_gpu_seconds"] == 0
    assert first["entry_id"] is not None
    markers = [e for e in database.list_compute_ledger(103) if e["kind"] == "admin_reset"]
    assert len(markers) == 1
    assert markers[0]["quantity"] == 0
    assert markers[0]["id"] == first["entry_id"]


def test_noop_reset_key_survives_a_later_balance_change(tmp_path):
    """A retried no-op key must never become a real reset later."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    database.gpu_credit_summary(112, at=at)

    noop = database.reset_compute_account(
        user_id=112, actor_user_id=7, reason="Refresh", idempotency_key="reset-noop-112", at=at + 60
    )
    assert noop["changed"] is False
    # The balance changes after the original no-op request.
    _seed_usage(database, 112, seconds=40_000, at=at, job_id="7212")
    assert database.gpu_credit_summary(112, at=at + 120)["remaining_gpu_seconds"] == 20_000

    retry = database.reset_compute_account(
        user_id=112, actor_user_id=7, reason="Refresh", idempotency_key="reset-noop-112", at=at + 180
    )

    assert retry["changed"] is False
    assert retry["entry_id"] == noop["entry_id"]
    # The retry must not have compensated the post-no-op change.
    assert database.gpu_credit_summary(112, at=at + 180)["remaining_gpu_seconds"] == 20_000
    assert len([e for e in database.list_compute_ledger(112) if e["kind"] == "admin_reset"]) == 1


def test_noop_reset_key_is_reserved_against_conflicting_reuse(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    database.gpu_credit_summary(113, at=at)

    database.reset_compute_account(
        user_id=113, actor_user_id=7, reason="Refresh", idempotency_key="reset-noop-113", at=at + 60
    )

    with pytest.raises(ValueError, match="different reset"):
        database.reset_compute_account(
            user_id=113, actor_user_id=8, reason="Different reason", idempotency_key="reset-noop-113", at=at + 120
        )


def test_reset_respects_custom_and_zero_allowances(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    database.set_compute_allowance(
        user_id=104, monthly_gpu_seconds=72_000, actor_user_id=1, idempotency_key="allow-104", updated_at=at
    )
    database.set_compute_allowance(
        user_id=105, monthly_gpu_seconds=0, actor_user_id=1, idempotency_key="allow-105", updated_at=at
    )
    database.adjust_compute_account(
        user_id=105, gpu_seconds=5_000, actor_user_id=1, reason="Manual top-up", idempotency_key="adjust-105", created_at=at
    )
    _seed_usage(database, 104, seconds=12_000, at=at, job_id="7204")

    custom = database.reset_compute_account(
        user_id=104, actor_user_id=7, reason="Custom allowance reset", idempotency_key="reset-104", at=at + 60
    )
    zero = database.reset_compute_account(
        user_id=105, actor_user_id=7, reason="Zero allowance reset", idempotency_key="reset-105", at=at + 60
    )

    assert custom["monthly_allowance_gpu_seconds"] == 72_000
    assert custom["remaining_gpu_seconds"] == 72_000
    assert zero["monthly_allowance_gpu_seconds"] == 0
    assert zero["reset_delta_gpu_seconds"] == -5_000
    assert zero["remaining_gpu_seconds"] == 0


def test_reset_preserves_usage_and_adjustment_history(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    _seed_usage(database, 106, seconds=40_000, at=at, job_id="7206")
    database.adjust_compute_account(
        user_id=106, gpu_seconds=6_000, actor_user_id=3, reason="Collaboration extension", idempotency_key="adjust-106", created_at=at
    )
    before = [dict(entry) for entry in database.list_compute_ledger(106)]

    database.reset_compute_account(
        user_id=106, actor_user_id=7, reason="Cycle reset", idempotency_key="reset-106", at=at + 60
    )

    after = {entry["id"]: entry for entry in database.list_compute_ledger(106)}
    for entry in before:
        assert after[entry["id"]] == entry
    recall = database.gpu_credit_summary(106, at=at + 60)
    assert recall["usage_gpu_seconds"] == 40_000
    assert recall["remaining_gpu_seconds"] == 60_000


def test_reset_is_idempotent_and_rejects_conflicting_reuse(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    _seed_usage(database, 107, seconds=40_000, at=at, job_id="7207")

    first = database.reset_compute_account(
        user_id=107, actor_user_id=7, reason="Cycle reset", idempotency_key="reset-107", at=at + 60
    )
    retry = database.reset_compute_account(
        user_id=107, actor_user_id=7, reason="Cycle reset", idempotency_key="reset-107", at=at + 90
    )

    assert first["entry_id"] == retry["entry_id"]
    assert len([e for e in database.list_compute_ledger(107) if e["kind"] == "admin_reset"]) == 1
    with pytest.raises(ValueError, match="different reset"):
        database.reset_compute_account(
            user_id=107, actor_user_id=8, reason="Cycle reset", idempotency_key="reset-107", at=at + 120
        )


def test_reset_only_affects_the_current_period(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    september = _timestamp(2026, 9, 4)
    october = _timestamp(2026, 10, 4)
    _seed_usage(database, 108, seconds=40_000, at=october, job_id="7208")

    result = database.reset_compute_account(
        user_id=108, actor_user_id=7, reason="September reset", idempotency_key="reset-108", at=september
    )

    assert result["changed"] is False
    assert database.gpu_credit_summary(108, at=september)["remaining_gpu_seconds"] == 60_000
    assert database.gpu_credit_summary(108, at=october)["remaining_gpu_seconds"] == 20_000


def test_reset_is_not_blocked_by_an_active_allocation_and_settles_afterward(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    database.gpu_credit_summary(109, at=at)
    database.record_allocation_start(
        user_id=109, task_id="9" * 32, stage_id="model", slurm_job_id="7209", gpu_count=1, cpu_cores=1, started_at=at
    )

    # A running allocation never blocks an administrative reset ...
    result = database.reset_compute_account(
        user_id=109, actor_user_id=7, reason="Refresh while running", idempotency_key="reset-109", at=at + 60
    )
    assert result["remaining_gpu_seconds"] == 60_000
    # ... and the later actual usage is appended normally.
    database.settle_allocation("7209", finished_at=at + 1_800)
    assert database.gpu_credit_summary(109, at=at + 1_800)["remaining_gpu_seconds"] == 58_200


def test_concurrent_resets_serialize_to_one_compensation(tmp_path):
    path = str(tmp_path / "tasks.sqlite3")
    at = _timestamp(2026, 9, 4)
    seed = TaskDatabase(path)
    _seed_usage(seed, 110, seconds=1_200, at=at, job_id="7210")
    seed.engine.dispose()

    databases = [TaskDatabase(path), TaskDatabase(path)]
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            databases[index].reset_compute_account(
                user_id=110,
                actor_user_id=7,
                reason="Concurrent reset",
                idempotency_key=f"reset-concurrent-{index}",
                at=at + 3_600,
            )
        except Exception as exc:  # pragma: no cover - surfaced through the assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    rows = [e for e in databases[0].list_compute_ledger(110) if e["kind"] == "admin_reset"]
    # The loser of the race durably records a zero marker instead of a second
    # compensation, so exactly one entry moves the balance.
    compensations = [row for row in rows if row["quantity"] != 0]
    assert len(compensations) == 1
    assert compensations[0]["quantity"] == 1_200
    assert len(rows) == 2
    assert databases[0].gpu_credit_summary(110, at=at + 3_600)["remaining_gpu_seconds"] == 60_000


def test_reset_rejects_blank_and_oversized_reasons(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    database.gpu_credit_summary(111, at=at)

    with pytest.raises(ValueError, match="reason is required"):
        database.reset_compute_account(user_id=111, actor_user_id=7, reason="   ", idempotency_key="reset-111", at=at)
    with pytest.raises(ValueError, match="at most 1000"):
        database.reset_compute_account(user_id=111, actor_user_id=7, reason="x" * 1001, idempotency_key="reset-112", at=at)


def test_global_reset_respects_per_user_allowances_and_reports_a_summary(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    _seed_usage(database, 201, seconds=50_000, at=at, job_id="7301")  # Alice: 10000/60000
    database.set_compute_allowance(
        user_id=202, monthly_gpu_seconds=72_000, actor_user_id=1, idempotency_key="allow-202", updated_at=at
    )  # Bob: 72000/72000
    database.set_compute_allowance(
        user_id=203, monthly_gpu_seconds=30_000, actor_user_id=1, idempotency_key="allow-203", updated_at=at
    )
    database.adjust_compute_account(
        user_id=203, gpu_seconds=20_000, actor_user_id=1, reason="Extension", idempotency_key="adjust-203", created_at=at
    )  # Carol: 50000/30000

    summary = database.reset_all_compute_accounts(
        user_ids=[201, 202, 203], actor_user_id=7, reason="Start refreshed cycle", idempotency_key="global-1", at=at + 60
    )

    assert summary["users_considered"] == 3
    assert summary["users_changed"] == 2
    assert summary["users_unchanged"] == 1
    assert summary["total_delta_gpu_seconds"] == 50_000 - 20_000
    assert database.gpu_credit_summary(201, at=at + 60)["remaining_gpu_seconds"] == 60_000
    assert database.gpu_credit_summary(202, at=at + 60)["remaining_gpu_seconds"] == 72_000
    assert database.gpu_credit_summary(203, at=at + 60)["remaining_gpu_seconds"] == 30_000

    alice_rows = [e for e in database.list_compute_ledger(201) if e["kind"] == "admin_reset"]
    bob_rows = [e for e in database.list_compute_ledger(202) if e["kind"] == "admin_reset"]
    carol_rows = [e for e in database.list_compute_ledger(203) if e["kind"] == "admin_reset"]
    assert len(alice_rows) == 1
    assert len(bob_rows) == 1 and bob_rows[0]["quantity"] == 0
    assert len(carol_rows) == 1
    # Every considered user gets a durable batch marker, including no-ops.
    batch = database.list_reset_batch(summary["batch_id"])
    assert {row["subject_id"] for row in batch} == {201, 202, 203}
    assert {row["reason"] for row in batch} == {"Start refreshed cycle"}
    assert {row["actor_user_id"] for row in batch} == {7}


def test_global_reset_retry_does_not_duplicate_entries(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    _seed_usage(database, 211, seconds=10_000, at=at, job_id="7311")
    _seed_usage(database, 212, seconds=20_000, at=at, job_id="7312")

    first = database.reset_all_compute_accounts(
        user_ids=[211, 212], actor_user_id=7, reason="Cycle reset", idempotency_key="global-retry", at=at + 60
    )
    retry = database.reset_all_compute_accounts(
        user_ids=[211, 212], actor_user_id=7, reason="Cycle reset", idempotency_key="global-retry", at=at + 120
    )

    assert first["batch_id"] == retry["batch_id"]
    assert first["users_changed"] == 2
    assert retry["users_changed"] == 2
    assert retry["total_delta_gpu_seconds"] == first["total_delta_gpu_seconds"]
    for user_id in (211, 212):
        assert len([e for e in database.list_compute_ledger(user_id) if e["kind"] == "admin_reset"]) == 1
        assert database.gpu_credit_summary(user_id, at=at + 120)["remaining_gpu_seconds"] == 60_000


def test_global_reset_batch_key_covers_initially_unchanged_users(tmp_path):
    """A retried batch must not newly reset a user who was a no-op the first time."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    _seed_usage(database, 231, seconds=10_000, at=at, job_id="7331")
    database.gpu_credit_summary(232, at=at)  # already exactly at the allowance

    first = database.reset_all_compute_accounts(
        user_ids=[231, 232], actor_user_id=7, reason="Cycle reset", idempotency_key="global-scope", at=at + 60
    )
    assert first["users_changed"] == 1
    assert first["users_unchanged"] == 1
    # The initially-unchanged user's balance changes after the first batch.
    _seed_usage(database, 232, seconds=25_000, at=at, job_id="7332")
    assert database.gpu_credit_summary(232, at=at + 120)["remaining_gpu_seconds"] == 35_000

    retry = database.reset_all_compute_accounts(
        user_ids=[231, 232], actor_user_id=7, reason="Cycle reset", idempotency_key="global-scope", at=at + 180
    )

    assert retry["batch_id"] == first["batch_id"]
    assert database.gpu_credit_summary(232, at=at + 180)["remaining_gpu_seconds"] == 35_000
    assert retry["users_changed"] == 1
    assert len([e for e in database.list_compute_ledger(232) if e["kind"] == "admin_reset"]) == 1


def test_global_reset_batch_is_all_or_nothing(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    _seed_usage(database, 221, seconds=10_000, at=at, job_id="7321")
    _seed_usage(database, 222, seconds=20_000, at=at, job_id="7322")

    original = database._reset_account_in_connection

    def explode(conn, **kwargs):
        if kwargs["user_id"] == 222:
            raise RuntimeError("accounting write failed")
        return original(conn, **kwargs)

    database._reset_account_in_connection = explode  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="accounting write failed"):
        database.reset_all_compute_accounts(
            user_ids=[221, 222], actor_user_id=7, reason="Atomic reset", idempotency_key="global-atomic", at=at + 60
        )
    database._reset_account_in_connection = original  # type: ignore[method-assign]

    assert [e for e in database.list_compute_ledger(221) if e["kind"] == "admin_reset"] == []
    assert [e for e in database.list_compute_ledger(222) if e["kind"] == "admin_reset"] == []
    assert database.gpu_credit_summary(221, at=at + 60)["remaining_gpu_seconds"] == 50_000


def test_admin_reset_api_is_authorized_idempotent_and_accurate(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    users = module.app.config["user_db"]
    admin = _active_user(users, "reset-admin", role="admin")
    target = _active_user(users, "reset-target")
    regular = _active_user(users, "reset-regular")
    at = _timestamp(2026, 9, 4)
    # The reset route omits ``at`` and falls back to the wall clock, so pin the
    # db module's clock inside the seeded September period.
    import revocompute.db as _db_module

    monkeypatch.setattr(_db_module.time, "time", lambda: at + 60)
    _seed_usage(module.task_store, target["id"], seconds=40_000, at=at, job_id="7401")
    path = f"/compute/api/auth/admin/users/{target['id']}/gpu-credit/reset"
    payload = {"reason": "Approved new allocation cycle", "idempotency_key": "reset-api-1"}
    client = module.app.test_client()

    unauthenticated = client.post(path, json=payload)
    denied = client.post(path, headers={**_bearer(regular), "Content-Type": "application/json"}, json=payload)
    first = client.post(path, headers={**_bearer(admin), "Content-Type": "application/json"}, json=payload)
    retry = client.post(path, headers={**_bearer(admin), "Content-Type": "application/json"}, json=payload)

    assert unauthenticated.status_code == 401
    assert denied.status_code == 403
    assert first.status_code == 200
    assert retry.status_code == 200
    assert first.json["user_id"] == target["id"]
    assert first.json["monthly_allowance_gpu_seconds"] == 60_000
    assert first.json["previous_remaining_gpu_seconds"] == 20_000
    assert first.json["reset_delta_gpu_seconds"] == 40_000
    assert first.json["remaining_gpu_seconds"] == 60_000
    assert first.json["changed"] is True
    assert first.json["entry_id"] == retry.json["entry_id"]
    assert first.json["gpu_credit"]["remaining_credits"] == 1000
    detail = client.get(
        f"/compute/api/auth/admin/users/{target['id']}/gpu-credit", headers=_bearer(admin)
    )
    reset_entry = next(entry for entry in detail.json["history"] if entry["kind"] == "admin_reset")
    assert reset_entry["actor_user_id"] == admin["id"]
    regular_view = client.get("/compute/api/gpu-credit", headers=_bearer(target))
    assert all("actor_user_id" not in entry for entry in regular_view.json["history"])


def test_admin_reset_api_validates_body_user_and_reason(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    users = module.app.config["user_db"]
    admin = _active_user(users, "reset-validation-admin", role="admin")
    target = _active_user(users, "reset-validation-target")
    deleted = _active_user(users, "reset-deleted")
    users.update_user(deleted["id"], deleted=True)
    client = module.app.test_client()
    headers = {**_bearer(admin), "Content-Type": "application/json"}
    path = f"/compute/api/auth/admin/users/{target['id']}/gpu-credit/reset"

    assert client.post(path, headers=headers, json={"idempotency_key": "missing-reason"}).status_code == 400
    assert client.post(path, headers=headers, json={"reason": "   ", "idempotency_key": "blank"}).status_code == 400
    assert client.post(path, headers=headers, json={"reason": "ok"}).status_code == 400
    assert client.post(path, headers=headers, json={"reason": "ok", "idempotency_key": "bad key!"}).status_code == 400
    assert (
        client.post(path, headers=headers, json={"reason": "ok", "idempotency_key": "x", "user_id": 5}).status_code
        == 400
    )
    assert (
        client.post(
            "/compute/api/auth/admin/users/999999/gpu-credit/reset",
            headers=headers,
            json={"reason": "ok", "idempotency_key": "missing-user"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/compute/api/auth/admin/users/{deleted['id']}/gpu-credit/reset",
            headers=headers,
            json={"reason": "ok", "idempotency_key": "deleted-user"},
        ).status_code
        == 404
    )


def test_admin_global_reset_api_respects_scope_and_is_idempotent(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    users = module.app.config["user_db"]
    admin = _active_user(users, "global-reset-admin", role="admin")
    regular = _active_user(users, "global-reset-regular")
    alice = _active_user(users, "global-reset-alice")
    bob = _active_user(users, "global-reset-bob")
    carol = _active_user(users, "global-reset-carol")
    deleted = _active_user(users, "global-reset-deleted")
    users.update_user(bob["id"], allow_gpu_use=False)
    users.update_user(deleted["id"], deleted=True)
    at = _timestamp(2026, 9, 4)
    # The reset route omits ``at`` and falls back to the wall clock, so pin the
    # db module's clock inside the seeded September period.
    import revocompute.db as _db_module

    monkeypatch.setattr(_db_module.time, "time", lambda: at + 60)
    _seed_usage(module.task_store, alice["id"], seconds=50_000, at=at, job_id="7501")
    module.task_store.set_compute_allowance(
        user_id=bob["id"], monthly_gpu_seconds=72_000, actor_user_id=admin["id"], idempotency_key="global-allow-bob", updated_at=at
    )
    module.task_store.set_compute_allowance(
        user_id=carol["id"], monthly_gpu_seconds=30_000, actor_user_id=admin["id"], idempotency_key="global-allow-carol", updated_at=at
    )
    module.task_store.adjust_compute_account(
        user_id=carol["id"], gpu_seconds=50_000, actor_user_id=admin["id"], reason="Extension", idempotency_key="global-adjust-carol", created_at=at
    )
    _seed_usage(module.task_store, deleted["id"], seconds=10_000, at=at, job_id="7502")
    expected_considered = len(users.list_users())
    path = "/compute/api/auth/admin/gpu-credit/reset"
    payload = {"reason": "Start refreshed allocation cycle", "idempotency_key": "global-api-1"}
    client = module.app.test_client()

    denied = client.post(path, headers={**_bearer(regular), "Content-Type": "application/json"}, json=payload)
    first = client.post(path, headers={**_bearer(admin), "Content-Type": "application/json"}, json=payload)
    retry = client.post(path, headers={**_bearer(admin), "Content-Type": "application/json"}, json=payload)

    assert denied.status_code == 403
    assert first.status_code == 200
    assert first.json["users_considered"] == expected_considered
    assert deleted["id"] not in {row["subject_id"] for row in module.task_store.list_reset_batch(first.json["batch_id"])}
    assert module.task_store.gpu_credit_summary(deleted["id"], at=at + 60)["remaining_gpu_seconds"] == 50_000
    assert module.task_store.gpu_credit_summary(alice["id"], at=at + 60)["remaining_gpu_seconds"] == 60_000
    # GPU permission is independent of the reset.
    assert users.get_user(bob["id"])["allow_gpu_use"] in (0, False)
    assert module.task_store.gpu_credit_summary(bob["id"], at=at + 60)["remaining_gpu_seconds"] == 72_000
    assert module.task_store.gpu_credit_summary(carol["id"], at=at + 60)["remaining_gpu_seconds"] == 30_000
    assert first.json["users_changed"] == 2
    assert first.json["users_unchanged"] == expected_considered - 2
    assert retry.json["batch_id"] == first.json["batch_id"]
    assert retry.json["total_delta_gpu_seconds"] == first.json["total_delta_gpu_seconds"]
    assert len(module.task_store.list_reset_batch(first.json["batch_id"])) == expected_considered


def test_admin_global_reset_api_validates_request(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    admin = _active_user(module.app.config["user_db"], "global-reset-validation", role="admin")
    client = module.app.test_client()
    headers = {**_bearer(admin), "Content-Type": "application/json"}
    path = "/compute/api/auth/admin/gpu-credit/reset"

    assert client.post(path, json={"reason": "ok", "idempotency_key": "x"}).status_code == 401
    assert client.post(path, headers=headers, json={"idempotency_key": "x"}).status_code == 400
    assert client.post(path, headers=headers, json={"reason": "   ", "idempotency_key": "x"}).status_code == 400
    assert client.post(path, headers=headers, json={"reason": "ok"}).status_code == 400


def test_noop_reset_marker_is_hidden_from_user_history_but_kept_for_admin(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    users = module.app.config["user_db"]
    admin = _active_user(users, "noop-admin", role="admin")
    target = _active_user(users, "noop-target")
    client = module.app.test_client()
    admin_headers = {**_bearer(admin), "Content-Type": "application/json"}
    path = f"/compute/api/auth/admin/users/{target['id']}/gpu-credit/reset"

    response = client.post(
        path, headers=admin_headers, json={"reason": "Already at allowance", "idempotency_key": "noop-api-1"}
    )

    assert response.status_code == 200
    assert response.json["changed"] is False
    assert response.json["reset_delta_gpu_seconds"] == 0
    assert response.json["entry_id"] is not None
    user_view = client.get("/compute/api/gpu-credit", headers=_bearer(target))
    assert user_view.status_code == 200
    assert all(entry["kind"] != "admin_reset" for entry in user_view.json["history"])
    admin_view = client.get(
        f"/compute/api/auth/admin/users/{target['id']}/gpu-credit", headers=_bearer(admin)
    )
    marker = next(entry for entry in admin_view.json["history"] if entry["kind"] == "admin_reset")
    assert marker["gpu_seconds"] == 0
    assert marker["actor_user_id"] == admin["id"]
