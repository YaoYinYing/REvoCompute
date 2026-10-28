# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Durable stage-execution state: attempts, monotonicity, projection, recovery."""

from __future__ import annotations

import json
import sqlite3
import time

import pytest

from revocompute import stage_state
from revocompute import task_runtime
from revocompute.db import TaskDatabase
from revocompute.resource_policy import ResolvedResources
from revocompute.task_types import RunnerConfig, RuntimeFamily, TaskType, WorkflowStage


def _policy(requires_gpu: bool) -> ResolvedResources:
    return ResolvedResources(
        cpus=8,
        memory="16G",
        max_runtime_seconds=3600,
        partition="gpu" if requires_gpu else "cpu",
        gres="gpu:1" if requires_gpu else None,
        nodes=1,
        ntasks=1,
        qos=None,
        account=None,
        constraint=None,
        exclusive=False,
        requires_gpu=requires_gpu,
        sources={},
    )


def _task_type() -> TaskType:
    runtime = RuntimeFamily("multistage_runner", ("bash", "run.sh"), "runner.def", "image.sif")
    stages = (
        WorkflowStage("multistage_runner.features", "Features", False, ("-s", "features"), ("msa",)),
        WorkflowStage("multistage_runner.model", "Model", True, ("-s", "model"), ("model",)),
    )
    return TaskType(
        "multistage_runner",
        "Synthetic staged calculation",
        runtime,
        ".fasta",
        "FASTA",
        gpus=True,
        stage_markers={"msa": "MSA", "model": "Model"},
        workflow=stages,
    )


def _single_stage_type() -> TaskType:
    runtime = RuntimeFamily("cpu_runner", ("bash", "run.sh"), "runner.def", "image.sif")
    return TaskType(
        "cpu_runner",
        "Synthetic CPU runner",
        runtime,
        ".fasta",
        "FASTA",
        stage_markers={"execute": "Execute"},
    )


def _insert_task(database: TaskDatabase, task_id: str, *, status: str = "queued", **fields) -> None:
    database.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=time.time(),
        status=status,
        is_binary=0,
        task_type=fields.pop("task_type", "multistage_runner"),
        storage_key="owner-key",
        submitted_by_user_id=fields.pop("submitted_by_user_id", 0),
        **fields,
    )


def test_attempt_identity_is_exactly_once_and_transitions_are_monotonic(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    try:
        task_id = "a" * 32
        _insert_task(database, task_id)
        first = database.begin_stage_attempt(
            task_id=task_id, stage_index=0, stage_name="features", planned_resources={"cpus": 4}
        )
        duplicate = database.begin_stage_attempt(
            task_id=task_id, stage_index=0, stage_name="features", planned_resources={"cpus": 4}
        )
        assert (first["attempt"], duplicate["attempt"]) == (1, 1)
        assert duplicate["id"] == first["id"]

        assert database.record_stage_dispatched(
            task_id=task_id, stage_index=0, attempt=1, slurm_job_id="4100"
        )
        assert database.record_stage_running(task_id=task_id, stage_index=0, attempt=1)
        assert database.finish_stage_attempt(
            task_id=task_id, stage_index=0, attempt=1, status=stage_state.COMPLETED,
            reason_code=stage_state.Reason.COMPLETED,
        )

        # Late/stale worker evidence cannot regress a settled attempt.
        assert not database.record_stage_running(task_id=task_id, stage_index=0, attempt=1)
        assert not database.finish_stage_attempt(
            task_id=task_id, stage_index=0, attempt=1, status=stage_state.FAILED
        )
        recorded = database.list_stage_runs(task_id)
        assert [run["status"] for run in recorded] == [stage_state.COMPLETED]
        assert recorded[0]["reason_code"] == stage_state.Reason.COMPLETED

        # A retry after an interrupted attempt is a new attempt, never an edit.
        retry = database.begin_stage_attempt(
            task_id=task_id, stage_index=0, stage_name="features", planned_resources={"cpus": 4}
        )
        assert retry["attempt"] == 2
        database.finish_stage_attempt(
            task_id=task_id, stage_index=0, attempt=2, status=stage_state.INTERRUPTED,
            reason_code=stage_state.Reason.WORKER_LOST,
        )
        assert [run["attempt"] for run in database.list_stage_runs(task_id)] == [1, 2]
    finally:
        database.engine.dispose()


def test_workflow_keeps_task_running_while_the_next_stage_is_queued(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "b" * 32
    _insert_task(database, task_id)
    monkeypatch.setattr(task_runtime, "task_store", database)
    tt = _task_type()
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (tt, None))

    snapshots: list[tuple[str, dict, str]] = []

    def _snapshot(label: str) -> None:
        task = database.get_task(task_id)
        # Capture the Task status at this exact boundary, not after the whole
        # workflow has run: a per-stage `status="queued"` regression must fail.
        snapshots.append((label, task_runtime.stage_projection(task), task["status"]))

    class _Job:
        def __init__(self, callbacks):
            self.callbacks = callbacks

        def submit(self):
            dispatched, started, _finished = self.callbacks
            dispatched("42", time.time(), True)
            _snapshot("dispatched")
            started("42", time.time())
            _snapshot("started")
            return "42"

        def poll(self):
            _snapshot("poll")
            return task_runtime.JobState.COMPLETED

    def _create_job(_task_id, _tt, _runner, _entities, _output, stage_callback=None, **kwargs):
        del stage_callback
        return _Job(
            (
                kwargs["allocation_dispatched_callback"],
                kwargs["allocation_started_callback"],
                kwargs["allocation_finished_callback"],
            )
        )

    monkeypatch.setattr(task_runtime, "_create_job", _create_job)

    result = task_runtime._run_compute_workflow(
        task_id,
        database.get_task(task_id),
        tt,
        RunnerConfig(),
        [],
        str(tmp_path / "results"),
        {
            "multistage_runner.features": _policy(False),
            "multistage_runner.model": _policy(True),
        },
        lambda stage: None,
    )

    assert result == task_runtime.JobState.COMPLETED
    by_label: dict[str, list[tuple[dict, str]]] = {}
    for label, projection, status in snapshots:
        by_label.setdefault(label, []).append((projection, status))

    features_dispatched, features_dispatched_status = by_label["dispatched"][0]
    assert features_dispatched["items"][0]["status"] == stage_state.QUEUED
    assert features_dispatched["items"][1]["status"] == stage_state.NOT_STARTED
    assert features_dispatched_status == "queued"

    features_started, features_started_status = by_label["started"][0]
    assert features_started["items"][0]["status"] == stage_state.RUNNING
    # The allocation, not a stdout marker, made the Task running.
    assert features_started_status == "running"

    model_dispatched, model_dispatched_status = by_label["dispatched"][1]
    assert [item["status"] for item in model_dispatched["items"]] == [
        stage_state.COMPLETED,
        stage_state.QUEUED,
    ]
    # The regression this change removes: at the moment the GPU stage is queued
    # (before its allocation starts), the Task is still running.
    assert model_dispatched_status == "running"

    model_started, model_started_status = by_label["started"][1]
    assert model_started["current"]["name"] == "multistage_runner.model"
    assert model_started["current"]["status"] == stage_state.RUNNING
    assert model_started_status == "running"

    final = task_runtime.stage_projection(database.get_task(task_id))
    assert final["source"] == "record"
    assert final["completed"] == final["total"] == 2
    assert final["current"] is None
    mirror = json.loads(database.get_task(task_id)["workflow_state"])
    assert [step["status"] for step in mirror.values()] == ["completed", "completed"]


def test_failed_attempt_uses_the_adapter_reason_and_never_another_attempt_evidence(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "f" * 32
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)
    attempt = database.begin_stage_attempt(
        task_id=task_id, stage_index=0, stage_name="multistage_runner.model"
    )
    database.record_stage_running(task_id=task_id, stage_index=0, attempt=attempt["attempt"])
    # The Task-level diagnostics row belongs to whichever allocation wrote last;
    # it must not supply the reason for this attempt.
    database.record_task_diagnostics(task_id, {"reason_code": "timeout"})

    task_runtime._finish_stage_attempt(
        task_id, 0, attempt["attempt"], task_runtime.JobState.FAILED, failure_reason="nonzero_exit"
    )

    run = database.list_stage_runs(task_id)[0]
    assert (run["status"], run["reason_code"]) == (stage_state.FAILED, "nonzero_exit")

    retry = database.begin_stage_attempt(
        task_id=task_id, stage_index=0, stage_name="multistage_runner.model"
    )
    task_runtime._finish_stage_attempt(task_id, 0, retry["attempt"], task_runtime.JobState.FAILED)
    assert database.list_stage_runs(task_id)[-1]["reason_code"] == "allocation_failed"
    # A stale worker reporting completion afterwards cannot rewrite the record.
    assert not database.finish_stage_attempt(
        task_id=task_id, stage_index=0, attempt=attempt["attempt"], status=stage_state.COMPLETED
    )


def test_failed_stage_stops_the_workflow_before_the_next_allocation(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "1" * 32
    _insert_task(database, task_id)
    monkeypatch.setattr(task_runtime, "task_store", database)
    tt = _task_type()
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (tt, None))
    created: list[str] = []

    class _FailingJob:
        def __init__(self, callbacks):
            self.callbacks = callbacks

        def submit(self):
            self.callbacks[0]("42", time.time(), True)
            self.callbacks[1]("42", time.time())
            return "42"

        def poll(self):
            return task_runtime.JobState.FAILED

    def _create_job(_task_id, _tt, _runner, _entities, _output, stage_callback=None, **kwargs):
        del stage_callback
        created.append(_tt.name)
        return _FailingJob(
            (
                kwargs["allocation_dispatched_callback"],
                kwargs["allocation_started_callback"],
                kwargs["allocation_finished_callback"],
            )
        )

    monkeypatch.setattr(task_runtime, "_create_job", _create_job)

    result = task_runtime._run_compute_workflow(
        task_id,
        database.get_task(task_id),
        tt,
        RunnerConfig(),
        [],
        str(tmp_path / "results"),
        {
            "multistage_runner.features": _policy(False),
            "multistage_runner.model": _policy(True),
        },
        lambda stage: None,
    )

    assert result == task_runtime.JobState.FAILED
    assert created == ["multistage_runner-features"]
    assert [(run["stage_index"], run["status"]) for run in database.list_stage_runs(task_id)] == [
        (0, stage_state.FAILED)
    ]
    mirror = json.loads(database.get_task(task_id)["workflow_state"])
    assert mirror["multistage_runner.features"]["status"] == "failed"


def test_cancellation_settles_live_attempt_and_rejects_late_running(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "c" * 32
    _insert_task(database, task_id)
    monkeypatch.setattr(task_runtime, "task_store", database)
    attempt = database.begin_stage_attempt(
        task_id=task_id, stage_index=0, stage_name="multistage_runner", planned_resources=None
    )

    assert database.claim_task_cancellation(task_id, finished_at=time.time()) is True
    runs = database.list_stage_runs(task_id)
    assert runs[0]["status"] == stage_state.CANCELLED
    assert runs[0]["reason_code"] == stage_state.Reason.TASK_CANCELLED
    # The compatibility mirror is rewritten at the cancellation boundary too.
    mirror = json.loads(database.get_task(task_id)["workflow_state"])
    assert mirror["multistage_runner"]["status"] == "cancelled"
    # A worker that still reports its allocation must not resurrect the attempt.
    assert not database.record_stage_running(
        task_id=task_id, stage_index=0, attempt=attempt["attempt"]
    )


def test_worker_loss_interrupts_the_live_attempt_and_resume_uses_a_new_attempt(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "d" * 32
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(
        task_runtime, "_get_task_type", lambda name: (_task_type(), None)
    )
    database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="multistage_runner.features")
    database.finish_stage_attempt(
        task_id=task_id, stage_index=0, attempt=1, status=stage_state.COMPLETED,
        reason_code=stage_state.Reason.COMPLETED,
    )
    database.begin_stage_attempt(task_id=task_id, stage_index=1, stage_name="multistage_runner.model")
    database.record_stage_running(task_id=task_id, stage_index=1, attempt=1)
    monkeypatch.setattr(
        task_runtime, "_stop_orphaned_workflow_execution", lambda *args: ""
    )
    monkeypatch.setattr(
        task_runtime.run_compute_task, "apply_async", lambda *args, **kwargs: type("Q", (), {"id": "replacement"})()
    )

    assert task_runtime._recover_orphaned_tasks() == 1
    runs = database.list_stage_runs(task_id)
    assert [(run["stage_index"], run["status"]) for run in runs] == [
        (0, stage_state.COMPLETED),
        (1, stage_state.INTERRUPTED),
    ]
    mirror = json.loads(database.get_task(task_id)["workflow_state"])
    assert mirror["multistage_runner.features"]["status"] == "completed"
    assert mirror["multistage_runner.model"]["status"] == "interrupted"

    # Resuming the workflow starts a second attempt of the interrupted stage and
    # leaves the completed one alone.
    resumed = database.begin_stage_attempt(
        task_id=task_id, stage_index=1, stage_name="multistage_runner.model"
    )
    assert resumed["attempt"] == 2


def test_duplicate_dispatch_cannot_rewrite_the_attempt_handle(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "3" * 32
    _insert_task(database, task_id)
    database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="cpu_runner")
    assert database.record_stage_dispatched(
        task_id=task_id, stage_index=0, attempt=1, slurm_job_id="4100"
    )
    assert not database.record_stage_dispatched(
        task_id=task_id, stage_index=0, attempt=1, slurm_job_id="4200"
    )
    assert database.list_stage_runs(task_id)[0]["slurm_job_id"] == "4100"


def test_finish_active_stage_runs_settles_every_live_attempt_and_no_terminal_one(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "4" * 32
    _insert_task(database, task_id)
    database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="a")
    database.record_stage_running(task_id=task_id, stage_index=0, attempt=1)
    database.begin_stage_attempt(task_id=task_id, stage_index=1, stage_name="b")
    database.begin_stage_attempt(task_id=task_id, stage_index=2, stage_name="c")
    database.finish_stage_attempt(
        task_id=task_id, stage_index=2, attempt=1, status=stage_state.COMPLETED,
        reason_code=stage_state.Reason.COMPLETED,
    )

    assert database.finish_active_stage_runs(
        task_id, status=stage_state.INTERRUPTED, reason_code=stage_state.Reason.WORKER_LOST
    ) == 2
    assert [(run["stage_index"], run["status"]) for run in database.list_stage_runs(task_id)] == [
        (0, stage_state.INTERRUPTED),
        (1, stage_state.INTERRUPTED),
        (2, stage_state.COMPLETED),
    ]


def test_an_attempt_whose_start_was_missed_can_still_complete(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "5" * 32
    _insert_task(database, task_id)
    database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="cpu_runner")
    assert database.finish_stage_attempt(
        task_id=task_id, stage_index=0, attempt=1, status=stage_state.COMPLETED,
        reason_code=stage_state.Reason.COMPLETED,
    )
    assert database.list_stage_runs(task_id)[0]["status"] == stage_state.COMPLETED


def test_deleting_a_task_settles_its_live_attempt(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "6" * 32
    _insert_task(database, task_id, status="queued")
    database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="cpu_runner")

    assert database.claim_task_cleanup(
        task_id,
        expected_status="queued",
        expected_finished_at=None,
        claim_status="deleting:cancel",
    )
    run = database.list_stage_runs(task_id)[0]
    assert (run["status"], run["reason_code"]) == (
        stage_state.CANCELLED,
        stage_state.Reason.TASK_DELETED,
    )


def test_cancellation_during_submission_settles_the_attempt(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "7" * 32
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)

    class _CancelledJob:
        def submit(self):
            database.claim_task_cancellation(task_id, finished_at=time.time())
            raise RuntimeError("task was cancelled during submission")

    monkeypatch.setattr(task_runtime, "_create_job", lambda *args, **kwargs: _CancelledJob())

    with pytest.raises(RuntimeError):
        task_runtime._run_compute_job(
            task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
            resource_policy=_policy(False),
        )

    run = database.list_stage_runs(task_id)[0]
    assert (run["status"], run["reason_code"]) == (
        stage_state.CANCELLED,
        stage_state.Reason.TASK_CANCELLED,
    )


def test_single_stage_job_records_its_lifecycle_through_the_allocation_boundary(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "8" * 32
    _insert_task(database, task_id, status="queued", task_type="cpu_runner")
    monkeypatch.setattr(task_runtime, "task_store", database)
    observed: list[str] = []

    class _Job:
        def __init__(self, callbacks):
            self.callbacks = callbacks

        def submit(self):
            self.callbacks[0]("77", time.time(), True)
            observed.append(database.get_task(task_id)["status"])
            self.callbacks[1]("77", time.time())
            observed.append(database.get_task(task_id)["status"])
            return "77"

        def poll(self):
            return task_runtime.JobState.COMPLETED

    captured: dict = {}

    def _create_job(*args, **kwargs):
        captured.update(kwargs)
        return _Job(
            (
                kwargs["allocation_dispatched_callback"],
                kwargs["allocation_started_callback"],
                kwargs["allocation_finished_callback"],
            )
        )

    monkeypatch.setattr(task_runtime, "_create_job", _create_job)

    state = task_runtime._run_compute_job(
        task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
        resource_policy=_policy(False),
    )

    assert state == task_runtime.JobState.COMPLETED
    # Callback presence is not the accounting decision: this Task has no
    # accounting subject, so the adapter must not open the grant gates.
    assert captured["allocation_accounting"] is False
    assert observed == ["queued", "running"]
    run = database.list_stage_runs(task_id)[0]
    assert (run["stage_index"], run["attempt"], run["status"], run["slurm_job_id"]) == (
        0, 1, stage_state.COMPLETED, "77",
    )
    assert run["started_at"] is not None and run["ended_at"] is not None


def test_unaccounted_callbacks_never_settle_an_allocation(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(
        database, "settle_allocation", lambda *args, **kwargs: pytest.fail("must not settle")
    )
    callbacks = task_runtime._compute_allocation_callbacks(
        task_id="9" * 32,
        user_id=0,
        stage_id="cpu_runner",
        resource_policy=_policy(False),
        stage_index=0,
        attempt=1,
    )

    callbacks[2]("77", time.time())


def test_projection_keeps_a_legacy_stage_that_predates_the_later_record(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "2" * 32
    _insert_task(
        database,
        task_id,
        status="running",
        workflow_state=json.dumps(
            {"multistage_runner.features": {"status": "completed", "job_id": "41"}}
        ),
    )
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (_task_type(), None))
    model = database.begin_stage_attempt(
        task_id=task_id, stage_index=1, stage_name="multistage_runner.model"
    )
    database.finish_stage_attempt(
        task_id=task_id, stage_index=1, attempt=model["attempt"],
        status=stage_state.COMPLETED, reason_code=stage_state.Reason.COMPLETED,
    )

    projection = task_runtime.stage_projection(database.get_task(task_id))
    assert projection["source"] == "record"
    assert [item["status"] for item in projection["items"]] == [
        stage_state.COMPLETED,
        stage_state.COMPLETED,
    ]
    # The legacy stage carries no attempt evidence; the recorded one does, and
    # each item names where its evidence came from.
    assert projection["items"][0]["attempt"] is None
    assert projection["items"][0]["source"] == "legacy"
    assert projection["items"][1]["attempt"] == model["attempt"]
    assert projection["items"][1]["source"] == "record"


def test_single_stage_worker_loss_interrupts_its_attempt(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "0" * 32
    _insert_task(
        database, task_id, status="running", task_type="cpu_runner", slurm_job_id="4154"
    )
    attempt = database.begin_stage_attempt(
        task_id=task_id, stage_index=0, stage_name="cpu_runner"
    )
    database.record_stage_running(task_id=task_id, stage_index=0, attempt=attempt["attempt"])
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (_single_stage_type(), None))
    monkeypatch.setattr(task_runtime.shutil, "which", lambda command: None)
    monkeypatch.setattr(task_runtime, "_record_failure", lambda *args, **kwargs: None)

    assert task_runtime._recover_orphaned_tasks() == 1

    run = database.list_stage_runs(task_id)[0]
    assert (run["status"], run["reason_code"]) == (
        stage_state.INTERRUPTED,
        stage_state.Reason.WORKER_LOST,
    )


def test_a_terminal_task_cannot_acquire_a_live_attempt(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "a1" * 16
    _insert_task(database, task_id, status="cancelled")

    assert database.begin_stage_attempt(
        task_id=task_id, stage_index=0, stage_name="cpu_runner"
    ) is None
    assert database.list_stage_runs(task_id) == []
    # A missing row is equally ineligible.
    assert database.begin_stage_attempt(
        task_id="b1" * 16, stage_index=0, stage_name="cpu_runner"
    ) is None


def test_delete_then_resubmit_starts_a_fresh_attempt(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "c1" * 16
    _insert_task(database, task_id, status="queued")
    database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="cpu_runner")
    database.delete_task(task_id)
    assert database.list_stage_runs(task_id) == []

    _insert_task(database, task_id, status="queued")
    fresh = database.begin_stage_attempt(
        task_id=task_id, stage_index=0, stage_name="cpu_runner"
    )
    assert fresh is not None and fresh["attempt"] == 1


def test_a_cancelled_single_stage_task_cannot_acquire_an_attempt(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "d1" * 16
    _insert_task(database, task_id, status="cancelled", task_type="cpu_runner")
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(
        task_runtime, "_create_job", lambda *args, **kwargs: pytest.fail("must not submit")
    )

    assert task_runtime._run_compute_job(
        task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out")
    ) == task_runtime.JobState.CANCELLED
    assert database.list_stage_runs(task_id) == []


def test_legacy_projection_is_labelled_and_historical_rows_survive_migration(tmp_path, monkeypatch):
    path = tmp_path / "tasks.sqlite3"
    database = TaskDatabase(str(path))
    task_id = "e" * 32
    _insert_task(
        database,
        task_id,
        status="running",
        workflow_state=json.dumps(
            {
                "multistage_runner.features": {"status": "completed", "job_id": "41"},
                "multistage_runner.model": {"status": "running", "job_id": "42"},
            }
        ),
    )
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (_task_type(), None))

    projection = task_runtime.stage_projection(database.get_task(task_id))
    assert projection["source"] == "legacy"
    assert [item["status"] for item in projection["items"]] == [
        stage_state.COMPLETED,
        stage_state.RUNNING,
    ]
    assert [item["source"] for item in projection["items"]] == ["legacy", "legacy"]
    assert projection["current"]["name"] == "multistage_runner.model"
    database.engine.dispose()

    # A database that predates the table gains it on open without touching the
    # Task row, and its historical Task is still reported from the mirror.
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE stage_runs")
    reopened = TaskDatabase(str(path))
    try:
        assert reopened.get_task(task_id)["status"] == "running"
        assert reopened.list_stage_runs(task_id) == []
        monkeypatch.setattr(task_runtime, "task_store", reopened)
        assert task_runtime.stage_projection(reopened.get_task(task_id))["source"] == "legacy"
    finally:
        reopened.engine.dispose()
