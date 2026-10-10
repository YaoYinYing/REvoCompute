# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The per-user durable-storage quota policy, and the ceiling admission applies.

Storage *accounting* (#59/#66) already answers "how many bytes does this subject
own?"; this file covers the *policy* layered on top of it: which of the three
distinguishable decisions is in force, how each one is encoded in SQLite, and
that whatever the decision is, changing it never rewrites an accounting fact.

The cases run the real production paths — a real :class:`TaskDatabase` on a
tmp-path SQLite file, and the real submission/HTTP refusals through the
conftest application helpers — so what is asserted is the behaviour a deployment
has, not a re-implementation of it.
"""

from __future__ import annotations

import io

import pytest
from conftest import _extract_md5, _load_pssm_module, _test_client_auth
from revocompute.db import DEFAULT_STORAGE_SOFT_LIMIT_BYTES, TaskDatabase
from revocompute.resource_policy import ResourceValidationError
from revocompute.storage_quota import (
    OPERATION_CLEAR_STORAGE_QUOTA,
    OPERATION_SET_STORAGE_QUOTA,
    STORAGE_QUOTA_UNIT,
    STORAGE_QUOTA_UNLIMITED_SENTINEL,
    StorageQuotaPolicy,
    StorageQuotaState,
    parse_quota_input,
)
from sqlalchemy import select

GIB = 1024**3
MB = 1024**2


def _database(tmp_path, **kwargs) -> TaskDatabase:
    return TaskDatabase(str(tmp_path / "tasks.sqlite3"), **kwargs)


def _set(database: TaskDatabase, user_id: int, state: str, limit_bytes=None, **overrides) -> dict:
    """One admin quota change with the defaults the contract requires.

    The default client key is distinct per (user, state, limit), so a test that
    changes one subject's policy twice says so by passing its own key.
    """
    payload = {
        "user_id": user_id,
        "state": state,
        "limit_bytes": limit_bytes,
        "actor_user_id": 3,
        "reason": "quota change under test",
        "idempotency_key": f"key-{user_id}-{state}-{limit_bytes}",
    }
    payload.update(overrides)
    return database.set_storage_quota(**payload)


def _stored_allowances(database: TaskDatabase) -> dict[int, int]:
    """The raw ``resource_policies`` rows this module owns, keyed by subject."""
    with database.engine.connect() as conn:
        rows = conn.execute(
            select(database.resource_policies_table).where(
                database.resource_policies_table.c.unit == STORAGE_QUOTA_UNIT
            )
        ).mappings().all()
    return {int(row["subject_id"]): int(row["allowance"]) for row in rows}


def _submit(module, client, headers, *, data: bytes = b">test\nACDE\n", task_type: str = "cpu_runner"):
    """POST one minimal submission through the real route."""
    return client.post(
        "/compute/api/post",
        data={
            "task_type": task_type,
            "file": (io.BytesIO(data), "upload.fasta"),
            "input_roles": "sequence",
        },
        headers=headers,
    )


# ---------------------------------------------------------------------------
# The three states, and the one encoding that keeps them apart
# ---------------------------------------------------------------------------


def test_absent_row_limited_and_unlimited_round_trip_through_sqlite(tmp_path):
    """All three decisions survive storage without any two of them colliding.

    The distinction the schema has to preserve is absent-row versus ``LIMITED``
    versus ``UNLIMITED``; it is preserved by mapping them onto *different* stored
    values: no row, a non-negative ``allowance``, and the reserved sentinel — so a
    stored ``0`` still reads back as a limit of zero bytes rather than as "no
    ceiling".
    """
    database = _database(tmp_path)

    # Absent row: the subject inherits the deployment default.
    assert database.storage_quota_policy(41).state is StorageQuotaState.INHERIT
    _set(database, 41, "limited", 0)
    _set(database, 42, "unlimited")
    _set(database, 43, "limited", 2 * GIB)

    # The stored bytes are exactly the encoding the module documents, and they
    # survive a close and reopen of the same file.
    assert _stored_allowances(database) == {41: 0, 42: STORAGE_QUOTA_UNLIMITED_SENTINEL, 43: 2 * GIB}
    database.engine.dispose()
    reopened = _database(tmp_path)

    assert reopened.storage_quota_policy(41) == StorageQuotaPolicy(StorageQuotaState.LIMITED, 0)
    assert reopened.storage_quota_policy(42).state is StorageQuotaState.UNLIMITED
    assert reopened.storage_quota_policy(42).limit_bytes is None
    assert reopened.storage_quota_policy(43) == StorageQuotaPolicy(StorageQuotaState.LIMITED, 2 * GIB)
    assert reopened.storage_quota_policy(44).state is StorageQuotaState.INHERIT
    assert _stored_allowances(reopened) == {41: 0, 42: STORAGE_QUOTA_UNLIMITED_SENTINEL, 43: 2 * GIB}


def test_clearing_a_quota_removes_the_row_and_restores_the_deployment_default(tmp_path):
    """Clearing and unlimited are different decisions with different outcomes."""
    database = _database(tmp_path)

    _set(database, 51, "unlimited")
    assert database.effective_storage_limit_bytes(51) is None
    cleared = _set(database, 51, "inherit", None, idempotency_key="clear-51")

    assert database.storage_quota_policy(51).state is StorageQuotaState.INHERIT
    assert database.effective_storage_limit_bytes(51) == DEFAULT_STORAGE_SOFT_LIMIT_BYTES
    assert _stored_allowances(database) == {}
    assert cleared["operation"] == OPERATION_CLEAR_STORAGE_QUOTA
    assert _set(database, 52, "limited", MB)["operation"] == OPERATION_SET_STORAGE_QUOTA


def test_effective_limit_for_each_state_including_the_inherited_default(tmp_path):
    database = _database(tmp_path)
    _set(database, 61, "limited", 5 * GIB)
    _set(database, 62, "unlimited")

    assert database.effective_storage_limit_bytes(60) == 100 * GIB
    assert database.effective_storage_limit_bytes(61) == 5 * GIB
    assert database.effective_storage_limit_bytes(62) is None


def test_every_state_carries_its_effective_limit_on_the_resource_envelope(tmp_path):
    """Admission reads one envelope, so the ceiling it sees is the effective one."""
    database = _database(tmp_path)
    _set(database, 71, "limited", 7 * GIB)
    _set(database, 72, "unlimited")

    assert database.resource_envelope(70).storage.soft_limit_bytes == 100 * GIB
    assert database.resource_envelope(71).storage.soft_limit_bytes == 7 * GIB
    assert database.resource_envelope(72).storage.soft_limit_bytes is None
    # No second spelling of the same fact appears in the projection.
    assert database.resource_envelope(71).storage.to_dict()["soft_limit_bytes"] == 7 * GIB
    assert "quota" not in database.resource_envelope(71).storage.to_dict()


def test_a_deployment_without_a_default_leaves_inheriting_subjects_uncapped(tmp_path):
    """``INHERIT`` resolves through the deployment default, ``None`` included."""
    database = _database(tmp_path, storage_soft_limit_bytes=0)
    _set(database, 81, "limited", 3 * GIB)

    assert database.effective_storage_limit_bytes(80) is None
    assert database.effective_storage_limit_bytes(81) == 3 * GIB


# ---------------------------------------------------------------------------
# Admin input validation
# ---------------------------------------------------------------------------


def test_parse_quota_input_accepts_only_the_three_documented_requests():
    assert parse_quota_input("inherit", None).state is StorageQuotaState.INHERIT
    assert parse_quota_input("UNLIMITED", None).state is StorageQuotaState.UNLIMITED
    assert parse_quota_input(" limited ", 0) == StorageQuotaPolicy(StorageQuotaState.LIMITED, 0)
    assert parse_quota_input(StorageQuotaState.LIMITED, 12) == StorageQuotaPolicy(
        StorageQuotaState.LIMITED, 12
    )


@pytest.mark.parametrize(
    ("state", "limit_bytes"),
    [
        ("limited", None),
        ("limited", -1),
        ("limited", "1024"),
        ("limited", True),
        ("limited", 1.5),
        ("unlimited", 0),
        ("inherit", 0),
        ("unlimited", -1),
        ("inherit", 1),
        ("bogus", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_quota_input_rejects_ambiguous_or_unknown_requests(state, limit_bytes):
    """A request that does not name exactly one decision is refused, not guessed."""
    with pytest.raises(ResourceValidationError) as error:
        parse_quota_input(state, limit_bytes)
    assert len(str(error.value)) < 200


def test_no_state_spells_unlimited_as_zero(tmp_path):
    """``0`` is a ceiling of zero bytes; there is no way to spell "no ceiling" as it."""
    database = _database(tmp_path)
    _set(database, 91, "limited", 0)
    _set(database, 92, "unlimited")
    database.ensure_data_lifecycle("e" * 32, user_id=91, logical_bytes=1)
    database.ensure_data_lifecycle("f" * 32, user_id=92, logical_bytes=1)

    assert database.effective_storage_limit_bytes(91) == 0
    assert database.effective_storage_limit_bytes(92) is None
    # One owned byte is refused at a ceiling of zero and permitted under no
    # ceiling at all, which is exactly the distinction ``0`` must not lose.
    assert database.storage_entitlement(91).over_soft_limit is True
    assert database.storage_entitlement(92).over_soft_limit is False


def test_set_storage_quota_refuses_an_unknown_state_with_a_bounded_message(tmp_path):
    database = _database(tmp_path)
    with pytest.raises(ResourceValidationError) as error:
        _set(database, 95, "x" * 5000)
    assert len(str(error.value)) < 200
    assert _stored_allowances(database) == {}
    assert database.list_storage_quota_audit(95) == []


def test_set_storage_quota_requires_a_bounded_reason(tmp_path):
    database = _database(tmp_path)
    for reason in ("", "   ", "r" * 1001):
        with pytest.raises(ValueError):
            _set(database, 96, "limited", MB, reason=reason)


# ---------------------------------------------------------------------------
# A policy change is not an accounting event
# ---------------------------------------------------------------------------


def test_setting_a_quota_never_touches_ownership_or_the_ledger(tmp_path):
    """A quota change is a policy fact: the accounting ledger is byte-identical after it."""
    database = _database(tmp_path)
    database.upsert_task(
        "a" * 32,
        filename="input.fasta",
        file_path="/immutable/input.fasta",
        uploaded_at=900.0,
        status="finished",
        is_binary=0,
        username="quota-owner",
        submitted_by_user_id=101,
        storage_key="quota-owner",
        task_type="cpu_runner",
    )
    database.ensure_data_lifecycle("a" * 32, user_id=101, logical_bytes=3 * GIB)
    owned_before = database.logical_owned_bytes(101)
    ledger_before = database.list_ledger(101, limit=200)
    lifecycle_before = database.get_data_lifecycle("a" * 32)

    _set(database, 101, "limited", MB)
    _set(database, 101, "unlimited", None, idempotency_key="unlimited-101")
    _set(database, 101, "limited", 0, idempotency_key="zero-101")
    _set(database, 101, "inherit", None, idempotency_key="clear-101")

    # Four policy changes, three of which move the current value, and the
    # ownership fact is still exactly the one original charge.
    assert owned_before == 3 * GIB
    assert database.logical_owned_bytes(101) == owned_before
    assert database.list_ledger(101, limit=200) == ledger_before
    assert [row["quantity"] for row in ledger_before] == [-3 * GIB]
    assert database.get_data_lifecycle("a" * 32) == lifecycle_before
    assert database.storage_entitlement(101).logical_owned_bytes == owned_before
    assert database.storage_quota_policy(101).state is StorageQuotaState.INHERIT
    assert len(database.list_storage_quota_audit(101)) == 4


def test_a_quota_change_is_recorded_once_per_mutation_with_its_before_and_after(tmp_path):
    database = _database(tmp_path)
    _set(database, 111, "limited", 4 * GIB, updated_at=1_000.0)
    _set(database, 111, "limited", 8 * GIB, idempotency_key="second", updated_at=2_000.0)

    audit = database.list_storage_quota_audit(111)

    # Exactly one audit row per mutation, newest first, each with its actor,
    # target, before, after, reason, and timestamp.
    assert len(audit) == 2
    assert [row["operation"] for row in audit] == [
        OPERATION_SET_STORAGE_QUOTA,
        OPERATION_SET_STORAGE_QUOTA,
    ]
    assert [row["unit"] for row in audit] == [STORAGE_QUOTA_UNIT] * 2
    assert [row["subject_id"] for row in audit] == [111, 111]
    assert [row["actor_user_id"] for row in audit] == [3, 3]
    assert [row["created_at"] for row in audit] == [2_000.0, 1_000.0]
    assert audit[0]["before_json"] == '{"limit_bytes": 4294967296, "state": "limited"}'
    assert audit[0]["after_json"] == '{"limit_bytes": 8589934592, "state": "limited"}'
    assert audit[1]["before_json"] == '{"limit_bytes": null, "state": "inherit"}'
    assert all(row["reason"] == "quota change under test" for row in audit)
    assert all(row["idempotency_key"].startswith("policy_audit:storage_quota:") for row in audit)

    # A compute-allowance change is a different policy and never appears here.
    database.set_compute_allowance(
        user_id=111, monthly_gpu_seconds=12_000, actor_user_id=3, idempotency_key="gpu-111"
    )
    assert len(database.list_storage_quota_audit(111)) == 2
    assert len(database.list_policy_audit(111)) == 3


def test_an_identical_retry_returns_the_prior_row_and_appends_nothing(tmp_path):
    database = _database(tmp_path)
    first = _set(database, 121, "limited", GIB, updated_at=1_000.0)
    retry = _set(database, 121, "limited", GIB, updated_at=5_000.0)

    assert retry == first
    assert len(database.list_storage_quota_audit(121)) == 1
    assert database.effective_storage_limit_bytes(121) == GIB


def test_a_reused_idempotency_key_with_different_content_is_refused(tmp_path):
    database = _database(tmp_path)
    _set(database, 131, "limited", GIB, idempotency_key="shared")

    with pytest.raises(ValueError, match="different storage quota"):
        _set(database, 131, "limited", 2 * GIB, idempotency_key="shared")
    with pytest.raises(ValueError, match="different storage quota"):
        _set(database, 131, "limited", GIB, actor_user_id=9, idempotency_key="shared")
    with pytest.raises(ValueError, match="different storage quota"):
        _set(database, 131, "limited", GIB, reason="another reason", idempotency_key="shared")

    # The refused requests changed nothing at all.
    assert database.effective_storage_limit_bytes(131) == GIB
    assert len(database.list_storage_quota_audit(131)) == 1
    # The same client key for a different user is a different request.
    _set(database, 132, "limited", GIB, idempotency_key="shared")
    assert database.effective_storage_limit_bytes(132) == GIB


# ---------------------------------------------------------------------------
# Admission consumes the effective limit
# ---------------------------------------------------------------------------


def test_a_limited_subject_is_refused_a_new_submission_while_its_result_survives(
    monkeypatch, tmp_path
):
    """The ceiling gates later admission; it never retroactively invalidates a result."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "cpu_runner"},
    )
    client = module.app.test_client()
    headers = _test_client_auth(module)
    user = module.app.config["user_db"].get_user_by_username("tester")
    user_id = int(user["id"])

    class _DummyAsyncResult:
        id = "celery-test-id"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *a, **kw: _DummyAsyncResult())
    accepted = _submit(module, client, headers)
    assert accepted.status_code == 302
    task_id = _extract_md5(accepted.headers["Location"])

    # A finished Task's durable result is charged, and the new per-user ceiling
    # is below it: the result keeps its bytes and its ACTIVE lifecycle state.
    module.task_store.ensure_data_lifecycle(task_id, user_id=user_id, logical_bytes=64)
    module.task_store.set_storage_quota(
        user_id=user_id,
        state="limited",
        limit_bytes=8,
        actor_user_id=user_id,
        reason="tighten below what is owned",
        idempotency_key="admission-limit",
    )
    assert module.task_store.logical_owned_bytes(user_id) == 64
    assert module.task_store.get_data_lifecycle(task_id)["state"] == "ACTIVE"

    refused = _submit(module, client, headers, data=b">refused\nACDEFGHIKLMNPQRSTVWY\n")

    assert refused.status_code == 403
    assert refused.get_json()["details"][0]["code"] == "storage_soft_limit_exceeded"
    # The overrun is unchanged: admission is not an accounting event.
    assert module.task_store.logical_owned_bytes(user_id) == 64


def test_unlimited_admits_what_the_deployment_default_would_have_refused(monkeypatch, tmp_path):
    """``UNLIMITED`` removes the refusal rather than raising the number."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "cpu_runner"},
    )
    client = module.app.test_client()
    headers = _test_client_auth(module)
    user_id = int(module.app.config["user_db"].get_user_by_username("tester")["id"])

    class _DummyAsyncResult:
        id = "celery-test-id"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *a, **kw: _DummyAsyncResult())
    module.task_store.ensure_data_lifecycle(
        "d" * 32, user_id=user_id, logical_bytes=module.task_store.storage_soft_limit_bytes + 1
    )

    assert _submit(module, client, headers).status_code == 403
    module.task_store.set_storage_quota(
        user_id=user_id,
        state="unlimited",
        limit_bytes=None,
        actor_user_id=user_id,
        reason="operator granted unlimited retention",
        idempotency_key="admission-unlimited",
    )
    assert _submit(module, client, headers, data=b">free\nACDEFGHIKLMNPQRSTVWY\n").status_code == 302

    # ...and a limit of zero is not a way to spell the same thing.
    module.task_store.set_storage_quota(
        user_id=user_id,
        state="limited",
        limit_bytes=0,
        actor_user_id=user_id,
        reason="operator revoked retention",
        idempotency_key="admission-zero",
    )
    zero = _submit(module, client, headers, data=b">zero\nACDEFGHIKLMNPQRSTVWYK\n")
    assert zero.status_code == 403
    assert zero.get_json()["details"][0]["code"] == "storage_soft_limit_exceeded"


def test_an_effective_limit_reaches_admission_through_the_api_envelope(monkeypatch, tmp_path):
    """The ceiling a client is told about is the one admission acts on."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    headers = _test_client_auth(module)
    user_id = int(module.app.config["user_db"].get_user_by_username("tester")["id"])

    module.task_store.set_storage_quota(
        user_id=user_id,
        state="limited",
        limit_bytes=9 * GIB,
        actor_user_id=user_id,
        reason="envelope under test",
        idempotency_key="envelope-limit",
    )
    payload = client.get("/compute/api/resource-entitlement", headers=headers).get_json()

    assert payload["storage"]["soft_limit_bytes"] == 9 * GIB
    assert payload["storage"]["remaining_bytes"] == 9 * GIB
    assert module.task_store.storage_soft_limit_bytes == DEFAULT_STORAGE_SOFT_LIMIT_BYTES
