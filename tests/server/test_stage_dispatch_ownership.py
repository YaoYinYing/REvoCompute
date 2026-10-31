# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""One live StageAttempt yields exactly one scheduler launch.

A StageRun row is reused by a repeated dispatch, so row uniqueness alone cannot
prove one allocation.  These tests drive the real ``task_runtime`` dispatch
paths against a real ``TaskDatabase`` and count scheduler submissions.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace

import pytest

from revocompute import stage_state, task_runtime
from revocompute.db import TaskDatabase
from revocompute.execution_graph import compile_graph
from revocompute.resource_policy import ResolvedResources
from revocompute.task_types import RunnerConfig, RuntimeFamily, TaskType, WorkflowStage

STAGE = "cpu_runner"


def _policy() -> ResolvedResources:
    return ResolvedResources(
        cpus=2,
        memory="4G",
        max_runtime_seconds=60,
        partition="cpu",
        gres=None,
        nodes=1,
        ntasks=1,
        qos=None,
        account=None,
        constraint=None,
        exclusive=False,
        requires_gpu=False,
        sources={},
    )


def _runtime() -> RuntimeFamily:
    return RuntimeFamily(STAGE, ("bash", "run.sh"), "runner.def", "image.sif")


def _single_stage_type() -> TaskType:
    return TaskType(
        STAGE, "Synthetic CPU runner", _runtime(), (), stage_markers={"execute": "Execute"},
    )


def _workflow_type() -> TaskType:
    """A one-stage workflow whose stage identity equals the single-stage name."""
    stage = WorkflowStage(STAGE, "Execute", False, (), ("execute",))
    return TaskType(
        STAGE, "Synthetic workflow", _runtime(), (),
        stage_markers={"execute": "Execute"}, workflow=(stage,),
    )


def _insert_task(database: TaskDatabase, task_id: str, *, status: str = "queued") -> None:
    database.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=time.time(),
        status=status,
        is_binary=0,
        task_type=STAGE,
        storage_key="owner-key",
        submitted_by_user_id=0,
    )


def _freeze(database: TaskDatabase, task_id: str, task_type: TaskType) -> None:
    graph = compile_graph(task_type)
    database.update_task(
        task_id,
        input_form=json.dumps({
            "execution_graph": {
                "ir_version": graph.ir_version, "digest": graph.digest, "document": graph.document,
            },
        }),
    )


class _RecordingJob:
    """A job that counts submissions and records its handle like the adapter."""

    def __init__(self, job_id: str, callbacks, submissions: list[str]) -> None:
        self._job_id = job_id
        self._callbacks = callbacks
        self._submissions = submissions

    def submit(self) -> str:
        self._submissions.append(self._job_id)
        self._callbacks[0](self._job_id, time.time(), False)
        return self._job_id

    def poll(self):
        return task_runtime.JobState.COMPLETED


def _job_factory(submissions: list[str]):
    def _create(*_args, **kwargs):
        job_id = f"70{len(submissions) + 1:02d}"
        return _RecordingJob(job_id, (kwargs["allocation_dispatched_callback"],), submissions)

    return _create


def test_concurrent_workflow_and_single_stage_dispatch_submit_once(tmp_path, monkeypatch):
    """(a) One attempt, one srun: the second dispatch fails closed before submit."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "a1" * 16
    _insert_task(database, task_id)
    workflow_type = _workflow_type()
    _freeze(database, task_id, workflow_type)
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(task_runtime, "_get_family", lambda _family: (workflow_type.runtime, RunnerConfig()))

    submissions: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    class _BlockingJob(_RecordingJob):
        def submit(self):
            submissions.append(self._job_id)
            entered.set()
            assert release.wait(10), "single-stage worker was never released"
            self._callbacks[0](self._job_id, time.time(), False)
            return self._job_id

    def _create(*_args, **kwargs):
        return _BlockingJob("7001", (kwargs["allocation_dispatched_callback"],), submissions)

    monkeypatch.setattr(task_runtime, "_create_job", _create)

    worker_errors: list[Exception] = []

    def _single_stage_worker():
        try:
            task_runtime._run_compute_job(
                task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
                resource_policy=_policy(),
            )
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            worker_errors.append(exc)

    worker = threading.Thread(target=_single_stage_worker)
    worker.start()
    try:
        assert entered.wait(10), "single-stage worker never submitted"
        # The attempt is QUEUED, claimed, and has no recorded job id yet.  The
        # workflow dispatch of the same stage must not create a second srun.
        with pytest.raises(task_runtime.StageDispatchConflict):
            task_runtime._run_compute_workflow(
                task_id,
                database.get_task(task_id),
                workflow_type,
                [],
                str(tmp_path / "out"),
                {STAGE: _policy()},
                lambda _stage: None,
            )
    finally:
        release.set()
        worker.join(10)

    assert not worker.is_alive()
    assert worker_errors == []
    assert submissions == ["7001"]
    runs = database.list_stage_runs(task_id)
    assert len(runs) == 1
    assert (runs[0]["attempt"], runs[0]["slurm_job_id"], runs[0]["status"]) == (
        1, "7001", stage_state.COMPLETED,
    )
    assert runs[0]["dispatch_claim"]


def test_reentry_with_a_recorded_handle_never_submits_again(tmp_path, monkeypatch):
    """(b) The recorded allocation is observed, never replaced."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "b1" * 16
    _insert_task(database, task_id)
    database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name=STAGE)
    assert database.record_stage_dispatched(
        task_id=task_id, stage_name=STAGE, attempt=1, slurm_job_id="4100"
    )
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(
        task_runtime, "_create_job", lambda *_args, **_kwargs: pytest.fail("must not submit")
    )

    with pytest.raises(task_runtime.StageDispatchConflict) as conflict:
        task_runtime._run_compute_job(
            task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
            resource_policy=_policy(),
        )

    assert "4100" in str(conflict.value)
    run = database.list_stage_runs(task_id)[0]
    assert (run["slurm_job_id"], run["status"]) == ("4100", stage_state.QUEUED)
    assert run["dispatch_claim"] is None


def test_a_claimed_attempt_without_a_handle_fails_closed(tmp_path, monkeypatch):
    """(c) A dead claimant before scheduler acceptance starts no replacement."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "c1" * 16
    _insert_task(database, task_id)
    database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name=STAGE)
    assert database.claim_stage_dispatch(
        task_id=task_id, stage_name=STAGE, attempt=1, claim_id="dead-worker"
    )
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(
        task_runtime, "_create_job", lambda *_args, **_kwargs: pytest.fail("must not submit")
    )

    def _dispatch():
        task_runtime._run_compute_job(
            task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
            resource_policy=_policy(),
        )

    with pytest.raises(task_runtime.StageDispatchConflict):
        _dispatch()

    run = database.list_stage_runs(task_id)[0]
    # Not settled: the claimant may have started an allocation the new caller
    # cannot identify, so the attempt stays live for reconciliation.
    assert (run["status"], run["slurm_job_id"], run["dispatch_claim"]) == (
        stage_state.QUEUED, None, "dead-worker",
    )


def test_a_lost_submission_response_keeps_the_allocation_and_blocks_a_retry(tmp_path, monkeypatch):
    """(c) A request accepted before the response was lost is never duplicated."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "c2" * 16
    _insert_task(database, task_id)
    monkeypatch.setattr(task_runtime, "task_store", database)

    class _LostResponseJob:
        def __init__(self, callback):
            self._callback = callback

        def submit(self):
            # The scheduler accepted the request and the handle was recorded;
            # only the caller's response was lost.
            self._callback("9001", time.time(), False)
            raise RuntimeError("connection lost after scheduler acceptance")

        def poll(self):  # pragma: no cover - never reached
            raise AssertionError("poll must not be reached")

    monkeypatch.setattr(
        task_runtime, "_create_job",
        lambda *_args, **kwargs: _LostResponseJob(kwargs["allocation_dispatched_callback"]),
    )
    # The cancellation cannot be proven, so the Task must keep the handle and
    # stay running instead of failing the attempt and abandoning the job.
    cancelled: list[str] = []
    monkeypatch.setattr(
        task_runtime, "_cancel_recorded_allocation", lambda handle: cancelled.append(handle) or False
    )

    with pytest.raises(task_runtime.AllocationUnconfirmed, match="could not be cancelled"):
        task_runtime._run_compute_job(
            task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
            resource_policy=_policy(),
        )

    assert cancelled == ["9001"]
    run = database.list_stage_runs(task_id)[0]
    assert (run["status"], run["slurm_job_id"]) == (stage_state.QUEUED, "9001")
    task = database.get_task(task_id)
    assert (task["status"], task["slurm_job_id"]) == ("running", "9001")

    # A redelivery observes the recorded allocation and starts no second srun.
    monkeypatch.setattr(
        task_runtime, "_create_job", lambda *_args, **_kwargs: pytest.fail("must not submit")
    )
    with pytest.raises(task_runtime.StageDispatchConflict) as conflict:
        task_runtime._run_compute_job(
            task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
            resource_policy=_policy(),
        )
    assert "9001" in str(conflict.value)
    assert database.list_stage_runs(task_id)[0]["slurm_job_id"] == "9001"


def test_a_confirmed_cancellation_settles_the_lost_response_attempt(tmp_path, monkeypatch):
    """(c) Once the orphaned allocation is cancelled, the attempt may settle."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "c4" * 16
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)

    class _LostResponseJob:
        def __init__(self, callback):
            self._callback = callback

        def submit(self):
            self._callback("9002", time.time(), False)
            raise RuntimeError("connection lost after scheduler acceptance")

        def poll(self):  # pragma: no cover - never reached
            raise AssertionError("poll must not be reached")

    monkeypatch.setattr(
        task_runtime, "_create_job",
        lambda *_args, **kwargs: _LostResponseJob(kwargs["allocation_dispatched_callback"]),
    )
    monkeypatch.setattr(task_runtime, "_cancel_recorded_allocation", lambda _handle: True)

    with pytest.raises(RuntimeError, match="connection lost"):
        task_runtime._run_compute_job(
            task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
            resource_policy=_policy(),
        )

    run = database.list_stage_runs(task_id)[0]
    assert (run["status"], run["slurm_job_id"]) == (stage_state.FAILED, "9002")


def test_an_unreadable_attempt_never_fails_the_task_over_an_allocation(tmp_path, monkeypatch):
    """(c) A read outage is treated as unconfirmed, not as a failed Task."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "c8" * 16
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)

    class _NeverSubmitted:
        def submit(self):
            raise RuntimeError("connection lost before submission")

        def poll(self):  # pragma: no cover - never reached
            raise AssertionError("poll must not be reached")

    monkeypatch.setattr(task_runtime, "_create_job", lambda *_args, **_kwargs: _NeverSubmitted())

    def _unreadable(_task_id):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(database, "list_stage_runs", _unreadable)

    with pytest.raises(task_runtime.AllocationUnconfirmed, match="could not be verified"):
        task_runtime._run_compute_job(
            task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
            resource_policy=_policy(),
        )

    assert database.get_task(task_id)["status"] == "running"


def test_a_bookkeeping_outage_does_not_mask_the_unconfirmed_allocation(tmp_path, monkeypatch):
    """(c) The Task-running signal survives a failed handle write."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "c9" * 16
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)

    class _LostResponseJob:
        def __init__(self, callback):
            self._callback = callback

        def submit(self):
            self._callback("9004", time.time(), False)
            raise RuntimeError("connection lost after scheduler acceptance")

        def poll(self):  # pragma: no cover - never reached
            raise AssertionError("poll must not be reached")

    monkeypatch.setattr(
        task_runtime, "_create_job",
        lambda *_args, **kwargs: _LostResponseJob(kwargs["allocation_dispatched_callback"]),
    )
    monkeypatch.setattr(task_runtime, "_cancel_recorded_allocation", lambda _handle: False)
    real_update = database.update_task

    def _write_raises(_task_id, **fields):
        if "Submission did not confirm" in str(fields.get("error", "")):
            raise RuntimeError("database write failed")
        return real_update(_task_id, **fields)

    monkeypatch.setattr(database, "update_task", _write_raises)

    with pytest.raises(task_runtime.AllocationUnconfirmed):
        task_runtime._run_compute_job(
            task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
            resource_policy=_policy(),
        )


def test_an_unrecorded_allocation_after_submit_failure_keeps_the_launch_gate(tmp_path, monkeypatch):
    """(c) srun started but its identity was lost: never settle, never retry."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "e1" * 16
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)

    job = task_runtime.SlurmJob(
        task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out")
    )
    job._process = object()
    job.submit = lambda: (_ for _ in ()).throw(RuntimeError("response lost after srun"))
    monkeypatch.setattr(task_runtime, "_create_job", lambda *_args, **_kwargs: job)

    with pytest.raises(task_runtime.AllocationUnconfirmed, match="without recording its identity"):
        task_runtime._run_compute_job(
            task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
            resource_policy=_policy(),
        )

    run = database.list_stage_runs(task_id)[0]
    assert (run["status"], run["slurm_job_id"], bool(run["dispatch_claim"])) == (
        stage_state.QUEUED, None, True,
    )
    assert database.get_task(task_id)["status"] == "running"

    # A redelivery observes the live claim and starts no second srun.
    monkeypatch.setattr(
        task_runtime, "_create_job", lambda *_args, **_kwargs: pytest.fail("must not submit")
    )
    with pytest.raises(task_runtime.StageDispatchConflict):
        task_runtime._run_compute_job(
            task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
            resource_policy=_policy(),
        )


def test_a_workflow_stage_keeps_the_gate_when_its_process_started(tmp_path, monkeypatch):
    """The composed path takes the same decision for an unrecorded allocation."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "e2" * 16
    _insert_task(database, task_id)
    workflow_type = _workflow_type()
    _freeze(database, task_id, workflow_type)
    monkeypatch.setattr(task_runtime, "task_store", database)
    monkeypatch.setattr(task_runtime, "_get_family", lambda _family: (workflow_type.runtime, RunnerConfig()))

    job = task_runtime.SlurmJob(
        task_id, workflow_type, RunnerConfig(), [], str(tmp_path / "out")
    )
    job._process = object()
    job.submit = lambda: (_ for _ in ()).throw(RuntimeError("response lost after srun"))
    monkeypatch.setattr(task_runtime, "_create_job", lambda *_args, **_kwargs: job)

    with pytest.raises(task_runtime.AllocationUnconfirmed, match="without recording its identity"):
        task_runtime._run_compute_workflow(
            task_id,
            database.get_task(task_id),
            workflow_type,
            [],
            str(tmp_path / "out"),
            {STAGE: _policy()},
            lambda _stage: None,
        )

    run = database.list_stage_runs(task_id)[0]
    assert (run["status"], run["slurm_job_id"], bool(run["dispatch_claim"])) == (
        stage_state.QUEUED, None, True,
    )


def test_a_bookkeeping_outage_after_submit_cancels_the_allocation(tmp_path, monkeypatch):
    """An accepted handle that cannot be stored is cancelled, never abandoned."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "e4" * 16
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)

    job = task_runtime.SlurmJob(
        task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out")
    )
    job._process = object()
    captured: dict[str, object] = {}

    def _create(*_args, **kwargs):
        captured["callback"] = kwargs["allocation_dispatched_callback"]
        return job

    def _submit():
        captured["callback"]("9006", time.time(), False)
        return "9006"

    job.submit = _submit
    monkeypatch.setattr(task_runtime, "_create_job", _create)
    cancelled: list[str] = []
    monkeypatch.setattr(
        task_runtime, "_cancel_recorded_allocation", lambda handle: cancelled.append(handle) or True
    )
    real_update = database.update_task

    def _raise_on_handle_write(_task_id, **fields):
        if set(fields) == {"slurm_job_id"}:
            raise RuntimeError("database write failed")
        return real_update(_task_id, **fields)

    monkeypatch.setattr(database, "update_task", _raise_on_handle_write)

    with pytest.raises(RuntimeError, match="database write failed"):
        task_runtime._run_compute_job(
            task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
            resource_policy=_policy(),
        )

    assert cancelled == ["9006"]
    assert database.list_stage_runs(task_id)[0]["status"] == stage_state.FAILED


def test_a_popen_failure_permits_a_fresh_attempt(tmp_path, monkeypatch):
    """(d) A failure proven to precede srun creation keeps the retry safe."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "e3" * 16
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)

    job = task_runtime.SlurmJob(
        task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out")
    )
    job.submit = lambda: (_ for _ in ()).throw(RuntimeError("script could not be written"))
    monkeypatch.setattr(task_runtime, "_create_job", lambda *_args, **_kwargs: job)

    with pytest.raises(RuntimeError, match="script could not be written"):
        task_runtime._run_compute_job(
            task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
            resource_policy=_policy(),
        )

    assert database.list_stage_runs(task_id)[0]["status"] == stage_state.FAILED

    submissions: list[str] = []
    monkeypatch.setattr(task_runtime, "_create_job", _job_factory(submissions))
    state = task_runtime._run_compute_job(
        task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
        resource_policy=_policy(),
    )
    assert state == task_runtime.JobState.COMPLETED
    assert submissions == ["7001"]


def test_a_task_cancelled_during_submit_cancels_the_slurm_allocation(tmp_path, monkeypatch):
    """The single-stage guard mirrors the workflow path for a real SlurmJob."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "c10" * 11
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)

    job = task_runtime.SlurmJob(
        task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out")
    )
    cancelled: list[str] = []

    def _submit():
        # The cancellation lands while the scheduler request is in flight.
        assert database.claim_task_cancellation(task_id, finished_at=time.time(), error="cancelled")
        return "7005"

    job.submit = _submit
    job.cancel = lambda: cancelled.append("7005")
    monkeypatch.setattr(task_runtime, "_create_job", lambda *_args, **_kwargs: job)

    state = task_runtime._run_compute_job(
        task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
        resource_policy=_policy(),
    )

    assert state == task_runtime.JobState.CANCELLED
    assert cancelled == ["7005"]
    assert database.list_stage_runs(task_id)[0]["status"] == stage_state.CANCELLED


def test_a_cancellation_between_claim_and_submit_starts_no_allocation(tmp_path, monkeypatch):
    """(P2) A Task cancelled after the claim never reaches the scheduler."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "c5" * 16
    _insert_task(database, task_id, status="running")
    monkeypatch.setattr(task_runtime, "task_store", database)

    real_claim = database.claim_stage_dispatch

    def _cancel_after_claim(**kwargs):
        claimed = real_claim(**kwargs)
        assert database.claim_task_cancellation(task_id, finished_at=time.time(), error="cancelled")
        return claimed

    monkeypatch.setattr(database, "claim_stage_dispatch", _cancel_after_claim)
    monkeypatch.setattr(
        task_runtime, "_create_job", lambda *_args, **_kwargs: pytest.fail("must not submit")
    )

    state = task_runtime._run_compute_job(
        task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
        resource_policy=_policy(),
    )

    assert state == task_runtime.JobState.CANCELLED
    run = database.list_stage_runs(task_id)[0]
    assert run["status"] == stage_state.CANCELLED


def test_a_refused_handle_cancels_the_allocation_it_could_not_record(tmp_path, monkeypatch):
    """(P2) ``record_stage_dispatched=False`` tears the allocation down."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "c6" * 16
    _insert_task(database, task_id, status="running")
    database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name=STAGE)
    assert database.record_stage_dispatched(
        task_id=task_id, stage_name=STAGE, attempt=1, slurm_job_id="4100"
    )
    monkeypatch.setattr(task_runtime, "task_store", database)
    cancelled: list[str] = []
    monkeypatch.setattr(
        task_runtime, "_cancel_recorded_allocation", lambda handle: cancelled.append(handle) or True
    )

    dispatched, _started, _finished = task_runtime._compute_allocation_callbacks(
        task_id=task_id,
        user_id=0,
        stage_id=STAGE,
        resource_policy=_policy(),
        required_entitlements=(),
        runner_family=STAGE,
        attempt=1,
    )
    dispatched("9999", time.time(), False)

    assert cancelled == ["9999"]
    assert database.list_stage_runs(task_id)[0]["slurm_job_id"] == "4100"


def test_recovery_cancels_known_handles_before_refusing_an_unknown_one(monkeypatch):
    """A known allocation is stopped even when another attempt has no handle."""
    task = {"md5sum": "c7" * 16, "status": "running", "slurm_job_id": "9003", "task_type": STAGE}
    updates: list[dict] = []
    stopped: list[str] = []

    class _Store:
        def list_tasks(self):
            return [task]

        def claim_task_recovery(self, _task_id, *, expected_status):
            return expected_status == "running"

        def list_stage_runs(self, _task_id):
            return [
                {
                    "stage_name": STAGE, "stage_index": 0, "attempt": 1,
                    "status": stage_state.RUNNING, "slurm_job_id": "9003", "dispatch_claim": "w1",
                },
                {
                    "stage_name": "next_stage", "stage_index": 1, "attempt": 1,
                    "status": stage_state.QUEUED, "slurm_job_id": None, "dispatch_claim": "w2",
                },
            ]

        def finish_active_stage_runs(self, _task_id, *, status, reason_code):
            return 0

        def update_task(self, _task_id, **fields):
            updates.append(fields)
            return True

    class _TaskType:
        workflow = (object(),)

    monkeypatch.setattr(task_runtime, "task_store", _Store())
    monkeypatch.setattr(task_runtime, "CONFIG", replace(task_runtime.CONFIG, demo_mode=False))
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda _name: (_TaskType(), object()))
    monkeypatch.setattr(task_runtime, "_slurm_job_is_active", lambda _job_id: True)
    monkeypatch.setattr(
        task_runtime,
        "_stop_orphaned_workflow_execution",
        lambda _task_id, handle, _container: stopped.append(handle) or "",
    )

    assert task_runtime._recover_orphaned_tasks() == 1
    assert stopped == ["9003"]
    assert updates[-1]["status"] == "running"
    assert "cancel the Task to settle it" in updates[-1]["error"]


def test_recovery_never_replaces_an_unresolved_claimed_dispatch(monkeypatch):
    """(c) Worker-loss recovery does not re-enqueue over an unknown allocation."""
    task = {"md5sum": "c3" * 16, "status": "running", "task_type": STAGE}
    updates: list[dict] = []
    enqueued: list[tuple] = []

    class _Store:
        def list_tasks(self):
            return [task]

        def claim_task_recovery(self, _task_id, *, expected_status):
            return expected_status == "running"

        def list_stage_runs(self, _task_id):
            return [{
                "stage_name": STAGE, "stage_index": 0, "attempt": 1,
                "status": stage_state.QUEUED, "slurm_job_id": None,
                "dispatch_claim": "dead-worker",
            }]

        def finish_active_stage_runs(self, _task_id, *, status, reason_code):
            return 0

        def update_task(self, _task_id, **fields):
            updates.append(fields)
            return True

    class _TaskType:
        workflow = (object(),)

    class _Queued:
        id = "replacement-task"

    monkeypatch.setattr(task_runtime, "task_store", _Store())
    monkeypatch.setattr(task_runtime, "CONFIG", replace(task_runtime.CONFIG, demo_mode=False))
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda _name: (_TaskType(), object()))
    monkeypatch.setattr(
        task_runtime.run_compute_task, "apply_async",
        lambda *args, **kwargs: enqueued.append((args, kwargs)) or _Queued(),
    )

    assert task_runtime._recover_orphaned_tasks() == 1
    assert enqueued == []
    assert updates[-1]["status"] == "running"
    assert "claimed a dispatch" in updates[-1]["error"]


def test_an_authorized_retry_after_a_terminal_attempt_gets_one_new_allocation(tmp_path, monkeypatch):
    """(d) A settled attempt permits exactly one fresh attempt and allocation."""
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "d1" * 16
    _insert_task(database, task_id)
    first = database.begin_stage_attempt(task_id=task_id, stage_index=0, stage_name=STAGE)
    assert database.finish_stage_attempt(
        task_id=task_id, stage_name=STAGE, attempt=first["attempt"],
        status=stage_state.FAILED, reason_code="allocation_failed",
    )
    monkeypatch.setattr(task_runtime, "task_store", database)

    submissions: list[str] = []
    monkeypatch.setattr(task_runtime, "_create_job", _job_factory(submissions))

    state = task_runtime._run_compute_job(
        task_id, _single_stage_type(), RunnerConfig(), [], str(tmp_path / "out"),
        resource_policy=_policy(),
    )

    assert state == task_runtime.JobState.COMPLETED
    assert submissions == ["7001"]
    runs = database.list_stage_runs(task_id)
    assert [(run["attempt"], run["status"], run["slurm_job_id"]) for run in runs] == [
        (1, stage_state.FAILED, None),
        (2, stage_state.COMPLETED, "7001"),
    ]
