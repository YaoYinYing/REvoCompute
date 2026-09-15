# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from revocompute import infrastructure
from revocompute.infrastructure import (
    CapacityStatus,
    InfrastructureComponent,
    InfrastructureReadinessService,
    InfrastructureStatus,
    ProbeResult,
)


def _clock():
    state = {"wall": datetime(2026, 9, 15, tzinfo=timezone.utc), "mono": 10.0}
    return state, lambda: state["wall"], lambda: state["mono"]


def test_probe_results_reject_unknown_reason_codes():
    with pytest.raises(ValueError, match="Unknown infrastructure reason code"):
        ProbeResult(InfrastructureStatus.READY, "invented_reason", "healthy")


@pytest.mark.parametrize(
    ("free_percent", "expected_status", "expected_reason"),
    [
        (20, InfrastructureStatus.READY, "storage_healthy"),
        (8, InfrastructureStatus.DEGRADED, "disk_space_low"),
        (4, InfrastructureStatus.UNAVAILABLE, "disk_space_critical"),
    ],
)
def test_storage_probe_classifies_free_space(
    monkeypatch, tmp_path, free_percent, expected_status, expected_reason
):
    monkeypatch.setattr(
        infrastructure.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=100, free=free_percent),
    )

    result = infrastructure._storage_probe(str(tmp_path), 10, 5)

    assert (result.status, result.reason_code) == (expected_status, expected_reason)


def test_worker_probe_reports_no_responsive_workers():
    inspect = SimpleNamespace(ping=lambda: None)
    celery_app = SimpleNamespace(control=SimpleNamespace(inspect=lambda timeout: inspect))

    result = infrastructure._worker_probe(celery_app)

    assert result.status is InfrastructureStatus.UNAVAILABLE
    assert result.reason_code == "worker_unavailable"


def test_missing_slurm_commands_are_unavailable_without_affecting_capacity(monkeypatch):
    monkeypatch.setattr(infrastructure.shutil, "which", lambda _command: None)

    controller = infrastructure._slurm_controller_probe()
    submission = infrastructure._slurm_submission_probe()
    gpu = infrastructure._gpu_inventory_probe()

    assert controller.reason_code == "slurm_command_missing"
    assert submission.reason_code == "slurm_submission_command_missing"
    assert gpu.status is InfrastructureStatus.UNAVAILABLE
    assert gpu.capacity is CapacityStatus.UNKNOWN


def test_visible_gpu_inventory_is_ready_with_unknown_transient_capacity(monkeypatch):
    monkeypatch.setattr(infrastructure, "_run_slurm_query", lambda _args: "gpu:a100:1\n")

    result = infrastructure._gpu_inventory_probe()

    assert result.status is InfrastructureStatus.READY
    assert result.capacity is CapacityStatus.UNKNOWN


def test_readiness_aggregates_health_separately_from_capacity():
    state, wall, mono = _clock()
    service = InfrastructureReadinessService(
        {
            InfrastructureComponent.WEB_API: lambda: ProbeResult(
                InfrastructureStatus.READY, "process_healthy", "healthy"
            ),
            InfrastructureComponent.GPU_INVENTORY: lambda: ProbeResult(
                InfrastructureStatus.READY,
                "gpu_inventory_visible",
                "visible",
                capacity=CapacityStatus.BUSY,
            ),
        },
        refresh_seconds=30,
        stale_seconds=60,
        wall_clock=wall,
        monotonic=mono,
        event_emitter=lambda *_args, **_kwargs: None,
    )

    report = service.report()

    assert report["status"] == "READY"
    assert report["summary"]["gpu"] == {
        "label": "GPU",
        "status": "READY",
        "stale": False,
        "capacity": "BUSY",
    }
    assert "components" not in report
    state["mono"] += 1


def test_probe_failure_preserves_last_evidence_and_marks_it_stale():
    state, wall, mono = _clock()
    failing = {"value": False}

    def probe():
        if failing["value"]:
            raise TimeoutError("private backend detail")
        return ProbeResult(
            InfrastructureStatus.READY, "redis_healthy", "Redis is responding."
        )

    service = InfrastructureReadinessService(
        {InfrastructureComponent.REDIS: probe},
        refresh_seconds=0,
        stale_seconds=60,
        wall_clock=wall,
        monotonic=mono,
        event_emitter=lambda *_args, **_kwargs: None,
    )
    first = service.report(admin=True)["components"][0]
    failing["value"] = True
    state["wall"] += timedelta(seconds=1)
    state["mono"] += 1
    second = service.report(force=True, admin=True)["components"][0]

    assert second["status"] == first["status"] == "READY"
    assert second["checked_at"] == first["checked_at"]
    assert second["stale"] is True
    assert second["failure_count"] == 1
    assert second["probe_error_code"] == "probe_failed"
    assert "private backend detail" not in str(second)


def test_evidence_becomes_stale_without_replacing_last_check():
    state, wall, mono = _clock()
    service = InfrastructureReadinessService(
        {
            InfrastructureComponent.WEB_API: lambda: ProbeResult(
                InfrastructureStatus.READY, "process_healthy", "healthy"
            )
        },
        refresh_seconds=120,
        stale_seconds=60,
        wall_clock=wall,
        monotonic=mono,
        event_emitter=lambda *_args, **_kwargs: None,
    )
    first = service.report(admin=True)
    state["wall"] += timedelta(seconds=61)
    state["mono"] += 61
    stale = service.report(admin=True)

    assert stale["stale"] is True
    assert stale["components"][0]["checked_at"] == first["components"][0]["checked_at"]


class _RouteService:
    def __init__(self):
        self.calls = []

    def report(self, *, force=False, admin=False):
        self.calls.append((force, admin))
        payload = {
            "status": "READY",
            "checked_at": "2026-09-15T00:00:00+00:00",
            "stale": False,
            "summary": {},
        }
        if admin:
            payload["components"] = [
                {"component": "web_api", "reason_code": "process_healthy"}
            ]
        return payload


def test_infrastructure_api_is_authenticated_and_hides_admin_evidence(
    monkeypatch, tmp_path
):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    service = _RouteService()
    module.app.config["infrastructure_readiness"] = service
    client = module.app.test_client()

    assert client.get("/compute/api/infrastructure").status_code == 401
    response = client.get(
        "/compute/api/infrastructure", headers=_test_client_auth(module)
    )

    assert response.status_code == 200
    assert "components" not in response.get_json()
    assert service.calls == [(False, False)]


def test_admin_can_refresh_detailed_infrastructure_evidence(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    service = _RouteService()
    module.app.config["infrastructure_readiness"] = service
    client = module.app.test_client()

    response = client.post(
        "/compute/api/auth/admin/infrastructure/refresh",
        headers=_admin_client_auth(module),
    )

    assert response.status_code == 200
    assert response.get_json()["components"][0]["reason_code"] == "process_healthy"
    assert service.calls == [(True, True)]


def test_non_admin_cannot_refresh_infrastructure_evidence(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    module.app.config["infrastructure_readiness"] = _RouteService()

    response = module.app.test_client().post(
        "/compute/api/auth/admin/infrastructure/refresh",
        headers=_test_client_auth(module),
    )

    assert response.status_code == 403
