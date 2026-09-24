# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Behavior coverage for the self-scoped user Task metrics projection."""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone

import conftest
from conftest import _load_pssm_module


def _project(module):
    """The live route module's projection, bound to this test's application."""
    route = module.app.view_functions["current_user_metrics"]
    while hasattr(route, "__wrapped__"):
        route = route.__wrapped__
    return route.__globals__["_project_user_metrics"]


def _task(uploaded_at: float, status: str, walltime: float | None = None, task_type: str = "gremlin") -> dict:
    return {
        "md5sum": "0" * 32,
        "status": status,
        "walltime": walltime,
        "uploaded_at": uploaded_at,
        "task_type": task_type,
    }


def test_user_metrics_projects_counts_runtimes_and_a_bounded_series(monkeypatch, tmp_path):
    """The projection counts persisted rows and never widens the requested window."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    project = _project(module)
    now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc).timestamp()
    day = 86_400
    tasks = [
        _task(now - 1 * day, "finished", 60.0),
        _task(now - 1 * day, "finished", 120.0),
        _task(now - 3 * day, "failed", 30.0),
        _task(now - 20 * day, "finished", 45.0),
    ]

    weekly = project(tasks, window="7d", now=now)

    assert weekly["days"] == 7
    assert weekly["tasks_submitted"] == 3
    assert weekly["tasks_completed"] == 2
    assert weekly["tasks_failed"] == 1
    assert weekly["success_rate"] == 2 / 3
    assert weekly["cpu_tasks"] == 2 and weekly["gpu_tasks"] == 0
    assert weekly["median_runtime_seconds"] == 60.0
    assert weekly["total_runtime_seconds"] == 210.0
    assert weekly["gpu_minutes"] == 0
    assert len(weekly["activity"]) == 7
    assert sum(point["count"] for point in weekly["activity"]) == 3
    assert weekly["activity"][0]["period"] == "2026-09-14"
    assert weekly["activity"][-1]["period"] == "2026-09-20"
    assert weekly["distribution"] == [
        {"task_type": "gremlin", "label": "PSSM-GREMLIN", "gpu": False, "tasks": 3}
    ]

    wider = project(tasks, window="30d", now=now)
    assert wider["tasks_submitted"] == 4
    assert len(wider["activity"]) == 30
    assert project(tasks, window="quarter", now=now)["days"] == 92

    empty = project([], window="7d", now=now)
    assert empty["tasks_submitted"] == 0
    assert empty["success_rate"] is None
    assert empty["median_runtime_seconds"] is None
    assert empty["distribution"] == []
    assert all(point["count"] == 0 for point in empty["activity"])


def test_gpu_task_identity_and_gpu_minutes_follow_the_task_type_contract(monkeypatch, tmp_path):
    """GPU classification resolves through TaskType.gpus, never a TaskType list."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    project = _project(module)
    base, runner = module.task_runtime._get_task_type("gremlin")
    conftest._inject_task_type(
        module,
        replace(base, name="gpu_metrics_test", display_name="GPU Metrics Test", gpus=True),
        runner,
    )
    charged = 600
    module.task_store.record_gpu_allocation_start(
        user_id=1, task_id="a" * 32, stage_id="predict", slurm_job_id="metrics-9001", gpu_count=2
    )
    module.task_store.settle_gpu_allocation_elapsed("metrics-9001", elapsed_seconds=charged // 2)
    now = time.time()
    task = _task(now - 3600, "finished", 60.0, task_type="gpu_metrics_test")
    task["md5sum"] = "a" * 32
    task["submitted_by_user_id"] = 1

    payload = project([task], window="7d", now=now)

    assert payload["gpu_tasks"] == 1 and payload["cpu_tasks"] == 0
    assert payload["gpu_minutes"] == charged / 60
    assert payload["distribution"] == [
        {"task_type": "gpu_metrics_test", "label": "GPU Metrics Test", "gpu": True, "tasks": 1}
    ]


def test_user_metrics_endpoint_is_self_scoped_and_window_parameterised(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    users = module.app.config["user_db"]
    owner = _create_user(users, "metrics-owner")
    other = _create_user(users, "metrics-other")
    now = time.time()
    _insert_task(module, owner, now - 60, "finished", 90.0)
    _insert_task(module, owner, now - 2 * 86_400, "failed", 12.0)
    _insert_task(module, owner, now - 60 * 86_400, "finished", 5.0)
    _insert_task(module, other, now - 60, "finished", 7.0)

    client = module.app.test_client()
    response = client.get("/compute/api/user-metrics?window=7d", headers=_bearer(owner))
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["window"] == "7d"
    assert payload["tasks_submitted"] == 2
    assert payload["tasks_completed"] == 1
    assert payload["tasks_failed"] == 1
    assert payload["success_rate"] == 0.5
    assert payload["total_runtime_seconds"] == 102.0
    assert len(payload["activity"]) == 7

    wide = client.get("/compute/api/user-metrics?window=quarter", headers=_bearer(owner)).get_json()
    assert wide["tasks_submitted"] == 3
    assert len(wide["activity"]) == 92
    defaulted = client.get("/compute/api/user-metrics", headers=_bearer(owner)).get_json()
    assert defaulted["window"] == "30d"
    assert defaulted["days"] == 30
    assert defaulted["tasks_submitted"] == 2

    # A different user's Tasks never appear in the response.
    assert client.get("/compute/api/user-metrics", headers=_bearer(other)).get_json()["tasks_submitted"] == 1
    assert client.get("/compute/api/user-metrics?window=all", headers=_bearer(owner)).status_code == 400
    assert client.get("/compute/api/user-metrics").status_code == 401


def _create_user(database, username: str) -> dict:
    user = database.create_user(
        username=username,
        email=f"{username}@test.local",
        password="password123",
        registration_status="approved",
        user_status="active",
    )
    database.verify_email(user["id"])
    return database.get_user(user["id"])


def _bearer(user: dict) -> dict[str, str]:
    from revocompute.auth import generate_token

    return {"Authorization": f"Bearer {generate_token(user['id'])}"}


def _insert_task(module, owner: dict, uploaded_at: float, status: str, walltime: float) -> str:
    md5sum = uuid.uuid4().hex
    module.task_store.upsert_task(
        md5sum,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=uploaded_at,
        finished_at=uploaded_at + walltime,
        walltime=walltime,
        status=status,
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username=owner["username"],
        task_type="gremlin",
        submitted_by_user_id=int(owner["id"]),
        storage_key=owner["storage_key"],
    )
    return md5sum
