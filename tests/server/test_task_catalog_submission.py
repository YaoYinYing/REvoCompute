# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The catalog and method detail report the submission decision POST applies.

The projection is server-authoritative and privacy-split: an anonymous reader
sees only whether the method accepts submissions, while an authenticated reader
also sees the server's reason and recovery action.  Neither shape may carry
artifact evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import _load_pssm_module, _test_client_auth


def _write_attestation(module, *, status: str, ready: bool, reason: str, message: str, next_action: str) -> None:
    path = Path(module.CONFIG.server_dir) / "readiness" / "cpu_runner.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "runner_family": "cpu_runner",
                "status": status,
                "ready": ready,
                "reason_code": reason,
                "message": message,
                "next_action": next_action,
                # Admin-only evidence that must never reach the public projection.
                "sif_path": "/deployment/images/cpu_runner_v1.sif",
                "sif_sha256": "sha256:" + "a" * 64,
                "receipt_sif_sha256": "sha256:" + "b" * 64,
            }
        ),
        encoding="utf-8",
    )


def _method(client, name: str, headers: dict[str, str], path: str | None = None) -> dict:
    response = client.get(path or "/compute/api/types", headers=headers)
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    entries = payload["task_types"] if path is None else [payload]
    return next(entry for entry in entries if entry["name"] == name)


def test_catalog_and_detail_project_the_published_submission_decision(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    manage_db = module.app.config["manage_db"]
    client = module.app.test_client()
    auth = _test_client_auth(module)

    # A deployment without the managed Scheduler does not gate submission, so
    # the projection is null rather than a restriction POST would not apply.
    manage_db.resource_set("slurm_enabled", "false")
    assert _method(client, "cpu_runner", auth)["submission"] is None
    assert _method(client, "cpu_runner", {})["submission"] is None

    manage_db.resource_set("slurm_enabled", "true")

    # No published attestation fails closed, and only the authenticated reader
    # is told why.
    missing = _method(client, "cpu_runner", auth)["submission"]
    assert missing["ready"] is False
    assert missing["status"] == "NOT_CONFIGURED"
    assert missing["reason_code"] == "RUNNER_UNAVAILABLE"
    assert missing["next_action"] == "doctor"
    assert _method(client, "cpu_runner", {})["submission"] == {"submittable": False}

    _write_attestation(
        module,
        status="VALIDATION_STALE",
        ready=False,
        reason="RECEIPT_STALE",
        message="Live-test receipt does not match the active Runner identity",
        next_action="live-test",
    )
    blocked = _method(client, "cpu_runner", auth)["submission"]
    assert blocked == {
        "ready": False,
        "status": "VALIDATION_STALE",
        "reason_code": "RECEIPT_STALE",
        "message": "Live-test receipt does not match the active Runner identity",
        "next_action": "live-test",
    }
    assert _method(client, "cpu_runner", {})["submission"] == {"submittable": False}
    # The same decision is on the method detail the deep link reads.
    assert _method(client, "cpu_runner", auth, "/compute/api/types/cpu_runner")["submission"] == blocked

    _write_attestation(
        module,
        status="READY",
        ready=True,
        reason="READY",
        message="Active Runner SIF passed all required current smoke cases",
        next_action="none",
    )
    ready = _method(client, "cpu_runner", auth)["submission"]
    assert ready["ready"] is True
    assert ready["status"] == "READY"
    assert ready["reason_code"] == "READY"
    assert _method(client, "cpu_runner", {})["submission"] == {"submittable": True}

    # No artifact path, digest, or receipt evidence leaves either shape.
    rendered = json.dumps(
        [
            _method(client, "cpu_runner", auth),
            _method(client, "cpu_runner", {}),
            _method(client, "cpu_runner", auth, "/compute/api/types/cpu_runner"),
        ]
    )
    assert "/deployment/images" not in rendered
    assert "sha256:" + "a" * 64 not in rendered
    assert "sha256:" + "b" * 64 not in rendered
    for field in ("sif_path", "sif_sha256", "receipt_sif_sha256", "build_provenance_digest", "evidence"):
        assert field not in rendered
