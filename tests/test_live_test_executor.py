# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

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
        "task_id": "a" * 32, "task_type": "easifa", "result_path": str(result_path),
        "artifact_path": str(artifact), "artifact_sha256": "sha256:" + __import__("hashlib").sha256(b"candidate").hexdigest(),
    }))
    with pytest.raises(ValueError, match="invalid schema"):
        live_test_executor.execute(request)


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
    (execution / "slurm-example.resource.json").write_text(
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
            }
        ),
        encoding="utf-8",
    )

    observation = live_test_executor._scheduler_resource_observation("42", tmp_path)

    assert observation["accounting_available"] is True
    assert observation["source"] == "allocation_wrapper"
    assert observation["wrapper"]["max_rss_kib"] == 1024


def test_wrapper_resource_observation_rejects_oversized_or_unknown_content(tmp_path):
    execution = tmp_path / "execution"
    execution.mkdir()
    candidate = execution / "slurm-example.resource.json"
    candidate.write_text(
        json.dumps({"source": "allocation_wrapper", "job_id": "42", "secret": "do-not-publish"}),
        encoding="utf-8",
    )
    assert live_test_executor._wrapper_resource_observation("42", tmp_path) is None

    candidate.write_text(" " * 8193, encoding="utf-8")
    assert live_test_executor._wrapper_resource_observation("42", tmp_path) is None


def test_gpu_live_case_seeds_isolated_authorization_and_reports_exact_settlement(monkeypatch, tmp_path):
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
    database.record_gpu_allocation_start(
        user_id=1,
        task_id="a" * 32,
        stage_id="model",
        slurm_job_id="42",
        gpu_count=2,
        started_at=started_at,
        required_entitlements=("licensed",),
    )
    database.settle_gpu_allocation_elapsed("42", elapsed_seconds=7, finished_at=started_at + 7)

    evidence = live_test_executor._gpu_accounting_evidence("a" * 32, context)
    assert evidence is not None
    assert evidence["usage_gpu_seconds"] == 14
    assert evidence["before_remaining_gpu_seconds"] - evidence["after_remaining_gpu_seconds"] == 14
    assert evidence["allocations"][0]["status"] == "settled"
    assert evidence["usage_entries"][0]["gpu_seconds"] == -14


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
