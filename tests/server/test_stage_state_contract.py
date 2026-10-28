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

    snapshots: list[tuple[str, dict]] = []

    def _snapshot(label: str) -> None:
        task = database.get_task(task_id)
        snapshots.append((label, task_runtime.stage_projection(task)))

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
    by_label: dict[str, list[tuple[str, dict]]] = {}
    for label, projection in snapshots:
        by_label.setdefault(label, []).append(projection)

    features_dispatched = by_label["dispatched"][0]
    assert features_dispatched["items"][0]["status"] == stage_state.QUEUED
    assert features_dispatched["items"][1]["status"] == stage_state.NOT_STARTED

    features_started = by_label["started"][0]
    assert features_started["items"][0]["status"] == stage_state.RUNNING
    # The allocation, not a stdout marker, made the Task running.
    assert database.get_task(task_id)["status"] == "running"

    model_dispatched = by_label["dispatched"][1]
    assert [item["status"] for item in model_dispatched["items"]] == [
        stage_state.COMPLETED,
        stage_state.QUEUED,
    ]
    # The regression this change removes: the Task must not fall back to queued
    # while its GPU stage waits.
    assert database.get_task(task_id)["status"] == "running"

    model_started = by_label["started"][1]
    assert model_started["current"]["name"] == "multistage_runner.model"
    assert model_started["current"]["status"] == stage_state.RUNNING

    final = task_runtime.stage_projection(database.get_task(task_id))
    assert final["source"] == "record"
    assert final["completed"] == final["total"] == 2
    assert final["current"] is None
    mirror = json.loads(database.get_task(task_id)["workflow_state"])
    assert [step["status"] for step in mirror.values()] == ["completed", "completed"]


def test_failed_attempt_uses_the_diagnostic_reason_and_rejects_late_completion(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "f" * 32
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)
    attempt = database.begin_stage_attempt(
        task_id=task_id, stage_index=0, stage_name="multistage_runner.model"
    )
    database.record_stage_running(task_id=task_id, stage_index=0, attempt=attempt["attempt"])
    database.record_task_diagnostics(task_id, {"reason_code": "timeout"})

    task_runtime._finish_stage_attempt(
        task_id, 0, attempt["attempt"], task_runtime.JobState.FAILED
    )

    run = database.list_stage_runs(task_id)[0]
    assert (run["status"], run["reason_code"]) == (stage_state.FAILED, "timeout")
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
    # The legacy stage carries no attempt evidence; the recorded one does.
    assert projection["items"][0]["attempt"] is None
    assert projection["items"][1]["attempt"] == model["attempt"]


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
