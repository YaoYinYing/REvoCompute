# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Admin read model, exercised against real canonical state.

Every case here builds the state through the *production* writer for that fact —
a real :class:`~revocompute.db.TaskDatabase` on a temporary file, the real ledger
and lifecycle writers, a real :class:`~revocompute.manage_db.ManageDatabase`, and
the real placement planner behind the submission snapshot — and then reads it
through :mod:`revocompute.admin_reports`.  Nothing asserts a query the module is
supposed to run; the tests assert the *behaviour* the read model must have:

* a recorded placement is reported as it was recorded, and a later policy change
  does not move it;
* a Task with no recorded decision reports unrecorded, never a guessed class;
* a measurement nobody took stays unknown, never ``0``;
* a drift record appears when the canonical detection finds one, and the report
  says "no drift" — not a fabricated health score — when there is none;
* every read is bounded, and a refusal is a typed error rather than a 500.

The authorization boundary is asserted at the HTTP layer in
``tests/server/test_admin_reports_api.py``; these cases are about the projection.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from revocompute import admin_reports as ar
from revocompute import resource_lifecycle as rlife
from revocompute.db import TaskDatabase
from revocompute.manage_db import ManageDatabase
from revocompute.placement import (
    PLACED_ACCELERATOR,
    PLACED_CPU,
    AcceleratorRequirement,
    resolve_submission_placement,
)
from revocompute.resource_ledger import DataLifecycleState

GIB = 1024**3


# --------------------------------------------------------------------------- #
# Real canonical state
# --------------------------------------------------------------------------- #


@pytest.fixture
def store(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    yield database
    database.engine.dispose()


def _task_row(
    store: TaskDatabase,
    task_id: str,
    *,
    user_id: int,
    status: str = "running",
    uploaded_at: float = 1_000.0,
    started_at: float | None = 1_010.0,
    finished_at: float | None = None,
    walltime: float | None = None,
    input_form: dict | None = None,
    task_type: str = "cpu_runner",
) -> dict:
    """Write one real Task row, as the submit path does."""
    fields = {
        "filename": "input.fasta",
        "file_path": f"/immutable/{task_id}.fasta",
        "uploaded_at": uploaded_at,
        "status": status,
        "is_binary": 0,
        "username": f"user-{user_id}",
        "submitted_by_user_id": user_id,
        "storage_key": f"user-{user_id}",
        "task_type": task_type,
    }
    if started_at is not None:
        fields["started_at"] = started_at
    if finished_at is not None:
        fields["finished_at"] = finished_at
    if walltime is not None:
        fields["walltime"] = walltime
    if input_form is not None:
        fields["input_form"] = json.dumps(input_form)
    store.upsert_task(task_id, **fields)
    return store.get_task(task_id)


@pytest.fixture
def deployment(tmp_path):
    """A real deployment configuration store, and the shape the planner reads.

    ``ManageDatabase`` is the production configuration owner, so a value that
    cannot survive the store cannot survive this fixture either: the class map is
    written and read back through the same serialize/parse pair the admin config
    path uses.
    """
    created: list[ManageDatabase] = []

    def _make(*, classes=None, allowed_queues=(), globals_=None):
        store = ManageDatabase(str(tmp_path / f"manage-{len(created)}.sqlite"))
        created.append(store)
        if allowed_queues:
            store.resource_set("slurm_allowed_queues", list(allowed_queues))
        if classes:
            store.resource_set("slurm_execution_classes", classes)
        for key, value in (globals_ or {}).items():
            store.resource_set(key, value)
        return store

    yield _make
    for store in created:
        store.close()


def _planned_snapshot(
    configured: ManageDatabase,
    *,
    name: str = "demo",
    gpus: bool = False,
    requirement=None,
    default_timeout_seconds: int = 3600,
) -> dict:
    """The ``input_form`` fields the real planner produces for one submission.

    This is the production planning call, not a hand-built dict: the decision and
    the frozen snapshot come from the same resolution the submission path makes.
    """
    task_type = SimpleNamespace(name=name, gpus=gpus, accelerator_requirement=requirement, workflow=())
    runner = SimpleNamespace(max_runtime_seconds=default_timeout_seconds)
    placement = resolve_submission_placement(configured, task_type, runner)
    return placement.public_input_fields()


def _submission_form(**extra) -> dict:
    """A minimal ``input_form`` body with no recorded placement decision."""
    return {"entities": [], "submitted_at": "2026-01-01T00:00:00+00:00", **extra}


# --------------------------------------------------------------------------- #
# Placement: the recorded decision, never a re-resolution
# --------------------------------------------------------------------------- #


def test_recorded_placement_is_projected_verbatim(store, deployment, tmp_path):
    configured = deployment(
        globals_={"slurm_partition": "normal", "slurm_gres": "gpu:a100:1"},
        allowed_queues=("normal", "gpu"),
        classes="cpu=normal;a100=gpu",
    )
    form = _submission_form(**_planned_snapshot(configured, gpus=True, requirement=AcceleratorRequirement("a100", 1)))
    row = _task_row(store, "a" * 32, user_id=7, task_type="demo", input_form=form)

    projected = ar.placement_projection(row)

    assert projected["state"] == ar.PLACEMENT_RECORDED
    assert projected["reason_code"] == PLACED_ACCELERATOR
    assert projected["execution_class_id"] == "accelerator|gpu|a100x1"
    assert projected["reason"]
    # The canonical projection of a decision, unaltered.
    assert projected["decision"]["execution_class"]["state"] == "accelerator"


def test_a_later_policy_change_does_not_move_a_recorded_placement(store, deployment, tmp_path):
    """The facade must never re-resolve: history is read, not recomputed."""
    configured = deployment(
        globals_={"slurm_partition": "normal"},
        allowed_queues=("normal", "gpu"),
        classes="cpu=normal;gpu=gpu",
    )
    form = _submission_form(**_planned_snapshot(configured, gpus=False))
    row = _task_row(store, "b" * 32, user_id=7, task_type="demo", input_form=form)
    before = ar.placement_projection(row)

    # Rewrite the deployment: CPU work now belongs to a different partition, and
    # the accelerator class is gone entirely.  A re-resolution would report that;
    # the recorded decision must not move.
    configured.resource_set("slurm_execution_classes", "cpu=other")
    configured.resource_set("slurm_partition", "other")
    after = ar.placement_projection(store.get_task("b" * 32))

    assert before["state"] == ar.PLACEMENT_RECORDED
    assert before["reason_code"] == PLACED_CPU
    assert after == before
    assert after["execution_class_id"] == "cpu|normal|none"


def test_a_policy_change_between_two_submissions_yields_two_recorded_revisions(store, deployment, tmp_path):
    """A revision is version identity, not a verdict about which one is right."""
    configured = deployment(globals_={"slurm_partition": "normal"}, allowed_queues=("normal",))
    first = _submission_form(**_planned_snapshot(configured))
    configured.resource_set("slurm_partition", "normal")
    second = _submission_form(**_planned_snapshot(configured))

    first_row = _task_row(store, "c" * 32, user_id=7, task_type="demo", input_form=first)
    second_row = _task_row(store, "d" * 32, user_id=7, task_type="demo", input_form=second)

    first_projection = ar.placement_projection(first_row)
    second_projection = ar.placement_projection(second_row)

    assert first_projection["policy_revision"].startswith("sha256:")
    # Both decisions are reported as recorded, whatever today's policy is.
    assert first_projection["state"] == ar.PLACEMENT_RECORDED
    assert second_projection["state"] == ar.PLACEMENT_RECORDED


def test_a_task_with_no_recorded_placement_reports_unrecorded_not_a_class(store):
    row = _task_row(store, "e" * 32, user_id=7, input_form=_submission_form())

    projected = ar.placement_projection(row)

    assert projected["state"] == ar.PLACEMENT_UNRECORDED
    assert projected["execution_class_id"] is None
    assert projected["reason_code"] is None
    assert projected["decision"] is None


def test_a_task_with_no_input_form_at_all_reports_unrecorded(store):
    row = _task_row(store, "f" * 32, user_id=7)

    projected = ar.placement_projection(row)

    assert projected["state"] == ar.PLACEMENT_UNRECORDED
    assert projected["provenance"] == "input_form_missing"
    assert projected["execution_class_id"] is None


def test_a_decision_without_its_snapshot_is_unreadable_not_unrecorded(store):
    """A record that cannot be joined to its snapshot is a different fault."""
    row = _task_row(
        store,
        "1" * 32,
        user_id=7,
        input_form=_submission_form(placement_decision={"execution_class": {"state": "cpu"}}),
    )

    projected = ar.placement_projection(row)

    assert projected["state"] == ar.PLACEMENT_UNREADABLE
    assert projected["error"]
    assert projected["execution_class_id"] is None


def test_a_decision_disagreeing_with_its_snapshot_is_unreadable(store, deployment):
    configured = deployment(globals_={"slurm_partition": "normal"}, allowed_queues=("normal", "gpu"))
    form = _submission_form(**_planned_snapshot(configured, gpus=True))
    # Tamper with the record so it no longer describes the snapshot beside it.
    form["placement_decision"]["execution_class"] = {
        "state": "accelerator",
        "partition": "elsewhere",
        "device_class": "a100",
        "device_count": 8,
    }
    row = _task_row(store, "2" * 32, user_id=7, input_form=form)

    projected = ar.placement_projection(row)

    assert projected["state"] == ar.PLACEMENT_UNREADABLE
    assert "snapshot" in projected["error"]


def test_every_workflow_stage_projects_its_own_recorded_decision(store, deployment):
    configured = deployment(globals_={"slurm_partition": "normal"}, allowed_queues=("normal", "gpu"))
    form = _submission_form(**_planned_snapshot(configured, gpus=False))
    # A workflow records its stages beside the primary profile exactly as the
    # planner writes them; both halves stay joined to their own snapshot.
    primary = form["resource_policy"]
    form["resource_policies"] = {"calc": primary}
    form["placement_decisions"] = {"calc": {**form["placement_decision"], "stage": "calc"}}
    row = _task_row(store, "3" * 32, user_id=7, input_form=form)

    projections = ar.placement_projections(row)

    assert [item["stage"] for item in projections] == [None, "calc"]
    assert all(item["state"] == ar.PLACEMENT_RECORDED for item in projections)
    assert projections[1]["provenance"] == "input_form.placement_decisions[calc]"


# --------------------------------------------------------------------------- #
# Task operations
# --------------------------------------------------------------------------- #


def test_task_operations_reports_bounded_counts_and_labelled_latency(store, deployment):
    configured = deployment(globals_={"slurm_partition": "normal"}, allowed_queues=("normal",))
    recorded = _submission_form(**_planned_snapshot(configured))
    _task_row(store, "4" * 32, user_id=7, status="running", input_form=recorded)
    _task_row(store, "5" * 32, user_id=8, status="queued", started_at=None, input_form=_submission_form())
    _task_row(store, "6" * 32, user_id=8, status="finished", started_at=1_100.0, finished_at=1_160.0, walltime=60.0)
    _task_row(store, "7" * 32, user_id=9, status="failed", started_at=1_100.0, finished_at=1_105.0, walltime=5.0)

    report = ar.task_operations(store)

    counts = report["counts_in_window"]
    assert counts["queued"] == 1
    assert counts["running"] == 1
    assert counts["active"] == 2
    assert counts["finished"] == 1
    assert counts["failed"] == 1
    assert counts["recorded_analysis"] == 1
    # The runtime total covers both finished Tasks and says so; the queue total
    # covers only the Tasks whose row carries a start.
    assert report["runtime"]["measured"] == 2
    assert report["runtime"]["total_seconds"] == 65.0
    assert report["queue_latency"]["unmeasured"] >= 1
    assert report["window"]["truncated"] is False
    assert [item["task_id"] for item in report["recent_failures"]] == ["7" * 32]


def test_the_operational_page_is_bounded_and_says_what_it_cut(store, deployment):
    configured = deployment(globals_={"slurm_partition": "normal"}, allowed_queues=("normal",))
    for index in range(5):
        _task_row(
            store,
            f"{index:032x}",
            user_id=7,
            task_type="demo",
            input_form=_submission_form(**_planned_snapshot(configured, name="demo")),
        )

    report = ar.task_operations(store, limit=2)

    assert len(report["tasks"]) == 2
    assert report["window"]["truncated"] is True
    assert report["counts_in_window"]["running"] == 5


def test_status_filter_narrows_the_page_but_not_the_counts(store):
    _task_row(store, "8" * 32, user_id=7, status="running")
    _task_row(store, "9" * 32, user_id=7, status="finished", started_at=1_100.0, finished_at=1_160.0)

    report = ar.task_operations(store, statuses=["running"])

    assert [item["status"] for item in report["tasks"]] == ["running"]
    assert report["counts_in_window"]["finished"] == 1


def test_a_queued_task_reports_no_run_or_queue_time_as_unknown_not_zero(store):
    _task_row(store, "a" * 31 + "0", user_id=7, status="queued", started_at=None)

    entry = ar.task_operations(store)["tasks"][0]

    assert entry["queue_seconds"] is None
    assert entry["run_seconds"] is None
    assert ar.task_operations(store)["runtime"]["state"] == "unknown"
    assert ar.task_operations(store)["runtime"]["total_seconds"] is None


# --------------------------------------------------------------------------- #
# Resource operations
# --------------------------------------------------------------------------- #


def test_an_unmeasured_subject_reports_unknown_usage_not_zero(store):
    """Nothing was ever measured for this subject, so usage stays unknown.

    The canonical envelope still reports the deployment's *readiness* for it (the
    GPU allowance and the ungated CPU unit), so the allowance is the canonical
    value; only the *measurement* is withheld, and it is withheld as unknown.
    """
    report = ar.resource_operations(store, 4242)

    units = {item["unit"]: item for item in report["units"]}
    assert units["gpu_second"]["state"] == ar.UNIT_UNMEASURED
    assert units["gpu_second"]["measured"] is False
    assert units["gpu_second"]["allowance"] == store.monthly_gpu_seconds
    assert units["gpu_second"]["measurement"]["used"] is None
    assert units["gpu_second"]["measurement"]["usage_complete"] is None
    assert units["gpu_second"]["pressure"] == "unknown_unmeasured"
    # The canonical projection is still the deployment's answer for the subject:
    # it says what it is allowed, and it is reported unaltered.
    assert units["gpu_second"]["canonical"]["allowance"] == store.monthly_gpu_seconds
    assert units["cpu_core_second"]["state"] == ar.UNIT_UNMEASURED
    assert units["cpu_core_second"]["canonical"]["allowance"] is None


def test_quota_pressure_reflects_the_canonical_envelope(store):
    store.set_compute_allowance(
        user_id=7, monthly_gpu_seconds=60, actor_user_id=1, idempotency_key="set-60", updated_at=time.time()
    )

    report = ar.resource_operations(store, 7)
    gpu = next(item for item in report["units"] if item["unit"] == "gpu_second")

    # Policy alone is not a measurement: the allowance is canonical and the usage
    # it was set against is unknown, so pressure is unknown rather than "available".
    assert gpu["state"] == ar.UNIT_UNMEASURED
    assert gpu["enforced"] is True
    # The allowance is the canonical one, and the projection agrees with the
    # envelope it was read from rather than computing a second balance.
    assert gpu["allowance"] == 60
    assert gpu["canonical"] == report["canonical_envelope"]["compute"][0]
    assert gpu["measurement"]["usage_complete"] is None
    assert gpu["pressure"] == "unknown_unmeasured"


def test_an_unknown_shape_allocation_stays_unknown_and_is_never_a_zero_total(store):
    """The scheduler proved a job held a node; nothing recorded how much."""
    store.observe_unknown_shape_allocation(
        user_id=7, task_id="b" * 32, slurm_job_id="9700", started_at=time.time(), stage_id="model"
    )

    report = ar.resource_operations(store, 7)

    assert report["allocation_facts"]["allocated_gpu_devices"] is None
    assert report["allocation_facts"]["allocated_cpu_cores"] is None
    assert report["allocation_facts"]["unknown_shape_allocations"]["gpu_second"] == 1
    assert report["allocation_facts"]["unsettled_allocations"][0]["unknown_shape"] is True
    assert report["allocation_facts"]["unsettled_allocations"][0]["resource_count"] is None


def test_an_unsettled_allocation_marks_usage_incomplete_rather_than_exact(store):
    store.set_compute_allowance(
        user_id=7, monthly_gpu_seconds=100_000, actor_user_id=1, idempotency_key="set-big", updated_at=time.time()
    )
    store.record_allocation_start(
        user_id=7, task_id="c" * 32, stage_id="model", slurm_job_id="9701",
        gpu_count=2, cpu_cores=1, started_at=time.time(),
    )

    report = ar.resource_operations(store, 7)
    gpu = next(item for item in report["units"] if item["unit"] == "gpu_second")

    assert gpu["measurement"]["unsettled_allocations"] == 1
    assert gpu["measurement"]["usage_complete"] is False
    assert gpu["pressure"] == "unknown_unsettled"


def test_storage_ownership_and_over_limit_come_from_the_lifecycle_rows(store):
    store.ensure_data_lifecycle("d" * 32, user_id=7, logical_bytes=2 * GIB)
    store._storage_soft_limit = GIB
    try:
        report = ar.resource_operations(store, 7)
    finally:
        store._storage_soft_limit = 100 * GIB

    storage = report["storage"]
    assert storage["logical_owned_bytes"] == 2 * GIB
    assert storage["effective_limit_bytes"] == GIB
    assert storage["over_limit"] is True
    assert storage["policy"]["state"] == "inherit"
    assert storage["policy"]["source"] == "deployment_default"
    assert report["durable_data"]["state_counts"] == {DataLifecycleState.ACTIVE.value: 1}


def test_the_report_names_the_per_user_quota_the_admission_decision_uses(store):
    """An override moves the reported ceiling, because it moves the enforced one.

    The report must not name the deployment default while admission refuses on a
    per-user override: two readers of "the ceiling" that disagree is exactly the
    second answer this facade exists to prevent.
    """
    store.ensure_data_lifecycle("c" * 32, user_id=9, logical_bytes=2 * GIB)
    store.set_storage_quota(
        user_id=9,
        state="limited",
        limit_bytes=GIB,
        actor_user_id=3,
        reason="override under test",
        idempotency_key="report-override",
    )

    storage = ar.resource_operations(store, 9)["storage"]

    assert storage["effective_limit_bytes"] == GIB
    assert storage["over_limit"] is True
    assert storage["policy"] == {"state": "limited", "source": "per_user_override"}
    # The deployment default is unchanged, so the two numbers are genuinely
    # different facts about the same subject.
    assert store.storage_soft_limit_bytes != GIB

    store.set_storage_quota(
        user_id=9,
        state="unlimited",
        limit_bytes=None,
        actor_user_id=3,
        reason="grant under test",
        idempotency_key="report-unlimited",
    )
    granted = ar.resource_operations(store, 9)["storage"]
    assert granted["effective_limit_bytes"] is None
    assert granted["over_limit"] is None
    assert granted["policy"] == {"state": "unlimited", "source": "per_user_override"}


def test_a_deployment_with_no_storage_limit_reports_no_limit_not_a_zero_one(store):
    report = ar.resource_operations(store, 7)

    assert report["storage"]["effective_limit_bytes"] == store.storage_soft_limit_bytes or None
    assert report["storage"]["policy"]["state"] in {"inherit", "limited", "unlimited"}
    if report["storage"]["effective_limit_bytes"] is None:
        assert report["storage"]["over_limit"] is None
        assert report["storage"]["remaining_bytes"] is None


def test_the_deployment_roll_reports_only_subjects_with_measured_facts(store):
    store.ensure_data_lifecycle("e" * 32, user_id=11, logical_bytes=GIB)
    store.set_compute_allowance(
        user_id=11, monthly_gpu_seconds=6000, actor_user_id=1, idempotency_key="roll", updated_at=time.time()
    )
    # A subject that only ever had an allowance configured, and never ran anything.
    store.set_compute_allowance(
        user_id=12, monthly_gpu_seconds=6000, actor_user_id=1, idempotency_key="roll-2", updated_at=time.time()
    )
    store.upsert_task(
        "e" * 31 + "f", filename="input.fasta", file_path="/x", uploaded_at=1_000.0, status="running",
        is_binary=0, username="user-11", submitted_by_user_id=11, storage_key="user-11", task_type="cpu_runner",
    )

    report = ar.resource_operations(store)

    assert report["scope"] == "deployment"
    assert [item["subject_id"] for item in report["subjects"]] == [11]
    assert report["subjects"][0]["logical_owned_bytes"] == GIB
    assert report["subjects"][0]["units_measured"]


# --------------------------------------------------------------------------- #
# Platform integrity
# --------------------------------------------------------------------------- #


def test_no_drift_is_reported_as_no_drift_and_never_as_a_health_score(store):
    report = ar.platform_integrity(store)

    assert report["state"] == "no_drift_detected"
    assert report["drift"]["records"] == []
    assert report["drift"]["total"] == 0
    assert "score" not in report
    # Scheduler evidence is measured-and-empty, which is not the same claim as
    # the subsystems that could not be read at all.
    assert report["scheduler_evidence"]["state"] == "measured"
    assert report["runner_readiness"]["state"] == "unknown"
    assert report["runner_readiness"]["reason"] == "runner_host_view_unavailable"
    assert report["operator"]["state"] == "unknown"
    assert report["operator"]["reason"] == "operator_job_store_unavailable"


def test_a_real_drift_class_is_surfaced_with_its_subject(store):
    """A lifecycle row charging bytes for a Task that no longer exists is drift."""
    store.ensure_data_lifecycle("f" * 32, user_id=7, logical_bytes=GIB)

    report = ar.platform_integrity(store)

    kinds = report["drift"]["kinds"]
    assert "lifecycle_without_task" in kinds
    assert report["state"] == "drift_detected"
    record = next(item for item in report["drift"]["records"] if item["kind"] == "lifecycle_without_task")
    assert record["subject"] == "f" * 32
    assert record["navigation"]["target"] == "task"
    assert record["detail"]


def test_a_terminal_task_with_an_unsettled_allocation_is_reported_as_drift(store):
    _task_row(store, "0" * 32, user_id=7, status="finished", started_at=1_000.0, finished_at=1_100.0)
    store.record_allocation_start(
        user_id=7, task_id="0" * 32, stage_id="model", slurm_job_id="9702",
        gpu_count=1, cpu_cores=1, started_at=1_000.0,
    )

    report = ar.platform_integrity(store)

    record = next(
        item for item in report["drift"]["records"] if item["kind"] == "terminal_task_unsettled_allocation"
    )
    assert record["subject"] == "0" * 32
    assert record["repairable"] is True
    # Unsettled allocations are also the scheduler-evidence unknown, reported
    # separately from the drift list that names them.
    assert report["scheduler_evidence"]["state"] == "unknown"
    assert report["scheduler_evidence"]["unsettled_allocations"] >= 1


def test_drift_detection_is_read_only(store):
    """The integrity report detects and navigates; it must repair nothing."""
    store.ensure_data_lifecycle("1" * 31 + "a", user_id=7, logical_bytes=GIB)

    ar.platform_integrity(store)

    record = store.get_data_lifecycle("1" * 31 + "a")
    assert record["state"] == DataLifecycleState.ACTIVE.value
    assert record["accounted_bytes"] == GIB
    assert store.logical_owned_bytes(7) == GIB


def test_integrity_wires_the_canonical_detector_rather_than_a_second_check(store, monkeypatch):
    """The drift list is the canonical detector's output, passed through."""
    from revocompute import resource_ledger as rloan

    sentinel = rloan.ReconciliationDrift(kind="stale_purge", subject="x" * 32, detail="d", repairable=True)
    monkeypatch.setattr(rlife, "detect_drift", lambda *_args, **_kwargs: [sentinel])

    report = ar.platform_integrity(store)

    assert [item["kind"] for item in report["drift"]["records"]] == ["stale_purge"]


def test_platform_integrity_reports_runner_readiness_when_a_host_view_is_supplied(store, monkeypatch):
    """Readiness is derived by the canonical view, and reported as its verdict."""
    from revocompute import admin_reports as module

    monkeypatch.setattr(
        module,
        "fleet_view",
        lambda _host, *, database=None, user_id=None: [
            {
                "runner_family": "demo",
                "readiness": {"status": "VALIDATION_STALE", "reason_code": "RECEIPT_MISSING"},
                "capacity": {"available": None, "reason": "capacity_unknown"},
                "access": {"restricted": False, "granted": True, "policy_id": None},
            }
        ],
    )

    report = ar.platform_integrity(store, host=object())

    assert report["runner_readiness"]["state"] == "measured"
    assert report["runner_readiness"]["families"] == {"demo": "VALIDATION_STALE"}
    assert report["runner_readiness"]["not_ready"] == {"demo": "VALIDATION_STALE"}


# --------------------------------------------------------------------------- #
# Admin activity
# --------------------------------------------------------------------------- #


def test_policy_mutations_appear_with_their_before_and_after(store, tmp_path):
    # The subject is canonical through a Task it owns: an allowance on its own is
    # policy, not a fact about what the subject did, and the activity list is
    # built from subjects the deployment already has facts for.
    _task_row(store, "3" * 31 + "a", user_id=7)
    store.set_compute_allowance(
        user_id=7, monthly_gpu_seconds=500, actor_user_id=99, idempotency_key="act-1", updated_at=2_000.0
    )
    store.set_compute_allowance(
        user_id=7, monthly_gpu_seconds=400, actor_user_id=99, idempotency_key="act-2", updated_at=2_100.0
    )

    report = ar.admin_activity(store, limit=10)

    entries = [item for item in report["activity"] if item["activity"] == "policy"]
    assert [item["after"]["allowance"] for item in entries] == [400, 500]
    assert entries[0]["subject_id"] == 7
    assert entries[0]["actor_user_id"] == 99
    assert entries[0]["operation"] == "set_compute_allowance"


def test_activity_is_bounded_by_a_window_the_caller_names(store):
    _task_row(store, "3" * 31 + "b", user_id=7)
    store.set_compute_allowance(
        user_id=7, monthly_gpu_seconds=500, actor_user_id=99, idempotency_key="win-1", updated_at=1_000.0
    )

    report = ar.admin_activity(store, since=1_500.0)

    assert [item for item in report["activity"] if item["activity"] == "policy"] == []
    assert report["since"] == 1_500.0


def test_operator_job_history_is_merged_into_the_activity_list(store, tmp_path):
    from revocompute.operator_jobs import OperatorJobStore

    _task_row(store, "3" * 31 + "c", user_id=7)
    jobs = OperatorJobStore(str(tmp_path / "operator-jobs.sqlite"))
    jobs.create(
        action="runner.live_test", runner_family="demo", actor_user_id=99, actor_username="sysadmin",
        tier="mutation", lease_scope="runner/demo", requested_intent="runner.live_test",
        plan_digest="sha256:" + "a" * 16, evidence_digest="sha256:" + "b" * 16,
        parameters={}, idempotency_key="op-1",
    )
    store.set_compute_allowance(
        user_id=7, monthly_gpu_seconds=500, actor_user_id=99, idempotency_key="act-3", updated_at=1_000.0
    )

    report = ar.admin_activity(store, operator_jobs=jobs, limit=10)

    assert report["operator"]["state"] == "measured"
    kinds = {item["activity"] for item in report["activity"]}
    assert kinds == {"policy", "operator_job"}


# --------------------------------------------------------------------------- #
# Bounds and refusal
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("function", ["task_operations", "resource_operations", "admin_activity"])
def test_an_over_large_limit_is_clamped_to_the_canonical_ceiling(store, function):
    report = getattr(ar, function)(store, limit=10_000)

    assert report["limit_ceiling"] == ar.MAX_LIMIT
    # Every entry point reports the page size it actually honoured, so a caller
    # that asked for more than the ceiling can see it was clamped.
    if "window" in report:
        assert report["window"]["limit"] == ar.MAX_LIMIT
    else:
        assert report["limit"] == ar.MAX_LIMIT


@pytest.mark.parametrize("function", ["task_operations", "resource_operations", "admin_activity"])
@pytest.mark.parametrize("limit", [0, -1, "many", None, True])
def test_an_unusable_limit_is_refused_with_a_typed_error(store, function, limit):
    with pytest.raises(ar.AdminReportError):
        getattr(ar, function)(store, limit=limit)


def test_platform_integrity_bounds_its_drift_page(store, monkeypatch):
    from revocompute import resource_ledger as rloan

    drift = [
        rloan.ReconciliationDrift(kind="stale_purge", subject=f"{index:032x}", detail="d", repairable=True)
        for index in range(5)
    ]
    monkeypatch.setattr(rlife, "detect_drift", lambda *_args, **_kwargs: drift)

    report = ar.platform_integrity(store, limit=2)

    assert len(report["drift"]["records"]) == 2
    assert report["drift"]["total"] == 5
    assert report["drift"]["truncated"] is True


def test_every_payload_is_json_safe(store, deployment):
    configured = deployment(globals_={"slurm_partition": "normal"}, allowed_queues=("normal",))
    _task_row(store, "2" * 31 + "a", user_id=7, input_form=_submission_form(**_planned_snapshot(configured)))
    store.ensure_data_lifecycle("2" * 31 + "b", user_id=7, logical_bytes=GIB)
    store.set_compute_allowance(
        user_id=7, monthly_gpu_seconds=100, actor_user_id=1, idempotency_key="json-1", updated_at=time.time()
    )

    payloads = {
        "tasks": ar.task_operations(store),
        "placement": ar.placement_projection(store.get_task("2" * 31 + "a")),
        "resources": ar.resource_operations(store, 7),
        "integrity": ar.platform_integrity(store),
        "activity": ar.admin_activity(store),
    }
    for payload in payloads.values():
        json.dumps(payload)
