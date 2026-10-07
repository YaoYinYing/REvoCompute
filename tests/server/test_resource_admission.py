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

from revocompute.db import GPUCreditUnavailableError, TaskDatabase
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
        cpu_cores=1,
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
    # Admission has exactly one authoritative scope, and it is class-agnostic:
    # there is no per-class balance that could answer "may this user run?" with
    # a different verdict.  Per-class detail is a *report* of the same ledger.
    entitlement = database.compute_entitlement(89, at=at + 100)
    assert entitlement.allowance == 1_000
    assert entitlement.used == 200
    assert entitlement.resource_class == ""
    assert entitlement.remaining == 800
    assert database.class_usage(89, gres="gpu:a100:2", period="2026-09") == 200
    assert database.class_usage(89, gres="gpu:h100:1", period="2026-09") == 0


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
        cpu_cores=1,
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
        cpu_cores=1,
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

def test_a_task_that_already_holds_entitlement_is_refused_not_crashed(tmp_path):
    """A resubmission whose hold is still live must be a bounded refusal.

    The refusal path is a decision the caller already knows how to report; an
    ``IntegrityError`` from the partial unique index would instead surface as an
    unhandled 500 on a submission that did nothing wrong.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=1_000)
    at = _timestamp(2026, 9, 6)
    task_id = "b" * 32

    first = _reserve(database, 92, task_id=task_id, at=at)
    second = _reserve(database, 92, task_id=task_id, at=at + 1)

    assert first["allowed"] is True
    assert second["allowed"] is False
    assert second["reason_code"] == AdmissionReason.COMPUTE_EXHAUSTED.value
    assert second["reservation_id"] is None
    assert second["quantity"] == 0
    # Exactly one hold exists: the refusal did not mint a second claim.
    holds = database.list_reservations(user_id=92, state=ReservationState.HELD.value)
    assert [hold["task_id"] for hold in holds] == [task_id]
    assert sum(int(hold["quantity"]) for hold in holds) == first["quantity"]


# ---------------------------------------------------------------------------
# One authoritative answer to "may this user run?"
# ---------------------------------------------------------------------------


def test_the_envelope_can_never_contradict_the_admission_decision(tmp_path):
    """The projection and the decision are the same scope, so they agree.

    A later consumer (placement, reporting, MCP) reads the envelope instead of
    re-deriving a balance.  If a per-class entry existed it could report a
    confident "yes" for one class while admission refuses at the shared
    allowance — so the envelope carries only the scopes admission decides on.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=1_000)
    at = _timestamp(2026, 9, 6)
    _start(database, 93, job_id="9810", at=at, gpus=1, gres="gpu:a100:1")
    database.settle_allocation_elapsed("9810", elapsed_seconds=600, finished_at=at + 600)

    envelope = database.resource_envelope(93, at=at + 600)
    gpu = envelope.compute_for("gpu_second")
    assert gpu is not None
    assert gpu.resource_class == ""

    # The envelope's own remaining balance is what admission acts on: a request
    # for the last of it is admitted, one unit more is refused, and the envelope
    # reports the same zero afterwards.
    decision = _reserve(database, 93, task_id="e" * 32, at=at + 600)
    assert decision["allowed"] is True
    assert decision["remaining"] == gpu.remaining - decision["quantity"]
    refused = _reserve(database, 93, task_id="f" * 32, at=at + 600)
    assert refused["allowed"] is False
    assert database.resource_envelope(93, at=at + 600).compute_for("gpu_second").remaining == 0


def test_releasing_a_hold_publishes_the_admission_release_fact(tmp_path, monkeypatch):
    """Giving entitlement back is an admission decision, so it is observable.

    The no-op case emits nothing: a second release has no live claim to report,
    and emitting one would make an idempotent call look like a second release.
    """
    emitted: list[tuple[str, dict]] = []
    import revocompute.db as db_module

    monkeypatch.setattr(
        db_module,
        "emit_event",
        lambda event, **fields: emitted.append((event, fields)) or fields,
    )
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=1_000)
    at = _timestamp(2026, 9, 6)
    _reserve(database, 94, task_id="a" * 32, at=at)

    assert database.release_reservation(task_id="a" * 32, at=at + 1) is True
    assert database.release_reservation(task_id="a" * 32, at=at + 2) is False

    assert [event for event, _ in emitted] == ["resource.admission.released"]
    assert emitted[0][1]["task_id"] == "a" * 32


# ---------------------------------------------------------------------------
# A reservation is the authority that admitted its own Task
# ---------------------------------------------------------------------------


def test_a_task_holding_the_final_entitlement_starts_its_own_allocation(tmp_path):
    """The hold that admitted a submission must not refuse it at allocation start.

    Holding the final unit drives the remaining balance to zero, so a start that
    re-read the balance would be refused by the Task's own reservation.  The
    reservation is this Task's admission authority, consumed by the same
    transition that records the allocation.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=100)
    at = _timestamp(2026, 9, 20)
    task_id = "a1" + "0" * 30
    decision = _reserve(database, 95, task_id=task_id, at=at)
    assert decision["allowed"] is True
    assert decision["quantity"] == 100
    assert database.compute_entitlement(95, at=at).remaining == 0

    allocation = database.record_allocation_start(
        user_id=95,
        task_id=task_id,
        stage_id="model",
        slurm_job_id="9901",
        gpu_count=1,
        cpu_cores=2,
        started_at=at + 5,
    )

    assert allocation["admitted_by_reservation"] is True
    assert allocation["slurm_job_id"] == "9901"
    reservation = database.list_task_reservations(task_id)[0]
    assert reservation["state"] == ReservationState.RELEASED.value
    assert reservation["reason_code"] == ReservationReason.ALLOCATION_STARTED.value
    # The allocation, not the hold, occupies the balance from here on: it is
    # unsettled (its elapsed time is not known yet), so the position is a lower
    # bound rather than a double charge.
    entitlement = database.compute_entitlement(95, at=at + 5)
    assert entitlement.reserved == 0
    assert entitlement.unsettled == 1


def test_two_tasks_racing_for_the_final_entitlement_leave_one_runnable_winner(tmp_path):
    """Exactly one of two competing submissions is granted the final entitlement.

    The first takes the final entitlement; the second is refused a hold and,
    having no hold of its own and no balance, is refused the grant at allocation
    start too — the refusal is the same decision either way, never a free run.
    The loser's refusal is a grant fact: it may be recorded only if Slurm
    actually handed it resources, which never happened here.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=60)
    at = _timestamp(2026, 9, 21)
    winner, loser = "b1" + "0" * 30, "b2" + "0" * 30

    first = _reserve(database, 96, task_id=winner, at=at)
    second = _reserve(database, 96, task_id=loser, at=at + 1)

    assert first["allowed"] is True
    assert second["allowed"] is False
    assert second["reason_code"] == AdmissionReason.COMPUTE_EXHAUSTED.value
    assert database.list_task_reservations(loser) == []

    assert database.record_allocation_start(
        user_id=96, task_id=winner, stage_id="model", slurm_job_id="9902", gpu_count=1, cpu_cores=1, started_at=at + 2
    )["admitted_by_reservation"] is True
    denied = database.record_allocation_start(
        user_id=96, task_id=loser, stage_id="model", slurm_job_id="9903", gpu_count=1, cpu_cores=1, started_at=at + 3
    )
    assert denied["granted"] is False
    assert denied["reason_code"] == AdmissionReason.COMPUTE_EXHAUSTED.value
    assert database.list_task_reservations(loser) == []


def test_an_expired_hold_with_a_consumed_balance_fails_closed(tmp_path):
    """A hold that lapsed is not authority: the grant is re-decided at start.

    The Task waited, its hold expired, and another allocation has since consumed
    the balance.  Running anyway would charge work the subject cannot pay for, so
    the grant is refused.  Slurm did hand this request resources, so the
    allocation fact exists — refused, not erased.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=60)
    at = _timestamp(2026, 9, 22)
    task_id = "c1" + "0" * 30
    _reserve(database, 97, task_id=task_id, at=at, ttl_seconds=1)
    assert database.expire_stale_reservations(now=at + 10) == 1

    _start(database, 97, job_id="9904", at=at + 20, task_id="c2" + "0" * 30, gpus=1)
    # The other allocation consumed the whole allowance before this start.
    database.settle_allocation_elapsed("9904", elapsed_seconds=60, finished_at=at + 21)

    denied = database.record_allocation_start(
        user_id=97, task_id=task_id, stage_id="model", slurm_job_id="9905", gpu_count=1, cpu_cores=1,
        started_at=at + 30,
    )

    assert denied["granted"] is False
    assert denied["reason_code"] == AdmissionReason.COMPUTE_EXHAUSTED.value
    assert [row["slurm_job_id"] for row in database.list_task_allocations(task_id)] == ["9905", "9905"]
    assert database.list_task_reservations(task_id)[0]["state"] == ReservationState.EXPIRED.value


def test_an_expired_hold_with_remaining_balance_is_re_admitted(tmp_path):
    """An expired hold whose entitlement is still unspent may run.

    Nothing consumed the balance while the hold lapsed, so the start re-decides
    the position in the same transaction and admits: the expiry bounds a claim
    that was never used, it does not bar the Task.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=60)
    at = _timestamp(2026, 9, 23)
    task_id = "d1" + "0" * 30
    _reserve(database, 98, task_id=task_id, at=at, ttl_seconds=1)
    assert database.expire_stale_reservations(now=at + 10) == 1

    allocation = database.record_allocation_start(
        user_id=98, task_id=task_id, stage_id="model", slurm_job_id="9906", gpu_count=1, cpu_cores=4,
        started_at=at + 20,
    )

    assert allocation["admitted_by_reservation"] is False
    assert allocation["remaining_gpu_seconds"] == 60
    assert {row["unit"] for row in database.list_task_allocations(task_id)} == {
        "cpu_core_second",
        "gpu_second",
    }


def test_a_later_workflow_stage_is_admitted_against_what_is_left(tmp_path):
    """A workflow's second GPU stage has no hold of its own; it is admitted on the balance.

    The Task's single submission hold was consumed by the first stage, so the
    later stage's start re-decides the position — admitted while entitlement
    remains, refused once it is gone, without a second reservation ever existing.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=240)
    at = _timestamp(2026, 9, 24)
    task_id = "e1" + "0" * 30
    _reserve(database, 99, task_id=task_id, at=at)
    database.record_allocation_start(
        user_id=99, task_id=task_id, stage_id="features", slurm_job_id="9907", gpu_count=1, cpu_cores=1,
        started_at=at + 1,
    )
    database.settle_allocation_elapsed("9907", elapsed_seconds=60, finished_at=at + 61)

    later = database.record_allocation_start(
        user_id=99, task_id=task_id, stage_id="model", slurm_job_id="9908", gpu_count=1, cpu_cores=1,
        started_at=at + 62,
    )
    assert later["admitted_by_reservation"] is False
    assert later["granted"] is True
    database.settle_allocation_elapsed("9908", elapsed_seconds=180, finished_at=at + 242)

    final = database.record_allocation_start(
        user_id=99, task_id=task_id, stage_id="relax", slurm_job_id="9909", gpu_count=1, cpu_cores=1,
        started_at=at + 243,
    )
    assert final["granted"] is False
    assert final["reason_code"] == AdmissionReason.COMPUTE_EXHAUSTED.value


def test_a_hold_is_not_authority_once_the_balance_is_gone(tmp_path):
    """A reservation buys a grant only while the position it was made against stands.

    The Task waited with a hold on the whole allowance, and the subject's
    balance has since gone negative *past* that hold (here by an administrative
    correction; the same shape arrives from an allocation that settled into an
    overdraft).  The hold is no longer authority for anything, so the grant is
    refused rather than charging an allocation the balance cannot cover.  The
    claim the submission made is still spent: the allocation the scheduler handed
    over exists, and the fact is what the balance is now charged against.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=100)
    at = _timestamp(2026, 9, 26)
    task_id = "a2" + "0" * 30
    assert _reserve(database, 101, task_id=task_id, at=at, ttl_seconds=1)

    database.adjust_compute_account(
        user_id=101,
        gpu_seconds=-250,
        actor_user_id=101,
        reason="The subject's balance was reduced below the outstanding hold",
        idempotency_key="drain-101",
        created_at=at + 5,
    )
    entitlement = database.compute_entitlement(101, at=at + 5)
    assert entitlement.remaining + 100 < 0

    denied = database.record_allocation_start(
        user_id=101,
        task_id=task_id,
        stage_id="model",
        slurm_job_id="9910",
        gpu_count=1,
        cpu_cores=1,
        started_at=at + 10,
    )

    assert denied["granted"] is False
    assert denied["reason_code"] == AdmissionReason.COMPUTE_EXHAUSTED.value
    # The allocation the scheduler granted is a fact, refused but present (one
    # row per unit), and the hold that covered it is spent rather than left live
    # for a re-claim.
    assert {row["slurm_job_id"] for row in database.list_task_allocations(task_id)} == {"9910"}
    assert {row["unit"] for row in database.list_task_allocations(task_id)} == {"gpu_second", "cpu_core_second"}
    assert database.list_task_reservations(task_id)[0]["state"] == ReservationState.RELEASED.value


# ---------------------------------------------------------------------------
# The allocation FACT exists independently of the admission GRANT
# ---------------------------------------------------------------------------


def test_a_denied_allocation_is_still_recorded_and_settleable(tmp_path):
    """A quota denial records the allocation that Slurm already handed over.

    The wrapper observed its own job RUNNING, so CPUs and GPUs were allocated to
    it.  The grant is refused — the balance cannot cover the work — but that is a
    policy answer about the *scientific command*, not a claim that no allocation
    happened.  The fact stays, marked with the denial, and settles for the time
    the resources were actually held.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=60)
    at = _timestamp(2026, 9, 28)
    winner, denied = "d1" + "0" * 30, "d2" + "0" * 30
    _reserve(database, 200, task_id=winner, at=at)
    _start(database, 200, job_id="9930", at=at + 1, task_id=winner, gpus=1)
    # The winner consumed the whole allowance, so the next start has no balance.
    database.settle_allocation_elapsed("9930", elapsed_seconds=60, finished_at=at + 61)

    decision = database.record_allocation_start(
        user_id=200, task_id=denied, stage_id="model", slurm_job_id="9931", gpu_count=1, cpu_cores=2,
        started_at=at + 2,
    )

    assert decision["granted"] is False
    assert decision["reason_code"] == AdmissionReason.COMPUTE_EXHAUSTED.value
    # The allocation the scheduler made is a fact: both units exist, ACTIVE, and
    # carrying the reason the command was refused.
    facts = database.list_task_allocations(denied)
    assert {row["unit"] for row in facts} == {"gpu_second", "cpu_core_second"}
    assert {row["status"] for row in facts} == {"active"}
    assert all(row["denial_reason"] for row in facts)
    # The wrapper held those resources for 30 s before the gate terminated it.
    settled = database.settle_allocation_elapsed("9931", elapsed_seconds=30, finished_at=at + 92)
    assert settled["quantity"] == 30
    assert database.list_task_allocations(denied)[0]["status"] == "settled"
    # The winner's own 60 s allocation plus this denied Task's 30 s.
    assert database.gpu_credit_summary(200, at=at + 62)["usage_gpu_seconds"] == 90


def test_a_denied_start_consumes_the_claim_it_made(tmp_path):
    """A denial does not return resources to the scheduler, so the hold is spent.

    The submission's reservation covered it up to the moment the allocation
    started; that moment happened, so the claim is consumed whether or not the
    command was granted.  Leaving it live would let the same Task re-claim
    entitlement after its refused allocation was already accounted for.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=100)
    at = _timestamp(2026, 9, 28)
    task_id = "e2" + "0" * 30
    assert _reserve(database, 201, task_id=task_id, at=at)["allowed"] is True
    database.adjust_compute_account(
        user_id=201,
        gpu_seconds=-250,
        actor_user_id=201,
        reason="drain",
        idempotency_key="drain-201",
        created_at=at + 1,
    )

    decision = database.record_allocation_start(
        user_id=201, task_id=task_id, stage_id="model", slurm_job_id="9932", gpu_count=1, cpu_cores=1,
        started_at=at + 2,
    )

    assert decision["granted"] is False
    reservation = database.list_task_reservations(task_id)[0]
    assert reservation["state"] == ReservationState.RELEASED.value
    assert reservation["reason_code"] == ReservationReason.ALLOCATION_STARTED.value


def test_a_repeated_denied_start_preserves_the_one_known_fact(tmp_path):
    """A lost response / retried start re-reads the fact instead of rewriting it."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=60)
    at = _timestamp(2026, 9, 28)
    winner, denied = "f2" + "0" * 30, "f3" + "0" * 30
    _reserve(database, 202, task_id=winner, at=at)
    _start(database, 202, job_id="9933", at=at + 1, task_id=winner, gpus=1)

    first = database.record_allocation_start(
        user_id=202, task_id=denied, stage_id="model", slurm_job_id="9934", gpu_count=1, cpu_cores=1,
        started_at=at + 2,
    )
    started_at = {row["unit"]: row["started_at"] for row in database.list_task_allocations(denied)}
    second = database.record_allocation_start(
        user_id=202, task_id=denied, stage_id="model", slurm_job_id="9934", gpu_count=1, cpu_cores=1,
        started_at=at + 99,
    )

    assert first["granted"] is False and second["granted"] is False
    assert len(database.list_task_allocations(denied)) == 2
    # The original start edge is the known fact: a retry never rewrites it.
    assert {row["unit"]: row["started_at"] for row in database.list_task_allocations(denied)} == started_at


def test_reconciliation_cannot_overwrite_a_known_settled_fact(tmp_path):
    """Once settled, the authoritative elapsed duration is not re-derived."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=600)
    at = _timestamp(2026, 9, 29)
    task_id = "a8" + "0" * 30
    _reserve(database, 203, task_id=task_id, at=at)
    _start(database, 203, job_id="9935", at=at + 1, task_id=task_id, gpus=1)
    first = database.settle_allocation_elapsed("9935", elapsed_seconds=45, finished_at=at + 46)
    second = database.settle_allocation_elapsed("9935", elapsed_seconds=999, finished_at=at + 1000)

    assert first == second
    assert database.gpu_credit_summary(203, at=at + 1000)["usage_gpu_seconds"] == 45


# ---------------------------------------------------------------------------
# The wrapper's execution evidence survives a crash
# ---------------------------------------------------------------------------


def test_a_wrapper_observation_is_a_settleable_fact_with_no_grant_yet(tmp_path):
    """The earliest compute-node evidence is durable, unsettled, and never zero.

    The wrapper printed its own ``$SLURM_JOB_ID`` — it is executing inside an
    allocation — but the server died before any admission decision.  The fact
    must survive as an ACTIVE allocation with unknown elapsed time, so a restart
    settles it from scheduler evidence instead of losing the occupancy.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=1_000)
    at = _timestamp(2026, 9, 30)
    task_id = "0a" + "0" * 30

    observed = database.observe_allocation_start(
        user_id=210, task_id=task_id, stage_id="model", slurm_job_id="9940",
        gpu_count=1, cpu_cores=4, started_at=at,
    )

    assert observed["slurm_job_id"] == "9940"
    facts = database.list_task_allocations(task_id)
    assert {row["unit"] for row in facts} == {"gpu_second", "cpu_core_second"}
    assert {row["status"] for row in facts} == {"active"}
    assert all(row["quantity"] is None for row in facts)
    assert all(row["evidence_source"] == "runner_observation" for row in facts)
    # Unknown elapsed time is not zero: the allocation still constrains admission.
    assert database.compute_entitlement(210, at=at).unsettled == 1

    # A restart settles it from the one authoritative elapsed duration.
    settled = database.settle_allocation_elapsed("9940", elapsed_seconds=300, finished_at=at + 300)
    assert settled["quantity"] == 300
    assert database.gpu_credit_summary(210, at=at + 300)["usage_gpu_seconds"] == 300


def test_the_grant_decision_is_made_once_for_an_observed_allocation(tmp_path):
    """A start after an observation adjudicates the same fact; it never doubles it.

    The observation and the later start describe one allocation.  The second call
    decides the grant and records it, and a third call reads that decision
    instead of making another against a balance the first already moved.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=100)
    at = _timestamp(2026, 9, 30)
    task_id = "0b" + "0" * 30
    assert _reserve(database, 211, task_id=task_id, at=at)["allowed"] is True
    database.observe_allocation_start(
        user_id=211, task_id=task_id, stage_id="model", slurm_job_id="9941",
        gpu_count=1, cpu_cores=1, started_at=at + 1,
    )

    granted = database.record_allocation_start(
        user_id=211, task_id=task_id, stage_id="model", slurm_job_id="9941",
        gpu_count=1, cpu_cores=1, started_at=at + 1,
    )

    assert granted["granted"] is True
    assert len(database.list_task_allocations(task_id)) == 2
    # The start edge is the evidence already recorded, never rewritten.
    assert {row["started_at"] for row in database.list_task_allocations(task_id)} == {at + 1}

    again = database.record_allocation_start(
        user_id=211, task_id=task_id, stage_id="model", slurm_job_id="9941",
        gpu_count=1, cpu_cores=1, started_at=at + 90,
    )
    assert again["granted"] is True
    assert len(database.list_task_allocations(task_id)) == 2
    assert {row["started_at"] for row in database.list_task_allocations(task_id)} == {at + 1}


def test_an_observation_makes_the_allocation_idempotent_across_a_restart(tmp_path):
    """Exactly one allocation survives a crash on either side of the dispatch.

    The reservation may or may not already be scheduler-owned when the process
    dies; either way the observation is idempotent, and the later start completes
    the same fact rather than creating a second one.
    """
    path = str(tmp_path / "tasks.sqlite3")
    at = _timestamp(2026, 9, 30)
    task_id = "0c" + "0" * 30

    first = TaskDatabase(path, monthly_gpu_seconds=1_000)
    first.observe_allocation_start(
        user_id=212, task_id=task_id, stage_id="model", slurm_job_id="9942",
        gpu_count=1, cpu_cores=1, started_at=at,
    )
    first.engine.dispose()

    second = TaskDatabase(path, monthly_gpu_seconds=1_000)
    # The observation is idempotent after the restart.
    second.observe_allocation_start(
        user_id=212, task_id=task_id, stage_id="model", slurm_job_id="9942",
        gpu_count=1, cpu_cores=1, started_at=at + 5,
    )
    second.record_allocation_start(
        user_id=212, task_id=task_id, stage_id="model", slurm_job_id="9942",
        gpu_count=1, cpu_cores=1, started_at=at + 5,
    )

    facts = second.list_task_allocations(task_id)
    assert len(facts) == 2
    assert {row["unit"] for row in facts} == {"gpu_second", "cpu_core_second"}
    second.settle_allocation_elapsed("9942", elapsed_seconds=120, finished_at=at + 120)
    assert second.gpu_credit_summary(212, at=at + 120)["usage_gpu_seconds"] == 120


def test_a_hold_covers_an_overdraft_within_its_own_unit(tmp_path):
    """The account's deliberate overdraft still applies to the Task that holds it.

    The hold is this Task's own unit and is excluded from the remaining balance,
    so a position that is negative only because of the hold itself is exactly
    the case the overdraft rule permits.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=100)
    at = _timestamp(2026, 9, 27)
    task_id = "a3" + "0" * 30
    assert _reserve(database, 102, task_id=task_id, at=at)["allowed"] is True
    assert database.compute_entitlement(102, at=at).remaining == 0

    allocation = database.record_allocation_start(
        user_id=102, task_id=task_id, stage_id="model", slurm_job_id="9911", gpu_count=1, cpu_cores=1,
        started_at=at + 1,
    )

    assert allocation["admitted_by_reservation"] is True


def test_a_dispatch_failure_returns_the_hold_immediately(tmp_path):
    """A failed dispatch must not strand entitlement until the TTL.

    The Task never reached the scheduler, so its claim is released at once and
    idempotently — the reservation row records the reason, and a second call is
    a no-op rather than a second release.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=100)
    at = _timestamp(2026, 9, 25)
    task_id = "f1" + "0" * 30
    assert _reserve(database, 100, task_id=task_id, at=at)["allowed"] is True
    assert database.compute_entitlement(100, at=at).remaining == 0

    assert (
        database.release_reservation(
            task_id=task_id, reason_code=ReservationReason.DISPATCH_FAILED.value, at=at + 5
        )
        is True
    )
    assert (
        database.release_reservation(
            task_id=task_id, reason_code=ReservationReason.DISPATCH_FAILED.value, at=at + 6
        )
        is False
    )

    assert database.compute_entitlement(100, at=at + 6).remaining == 100
    reservation = database.list_task_reservations(task_id)[0]
    assert reservation["state"] == ReservationState.RELEASED.value
    assert reservation["reason_code"] == ReservationReason.DISPATCH_FAILED.value


# ---------------------------------------------------------------------------
# Scheduler ownership: identity and commitment are one row
# ---------------------------------------------------------------------------


def test_dispatch_hands_the_hold_to_the_scheduler_and_names_its_job(tmp_path):
    """Dispatch is the whole transition: state, TTL, and identity in one write.

    A queued reservation with no recorded scheduler identity could be read as
    "there is nothing to wait for" during the window before the Task row is
    updated, and its entitlement would be handed to a second submission while a
    real request was still queued.  Writing the identity with the state is what
    makes that read impossible.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=1_000)
    at = _timestamp(2026, 9, 22)
    task_id = "a4" + "0" * 30
    assert _reserve(database, 104, task_id=task_id, at=at)["allowed"] is True

    assert database.record_reservation_dispatch(task_id=task_id, slurm_job_id="7001", at=at + 2) is True
    # A repeated observation of the same identity is not a second dispatch.
    assert database.record_reservation_dispatch(task_id=task_id, slurm_job_id="7001", at=at + 3) is False

    reservation = database.list_task_reservations(task_id)[0]
    assert reservation["state"] == ReservationState.QUEUED.value
    # No wall-clock expiry any more: the scheduler owns it until evidence frees it.
    assert reservation["expires_at"] is None
    assert reservation["scheduler_job_id"] == "7001"
    assert reservation["dispatched_at"] == at + 2


def test_a_queued_commitment_survives_a_long_queue_wait(tmp_path):
    """A request waiting past the pre-dispatch TTL keeps its entitlement.

    This is the whole point of the two ownership modes: the hold has a TTL
    because a submission that died before dispatch would otherwise strand
    entitlement, and the queued commitment deliberately has none because the
    request it belongs to may legitimately wait far longer than that TTL.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=1_000)
    at = _timestamp(2026, 9, 22)
    task_id = "a5" + "0" * 30
    assert _reserve(database, 105, task_id=task_id, at=at, ttl_seconds=60)["allowed"] is True
    database.record_reservation_dispatch(task_id=task_id, slurm_job_id="7002", at=at + 1)

    # Far past the TTL the hold was created with.
    assert database.expire_stale_reservations(now=at + 100_000) == 0

    reservation = database.list_task_reservations(task_id)[0]
    assert reservation["state"] == ReservationState.QUEUED.value
    # And it still constrains a competing submission.
    competing = _reserve(database, 105, task_id="a6" + "0" * 30, at=at + 100_000)
    assert competing["quantity"] == 0
    held = database.list_task_reservations(task_id)[0]
    assert held["state"] == ReservationState.QUEUED.value


def test_a_reclaim_leaves_a_queued_request_named_by_its_identity(tmp_path):
    """Only the scheduler's evidence frees a queued commitment, exactly once."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"), monthly_gpu_seconds=1_000)
    at = _timestamp(2026, 9, 22)
    task_id = "a7" + "0" * 30
    _reserve(database, 106, task_id=task_id, at=at)
    database.record_reservation_dispatch(task_id=task_id, slurm_job_id="7003", at=at + 1)

    assert database.reclaim_queued_reservation(task_id=task_id, at=at + 5) is True
    assert database.reclaim_queued_reservation(task_id=task_id, at=at + 6) is False
    assert database.list_queued_reservations() == []
    assert database.compute_entitlement(106, at=at + 6).remaining == 1_000

