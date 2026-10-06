# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Failure injection for durable-storage ownership and purge.

Storage quota is freed by exactly one event — the moment the owned bytes are
actually gone — so every way of *not* reaching that moment has to free nothing,
and every way of reaching it twice has to free once.  These tests drive the real
ledger and lifecycle rows through partial purges, a crash between the claim and
the destructive work, a repeated reconciliation, and a completed purge that must
release exactly the bytes it charged.
"""

from __future__ import annotations

import pytest

from revocompute import resource_lifecycle
from revocompute.db import TaskDatabase
from revocompute.resource_ledger import DataLifecycleState, ReservationState

GIB = 1024**3


def _remove(_task: dict) -> None:
    """The destructive work succeeds and does nothing."""
    return None


def _charge(database: TaskDatabase, task_id: str, *, user_id: int, owned: int, at: float = 1_000.0) -> None:
    database.ensure_data_lifecycle(task_id, user_id=user_id, logical_bytes=owned, at=at)


def _task(task_id: str, *, user_id: int) -> dict:
    return {"md5sum": task_id, "submitted_by_user_id": user_id}


def _own_task(database: TaskDatabase, task_id: str, *, user_id: int) -> None:
    """A real Task row, so the purge has an owning row to remove artifacts for."""
    database.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/immutable/input.fasta",
        uploaded_at=900.0,
        status="finished",
        is_binary=0,
        username=f"user-{user_id}",
        submitted_by_user_id=user_id,
        storage_key=f"user-{user_id}",
        task_type="gremlin",
    )


def test_logical_ownership_is_charged_once_and_measured_from_the_manifest(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "a" * 32, user_id=11, owned=3 * GIB)

    # A second publication of the same Task (a retry, or a recomputation that
    # re-reads the same manifest) does not double-charge.
    _charge(database, "a" * 32, user_id=11, owned=3 * GIB)

    assert database.logical_owned_bytes(11) == 3 * GIB
    storage = database.storage_entitlement(11)
    assert storage.logical_owned_bytes == 3 * GIB
    assert storage.soft_limit_bytes == database.storage_soft_limit_bytes
    assert storage.over_soft_limit is False


def test_crossing_the_soft_limit_keeps_the_result_and_restricts_admission(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "b" * 32, user_id=12, owned=2 * GIB)

    # The limit is a policy for *later* admission, not a delete trigger: the
    # owned bytes are still charged and the Task's data is intact.
    database._storage_soft_limit = GIB
    try:
        storage = database.storage_entitlement(12)
        assert storage.over_soft_limit is True
        assert storage.remaining_bytes == -GIB
        assert database.logical_owned_bytes(12) == 2 * GIB
        assert database.get_data_lifecycle("b" * 32)["state"] == DataLifecycleState.ACTIVE.value
    finally:
        database._storage_soft_limit = 100 * GIB


def test_partial_purge_frees_nothing(tmp_path):
    """Claiming a purge without completing it is not a release."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "c" * 32, user_id=13, owned=GIB)
    database.claim_data_deletion("c" * 32, user_id=13, actor_user_id=13, at=1_100.0)
    assert database.begin_data_purge("c" * 32, at=1_200.0) is True

    # The row is PURGING; the bytes are still owned and still charged.
    assert database.get_data_lifecycle("c" * 32)["state"] == DataLifecycleState.PURGING.value
    assert database.logical_owned_bytes(13) == GIB


def test_failed_destructive_work_keeps_the_charge_and_the_row_retryable(tmp_path):
    """A crash inside the destructive step must not look like a completed purge."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "d" * 32, user_id=14, owned=GIB)
    resource_lifecycle.request_data_deletion(database, _task("d" * 32, user_id=14), actor_user_id=14, at=1_100.0)

    def _explode(_task: dict) -> None:
        raise OSError("filesystem went away")

    try:
        resource_lifecycle.purge_task_data(
            database, _task("d" * 32, user_id=14), remove_artifacts=_explode, at=1_200.0
        )
    except OSError:
        pass
    else:  # pragma: no cover - the caller's failure contract is the point
        raise AssertionError("a failed purge must propagate to its caller")

    record = database.get_data_lifecycle("d" * 32)
    assert record["state"] == DataLifecycleState.ERROR.value
    assert "filesystem went away" in record["error"]
    assert database.logical_owned_bytes(14) == GIB
    # Nothing was released into the ledger.
    released = [entry for entry in database.list_ledger(14) if entry["reason_code"] == "storage_released"]
    assert released == []


def test_a_failed_purge_is_recovered_on_a_later_pass(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "e" * 32, user_id=15, owned=GIB)
    resource_lifecycle.request_data_deletion(database, _task("e" * 32, user_id=15), actor_user_id=15, at=1_100.0)
    try:
        resource_lifecycle.purge_task_data(
            database,
            _task("e" * 32, user_id=15),
            remove_artifacts=lambda _task: (_ for _ in ()).throw(OSError("transient")),
            at=1_200.0,
        )
    except OSError:
        pass
    assert database.get_data_lifecycle("e" * 32)["state"] == DataLifecycleState.ERROR.value

    recovered = resource_lifecycle.retry_stale_purges(database, remove_artifacts=_remove, now=1_300.0)

    assert recovered == {"recovered": 1}
    assert database.get_data_lifecycle("e" * 32)["state"] == DataLifecycleState.PURGED.value
    assert database.logical_owned_bytes(15) == 0


def test_completed_purge_releases_exactly_the_charged_bytes_once(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "f" * 32, user_id=16, owned=2 * GIB)
    resource_lifecycle.request_data_deletion(database, _task("f" * 32, user_id=16), actor_user_id=16, at=1_100.0)

    assert resource_lifecycle.purge_task_data(
        database, _task("f" * 32, user_id=16), remove_artifacts=_remove, at=1_200.0
    )
    # A repeated completion is a no-op: the state guard admits it once.
    assert database.complete_data_purge("f" * 32, at=1_300.0) is False

    assert database.logical_owned_bytes(16) == 0
    storage_facts = [
        entry for entry in database.list_ledger(16) if entry["reason_code"] in {"storage_charged", "storage_released"}
    ]
    assert sorted(entry["quantity"] for entry in storage_facts) == [-2 * GIB, 2 * GIB]


def test_purge_requested_tasks_purges_each_task_and_survives_one_failure(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    for task_id in ("1" * 32, "2" * 32, "3" * 32):
        _own_task(database, task_id, user_id=17)
        _charge(database, task_id, user_id=17, owned=GIB)
        resource_lifecycle.request_data_deletion(
            database, _task(task_id, user_id=17), actor_user_id=17, at=1_100.0
        )

    def _remove_or_fail(task: dict) -> None:
        if task["md5sum"] == "2" * 32:
            raise OSError("one task's tree is unreadable")

    outcome = resource_lifecycle.purge_requested_tasks(
        database, remove_artifacts=_remove_or_fail, now=1_200.0
    )

    assert outcome == {"purged": 2, "failed": 1}
    assert database.logical_owned_bytes(17) == GIB  # only the failed Task is still charged
    assert database.get_data_lifecycle("2" * 32)["state"] == DataLifecycleState.ERROR.value


def test_reconciliation_is_repeatable_and_double_charges_nothing(tmp_path):
    """Running the whole pass twice must not settle, expire, or release twice."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=10_000)
    database.record_allocation_start(
        user_id=18, task_id="4" * 32, stage_id="model", slurm_job_id="9500", gpu_count=1, started_at=1_000.0
    )
    database.reserve_compute_admission(user_id=18, task_id="5" * 32, at=1_000.0, ttl_seconds=60)
    _charge(database, "6" * 32, user_id=18, owned=GIB)
    resource_lifecycle.request_data_deletion(database, _task("6" * 32, user_id=18), actor_user_id=18, at=1_100.0)

    first = resource_lifecycle.reconcile_resources(database, now=1_200.0)
    second = resource_lifecycle.reconcile_resources(database, now=1_200.0)

    assert first.expired_reservations == 1
    assert second.expired_reservations == 0
    assert database.list_reservations(user_id=18, state=ReservationState.HELD.value) == []
    # The unsettled allocation is untouched by reconciliation: it needs
    # scheduler evidence, which only the worker can supply.
    assert database.compute_entitlement(18, at=1_200.0).used == 0
    assert database.list_unsettled_allocations()


def test_drift_reports_stale_reservations_and_terminal_tasks_with_unsettled_usage(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=10_000)
    database.upsert_task(
        "7" * 32,
        filename="input.fasta",
        file_path="/immutable/input.fasta",
        uploaded_at=900.0,
        status="failed",
        is_binary=0,
        username="tester",
        submitted_by_user_id=19,
        storage_key="tester",
        task_type="gremlin",
    )
    database.record_allocation_start(
        user_id=19,
        task_id="7" * 32,
        stage_id="model",
        slurm_job_id="9600",
        gpu_count=1,
        started_at=1_000.0,
    )
    database.reserve_compute_admission(user_id=19, task_id="8" * 32, at=1_000.0, ttl_seconds=60)

    drift = {item.kind for item in resource_lifecycle.detect_drift(database, now=1_200.0)}

    assert "terminal_task_unsettled_allocation" in drift
    assert "stale_reservation" in drift


def test_drift_reports_a_purged_row_that_still_claims_owned_bytes(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "9" * 32, user_id=20, owned=GIB)
    database.claim_data_deletion("9" * 32, user_id=20, actor_user_id=20, at=1_100.0)
    database.begin_data_purge("9" * 32, at=1_200.0)
    database.complete_data_purge("9" * 32, at=1_300.0)

    # Corrupt the row directly: the append-only ledger cannot be edited, but the
    # lifecycle row is mutable state, and drift detection must not trust it.
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE data_lifecycle SET logical_bytes = 4096 WHERE task_id = ?", ("9" * 32,)
        )

    kinds = {item.kind for item in resource_lifecycle.detect_drift(database, now=1_400.0)}
    assert "purged_with_owned_bytes" in kinds


def test_purge_releases_by_charged_amount_not_by_current_logical_size(tmp_path):
    """A recomputation that finds a smaller result does not change what a purge
    releases — the ledger fact, not the latest directory size, is the truth."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "a0" + "0" * 30, user_id=21, owned=2 * GIB)
    # A later publication reports a different (smaller) logical size.
    database.ensure_data_lifecycle("a0" + "0" * 30, user_id=21, logical_bytes=GIB, at=1_100.0)
    assert database.get_data_lifecycle("a0" + "0" * 30)["accounted_bytes"] == 2 * GIB

    resource_lifecycle.request_data_deletion(
        database, _task("a0" + "0" * 30, user_id=21), actor_user_id=21, at=1_200.0
    )
    resource_lifecycle.purge_task_data(
        database, _task("a0" + "0" * 30, user_id=21), remove_artifacts=_remove, at=1_300.0
    )

    released = [
        entry for entry in database.list_ledger(21) if entry["reason_code"] == "storage_released"
    ]
    assert [entry["quantity"] for entry in released] == [2 * GIB]
    assert database.logical_owned_bytes(21) == 0

def test_a_crashed_purge_reaches_purged_and_releases_the_charged_bytes_once(tmp_path):
    """A worker that dies between its claim and its completion must not wedge.

    The row is durable state, so recovery is re-entering *from* that state.  A
    purge that stops at ``PURGING`` — the crash window the claim exists to make
    resumable — has to reach ``PURGED`` on a later pass and free exactly the
    bytes it charged, once.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _own_task(database, "b1" + "0" * 30, user_id=30)
    _charge(database, "b1" + "0" * 30, user_id=30, owned=GIB)
    resource_lifecycle.request_data_deletion(
        database, _task("b1" + "0" * 30, user_id=30), actor_user_id=30, at=1_100.0
    )
    # The claim is taken and the worker dies: nothing completes it, and no later
    # pass observes a DELETE_REQUESTED row because the state is already PURGING.
    assert database.begin_data_purge("b1" + "0" * 30, at=1_200.0) is True
    assert database.get_data_lifecycle("b1" + "0" * 30)["state"] == DataLifecycleState.PURGING.value
    assert database.logical_owned_bytes(30) == GIB

    # A fresh claim is live, so a pass that runs immediately must not steal it.
    assert resource_lifecycle.retry_stale_purges(
        database, remove_artifacts=_remove, now=1_201.0
    ) == {"recovered": 0}
    assert database.get_data_lifecycle("b1" + "0" * 30)["state"] == DataLifecycleState.PURGING.value

    # Past the staleness bound the crash is recoverable.
    recovered = resource_lifecycle.retry_stale_purges(
        database, remove_artifacts=_remove, now=1_200.0 + resource_lifecycle.PURGE_STALE_SECONDS + 1
    )

    assert recovered == {"recovered": 1}
    assert database.get_data_lifecycle("b1" + "0" * 30)["state"] == DataLifecycleState.PURGED.value
    assert database.logical_owned_bytes(30) == 0
    released = [
        entry for entry in database.list_ledger(30) if entry["reason_code"] == "storage_released"
    ]
    assert [entry["quantity"] for entry in released] == [GIB]

    # And it stays released: repeated passes free nothing more.
    resource_lifecycle.retry_stale_purges(
        database, remove_artifacts=_remove, now=1_200.0 + 3 * resource_lifecycle.PURGE_STALE_SECONDS
    )
    assert database.logical_owned_bytes(30) == 0


def test_a_crashed_purge_with_no_owning_task_row_is_completed(tmp_path):
    """The orphan case: the Task row was hard-removed while its purge was claimed."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "b2" + "0" * 30, user_id=31, owned=GIB)
    database.claim_data_deletion("b2" + "0" * 30, user_id=31, actor_user_id=31, at=1_100.0)
    assert database.begin_data_purge("b2" + "0" * 30, at=1_200.0) is True

    recovered = resource_lifecycle.retry_stale_purges(
        database, remove_artifacts=_remove, now=1_200.0 + resource_lifecycle.PURGE_STALE_SECONDS + 1
    )

    assert recovered == {"recovered": 1}
    assert database.get_data_lifecycle("b2" + "0" * 30)["state"] == DataLifecycleState.PURGED.value
    assert database.logical_owned_bytes(31) == 0


def test_republishing_a_purged_result_charges_the_new_bytes(tmp_path):
    """PURGED is a lifecycle state, not a tombstone.

    Bytes that are back on disk are quota the user holds again.  Leaving the row
    PURGED after a republication reports zero owned bytes for a real result —
    phantom free storage — so the republication re-opens the charge under a new
    revision and the purge's release stays a fact of history.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "b3" + "0" * 30
    _charge(database, task_id, user_id=32, owned=GIB)
    resource_lifecycle.request_data_deletion(database, _task(task_id, user_id=32), actor_user_id=32, at=1_100.0)
    resource_lifecycle.purge_task_data(
        database, _task(task_id, user_id=32), remove_artifacts=_remove, at=1_200.0
    )
    assert database.logical_owned_bytes(32) == 0

    database.ensure_data_lifecycle(task_id, user_id=32, logical_bytes=2 * GIB, at=1_300.0)
    record = database.get_data_lifecycle(task_id)

    assert record["state"] == DataLifecycleState.ACTIVE.value
    assert record["logical_bytes"] == 2 * GIB
    assert database.logical_owned_bytes(32) == 2 * GIB
    facts = sorted(
        entry["quantity"]
        for entry in database.list_ledger(32)
        if entry["reason_code"] in {"storage_charged", "storage_released"}
    )
    # charged, released, charged again — the release was not rewritten.
    assert facts == [-2 * GIB, -GIB, GIB]
    # No drift: the row no longer claims PURGED while owning bytes.
    assert "purged_with_owned_bytes" not in {
        item.kind for item in resource_lifecycle.detect_drift(database, now=1_400.0)
    }

# ---------------------------------------------------------------------------
# Accounting vs. the filesystem
# ---------------------------------------------------------------------------


def test_drift_reports_charged_bytes_that_are_not_on_disk(tmp_path):
    """Accounting says the bytes exist; the filesystem says they do not."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "c1" + "0" * 30, user_id=40, owned=GIB)

    kinds = {
        item.kind
        for item in resource_lifecycle.detect_drift(
            database, now=1_400.0, owned_paths=lambda _task_id: 0
        )
    }

    assert "charged_bytes_missing_on_disk" in kinds


def test_drift_reports_task_data_that_is_not_accounted_for(tmp_path):
    """The mirror case: durable data on disk that nothing charges the subject for."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "c2" + "0" * 30, user_id=41, owned=0)

    kinds = {
        item.kind
        for item in resource_lifecycle.detect_drift(
            database, now=1_400.0, owned_paths=lambda _task_id: 4096
        )
    }

    assert "filesystem_data_not_accounted" in kinds


def test_unmeasurable_storage_is_reported_as_unknown_not_as_zero(tmp_path):
    """A measurement that could not be taken is its own drift, never "no data"."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "c3" + "0" * 30, user_id=42, owned=GIB)

    kinds = {
        item.kind
        for item in resource_lifecycle.detect_drift(
            database, now=1_400.0, owned_paths=lambda _task_id: None
        )
    }

    assert "owned_bytes_unmeasurable" in kinds
    assert "charged_bytes_missing_on_disk" not in kinds


def test_agreeing_accounting_and_filesystem_report_no_storage_drift(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    _charge(database, "c4" + "0" * 30, user_id=43, owned=GIB)

    kinds = {
        item.kind
        for item in resource_lifecycle.detect_drift(
            database, now=1_400.0, owned_paths=lambda _task_id: GIB
        )
    }

    assert kinds & {
        "charged_bytes_missing_on_disk",
        "filesystem_data_not_accounted",
        "owned_bytes_unmeasurable",
    } == set()

# ---------------------------------------------------------------------------
# The lifecycle side of the operational vocabulary
# ---------------------------------------------------------------------------


def test_a_deletion_publishes_its_lifecycle_events(tmp_path, monkeypatch):
    """The canonical event names are the audit trail of an authorized deletion.

    Declaring a vocabulary and never emitting it leaves the lifecycle side of
    "one reason/event scheme" silent, so the transitions that free quota are the
    ones an operator cannot see.
    """
    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        resource_lifecycle,
        "emit_event",
        lambda event, **fields: emitted.append((event, fields)) or fields,
    )
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "d1" + "0" * 30
    _charge(database, task_id, user_id=50, owned=GIB)

    resource_lifecycle.request_data_deletion(
        database, _task(task_id, user_id=50), actor_user_id=50, at=1_100.0
    )
    resource_lifecycle.purge_task_data(
        database, _task(task_id, user_id=50), remove_artifacts=_remove, at=1_200.0
    )

    names = [event for event, _ in emitted]
    assert names == [
        "resource.lifecycle.requested",
        "resource.lifecycle.purged",
        "resource.storage.released",
    ]
    released = dict(emitted)["resource.storage.released"]
    # The event reports what this purge released, read before completion zeroed
    # it — not the row's end state.
    assert released["storage_bytes"] == GIB
    assert released["task_id"] == task_id
    assert released["user_id"] == 50


def test_a_failed_purge_publishes_a_bounded_error_event(tmp_path, monkeypatch):
    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        resource_lifecycle,
        "emit_event",
        lambda event, **fields: emitted.append((event, fields)) or fields,
    )
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "d2" + "0" * 30
    _charge(database, task_id, user_id=51, owned=GIB)
    resource_lifecycle.request_data_deletion(
        database, _task(task_id, user_id=51), actor_user_id=51, at=1_100.0
    )

    with pytest.raises(OSError):
        resource_lifecycle.purge_task_data(
            database,
            _task(task_id, user_id=51),
            remove_artifacts=lambda _task: (_ for _ in ()).throw(OSError("gone")),
            at=1_200.0,
        )

    assert [event for event, _ in emitted] == [
        "resource.lifecycle.requested",
        "resource.lifecycle.error",
    ]


def test_reconciliation_publishes_its_completed_event(tmp_path, monkeypatch):
    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        resource_lifecycle,
        "emit_event",
        lambda event, **fields: emitted.append((event, fields)) or fields,
    )
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=10_000)

    resource_lifecycle.reconcile_resources(database, now=1_200.0)

    assert [event for event, _ in emitted] == ["resource.reconciliation.completed"]
    assert emitted[0][1]["expired_reservations"] == 0
