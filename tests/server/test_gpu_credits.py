# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Behavior coverage for compute-database GPU credit accounting."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from conftest import _load_pssm_module
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
    monkeypatch.setattr(module.task_runtime.shutil, "which", lambda command: "/usr/bin/sacct")
    monkeypatch.setattr(
        module.task_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="8801|COMPLETED|73|\n"),
    )

    first = module.task_runtime._reconcile_gpu_allocations()
    second = module.task_runtime._reconcile_gpu_allocations()

    assert first == {"settled": 1, "active": 0, "review": 0}
    assert second == {"settled": 0, "active": 0, "review": 0}
    assert module.task_store.gpu_credit_summary(59, at=started_at)["usage_gpu_seconds"] == 146


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("8802|RUNNING|19|\n", {"settled": 0, "active": 1, "review": 0}),
        ("8802|RESIZING|19|\n", {"settled": 0, "active": 0, "review": 1}),
        ("8802||19|\n", {"settled": 0, "active": 0, "review": 1}),
        ("8802|FAILED|unknown|\n", {"settled": 0, "active": 0, "review": 1}),
        ("8802|FAILED|-1|\n", {"settled": 0, "active": 0, "review": 1}),
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
    monkeypatch.setattr(module.task_runtime.shutil, "which", lambda command: "/usr/bin/sacct")
    monkeypatch.setattr(
        module.task_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=stdout),
    )

    assert module.task_runtime._reconcile_gpu_allocations() == expected
    allocation = module.task_store.list_unsettled_gpu_allocations()[0]
    assert allocation["status"] == ("active" if expected["active"] else "review")
    assert module.task_store.gpu_credit_summary(61, at=_timestamp(2026, 9, 5))["usage_gpu_seconds"] == 0


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
