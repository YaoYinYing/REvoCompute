# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
from pathlib import Path

import pytest

from revocompute import live_test_executor


def test_worker_executor_records_execution_identity_and_scheduler(tmp_path, monkeypatch):
    request = tmp_path / "request.json"
    result_path = tmp_path / "evidence.json"
    artifact = tmp_path / "candidate.sif"
    artifact.write_bytes(b"candidate")
    request.write_text(json.dumps({
        "task_id": "a" * 32, "task_type": "easifa", "result_path": str(result_path),
        "artifact_path": str(artifact), "artifact_sha256": "sha256:" + __import__("hashlib").sha256(b"candidate").hexdigest(),
    }))
    monkeypatch.setattr(live_test_executor.task_runtime, "_execute_compute_task", lambda *_args: None)
    monkeypatch.setattr(live_test_executor.task_runtime.task_store, "get_task", lambda _task_id: {
        "status": "finished", "error": None, "slurm_job_id": "42", "workflow_state": None,
    })
    monkeypatch.setattr(live_test_executor, "_scheduler_user", lambda _job_id: "revodesign")
    evidence = live_test_executor.execute(request)
    assert evidence["execution_uid"] == live_test_executor.os.getuid()
    assert evidence["execution_gid"] == live_test_executor.os.getgid()
    assert evidence["scheduler_user"] == "revodesign"
    assert json.loads(result_path.read_text()) == evidence


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
