# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import time
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml
from sqlalchemy.exc import IntegrityError

from revocompute.access_control import get_policy, load_policies
from revocompute.auth import UserDatabase

ROOT = Path(__file__).resolve().parents[1]


def _write_policy(directory: Path, **updates) -> None:
    policy = {
        "id": "example_academic_runner",
        "label": "Example academic access",
        "description": "Operator approval is required.",
        "requires": ["example_academic"],
        "match": "all",
        "requestable": True,
    }
    policy.update(updates)
    directory.mkdir(exist_ok=True)
    (directory / "example.yaml").write_text(yaml.safe_dump(policy), encoding="utf-8")


def test_policy_loader_accepts_strict_declarative_policy(tmp_path):
    _write_policy(tmp_path, notice={"title": "Restricted", "summary": "Approval required."})
    load_policies(str(tmp_path))
    policy = get_policy("example_academic_runner")
    assert policy.requires == ("example_academic",)
    assert policy.requestable is True


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"requires": ["Unsafe entitlement"]}, "entitlement identifiers"),
        ({"match": "any"}, "match must be 'all'"),
        ({"unexpected": True}, "unknown keys"),
        ({"description": None}, "description must be non-empty text"),
    ],
)
def test_policy_loader_rejects_malformed_policy(tmp_path, updates, message):
    _write_policy(tmp_path, **updates)
    with pytest.raises(ValueError, match=message):
        load_policies(str(tmp_path))


def test_entitlement_and_request_audit_lifecycle(tmp_path):
    db = UserDatabase(str(tmp_path / "users.sqlite3"))
    admin = db.create_user("admin", "admin@example.test", "password", role="admin")
    user = db.create_user("alice", "alice@example.test", "password")

    request = db.create_access_request(user["id"], "example_academic", "Research use")
    with pytest.raises(ValueError, match="already pending"):
        db.create_access_request(user["id"], "example_academic", "Again")
    grant = db.approve_access_request(
        request["id"], reviewed_by=admin["id"], basis="individually_verified", review_note="Checked"
    )
    assert db.has_entitlement(user["id"], "example_academic")
    assert db.get_access_request(request["id"])["status"] == "approved"
    with pytest.raises(ValueError, match="already active"):
        db.grant_entitlement(
            user["id"], "example_academic", granted_by=admin["id"], basis="individually_verified"
        )

    assert db.revoke_entitlement(grant["id"], revoked_by=admin["id"])
    assert not db.has_entitlement(user["id"], "example_academic")
    replacement = db.grant_entitlement(
        user["id"], "example_academic", granted_by=admin["id"], basis="lab_member"
    )
    assert replacement["id"] != grant["id"]
    assert len(db.list_entitlement_grants(user["id"])) == 2

    expired = db.grant_entitlement(
        user["id"],
        "temporary_access",
        granted_by=admin["id"],
        basis="other",
        expires_at=time.time() + 0.01,
    )
    assert db.has_entitlement(user["id"], "temporary_access", now=expired["expires_at"] - 0.001)
    assert not db.has_entitlement(user["id"], "temporary_access", now=expired["expires_at"])
    time.sleep(0.02)
    db.grant_entitlement(user["id"], "temporary_access", granted_by=admin["id"], basis="other")


def test_rejected_request_remains_auditable_and_can_be_resubmitted(tmp_path):
    db = UserDatabase(str(tmp_path / "users.sqlite3"))
    admin = db.create_user("admin", "admin@example.test", "password", role="admin")
    user = db.create_user("alice", "alice@example.test", "password")
    first = db.create_access_request(user["id"], "example_academic", "Initial reason")
    assert db.reject_access_request(first["id"], reviewed_by=admin["id"], review_note="Not yet")
    second = db.create_access_request(user["id"], "example_academic", "New evidence")
    assert second["id"] != first["id"]
    assert db.get_access_request(first["id"])["status"] == "rejected"


def test_failed_approval_leaves_request_pending_and_creates_no_grant(tmp_path):
    db = UserDatabase(str(tmp_path / "users.sqlite3"))
    admin = db.create_user("admin", "admin@example.test", "password", role="admin")
    user = db.create_user("alice", "alice@example.test", "password")
    request = db.create_access_request(user["id"], "example_academic", "Research")
    with pytest.raises(IntegrityError):
        db.approve_access_request(request["id"], reviewed_by=admin["id"], basis="invalid")
    assert db.get_access_request(request["id"])["status"] == "pending"
    assert db.list_entitlement_grants(user["id"]) == []


def test_direct_grant_atomically_approves_matching_pending_request(tmp_path):
    db = UserDatabase(str(tmp_path / "users.sqlite3"))
    admin = db.create_user("admin", "admin@example.test", "password", role="admin")
    user = db.create_user("alice", "alice@example.test", "password")
    request = db.create_access_request(user["id"], "example_academic", "Research")

    grant = db.grant_entitlement(
        user["id"],
        "example_academic",
        granted_by=admin["id"],
        basis="individually_verified",
        note="Verified directly",
    )

    resolved = db.get_access_request(request["id"])
    assert grant["source_request_id"] == request["id"]
    assert resolved["status"] == "approved"
    assert resolved["reviewed_by"] == admin["id"]
    assert resolved["review_note"] == "Verified directly"
    assert db.get_pending_access_requests(user["id"]) == []


def test_multi_entitlement_request_rolls_back_on_insert_failure(tmp_path):
    db = UserDatabase(str(tmp_path / "users.sqlite3"))
    user = db.create_user("alice", "alice@example.test", "password")
    inserts = 0

    def fail_second_request(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal inserts
        if statement.startswith("INSERT INTO access_requests"):
            inserts += 1
            if inserts == 2:
                raise RuntimeError("injected request failure")

    sa.event.listen(db.engine, "before_cursor_execute", fail_second_request)
    try:
        with pytest.raises(RuntimeError, match="injected request failure"):
            db.create_access_requests(user["id"], ("entitlement_a", "entitlement_b"), "Research")
    finally:
        sa.event.remove(db.engine, "before_cursor_execute", fail_second_request)

    assert db.get_pending_access_requests(user["id"]) == []


def test_policy_request_completes_a_partial_pending_set(tmp_path):
    db = UserDatabase(str(tmp_path / "users.sqlite3"))
    user = db.create_user("alice", "alice@example.test", "password")
    first = db.create_access_request(user["id"], "entitlement_a", "Initial request")

    created = db.create_access_requests(user["id"], ("entitlement_a", "entitlement_b"), "Retry")

    assert [request["entitlement"] for request in created] == ["entitlement_b"]
    assert {request["id"] for request in db.get_pending_access_requests(user["id"])} == {
        first["id"],
        created[0]["id"],
    }
