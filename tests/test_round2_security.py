# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Regression tests for the second defensive security review.

Each test pins one externally observable contract: a bounded batch delete, an
id-existence oracle that stays closed, a logout that always ends the browser
session, a per-tenant Tool storage share, and a guest role that reaches no
compute boundary.
"""

from __future__ import annotations

import io
import json
import uuid

from conftest import _extract_md5, _load_pssm_module, _test_client_auth, _upsert_task_for_user
from revocompute.auth import generate_token
from revocompute.tool_calls import ToolAdmissionError, ToolCallDatabase, new_tool_call_id


class _AsyncResult:
    id = "celery-test-id"


def _module(monkeypatch, tmp_path, extra_env: dict | None = None):
    environment = {"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    environment.update(extra_env or {})
    return _load_pssm_module(monkeypatch, tmp_path, environment)


def _guest_headers(module, username: str = "guest_user") -> dict[str, str]:
    db = module.app.config["user_db"]
    user = db.create_user(
        username=username,
        email=f"{username}@test.local",
        password="guestpass123",
        role="guest",
        registration_status="approved",
        user_status="active",
    )
    db.verify_email(user["id"])
    return {"Authorization": f"Bearer {generate_token(user['id'])}"}


# ── SEC-DOS-9: batch delete is bounded ─────────────────────────────────────────


def test_batch_delete_rejects_more_ids_than_the_cap(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = {**_test_client_auth(module), "Content-Type": "application/json"}

    response = client.post(
        "/compute/api/delete",
        headers=headers,
        data=json.dumps({"md5sums": [uuid.uuid4().hex for _ in range(101)]}),
    )

    assert response.status_code == 400
    assert "at most" in response.json["error"]


# ── SEC-AUTHZ-3: batch delete reports foreign ids as missing ───────────────────


def test_batch_delete_does_not_disclose_foreign_task_existence(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    owner_header = _test_client_auth(module)
    other_header = _test_client_auth(module, "other", "password2")

    foreign_md5 = uuid.uuid4().hex
    foreign_dir = tmp_path / "foreign_task"
    foreign_dir.mkdir(parents=True, exist_ok=True)
    _upsert_task_for_user(
        module,
        foreign_md5,
        filename="foreign.fasta",
        file_path=foreign_dir / "foreign.fasta",
        result_dir=foreign_dir,
        username="other",
        status="finished",
    )

    response = client.post(
        "/compute/api/delete",
        headers={**owner_header, "Content-Type": "application/json"},
        data=json.dumps({"md5sums": [foreign_md5]}),
    )

    assert response.status_code == 200
    payload = response.json
    assert "forbidden" not in payload
    assert payload["not_found"] == [foreign_md5]
    assert payload["deleted"] == []
    assert module.task_store.get_task(foreign_md5)["status"] == "finished"


# ── SEC-AUTHZ-2: unowned tasks look missing across the read surfaces ───────────


def test_unowned_task_looks_missing_on_every_read_surface(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *a, **kw: _AsyncResult())
    client = module.app.test_client()
    owner_header = _test_client_auth(module)
    other_header = _test_client_auth(module, "other", "password2")

    upload = client.post(
        "/compute/api/post",
        data={
            "task_type": "gremlin",
            "files": (io.BytesIO(b">test\nACDE\n"), "upload.fasta"),
            "input_roles": "sequence",
        },
        headers=owner_header,
    )
    assert upload.status_code == 302
    md5sum = _extract_md5(upload.headers["Location"])

    # The task exists and belongs to someone else: no 403 may confirm that a
    # foreign id exists on any read surface.
    for template in (
        "/compute/api/running/{id}",
        "/compute/api/results/{id}",
        "/compute/api/download/{id}",
        "/compute/results/{id}",
    ):
        response = client.get(template.format(id=md5sum), headers=other_header)
        assert response.status_code == 404, template

    unowned = client.get(f"/compute/api/running/{md5sum}", headers=other_header)
    missing = client.get(f"/compute/api/running/{'0' * 32}", headers=other_header)
    assert set(unowned.json) == set(missing.json) == {"status", "md5sum"}
    assert unowned.json["status"] == missing.json["status"] == "not_found"


# ── SEC-AUTHZ-4: logout always expires the cookie ──────────────────────────────


def test_cookie_only_logout_still_clears_the_cookie(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _guest_headers(module)  # create the account
    client = module.app.test_client()
    db = module.app.config["user_db"]
    user = db.get_user_by_username("guest_user")
    client.set_cookie("auth_token", generate_token(user["id"]))

    response = client.post("/compute/api/auth/logout")

    assert response.status_code == 403
    cookie = response.headers.get("Set-Cookie", "")
    assert "auth_token=" in cookie and "Expires=" in cookie
    # Cookie-only logout must not invalidate the bearer the same session holds.
    assert db.get_user_by_username("guest_user")["token_version"] == user["token_version"]


# ── SEC-DOS-1: one tenant cannot hold the whole Tool byte pool ─────────────────


def test_one_user_cannot_reserve_the_whole_tool_storage_pool(tmp_path):
    store = ToolCallDatabase(str(tmp_path / "tool-calls.sqlite3"))

    def reserve(user_id: int, reserved_bytes: int):
        return store.reserve(
            tool_call_id=new_tool_call_id(),
            tool_type="inspect",
            runtime_family="fixture",
            runtime_identity="fixture-identity",
            user_id=user_id,
            username=f"user-{user_id}",
            parameter_json="{}",
            input_manifest_json='{"inputs":{}}',
            idempotency_key=None,
            per_user_limit=2,
            global_limit=8,
            reserved_bytes=reserved_bytes,
            storage_max_bytes=100,
        )

    assert reserve(1, 50).created is True
    # The tenant already holds its half of the pool, so the next call is
    # refused even though the global sum is only at 50 of 100 bytes.
    try:
        reserve(1, 20)
    except ToolAdmissionError as exc:
        assert exc.reason == "user_storage_limit"
    else:
        raise AssertionError("a single tenant consumed the whole Tool storage pool")

    # Another tenant still has its own room in the same pool.
    assert reserve(2, 20).created is True


def test_an_under_sized_pool_still_admits_its_one_legitimate_caller(tmp_path):
    store = ToolCallDatabase(str(tmp_path / "tool-calls.sqlite3"))

    def reserve(user_id: int, reserved_bytes: int):
        return store.reserve(
            tool_call_id=new_tool_call_id(),
            tool_type="inspect",
            runtime_family="fixture",
            runtime_identity="fixture-identity",
            user_id=user_id,
            username=f"user-{user_id}",
            parameter_json="{}",
            input_manifest_json='{"inputs":{}}',
            idempotency_key=None,
            per_user_limit=1,
            global_limit=8,
            reserved_bytes=reserved_bytes,
            storage_max_bytes=150,
        )

    # One call is larger than an equal share of this small pool; it is still
    # admitted on the global bound rather than blocked by its own share.
    assert reserve(1, 150).created is True
    try:
        reserve(2, 10)
    except ToolAdmissionError as exc:
        assert exc.reason == "storage_limit"
    else:
        raise AssertionError("the global Tool storage bound was not enforced")


# ── SEC-AUTHZ-1: guests reach no compute boundary ──────────────────────────────


def test_guest_is_rejected_at_every_compute_boundary(monkeypatch, tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "bioio.sif").write_bytes(b"fixture-sif")
    module = _module(
        monkeypatch, tmp_path, {"ENABLED_TOOL_FAMILIES": "bioio", "TOOL_IMAGE_DIR": str(images)}
    )
    client = module.app.test_client()
    guest = _guest_headers(module)

    submission = client.post(
        "/compute/api/post",
        data={
            "task_type": "gremlin",
            "files": (io.BytesIO(b">guest\nACDE\n"), "guest.fasta"),
            "input_roles": "sequence",
        },
        headers=guest,
    )
    assert submission.status_code == 403
    assert "Guest" in submission.json["error"]

    preflight = client.post(
        "/compute/api/preflight/gremlin",
        data={
            "task_type": "gremlin",
            "files": (io.BytesIO(b">guest\nACDE\n"), "guest.fasta"),
            "input_roles": "sequence",
        },
        headers=guest,
    )
    assert preflight.status_code == 403

    tool_call = client.post(
        "/compute/api/tools/fasta_inspect/call",
        headers=guest,
        data={
            "parameters": "{}",
            "file_roles": "sequence",
            "files": (io.BytesIO(b">guest\nACDE\n"), "guest.fasta"),
        },
    )
    assert tool_call.status_code == 403
    assert "Guest" in tool_call.json["error"]


def test_guest_bearer_is_confined_to_its_own_tasks(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    guest = _guest_headers(module)
    other_header = _test_client_auth(module, "other", "password2")

    md5sum = uuid.uuid4().hex
    result_dir = tmp_path / "guest_task"
    result_dir.mkdir(parents=True, exist_ok=True)
    _upsert_task_for_user(
        module,
        md5sum,
        filename="shared.fasta",
        file_path=result_dir / "shared.fasta",
        result_dir=result_dir,
        username="guest_user",
        status="finished",
    )

    # The guest account still bears a token — ensureToken() needs one — but it
    # must not inherit another tenant's task authority.
    assert client.get(f"/compute/api/running/{md5sum}", headers=guest).status_code == 200
    assert client.get(f"/compute/api/running/{md5sum}", headers=other_header).status_code == 404

    deleted = client.delete(f"/compute/api/delete/{md5sum}", headers=guest)
    assert deleted.status_code == 403
    assert module.task_store.get_task(md5sum)["status"] == "finished"
