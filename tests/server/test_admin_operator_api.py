# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Level 1 security matrix for the Admin Runner-fleet control-plane API.

Authorization is the route's job and is asserted here against the real Flask
app: anonymous callers, non-admins, and cookie-authenticated mutations are all
refused, and only an authorized admin reaches a typed operator operation.  The
service itself is faked where the test is about the authorization boundary, so
a denial is proven to happen *before* any control-core call.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from conftest import _admin_client_auth, _test_client_auth, _load_pssm_module
from revocompute.operator_actions import get_action


class _FakeOperatorService:
    """A service that records how it was called and returns a bounded shape."""

    def __init__(self):
        self.calls: list[tuple] = []

    def fleet(self, user_id):
        self.calls.append(("fleet", user_id))
        return {"runners": [], "executor": {"available": False, "reason": "operator_executor_unavailable"}}

    def detail(self, runner_family, user_id):
        self.calls.append(("detail", runner_family, user_id))
        return {"runner_family": runner_family, "readiness": {}, "capacity": {}, "access": {}, "actions": []}

    def plan(self, action, runner_family):
        get_action(action)  # the closed registry is the real rejection point
        self.calls.append(("plan", action, runner_family))
        return SimpleNamespace(
            as_dict=lambda: {"action": action, "runner_family": runner_family, "plan_digest": "sha256:" + "a" * 16}
        )

    def submit(self, action, runner_family, **kwargs):
        get_action(action)
        self.calls.append(("submit", action, runner_family, kwargs))
        return SimpleNamespace(
            job={"job_id": None, "status": "SUCCEEDED"},
            created=False,
            plan=SimpleNamespace(as_dict=lambda: {"action": action, "plan_digest": kwargs["plan_digest"]}),
        )

    def history(self, runner_family, limit=50):
        self.calls.append(("history", runner_family, limit))
        return []

    def jobs(self, **kwargs):
        self.calls.append(("jobs", kwargs))
        return []

    def job(self, job_id):
        self.calls.append(("job", job_id))
        return {"job_id": job_id, "status": "RUNNING"}

    def cancel(self, job_id, *, actor_user_id):
        self.calls.append(("cancel", job_id, actor_user_id))
        return {"job_id": job_id, "status": "CANCELLED"}


def _app_with_service(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    service = _FakeOperatorService()
    module.app.config["operator_service"] = service
    return module, service


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/compute/api/auth/admin/runners"),
        ("get", "/compute/api/auth/admin/runners/demo"),
        ("get", "/compute/api/auth/admin/runners/demo/history"),
        ("get", "/compute/api/auth/admin/operator/jobs"),
        ("get", "/compute/api/auth/admin/operator/jobs/job-1"),
        ("post", "/compute/api/auth/admin/runners/demo/plan"),
        ("post", "/compute/api/auth/admin/runners/demo/actions"),
        ("post", "/compute/api/auth/admin/operator/jobs/job-1/cancel"),
    ],
)
def test_anonymous_requests_are_rejected(monkeypatch, tmp_path, method, path):
    module, service = _app_with_service(monkeypatch, tmp_path)
    client = module.app.test_client()
    response = getattr(client, method)(path, json={})
    assert response.status_code == 401
    assert service.calls == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/compute/api/auth/admin/runners"),
        ("get", "/compute/api/auth/admin/runners/demo"),
        ("post", "/compute/api/auth/admin/runners/demo/plan"),
        ("post", "/compute/api/auth/admin/runners/demo/actions"),
        ("post", "/compute/api/auth/admin/operator/jobs/job-1/cancel"),
    ],
)
def test_authenticated_non_admins_are_rejected(monkeypatch, tmp_path, method, path):
    module, service = _app_with_service(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _test_client_auth(module, username="ordinary")
    response = getattr(client, method)(path, headers=headers, json={})
    assert response.status_code == 403
    assert service.calls == []


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/compute/api/auth/admin/runners/demo/plan", {"action": "runner.status"}),
        ("post", "/compute/api/auth/admin/runners/demo/actions", {"action": "runner.status", "plan_digest": "sha256:" + "a" * 16}),
        ("post", "/compute/api/auth/admin/operator/jobs/job-1/cancel", {}),
    ],
)
def test_cookie_authenticated_mutations_are_refused_by_the_bearer_gate(monkeypatch, tmp_path, method, path, body):
    """A session cookie must not authorize a privileged mutation (CSRF gate)."""
    module, service = _app_with_service(monkeypatch, tmp_path)
    client = module.app.test_client()
    _admin_client_auth(module)
    # Establish a cookie-authenticated session the way a browser would.
    login = client.post(
        "/compute/api/auth/login",
        json={"username": "sysadmin", "password": "admin_password"},
    )
    assert login.status_code == 200
    assert login.headers.get("Set-Cookie")

    response = getattr(client, method)(path, json=body)
    assert response.status_code == 403
    assert "Bearer token" in response.get_json()["error"]
    assert service.calls == []


def test_an_authorized_admin_reaches_only_the_typed_operation(monkeypatch, tmp_path):
    module, service = _app_with_service(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _admin_client_auth(module)

    fleet = client.get("/compute/api/auth/admin/runners", headers=headers)
    assert fleet.status_code == 200
    assert fleet.get_json()["executor"]["available"] is False

    plan = client.post(
        "/compute/api/auth/admin/runners/demo/plan", headers=headers, json={"action": "runner.status"}
    )
    assert plan.status_code == 200
    assert plan.get_json()["runner_family"] == "demo"

    assert ("plan", "runner.status", "demo") in service.calls


def test_unknown_actions_and_extra_fields_are_rejected_before_the_service(monkeypatch, tmp_path):
    module, service = _app_with_service(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _admin_client_auth(module)

    unknown = client.post(
        "/compute/api/auth/admin/runners/demo/plan", headers=headers, json={"action": "runner.exec"}
    )
    assert unknown.status_code == 400

    extra = client.post(
        "/compute/api/auth/admin/runners/demo/actions",
        headers=headers,
        json={"action": "runner.status", "plan_digest": "sha256:" + "a" * 16, "command": "rm -rf /"},
    )
    assert extra.status_code == 400

    family_in_body = client.post(
        "/compute/api/auth/admin/runners/demo/plan",
        headers=headers,
        json={"action": "runner.status", "runner_family": "other"},
    )
    assert family_in_body.status_code == 400  # the path owns the target, not the body

    malformed = client.post("/compute/api/auth/admin/runners/demo/plan", headers=headers, json={"action": 7})
    assert malformed.status_code == 400

    assert all(call[0] != "submit" for call in service.calls)


def test_oversized_parameters_are_rejected(monkeypatch, tmp_path):
    module, _service = _app_with_service(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _admin_client_auth(module)

    for family in ("d" * 4096, "..", "demo/../other", "demo;id", "-rf"):
        response = client.post(
            "/compute/api/auth/admin/runners/" + family + "/plan",
            headers=headers,
            json={"action": "runner.status"},
        )
        # A value that is not even the shape of a canonical family is a
        # not-found resource, never something the control core resolves.
        assert response.status_code in {404, 405}, family


def test_wrong_http_method_is_rejected(monkeypatch, tmp_path):
    module, _service = _app_with_service(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _admin_client_auth(module)
    assert client.post("/compute/api/auth/admin/runners", headers=headers, json={}).status_code == 405
    assert client.get("/compute/api/auth/admin/runners/demo/plan", headers=headers).status_code == 405
