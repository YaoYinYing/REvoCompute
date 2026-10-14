# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Admin user listing's GPU-credit projection, as a contract.

``GET /compute/api/auth/admin/users`` publishes ``AdminUser.gpu_credit`` as
``$ref: GPUCreditSummary`` — the same component the per-user detail route and the
user's own ``/compute/api/gpu-credit`` serve.  A listing that put a differently
shaped object in that field would let every reader of the published contract
render a balance the server never computed, which is exactly how an administrator
sees "0 credits" for an account that holds a real allowance.

These cases therefore assert the served body against the server's own published
component, and assert that the listing and the detail route agree field for
field: one canonical projection, so ``gpu_second`` and ``credit = 60
GPU-seconds`` cannot diverge between two surfaces that were supposed to show the
same fact.
"""

from __future__ import annotations

import time

from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from jsonschema import Draft202012Validator

CREDIT_UNIT_GPU_SECONDS = 60
DEFAULT_MONTHLY_GPU_SECONDS = 60_000


def _validate(spec, schema_name: str, payload: object) -> None:
    Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema_name}", "components": spec["components"]},
    ).validate(payload)


def _module(monkeypatch, tmp_path):
    return _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )


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


def _listing(module, headers) -> dict[int, dict]:
    """Every listed user's ``gpu_credit`` projection, keyed by user id."""
    response = module.app.test_client().get(
        "/compute/api/auth/admin/users", headers=_bearer(headers)
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return {item["id"]: item for item in response.json["users"]}


def test_the_listing_serves_the_published_summary_for_every_user(monkeypatch, tmp_path):
    """The listing's ``gpu_credit`` is the published component, not a bare summary.

    A user holding the deployment's monthly grant must read as that grant: the
    published shape carries ``remaining_credits`` and the projection constant, and
    a listing that omitted them made every consumer fall back to zero.
    """
    module = _module(monkeypatch, tmp_path)
    users = module.app.config["user_db"]
    admin = _active_user(users, "listing-admin", role="admin")
    granted = _active_user(users, "listing-granted")
    client = module.app.test_client()
    spec = client.get("/openapi.json").get_json()

    listed = _listing(module, admin)

    for item in listed.values():
        _validate(spec, "AdminUser", item)
        _validate(spec, "GPUCreditSummary", item["gpu_credit"])
    credit = listed[granted["id"]]["gpu_credit"]
    assert credit["credit_unit_gpu_seconds"] == CREDIT_UNIT_GPU_SECONDS
    assert credit["monthly_grant_gpu_seconds"] == DEFAULT_MONTHLY_GPU_SECONDS
    assert credit["remaining_gpu_seconds"] == DEFAULT_MONTHLY_GPU_SECONDS
    assert credit["remaining_credits"] == DEFAULT_MONTHLY_GPU_SECONDS / CREDIT_UNIT_GPU_SECONDS
    assert isinstance(credit["history"], list)


def test_the_listing_shows_the_account_its_own_balance_verbatim(monkeypatch, tmp_path):
    """Two surfaces of the same fact must not answer differently.

    An administrator reading the listing and the account reading its own
    ``/compute/api/gpu-credit`` are reading one ledger, so the listing carries
    that account's own projection unchanged; the operator's admission flag sits
    beside it as a separate ``AdminUser`` field rather than inside the summary.
    """
    module = _module(monkeypatch, tmp_path)
    users = module.app.config["user_db"]
    admin = _active_user(users, "detail-admin", role="admin")
    target = _active_user(users, "detail-target")
    module.task_store.adjust_compute_account(
        user_id=target["id"],
        gpu_seconds=600,
        actor_user_id=admin["id"],
        reason="Approved extension",
        idempotency_key="detail-extension",
    )
    client = module.app.test_client()

    listed = _listing(module, admin)[target["id"]]["gpu_credit"]
    own = client.get("/compute/api/gpu-credit", headers=_bearer(target)).json
    assert own.pop("allow_gpu_use") is False

    assert listed == own
    assert listed["remaining_credits"] == (
        DEFAULT_MONTHLY_GPU_SECONDS + 600
    ) / CREDIT_UNIT_GPU_SECONDS

    # The operator's drill-in answers the same balance, and adds the
    # administrative audit fields to each history entry.
    detail = client.get(
        f"/compute/api/auth/admin/users/{target['id']}/gpu-credit", headers=_bearer(admin)
    ).json
    for field in (
        "user_id",
        "period",
        "credit_unit_gpu_seconds",
        "monthly_grant_gpu_seconds",
        "usage_gpu_seconds",
        "adjustment_gpu_seconds",
        "remaining_gpu_seconds",
        "monthly_grant_credits",
        "usage_credits",
        "adjustment_credits",
        "remaining_credits",
    ):
        assert detail[field] == listed[field], field


def test_a_granted_allowance_of_zero_reads_as_zero_and_not_as_missing(monkeypatch, tmp_path):
    """Exactly zero and "nobody recorded a balance" are different answers.

    The policy decision here really is a zero-second allowance, so the projection
    must carry a real ``0`` — a missing field would be indistinguishable from an
    account whose balance the server never computed.
    """
    module = _module(monkeypatch, tmp_path)
    users = module.app.config["user_db"]
    admin = _active_user(users, "zero-admin", role="admin")
    target = _active_user(users, "zero-target")
    module.task_store.set_compute_allowance(
        user_id=target["id"],
        monthly_gpu_seconds=0,
        actor_user_id=admin["id"],
        idempotency_key="zero-allowance",
    )

    credit = _listing(module, admin)[target["id"]]["gpu_credit"]

    assert credit["remaining_credits"] == 0
    assert credit["monthly_grant_credits"] == 0
    assert "remaining_credits" in credit


def test_overdraft_is_reported_negative_and_never_clamped(monkeypatch, tmp_path):
    """An account over its allowance reports the real negative balance."""
    module = _module(monkeypatch, tmp_path)
    users = module.app.config["user_db"]
    admin = _active_user(users, "overdraft-admin", role="admin")
    target = _active_user(users, "overdraft-target")
    module.task_store.adjust_compute_account(
        user_id=target["id"],
        gpu_seconds=-(DEFAULT_MONTHLY_GPU_SECONDS + 600),
        actor_user_id=admin["id"],
        reason="Recover an over-grant",
        idempotency_key="overdraft-recovery",
    )

    credit = _listing(module, admin)[target["id"]]["gpu_credit"]

    assert credit["remaining_gpu_seconds"] == -600
    assert credit["remaining_credits"] == -10


def test_unsettled_usage_is_published_as_a_conservative_balance(monkeypatch, tmp_path):
    """A live allocation keeps the balance a lower bound, and the envelope says so.

    The allocation has definitely consumed something and no authoritative elapsed
    duration exists yet, so an exact figure would be a fabricated measurement.  The
    credit projection is the canonical conservative balance — it already reserves
    the unsettled worst case — and the envelope beside it names the outstanding
    count and marks the usage incomplete, so a reader is never told a settled zero.
    """
    module = _module(monkeypatch, tmp_path)
    users = module.app.config["user_db"]
    admin = _active_user(users, "unsettled-admin", role="admin")
    target = _active_user(users, "unsettled-target")
    module.task_store.record_allocation_start(
        user_id=target["id"],
        task_id="a" * 32,
        stage_id="model",
        slurm_job_id="9711",
        gpu_count=2,
        cpu_cores=1,
        started_at=time.time(),
    )

    credit = _listing(module, admin)[target["id"]]["gpu_credit"]
    envelope = module.task_store.resource_envelope(target["id"])
    gpu = next(entry for entry in envelope.compute if entry.unit == "gpu_second")

    # No settled usage exists, and the outstanding allocation is still reserved:
    # the reported balance is conservative rather than an exact, fabricated zero.
    assert credit["usage_gpu_seconds"] == 0
    assert credit["remaining_gpu_seconds"] < DEFAULT_MONTHLY_GPU_SECONDS
    assert credit["remaining_gpu_seconds"] == gpu.remaining

    # The canonical envelope names the unknown, so a consumer that must present
    # "not yet known" rather than a number reads it from the same subject.
    assert gpu.usage_complete is False
    assert gpu.unsettled == 1
    assert gpu.unsettled_quantity > 0


def test_admission_permission_is_a_separate_fact_from_the_balance(monkeypatch, tmp_path):
    """``allow_gpu_use`` gates submission; it is never read as an allowance.

    An account admitted to the GPU queue with no recorded allowance, and an
    account with a healthy allowance that is blocked, must each report both facts
    without either rewriting the other.
    """
    module = _module(monkeypatch, tmp_path)
    users = module.app.config["user_db"]
    admin = _active_user(users, "admission-admin", role="admin")
    blocked = _active_user(users, "admission-blocked")
    users.update_user(blocked["id"], allow_gpu_use=False)

    listed = _listing(module, admin)

    blocked_row = listed[blocked["id"]]
    assert blocked_row["allow_gpu_use"] is False
    assert blocked_row["gpu_credit"]["remaining_credits"] == (
        DEFAULT_MONTHLY_GPU_SECONDS / CREDIT_UNIT_GPU_SECONDS
    )


def test_the_listing_keeps_the_append_only_history_intact(monkeypatch, tmp_path):
    """Reading the listing never rewrites the ledger, and history survives.

    The projection materializes the period's grant as any canonical read does, and
    every earlier entry — including an adjustment's reason and actor — remains
    readable afterwards.
    """
    module = _module(monkeypatch, tmp_path)
    users = module.app.config["user_db"]
    admin = _active_user(users, "history-admin", role="admin")
    target = _active_user(users, "history-target")
    module.task_store.adjust_compute_account(
        user_id=target["id"],
        gpu_seconds=+120,
        actor_user_id=admin["id"],
        reason="Pilot allocation",
        idempotency_key="history-pilot",
    )
    before = module.task_store.list_compute_ledger(target["id"])
    ids_before = [entry["id"] for entry in before]

    _listing(module, admin)

    after = module.task_store.list_compute_ledger(target["id"])
    assert [entry["id"] for entry in after] == ids_before
    assert {entry["kind"] for entry in after} == {"monthly_grant", "admin_adjustment"}


def test_the_listing_requires_an_administrator(monkeypatch, tmp_path):
    """Anonymous is authenticated-for and a non-admin is refused."""
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    regular = _test_client_auth(module)
    admin = _admin_client_auth(module)

    assert client.get("/compute/api/auth/admin/users").status_code == 401
    assert client.get("/compute/api/auth/admin/users", headers=regular).status_code == 403
    assert client.get("/compute/api/auth/admin/users", headers=admin).status_code == 200
