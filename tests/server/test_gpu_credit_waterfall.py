# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The bounded GPU-credit waterfall on the canonical resource-ledger read.

The waterfall is the cumulative view a reader needs to explain a balance: an
authoritative opening, signed deltas in UTC chronological order, and a closing
that reconciles to the canonical summary.  These cases drive the real endpoint
against the real ledger and assert the arithmetic a reader is shown, not the
implementation that produced it.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import sqlalchemy as sa
from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from jsonschema import Draft202012Validator


def _validate(spec: dict, schema_name: str, payload: object) -> None:
    Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema_name}", "components": spec["components"]},
    ).validate(payload)


def _module(monkeypatch, tmp_path):
    return _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )


def _user(module, username: str = "tester") -> dict:
    return module.app.config["user_db"].get_user_by_username(username)


def _ledger(module, headers: dict, *, limit: int | None = None) -> dict:
    suffix = "" if limit is None else f"?limit={limit}"
    response = module.app.test_client().get(f"/compute/api/resource-ledger{suffix}", headers=headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _gpu_entries(payload: dict) -> list[dict]:
    return [entry for entry in payload["entries"] if entry["unit"] == "gpu_second"]


def _charge(module, user_id: int, job: str, *, seconds: int, at: float) -> None:
    task_id = job.rjust(32, "0")
    module.task_store.record_allocation_start(
        user_id=user_id,
        task_id=task_id,
        stage_id="model",
        slurm_job_id=job,
        gpu_count=1,
        cpu_cores=1,
        started_at=at,
    )
    module.task_store.settle_allocation(job, finished_at=at + seconds)


def test_openapi_publishes_the_waterfall_as_part_of_the_ledger_read(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    spec = module.app.test_client().get("/openapi.json").get_json()

    window = spec["components"]["schemas"]["ResourceLedger"]
    assert {"order", "gpu_waterfall"} <= set(window["required"])
    assert window["properties"]["gpu_waterfall"] == {"$ref": "#/components/schemas/GPUCreditWaterfall"}
    waterfall = spec["components"]["schemas"]["GPUCreditWaterfall"]
    assert waterfall["additionalProperties"] is False
    assert {"opening_gpu_seconds", "closing_gpu_seconds", "complete", "truncated", "steps", "summary"} <= set(
        waterfall["required"]
    )
    assert window["properties"]["order"]["enum"] == ["chronological"]


def test_a_complete_window_opens_at_zero_and_closes_at_the_summary(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    now = time.time()
    _charge(module, user["id"], "8101", seconds=100, at=now - 50)
    module.task_store.adjust_compute_account(
        user_id=user["id"], gpu_seconds=120, actor_user_id=99,
        reason="Pilot allocation", idempotency_key="pilot", created_at=now + 1,
    )

    payload = _ledger(module, headers)
    _validate(module.app.test_client().get("/openapi.json").get_json(), "ResourceLedger", payload)

    waterfall = payload["gpu_waterfall"]
    assert payload["order"] == "chronological"
    assert waterfall["complete"] is True
    assert waterfall["truncated"] is False
    assert waterfall["opening_gpu_seconds"] == 0
    # Closing is the canonical settled position: grant + adjustment - usage.
    summary = waterfall["summary"]
    assert waterfall["closing_gpu_seconds"] == (
        summary["monthly_grant_gpu_seconds"]
        + summary["adjustment_gpu_seconds"]
        - summary["usage_gpu_seconds"]
    )
    assert waterfall["closing_gpu_seconds"] == summary["settled_balance_gpu_seconds"]

    gpu_entries = _gpu_entries(payload)
    # UTC order: the grant at allocation start, the adjustment, then the settled
    # usage recorded at the allocation's finish.
    assert [entry["kind"] for entry in gpu_entries] == ["monthly_grant", "admin_adjustment", "usage"]
    assert [step["entry_id"] for step in waterfall["steps"]] == [entry["id"] for entry in gpu_entries]
    balance = waterfall["opening_gpu_seconds"]
    for entry, step in zip(gpu_entries, waterfall["steps"]):
        balance += entry["quantity"]
        assert step["delta_gpu_seconds"] == entry["quantity"]
        assert step["balance_gpu_seconds"] == balance
    assert balance == waterfall["closing_gpu_seconds"]


def test_entries_are_utc_chronological_and_duplicate_timestamps_have_a_total_order(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    stamp = time.time()
    for index in range(4):
        module.task_store.adjust_compute_account(
            user_id=user["id"], gpu_seconds=10, actor_user_id=99,
            reason=f"Correction {index}", idempotency_key=f"same-stamp-{index}", created_at=stamp,
        )

    payload = _ledger(module, headers)
    entries = _gpu_entries(payload)
    keys = [(entry["created_at"], entry["id"]) for entry in entries]
    assert keys == sorted(keys)
    # The immutable identifier is the tie-break for facts recorded in one second.
    same_stamp = [entry["id"] for entry in entries if entry["created_at"] == stamp]
    assert same_stamp == sorted(same_stamp)

    steps = payload["gpu_waterfall"]["steps"]
    assert [step["entry_id"] for step in steps] == [entry["id"] for entry in entries]
    balances = [step["balance_gpu_seconds"] for step in steps]
    assert balances == sorted(balances)


def test_a_backdated_fact_does_not_displace_a_newer_timestamp_from_the_window(monkeypatch, tmp_path):
    """The bounded window is newest by UTC time, not by insertion order.

    The three corrections are inserted newest-time first, so a window selected by
    descending identifier would hold the two oldest timestamps and present them
    as the newest. The shown window must instead be the two newest timestamps,
    and the opening balance must be the exact sum of everything it omitted.
    """
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    # A deterministic instant inside the current UTC month, so the grant and the
    # backdated facts cannot straddle a month boundary.
    noon = datetime.fromtimestamp(time.time(), timezone.utc).replace(
        day=1, hour=12, minute=0, second=0, microsecond=0
    ).timestamp()
    # Materialize the period grant earlier than every correction, so it does not
    # share the newest timestamp with the newest correction.
    module.task_store.gpu_credit_summary(user["id"], at=noon - 60)
    for gpu_seconds, offset, key in ((30, 10, "newest"), (20, 20, "middle"), (10, 30, "oldest")):
        module.task_store.adjust_compute_account(
            user_id=user["id"], gpu_seconds=gpu_seconds, actor_user_id=99,
            reason=f"Backdated {key}", idempotency_key=key, created_at=noon - offset,
        )

    payload = _ledger(module, headers, limit=2)
    shown = _gpu_entries(payload)
    # Chronological order, but only the two newest timestamps are present.
    assert [entry["quantity"] for entry in shown] == [20, 30]
    assert all(entry["created_at"] >= noon - 20 for entry in shown)
    oldest = next(
        entry for entry in _gpu_entries(_ledger(module, headers, limit=200))
        if entry["reason"] == "Backdated oldest"
    )
    assert oldest["id"] not in {entry["id"] for entry in shown}

    all_entries = _gpu_entries(_ledger(module, headers, limit=200))
    omitted = sum(
        entry["quantity"] for entry in all_entries
        if entry["id"] not in {shown_entry["id"] for shown_entry in shown}
    )
    waterfall = payload["gpu_waterfall"]
    assert waterfall["opening_gpu_seconds"] == omitted
    assert waterfall["closing_gpu_seconds"] == waterfall["summary"]["settled_balance_gpu_seconds"]
    assert waterfall["complete"] is False


def test_a_partial_window_uses_the_verified_opening_and_still_reconciles(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    stamp = time.time()
    for index in range(55):
        module.task_store.adjust_compute_account(
            user_id=user["id"], gpu_seconds=index + 1, actor_user_id=99,
            reason=f"Batch {index}", idempotency_key=f"batch-{index}", created_at=stamp + index,
        )

    payload = _ledger(module, headers, limit=10)
    waterfall = payload["gpu_waterfall"]
    assert payload["limit"] == 10
    assert waterfall["complete"] is False
    assert waterfall["truncated"] is True
    assert waterfall["entry_count"] == len(_gpu_entries(payload))
    assert waterfall["entry_count"] == 10
    assert waterfall["total_entry_count"] > waterfall["entry_count"]

    # The opening is exactly the sum of every fact this window omits, not a
    # guessed zero: the closing still equals the complete settled balance.
    all_entries = _gpu_entries(_ledger(module, headers, limit=200))
    shown = {entry["id"] for entry in _gpu_entries(payload)}
    omitted = sum(entry["quantity"] for entry in all_entries if entry["id"] not in shown)
    assert waterfall["opening_gpu_seconds"] == omitted
    assert waterfall["closing_gpu_seconds"] == waterfall["summary"]["settled_balance_gpu_seconds"]

    # Concatenating the omitted facts before the shown ones reproduces the
    # closing balance, step by step.
    balance = waterfall["opening_gpu_seconds"]
    for step in waterfall["steps"]:
        balance += step["delta_gpu_seconds"]
        assert step["balance_gpu_seconds"] == balance
    assert balance == waterfall["closing_gpu_seconds"]


def test_a_negative_balance_is_reported_rather_than_clamped(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    allowance = module.task_store.monthly_gpu_seconds
    module.task_store.adjust_compute_account(
        user_id=user["id"], gpu_seconds=-(allowance + 600), actor_user_id=99,
        reason="Correction below zero", idempotency_key="negative",
    )

    waterfall = _ledger(module, headers)["gpu_waterfall"]
    assert waterfall["closing_gpu_seconds"] == -600
    assert waterfall["summary"]["settled_balance_gpu_seconds"] == -600
    assert waterfall["summary"]["remaining_gpu_seconds"] < 0
    assert waterfall["steps"][-1]["balance_gpu_seconds"] == -600


def test_corrections_and_reversals_are_ordinary_signed_steps(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    module.task_store.set_compute_allowance(
        user_id=user["id"], monthly_gpu_seconds=1_200, actor_user_id=99,
        idempotency_key="cap",
    )
    period = module.task_store.gpu_credit_summary(user["id"])["period"]
    ledger = module.task_store.resource_ledger_table
    with module.task_store.engine.begin() as conn:
        conn.execute(sa.insert(ledger).values(
            subject_type="user", subject_id=user["id"], period=period,
            kind="reversal", unit="gpu_second", resource_class="",
            quantity=90, actor_user_id=None, reason="Canceled settlement reversed",
            reason_code=None, evidence_source="reconciliation",
            idempotency_key="reversal-fixture", created_at=time.time(),
        ))

    payload = _ledger(module, headers)
    entries = _gpu_entries(payload)
    assert {"allowance_adjustment", "reversal"} <= {entry["kind"] for entry in entries}
    by_id = {entry["id"]: entry for entry in entries}
    for step in payload["gpu_waterfall"]["steps"]:
        assert step["delta_gpu_seconds"] == by_id[step["entry_id"]]["quantity"]
    summary = payload["gpu_waterfall"]["summary"]
    assert payload["gpu_waterfall"]["closing_gpu_seconds"] == (
        summary["monthly_grant_gpu_seconds"] + summary["adjustment_gpu_seconds"] - summary["usage_gpu_seconds"]
    )


def test_unattributed_facts_are_published_and_named(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    module.task_store.adjust_compute_account(
        user_id=user["id"], gpu_seconds=60, actor_user_id=99,
        reason="Pilot allocation", idempotency_key="unattributed",
    )

    payload = _ledger(module, headers)
    unattributed = [
        entry for entry in _gpu_entries(payload)
        if entry["kind"] in {"monthly_grant", "admin_adjustment"}
    ]
    assert unattributed
    assert all(entry["task_id"] is None and entry["stage_id"] is None for entry in unattributed)
    # The step still names the immutable fact, so the chart explains every credit.
    step_ids = {step["entry_id"] for step in payload["gpu_waterfall"]["steps"]}
    assert {entry["id"] for entry in unattributed} <= step_ids


def test_reservation_and_release_change_availability_without_appending_facts(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    before = _ledger(module, headers)

    reservation = module.task_store.reserve_compute_admission(
        user_id=user["id"], task_id="a" * 32
    )
    assert reservation["quantity"] > 0
    held = _ledger(module, headers)
    assert held["gpu_waterfall"]["summary"]["reserved_gpu_seconds"] == reservation["quantity"]
    assert held["gpu_waterfall"]["summary"]["remaining_gpu_seconds"] == (
        held["gpu_waterfall"]["summary"]["settled_balance_gpu_seconds"]
        - reservation["quantity"]
        - held["gpu_waterfall"]["summary"]["unsettled_gpu_seconds"]
    )
    # A hold is admission state: it is not a ledger entry and never a delta.
    assert [entry["id"] for entry in held["entries"]] == [entry["id"] for entry in before["entries"]]

    assert module.task_store.release_reservation(task_id="a" * 32) is True
    released = _ledger(module, headers)
    assert released["gpu_waterfall"]["summary"]["reserved_gpu_seconds"] == 0
    assert released["gpu_waterfall"]["summary"]["remaining_gpu_seconds"] == (
        before["gpu_waterfall"]["summary"]["remaining_gpu_seconds"]
    )
    assert [entry["id"] for entry in released["entries"]] == [entry["id"] for entry in before["entries"]]


def test_reads_are_idempotent_and_duplicate_adjustments_append_once(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    for _ in range(2):
        module.task_store.adjust_compute_account(
            user_id=user["id"], gpu_seconds=60, actor_user_id=99,
            reason="Approved collaboration", idempotency_key="replayed",
        )

    first = _ledger(module, headers)
    second = _ledger(module, headers)
    assert first["entries"] == second["entries"]
    assert first["gpu_waterfall"] == second["gpu_waterfall"]
    steps = first["gpu_waterfall"]["steps"]
    assert len({step["entry_id"] for step in steps}) == len(steps)
    assert len([entry for entry in _gpu_entries(first) if entry["kind"] == "admin_adjustment"]) == 1


def test_an_unrepresentable_value_is_unavailable_not_rounded(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    period = module.task_store.gpu_credit_summary(user["id"])["period"]
    ledger = module.task_store.resource_ledger_table
    with module.task_store.engine.begin() as conn:
        conn.execute(sa.insert(ledger).values(
            subject_type="user", subject_id=user["id"], period=period,
            kind="admin_adjustment", unit="gpu_second", resource_class="",
            quantity=2**53, actor_user_id=99, reason="Corrupt fixture",
            reason_code="admin_adjustment", evidence_source="policy",
            idempotency_key="overflow-fixture", created_at=time.time(),
        ))

    response = module.app.test_client().get("/compute/api/resource-ledger", headers=headers)
    assert response.status_code == 503
    body = response.get_json()
    assert body["unavailable_reason"] == "ledger_value_out_of_range"
    assert "entries" not in body and "gpu_waterfall" not in body


def _store_outage(*_args, **_kwargs):
    raise sa.exc.OperationalError("SELECT", {}, Exception("database is locked"))


def test_a_transient_store_outage_is_reported_as_unavailable(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    monkeypatch.setattr(module.task_store, "resource_ledger_window", _store_outage)

    response = module.app.test_client().get("/compute/api/resource-ledger", headers=headers)
    assert response.status_code == 503
    body = response.get_json()
    assert body["unavailable_reason"] == "ledger_unavailable"
    # Unavailability is never an empty history or a zero balance.
    assert "entries" not in body and "gpu_waterfall" not in body


def test_the_admin_report_reports_the_same_unavailability_as_the_account_read(monkeypatch, tmp_path):
    """Both ledger scopes map an unrepresentable value and an outage to one 503."""
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    _test_client_auth(module)
    admin_headers = _admin_client_auth(module)
    user = _user(module)
    report_url = f"/compute/api/auth/admin/reports/resources?subject={user['id']}"
    period = module.task_store.gpu_credit_summary(user["id"])["period"]
    ledger = module.task_store.resource_ledger_table
    with module.task_store.engine.begin() as conn:
        conn.execute(sa.insert(ledger).values(
            subject_type="user", subject_id=user["id"], period=period,
            kind="admin_adjustment", unit="gpu_second", resource_class="",
            quantity=2**53, actor_user_id=99, reason="Corrupt fixture",
            reason_code="admin_adjustment", evidence_source="policy",
            idempotency_key="overflow-admin-fixture", created_at=time.time(),
        ))
    overflow = client.get(report_url, headers=admin_headers)
    assert overflow.status_code == 503
    assert overflow.get_json()["unavailable_reason"] == "ledger_value_out_of_range"
    assert "canonical_envelope" not in overflow.get_json()

    monkeypatch.setattr(module.task_store, "resource_ledger_window", _store_outage)
    outage = client.get(report_url, headers=admin_headers)
    assert outage.status_code == 503
    assert outage.get_json()["unavailable_reason"] == "ledger_unavailable"
    assert "ledger" not in outage.get_json()


def test_the_admin_drill_in_serves_the_same_waterfall_and_respects_rbac(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    user_headers = _test_client_auth(module)
    admin_headers = _admin_client_auth(module)
    user = _user(module)
    _charge(module, user["id"], "8301", seconds=90, at=time.time() - 90)

    own = _ledger(module, user_headers, limit=50)
    client = module.app.test_client()
    report = client.get(
        f"/compute/api/auth/admin/reports/resources?subject={user['id']}&limit=50",
        headers=admin_headers,
    )
    assert report.status_code == 200
    admin_ledger = report.get_json()["ledger"]
    assert admin_ledger["gpu_waterfall"] == own["gpu_waterfall"]
    assert admin_ledger["order"] == "chronological"

    assert client.get(
        f"/compute/api/auth/admin/reports/resources?subject={user['id']}", headers=user_headers
    ).status_code == 403
    assert client.get("/compute/api/resource-ledger").status_code == 401


def test_reading_the_waterfall_never_rewrites_append_only_facts(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    _charge(module, user["id"], "8401", seconds=30, at=time.time() - 30)
    before = [dict(entry) for entry in module.task_store.list_compute_ledger(user["id"], limit=200)]

    _ledger(module, headers)

    after = [dict(entry) for entry in module.task_store.list_compute_ledger(user["id"], limit=200)]
    assert after == before


def test_the_gpu_credit_balance_routes_refuse_an_unrepresentable_quantity(monkeypatch, tmp_path):
    """A balance read refuses a quantity no JSON client can represent exactly.

    The ledger read already refused; the two GPU balance routes published the
    same fact as a rounded number.  One corrupt row must not make one surface
    truthful and another invent a value.
    """
    module = _module(monkeypatch, tmp_path)
    user_headers = _test_client_auth(module)
    admin_headers = _admin_client_auth(module)
    user = _user(module)
    period = module.task_store.gpu_credit_summary(user["id"])["period"]
    ledger = module.task_store.resource_ledger_table
    with module.task_store.engine.begin() as conn:
        conn.execute(sa.insert(ledger).values(
            subject_type="user", subject_id=user["id"], period=period,
            kind="admin_adjustment", unit="gpu_second", resource_class="",
            quantity=2**53, actor_user_id=99, reason="Corrupt fixture",
            reason_code="admin_adjustment", evidence_source="policy",
            idempotency_key="overflow-credit-fixture", created_at=time.time(),
        ))

    client = module.app.test_client()
    own = client.get("/compute/api/gpu-credit", headers=user_headers)
    assert own.status_code == 503
    body = own.get_json()
    assert body["unavailable_reason"] == "ledger_value_out_of_range"
    assert "adjustment_gpu_seconds" not in body and "remaining_credits" not in body

    admin = client.get(
        f"/compute/api/auth/admin/users/{user['id']}/gpu-credit", headers=admin_headers
    )
    assert admin.status_code == 503
    assert admin.get_json()["unavailable_reason"] == "ledger_value_out_of_range"
    assert "adjustment_gpu_seconds" not in admin.get_json()


def test_the_entitlement_route_refuses_an_unrepresentable_gpu_balance(monkeypatch, tmp_path):
    """The envelope route publishes the same balance as the guarded reads."""
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    period = module.task_store.gpu_credit_summary(user["id"])["period"]
    ledger = module.task_store.resource_ledger_table
    with module.task_store.engine.begin() as conn:
        conn.execute(sa.insert(ledger).values(
            subject_type="user", subject_id=user["id"], period=period,
            kind="admin_adjustment", unit="gpu_second", resource_class="",
            quantity=2**53 + 1, actor_user_id=99, reason="Corrupt fixture",
            reason_code="admin_adjustment", evidence_source="policy",
            idempotency_key="overflow-envelope-fixture", created_at=time.time(),
        ))

    response = module.app.test_client().get("/compute/api/resource-entitlement", headers=headers)
    assert response.status_code == 503
    body = response.get_json()
    assert body["unavailable_reason"] == "ledger_value_out_of_range"
    assert "compute" not in body


def test_a_storage_dominated_window_reports_no_gpu_step_and_the_settled_opening(monkeypatch, tmp_path):
    """A window filled by newer storage facts is partial, not a zero history.

    The GPU facts still exist in the period; they are simply outside the showing.
    The opening balance must equal the settled total those omitted facts sum to,
    and ``complete`` must say the window does not show them.
    """
    module = _module(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    user = _user(module)
    _charge(module, user["id"], "8401", seconds=90, at=time.time() - 90)
    period = module.task_store.gpu_credit_summary(user["id"])["period"]
    ledger = module.task_store.resource_ledger_table
    now = time.time()
    with module.task_store.engine.begin() as conn:
        for index in range(2):
            conn.execute(sa.insert(ledger).values(
                subject_type="user", subject_id=user["id"], period=period,
                kind="storage_usage", unit="storage_byte", resource_class="",
                quantity=-(1000 + index), task_id=str(index).rjust(32, "0"),
                reason="Storage ownership", reason_code="storage_usage",
                evidence_source="lifecycle", idempotency_key=f"storage-window-{index}",
                created_at=now + index,
            ))

    window = _ledger(module, headers, limit=2)
    assert _gpu_entries(window) == []
    waterfall = window["gpu_waterfall"]
    assert waterfall["entry_count"] == 0
    assert waterfall["total_entry_count"] > 0
    assert waterfall["complete"] is False
    assert waterfall["opening_gpu_seconds"] == waterfall["closing_gpu_seconds"]
    summary = module.task_store.gpu_credit_summary(user["id"])
    assert waterfall["opening_gpu_seconds"] == (
        summary["monthly_grant_gpu_seconds"] + summary["adjustment_gpu_seconds"] - summary["usage_gpu_seconds"]
    )
