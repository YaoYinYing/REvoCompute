# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Admin HTTP path for the per-user durable-storage quota.

``revocompute.storage_quota`` owns what a quota *is* and how it is encoded, and
``tests/server/test_storage_quota_policy.py`` covers that layer against the real
store.  This file covers the boundary an operator actually touches: the three
authorization states of the route, the bounded refusal of a request that does not
name exactly one decision, and — the property the whole feature rests on — that a
quota change travels the real HTTP path, reaches admission, and leaves every
accounting fact byte-for-byte unchanged.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from revocompute.db import DEFAULT_STORAGE_SOFT_LIMIT_BYTES

GIB = 1024**3
MB = 1024**2


def _module(monkeypatch, tmp_path):
    return _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "cpu_runner"},
    )


def _quota_path(user_id: int) -> str:
    return f"/compute/api/auth/admin/users/{user_id}/storage-quota"


def _change(state: str, *, limit_bytes=None, key: str, reason: str = "operator quota change"):
    body = {"state": state, "reason": reason, "idempotency_key": key}
    if limit_bytes is not None:
        body["limit_bytes"] = limit_bytes
    return body


def test_the_quota_route_requires_an_administrator(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    regular = _test_client_auth(module)
    admin = _admin_client_auth(module)
    target = module.app.config["user_db"].get_user_by_username("tester")["id"]
    path = _quota_path(int(target))

    assert client.get(path).status_code == 401
    assert client.get(path, headers=regular).status_code == 403
    assert client.get(path, headers=admin).status_code == 200
    # A policy change is a state change, so it carries the same non-admin refusal
    # as the read; the administrator's own request is what is accepted.
    assert client.put(path, headers=regular, json=_change("unlimited", key="k1")).status_code == 403
    assert client.put(path, headers=admin, json=_change("unlimited", key="k1")).status_code == 200


def test_the_effective_ceiling_follows_the_stored_policy_through_http(monkeypatch, tmp_path):
    """Set, grant, and remove an override, reading the effect back through the API.

    The response is the effective entitlement admission applies, not an echo of the
    request: ``inherit`` reports the deployment default because that is the ceiling
    in force, and ``unlimited`` reports no ceiling at all rather than a large one.
    """
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin = _admin_client_auth(module)
    subject = _test_client_auth(module)
    target = module.app.config["user_db"].get_user_by_username("tester")["id"]
    path = _quota_path(int(target))

    limited = client.put(path, headers=admin, json=_change("limited", limit_bytes=7 * GIB, key="set-7gib"))
    assert limited.status_code == 200
    payload = limited.get_json()["storage_quota"]
    assert payload["state"] == "limited"
    assert payload["soft_limit_bytes"] == 7 * GIB
    assert payload["remaining_bytes"] == 7 * GIB
    assert payload["over_soft_limit"] is False
    assert client.get(path, headers=admin).get_json()["soft_limit_bytes"] == 7 * GIB

    granted = client.put(path, headers=admin, json=_change("unlimited", key="grant-unlimited"))
    assert granted.status_code == 200
    assert granted.get_json()["storage_quota"]["state"] == "unlimited"
    assert granted.get_json()["storage_quota"]["soft_limit_bytes"] is None
    assert granted.get_json()["storage_quota"]["remaining_bytes"] is None

    cleared = client.put(path, headers=admin, json=_change("inherit", key="clear-override"))
    assert cleared.status_code == 200
    assert cleared.get_json()["storage_quota"]["state"] == "inherit"
    assert cleared.get_json()["storage_quota"]["soft_limit_bytes"] == DEFAULT_STORAGE_SOFT_LIMIT_BYTES

    # The same effective ceiling the operator reads here is the one the subject's
    # own entitlement endpoint reports: one number, two readers.
    subject = _test_client_auth(module)
    envelope = client.get("/compute/api/resource-entitlement", headers=subject).get_json()
    assert envelope["storage"]["soft_limit_bytes"] == DEFAULT_STORAGE_SOFT_LIMIT_BYTES


def test_a_zero_ceiling_is_reported_as_zero_and_never_as_unlimited(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin = _admin_client_auth(module)
    subject = _test_client_auth(module)
    target = int(module.app.config["user_db"].get_user_by_username("tester")["id"])
    path = _quota_path(target)

    zero = client.put(path, headers=admin, json=_change("limited", limit_bytes=0, key="zero-ceiling"))
    assert zero.status_code == 200
    assert zero.get_json()["storage_quota"]["soft_limit_bytes"] == 0
    assert zero.get_json()["storage_quota"]["remaining_bytes"] == 0

    # One owned byte is over a ceiling of zero, and permitted under no ceiling:
    # the two must not read the same.
    module.task_store.ensure_data_lifecycle("e" * 32, user_id=target, logical_bytes=1)
    assert client.get(path, headers=admin).get_json()["over_soft_limit"] is True

    client.put(path, headers=admin, json=_change("unlimited", key="lift-ceiling"))
    assert client.get(path, headers=admin).get_json()["over_soft_limit"] is False


def test_a_request_that_does_not_name_one_decision_is_refused(monkeypatch, tmp_path):
    """Every ambiguous request is a bounded 400, and nothing is written."""
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin = _admin_client_auth(module)
    subject = _test_client_auth(module)
    target = int(module.app.config["user_db"].get_user_by_username("tester")["id"])
    path = _quota_path(target)

    ambiguous = [
        {"state": "limited", "reason": "no number", "idempotency_key": "amb-1"},
        {"state": "unlimited", "limit_bytes": 5, "reason": "number where none belongs", "idempotency_key": "amb-2"},
        {"state": "inherit", "limit_bytes": 0, "reason": "number where none belongs", "idempotency_key": "amb-3"},
        {"state": "forever", "reason": "unknown state", "idempotency_key": "amb-4"},
    ]
    for body in ambiguous:
        response = client.put(path, headers=admin, json=body)
        assert response.status_code == 400, body
        assert response.get_json()["error"]
        assert len(response.get_json()["error"]) < 200

    assert client.get(path, headers=admin).get_json()["state"] == "inherit"
    assert module.task_store.list_storage_quota_audit(target) == []


def test_a_reused_key_for_a_different_change_is_a_conflict(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin = _admin_client_auth(module)
    subject = _test_client_auth(module)
    target = int(module.app.config["user_db"].get_user_by_username("tester")["id"])
    path = _quota_path(target)

    first = client.put(path, headers=admin, json=_change("limited", limit_bytes=GIB, key="shared-key"))
    assert first.status_code == 200
    replay = client.put(path, headers=admin, json=_change("limited", limit_bytes=GIB, key="shared-key"))
    assert replay.status_code == 200
    assert replay.get_json()["entry_id"] == first.get_json()["entry_id"]

    conflicting = client.put(
        path, headers=admin, json=_change("limited", limit_bytes=2 * GIB, key="shared-key")
    )
    assert conflicting.status_code == 409
    assert client.get(path, headers=admin).get_json()["soft_limit_bytes"] == GIB


def test_an_unknown_user_is_not_a_quota_target(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin = _admin_client_auth(module)
    path = _quota_path(987654)

    assert client.get(path, headers=admin).status_code == 404
    assert client.put(path, headers=admin, json=_change("unlimited", key="nowhere")).status_code == 404


def test_the_quota_change_reaches_admission_without_touching_accounting(monkeypatch, tmp_path):
    """The headline property: policy moves, ownership does not.

    A Task's published result is charged, the subject's ceiling is then tightened
    below what they own through the real HTTP route, and a later submission is
    refused — while the owned bytes, the ledger, and the lifecycle row are exactly
    what they were before the policy changed.
    """
    module = _module(monkeypatch, tmp_path)
    monkeypatch.setattr(
        module.run_compute_task,
        "apply_async",
        lambda *args, **kwargs: SimpleNamespace(id="celery-dispatch-id"),
    )
    client = module.app.test_client()
    subject = _test_client_auth(module)
    admin = _admin_client_auth(module)
    target = int(module.app.config["user_db"].get_user_by_username("tester")["id"])

    accepted = client.post(
        "/compute/api/post",
        headers=subject,
        data={
            "task_type": "cpu_runner",
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )
    assert accepted.status_code in {200, 201, 202, 302}, accepted.get_data(as_text=True)

    task_id = module.task_store.list_tasks()[0]["md5sum"]
    module.task_store.ensure_data_lifecycle(task_id, user_id=target, logical_bytes=64 * MB)
    owned_before = module.task_store.logical_owned_bytes(target)
    ledger_before = module.task_store.list_ledger(target, limit=200)
    lifecycle_before = module.task_store.get_data_lifecycle(task_id)

    changed = client.put(
        _quota_path(target),
        headers=admin,
        json=_change("limited", limit_bytes=8, key="tighten", reason="tighten below what is owned"),
    )
    assert changed.status_code == 200
    assert changed.get_json()["storage_quota"]["over_soft_limit"] is True

    refused = client.post(
        "/compute/api/post",
        headers=subject,
        data={
            "task_type": "cpu_runner",
            "files": (io.BytesIO(b">reference\nACDEFGHIKLMNPQRSTVWY\n"), "reference.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )
    assert refused.status_code == 403
    assert refused.get_json()["details"][0]["code"] == "storage_soft_limit_exceeded"

    # Four policy changes and a refusal later, the facts are the original ones.
    assert module.task_store.logical_owned_bytes(target) == owned_before == 64 * MB
    assert module.task_store.list_ledger(target, limit=200) == ledger_before
    assert module.task_store.get_data_lifecycle(task_id) == lifecycle_before
    assert len(module.task_store.list_storage_quota_audit(target)) == 1
