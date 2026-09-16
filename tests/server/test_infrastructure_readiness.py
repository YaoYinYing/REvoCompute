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
    WorkerInfrastructureProbes,
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


def test_slurm_submission_probe_validates_without_allocating(monkeypatch):
    calls = []
    monkeypatch.setattr(infrastructure, "_run_slurm_query", lambda args: calls.append(args) or "estimate")

    result = infrastructure._slurm_submission_probe()

    assert result.status is InfrastructureStatus.READY
    assert calls == [[
        "srun",
        "--test-only",
        "--nodes=1",
        "--ntasks=1",
        "--cpus-per-task=1",
        "--time=00:01:00",
        "/bin/true",
    ]]


def test_visible_busy_gpu_inventory_remains_ready(monkeypatch):
    monkeypatch.setattr(infrastructure, "_run_slurm_query", lambda _args: "gpu:a100:1 gpu:a100:1\n")

    result = infrastructure._gpu_inventory_probe()

    assert result.status is InfrastructureStatus.READY
    assert result.capacity is CapacityStatus.BUSY


def test_gpu_capacity_uses_allocated_gres_not_node_state(monkeypatch):
    """A MIXED node with its only GPU allocated is BUSY, not AVAILABLE."""
    monkeypatch.setattr(
        infrastructure, "_run_slurm_query", lambda _args: "gpu:a100:1 gpu:a100:1(IDX:0)\n"
    )

    busy = infrastructure._gpu_inventory_probe()
    monkeypatch.setattr(infrastructure, "_run_slurm_query", lambda _args: "gpu:a100:1 (null)\n")
    free = infrastructure._gpu_inventory_probe()

    assert busy.capacity is CapacityStatus.BUSY
    assert free.capacity is CapacityStatus.AVAILABLE


def test_gpu_count_parses_multi_gpu_and_multi_gres_fields():
    assert infrastructure._gpu_count_from_gres("gpu:a100:1, gpu:h100:2") == 3
    assert infrastructure._gpu_count_from_gres("gpu:a100:2(IDX:0-1)") == 2
    assert infrastructure._gpu_count_from_gres("(null)") == 0
    assert infrastructure._gpu_count_from_gres("N/A") == 0


def test_worker_scheduler_probes_share_one_remote_result_per_refresh(tmp_path):
    calls = []
    reason_codes = {
        InfrastructureComponent.SLURM_CONTROLLER: "slurm_controller_healthy",
        InfrastructureComponent.SLURM_SUBMISSION: "slurm_submission_ready",
        InfrastructureComponent.GPU_INVENTORY: "gpu_inventory_visible",
    }
    payload = {
        component.value: ProbeResult(
            InfrastructureStatus.READY,
            reason_codes[component],
            "healthy",
            capacity=CapacityStatus.AVAILABLE,
        ).as_dict()
        for component in reason_codes
    }
    result = SimpleNamespace(get=lambda timeout: calls.append(("get", timeout)) or payload)
    task = SimpleNamespace(apply_async=lambda: calls.append(("apply", None)) or result)
    probes = WorkerInfrastructureProbes(task, str(tmp_path / "evidence.json"), timeout_seconds=3)
    probes.prepare(True)

    assert probes.probe(InfrastructureComponent.SLURM_CONTROLLER).capacity is CapacityStatus.AVAILABLE
    assert probes.probe(InfrastructureComponent.GPU_INVENTORY).status is InfrastructureStatus.READY
    assert calls == [("apply", None), ("get", 3)]

    probes.prepare(True)
    probes.probe(InfrastructureComponent.SLURM_SUBMISSION)
    assert calls == [("apply", None), ("get", 3), ("apply", None), ("get", 3)]


def test_worker_scheduler_probe_failure_is_requested_once_per_refresh(tmp_path):
    calls = []

    def fail(timeout):
        calls.append(timeout)
        raise TimeoutError("worker unavailable")

    task = SimpleNamespace(apply_async=lambda: SimpleNamespace(get=fail))
    probes = WorkerInfrastructureProbes(task, str(tmp_path / "evidence.json"), timeout_seconds=3)
    probes.prepare(True)

    for component in (InfrastructureComponent.SLURM_CONTROLLER, InfrastructureComponent.GPU_INVENTORY):
        with pytest.raises(TimeoutError, match="worker unavailable"):
            probes.probe(component)
    assert calls == [3]


def test_worker_scheduler_probes_read_snapshot_without_queueing(tmp_path):
    snapshot = tmp_path / "evidence.json"
    snapshot.write_text(
        '{"slurm_controller":{"status":"READY","reason_code":"slurm_controller_healthy",'
        '"message":"healthy","capacity":"BUSY"}}',
        encoding="utf-8",
    )
    queued = []
    probes = WorkerInfrastructureProbes(
        SimpleNamespace(apply_async=lambda: queued.append(True)),
        str(snapshot),
    )
    probes.prepare(False)

    result = probes.probe(InfrastructureComponent.SLURM_CONTROLLER)

    assert result.capacity is CapacityStatus.BUSY
    assert queued == []


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


def test_compute_worker_probe_task_returns_only_typed_scheduler_evidence(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_runtime = module.task_runtime
    monkeypatch.setattr(
        task_runtime,
        "_slurm_controller_probe",
        lambda: ProbeResult(
            InfrastructureStatus.READY,
            "slurm_controller_healthy",
            "healthy",
            capacity=CapacityStatus.BUSY,
        ),
    )
    monkeypatch.setattr(
        task_runtime,
        "_slurm_submission_probe",
        lambda: ProbeResult(InfrastructureStatus.READY, "slurm_submission_ready", "healthy"),
    )
    monkeypatch.setattr(
        task_runtime,
        "_gpu_inventory_probe",
        lambda: ProbeResult(
            InfrastructureStatus.READY,
            "gpu_inventory_visible",
            "healthy",
            capacity=CapacityStatus.AVAILABLE,
        ),
    )

    payload = task_runtime.probe_compute_infrastructure.run()

    assert set(payload) == {"slurm_controller", "slurm_submission", "gpu_inventory"}
    assert payload["slurm_controller"]["capacity"] == "BUSY"
    assert payload["gpu_inventory"]["capacity"] == "AVAILABLE"


def _service_with_gpu_evidence(gpu_status: InfrastructureStatus) -> InfrastructureReadinessService:
    def ready() -> ProbeResult:
        return ProbeResult(InfrastructureStatus.READY, "process_healthy", "healthy")

    probes = {component: ready for component in InfrastructureReadinessService.COMMON_SLURM_COMPONENTS}
    probes[InfrastructureComponent.GPU_INVENTORY] = lambda: ProbeResult(
        gpu_status,
        "gpu_inventory_visible" if gpu_status is InfrastructureStatus.READY else "gpu_inventory_unavailable",
        "GPU inventory evidence",
        None,
        CapacityStatus.UNKNOWN if gpu_status is InfrastructureStatus.UNAVAILABLE else CapacityStatus.AVAILABLE,
    )
    return InfrastructureReadinessService(probes)


def test_admission_blocks_are_resource_specific():
    """GPU evidence must not gate CPU work, and the aggregate stays global."""
    service = _service_with_gpu_evidence(InfrastructureStatus.UNAVAILABLE)

    assert service.report()["status"] == "UNAVAILABLE"
    assert service.admission_block(requires_gpu=False) is None
    block = service.admission_block(requires_gpu=True)
    assert block is not None
    assert block["component"] == "gpu_inventory"
    assert block["stale"] is False


def test_admission_allows_both_classes_when_evidence_is_ready():
    service = _service_with_gpu_evidence(InfrastructureStatus.READY)

    assert service.admission_block(requires_gpu=False) is None
    assert service.admission_block(requires_gpu=True) is None
