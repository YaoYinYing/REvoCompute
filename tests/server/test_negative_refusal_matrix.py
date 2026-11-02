# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Negative admission refusals leave no Task, upload, reservation or dispatch.

These are unit-level evidence: the real HTTP submission boundary is driven with
a fake queue, a synthetic SIF and a fake live-test receipt.  They do not claim
target-host Slurm/Apptainer acceptance.  The remaining rows of the release
matrix are proved by the focused suites cited in the campaign record.

A refusal is a decision at the submission boundary, not a later launch failure:
this module pins the two cases that are easy to regress into side effects -- a
disabled TaskType and an artifact that changed after its receipt was written.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from conftest import _load_pssm_module, _pin_runtime_image, _test_client_auth


class _AvailableInfrastructure:
    """Infrastructure evidence that would admit the Task if the Runner allowed it."""

    def report(self) -> dict:
        return {
            "status": "READY",
            "stale": False,
            "summary": {"scheduler": {"capacity": "AVAILABLE"}, "gpu": {"capacity": "AVAILABLE"}},
        }

    def admission_block(self, **_kwargs):
        return None


def _write_attestation(module) -> Path:
    path = Path(module.CONFIG.server_dir) / "readiness" / "cpu_runner.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "runner_family": "cpu_runner",
                "status": "READY",
                "ready": True,
                "reason_code": "READY",
                "message": "Runner readiness evidence for the refusal matrix.",
                "next_action": "none",
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


def test_disabled_task_type_is_refused_before_any_task_upload_or_dispatch(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.app.config["manage_db"].task_type_upsert("cpu_runner", enabled=False)
    queued: list[bool] = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *_args, **_kwargs: queued.append(True))

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data=_payload(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 400, response.get_data(as_text=True)
    assert "disabled" in response.get_json()["error"]
    assert module.task_store.list_tasks() == []
    assert module.task_store.list_live_reservations() == []
    assert _durable_uploads(module) == []
    assert queued == []


def test_a_sif_changed_after_its_receipt_is_refused_before_any_side_effect(monkeypatch, tmp_path):
    """A corrupted active artifact is not the artifact the receipt validated."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.app.config["manage_db"].resource_set("slurm_enabled", "true")
    module.app.config["infrastructure_readiness"] = _AvailableInfrastructure()
    _pin_runtime_image(module, "cpu_runner")
    _write_attestation(module)

    family, _runner = module.task_runtime._get_family("cpu_runner")
    Path(family.slurm_image).write_bytes(b"corrupted after the receipt was written")

    queued: list[bool] = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *_args, **_kwargs: queued.append(True))

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data=_payload(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 503, response.get_data(as_text=True)
    assert response.get_json()["reason"] == "RUNTIME_IMAGE_UNPINNED"
    assert module.task_store.list_tasks() == []
    assert module.task_store.list_live_reservations() == []
    assert _durable_uploads(module) == []
    assert queued == []
