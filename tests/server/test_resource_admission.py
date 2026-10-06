# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Failure-injection and concurrency coverage for compute admission.

Admission is the one place where a mistake hands out scarce resource for free.
Every case here is a way that has historically gone wrong — a race on the final
entitlement, a submission that dies between its hold and its allocation, an
allocation whose authoritative elapsed time never arrives — and the property
under test is the same each time: the recorded usage is a fact, the hold is a
claim that can be released exactly once, and a measurement that is unknown is
never treated as zero.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from revocompute.db import TaskDatabase
from revocompute.resource_ledger import (
    AdmissionReason,
    AllocationStatus,
    LedgerReason,
    ReservationReason,
    ReservationState,
)


def _timestamp(year: int, month: int, day: int = 1, second: int = 0) -> float:
    return datetime(year, month, day, 0, 0, second, tzinfo=timezone.utc).timestamp()


def _start(
    database: TaskDatabase,
    user_id: int,
    *,
    job_id: str,
    at: float,
    gpus: int = 1,
    task_id: str | None = None,
    gres: str = "",
) -> None:
    database.record_allocation_start(
        user_id=user_id,
        task_id=task_id or f"{user_id:032d}",
        stage_id="model",
        slurm_job_id=job_id,
        gpu_count=gpus,
        started_at=at,
        gres=gres,
    )


def _reserve(database: TaskDatabase, user_id: int, *, task_id: str, at: float, **kwargs):
    return database.reserve_compute_admission(user_id=user_id, task_id=task_id, at=at, **kwargs)


# ---------------------------------------------------------------------------
# "Unknown is not zero" — through the admission path, not only the projection
# ---------------------------------------------------------------------------


def test_running_allocation_with_unknown_elapsed_time_blocks_admission(tmp_path):
    """A user whose running allocation has no authoritative end time yet is not
    admitted as if that allocation had consumed nothing.

    The allocation has definitely consumed *something* — it is running — so the
    balance available to a new submission is reduced by a conservative reserve
    before the hold is taken.  Reading the same position without that reserve
    would report a positive remaining balance and admit the submission.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=3_000)
    at = _timestamp(2026, 9, 5)
    _start(database, 81, job_id="9001", at=at)

    entitlement = database.compute_entitlement(81, at=at)
    assert entitlement.used == 0
    assert entitlement.unsettled == 1
    assert entitlement.unsettled_quantity > 0
    assert entitlement.usage_complete is False
    # The settle-only arithmetic would say 3_000; the admission balance says the
    # running allocation has already claimed its share.
    assert entitlement.remaining == 3_000 - entitlement.unsettled_quantity
    assert entitlement.remaining < 3_000

    decision = _reserve(database, 81, task_id="a" * 32, at=at)
    assert decision["allowed"] is False
    assert decision["reason_code"] == AdmissionReason.COMPUTE_EXHAUSTED.value
    assert decision["unsettled"] == entitlement.unsettled_quantity
    assert decision["remaining"] < 0
    assert database.list_reservations(user_id=81, state=ReservationState.HELD.value) == []


def test_unknown_elapsed_allocation_narrows_but_does_not_invent_a_hold(tmp_path):
    """An unsettled allocation reserves a bounded amount: it constrains the next
    submission without consuming the whole allowance on its own."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=10_000)
    at = _timestamp(2026, 9, 5)
    _start(database, 82, job_id="9002", at=at)

    decision = _reserve(database, 82, task_id="b" * 32, at=at)
    assert decision["allowed"] is True
    assert decision["unsettled"] > 0
    assert decision["quantity"] > 0
    # The held quantity is drawn from the balance that remains after the
    # unsettled reserve, so the two together never exceed the allowance.
    assert decision["quantity"] + decision["unsettled"] <= 10_000
    assert decision["remaining"] == 10_000 - decision["unsettled"] - decision["quantity"]


def test_settling_unknown_usage_restores_the_exact_balance(tmp_path):
    """Once the authoritative elapsed time arrives the reserve is replaced by
    the measured fact, and the balance is computed from one number again."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=10_000)
    at = _timestamp(2026, 9, 5)
    _start(database, 83, job_id="9003", at=at)

    assert database.compute_entitlement(83, at=at).usage_complete is False
    database.settle_allocation("9003", finished_at=at + 600)

    entitlement = database.compute_entitlement(83, at=at + 600)
    assert entitlement.used == 600
    assert entitlement.unsettled == 0
    assert entitlement.unsettled_quantity == 0
    assert entitlement.remaining == 9_400
    assert entitlement.usage_complete is True


def test_allocation_without_slurm_accounting_is_never_charged_zero(tmp_path, monkeypatch):
    """When the scheduler cannot answer, the allocation stays unsettled and the
    reason it is unknown is recorded — never a fabricated zero charge."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=10_000)
    at = _timestamp(2026, 9, 5)
    _start(database, 84, job_id="9004", at=at)

    assert database.mark_allocation_for_review("9004") is True
    allocation = database.list_unsettled_allocations()[0]
    assert allocation["status"] == AllocationStatus.REVIEW.value
    assert allocation["quantity"] is None
    assert allocation["evidence_source"] == "allocation_lifecycle"

    # A reviewed allocation is still unsettled, so it still constrains admission.
    entitlement = database.compute_entitlement(84, at=at)
    assert entitlement.unsettled == 1
    assert entitlement.unsettled_quantity > 0
    assert database.compute_entitlement(84, at=at).used == 0


# ---------------------------------------------------------------------------
# Races on the final entitlement
# ---------------------------------------------------------------------------


def test_concurrent_admissions_cannot_oversubscribe_the_final_entitlement(tmp_path):
    """Two submissions racing for the last of the entitlement: exactly one wins.

    The decision and the hold are one transaction, so the loser observes the
    winner's hold instead of both being dispatched against the same balance.
    """
    path = str(tmp_path / "tasks.sqlite3")
    at = _timestamp(2026, 9, 6)
    seed = TaskDatabase(path, monthly_gpu_seconds=100)
    seed.compute_entitlement(85, at=at)  # materialize the period grant
    seed.engine.dispose()

    databases = [TaskDatabase(path), TaskDatabase(path)]
    barrier = threading.Barrier(2)
    results: list[dict] = []
    errors: list[Exception] = []

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            results.append(
                databases[index].reserve_compute_admission(
                    user_id=85, task_id=f"{index}" * 32, at=at
                )
            )
        except Exception as exc:  # pragma: no cover - surfaced via assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    allowed = [item for item in results if item["allowed"]]
    refused = [item for item in results if not item["allowed"]]
    assert len(allowed) == 1
    assert len(refused) == 1
    assert refused[0]["reason_code"] == AdmissionReason.COMPUTE_EXHAUSTED.value
    assert allowed[0]["quantity"] == 100
    # The hold is exactly the entitlement: nothing was handed out twice.
    holds = databases[0].list_reservations(user_id=85, state=ReservationState.HELD.value)
    assert sum(int(hold["quantity"]) for hold in holds) == 100


def test_a_refused_admission_records_no_hold_and_no_charge(tmp_path):
    """A refusal is not an accounting event: no hold, no ledger row, no usage."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=0)
    at = _timestamp(2026, 9, 6)

    decision = _reserve(database, 86, task_id="c" * 32, at=at)

    assert decision["allowed"] is False
    assert decision["reason_code"] == AdmissionReason.COMPUTE_EXHAUSTED.value
    assert decision["reservation_id"] is None
    assert database.list_reservations(user_id=86, state=ReservationState.HELD.value) == []
    assert database.list_compute_ledger(86) == database.list_compute_ledger(86)  # stable
    kinds = {entry["kind"] for entry in database.list_compute_ledger(86)}
    assert "usage" not in kinds
    assert database.compute_entitlement(86, at=at).used == 0


# ---------------------------------------------------------------------------
# A hold's whole lifecycle, including the ways a submission dies
# ---------------------------------------------------------------------------


def test_releasing_a_hold_is_idempotent(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=10_000)
    at = _timestamp(2026, 9, 7)
    decision = _reserve(database, 87, task_id="d" * 32, at=at)
    assert decision["allowed"] is True

    assert database.release_reservation(task_id="d" * 32, reason_code=ReservationReason.DISPATCH_FAILED.value, at=at) is True
    assert database.release_reservation(task_id="d" * 32, reason_code=ReservationReason.DISPATCH_FAILED.value, at=at + 1) is False
    assert database.compute_entitlement(87, at=at).reserved == 0
    assert database.compute_entitlement(87, at=at).remaining == 10_000


def test_allocation_start_consumes_the_hold_without_double_counting(tmp_path):
    """The hold spans submit -> allocation start and is released exactly there;
    the allocation, not the hold, is what the balance is charged for."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=10_000)
    at = _timestamp(2026, 9, 7)
    decision = _reserve(database, 88, task_id="e" * 32, at=at)
    assert decision["allowed"] is True

    _start(database, 88, job_id="9100", at=at + 5, task_id="e" * 32)

    assert database.list_reservations(user_id=88, state=ReservationState.HELD.value) == []
    released = database.list_reservations(user_id=88)[0]
    assert released["state"] == ReservationState.RELEASED.value
    assert released["reason_code"] == ReservationReason.ALLOCATION_STARTED.value
    # The allocation now occupies the balance instead of the hold, once.
    entitlement = database.compute_entitlement(88, at=at + 5)
    assert entitlement.reserved == 0
    assert entitlement.unsettled == 1
    assert entitlement.used == 0


def test_stale_hold_is_expired_exactly_once(tmp_path):
    """A submission that died between holding and starting leaves a hold that
    must not keep entitlement forever — and expiring it twice frees nothing."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=100)
    at = _timestamp(2026, 9, 8)
    decision = _reserve(database, 89, task_id="f" * 32, at=at, ttl_seconds=60)
    assert decision["allowed"] is True
    assert decision["quantity"] == 100

    assert database.expire_stale_reservations(now=at + 30) == 0
    assert database.expire_stale_reservations(now=at + 61) == 1
    assert database.expire_stale_reservations(now=at + 120) == 0
    assert database.compute_entitlement(89, at=at + 120).remaining == 100


def test_settlement_after_a_released_hold_still_charges_the_real_usage(tmp_path):
    """The hold is not the charge: a submission whose hold expired is still
    accounted for the allocation it really ran."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=10_000)
    at = _timestamp(2026, 9, 8)
    _reserve(database, 90, task_id="1" * 32, at=at, ttl_seconds=1)
    assert database.expire_stale_reservations(now=at + 10) == 1

    _start(database, 90, job_id="9200", at=at + 20, task_id="1" * 32)
    database.settle_allocation("9200", finished_at=at + 200)

    entitlement = database.compute_entitlement(90, at=at + 200)
    assert entitlement.used == 180
    assert entitlement.remaining == 9_820
    usage = [entry for entry in database.list_compute_ledger(90) if entry["kind"] == "usage"]
    assert len(usage) == 1
    assert usage[0]["reason_code"] == LedgerReason.ACTUAL_ALLOCATION.value


def test_repeated_settlement_charges_once(tmp_path):
    """A lost response, a retried settlement, or a reconciliation pass all
    observe the same single usage fact."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=10_000)
    at = _timestamp(2026, 9, 9)
    _start(database, 91, job_id="9300", at=at)

    first = database.settle_allocation("9300", finished_at=at + 100)
    second = database.settle_allocation("9300", finished_at=at + 5_000)
    third = database.settle_allocation_elapsed("9300", elapsed_seconds=100, finished_at=at + 100)

    assert second == first
    assert third == first
    usage = [entry for entry in database.list_compute_ledger(91) if entry["kind"] == "usage"]
    assert len(usage) == 1
    assert usage[0]["quantity"] == -100
    assert database.compute_entitlement(91, at=at + 5_000).used == 100


def test_a_policy_change_never_rewrites_recorded_usage(tmp_path):
    """An admin allowance change appends a new fact; the recorded allocation and
    its charge are untouched history."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=10_000)
    at = _timestamp(2026, 9, 9)
    _start(database, 92, job_id="9400", at=at)
    database.settle_allocation("9400", finished_at=at + 400)
    before = [entry for entry in database.list_compute_ledger(92) if entry["kind"] == "usage"]

    database.set_compute_allowance(
        user_id=92, monthly_gpu_seconds=500, actor_user_id=7, idempotency_key="allow-92", updated_at=at + 500
    )

    after = [entry for entry in database.list_compute_ledger(92) if entry["kind"] == "usage"]
    assert after == before
    assert after[0]["quantity"] == -400
    assert database.compute_entitlement(92, at=at + 500).allowance == 500
    assert database.compute_entitlement(92, at=at + 500).remaining == 100


# ---------------------------------------------------------------------------
# The resource class is preserved; the allowance is not per class
# ---------------------------------------------------------------------------


def test_a_named_class_is_recorded_and_admitted_against_the_one_allowance(tmp_path):
    """A GRES class is evidence, not a separate budget.

    A request for ``gpu:a100:2`` is admitted against the deployment's single
    allowance (so the class-agnostic scope is the authority on "may this user
    run?"), and the class is preserved on both the hold and the allocation so a
    historical A100 second is never collapsed into an anonymous one.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=1_000)
    at = _timestamp(2026, 9, 12)

    decision = database.reserve_compute_admission(
        user_id=89, task_id="c" * 32, gres="gpu:a100:2", at=at
    )
    assert decision["allowed"] is True
    assert decision["resource_class"] == "a100"
    hold = database.list_reservations(user_id=89, state=ReservationState.HELD.value)[0]
    assert hold["resource_class"] == "a100"

    _start(database, 89, job_id="9800", at=at, gpus=2, gres="gpu:a100:2", task_id="c" * 32)
    database.settle_allocation_elapsed("9800", elapsed_seconds=100, finished_at=at + 100)

    allocation = database.list_task_allocations("c" * 32)[0]
    assert allocation["resource_class"] == "a100"
    assert allocation["resource_count"] == 2
    assert allocation["quantity"] == 200
    # The class view and the class-agnostic view agree on the same single
    # allowance, so neither can contradict the other's admission answer.
    assert database.compute_entitlement(89, at=at + 100).allowance == 1_000
    assert database.compute_entitlement(89, at=at + 100, gres="gpu:a100:2").allowance == 1_000
    assert database.compute_entitlement(89, at=at + 100).used == 200


def test_typed_gpu_usage_consumes_the_shared_allowance(tmp_path):
    """Usage recorded under one class reduces the balance every class draws on."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=1_000)
    at = _timestamp(2026, 9, 12)
    database.record_allocation_start(
        user_id=90,
        task_id="d" * 32,
        stage_id="model",
        slurm_job_id="9801",
        gpu_count=1,
        started_at=at,
        gres="gpu:a100:1",
    )
    database.settle_allocation_elapsed("9801", elapsed_seconds=600, finished_at=at + 600)

    # An untyped request draws on the same balance the typed usage consumed.
    decision = database.reserve_compute_admission(user_id=90, task_id="e" * 32, at=at + 600)
    assert decision["allowed"] is True
    assert decision["quantity"] == 400
    assert decision["remaining"] == 0
    centralized = database.compute_entitlement(90, at=at + 600)
    assert centralized.used == 600
    assert centralized.remaining == 400 - 400


def test_a_different_class_does_not_open_a_second_budget(tmp_path):
    """Switching accelerator class cannot mint entitlement: the balance is one."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=500)
    at = _timestamp(2026, 9, 12)
    database.record_allocation_start(
        user_id=91,
        task_id="f" * 32,
        stage_id="model",
        slurm_job_id="9802",
        gpu_count=1,
        started_at=at,
        gres="gpu:a100:1",
    )
    database.settle_allocation_elapsed("9802", elapsed_seconds=500, finished_at=at + 500)
    assert database.compute_entitlement(91, at=at + 500).remaining == 0

    decision = database.reserve_compute_admission(
        user_id=91, task_id="a" * 32, gres="gpu:h100:1", at=at + 500
    )
    assert decision["allowed"] is False
    assert decision["reason_code"] == AdmissionReason.COMPUTE_EXHAUSTED.value
