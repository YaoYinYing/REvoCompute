# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from conftest import _load_pssm_module, _test_client_auth
from revocompute.operational_events import build_event


def _events(module) -> list[dict]:
    path = Path(module.CONFIG.server_dir) / "logs/operational-events.log"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_event_envelope_rejects_unknown_fields_and_bounds_text():
    with pytest.raises(TypeError, match="raw_sequence"):
        build_event("preflight.passed", raw_sequence="ACDE")

    event = build_event("preflight.contract_rejected", reason_code="bad\nvalue" + "x" * 300)
    assert event["reason_code"] == "bad?value" + "x" * 247
    assert len(event["reason_code"]) == 256


def test_request_and_preflight_events_share_safe_request_id(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    response = module.app.test_client().post(
        "/compute/api/preflight/gremlin",
        headers={**_test_client_auth(module), "X-Request-ID": "client-request-42"},
        data={
            "files": (io.BytesIO(b">private-sequence\nACDEFGHIK\n"), "private.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "client-request-42"
    events = _events(module)
    assert [event["event"] for event in events] == [
        "http.request.started",
        "preflight.started",
        "preflight.passed",
        "http.request.finished",
    ]
    assert {event["request_id"] for event in events} == {"client-request-42"}
    serialized = json.dumps(events)
    assert "private-sequence" not in serialized
    assert "private.fasta" not in serialized
    assert "Authorization" not in serialized


def test_submission_persists_and_queues_request_correlation(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    queued: dict = {}

    def enqueue(*args, **kwargs):
        queued.update(args=args, kwargs=kwargs)
        return type("Queued", (), {"id": "celery-42"})()

    monkeypatch.setattr(module.run_compute_task, "apply_async", enqueue)
    response = module.app.test_client().post(
        "/compute/api/post",
        headers={**_test_client_auth(module), "X-Request-ID": "submission-request-42"},
        data={
            "task_type": "gremlin",
            "files": (io.BytesIO(b">private-sequence\nACDEFGHIK\n"), "private.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert queued["kwargs"]["kwargs"]["request_id"] == "submission-request-42"
    task = module.task_store.get_task(response.get_json()["task_id"])
    assert json.loads(task["input_form"])["request_id"] == "submission-request-42"
    events = _events(module)
    assert [event["event"] for event in events] == [
        "http.request.started",
        "task.submission.started",
        "preflight.passed",
        "task.submitted",
        "http.request.finished",
    ]
    submitted = events[-2]
    assert (submitted["request_id"], submitted["task_id"], submitted["celery_task_id"]) == (
        "submission-request-42",
        response.get_json()["task_id"],
        "celery-42",
    )
    assert "private-sequence" not in json.dumps(events)
    assert "private.fasta" not in json.dumps(events)


def test_worker_events_continue_submission_correlation(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    task = {
        "md5sum": "a" * 32,
        "task_type": "gremlin",
        "status": "finished",
        "run_stage": "blast",
        "celery_task_id": "celery-42",
        "input_form": json.dumps({"request_id": "submission-request-42"}),
    }
    monkeypatch.setattr(module.task_runtime.task_store, "get_task", lambda _task_id: task)
    monkeypatch.setattr(module.task_runtime, "_execute_compute_task", lambda *args, **kwargs: None)

    module.task_runtime.run_compute_task.run(task["md5sum"], task_type="gremlin")

    events = _events(module)
    assert [event["event"] for event in events] == [
        "worker.task.started",
        "task.finished",
        "worker.task.finished",
    ]
    assert {event["request_id"] for event in events} == {"submission-request-42"}
    assert {event["task_id"] for event in events} == {task["md5sum"]}
    assert {event["celery_task_id"] for event in events} == {"celery-42"}
