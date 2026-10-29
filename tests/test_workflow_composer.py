# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import signal
import sqlite3
from dataclasses import replace
from io import StringIO
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from revocompute.execution_graph import compile_graph
from revocompute.job import JobState
from revocompute.job.runners.slurm_runner import SlurmJob
from revocompute.resource_policy import ResolvedResources
from revocompute.task_types import (
    RuntimeFamily,
    StagePortSpec,
    TaskType,
    WorkflowStage,
    get,
    get_family,
)

ROOT = Path(__file__).resolve().parents[1]

# The composer drives the real task_runtime module object. Import it at
# collection time so every test resolves the same module the discovery fixture
# installs its snapshot into, and so a test that only reads the registry never
# triggers an import that repoints it.
from revocompute import task_runtime as _task_runtime  # noqa: E402,F401


def _live_task_runtime():
    """The task_runtime module object the composer binds to.

    A prior test in the same xdist worker can pop ``sys.modules['revocompute.task_runtime']``
    (conftest's import-isolation dance does exactly that for isolated-app tests). Resolving
    through ``sys.modules`` first keeps the composer tests reading the module whose registry
    the autouse fixture repopulates.
    """
    return sys.modules.get("revocompute.task_runtime") or _task_runtime


@pytest.fixture(autouse=True)
def _isolated_runtime_state(monkeypatch, tmp_path):
    server_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("SERVER_DIR", str(tmp_path))
    monkeypatch.setenv("CONFIG_DIR", str(server_root / "config"))
    monkeypatch.setenv("ENABLED_TASKRUNNERS", "multistage_runner")


def _ensure_task_row(task_runtime, task_id: str) -> None:
    """A StageRun needs an active Task row; production always has one."""
    task_runtime.task_store.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=1.0,
        status="queued",
        is_binary=0,
        task_type="multistage_runner",
        storage_key="owner-key",
        submitted_by_user_id=0,
    )


def _frozen(task_type, **fields) -> dict:
    graph = compile_graph(task_type)
    fields.setdefault(
        "input_form",
        json.dumps({
            "execution_graph": {
                "ir_version": graph.ir_version, "digest": graph.digest, "document": graph.document,
            },
        }),
    )
    return fields


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


@pytest.mark.parametrize("output_kind", ["valid", "missing", "escape"])
def test_graph_scheduler_validates_outputs_and_preserves_attempts(monkeypatch, tmp_path, output_kind):
    task_runtime = _live_task_runtime()
    runtime = RuntimeFamily("multistage_runner", ("bash", "run.sh"), "runner.def", "image.sif")
    features = WorkflowStage(
        "multistage_runner.features", "Features", False, ("-s", "features"), ("msa",),
        outputs=(StagePortSpec("features", "features", path="features.dat"),),
    )
    model = WorkflowStage(
        "multistage_runner.model", "Model", True, ("-s", "model"), ("model",),
        inputs=(StagePortSpec("features", "features", source="multistage_runner.features:features"),),
    )
    task_type = TaskType(
        "multistage_runner", "Synthetic staged calculation", runtime, (),
        stage_markers={"msa": "MSA", "model": "Model"}, workflow=(model, features),
    )
    output = tmp_path / "output"
    output.mkdir()
    if output_kind == "valid":
        (output / "features.dat").write_text("features")
    elif output_kind == "escape":
        outside = tmp_path / "outside"
        outside.write_text("features")
        (output / "features.dat").symlink_to(outside)

    class Job:
        def submit(self):
            return "42"

        def poll(self):
            return JobState.COMPLETED

    started = []
    monkeypatch.setattr(task_runtime, "_create_job", lambda *args, **kwargs: started.append(args[1].name) or Job())
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: True)
    task_id = {"valid": "1", "missing": "2", "escape": "3"}[output_kind] * 32
    _ensure_task_row(task_runtime, task_id)
    result = task_runtime._run_compute_workflow(
        task_id, _frozen(task_type), task_type, [], str(output),
        {stage.name: _policy(stage.requires_gpu) for stage in task_type.workflow}, lambda _: None,
    )
    runs = task_runtime.task_store.list_stage_runs(task_id)
    if output_kind == "valid":
        assert result == JobState.COMPLETED
        assert started == ["multistage_runner-features", "multistage_runner-model"]
        assert {(run["stage_name"], run["attempt"], run["stage_index"], run["status"]) for run in runs} == {
            (features.name, 1, 1, "COMPLETED"), (model.name, 1, 0, "COMPLETED")
        }
    else:
        assert result == JobState.FAILED
        assert started == ["multistage_runner-features"]
        assert len(runs) == 1
        assert runs[0]["status"] == "FAILED"
        assert runs[0]["reason_code"] == "stage_output_missing"


@pytest.mark.parametrize(("mutation", "expected_reason"), [
    ("unchanged", None),
    ("deleted", "stage_output_invalid"),
    ("changed", "stage_output_invalid"),
    ("unverified", "stage_output_unverified"),
])
def test_resume_revalidates_completed_producer_outputs(monkeypatch, tmp_path, mutation, expected_reason):
    task_runtime = _live_task_runtime()
    runtime = RuntimeFamily("multistage_runner", ("bash", "run.sh"), "runner.def", "image.sif")
    features = WorkflowStage(
        "multistage_runner.features", "Features", False, ("-s", "features"), ("msa",),
        outputs=(StagePortSpec("features", "features", path="features.dat"),),
    )
    model = WorkflowStage(
        "multistage_runner.model", "Model", True, ("-s", "model"), ("model",),
        inputs=(StagePortSpec("features", "features", source="multistage_runner.features:features"),),
    )
    task_type = TaskType(
        "multistage_runner", "Synthetic staged calculation", runtime, (),
        stage_markers={"msa": "MSA", "model": "Model"}, workflow=(features, model),
    )
    output = tmp_path / "output"
    output.mkdir()
    task_id = mutation.encode().hex().ljust(32, "0")[:32]
    _ensure_task_row(task_runtime, task_id)

    first_call = {"done": False}

    class Job:
        def __init__(self, name):
            self.name = name

        def submit(self):
            return "42"

        def poll(self):
            if self.name.endswith("features"):
                (output / "features.dat").write_text("features")
                return JobState.COMPLETED
            return JobState.COMPLETED if first_call["done"] else JobState.FAILED

    def create(_task_id, stage_tt, *_args, **_kwargs):
        return Job(stage_tt.name)

    monkeypatch.setattr(task_runtime, "_create_job", create)
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: True)
    policies = {stage.name: _policy(stage.requires_gpu) for stage in task_type.workflow}
    assert task_runtime._run_compute_workflow(
        task_id, _frozen(task_type), task_type, [], str(output), policies, lambda _: None,
    ) == JobState.FAILED
    first_call["done"] = True
    assert task_runtime.task_store.list_stage_runs(task_id)[0]["output_identity"]

    if mutation == "deleted":
        (output / "features.dat").unlink()
    elif mutation == "changed":
        (output / "features.dat").write_text("tampered")
    elif mutation == "unverified":
        with task_runtime.task_store.engine.begin() as conn:
            conn.exec_driver_sql(
                "UPDATE stage_runs SET output_identity = NULL WHERE task_id = ?",
                (task_id,),
            )

    started = []
    monkeypatch.setattr(task_runtime, "_create_job", lambda _id, tt, *a, **kw: started.append(tt.name) or Job(tt.name))
    result = task_runtime._run_compute_workflow(
        task_id, _frozen(task_type), task_type, [], str(output), policies, lambda _: None,
    )
    if expected_reason is None:
        assert result == JobState.COMPLETED
        assert started == ["multistage_runner-model"]
    else:
        assert result == JobState.FAILED
        assert started == []
        evidence = task_runtime.task_store.get_task_diagnostics(task_id) or {}
        assert evidence["reason_code"] == expected_reason
        assert evidence["blocked_stages"] == ["multistage_runner.model"]


def test_composer_refuses_unverified_legacy_completed_stage(monkeypatch):
    task_runtime = _live_task_runtime()

    runtime = RuntimeFamily("multistage_runner", ("bash", "run.sh"), "runner.def", "image.sif")
    stages = (
        WorkflowStage(
            "multistage_runner.features", "Features", False, ("-s", "features"), ("msa",),
            outputs=(StagePortSpec("features", "features", path="features.dat"),),
        ),
        WorkflowStage(
            "multistage_runner.model", "Model", True, ("-s", "model"), ("model",),
            inputs=(StagePortSpec("features", "features", source="multistage_runner.features:features"),),
        ),
    )
    task_type = TaskType(
        "multistage_runner",
        "Synthetic staged calculation",
        runtime,
        (),
        gpus=True,
        stage_markers={"msa": "MSA", "model": "Model"},
        workflow=stages,
    )
    created = []
    monkeypatch.setattr(
        task_runtime, "_create_job", lambda *args, **kwargs: created.append(args[1].name) or pytest.fail("no dispatch")
    )
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: True)
    task = _frozen(
        task_type,
        username="tester",
        workflow_state=json.dumps({"multistage_runner.features": {"status": "completed", "job_id": "41"}}),
    )
    _ensure_task_row(task_runtime, "a" * 32)

    result = task_runtime._run_compute_workflow(
        "a" * 32, task, task_type, [], "/tmp/results",
        {"multistage_runner.features": _policy(False), "multistage_runner.model": _policy(True)},
        lambda stage: None,
    )

    assert result == JobState.FAILED
    assert created == []
    evidence = task_runtime.task_store.get_task_diagnostics("a" * 32) or {}
    assert evidence["reason_code"] == "stage_output_unverified"
    assert evidence["blocked_stages"] == ["multistage_runner.model"]


@pytest.mark.parametrize(
    ("frozen", "reason"),
    [(None, "execution_graph_unverified"), ("changed", "execution_graph_changed")],
)
def test_dispatch_refuses_graph_that_differs_from_submission(monkeypatch, frozen, reason):
    task_runtime = _live_task_runtime()
    runtime = RuntimeFamily("multistage_runner", ("bash", "run.sh"), "runner.def", "image.sif")
    features = WorkflowStage(
        "multistage_runner.features", "Features", False, ("-s", "features"), ("msa",),
        outputs=(StagePortSpec("features", "features", path="features.dat"),),
    )
    task_type = TaskType(
        "multistage_runner", "Synthetic staged calculation", runtime, (),
        stage_markers={"msa": "MSA"}, workflow=(features,),
    )
    task = {} if frozen is None else _frozen(task_type)
    if frozen == "changed":
        task_type = replace(
            task_type,
            workflow=(replace(features, runner_args=("-s", "features-v2")),),
        )
    monkeypatch.setattr(task_runtime, "_create_job", lambda *args, **kwargs: pytest.fail("no dispatch"))
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: True)
    task_id = ("1" if frozen is None else "2") * 32
    _ensure_task_row(task_runtime, task_id)
    result = task_runtime._run_compute_workflow(
        task_id, task, task_type, [], "/tmp/results",
        {features.name: _policy(False)}, lambda _: None,
    )
    assert result == JobState.FAILED
    assert (task_runtime.task_store.get_task_diagnostics(task_id) or {})["reason_code"] == reason


def _diamond_workflow() -> TaskType:
    runtime = RuntimeFamily("multistage_runner", ("bash", "run.sh"), "runner.def", "image.sif")
    stage_a = WorkflowStage(
        "dag.a", "A", False, ("-s", "a"), ("a",), outputs=(StagePortSpec("out", "x", path="a.dat"),),
    )
    stage_b = WorkflowStage(
        "dag.b", "B", False, ("-s", "b"), ("b",),
        inputs=(StagePortSpec("in", "x", source="dag.a:out"),),
        outputs=(StagePortSpec("out", "x", path="b.dat"),),
    )
    stage_c = WorkflowStage(
        "dag.c", "C", False, ("-s", "c"), ("c",),
        inputs=(StagePortSpec("in", "x", source="dag.a:out"),),
        outputs=(StagePortSpec("out", "x", path="c.dat"),),
    )
    stage_d = WorkflowStage(
        "dag.d", "D", False, ("-s", "d"), ("d",),
        inputs=(
            StagePortSpec("left", "x", source="dag.b:out"),
            StagePortSpec("right", "x", source="dag.c:out"),
        ),
        outputs=(StagePortSpec("out", "x", path="d.dat"),),
    )
    return TaskType(
        "dag", "Synthetic DAG", runtime, (),
        stage_markers={"a": "A", "b": "B", "c": "C", "d": "D"},
        workflow=(stage_a, stage_b, stage_c, stage_d),
    )


def test_foreign_family_node_uses_that_family_runtime_runner_and_policy(monkeypatch, tmp_path):
    task_runtime = _live_task_runtime()
    foreign_runtime, foreign_runner = get_family("restricted_runner")
    base = _diamond_workflow()
    foreign = replace(base.workflow[1], family="restricted_runner")
    task_type = replace(base, workflow=(base.workflow[0], foreign, *base.workflow[2:]))
    output = tmp_path / "output"
    output.mkdir()
    created = []
    callback_arguments = []

    class Job:
        def __init__(self, name):
            self.name = name

        def submit(self):
            return "42"

        def poll(self):
            (output / f"{self.name.rsplit('-', 1)[-1]}.dat").write_text("ok")
            return JobState.COMPLETED

    def create(_task_id, stage_tt, runner, *_args, **_kwargs):
        created.append((stage_tt, runner))
        return Job(stage_tt.name)

    real_callbacks = task_runtime._compute_allocation_callbacks

    def callbacks(**kwargs):
        callback_arguments.append(kwargs)
        return real_callbacks(**kwargs)

    monkeypatch.setattr(task_runtime, "_create_job", create)
    monkeypatch.setattr(task_runtime, "_compute_allocation_callbacks", callbacks)
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: True)
    task_id = "e" * 32
    _ensure_task_row(task_runtime, task_id)
    policies = {stage.name: _policy(False) for stage in task_type.workflow}

    result = task_runtime._run_compute_workflow(
        task_id, _frozen(task_type), task_type, [], str(output), policies, lambda _: None,
    )

    assert result == JobState.COMPLETED
    by_name = {stage_tt.name: (stage_tt, runner) for stage_tt, runner in created}
    foreign_tt, foreign_job_runner = by_name["dag-b"]
    assert foreign_tt.runtime is foreign_runtime
    assert foreign_tt.runtime.slurm_image == foreign_runtime.slurm_image
    assert foreign_tt.runtime.entrypoint == foreign_runtime.entrypoint
    assert foreign_job_runner is foreign_runner
    callback = next(item for item in callback_arguments if item["stage_id"] == "dag.b")
    assert callback["required_entitlements"] == ("synthetic_noncommercial",)
    assert callback["runner_family"] == "restricted_runner"
    own_tt, own_job_runner = by_name["dag-a"]
    assert own_tt.runtime.name == "multistage_runner"
    assert own_job_runner is get_family("multistage_runner")[1]


def test_unavailable_stage_attempt_blocks_every_allocation(monkeypatch, tmp_path):
    """No durable attempt means no allocation authority: never submit the Runner."""
    task_runtime = _live_task_runtime()
    task_type = _diamond_workflow()
    output = tmp_path / "output"
    output.mkdir()
    created = []

    def unavailable(**_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(task_runtime.task_store, "begin_stage_attempt", unavailable)
    monkeypatch.setattr(task_runtime, "_create_job", lambda *args, **kwargs: created.append(args))
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: True)
    task_id = "b2" * 16
    _ensure_task_row(task_runtime, task_id)
    policies = {stage.name: _policy(False) for stage in task_type.workflow}

    result = task_runtime._run_compute_workflow(
        task_id, _frozen(task_type), task_type, [], str(output), policies, lambda _: None,
    )

    assert result == JobState.FAILED
    assert created == []
    evidence = task_runtime.task_store.get_task_diagnostics(task_id)
    assert evidence["reason_code"] == "stage_attempt_unavailable"
    assert evidence["stage_id"] == "dag.a"


def test_unsettled_completion_stops_before_consumer_dispatch(monkeypatch, tmp_path):
    """A COMPLETED allocation whose durable transition fails must not advance the DAG."""
    task_runtime = _live_task_runtime()
    task_type = _diamond_workflow()
    output = tmp_path / "output"
    output.mkdir()
    started = []

    class Job:
        def __init__(self, name):
            self.name = name

        def submit(self):
            return "42"

        def poll(self):
            (output / f"{self.name.rsplit('-', 1)[-1]}.dat").write_text("ok")
            return JobState.COMPLETED

    def create(_task_id, stage_tt, *_args, **_kwargs):
        started.append(stage_tt.name)
        return Job(stage_tt.name)

    monkeypatch.setattr(task_runtime, "_create_job", create)
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: True)
    monkeypatch.setattr(task_runtime.task_store, "finish_stage_attempt", lambda **kwargs: False)
    task_id = "a1" * 16
    _ensure_task_row(task_runtime, task_id)
    policies = {stage.name: _policy(False) for stage in task_type.workflow}

    result = task_runtime._run_compute_workflow(
        task_id, _frozen(task_type), task_type, [], str(output), policies, lambda _: None,
    )

    assert result == JobState.FAILED
    assert started == ["dag-a"]
    evidence = task_runtime.task_store.get_task_diagnostics(task_id)
    assert evidence["reason_code"] == "stage_settlement_failed"
    assert evidence["stage_id"] == "dag.a"


def test_fork_join_runs_serial_schedule_and_resume_after_branch_failure(monkeypatch, tmp_path):
    task_runtime = _live_task_runtime()
    task_type = _diamond_workflow()
    output = tmp_path / "output"
    output.mkdir()
    fail_b = {"value": True}
    started = []

    class Job:
        def __init__(self, task_id, name):
            self.task_id = task_id
            self.name = name

        def submit(self):
            return "42"

        def poll(self):
            suffix = self.name.rsplit("-", 1)[-1]
            if suffix == "b" and fail_b["value"]:
                task_runtime.task_store.record_task_diagnostics(
                    self.task_id, {"reason_code": "nonzero_exit", "stage_id": "dag.b"}
                )
                return JobState.FAILED
            (output / f"{suffix}.dat").write_text(suffix)
            return JobState.COMPLETED

    def create(task_id, stage_tt, *_args, **_kwargs):
        started.append(stage_tt.name)
        return Job(task_id, stage_tt.name)

    monkeypatch.setattr(task_runtime, "_create_job", create)
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: True)
    task_id = "7" * 32
    _ensure_task_row(task_runtime, task_id)
    policies = {stage.name: _policy(False) for stage in task_type.workflow}

    first = task_runtime._run_compute_workflow(
        task_id, _frozen(task_type), task_type, [], str(output), policies, lambda _: None,
    )

    assert first == JobState.FAILED
    assert started == ["dag-a", "dag-b", "dag-c"]
    assert (output / "c.dat").read_text() == "c"
    runs = {run["stage_name"]: run for run in task_runtime.task_store.list_stage_runs(task_id)}
    assert set(runs) == {"dag.a", "dag.b", "dag.c"}
    assert runs["dag.c"]["status"] == "COMPLETED"
    evidence = task_runtime.task_store.get_task_diagnostics(task_id)
    assert evidence["reason_code"] == "nonzero_exit"
    assert evidence["blocked_stages"] == ["dag.d"]

    fail_b["value"] = False
    started.clear()
    second = task_runtime._run_compute_workflow(
        task_id, _frozen(task_type), task_type, [], str(output), policies, lambda _: None,
    )

    assert second == JobState.COMPLETED
    assert started == ["dag-b", "dag-d"]
    runs = task_runtime.task_store.list_stage_runs(task_id)
    assert {(run["stage_name"], run["status"]) for run in runs if run["attempt"] == 1} == {
        ("dag.a", "COMPLETED"), ("dag.b", "FAILED"), ("dag.c", "COMPLETED"), ("dag.d", "COMPLETED")
    }


def test_fork_and_join_both_complete_in_deterministic_order(monkeypatch, tmp_path):
    task_runtime = _live_task_runtime()
    task_type = _diamond_workflow()
    output = tmp_path / "output"
    output.mkdir()
    started = []

    class Job:
        def submit(self):
            return "42"

        def poll(self):
            return JobState.COMPLETED

    def create(_task_id, stage_tt, *_args, **_kwargs):
        suffix = stage_tt.name.rsplit("-", 1)[-1]
        started.append(stage_tt.name)
        (output / f"{suffix}.dat").write_text(suffix)
        return Job()

    monkeypatch.setattr(task_runtime, "_create_job", create)
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: True)
    task_id = "8" * 32
    _ensure_task_row(task_runtime, task_id)
    result = task_runtime._run_compute_workflow(
        task_id, _frozen(task_type), task_type, [], str(output),
        {stage.name: _policy(False) for stage in task_type.workflow}, lambda _: None,
    )

    assert result == JobState.COMPLETED
    assert started == ["dag-a", "dag-b", "dag-c", "dag-d"]


def test_latest_failed_attempt_is_not_reused(monkeypatch, tmp_path):
    task_runtime = _live_task_runtime()
    runtime = RuntimeFamily("multistage_runner", ("bash", "run.sh"), "runner.def", "image.sif")
    features = WorkflowStage(
        "multistage_runner.features", "Features", False, ("-s", "features"), ("msa",),
        outputs=(StagePortSpec("features", "features", path="features.dat"),),
    )
    task_type = TaskType(
        "multistage_runner", "Synthetic staged calculation", runtime, (),
        stage_markers={"msa": "MSA"}, workflow=(features,),
    )
    task_id = "9" * 32
    _ensure_task_row(task_runtime, task_id)
    first = task_runtime.task_store.begin_stage_attempt(
        task_id=task_id, stage_index=0, stage_name=features.name
    )
    task_runtime.task_store.finish_stage_attempt(
        task_id=task_id, stage_name=features.name, attempt=first["attempt"],
        status="COMPLETED", reason_code="completed", output_identity='{"output_identity_format":1,"files":[]}',
    )
    second = task_runtime.task_store.begin_stage_attempt(
        task_id=task_id, stage_index=0, stage_name=features.name
    )
    task_runtime.task_store.finish_stage_attempt(
        task_id=task_id, stage_name=features.name, attempt=second["attempt"],
        status="FAILED", reason_code="allocation_failed",
    )
    output = tmp_path / "output"
    output.mkdir()
    started = []

    class Job:
        def submit(self):
            return "42"

        def poll(self):
            (output / "features.dat").write_text("features")
            return JobState.COMPLETED

    monkeypatch.setattr(
        task_runtime, "_create_job", lambda _id, tt, *a, **kw: started.append(tt.name) or Job()
    )
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: True)
    result = task_runtime._run_compute_workflow(
        task_id, _frozen(task_type), task_type, [], str(output),
        {features.name: _policy(False)}, lambda _: None,
    )

    assert result == JobState.COMPLETED
    assert started == ["multistage_runner-features"]
    runs = task_runtime.task_store.list_stage_runs(task_id)
    assert max(int(run["attempt"]) for run in runs) == 3
    assert [run["status"] for run in runs if run["attempt"] == 3] == ["COMPLETED"]


def test_gpu_workflow_uses_owning_runtime_for_allocation_authorization(monkeypatch):
    task_runtime = _live_task_runtime()

    runtime, runner = get_family("restricted_runner")
    stage = WorkflowStage("restricted_runner.model", "Model", True, ("-s", "model"), ("model",))
    task_type = TaskType(
        "restricted_runner",
        "Synthetic staged calculation",
        runtime,
        (),
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

    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        task_runtime,
        "_compute_allocation_callbacks",
        lambda **kwargs: callback_requests.append(kwargs) or (None, None, None),
    )
    monkeypatch.setattr(task_runtime, "_create_job", lambda *args, **kwargs: _Job())

    _ensure_task_row(task_runtime, "f" * 32)
    result = task_runtime._run_compute_workflow(
        "f" * 32,
        _frozen(task_type, submitted_by_user_id=17, username="tester"),
        task_type,
        [],
        "/tmp/results",
        {"restricted_runner.model": _policy(True)},
        lambda stage_name: None,
    )

    assert result == JobState.COMPLETED
    # Each allocation callback is bound to the durable attempt it belongs to, so
    # a duplicate dispatch cannot create a second StageRun for the same work.
    assert len(callback_requests) == 1
    request = dict(callback_requests[0])
    assert request.pop("attempt") == 1
    assert request == {
        "task_id": "f" * 32,
        "user_id": 17,
        "stage_id": "restricted_runner.model",
        "resource_policy": _policy(True),
        "required_entitlements": ("synthetic_noncommercial",),
        "runner_family": "restricted_runner",
    }


def test_composer_does_not_submit_after_cancellation_claim_fails(monkeypatch):
    task_runtime = _live_task_runtime()

    runtime = RuntimeFamily("multistage_runner", ("bash", "run.sh"), "runner.def", "image.sif")
    stage = WorkflowStage("multistage_runner.model", "Model", True, ("-s", "model"), ("model",))
    task_type = TaskType(
        "multistage_runner",
        "Synthetic staged calculation",
        runtime,
        (),
        gpus=True,
        stage_markers={"model": "Model"},
        workflow=(stage,),
    )
    monkeypatch.setattr(task_runtime.task_store, "update_task", lambda *args, **kwargs: False)
    monkeypatch.setattr(task_runtime, "_create_job", lambda *args, **kwargs: pytest.fail("job must not be created"))

    result = task_runtime._run_compute_workflow(
        "b" * 32,
        _frozen(task_type),
        task_type,
        [],
        "/tmp/results",
        {"multistage_runner.model": _policy(True)},
        lambda stage_name: None,
    )

    assert result == JobState.CANCELLED


def test_composer_cancels_submitted_job_when_handle_cannot_be_persisted(monkeypatch):
    task_runtime = _live_task_runtime()

    runtime = RuntimeFamily("multistage_runner", ("bash", "run.sh"), "runner.def", "image.sif")
    stage = WorkflowStage("multistage_runner.model", "Model", True, ("-s", "model"), ("model",))
    task_type = TaskType(
        "multistage_runner",
        "Synthetic staged calculation",
        runtime,
        (),
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

    _ensure_task_row(task_runtime, "c" * 32)
    result = task_runtime._run_compute_workflow(
        "c" * 32,
        _frozen(task_type),
        task_type,
        [],
        "/tmp/results",
        {"multistage_runner.model": _policy(True)},
        lambda stage_name: None,
    )

    assert result == JobState.CANCELLED
    assert cancelled == [True]


def test_workflow_recovery_claims_stops_and_requeues_once(monkeypatch):
    task_runtime = _live_task_runtime()

    task = {
        "md5sum": "d" * 32,
        "status": "running",
        "task_type": "multistage_runner",
        "slurm_job_id": "1234",
        "container_id": None,
        "workflow_state": json.dumps({"multistage_runner.features": {"status": "running"}}),
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
    task_runtime = _live_task_runtime()

    task = {"md5sum": "e" * 32, "status": "queued", "task_type": "multistage_runner"}
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
    task_runtime = _live_task_runtime()

    kills = []
    waits = iter((False, True))
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"srun task-1234")
    monkeypatch.setattr(task_runtime.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(task_runtime, "_wait_for_process_exit", lambda pid, timeout: next(waits))

    error = task_runtime._stop_orphaned_workflow_execution("task-1234", "srun-42", "")

    assert error == ""
    assert kills == [(42, signal.SIGTERM), (42, signal.SIGKILL)]


def _synthetic_stage(runner_args: tuple[str, ...]):
    """Return the synthetic stage TaskType the composer builds.

    The composer derives each allocation from the discovered task, so the
    stage-local marker set here is exactly what the stage parser sees.
    """
    task_type, runner = get("restricted_runner")
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
    """Feed synthetic Runner stdout through ``SlurmJob._read_stdout`` + completion.

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
    # Discover the AF3 subset into the active registry for the duration of each
    # test, then restore the exact prior snapshot. isolated_discovery owns that
    # save/restore, so this fixture never leaks a narrowed registry into a later
    # test in the same worker.
    from revocompute.task_types import isolated_discovery

    with isolated_discovery(str(ROOT / "tests" / "fixtures" / "runners"), {"multistage_runner", "restricted_runner", "gpu_runner"}):
        yield


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


def test_restricted_runner_features_stage_observes_pipeline_and_validation_markers(tmp_path):
    """The features allocation must accept both markers the Runner emits."""
    stage_tt, runner = _synthetic_stage(("-s", "features"))
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


def test_restricted_runner_model_stage_observes_inference_and_validation_markers(tmp_path):
    stage_tt, runner = _synthetic_stage(("-s", "model"))
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


def test_restricted_runner_stage_ignores_duplicate_and_foreign_markers(tmp_path):
    """Duplicate lines must not double-advance, and another stage's marker is
    not observable by the active stage."""
    features, runner = _synthetic_stage(("-s", "features"))
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

    model, runner = _synthetic_stage(("-s", "model"))
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
    task_runtime = _live_task_runtime()

    task_type, _runner = get("restricted_runner")
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

    _ensure_task_row(task_runtime, "a" * 32)
    result = task_runtime._run_compute_workflow(
        "a" * 32,
        _frozen(task_type, username="tester"),
        task_type,
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


def test_restricted_runner_running_trace_represents_every_phase_in_order(monkeypatch):
    """The running trace can place run_stage at any of the four AF3 phases.

    Before the corrected ownership the task-level markers were correct but the
    two validation phases were unreachable, so a running trace could never
    settle on them.  ``run_stage`` now reaches each marker, so the trace must
    render each one as the current phase with the earlier phases done.
    """
    task_runtime = _live_task_runtime()

    task_type, runner = get("restricted_runner")
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (task_type, runner))
    ordered = list(task_type.stage_markers)
    assert ordered == ["data_pipeline", "feature_validation", "inference", "output_validation"]

    for index, marker in enumerate(ordered):
        trace = task_runtime._build_running_trace(
            {"status": "running", "task_type": "restricted_runner", "run_stage": marker}
        )
        lines = trace.splitlines()
        assert len(lines) == len(ordered)
        assert lines[index].endswith("[running]")
        assert all(line.endswith("[done]") for line in lines[:index])
        assert all(line.endswith("[pending]") for line in lines[index + 1 :])
