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


def _restrict_runtime(module, runtime: str = "gremlin", *, requestable: bool = True) -> None:
    config_root = Path(module.CONFIG.task_types_config).parent
    policy_dir = config_root / "access_policies"
    policy_dir.mkdir(exist_ok=True)
    (policy_dir / "example.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "example_academic_runner",
                "label": "Example academic access",
                "description": "Operator approval is required.",
                "requires": ["example_academic"],
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
    unknown = client.post(
        "/compute/api/access/requests", headers=user_headers, json={"entitlement": "made_up", "reason": "Test"}
    )
    assert unknown.status_code == 400
    requested = client.post(
        "/compute/api/access/requests",
        headers=user_headers,
        json={"entitlement": "example_academic", "reason": "Academic research"},
    )
    assert requested.status_code == 201
    request_id = requested.get_json()["request"]["id"]
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
        json={"entitlement": "example_academic", "reason": "Research"},
    ).get_json()["request"]
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
        json={"entitlement": "example_academic", "reason": "Research"},
    )
    assert blocked.status_code == 403


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
