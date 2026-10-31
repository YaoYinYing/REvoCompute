# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from revocompute import live_test_executor
from revocompute.db import TaskDatabase


def test_worker_executor_rejects_removed_legacy_request(tmp_path):
    request = tmp_path / "request.json"
    result_path = tmp_path / "evidence.json"
    artifact = tmp_path / "candidate.sif"
    artifact.write_bytes(b"candidate")
    request.write_text(json.dumps({
        "task_id": "a" * 32, "task_type": "profile_runner", "result_path": str(result_path),
        "artifact_path": str(artifact), "artifact_sha256": "sha256:" + __import__("hashlib").sha256(b"candidate").hexdigest(),
    }))
    with pytest.raises(ValueError, match="invalid schema"):
        live_test_executor.execute(request)


def test_fileless_live_case_serializes_explicit_task_workspace_identity(tmp_path):
    """A fileless case has no file entity, so the workspace identity must be
    top-level or task_runtime cannot resolve the task workspace."""
    snapshot_root = tmp_path / "workspace" / ("a" * 32) / "inputs"
    form = json.loads(
        live_test_executor._task_input_form(
            [], snapshot_root, "live-test-fileless_runner", {"resource_policy": None},
            {"fileless_runner": "sha256:" + "a" * 64},
            {"fileless_runner": "sha256:" + "b" * 64}, None,
        )
    )
    assert form["entities"] == []
    # These two fields are exactly what task_runtime._execute_compute_task
    # consumes to append the explicit workspace entity.
    assert form["workspace_key"] == "live-test-fileless_runner"
    assert form["snapshot_root"] == str(snapshot_root)
    assert form["resource_policy"] is None
    assert form["runtime_bundles"] == {"fileless_runner": "sha256:" + "a" * 64}
    assert form["runtime_images"] == {"fileless_runner": "sha256:" + "b" * 64}


def test_live_test_pins_candidate_image_bytes_before_a_receipt_exists(tmp_path):
    """The live test is the run that produces the receipt, so it pins the bytes."""
    from revocompute.task_types import RuntimeFamily, TaskType

    image = tmp_path / "candidate.sif"
    image.write_bytes(b"candidate")
    runtime = RuntimeFamily("live_family", ("bash", "run.sh"), "runner.def", str(image))
    task_type = TaskType("live", "Live", runtime, ())

    assert live_test_executor._pinned_runtime_images(task_type) == {
        "live_family": "sha256:" + hashlib.sha256(b"candidate").hexdigest()
    }

    image.unlink()
    with pytest.raises(ValueError, match="runtime image is unavailable"):
        live_test_executor._pinned_runtime_images(task_type)


def test_live_storage_key_survives_a_composed_enabled_scope(tmp_path, monkeypatch):
    """A composed run enables several families; the resolver rejects a comma."""
    from revocompute.storage import StorageResolver

    monkeypatch.setenv("ENABLED_TASKRUNNERS", "alpha_runner,beta_runner")
    resolver = StorageResolver(str(tmp_path / "results"), str(tmp_path / "workspaces"), None)
    root = resolver.get_input_root({"md5sum": "a" * 32, "storage_key": live_test_executor._live_storage_key()})
    assert Path(root).name == "a" * 32

    monkeypatch.setenv("ENABLED_TASKRUNNERS", "alpha_runner")
    assert live_test_executor._live_storage_key() == "live-test-alpha_runner"


def test_workflow_live_task_form_carries_a_dispatchable_frozen_graph(tmp_path):
    from revocompute import task_runtime
    from revocompute.execution_graph import execution_graph_payload
    from revocompute.task_types import RuntimeFamily, StagePortSpec, TaskType, WorkflowStage

    runtime = RuntimeFamily("live_family", ("bash", "run.sh"), "runner.def", "image.sif")
    first = WorkflowStage(
        "live.first", "First", False, (), ("first",),
        outputs=(StagePortSpec("out", "x", path="first.dat"),),
    )
    second = WorkflowStage(
        "live.second", "Second", False, (), ("second",),
        inputs=(StagePortSpec("in", "x", source="live.first:out"),),
    )
    task_type = TaskType(
        "live", "Live", runtime, (),
        stage_markers={"first": "First", "second": "Second"},
        workflow=(first, second),
    )
    graph = execution_graph_payload(task_type)
    form = json.loads(
        live_test_executor._task_input_form([], tmp_path / "inputs", "live-key", {}, {}, {}, graph)
    )

    frozen = task_runtime._frozen_execution_graph({"input_form": json.dumps(form)})

    assert frozen is not None
    assert frozen["digest"] == graph["digest"]


def test_composed_live_test_pins_every_referenced_family(monkeypatch, tmp_path):
    from dataclasses import replace

    from revocompute import runtime_bundle
    from revocompute.task_types import get, get_family

    base, _ = get("multistage_runner")
    foreign_runtime, _ = get_family("cpu_runner")
    composed = replace(
        base,
        workflow=(base.workflow[0], replace(base.workflow[1], family=foreign_runtime.name)),
    )
    runner_root = tmp_path / "runner_root"
    for family in (base.runtime, foreign_runtime):
        for relative in family.runtime_overlay:
            path = runner_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(family.name, encoding="utf-8")
    store = tmp_path / "bundles"
    published = {
        family.name: runtime_bundle.materialize(runner_root, family.runtime_overlay, store)[0]
        for family in (base.runtime, foreign_runtime)
    }
    runtime_bundle.write_index(store, published)
    for relative in base.runtime.runtime_overlay:
        (runner_root / relative).write_text("candidate", encoding="utf-8")
    candidate = runtime_bundle.materialize(runner_root, base.runtime.runtime_overlay, store)[0]
    assert candidate != published[base.runtime.name]
    monkeypatch.setattr(
        live_test_executor.task_runtime,
        "CONFIG",
        replace(live_test_executor.task_runtime.CONFIG, runtime_bundle_root=str(store)),
    )

    pins = live_test_executor._pinned_runtime_bundles(composed, candidate)

    assert pins == {
        base.runtime.name: candidate,
        foreign_runtime.name: published[foreign_runtime.name],
    }

    runtime_bundle.write_index(store, {base.runtime.name: published[base.runtime.name]})
    with pytest.raises(ValueError, match="runtime bundle is unavailable"):
        live_test_executor._pinned_runtime_bundles(composed, candidate)


def test_gpu_accounting_uses_any_gpu_stage_in_the_graph(monkeypatch):
    from revocompute.task_types import RuntimeFamily, TaskType, WorkflowStage

    runtime = RuntimeFamily("live_cpu_family", ("bash", "run.sh"), "runner.def", "image.sif")
    cpu = WorkflowStage("live.prepare", "Prepare", False, (), ("prepare",))
    gpu = WorkflowStage("live.model", "Model", True, (), ("model",))
    task_type = TaskType(
        "live_cpu", "Live CPU", runtime, (), gpus=False,
        stage_markers={"prepare": "Prepare", "model": "Model"},
        workflow=(cpu, gpu),
    )
    published = []
    monkeypatch.setattr(
        live_test_executor.task_runtime.task_store,
        "project_gpu_authorization",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        live_test_executor.task_runtime.task_store,
        "gpu_credit_summary",
        lambda _user_id: {"period": "2026-10", "remaining_gpu_seconds": 10},
    )
    monkeypatch.setattr(
        live_test_executor, "atomic_write_json", lambda path, payload: published.append((path, payload))
    )

    context = live_test_executor._prepare_gpu_accounting(task_type)

    assert context == {
        "user_id": live_test_executor._LIVE_TEST_GPU_USER_ID,
        "before": {"period": "2026-10", "remaining_gpu_seconds": 10},
    }
    assert published


def test_worker_executor_records_every_workflow_scheduler_identity(monkeypatch):
    users = {"41": None, "42": "revodesign"}
    monkeypatch.setattr(live_test_executor, "_scheduler_user", users.get)
    monkeypatch.setattr(
        live_test_executor,
        "_scheduler_resource_observation",
        lambda job_id, _output_root=None: {"job_id": job_id, "accounting_available": True, "rows": []},
    )
    evidence = live_test_executor._evidence({
        "status": "finished",
        "slurm_job_id": "42",
        "workflow_state": json.dumps({
            "features": {"job_id": "41", "status": "completed"},
            "model": {"job_id": "42", "status": "completed"},
        }),
    })
    assert [job["scheduler_user"] for job in evidence["slurm_jobs"]] == ["revodesign", "revodesign"]
    assert evidence["scheduler_user"] == "revodesign"


def test_worker_executor_rejects_conflicting_workflow_scheduler_identities(monkeypatch):
    monkeypatch.setattr(live_test_executor, "_scheduler_user", {"41": "revodesign", "42": "yinying"}.get)
    monkeypatch.setattr(
        live_test_executor,
        "_scheduler_resource_observation",
        lambda job_id, _output_root=None: {"job_id": job_id, "accounting_available": True, "rows": []},
    )
    evidence = live_test_executor._evidence({
        "status": "finished",
        "workflow_state": json.dumps({
            "features": {"job_id": "41", "status": "completed"},
            "model": {"job_id": "42", "status": "completed"},
        }),
    })
    assert evidence["scheduler_user"] is None


def test_scheduler_resource_observation_records_core_and_optional_accelerator_metrics(monkeypatch):
    responses = iter(
        (
            SimpleNamespace(
                returncode=0,
                stdout="42|COMPLETED|11|4|cpu=4,gres/gpu:a100=1|00:00:09|128M|\n",
            ),
            SimpleNamespace(
                returncode=0,
                stdout="42.batch|gres/gpumem=2048M,gres/gpuutil=76|gres/gpuutil=54|\n",
            ),
        )
    )
    monkeypatch.setattr(live_test_executor.subprocess, "run", lambda *args, **kwargs: next(responses))

    observation = live_test_executor._scheduler_resource_observation("42")

    assert observation["accounting_available"] is True
    assert observation["rows"] == [
        {
            "JobIDRaw": "42",
            "State": "COMPLETED",
            "ElapsedRaw": "11",
            "AllocCPUS": "4",
            "AllocTRES": "cpu=4,gres/gpu:a100=1",
            "TotalCPU": "00:00:09",
            "MaxRSS": "128M",
        }
    ]
    assert observation["accelerator_metrics_available"] is True
    assert observation["accelerator_rows"][0]["TRESUsageInMax"] == "gres/gpumem=2048M,gres/gpuutil=76"


def test_scheduler_resource_observation_fails_closed_on_unavailable_accounting(monkeypatch):
    monkeypatch.setattr(
        live_test_executor.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="private scheduler detail"),
    )

    observation = live_test_executor._scheduler_resource_observation("42")

    assert observation == {
        "job_id": "42",
        "accounting_available": False,
        "rows": [],
        "accelerator_metrics_available": False,
        "accelerator_rows": [],
    }


def test_scheduler_resource_observation_uses_bounded_wrapper_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(
        live_test_executor.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="accounting disabled"),
    )
    execution = tmp_path / "execution"
    execution.mkdir()
    (execution / "slurm-demo.resource.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "allocation_wrapper",
                "job_id": "42",
                "allocated_cpus_per_task": 4,
                "allocated_tasks": 1,
                "exit_code": 0,
                "elapsed_seconds": 1.2,
                "user_cpu_seconds": 0.8,
                "system_cpu_seconds": 0.1,
                "max_rss_kib": 1024,
                "gpu_memory_peak_mib": 512,
                "gpu_utilization_peak_percent": 60,
            }
        ),
        encoding="utf-8",
    )

    observation = live_test_executor._scheduler_resource_observation("42", tmp_path)

    assert observation["accounting_available"] is True
    assert observation["source"] == "allocation_wrapper"
    assert observation["accelerator_metrics_available"] is True
    assert observation["wrapper"]["max_rss_kib"] == 1024


def test_scheduler_resource_observation_accepts_a_wrapper_payload_with_scratch_evidence(
    monkeypatch, tmp_path
):
    """A current wrapper payload carries the guard's fields and must still read.

    The allocation wrapper reports the scratch capacity guard's measurements
    alongside the scheduler facts.  A reader with a stale allowlist would treat
    the whole payload as unknown content, report ``accounting_available: False``
    where the wrapper did report accounting, and fall back to ``sacct`` — which
    is not always enabled.
    """
    monkeypatch.setattr(
        live_test_executor.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="accounting disabled"),
    )
    execution = tmp_path / "execution"
    execution.mkdir()
    (execution / "slurm-demo.resource.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "allocation_wrapper",
                "job_id": "42",
                "allocated_cpus_per_task": 4,
                "allocated_tasks": 1,
                "exit_code": 0,
                "elapsed_seconds": 1.2,
                "user_cpu_seconds": 0.8,
                "system_cpu_seconds": 0.1,
                "max_rss_kib": 1024,
                "scratch_guard.peak_bytes": 3145728,
                "scratch_guard.samples": 4,
                "scratch_guard.exceeded": 1,
            }
        ),
        encoding="utf-8",
    )

    observation = live_test_executor._scheduler_resource_observation("42", tmp_path)

    assert observation["accounting_available"] is True
    assert observation["source"] == "allocation_wrapper"
    assert observation["wrapper"]["max_rss_kib"] == 1024
    assert observation["wrapper"]["scratch_guard.exceeded"] == 1


def test_wrapper_resource_observation_rejects_oversized_or_unknown_content(tmp_path):
    execution = tmp_path / "execution"
    execution.mkdir()
    candidate = execution / "slurm-demo.resource.json"
    candidate.write_text(
        json.dumps({"source": "allocation_wrapper", "job_id": "42", "secret": "do-not-publish"}),
        encoding="utf-8",
    )
    assert live_test_executor._wrapper_resource_observation("42", tmp_path) is None

    candidate.write_text(" " * 8193, encoding="utf-8")
    assert live_test_executor._wrapper_resource_observation("42", tmp_path) is None


def test_gpu_live_case_seeds_isolated_authorization_and_reports_exact_settlement(monkeypatch, tmp_path):
    """A GPU live case seeds its own authorization, readiness, and balance.

    The projector half of the acceptance: the case must provision the isolated
    state its own admission needs, and the settlement it reports must be the
    canonical one.  The validator half — the projector's real output passed
    unchanged into ``_gpu_accounting_valid``, including the CPU-only and core-unit
    rows a GPU settlement must ignore — lives in
    ``tests/server/test_gpu_accounting_acceptance.py``.
    """
    database = TaskDatabase(str(tmp_path / "gpu-live.sqlite3"))
    monkeypatch.setattr(live_test_executor.task_runtime, "task_store", database)
    monkeypatch.setattr(
        live_test_executor.task_runtime,
        "CONFIG",
        SimpleNamespace(server_dir=str(tmp_path)),
    )
    task_type = SimpleNamespace(
        gpus=True,
        runtime=SimpleNamespace(
            name="gpu-demo",
            access_policy=SimpleNamespace(requires=("licensed",)),
        ),
    )

    context = live_test_executor._prepare_gpu_accounting(task_type)
    assert context is not None
    database.require_gpu_authorization(1, required_entitlements=("licensed",))
    readiness = json.loads((tmp_path / "readiness" / "gpu-demo.json").read_text(encoding="utf-8"))
    assert readiness["ready"] is True

    started_at = time.time()
    database.record_allocation_start(
        user_id=1,
        task_id="a" * 32,
        stage_id="model",
        slurm_job_id="42",
        gpu_count=2,
        cpu_cores=1,
        started_at=started_at,
        required_entitlements=("licensed",),
    )
    database.settle_allocation_elapsed("42", elapsed_seconds=7, finished_at=started_at + 7)

    evidence = live_test_executor._gpu_accounting_evidence("a" * 32, context)
    assert evidence is not None
    assert evidence["usage_gpu_seconds"] == 14
    assert evidence["before_remaining_gpu_seconds"] - evidence["after_remaining_gpu_seconds"] == 14
    assert evidence["allocations"][0]["status"] == "settled"
    assert evidence["usage_entries"][0]["quantity"] == -14


@pytest.mark.parametrize("payload", [
    {"task_id": "../escape", "task_type": "x", "result_path": "/tmp/result", "artifact_path": "/tmp/a", "artifact_sha256": "x"},
    {"task_id": "a" * 32, "task_type": "", "result_path": "/tmp/result", "artifact_path": "/tmp/a", "artifact_sha256": "x"},
    {"task_id": "a" * 32, "task_type": "x", "result_path": "/tmp/result", "artifact_path": "/tmp/a", "artifact_sha256": "x", "extra": 1},
])
def test_worker_executor_rejects_invalid_request(tmp_path, payload):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        live_test_executor.execute(path)
