# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import io
import time
from pathlib import Path

import yaml
from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from revocompute.task_types import load_registry


def _restrict_runtime(
    module,
    runtime: str = "gremlin",
    *,
    requestable: bool = True,
    requires: list[str] | None = None,
) -> None:
    config_root = Path(module.CONFIG.task_types_config).parent
    policy_dir = config_root / "access_policies"
    policy_dir.mkdir(exist_ok=True)
    (policy_dir / "example.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "example_academic_runner",
                "label": "Example academic access",
                "description": "Operator approval is required.",
                "requires": requires or ["example_academic"],
                "match": "all",
                "requestable": requestable,
                "notice": {"title": "Restricted access", "summary": "This Runner requires operator approval."},
            }
        ),
        encoding="utf-8",
    )
    registry = yaml.safe_load(Path(module.CONFIG.task_types_config).read_text(encoding="utf-8"))
    registry["runtime_families"][runtime]["access_policy"] = "example_academic_runner"
    Path(module.CONFIG.task_types_config).write_text(yaml.safe_dump(registry), encoding="utf-8")
    enabled = {runtime} if runtime != "gremlin" else set()
    load_registry(module.CONFIG.task_types_config, module.CONFIG.runners_dir, enabled)


def _submit_gremlin(client, headers, *, project_id=None):
    data = {"task_type": "gremlin", "params[iter]": "100", "file": (io.BytesIO(b">x\nACDE\n"), "x.fasta")}
    if project_id is not None:
        data.update(scope_type="project", scope_id=str(project_id))
    return client.post(
        "/compute/api/post",
        headers=headers,
        data=data,
        content_type="multipart/form-data",
    )


def _stub_queue(module, monkeypatch) -> None:
    queued = type("Queued", (), {"id": "runner-access-test"})()
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *_args, **_kwargs: queued)


def test_progressive_cooldown_audit_and_admin_visibility(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _restrict_runtime(module)
    _stub_queue(module, monkeypatch)
    client = module.app.test_client()
    user_headers = _test_client_auth(module)
    admin_headers = _admin_client_auth(module)
    db = module.app.config["user_db"]
    user = db.get_user_by_username("tester")

    assert _submit_gremlin(client, user_headers).status_code == 403
    assert _submit_gremlin(client, user_headers).status_code == 403
    suspended = _submit_gremlin(client, user_headers)
    assert suspended.status_code == 403
    blocked = _submit_gremlin(client, user_headers)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1

    events = client.get("/compute/api/auth/admin/access/events", headers=admin_headers).get_json()["events"]
    assert [event["outcome"] for event in events[:4]] == ["blocked", "suspended", "denied", "denied"]
    assert all(event["policy_id"] == "example_academic_runner" for event in events[:4])
    policies = client.get("/compute/api/auth/admin/access/policies", headers=admin_headers).get_json()["policies"]
    policy = next(item for item in policies if item["policy_id"] == "example_academic_runner")
    assert policy["suspended_users"] == 1

    grant = client.post(
        f"/compute/api/auth/admin/users/{user['id']}/entitlements",
        headers=admin_headers,
        json={"entitlement": "example_academic", "basis": "other"},
    )
    assert grant.status_code == 201
    policies = client.get("/compute/api/auth/admin/access/policies", headers=admin_headers).get_json()["policies"]
    assert next(item for item in policies if item["policy_id"] == "example_academic_runner")["suspended_users"] == 0
    assert _submit_gremlin(client, user_headers).status_code == 302
    latest = client.get("/compute/api/auth/admin/access/events?limit=1", headers=admin_headers).get_json()["events"][0]
    assert latest["event_type"] == "runner_access_allowed"
    assert latest["reason_code"] == "task_accepted"


def test_bearer_and_api_key_share_policy_cooldown(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _restrict_runtime(module)
    client = module.app.test_client()
    bearer = _test_client_auth(module)
    db = module.app.config["user_db"]
    user = db.get_user_by_username("tester")
    api_key = {"X-API-Key": db.generate_api_key(user["id"])}

    assert _submit_gremlin(client, bearer).status_code == 403
    assert _submit_gremlin(client, api_key).status_code == 403
    assert _submit_gremlin(client, bearer).status_code == 403
    response = _submit_gremlin(client, api_key)
    assert response.status_code == 429
    assert response.headers["Retry-After"]


def test_audit_failure_never_weakens_entitlement_denial(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _restrict_runtime(module)
    headers = _test_client_auth(module)
    monkeypatch.setattr(
        module.app.config["user_db"], "record_runner_access_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )
    response = _submit_gremlin(module.app.test_client(), headers)
    assert response.status_code == 403
    assert response.get_json()["error"] == "Runner access required"


def test_user_request_admin_review_and_direct_grant_routes(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _restrict_runtime(module)
    _stub_queue(module, monkeypatch)
    client = module.app.test_client()
    user_headers = _test_client_auth(module)
    admin_headers = _admin_client_auth(module)
    user = module.app.config["user_db"].get_user_by_username("tester")

    catalog = client.get("/compute/api/types", headers=user_headers).get_json()
    access = next(item for item in catalog["task_types"] if item["name"] == "gremlin")["access"]
    assert access["restricted"] is True and access["granted"] is False
    assert {"requires", "missing_entitlements", "requestable_entitlements"}.isdisjoint(access)
    current_access = client.get("/compute/api/access", headers=user_headers).get_json()
    assert set(current_access) == {"policies"}
    assert {"requires", "missing_entitlements", "requestable_entitlements"}.isdisjoint(
        current_access["policies"][0]
    )
    anonymous = client.get("/compute/api/types").get_json()
    anonymous_access = next(item for item in anonymous["task_types"] if item["name"] == "gremlin")["access"]
    assert "granted" not in anonymous_access and "request_status" not in anonymous_access
    assert {"requires", "missing_entitlements", "requestable_entitlements"}.isdisjoint(anonymous_access)
    unknown = client.post(
        "/compute/api/access/requests", headers=user_headers, json={"policy_id": "made_up", "reason": "Test"}
    )
    assert unknown.status_code == 400
    requested = client.post(
        "/compute/api/access/requests",
        headers=user_headers,
        json={"policy_id": "example_academic_runner", "reason": "Academic research"},
    )
    assert requested.status_code == 201
    request_id = requested.get_json()["requests"][0]["id"]
    assert client.post(
        f"/compute/api/auth/admin/access/requests/{request_id}/decision",
        headers=user_headers,
        json={"decision": "approved", "basis": "lab_member"},
    ).status_code == 403
    approved = client.post(
        f"/compute/api/auth/admin/access/requests/{request_id}/decision",
        headers=admin_headers,
        json={"decision": "approved", "basis": "individually_verified", "note": "Verified"},
    )
    assert approved.status_code == 200
    grant_id = approved.get_json()["grant"]["id"]
    assert _submit_gremlin(client, user_headers).status_code == 302
    assert client.post(
        f"/compute/api/auth/admin/users/{user['id']}/entitlements/{grant_id}/revoke", headers=admin_headers
    ).status_code == 200
    assert _submit_gremlin(client, user_headers).status_code == 403

    direct = client.post(
        f"/compute/api/auth/admin/users/{user['id']}/entitlements",
        headers=admin_headers,
        json={"entitlement": "example_academic", "basis": "lab_member"},
    )
    assert direct.status_code == 201


def test_rejection_and_non_requestable_entitlement(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _restrict_runtime(module)
    client = module.app.test_client()
    user_headers = _test_client_auth(module)
    admin_headers = _admin_client_auth(module)
    requested = client.post(
        "/compute/api/access/requests",
        headers=user_headers,
        json={"policy_id": "example_academic_runner", "reason": "Research"},
    ).get_json()["requests"][0]
    rejected = client.post(
        f"/compute/api/auth/admin/access/requests/{requested['id']}/decision",
        headers=admin_headers,
        json={"decision": "rejected", "note": "More evidence needed"},
    )
    assert rejected.status_code == 200
    assert module.app.config["user_db"].get_access_request(requested["id"])["status"] == "rejected"

    _restrict_runtime(module, requestable=False)
    blocked = client.post(
        "/compute/api/access/requests",
        headers=user_headers,
        json={"policy_id": "example_academic_runner", "reason": "Research"},
    )
    assert blocked.status_code == 403


def test_policy_request_creates_all_missing_rows_and_returns_stable_conflicts(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _restrict_runtime(module, requires=["entitlement_a", "entitlement_b"])
    client = module.app.test_client()
    headers = _test_client_auth(module)
    db = module.app.config["user_db"]
    user = db.get_user_by_username("tester")
    payload = {"policy_id": "example_academic_runner", "reason": "Research"}

    created = client.post("/compute/api/access/requests", headers=headers, json=payload)
    assert created.status_code == 201
    assert {item["entitlement"] for item in created.get_json()["requests"]} == {
        "entitlement_a",
        "entitlement_b",
    }
    repeat = client.post("/compute/api/access/requests", headers=headers, json=payload)
    assert repeat.status_code == 409
    assert repeat.get_json()["error"] == "Runner access request is already pending"

    for entitlement in ("entitlement_a", "entitlement_b"):
        db.grant_entitlement(user["id"], entitlement, granted_by=user["id"], basis="other")
    granted = client.post("/compute/api/access/requests", headers=headers, json=payload)
    assert granted.status_code == 409
    assert granted.get_json()["error"] == "Runner access is already granted"


def test_direct_grant_route_resolves_matching_pending_request(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _restrict_runtime(module)
    client = module.app.test_client()
    user_headers = _test_client_auth(module)
    admin_headers = _admin_client_auth(module)
    db = module.app.config["user_db"]
    user = db.get_user_by_username("tester")
    requested = client.post(
        "/compute/api/access/requests",
        headers=user_headers,
        json={"policy_id": "example_academic_runner", "reason": "Research"},
    ).get_json()["requests"][0]

    response = client.post(
        f"/compute/api/auth/admin/users/{user['id']}/entitlements",
        headers=admin_headers,
        json={
            "entitlement": "example_academic",
            "basis": "individually_verified",
            "note": "Verified directly",
        },
    )

    assert response.status_code == 201
    assert response.get_json()["grant"]["source_request_id"] == requested["id"]
    assert db.get_access_request(requested["id"])["status"] == "approved"
    assert db.get_pending_access_requests(user["id"]) == []


def test_denial_precedes_upload_task_and_queue_side_effects(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _restrict_runtime(module)
    client = module.app.test_client()
    headers = _admin_client_auth(module)
    before = module.task_store.list_tasks()
    monkeypatch.setattr(
        module.run_compute_task,
        "apply_async",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
    )
    response = _submit_gremlin(client, headers)
    assert response.status_code == 403
    assert response.get_json() == {
        "error": "Runner access required",
        "policy_id": "example_academic_runner",
        "requestable": True,
    }
    assert module.task_store.list_tasks() == before
    assert not any(Path(module.CONFIG.workspace_folder).rglob("*"))


def test_expired_grant_and_admin_role_do_not_bypass_policy(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _restrict_runtime(module)
    client = module.app.test_client()
    admin_headers = _admin_client_auth(module)
    admin = module.app.config["user_db"].get_user_by_username("sysadmin")
    assert _submit_gremlin(client, admin_headers).status_code == 403
    module.app.config["user_db"].grant_entitlement(
        admin["id"],
        "example_academic",
        granted_by=admin["id"],
        basis="other",
        expires_at=time.time() + 0.01,
    )
    time.sleep(0.02)
    assert _submit_gremlin(client, admin_headers).status_code == 403


def test_api_key_submission_uses_same_entitlement_check(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _restrict_runtime(module)
    _stub_queue(module, monkeypatch)
    client = module.app.test_client()
    _test_client_auth(module)
    db = module.app.config["user_db"]
    user = db.get_user_by_username("tester")
    api_headers = {"X-API-Key": db.generate_api_key(user["id"])}
    assert _submit_gremlin(client, api_headers).status_code == 403
    db.grant_entitlement(user["id"], "example_academic", granted_by=user["id"], basis="other")
    assert _submit_gremlin(client, api_headers).status_code == 302


def test_public_runner_is_unaffected(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _stub_queue(module, monkeypatch)
    client = module.app.test_client()
    assert _submit_gremlin(client, _test_client_auth(module)).status_code == 302


def test_restricted_gpu_runner_requires_entitlement_and_gpu_access(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        {"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "alphafold"},
    )
    _restrict_runtime(module, "alphafold")
    _stub_queue(module, monkeypatch)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    db = module.app.config["user_db"]
    user = db.get_user_by_username("tester")

    def submit():
        return client.post(
            "/compute/api/post",
            headers=headers,
            data={"task_type": "alphafold", "file": (io.BytesIO(b">x\nACDE\n"), "x.fasta")},
            content_type="multipart/form-data",
        )

    assert submit().get_json()["error"] == "Runner access required"
    db.grant_entitlement(user["id"], "example_academic", granted_by=user["id"], basis="other")
    assert submit().get_json()["error"].startswith("GPU access required")
    db.update_user(user["id"], allow_gpu_use=True)
    assert submit().status_code == 302


def test_project_membership_does_not_supply_owner_entitlement(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    _restrict_runtime(module)
    _stub_queue(module, monkeypatch)
    owner_headers = _test_client_auth(module, "owner")
    member_headers = _test_client_auth(module, "member")
    db = module.app.config["user_db"]
    owner = db.get_user_by_username("owner")
    member = db.get_user_by_username("member")
    store = module.app.config["collaboration"]
    project = store.create_project(owner["id"], "Restricted science")
    invitation = store.invite(project["id"], member["id"], owner["id"], "contributor")
    assert store.respond_invitation(invitation["id"], member["id"], True)
    db.grant_entitlement(owner["id"], "example_academic", granted_by=owner["id"], basis="other")

    client = module.app.test_client()
    assert _submit_gremlin(client, member_headers, project_id=project["id"]).status_code == 403
    db.grant_entitlement(member["id"], "example_academic", granted_by=owner["id"], basis="other")
    assert _submit_gremlin(client, member_headers, project_id=project["id"]).status_code == 302
    assert _submit_gremlin(client, owner_headers, project_id=project["id"]).status_code in {202, 302}
