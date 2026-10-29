# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Durable stage-execution state: attempts, monotonicity, projection, recovery."""

from __future__ import annotations

from dataclasses import replace
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
            task_id=task_id, stage_name="features", attempt=1, slurm_job_id="4100"
        )
        assert database.record_stage_running(task_id=task_id, stage_name="features", attempt=1)
        assert database.finish_stage_attempt(
            task_id=task_id, stage_name="features", attempt=1, status=stage_state.COMPLETED,
            reason_code=stage_state.Reason.COMPLETED,
        )

        # Late/stale worker evidence cannot regress a settled attempt.
        assert not database.record_stage_running(task_id=task_id, stage_name="features", attempt=1)
        assert not database.finish_stage_attempt(
            task_id=task_id, stage_name="features", attempt=1, status=stage_state.FAILED
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
            task_id=task_id, stage_name="features", attempt=2, status=stage_state.INTERRUPTED,
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
    database.record_stage_running(
        task_id=task_id, stage_name="multistage_runner.model", attempt=attempt["attempt"]
    )
    # The Task-level diagnostics row belongs to whichever allocation wrote last;
    # it must not supply the reason for this attempt.
    database.record_task_diagnostics(task_id, {"reason_code": "timeout"})

    task_runtime._finish_stage_attempt(
        task_id, "multistage_runner.model", attempt["attempt"], task_runtime.JobState.FAILED,
        failure_reason="nonzero_exit",
    )

    run = database.list_stage_runs(task_id)[0]
    assert (run["status"], run["reason_code"]) == (stage_state.FAILED, "nonzero_exit")

    retry = database.begin_stage_attempt(
        task_id=task_id, stage_index=0, stage_name="multistage_runner.model"
    )
    task_runtime._finish_stage_attempt(
        task_id, "multistage_runner.model", retry["attempt"], task_runtime.JobState.FAILED
    )
    assert database.list_stage_runs(task_id)[-1]["reason_code"] == "allocation_failed"
    # A stale worker reporting completion afterwards cannot rewrite the record.
    assert not database.finish_stage_attempt(
        task_id=task_id, stage_name="multistage_runner.model", attempt=attempt["attempt"],
        status=stage_state.COMPLETED,
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
        task_id=task_id, stage_name="multistage_runner", attempt=attempt["attempt"]
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
        task_id=task_id, stage_name="multistage_runner.features", attempt=1,
        status=stage_state.COMPLETED, reason_code=stage_state.Reason.COMPLETED,
    )
    database.begin_stage_attempt(task_id=task_id, stage_index=1, stage_name="multistage_runner.model")
    database.record_stage_running(
        task_id=task_id, stage_name="multistage_runner.model", attempt=1
    )
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
        task_id=task_id, stage_name="cpu_runner", attempt=1, slurm_job_id="4100"
    )
    assert not database.record_stage_dispatched(
        task_id=task_id, stage_name="cpu_runner", attempt=1, slurm_job_id="4200"
    )
    assert database.list_stage_runs(task_id)[0]["slurm_job_id"] == "4100"


def test_finish_active_stage_runs_settles_every_live_attempt_and_no_terminal_one(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "4" * 32
    _insert_task(database, task_id)
    database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="a")
    database.record_stage_running(task_id=task_id, stage_name="a", attempt=1)
    database.begin_stage_attempt(task_id=task_id, stage_index=1, stage_name="b")
    database.begin_stage_attempt(task_id=task_id, stage_index=2, stage_name="c")
    database.finish_stage_attempt(
        task_id=task_id, stage_name="c", attempt=1, status=stage_state.COMPLETED,
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
        task_id=task_id, stage_name="cpu_runner", attempt=1, status=stage_state.COMPLETED,
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
        attempt=1,
    )

    callbacks[2]("77", time.time())


def test_an_unaccounted_run_reports_its_stage_running_when_the_scheduler_says_so(tmp_path, monkeypatch):
    """Stage RUNNING is driven by the allocation observation, not by billing.

    A live test Task has ``submitted_by_user_id=0`` and therefore no accounting
    subject.  It still holds an allocation, so the wrapper must observe the
    scheduler and report allocation-live while the command executes; only then
    does the StageRun become RUNNING.  With the observation behind the
    accounting gates it never happens, and the Task reads QUEUED for its whole
    run.
    """
    import hashlib
    import os
    import subprocess
    import threading

    from revocompute.job.runners.slurm_runner import SlurmJob
    from tests.test_slurm_runner import _fake_compute_node_bin

    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "5a" * 16
    _insert_task(database, task_id, status="queued", task_type="cpu_runner")
    monkeypatch.setattr(task_runtime, "task_store", database)
    attempt = database.begin_stage_attempt(
        task_id=task_id, stage_index=0, stage_name="cpu_runner"
    )
    callbacks = task_runtime._compute_allocation_callbacks(
        task_id=task_id,
        user_id=0,
        stage_id="cpu_runner",
        resource_policy=_policy(False),
        attempt=attempt["attempt"],
    )

    workspace = tmp_path / "workspace" / task_id
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True)
    input_path = inputs / "input.fasta"
    input_path.write_text(">test\nACDE\n", encoding="utf-8")
    entities = [{
        "name": "sequence",
        "type": "file",
        "value": "input.fasta",
        "snapshot_path": str(input_path),
        "snapshot_root": str(inputs),
        "hash": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "workspace_key": "owner-key",
    }]
    output_dir = tmp_path / "out"
    job = SlurmJob(
        task_id,
        _single_stage_type(),
        RunnerConfig(),
        entities,
        str(output_dir),
        resource_policy=_policy(False),
        allocation_dispatched_callback=callbacks[0],
        allocation_started_callback=callbacks[1],
        allocation_finished_callback=callbacks[2],
        allocation_accounting=False,
    )
    job._prepare_scratch_dir()

    started = tmp_path / "command-started"
    done = tmp_path / "command-done"
    fake_bin = _fake_compute_node_bin(tmp_path)
    apptainer = fake_bin / "apptainer"
    apptainer.write_text(
        '#!/bin/bash\n: > "${COMMAND_STARTED:?}"\nsleep 3\n: > "${COMMAND_DONE:?}"\n',
        encoding="utf-8",
    )
    apptainer.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SLURM_JOB_ID": "42",
        "SLURM_CPUS_PER_TASK": "1",
        "SLURM_NTASKS": "1",
        "COMMAND_STARTED": str(started),
        "COMMAND_DONE": str(done),
    }

    process = subprocess.Popen(
        ["bash"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=environment,
    )
    job._process = process
    process.stdin.write(job._render_wrapper())
    process.stdin.close()
    reader = threading.Thread(target=job._read_stdout, daemon=True)
    reader.start()

    deadline = time.monotonic() + 10
    while not started.is_file() and time.monotonic() < deadline:
        time.sleep(0.02)

    # The observation is the live allocation, so the stage is RUNNING while the
    # scientific command is still executing -- never from the post-exit fallback.
    assert started.is_file()
    run = database.list_stage_runs(task_id)[0]
    assert run["status"] == stage_state.RUNNING
    assert not done.is_file()
    assert process.poll() is None
    # Unaccounted means uncharged: no allocation fact and no ledger row exist.
    with database.engine.connect() as connection:
        for table in ("resource_ledger", "resource_allocations"):
            assert connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar() == 0

    reader.join(timeout=15)
    assert not reader.is_alive()
    assert process.wait(timeout=10) == 0


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
        task_id=task_id, stage_name="multistage_runner.model", attempt=model["attempt"],
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
    database.record_stage_running(task_id=task_id, stage_name="cpu_runner", attempt=attempt["attempt"])
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


def test_delete_then_resubmit_settles_the_old_attempt_and_keeps_its_history(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "c1" * 16
    _insert_task(database, task_id, status="queued")
    database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="cpu_runner")
    # The production deletion path is the cleanup claim; it settles the live
    # attempt instead of erasing it, so the history of the deleted lifecycle
    # stays truthful.
    assert database.claim_task_cleanup(
        task_id,
        expected_status="queued",
        expected_finished_at=None,
        claim_status="deleting:cancel",
    )
    assert database.list_stage_runs(task_id)[0]["status"] == stage_state.CANCELLED
    assert database.complete_task_cleanup(
        task_id, claim_status="deleting:cancel", cleaned_status="deleted:cancel"
    )

    _insert_task(database, task_id, status="queued")
    fresh = database.begin_stage_attempt(
        task_id=task_id, stage_index=0, stage_name="cpu_runner"
    )
    assert fresh is not None and fresh["attempt"] == 2
    assert [run["status"] for run in database.list_stage_runs(task_id)] == [
        stage_state.CANCELLED,
        stage_state.QUEUED,
    ]


def test_deleting_a_task_removes_its_stage_rows(tmp_path):
    """A row-level delete leaves no attempt for a re-submitted identical id."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "c2" * 16
    _insert_task(database, task_id, status="queued")
    database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="cpu_runner")
    assert database.list_stage_runs(task_id) != []

    database.delete_task(task_id)

    assert database.get_task(task_id) is None
    assert database.list_stage_runs(task_id) == []


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


def test_late_allocation_start_cannot_resurrect_a_settled_task(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    monkeypatch.setattr(task_runtime, "task_store", database)
    try:
        # Recovery interleaving: the old worker's "started" observation arrives
        # after recovery interrupted its attempt and reset the Task to pending.
        task_id = "2a" * 16
        _insert_task(database, task_id, status="pending")
        attempt = database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="model")
        database.finish_stage_attempt(
            task_id=task_id,
            stage_name="model",
            attempt=attempt["attempt"],
            status=stage_state.INTERRUPTED,
            reason_code=stage_state.Reason.WORKER_LOST,
        )
        callbacks = task_runtime._compute_allocation_callbacks(
            task_id=task_id,
            user_id=0,
            stage_id="model",
            resource_policy=None,
            attempt=attempt["attempt"],
        )
        callbacks[1]("403300", time.time())
        assert database.get_task(task_id)["status"] == "pending"
        assert database.list_stage_runs(task_id)[0]["status"] == stage_state.INTERRUPTED
        # The replacement worker's claim is still the only one that can win.
        assert database.claim_task_execution(task_id) is True

        # A late start must not move a failed Task back to running either.
        failed_id = "2b" * 16
        _insert_task(database, failed_id, status="running")
        failed_attempt = database.begin_stage_attempt(
            task_id=failed_id, stage_index=0, stage_name="model"
        )
        database.finish_stage_attempt(
            task_id=failed_id,
            stage_name="model",
            attempt=failed_attempt["attempt"],
            status=stage_state.FAILED,
            reason_code="nonzero_exit",
        )
        assert database.update_task(failed_id, status="failed") is True
        task_runtime._compute_allocation_callbacks(
            task_id=failed_id,
            user_id=0,
            stage_id="model",
            resource_policy=None,
            attempt=failed_attempt["attempt"],
        )[1]("403301", time.time())
        assert database.get_task(failed_id)["status"] == "failed"
    finally:
        database.engine.dispose()


def test_duplicate_allocation_start_is_idempotent_but_a_settled_attempt_is_rejected(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "2c" * 16
    _insert_task(database, task_id, status="queued")
    attempt = database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="model")
    try:
        assert database.record_stage_running(
            task_id=task_id, stage_name="model", attempt=attempt["attempt"]
        )
        # A duplicate observation of the same live allocation is accepted.
        assert database.record_stage_running(
            task_id=task_id, stage_name="model", attempt=attempt["attempt"]
        )
        database.finish_stage_attempt(
            task_id=task_id, stage_name="model", attempt=attempt["attempt"],
            status=stage_state.COMPLETED, reason_code=stage_state.Reason.COMPLETED,
        )
        assert not database.record_stage_running(
            task_id=task_id, stage_name="model", attempt=attempt["attempt"]
        )
    finally:
        database.engine.dispose()


def test_cleanup_settlement_rewrites_the_workflow_state_mirror(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "2d" * 16
    _insert_task(database, task_id, status="running")
    attempt = database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="model")
    database.record_stage_running(task_id=task_id, stage_name="model", attempt=attempt["attempt"])
    mirror = {"model": {"status": "running", "attempt": attempt["attempt"]}}
    database.update_task(task_id, workflow_state=json.dumps(mirror))
    try:
        assert database.claim_task_cleanup(
            task_id,
            expected_status="running",
            expected_finished_at=None,
            claim_status="deleting:cancel",
        )
        settled = database.list_stage_runs(task_id)[0]
        assert (settled["status"], settled["reason_code"]) == (
            stage_state.CANCELLED,
            stage_state.Reason.TASK_DELETED,
        )
        mirrored = json.loads(database.get_task(task_id)["workflow_state"])["model"]
        assert mirrored["status"] == "cancelled"
        assert mirrored["reason_code"] == stage_state.Reason.TASK_DELETED
    finally:
        database.engine.dispose()


def test_settled_tasks_cannot_begin_an_attempt(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    try:
        for status in ("finished", "failed", "cancelled"):
            task_id = (status[:2] + "0" * 30)[:32]
            _insert_task(database, task_id, status=status)
            assert database.begin_stage_attempt(
                task_id=task_id, stage_index=0, stage_name="model"
            ) is None
            assert database.list_stage_runs(task_id) == []

        active_id = "2f" * 16
        _insert_task(database, active_id, status="queued")
        active = database.begin_stage_attempt(
            task_id=active_id, stage_index=0, stage_name="model"
        )
        assert active is not None and active["attempt"] == 1
    finally:
        database.engine.dispose()


def test_reordered_manifest_resume_reuses_the_live_attempt_by_name(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "3a" * 16
    _insert_task(database, task_id, status="running")
    try:
        original = database.begin_stage_attempt(
            task_id=task_id, stage_index=1, stage_name="multistage_runner.model"
        )
        # The same manifest stage now sits at index 0 (an inserted/reordered
        # workflow): it must reuse the live attempt rather than open a second one.
        reused = database.begin_stage_attempt(
            task_id=task_id, stage_index=0, stage_name="multistage_runner.model"
        )
        assert reused["id"] == original["id"]
        assert (reused["attempt"], reused["stage_index"]) == (1, 1)
        live = [
            run for run in database.list_stage_runs(task_id)
            if run["status"] in stage_state.ACTIVE_STATUSES
        ]
        assert len(live) == 1

        # Transitions are keyed by the stage identity, which a reused attempt
        # keeps even though its manifest index moved.
        assert database.record_stage_dispatched(
            task_id=task_id, stage_name="multistage_runner.model", attempt=1, slurm_job_id="77"
        )
        assert database.record_stage_running(
            task_id=task_id, stage_name="multistage_runner.model", attempt=1
        )
        assert database.finish_stage_attempt(
            task_id=task_id, stage_name="multistage_runner.model", attempt=1,
            status=stage_state.COMPLETED, reason_code=stage_state.Reason.COMPLETED,
        )
        assert database.list_stage_runs(task_id)[0]["reason_code"] == stage_state.Reason.COMPLETED

        # A new attempt after a reorder advances the stage's attempt number, so
        # the newest record wins even though its index moved.
        next_attempt = database.begin_stage_attempt(
            task_id=task_id, stage_index=0, stage_name="multistage_runner.model"
        )
        assert (next_attempt["attempt"], next_attempt["stage_index"]) == (2, 0)
    finally:
        database.engine.dispose()


def test_failure_settlement_does_not_borrow_another_attempt_diagnostic_reason(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "3b" * 16
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(task_runtime, "_capture_debug_submission", lambda *args: None)
    monkeypatch.setattr(task_runtime, "_finalize_failed_results", lambda *args, **kwargs: None)
    monkeypatch.setattr(task_runtime, "_cleanup_task_workspace", lambda *args: None)
    attempt = database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name="model")
    database.record_task_diagnostics(task_id, {"reason_code": "timeout", "stage_id": "earlier-stage"})
    try:
        task_runtime._record_failure(task_id, database.get_task(task_id), 1.0, "model", "boom")
        run = database.list_stage_runs(task_id)[0]
        assert (run["status"], run["reason_code"]) == (stage_state.FAILED, "execution_exception")
        assert database.get_task(task_id)["status"] == "failed"
    finally:
        database.engine.dispose()


def test_stage_run_indexes_are_replaced_when_an_old_definition_exists(tmp_path):
    path = str(tmp_path / "tasks.sqlite3")
    database = TaskDatabase(path)
    database.engine.dispose()
    # Reproduce a database created by an earlier head of this branch: the
    # identity index is position-keyed and the live index is index-keyed.
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX idx_stage_runs_identity")
        conn.execute("DROP INDEX idx_stage_runs_live_name")
        conn.execute(
            "CREATE UNIQUE INDEX idx_stage_runs_task_stage_attempt "
            "ON stage_runs (task_id, stage_index, attempt)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX idx_stage_runs_live_stage ON stage_runs (task_id, stage_index) "
            "WHERE status IN ('QUEUED', 'RUNNING')"
        )
    repaired = TaskDatabase(path)
    try:
        with repaired.engine.connect() as conn:
            names = {
                row[0]
                for row in conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='stage_runs'"
                )
            }
            identity_columns = [
                row[2] for row in conn.exec_driver_sql("PRAGMA index_info('idx_stage_runs_identity')")
            ]
            live_columns = [
                row[2] for row in conn.exec_driver_sql("PRAGMA index_info('idx_stage_runs_live_name')")
            ]
        assert "idx_stage_runs_task_stage_attempt" not in names
        assert "idx_stage_runs_live_stage" not in names
        assert identity_columns == ["task_id", "stage_name", "attempt"]
        # The live-attempt constraint is keyed by stage name, so a reordered
        # manifest cannot open a second live attempt for one stage.
        assert live_columns == ["task_id", "stage_name"]
    finally:
        repaired.engine.dispose()


def test_reordered_never_run_stage_does_not_collide_with_another_stages_attempt(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "3c" * 16
    _insert_task(database, task_id, status="running")
    try:
        features = database.begin_stage_attempt(
            task_id=task_id, stage_index=0, stage_name="multistage_runner.features"
        )
        database.finish_stage_attempt(
            task_id=task_id, stage_name="multistage_runner.features", attempt=features["attempt"],
            status=stage_state.COMPLETED, reason_code=stage_state.Reason.COMPLETED,
        )
        # The model stage has never run and now occupies index 0, which already
        # holds the features attempt 1.  Identity is per stage name, so this
        # opens a record instead of failing a position-keyed unique constraint.
        model = database.begin_stage_attempt(
            task_id=task_id, stage_index=0, stage_name="multistage_runner.model"
        )
        assert model is not None
        assert (model["stage_index"], model["attempt"]) == (0, 1)
        rows = {(run["stage_name"], run["attempt"]) for run in database.list_stage_runs(task_id)}
        assert rows == {("multistage_runner.features", 1), ("multistage_runner.model", 1)}
    finally:
        database.engine.dispose()


def test_workflow_state_mirror_prefers_the_newest_attempt_after_a_reorder(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "3d" * 16
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)
    try:
        first = database.begin_stage_attempt(
            task_id=task_id, stage_index=2, stage_name="multistage_runner.model"
        )
        database.finish_stage_attempt(
            task_id=task_id, stage_name="multistage_runner.model", attempt=first["attempt"],
            status=stage_state.INTERRUPTED, reason_code=stage_state.Reason.WORKER_LOST,
        )
        # The retry sits at a lower manifest index; position must not make the
        # older attempt look newer.
        second = database.begin_stage_attempt(
            task_id=task_id, stage_index=0, stage_name="multistage_runner.model"
        )
        assert (second["attempt"], second["stage_index"]) == (2, 0)
        database.finish_stage_attempt(
            task_id=task_id, stage_name="multistage_runner.model", attempt=second["attempt"],
            status=stage_state.COMPLETED, reason_code=stage_state.Reason.COMPLETED,
        )

        projection = stage_state.workflow_state_projection(database.list_stage_runs(task_id))
        assert projection["multistage_runner.model"]["attempt"] == 2
        assert projection["multistage_runner.model"]["status"] == "completed"
        mirror = json.loads(task_runtime._mirror_json(task_id, {}))
        assert mirror["multistage_runner.model"]["attempt"] == 2
        assert mirror["multistage_runner.model"]["reason_code"] == stage_state.Reason.COMPLETED
    finally:
        database.engine.dispose()


def test_index_migration_reports_duplicate_live_attempts_and_keeps_the_old_indexes(tmp_path):
    path = str(tmp_path / "tasks.sqlite3")
    database = TaskDatabase(path)
    database.engine.dispose()
    task_id = "4a" * 16
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX idx_stage_runs_identity")
        conn.execute("DROP INDEX idx_stage_runs_live_name")
        conn.execute(
            "CREATE UNIQUE INDEX idx_stage_runs_task_stage_attempt "
            "ON stage_runs (task_id, stage_index, attempt)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX idx_stage_runs_live_stage ON stage_runs (task_id, stage_index) "
            "WHERE status IN ('QUEUED', 'RUNNING')"
        )
        now = time.time()
        for index in (0, 1):
            conn.execute(
                "INSERT INTO stage_runs "
                "(task_id, stage_index, stage_name, attempt, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task_id, index, "dup_stage", index + 1, stage_state.QUEUED, now, now),
            )

    with pytest.raises(RuntimeError) as failure:
        TaskDatabase(path)
    message = str(failure.value)
    assert task_id in message
    assert "dup_stage" in message
    assert "2 live attempts" in message
    assert "Resolve these duplicate stage_runs rows" in message

    # The failed migration rolled back to the indexes the database already had,
    # so it is not left without its stage-run constraints.
    with sqlite3.connect(path) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='stage_runs'"
            )
        }
        assert {"idx_stage_runs_task_stage_attempt", "idx_stage_runs_live_stage"} <= names
        assert "idx_stage_runs_identity" not in names
        assert "idx_stage_runs_live_name" not in names
        conn.execute(
            "DELETE FROM stage_runs WHERE task_id = ? AND stage_index = 1", (task_id,)
        )

    # Once the conflict is resolved, the same database opens and migrates.
    reopened = TaskDatabase(path)
    try:
        with reopened.engine.connect() as conn:
            names = {
                row[0]
                for row in conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='stage_runs'"
                )
            }
        assert {"idx_stage_runs_identity", "idx_stage_runs_live_name"} <= names
    finally:
        reopened.engine.dispose()


def test_projection_keeps_a_removed_stage_out_of_a_current_stages_index(tmp_path, monkeypatch):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "4b" * 16
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (_task_type(), None))
    try:
        features = database.begin_stage_attempt(
            task_id=task_id, stage_index=0, stage_name="multistage_runner.features"
        )
        database.finish_stage_attempt(
            task_id=task_id, stage_name="multistage_runner.features", attempt=features["attempt"],
            status=stage_state.COMPLETED, reason_code=stage_state.Reason.COMPLETED,
        )
        # A stage that left the manifest keeps the index it was recorded under,
        # which is now features' index; it must get a display position of its own.
        removed = database.begin_stage_attempt(
            task_id=task_id, stage_index=0, stage_name="retired_stage"
        )
        database.record_stage_running(
            task_id=task_id, stage_name="retired_stage", attempt=removed["attempt"]
        )
        database.begin_stage_attempt(
            task_id=task_id, stage_index=1, stage_name="multistage_runner.model"
        )

        projection = task_runtime.stage_projection(database.get_task(task_id))
        by_name = {item["name"]: item for item in projection["items"]}
        assert len(projection["items"]) == 3
        assert by_name["multistage_runner.features"]["status"] == stage_state.COMPLETED
        assert by_name["retired_stage"]["status"] == stage_state.RUNNING
        assert by_name["multistage_runner.model"]["status"] == stage_state.QUEUED
        assert by_name["retired_stage"]["index"] == 2
    finally:
        database.engine.dispose()


def test_projection_does_not_fabricate_stages_for_a_recorded_index_gap(tmp_path, monkeypatch):
    """A retired stage's stored index is a position, not a run of empty stages.

    A task with two declared stages whose only record is a retired stage at
    index 5 has three stages, not six: the unoccupied positions between the
    manifest and the record are not stages.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "4d" * 16
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (_task_type(), None))
    try:
        retired = database.begin_stage_attempt(
            task_id=task_id, stage_index=5, stage_name="retired_stage"
        )
        database.record_stage_running(
            task_id=task_id, stage_name="retired_stage", attempt=retired["attempt"]
        )

        projection = task_runtime.stage_projection(database.get_task(task_id))
        assert [item["name"] for item in projection["items"]] == [
            "multistage_runner.features",
            "multistage_runner.model",
            "retired_stage",
        ]
        assert [item["source"] for item in projection["items"]] == [
            "definition",
            "definition",
            "record",
        ]
        assert [item["status"] for item in projection["items"]] == [
            stage_state.NOT_STARTED,
            stage_state.NOT_STARTED,
            stage_state.RUNNING,
        ]
        assert projection["total"] == 3
        assert projection["current"]["name"] == "retired_stage"
    finally:
        database.engine.dispose()


def test_two_retired_stages_at_one_historical_index_get_distinct_positions(tmp_path, monkeypatch):
    """A retired stage that keeps its stored index still occupies that slot.

    Two stages removed from a manifest can both be recorded at the same
    historical index.  The first keeps the index, so the fallback for the second
    must start past it instead of handing out the same position and dropping one
    stage — the one that was running — from the projection.
    """
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "4c" * 16
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)
    declared = _task_type()
    monkeypatch.setattr(
        task_runtime,
        "_get_task_type",
        lambda name: (replace(declared, workflow=(declared.workflow[0],)), None),
    )
    try:
        first = database.begin_stage_attempt(
            task_id=task_id, stage_index=1, stage_name="retired_first"
        )
        database.finish_stage_attempt(
            task_id=task_id, stage_name="retired_first", attempt=first["attempt"],
            status=stage_state.COMPLETED, reason_code=stage_state.Reason.COMPLETED,
        )
        second = database.begin_stage_attempt(
            task_id=task_id, stage_index=1, stage_name="retired_second"
        )
        database.record_stage_running(
            task_id=task_id, stage_name="retired_second", attempt=second["attempt"]
        )

        projection = task_runtime.stage_projection(database.get_task(task_id))
        by_name = {item["name"]: item for item in projection["items"]}
        assert set(by_name) == {
            "multistage_runner.features", "retired_first", "retired_second",
        }
        assert by_name["retired_first"]["index"] != by_name["retired_second"]["index"]
        assert by_name["retired_second"]["status"] == stage_state.RUNNING
    finally:
        database.engine.dispose()
