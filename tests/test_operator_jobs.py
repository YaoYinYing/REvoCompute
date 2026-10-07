# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Operator Job lifecycle, leases, idempotency, and restart reconciliation."""

from __future__ import annotations

from pathlib import Path

import pytest
from revocompute.operator_jobs import (
    OperatorConflictError,
    OperatorJobError,
    OperatorJobStatus,
    OperatorJobStore,
)


@pytest.fixture
def store(tmp_path: Path) -> OperatorJobStore:
    return OperatorJobStore(str(tmp_path / "operator.sqlite"))


def _create(
    store,
    *,
    family="demo",
    key=None,
    intent="build",
    actor=1,
    scope=None,
    action="runner.build",
    parameters=None,
    plan_digest="sha256:plan",
    evidence_digest="sha256:evidence",
):
    return store.create(
        action=action,
        runner_family=family,
        actor_user_id=actor,
        actor_username="admin%d" % actor,
        tier="mutate",
        lease_scope=scope or ("runner/" + family),
        requested_intent=intent,
        plan_digest=plan_digest,
        evidence_digest=evidence_digest,
        parameters=parameters if parameters is not None else {"runner_family": family},
        idempotency_key=key,
    )


def test_a_job_starts_queued_and_is_durable(store):
    record, created = _create(store, key="k1")
    assert created is True
    assert record["status"] == OperatorJobStatus.QUEUED.value
    # A fresh store over the same file still reads the record (restart durability).
    reopened = OperatorJobStore(store.path)
    assert reopened.get(record["job_id"])["action"] == record["action"]


def test_idempotent_retry_returns_the_same_job(store):
    first, _ = _create(store, key="same")
    second, created = _create(store, key="same")
    assert created is False
    assert second["job_id"] == first["job_id"]


def test_same_key_different_body_is_rejected(store):
    _create(store, key="k", intent="build")
    with pytest.raises(OperatorJobError, match="Idempotency key reused"):
        _create(store, key="k", intent="validate")


def test_same_key_different_runner_family_is_rejected(store):
    """The key names a request for one Runner, not a blank cheque for any of them."""
    _create(store, key="k", family="one")
    with pytest.raises(OperatorJobError, match="Idempotency key reused"):
        _create(store, key="k", family="two")


def test_same_key_different_parameters_is_rejected(store):
    """A different collection/task is a different request, not a retry."""
    _create(store, key="k", parameters={"runner_family": "demo", "collection": "one"})
    with pytest.raises(OperatorJobError, match="Idempotency key reused"):
        _create(store, key="k", parameters={"runner_family": "demo", "collection": "two"})


def test_same_key_different_action_is_rejected(store):
    _create(store, key="k", action="runner.build", intent="runner.build")
    with pytest.raises(OperatorJobError, match="Idempotency key reused"):
        _create(store, key="k", action="runner.prepare", intent="runner.prepare")


def test_same_key_with_a_changed_plan_or_evidence_identity_is_rejected(store):
    """A replayed key must not authorize a plan computed against other evidence."""
    _create(store, key="k")
    with pytest.raises(OperatorJobError, match="Idempotency key reused"):
        _create(store, key="k", plan_digest="sha256:other-plan")
    with pytest.raises(OperatorJobError, match="Idempotency key reused"):
        _create(store, key="k", evidence_digest="sha256:other-evidence")


def test_a_second_conflicting_mutation_on_one_family_is_rejected(store):
    _create(store, actor=1)
    with pytest.raises(OperatorConflictError):
        _create(store, actor=2)


def test_read_only_scope_does_not_block_and_reads_do_not_lease(store):
    _create(store, actor=1, scope="read-only")
    _create(store, actor=2, scope="read-only")
    assert len(store.list_jobs()) == 2


def test_a_different_family_is_not_blocked(store):
    _create(store, family="one")
    _create(store, family="two")
    assert len(store.list_jobs()) == 2


def test_status_transitions_reject_impossible_regressions(store):
    record, _ = _create(store, key="k")
    job = record["job_id"]
    assert store.transition(job, expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING)
    assert store.transition(job, expected=(OperatorJobStatus.RUNNING,), new_status=OperatorJobStatus.SUCCEEDED)
    # A terminal job cannot return to RUNNING.
    with pytest.raises(OperatorJobError, match="Illegal operator transition"):
        store.transition(job, expected=(OperatorJobStatus.SUCCEEDED,), new_status=OperatorJobStatus.RUNNING)
    # Nor can a move that skips the lifecycle be persisted.
    assert store.transition(job, expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING) is False


def test_compare_and_set_lets_only_one_concurrent_transition_win(store):
    record, _ = _create(store, key="k")
    job = record["job_id"]
    assert store.transition(job, expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING) is True
    assert store.transition(job, expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING) is False


def test_cancelling_only_touches_the_owned_job(store):
    first, _ = _create(store, family="one", key="a")
    second, _ = _create(store, family="two", key="b")
    assert store.request_cancel(first["job_id"]) is True
    assert store.get(first["job_id"])["status"] == OperatorJobStatus.CANCELLED.value
    assert store.get(second["job_id"])["status"] == OperatorJobStatus.QUEUED.value


def test_cancelling_a_running_job_moves_it_to_cancelling(store):
    record, _ = _create(store, key="k")
    job = record["job_id"]
    store.transition(job, expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING)
    assert store.request_cancel(job) is True
    assert store.get(job)["status"] == OperatorJobStatus.CANCELLING.value
    assert store.transition(job, expected=(OperatorJobStatus.CANCELLING,), new_status=OperatorJobStatus.CANCELLED)


def test_a_terminal_write_refused_by_a_cancelling_row_is_converted_not_dropped(store):
    """A completion racing a cancel must not strand the row in CANCELLING.

    The executor's RUNNING -> SUCCEEDED compare-and-swap is refused because a
    concurrent cancel already moved the row to CANCELLING.  The loser observes
    the real status and carries the cancel to its terminal state, releasing the
    exclusive lease exactly once.
    """
    record, _ = _create(store, key="k")
    job = record["job_id"]
    store.transition(job, expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING)
    assert store.request_cancel(job) is True

    # The completion write loses the race and is refused, not silently ignored.
    assert (
        store.transition(job, expected=(OperatorJobStatus.RUNNING,), new_status=OperatorJobStatus.SUCCEEDED)
        is False
    )
    assert store.status_of(job) == OperatorJobStatus.CANCELLING  # never stranded

    assert store.cancel_if_terminal(job) is True
    assert store.get(job)["status"] == OperatorJobStatus.CANCELLED.value
    assert store.active_exclusive("runner/demo") is None  # lease released at the terminal transition


def test_cancel_if_terminal_is_a_no_op_once_the_winner_has_landed(store):
    """The race loser must not write a second terminal state over the winner's."""
    record, _ = _create(store, key="k")
    job = record["job_id"]
    store.transition(job, expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING)
    store.transition(job, expected=(OperatorJobStatus.RUNNING,), new_status=OperatorJobStatus.SUCCEEDED)

    # The row is already terminal, so the losing writer changes nothing.
    assert store.cancel_if_terminal(job) is True
    assert store.get(job)["status"] == OperatorJobStatus.SUCCEEDED.value


def test_a_terminal_job_releases_its_lease(store):
    record, _ = _create(store, key="k")
    job = record["job_id"]
    store.transition(job, expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING)
    store.transition(job, expected=(OperatorJobStatus.RUNNING,), new_status=OperatorJobStatus.FAILED, failure_category="operation_failed")
    assert store.active_exclusive("runner/demo") is None
    _create(store, actor=2, key="k2")


def test_restart_reconciliation_never_auto_retries(store):
    record, _ = _create(store, key="k")
    job = record["job_id"]
    store.transition(job, expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING)

    reconciled = store.reconcile_orphans()

    assert reconciled == [job]
    row = store.get(job)
    assert row["status"] == OperatorJobStatus.FAILED.value
    assert row["failure_category"] == "orphaned_executor_restart"
    # The lease is free, but nothing was re-executed.
    assert store.active_exclusive("runner/demo") is None


def test_history_survives_a_restart(store):
    record, _ = _create(store, key="k")
    store.transition(record["job_id"], expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING)
    store.transition(
        record["job_id"],
        expected=(OperatorJobStatus.RUNNING,),
        new_status=OperatorJobStatus.SUCCEEDED,
        result={"status": "READY"},
        effect={"requested_intent": "build", "effective_actions": ["build", "live_test"]},
    )
    reopened = OperatorJobStore(store.path)
    row = reopened.get(record["job_id"])
    assert row["status"] == OperatorJobStatus.SUCCEEDED.value
    assert "effective_actions" in row["effect_json"]


def test_queue_limit_bounds_job_creation(store):
    store.create(
        action="runner.status",
        runner_family="a",
        actor_user_id=1,
        actor_username="admin1",
        tier="read",
        lease_scope="read-only",
        requested_intent="status",
        plan_digest="sha256:plan",
        evidence_digest="sha256:evidence",
        parameters={"runner_family": "a"},
        idempotency_key=None,
        queue_limit=1,
    )
    with pytest.raises(OperatorJobError, match="queue is full"):
        store.create(
            action="runner.status",
            runner_family="b",
            actor_user_id=1,
            actor_username="admin1",
            tier="read",
            lease_scope="read-only",
            requested_intent="status",
            plan_digest="sha256:plan",
            evidence_digest="sha256:evidence",
            parameters={"runner_family": "b"},
            idempotency_key=None,
            queue_limit=1,
        )


def test_failure_category_is_a_closed_set(store):
    record, _ = _create(store, key="k")
    store.transition(record["job_id"], expected=(OperatorJobStatus.QUEUED,), new_status=OperatorJobStatus.RUNNING)
    with pytest.raises(OperatorJobError, match="Unknown failure category"):
        store.transition(
            record["job_id"],
            expected=(OperatorJobStatus.RUNNING,),
            new_status=OperatorJobStatus.FAILED,
            failure_category="totally_made_up",
        )
