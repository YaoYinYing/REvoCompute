# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import signal
from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from revocompute.access_control import AccessPolicy
from revocompute.job import JobState
from revocompute.job.runners.slurm_runner import SlurmJob
from revocompute.resource_policy import ResolvedResources
from revocompute.task_types import RunnerConfig, RuntimeFamily, TaskType, WorkflowStage, discover_plugins, get

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolated_runtime_state(monkeypatch, tmp_path):
    server_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("SERVER_DIR", str(tmp_path))
    monkeypatch.setenv("CONFIG_DIR", str(server_root / "config"))
    monkeypatch.setenv("ENABLED_TASKRUNNERS", "alphafold")


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


def test_composer_resumes_after_completed_feature_stage(monkeypatch):
    from revocompute import task_runtime

    runtime = RuntimeFamily("alphafold", ("bash", "run.sh"), "runner.def", "image.sif")
    stages = (
        WorkflowStage("alphafold.features", "Features", False, ("-s", "features"), ("msa",)),
        WorkflowStage("alphafold.model", "Model", True, ("-s", "model"), ("model",)),
    )
    task_type = TaskType(
        "alphafold",
        "AlphaFold2",
        runtime,
        ".fasta",
        "FASTA",
        gpus=True,
        stage_markers={"msa": "MSA", "model": "Model"},
        workflow=stages,
    )
    updates = []
    created = []

    class _Job:
        def submit(self):
            return "42"

        def poll(self):
            return JobState.COMPLETED

    def _create(*args, **kwargs):
        created.append((args[1], kwargs["resource_policy"]))
        return _Job()

    monkeypatch.setattr(task_runtime, "_create_job", _create)

    def _update(task_id, **fields):
        del task_id
        updates.append(fields)
        return True

    monkeypatch.setattr(task_runtime.task_store, "update_task", _update)
    task = {
        "username": "tester",
        "workflow_state": json.dumps({"alphafold.features": {"status": "completed", "job_id": "41"}}),
    }

    result = task_runtime._run_compute_workflow(
        "a" * 32,
        task,
        task_type,
        RunnerConfig(),
        [],
        "/tmp/results",
        {"alphafold.features": _policy(False), "alphafold.model": _policy(True)},
        lambda stage: None,
    )

    assert result == JobState.COMPLETED
    assert len(created) == 1
    assert created[0][0].name == "alphafold-model"
    assert created[0][0].gpus is True
    assert created[0][1].requires_gpu is True
    final_state = json.loads(updates[-1]["workflow_state"])
    assert final_state["alphafold.features"]["status"] == "completed"
    assert final_state["alphafold.model"]["status"] == "completed"


def test_gpu_workflow_uses_owning_runtime_for_allocation_authorization(monkeypatch):
    from revocompute import task_runtime

    access_policy = AccessPolicy(
        "alphafold_noncommercial",
        "AlphaFold access",
        "Restricted runtime",
        ("alphafold_terms",),
        True,
    )
    runtime = RuntimeFamily(
        "alphafold",
        ("bash", "run.sh"),
        "runner.def",
        "image.sif",
        access_policy=access_policy,
    )
    stage = WorkflowStage("alphafold.model", "Model", True, ("-s", "model"), ("model",))
    task_type = TaskType(
        "alphafold",
        "AlphaFold2",
        runtime,
        ".fasta",
        "FASTA",
        gpus=True,
        stage_markers={"model": "Model"},
        workflow=(stage,),
    )
    callback_requests = []

    class _Job:
        def submit(self):
            return "42"

        def poll(self):
            return JobState.COMPLETED

    monkeypatch.setattr(task_runtime.task_store, "require_gpu_credit", lambda user_id: None)
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        task_runtime,
        "_gpu_allocation_callbacks",
        lambda **kwargs: callback_requests.append(kwargs) or (None, None),
    )
    monkeypatch.setattr(task_runtime, "_create_job", lambda *args, **kwargs: _Job())

    result = task_runtime._run_compute_workflow(
        "f" * 32,
        {"submitted_by_user_id": 17, "username": "tester"},
        task_type,
        RunnerConfig(),
        [],
        "/tmp/results",
        {"alphafold.model": _policy(True)},
        lambda stage_name: None,
    )

    assert result == JobState.COMPLETED
    assert callback_requests == [
        {
            "task_id": "f" * 32,
            "user_id": 17,
            "stage_id": "alphafold.model",
            "resource_policy": _policy(True),
            "required_entitlements": ("alphafold_terms",),
            "runner_family": "alphafold",
        }
    ]


def test_composer_does_not_submit_after_cancellation_claim_fails(monkeypatch):
    from revocompute import task_runtime

    runtime = RuntimeFamily("alphafold", ("bash", "run.sh"), "runner.def", "image.sif")
    stage = WorkflowStage("alphafold.model", "Model", True, ("-s", "model"), ("model",))
    task_type = TaskType(
        "alphafold",
        "AlphaFold2",
        runtime,
        ".fasta",
        "FASTA",
        gpus=True,
        stage_markers={"model": "Model"},
        workflow=(stage,),
    )
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: False)
    monkeypatch.setattr(task_runtime, "_create_job", lambda *args, **kwargs: pytest.fail("job must not be created"))

    result = task_runtime._run_compute_workflow(
        "b" * 32,
        {},
        task_type,
        RunnerConfig(),
        [],
        "/tmp/results",
        {"alphafold.model": _policy(True)},
        lambda stage_name: None,
    )

    assert result == JobState.CANCELLED


def test_composer_cancels_submitted_job_when_handle_cannot_be_persisted(monkeypatch):
    from revocompute import task_runtime

    runtime = RuntimeFamily("alphafold", ("bash", "run.sh"), "runner.def", "image.sif")
    stage = WorkflowStage("alphafold.model", "Model", True, ("-s", "model"), ("model",))
    task_type = TaskType(
        "alphafold",
        "AlphaFold2",
        runtime,
        ".fasta",
        "FASTA",
        gpus=True,
        stage_markers={"model": "Model"},
        workflow=(stage,),
    )
    updates = iter((True, False))
    cancelled = []

    class _Job:
        def submit(self):
            return "42"

        def cancel(self):
            cancelled.append(True)

    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: next(updates))
    monkeypatch.setattr(task_runtime, "_create_job", lambda *args, **kwargs: _Job())

    result = task_runtime._run_compute_workflow(
        "c" * 32,
        {},
        task_type,
        RunnerConfig(),
        [],
        "/tmp/results",
        {"alphafold.model": _policy(True)},
        lambda stage_name: None,
    )

    assert result == JobState.CANCELLED
    assert cancelled == [True]


def test_workflow_recovery_claims_stops_and_requeues_once(monkeypatch):
    from revocompute import task_runtime

    task = {
        "md5sum": "d" * 32,
        "status": "running",
        "task_type": "alphafold",
        "slurm_job_id": "1234",
        "container_id": None,
        "workflow_state": json.dumps({"alphafold.features": {"status": "running"}}),
    }
    claims = []
    stops = []
    updates = []

    class _TaskType:
        workflow = (object(),)

    class _Queued:
        id = "replacement-task"

    monkeypatch.setattr(task_runtime.task_store, "list_tasks", lambda: [task])
    monkeypatch.setattr(
        task_runtime.task_store,
        "claim_task_recovery",
        lambda task_id, expected_status: claims.append((task_id, expected_status)) or True,
    )
    monkeypatch.setattr(
        task_runtime.task_store,
        "update_task",
        lambda task_id, **fields: updates.append((task_id, fields)) or True,
    )
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (_TaskType(), object()))
    monkeypatch.setattr(
        task_runtime,
        "_stop_orphaned_workflow_execution",
        lambda *args: stops.append(args) or "",
    )
    monkeypatch.setattr(task_runtime.run_compute_task, "apply_async", lambda *args, **kwargs: _Queued())

    assert task_runtime._recover_orphaned_tasks() == 1
    assert claims == [("d" * 32, "running")]
    assert stops == [("d" * 32, "1234", "")]
    assert updates[-1][1]["celery_task_id"] == "replacement-task"


def test_workflow_recovery_enqueue_failure_stays_discoverable(monkeypatch):
    from revocompute import task_runtime

    task = {"md5sum": "e" * 32, "status": "queued", "task_type": "alphafold"}
    updates = []

    class _TaskType:
        workflow = (object(),)

    monkeypatch.setattr(task_runtime.task_store, "list_tasks", lambda: [task])
    monkeypatch.setattr(task_runtime.task_store, "claim_task_recovery", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        task_runtime.task_store,
        "update_task",
        lambda task_id, **fields: updates.append(fields) or True,
    )
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (_TaskType(), object()))
    monkeypatch.setattr(task_runtime, "_stop_orphaned_workflow_execution", lambda *args: "")
    monkeypatch.setattr(
        task_runtime.run_compute_task,
        "apply_async",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broker unavailable")),
    )

    assert task_runtime._recover_orphaned_tasks() == 1
    assert updates[-1]["status"] == "queued"
    assert "broker unavailable" in updates[-1]["error"]


def test_workflow_recovery_escalates_srun_termination(monkeypatch):
    from revocompute import task_runtime

    kills = []
    waits = iter((False, True))
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"srun task-1234")
    monkeypatch.setattr(task_runtime.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(task_runtime, "_wait_for_process_exit", lambda pid, timeout: next(waits))

    error = task_runtime._stop_orphaned_workflow_execution("task-1234", "srun-42", "")

    assert error == ""
    assert kills == [(42, signal.SIGTERM), (42, signal.SIGKILL)]


def _real_af3_stage(runner_args: tuple[str, ...]):
    """Return the real AlphaFold 3 stage TaskType the composer builds.

    The composer derives each allocation from the discovered task, so the
    stage-local marker set here is exactly what the stage parser sees.
    """
    task_type, runner = get("alphafold3")
    stage = next(item for item in task_type.workflow if tuple(item.runner_args) == runner_args)
    markers = {name: task_type.stage_markers[name] for name in stage.stage_markers}
    return replace(
        task_type,
        name=stage.name.replace(".", "-"),
        runner_args=stage.runner_args,
        gpus=stage.requires_gpu,
        requires_network=stage.requires_network,
        stage_markers=markers,
        workflow=(),
    ), runner


def _drive_stage_stdout(stage_tt, runner, tmp_path, stdout: str) -> list[str]:
    """Feed real runner stdout through ``SlurmJob._read_stdout`` + completion.

    ``_read_stdout`` is the production marker parser: it emits the first
    declared marker as a liveness signal once the allocation id is known, then
    advances on every later ``REVODESIGN_STAGE:`` line, and ``_maybe_stage_callback``
    settles the final declared marker on completion.
    """
    seen: list[str] = []
    job = SlurmJob(
        "task-1",
        stage_tt,
        runner,
        [],
        str(tmp_path / "out"),
        stage_callback=seen.append,
    )
    job._process = SimpleNamespace(stdout=StringIO(stdout))
    job._read_stdout()
    job._maybe_stage_callback(JobState.COMPLETED)
    return seen


@pytest.fixture(autouse=True)
def _discover_af3_runners():
    discover_plugins(str(ROOT / "docker" / "runners"), {"alphafold", "alphafold3", "colabfold_af2"})


def _transitions(seen: list[str]) -> list[str]:
    """Collapse consecutive duplicate callbacks, exactly as ``run_stage`` does.

    ``_on_stage_change`` only records a new ``run_stage`` when the marker
    differs from the current one, so a repeated marker line is a progress
    event, never a second transition.
    """
    transitions: list[str] = []
    for stage in seen:
        if not transitions or transitions[-1] != stage:
            transitions.append(stage)
    return transitions


def test_alphafold3_features_stage_observes_pipeline_and_validation_markers(tmp_path):
    """The features allocation must accept both markers the Runner emits."""
    stage_tt, runner = _real_af3_stage(("-s", "features"))
    assert set(stage_tt.stage_markers) == {"data_pipeline", "feature_validation"}

    seen = _drive_stage_stdout(
        stage_tt,
        runner,
        tmp_path,
        "REVODESIGN_JOB_ID=4154\n"
        "REVODESIGN_STAGE:data_pipeline\n"
        "REVODESIGN_STAGE:feature_validation\n",
    )

    # Liveness signal (first declared marker) then the Runner's own markers;
    # each advances run_stage once and the stage settles on its final marker.
    assert _transitions(seen) == ["data_pipeline", "feature_validation"]
    assert seen[-1] == "feature_validation"


def test_alphafold3_model_stage_observes_inference_and_validation_markers(tmp_path):
    stage_tt, runner = _real_af3_stage(("-s", "model"))
    assert set(stage_tt.stage_markers) == {"inference", "output_validation"}

    seen = _drive_stage_stdout(
        stage_tt,
        runner,
        tmp_path,
        "REVODESIGN_JOB_ID=4155\n"
        "REVODESIGN_STAGE:inference\n"
        "REVODESIGN_STAGE:output_validation\n",
    )

    assert _transitions(seen) == ["inference", "output_validation"]
    assert seen[-1] == list(stage_tt.stage_markers)[-1]


def test_alphafold3_stage_ignores_duplicate_and_foreign_markers(tmp_path):
    """Duplicate lines must not double-advance, and another stage's marker is
    not observable by the active stage."""
    features, runner = _real_af3_stage(("-s", "features"))
    seen = _drive_stage_stdout(
        features,
        runner,
        tmp_path,
        "REVODESIGN_JOB_ID=4154\n"
        "REVODESIGN_STAGE:data_pipeline\n"
        "REVODESIGN_STAGE:data_pipeline\n"
        # Belongs to the model stage, so the features parser must ignore it.
        "REVODESIGN_STAGE:inference\n"
        "REVODESIGN_STAGE:feature_validation\n",
    )
    assert "inference" not in seen
    assert _transitions(seen) == ["data_pipeline", "feature_validation"]

    model, runner = _real_af3_stage(("-s", "model"))
    seen = _drive_stage_stdout(
        model,
        runner,
        tmp_path,
        "REVODESIGN_JOB_ID=4155\n"
        "REVODESIGN_STAGE:inference\n"
        # Belongs to the features stage, so the model parser must ignore it.
        "REVODESIGN_STAGE:data_pipeline\n"
        "REVODESIGN_STAGE:inference\n"
        "REVODESIGN_STAGE:output_validation\n",
    )
    assert "data_pipeline" not in seen
    assert _transitions(seen) == ["inference", "output_validation"]


def test_composed_af3_workflow_advances_task_run_stage_through_all_markers(monkeypatch):
    """The composer's stage callbacks expose every task-level marker in order."""
    from revocompute import task_runtime

    task_type, runner = get("alphafold3")
    task_level = list(task_type.stage_markers)
    assert task_level == ["data_pipeline", "feature_validation", "inference", "output_validation"]

    seen: list[str] = []
    run_stages: list[str] = []

    class _Job:
        def __init__(self, tt):
            self._tt = tt

        def submit(self):
            return "42"

        def poll(self):
            # Emit the stage-local markers the real Runner's run.sh writes for
            # this allocation, through the composer's real callback boundary.
            for marker in self._tt.stage_markers:
                seen.append(marker)
            return JobState.COMPLETED

        def cancel(self):
            pass

    def _create_job(task_id, tt, runner, entities, output_dir, stage_callback=None, **kwargs):
        del task_id, runner, entities, output_dir, kwargs
        return _Job(tt)

    def _update(task_id, **fields):
        del task_id
        if fields.get("run_stage"):
            run_stages.append(fields["run_stage"])
        return True

    monkeypatch.setattr(task_runtime, "_create_job", _create_job)
    monkeypatch.setattr(task_runtime.task_store, "update_task", _update)

    result = task_runtime._run_compute_workflow(
        "a" * 32,
        {"username": "tester"},
        task_type,
        runner,
        [],
        "/tmp/results",
        {stage.name: _policy(stage.requires_gpu) for stage in task_type.workflow},
        seen.append,
    )

    assert result == JobState.COMPLETED
    # The composer opens each allocation on its first declared marker, in order.
    assert run_stages == [stage.stage_markers[0] for stage in task_type.workflow]
    # Concatenating what the Runner emitted per stage reproduces the task-level
    # ordered marker sequence exactly — no marker is skipped or duplicated.
    assert seen == task_level


def test_alphafold3_running_trace_represents_every_phase_in_order(monkeypatch):
    """The running trace can place run_stage at any of the four AF3 phases.

    Before the corrected ownership the task-level markers were correct but the
    two validation phases were unreachable, so a running trace could never
    settle on them.  ``run_stage`` now reaches each marker, so the trace must
    render each one as the current phase with the earlier phases done.
    """
    from revocompute import task_runtime

    task_type, runner = get("alphafold3")
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (task_type, runner))
    ordered = list(task_type.stage_markers)
    assert ordered == ["data_pipeline", "feature_validation", "inference", "output_validation"]

    for index, marker in enumerate(ordered):
        trace = task_runtime._build_running_trace(
            {"status": "running", "task_type": "alphafold3", "run_stage": marker}
        )
        lines = trace.splitlines()
        assert len(lines) == len(ordered)
        assert lines[index].endswith("[running]")
        assert all(line.endswith("[done]") for line in lines[:index])
        assert all(line.endswith("[pending]") for line in lines[index + 1 :])
