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
    evidence = live_test_executor._evidence({
        "status": "finished",
        "workflow_state": json.dumps({
            "features": {"job_id": "41", "status": "completed"},
            "model": {"job_id": "42", "status": "completed"},
        }),
    })
    assert evidence["scheduler_user"] is None


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
