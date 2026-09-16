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


def test_cross_month_allocation_is_charged_to_its_start_month(tmp_path):
    """An allocation's whole usage belongs to the UTC month it started in."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=60)
    # Start 30 seconds before the September→October boundary and finish after it.
    september = _timestamp(2026, 10) - 30  # 2026-09-30 23:59:30 UTC
    october_start = september + 75  # 2026-10-01 00:00:45 UTC
    assert database._gpu_period(september) == "2026-09"
    assert database._gpu_period(october_start) == "2026-10"
    database.record_gpu_allocation_start(
        user_id=41,
        task_id="c" * 32,
        stage_id="model",
        slurm_job_id="6001",
        gpu_count=1,
        started_at=september,
    )
    # The allocation finishes after the September→October boundary.
    database.settle_gpu_allocation("6001", finished_at=october_start)

    usage = next(
        entry
        for entry in database.list_gpu_credit_ledger(41, period="2026-09")
        if entry["kind"] == "usage"
    )
    assert usage["gpu_seconds"] == -75
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
                sa.update(database.gpu_credit_ledger_table).values(gpu_seconds=0)
            )
    with pytest.raises(sa.exc.DatabaseError, match="append-only"):
        with database.engine.begin() as connection:
            connection.execute(sa.delete(database.gpu_credit_ledger_table))


def test_admin_adjustment_requires_reason_and_is_idempotent(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 5)

    first = database.adjust_gpu_credit(
        user_id=47,
        gpu_seconds=12_000,
        actor_user_id=3,
        reason="Approved collaboration run",
        idempotency_key="request-1",
        created_at=at,
    )
    retry = database.adjust_gpu_credit(
        user_id=47,
        gpu_seconds=12_000,
        actor_user_id=3,
        reason="Approved collaboration run",
        idempotency_key="request-1",
        created_at=at + 1,
    )

    assert retry == first
    assert database.gpu_credit_summary(47, at=at)["remaining_gpu_seconds"] == 72_000
    entries = database.list_gpu_credit_ledger(47, period="2026-09")
    assert [entry["kind"] for entry in entries] == ["admin_adjustment", "monthly_grant"]
    with pytest.raises(ValueError, match="different adjustment"):
        database.adjust_gpu_credit(
            user_id=47,
            gpu_seconds=-60,
            actor_user_id=3,
            reason="Changed request",
            idempotency_key="request-1",
            created_at=at + 2,
        )
    with pytest.raises(ValueError, match="reason is required"):
        database.adjust_gpu_credit(
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

    first = database.set_gpu_monthly_allowance(
        user_id=49,
        monthly_gpu_seconds=72_000,
        actor_user_id=3,
        idempotency_key="allowance-1",
        updated_at=september,
    )
    retry = database.set_gpu_monthly_allowance(
        user_id=49,
        monthly_gpu_seconds=72_000,
        actor_user_id=3,
        idempotency_key="allowance-1",
        updated_at=september + 1,
    )

    assert retry == first
    assert database.gpu_credit_summary(49, at=september)["monthly_grant_gpu_seconds"] == 72_000
    assert database.gpu_credit_summary(49, at=_timestamp(2026, 10))["monthly_grant_gpu_seconds"] == 72_000
    entries = database.list_gpu_credit_ledger(49, period="2026-09")
    assert [entry["kind"] for entry in entries].count("allowance_adjustment") == 1


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
    started, _finished = module.task_runtime._gpu_allocation_callbacks(
        task_id="2" * 32,
        user_id=63,
        stage_id="prediction",
        resource_policy=SimpleNamespace(requires_gpu=True, gres="gpu:1"),
        required_entitlements=("licensed_runner",),
    )

    with pytest.raises(GPUAuthorizationUnavailableError):
        started("8901", _timestamp(2026, 9, 6))

    assert module.task_store.list_unsettled_gpu_allocations() == []
    module.task_store.project_gpu_authorization(
        63,
        account_enabled=True,
        allow_gpu_use=True,
        entitlements={"licensed_runner": None},
    )
    started("8901", _timestamp(2026, 9, 6))
    assert module.task_store.list_unsettled_gpu_allocations()[0]["slurm_job_id"] == "8901"
    module.task_store.deny_gpu_authorization(63)
    started("8901", _timestamp(2026, 9, 6))
    assert len(module.task_store.list_unsettled_gpu_allocations()) == 1


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
    started, _finished = module.task_runtime._gpu_allocation_callbacks(
        task_id="3" * 32,
        user_id=67,
        stage_id="prediction",
        resource_policy=SimpleNamespace(requires_gpu=True, gres="gpu:1"),
        runner_family="licensed",
    )

    with pytest.raises(GPUAuthorizationUnavailableError, match="readiness"):
        started("8902", _timestamp(2026, 9, 7))

    assert module.task_store.list_unsettled_gpu_allocations() == []


def test_reconciliation_settles_terminal_slurm_elapsed_time_once(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    started_at = _timestamp(2026, 9, 4)
    module.task_store.record_gpu_allocation_start(
        user_id=59,
        task_id="f" * 32,
        stage_id="inference",
        slurm_job_id="8801",
        gpu_count=2,
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

    first = module.task_runtime._reconcile_gpu_allocations()
    second = module.task_runtime._reconcile_gpu_allocations()

    assert first == {"settled": 1, "active": 0, "review": 0}
    assert second == {"settled": 0, "active": 0, "review": 0}
    assert module.task_store.gpu_credit_summary(59, at=started_at)["usage_gpu_seconds"] == 146


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
    module.task_store.record_gpu_allocation_start(
        user_id=61,
        task_id="1" * 32,
        stage_id="model",
        slurm_job_id="8802",
        gpu_count=1,
        started_at=_timestamp(2026, 9, 5),
    )
    monkeypatch.setattr(module.task_runtime.shutil, "which", lambda command: "/usr/bin/scontrol")
    monkeypatch.setattr(
        module.task_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=stdout),
    )

    assert module.task_runtime._reconcile_gpu_allocations() == expected
    allocation = module.task_store.list_unsettled_gpu_allocations()[0]
    assert allocation["status"] == ("active" if expected["active"] else "review")
    assert module.task_store.gpu_credit_summary(61, at=_timestamp(2026, 9, 5))["usage_gpu_seconds"] == 0


def test_reconciliation_uses_scontrol_without_slurm_accounting(monkeypatch, tmp_path):
    """Recovery must not depend on sacct/SlurmDBD being configured."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.task_store.record_gpu_allocation_start(
        user_id=71,
        task_id="9" * 32,
        stage_id="relax",
        slurm_job_id="8803",
        gpu_count=1,
        started_at=_timestamp(2026, 9, 5),
    )
    commands: list[list[str]] = []

    def fake_run(command, *args, **kwargs):
        commands.append(list(command))
        return SimpleNamespace(stdout="JobState=COMPLETED RunTime=01-00:00:10\n")

    monkeypatch.setattr(module.task_runtime.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(module.task_runtime.subprocess, "run", fake_run)

    assert module.task_runtime._reconcile_gpu_allocations() == {"settled": 1, "active": 0, "review": 0}
    assert commands == [["/usr/bin/scontrol", "show", "job", "8803"]]
    assert module.task_store.gpu_credit_summary(71, at=_timestamp(2026, 9, 5))["usage_gpu_seconds"] == 86_410


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
    module.task_store.adjust_gpu_credit(
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
    entries = module.task_store.list_gpu_credit_ledger(target["id"])
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

    monkeypatch.setattr(module.task_runtime.reconcile_gpu_allocations, "apply_async", _apply_async)
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
    module.task_store.record_gpu_allocation_start(
        user_id=83,
        task_id="8" * 32,
        stage_id="prediction",
        slurm_job_id="8903",
        gpu_count=1,
        started_at=_timestamp(2026, 9, 8),
    )
    _started, finished = module.task_runtime._gpu_allocation_callbacks(
        task_id="8" * 32,
        user_id=83,
        stage_id="prediction",
        resource_policy=SimpleNamespace(requires_gpu=True, gres="gpu:1"),
    )

    def failing_settlement(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(module.task_store, "settle_gpu_allocation", failing_settlement)

    # The finish callback must swallow the accounting failure instead of
    # escaping poll() and failing an already-completed Runner.
    finished("8903", _timestamp(2026, 9, 8, second=30))

    allocations = module.task_store.list_unsettled_gpu_allocations()
    assert [item["slurm_job_id"] for item in allocations] == ["8903"]
    assert allocations[0]["status"] == "review"


# ---------------------------------------------------------------------------
# Administrative GPU-credit reset
# ---------------------------------------------------------------------------


def _seed_usage(database: TaskDatabase, user_id: int, *, seconds: int, at: float, job_id: str) -> None:
    database.record_gpu_allocation_start(
        user_id=user_id,
        task_id=f"{user_id:032d}",
        stage_id="model",
        slurm_job_id=job_id,
        gpu_count=1,
        started_at=at,
    )
    database.settle_gpu_allocation(job_id, finished_at=at + seconds)


def test_reset_below_allowance_appends_positive_compensation(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    _seed_usage(database, 101, seconds=40_000, at=at, job_id="7201")

    result = database.reset_gpu_credit(
        user_id=101, actor_user_id=7, reason="Approved new allocation cycle", idempotency_key="reset-101", at=at + 60
    )

    assert result["changed"] is True
    assert result["previous_remaining_gpu_seconds"] == 20_000
    assert result["reset_delta_gpu_seconds"] == 40_000
    assert result["remaining_gpu_seconds"] == 60_000
    assert database.gpu_credit_summary(101, at=at + 60)["remaining_gpu_seconds"] == 60_000
    entry = next(e for e in database.list_gpu_credit_ledger(101) if e["kind"] == "admin_reset")
    assert entry["gpu_seconds"] == 40_000
    assert entry["actor_user_id"] == 7
    assert entry["reason"] == "Approved new allocation cycle"


def test_reset_above_allowance_appends_negative_compensation(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    database.gpu_credit_summary(102, at=at)
    database.adjust_gpu_credit(
        user_id=102, gpu_seconds=18_000, actor_user_id=1, reason="Approved extension", idempotency_key="top-up-102", created_at=at
    )

    result = database.reset_gpu_credit(
        user_id=102, actor_user_id=7, reason="Normalize to allowance", idempotency_key="reset-102", at=at + 60
    )

    assert result["previous_remaining_gpu_seconds"] == 78_000
    assert result["reset_delta_gpu_seconds"] == -18_000
    assert result["remaining_gpu_seconds"] == 60_000
    assert database.gpu_credit_summary(102, at=at + 60)["remaining_gpu_seconds"] == 60_000


def test_reset_at_allowance_is_a_noop_without_a_zero_row(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    database.gpu_credit_summary(103, at=at)

    first = database.reset_gpu_credit(
        user_id=103, actor_user_id=7, reason="Refresh", idempotency_key="reset-103", at=at + 60
    )
    second = database.reset_gpu_credit(
        user_id=103, actor_user_id=7, reason="Refresh", idempotency_key="reset-103", at=at + 120
    )

    assert first == second
    assert first["changed"] is False
    assert first["reset_delta_gpu_seconds"] == 0
    assert first["entry_id"] is None
    assert [e for e in database.list_gpu_credit_ledger(103) if e["kind"] == "admin_reset"] == []


def test_reset_respects_custom_and_zero_allowances(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    database.set_gpu_monthly_allowance(
        user_id=104, monthly_gpu_seconds=72_000, actor_user_id=1, idempotency_key="allow-104", updated_at=at
    )
    database.set_gpu_monthly_allowance(
        user_id=105, monthly_gpu_seconds=0, actor_user_id=1, idempotency_key="allow-105", updated_at=at
    )
    database.adjust_gpu_credit(
        user_id=105, gpu_seconds=5_000, actor_user_id=1, reason="Manual top-up", idempotency_key="adjust-105", created_at=at
    )
    _seed_usage(database, 104, seconds=12_000, at=at, job_id="7204")

    custom = database.reset_gpu_credit(
        user_id=104, actor_user_id=7, reason="Custom allowance reset", idempotency_key="reset-104", at=at + 60
    )
    zero = database.reset_gpu_credit(
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
    database.adjust_gpu_credit(
        user_id=106, gpu_seconds=6_000, actor_user_id=3, reason="Collaboration extension", idempotency_key="adjust-106", created_at=at
    )
    before = [dict(entry) for entry in database.list_gpu_credit_ledger(106)]

    database.reset_gpu_credit(
        user_id=106, actor_user_id=7, reason="Cycle reset", idempotency_key="reset-106", at=at + 60
    )

    after = {entry["id"]: entry for entry in database.list_gpu_credit_ledger(106)}
    for entry in before:
        assert after[entry["id"]] == entry
    recall = database.gpu_credit_summary(106, at=at + 60)
    assert recall["usage_gpu_seconds"] == 40_000
    assert recall["remaining_gpu_seconds"] == 60_000


def test_reset_is_idempotent_and_rejects_conflicting_reuse(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    _seed_usage(database, 107, seconds=40_000, at=at, job_id="7207")

    first = database.reset_gpu_credit(
        user_id=107, actor_user_id=7, reason="Cycle reset", idempotency_key="reset-107", at=at + 60
    )
    retry = database.reset_gpu_credit(
        user_id=107, actor_user_id=7, reason="Cycle reset", idempotency_key="reset-107", at=at + 90
    )

    assert first["entry_id"] == retry["entry_id"]
    assert len([e for e in database.list_gpu_credit_ledger(107) if e["kind"] == "admin_reset"]) == 1
    with pytest.raises(ValueError, match="different reset"):
        database.reset_gpu_credit(
            user_id=107, actor_user_id=8, reason="Cycle reset", idempotency_key="reset-107", at=at + 120
        )


def test_reset_only_affects_the_current_period(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    september = _timestamp(2026, 9, 4)
    october = _timestamp(2026, 10, 4)
    _seed_usage(database, 108, seconds=40_000, at=october, job_id="7208")

    result = database.reset_gpu_credit(
        user_id=108, actor_user_id=7, reason="September reset", idempotency_key="reset-108", at=september
    )

    assert result["changed"] is False
    assert database.gpu_credit_summary(108, at=september)["remaining_gpu_seconds"] == 60_000
    assert database.gpu_credit_summary(108, at=october)["remaining_gpu_seconds"] == 20_000


def test_reset_is_not_blocked_by_an_active_allocation_and_settles_afterward(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    database.gpu_credit_summary(109, at=at)
    database.record_gpu_allocation_start(
        user_id=109, task_id="9" * 32, stage_id="model", slurm_job_id="7209", gpu_count=1, started_at=at
    )

    # A running allocation never blocks an administrative reset ...
    result = database.reset_gpu_credit(
        user_id=109, actor_user_id=7, reason="Refresh while running", idempotency_key="reset-109", at=at + 60
    )
    assert result["remaining_gpu_seconds"] == 60_000
    # ... and the later actual usage is appended normally.
    database.settle_gpu_allocation("7209", finished_at=at + 1_800)
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
            databases[index].reset_gpu_credit(
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
    rows = [e for e in databases[0].list_gpu_credit_ledger(110) if e["kind"] == "admin_reset"]
    assert len(rows) == 1
    assert rows[0]["gpu_seconds"] == 1_200
    assert databases[0].gpu_credit_summary(110, at=at + 3_600)["remaining_gpu_seconds"] == 60_000


def test_reset_rejects_blank_and_oversized_reasons(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    database.gpu_credit_summary(111, at=at)

    with pytest.raises(ValueError, match="reason is required"):
        database.reset_gpu_credit(user_id=111, actor_user_id=7, reason="   ", idempotency_key="reset-111", at=at)
    with pytest.raises(ValueError, match="at most 1000"):
        database.reset_gpu_credit(user_id=111, actor_user_id=7, reason="x" * 1001, idempotency_key="reset-112", at=at)


def test_global_reset_respects_per_user_allowances_and_reports_a_summary(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    _seed_usage(database, 201, seconds=50_000, at=at, job_id="7301")  # Alice: 10000/60000
    database.set_gpu_monthly_allowance(
        user_id=202, monthly_gpu_seconds=72_000, actor_user_id=1, idempotency_key="allow-202", updated_at=at
    )  # Bob: 72000/72000
    database.set_gpu_monthly_allowance(
        user_id=203, monthly_gpu_seconds=30_000, actor_user_id=1, idempotency_key="allow-203", updated_at=at
    )
    database.adjust_gpu_credit(
        user_id=203, gpu_seconds=20_000, actor_user_id=1, reason="Extension", idempotency_key="adjust-203", created_at=at
    )  # Carol: 50000/30000

    summary = database.reset_all_gpu_credits(
        user_ids=[201, 202, 203], actor_user_id=7, reason="Start refreshed cycle", idempotency_key="global-1", at=at + 60
    )

    assert summary["users_considered"] == 3
    assert summary["users_changed"] == 2
    assert summary["users_unchanged"] == 1
    assert summary["total_delta_gpu_seconds"] == 50_000 - 20_000
    assert database.gpu_credit_summary(201, at=at + 60)["remaining_gpu_seconds"] == 60_000
    assert database.gpu_credit_summary(202, at=at + 60)["remaining_gpu_seconds"] == 72_000
    assert database.gpu_credit_summary(203, at=at + 60)["remaining_gpu_seconds"] == 30_000

    assert len([e for e in database.list_gpu_credit_ledger(201) if e["kind"] == "admin_reset"]) == 1
    assert [e for e in database.list_gpu_credit_ledger(202) if e["kind"] == "admin_reset"] == []
    assert len([e for e in database.list_gpu_credit_ledger(203) if e["kind"] == "admin_reset"]) == 1
    batch = database.list_gpu_credit_reset_batch(summary["batch_id"])
    assert {row["user_id"] for row in batch} == {201, 203}
    assert {row["reason"] for row in batch} == {"Start refreshed cycle"}
    assert {row["actor_user_id"] for row in batch} == {7}


def test_global_reset_retry_does_not_duplicate_entries(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    _seed_usage(database, 211, seconds=10_000, at=at, job_id="7311")
    _seed_usage(database, 212, seconds=20_000, at=at, job_id="7312")

    first = database.reset_all_gpu_credits(
        user_ids=[211, 212], actor_user_id=7, reason="Cycle reset", idempotency_key="global-retry", at=at + 60
    )
    retry = database.reset_all_gpu_credits(
        user_ids=[211, 212], actor_user_id=7, reason="Cycle reset", idempotency_key="global-retry", at=at + 120
    )

    assert first["batch_id"] == retry["batch_id"]
    assert first["users_changed"] == 2
    assert retry["users_changed"] == 2
    assert retry["total_delta_gpu_seconds"] == first["total_delta_gpu_seconds"]
    for user_id in (211, 212):
        assert len([e for e in database.list_gpu_credit_ledger(user_id) if e["kind"] == "admin_reset"]) == 1
        assert database.gpu_credit_summary(user_id, at=at + 120)["remaining_gpu_seconds"] == 60_000


def test_global_reset_batch_is_all_or_nothing(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    at = _timestamp(2026, 9, 4)
    _seed_usage(database, 221, seconds=10_000, at=at, job_id="7321")
    _seed_usage(database, 222, seconds=20_000, at=at, job_id="7322")

    original = database._reset_gpu_credit_in_connection

    def explode(conn, **kwargs):
        if kwargs["user_id"] == 222:
            raise RuntimeError("accounting write failed")
        return original(conn, **kwargs)

    database._reset_gpu_credit_in_connection = explode  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="accounting write failed"):
        database.reset_all_gpu_credits(
            user_ids=[221, 222], actor_user_id=7, reason="Atomic reset", idempotency_key="global-atomic", at=at + 60
        )
    database._reset_gpu_credit_in_connection = original  # type: ignore[method-assign]

    assert [e for e in database.list_gpu_credit_ledger(221) if e["kind"] == "admin_reset"] == []
    assert [e for e in database.list_gpu_credit_ledger(222) if e["kind"] == "admin_reset"] == []
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
    _seed_usage(module.task_store, alice["id"], seconds=50_000, at=at, job_id="7501")
    module.task_store.set_gpu_monthly_allowance(
        user_id=bob["id"], monthly_gpu_seconds=72_000, actor_user_id=admin["id"], idempotency_key="global-allow-bob", updated_at=at
    )
    module.task_store.set_gpu_monthly_allowance(
        user_id=carol["id"], monthly_gpu_seconds=30_000, actor_user_id=admin["id"], idempotency_key="global-allow-carol", updated_at=at
    )
    module.task_store.adjust_gpu_credit(
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
    assert deleted["id"] not in {row["user_id"] for row in module.task_store.list_gpu_credit_reset_batch(first.json["batch_id"])}
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
    assert len(module.task_store.list_gpu_credit_reset_batch(first.json["batch_id"])) == 2


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
