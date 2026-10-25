# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Readiness can change between preflight and the accepted submission.

Preflight is advice; the submission boundary is the decision.  A Runner that
was READY when the browser checked it, and is not READY when the same request
arrives for execution, must be refused before the request can create a Task ID,
a durable upload, a reservation, or a scheduler submission.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import _load_pssm_module, _test_client_auth


class _AvailableInfrastructure:
    """Infrastructure evidence that would admit the Task if readiness allowed it."""

    def report(self) -> dict:
        return {
            "status": "READY",
            "stale": False,
            "summary": {"scheduler": {"capacity": "AVAILABLE"}, "gpu": {"capacity": "AVAILABLE"}},
        }

    def admission_block(self, **_kwargs):
        return None


def _write_attestation(module, *, status: str, ready: bool, reason: str, next_action: str) -> Path:
    path = Path(module.CONFIG.server_dir) / "readiness" / "cpu_runner.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "runner_family": "cpu_runner",
                "status": status,
                "ready": ready,
                "reason_code": reason,
                "message": "Runner readiness evidence for the race case.",
                "next_action": next_action,
            }
        ),
        encoding="utf-8",
    )
    return path


def _payload() -> dict:
    return {
        "task_type": "cpu_runner",
        "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
        "input_roles": "sequence",
    }


def _durable_uploads(module) -> list[Path]:
    root = Path(module.app.config["UPLOAD_FOLDER"])
    return sorted(path for path in root.rglob("*") if path.is_file())


@pytest.mark.parametrize("mutation", ["stale", "deleted", "malformed"])
def test_readiness_change_between_preflight_and_post_has_no_side_effects(monkeypatch, tmp_path, mutation):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.app.config["manage_db"].resource_set("slurm_enabled", "true")
    module.app.config["infrastructure_readiness"] = _AvailableInfrastructure()
    queued: list[bool] = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *_args, **_kwargs: queued.append(True))

    attestation = _write_attestation(
        module, status="READY", ready=True, reason="READY", next_action="none"
    )
    client = module.app.test_client()
    headers = _test_client_auth(module)

    preflight = client.post(
        "/compute/api/preflight/cpu_runner",
        headers=headers,
        data=_payload(),
        content_type="multipart/form-data",
    )
    assert preflight.status_code == 200, preflight.get_data(as_text=True)
    assert preflight.get_json()["valid"] is True

    # The evidence the browser saw is no longer the evidence the submission reads.
    if mutation == "stale":
        _write_attestation(
            module,
            status="VALIDATION_STALE",
            ready=False,
            reason="RECEIPT_STALE",
            next_action="live-test",
        )
    elif mutation == "deleted":
        attestation.unlink()
    else:
        attestation.write_text('{"runner_family": "cpu_runner",', encoding="utf-8")

    tasks_before = module.task_store.list_tasks()
    reservations_before = module.task_store.list_live_reservations()
    uploads_before = _durable_uploads(module)

    response = client.post("/compute/api/post", headers=headers, data=_payload(), content_type="multipart/form-data")

    assert response.status_code == 503, response.get_data(as_text=True)
    body = response.get_json()
    assert body["runner"] == "cpu_runner"
    assert body["next_action"] in {"live-test", "doctor"}
    if mutation == "stale":
        assert body["status"] == "VALIDATION_STALE"
        assert body["reason"] == "RECEIPT_STALE"
    else:
        # Missing or malformed published evidence fails closed as unavailable.
        assert body["status"] == "NOT_CONFIGURED"

    assert module.task_store.list_tasks() == tasks_before == []
    assert module.task_store.list_live_reservations() == reservations_before == []
    assert _durable_uploads(module) == uploads_before == []
    assert queued == []


def test_direct_post_without_readiness_evidence_is_refused_before_any_side_effect(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.app.config["manage_db"].resource_set("slurm_enabled", "true")
    module.app.config["infrastructure_readiness"] = _AvailableInfrastructure()
    queued: list[bool] = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *_args, **_kwargs: queued.append(True))

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data=_payload(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 503
    assert response.get_json()["reason"] == "RUNNER_UNAVAILABLE"
    assert module.task_store.list_tasks() == []
    assert module.task_store.list_live_reservations() == []
    assert _durable_uploads(module) == []
    assert queued == []
