# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Core-owned infrastructure readiness and transient capacity evidence."""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping

from revocompute.config import env_float, env_int
from revocompute.operational_events import emit_event
from revocompute.redis_util import get_redis


class InfrastructureStatus(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class CapacityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    UNKNOWN = "UNKNOWN"


class InfrastructureComponent(StrEnum):
    WEB_API = "web_api"
    REDIS = "redis"
    CELERY_WORKER = "celery_worker"
    TASK_DATABASE = "task_database"
    USER_DATABASE = "user_database"
    TASK_STORAGE = "task_storage"
    RESULT_STORAGE = "result_storage"
    SCRATCH_STORAGE = "scratch_storage"
    SLURM_CONTROLLER = "slurm_controller"
    SLURM_SUBMISSION = "slurm_submission"
    GPU_INVENTORY = "gpu_inventory"


INFRASTRUCTURE_REASON_CODES = frozenset(
    {
        "process_healthy",
        "redis_healthy",
        "redis_unreachable",
        "worker_healthy",
        "worker_unavailable",
        "database_healthy",
        "storage_healthy",
        "storage_unwritable",
        "disk_space_low",
        "disk_space_critical",
        "slurm_command_missing",
        "slurm_controller_unreachable",
        "slurm_controller_healthy",
        "slurm_submission_command_missing",
        "slurm_submission_ready",
        "gpu_inventory_command_missing",
        "gpu_inventory_unavailable",
        "gpu_inventory_empty",
        "gpu_inventory_visible",
    }
)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    status: InfrastructureStatus
    reason_code: str
    message: str
    next_action: str | None = None
    capacity: CapacityStatus | None = None
    checked_at: str | None = None

    def __post_init__(self) -> None:
        if self.reason_code not in INFRASTRUCTURE_REASON_CODES:
            raise ValueError(f"Unknown infrastructure reason code: {self.reason_code}")

    def as_dict(self) -> dict[str, str]:
        payload = {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "message": self.message,
        }
        if self.next_action:
            payload["next_action"] = self.next_action
        if self.capacity:
            payload["capacity"] = self.capacity.value
        if self.checked_at:
            payload["checked_at"] = self.checked_at
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ProbeResult:
        return cls(
            status=InfrastructureStatus(payload["status"]),
            reason_code=str(payload["reason_code"]),
            message=str(payload["message"]),
            next_action=str(payload["next_action"]) if payload.get("next_action") else None,
            capacity=CapacityStatus(payload["capacity"]) if payload.get("capacity") else None,
            checked_at=str(payload["checked_at"]) if payload.get("checked_at") else None,
        )


@dataclass(frozen=True, slots=True)
class ComponentEvidence:
    component: InfrastructureComponent
    status: InfrastructureStatus
    reason_code: str
    message: str
    checked_at: str
    duration_ms: int
    failure_count: int = 0
    next_action: str | None = None
    capacity: CapacityStatus | None = None
    stale: bool = False
    last_attempted_at: str | None = None
    probe_error_code: str | None = None

    def as_dict(self, *, admin: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "component": self.component.value,
            "status": self.status.value,
            "checked_at": self.checked_at,
            "stale": self.stale,
        }
        if self.capacity is not None:
            payload["capacity"] = self.capacity.value
        if admin:
            payload.update(
                reason_code=self.reason_code,
                message=self.message,
                duration_ms=self.duration_ms,
                failure_count=self.failure_count,
            )
            if self.next_action:
                payload["next_action"] = self.next_action
            if self.last_attempted_at:
                payload["last_attempted_at"] = self.last_attempted_at
            if self.probe_error_code:
                payload["probe_error_code"] = self.probe_error_code
        return payload


Probe = Callable[[], ProbeResult]


class InfrastructureReadinessService:
    """Run bounded probes and retain the last successful component evidence."""

    def __init__(
        self,
        probes: Mapping[InfrastructureComponent, Probe],
        *,
        refresh_seconds: int = 15,
        stale_seconds: int = 60,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        event_emitter: Callable[..., Any] = emit_event,
        before_refresh: Callable[[bool], None] | None = None,
    ) -> None:
        if refresh_seconds < 0 or stale_seconds < 1:
            raise ValueError("Infrastructure refresh and stale intervals are invalid")
        self._probes = dict(probes)
        self._refresh_seconds = refresh_seconds
        self._stale_seconds = stale_seconds
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic
        self._emit_event = event_emitter
        self._before_refresh = before_refresh
        self._evidence: dict[InfrastructureComponent, ComponentEvidence] = {}
        self._last_refresh_monotonic: float | None = None
        self._lock = threading.Lock()

    def report(self, *, force: bool = False, admin: bool = False) -> dict[str, Any]:
        with self._lock:
            now_mono = self._monotonic()
            if (
                force
                or self._last_refresh_monotonic is None
                or (now_mono - self._last_refresh_monotonic >= self._refresh_seconds)
            ):
                self._refresh_locked(force=force)
            evidence = self._with_current_staleness(self._wall_clock())
        return self._serialize(evidence, admin=admin)

    def _refresh_locked(self, *, force: bool) -> None:
        refresh_started = self._monotonic()
        if self._before_refresh:
            self._before_refresh(force)
        for component, probe in self._probes.items():
            started = self._monotonic()
            attempted_at = self._iso(self._wall_clock())
            previous = self._evidence.get(component)
            try:
                result = probe()
                current = ComponentEvidence(
                    component=component,
                    status=result.status,
                    reason_code=result.reason_code,
                    message=result.message,
                    checked_at=result.checked_at or attempted_at,
                    duration_ms=max(0, round((self._monotonic() - started) * 1000)),
                    next_action=result.next_action,
                    capacity=result.capacity,
                )
            except Exception:  # Probe failures are evidence, never request failures.
                duration_ms = max(0, round((self._monotonic() - started) * 1000))
                if previous is not None:
                    current = replace(
                        previous,
                        duration_ms=duration_ms,
                        failure_count=previous.failure_count + 1,
                        stale=True,
                        last_attempted_at=attempted_at,
                        probe_error_code="probe_failed",
                    )
                else:
                    current = ComponentEvidence(
                        component=component,
                        status=InfrastructureStatus.UNAVAILABLE,
                        reason_code="probe_failed",
                        message="Readiness evidence is unavailable.",
                        checked_at=attempted_at,
                        duration_ms=duration_ms,
                        failure_count=1,
                        next_action="Inspect the component and retry the readiness check.",
                        stale=True,
                        last_attempted_at=attempted_at,
                        probe_error_code="probe_failed",
                    )
            self._evidence[component] = current
            self._emit_event(
                "infrastructure.check.completed",
                component=component.value,
                state=current.status.value,
                reason_code=current.probe_error_code or current.reason_code,
                duration_ms=current.duration_ms,
                level=(
                    "ERROR"
                    if current.status is InfrastructureStatus.UNAVAILABLE
                    else "INFO"
                ),
            )
            if previous is not None and previous.status is not current.status:
                self._emit_event(
                    "infrastructure.readiness.changed",
                    component=component.value,
                    state=current.status.value,
                    reason_code=current.reason_code,
                    level=(
                        "ERROR"
                        if current.status is InfrastructureStatus.UNAVAILABLE
                        else "INFO"
                    ),
                )
        self._last_refresh_monotonic = max(refresh_started, self._monotonic())

    def _with_current_staleness(self, now: datetime) -> list[ComponentEvidence]:
        result = []
        for evidence in self._evidence.values():
            checked_at = datetime.fromisoformat(evidence.checked_at)
            stale = (
                evidence.stale
                or (now - checked_at).total_seconds() > self._stale_seconds
            )
            result.append(replace(evidence, stale=stale))
        return sorted(result, key=lambda item: item.component.value)

    def _serialize(
        self, evidence: list[ComponentEvidence], *, admin: bool
    ) -> dict[str, Any]:
        overall = _aggregate_status(item.status for item in evidence)
        checked_at = max(
            (item.checked_at for item in evidence),
            default=self._iso(self._wall_clock()),
        )
        by_component = {item.component: item for item in evidence}
        groups = {
            "infrastructure": _group("Infrastructure", evidence),
            "scheduler": _group(
                "Scheduler",
                [
                    by_component[item]
                    for item in (
                        InfrastructureComponent.SLURM_CONTROLLER,
                        InfrastructureComponent.SLURM_SUBMISSION,
                    )
                    if item in by_component
                ],
                capacity=_capacity(
                    by_component.get(InfrastructureComponent.SLURM_CONTROLLER)
                ),
            ),
            "gpu": _group(
                "GPU",
                (
                    [by_component[InfrastructureComponent.GPU_INVENTORY]]
                    if InfrastructureComponent.GPU_INVENTORY in by_component
                    else []
                ),
                capacity=_capacity(
                    by_component.get(InfrastructureComponent.GPU_INVENTORY)
                ),
            ),
            "worker": _group(
                "Worker",
                (
                    [by_component[InfrastructureComponent.CELERY_WORKER]]
                    if InfrastructureComponent.CELERY_WORKER in by_component
                    else []
                ),
            ),
            "storage": _group(
                "Storage",
                [
                    by_component[item]
                    for item in (
                        InfrastructureComponent.TASK_STORAGE,
                        InfrastructureComponent.RESULT_STORAGE,
                        InfrastructureComponent.SCRATCH_STORAGE,
                    )
                    if item in by_component
                ],
            ),
        }
        payload: dict[str, Any] = {
            "status": overall.value,
            "checked_at": checked_at,
            "stale": any(item.stale for item in evidence),
            "summary": groups,
        }
        if admin:
            payload["components"] = [item.as_dict(admin=True) for item in evidence]
        return payload

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


def _aggregate_status(statuses) -> InfrastructureStatus:
    values = list(statuses)
    if not values or InfrastructureStatus.UNAVAILABLE in values:
        return InfrastructureStatus.UNAVAILABLE
    if InfrastructureStatus.DEGRADED in values:
        return InfrastructureStatus.DEGRADED
    return InfrastructureStatus.READY


def _capacity(evidence: ComponentEvidence | None) -> CapacityStatus:
    return (
        evidence.capacity if evidence and evidence.capacity else CapacityStatus.UNKNOWN
    )


def _group(
    label: str,
    evidence: list[ComponentEvidence],
    *,
    capacity: CapacityStatus | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "label": label,
        "status": _aggregate_status(item.status for item in evidence).value,
        "stale": not evidence or any(item.stale for item in evidence),
    }
    if capacity is not None:
        payload["capacity"] = capacity.value
    return payload


class WorkerInfrastructureProbes:
    """Fetch scheduler and GPU evidence once per refresh from the compute worker."""

    def __init__(self, probe_task, snapshot_path: str, *, timeout_seconds: int = 8) -> None:
        self._probe_task = probe_task
        self._snapshot_path = Path(snapshot_path)
        self._timeout_seconds = timeout_seconds
        self._results: dict[str, ProbeResult] | None = None
        self._error: Exception | None = None
        self._force = False

    def prepare(self, force: bool) -> None:
        self._results = None
        self._error = None
        self._force = force

    def probe(self, component: InfrastructureComponent) -> ProbeResult:
        if self._error is not None:
            raise self._error
        if self._results is None:
            try:
                if self._force:
                    async_result = self._probe_task.apply_async()
                    payload = async_result.get(timeout=self._timeout_seconds)
                else:
                    payload = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("Worker infrastructure probe returned an invalid response")
                self._results = {
                    str(name): ProbeResult.from_dict(result)
                    for name, result in payload.items()
                    if isinstance(result, dict)
                }
            except Exception as exc:
                self._error = exc
                raise
        try:
            return self._results[component.value]
        except KeyError as exc:
            raise ValueError(f"Worker infrastructure probe omitted {component.value}") from exc


def build_default_service(
    config, *, celery_app, task_store, user_db, worker_probe_task
) -> InfrastructureReadinessService:
    warning_percent = env_float("INFRA_DISK_WARNING_PERCENT_FREE", 10.0)
    critical_percent = env_float("INFRA_DISK_CRITICAL_PERCENT_FREE", 5.0)
    if not 0 <= critical_percent <= warning_percent <= 100:
        raise ValueError(
            "Infrastructure disk thresholds must satisfy 0 <= critical <= warning <= 100"
        )

    def database_probe(database, label: str) -> Probe:
        def probe() -> ProbeResult:
            with database.engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1").scalar_one()
            parent = Path(database.path).resolve().parent
            with tempfile.NamedTemporaryFile(prefix=".readiness-", dir=parent):
                pass
            return ProbeResult(
                InfrastructureStatus.READY,
                "database_healthy",
                f"{label} is readable and writable.",
            )

        return probe

    worker_probes = WorkerInfrastructureProbes(
        worker_probe_task,
        os.path.join(config.server_dir, "readiness", "infrastructure.json"),
    )
    probes: dict[InfrastructureComponent, Probe] = {
        InfrastructureComponent.WEB_API: lambda: ProbeResult(
            InfrastructureStatus.READY,
            "process_healthy",
            "The web API process is responding.",
        ),
        InfrastructureComponent.REDIS: _redis_probe,
        InfrastructureComponent.CELERY_WORKER: lambda: _worker_probe(celery_app),
        InfrastructureComponent.TASK_DATABASE: database_probe(
            task_store, "Task database"
        ),
        InfrastructureComponent.USER_DATABASE: database_probe(user_db, "User database"),
        InfrastructureComponent.TASK_STORAGE: lambda: _storage_probe(
            config.workspace_folder, warning_percent, critical_percent
        ),
        InfrastructureComponent.RESULT_STORAGE: lambda: _storage_probe(
            config.results_folder, warning_percent, critical_percent
        ),
        InfrastructureComponent.SCRATCH_STORAGE: lambda: _storage_probe(
            "/dev/shm" if config.scratch_backend == "ram" else config.workspace_folder,
            warning_percent,
            critical_percent,
        ),
        InfrastructureComponent.SLURM_CONTROLLER: lambda: worker_probes.probe(
            InfrastructureComponent.SLURM_CONTROLLER
        ),
        InfrastructureComponent.SLURM_SUBMISSION: lambda: worker_probes.probe(
            InfrastructureComponent.SLURM_SUBMISSION
        ),
        InfrastructureComponent.GPU_INVENTORY: lambda: worker_probes.probe(
            InfrastructureComponent.GPU_INVENTORY
        ),
    }
    return InfrastructureReadinessService(
        probes,
        refresh_seconds=env_int("INFRA_REFRESH_SECONDS", 15),
        stale_seconds=env_int("INFRA_STALE_SECONDS", 60),
        before_refresh=worker_probes.prepare,
    )


def publish_worker_probe_snapshot(path: str, payload: Mapping[str, Any]) -> None:
    """Atomically publish bounded worker evidence into shared deployment storage."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _redis_probe() -> ProbeResult:
    get_redis.cache_clear()
    if get_redis() is None:
        return ProbeResult(
            InfrastructureStatus.UNAVAILABLE,
            "redis_unreachable",
            "Redis is unavailable.",
            "Restore Redis connectivity.",
        )
    return ProbeResult(
        InfrastructureStatus.READY, "redis_healthy", "Redis is responding."
    )


def _worker_probe(celery_app) -> ProbeResult:
    replies = celery_app.control.inspect(timeout=1.0).ping() or {}
    if not replies:
        return ProbeResult(
            InfrastructureStatus.UNAVAILABLE,
            "worker_unavailable",
            "No compute worker responded.",
            "Start or inspect the compute worker.",
        )
    return ProbeResult(
        InfrastructureStatus.READY, "worker_healthy", "A compute worker is responding."
    )


def _storage_probe(
    path: str, warning_percent: float, critical_percent: float
) -> ProbeResult:
    target = Path(path)
    if not target.is_dir() or not os.access(target, os.R_OK | os.W_OK | os.X_OK):
        return ProbeResult(
            InfrastructureStatus.UNAVAILABLE,
            "storage_unwritable",
            "Required storage is unavailable.",
            "Restore the storage mount and write permissions.",
        )
    usage = shutil.disk_usage(target)
    free_percent = (usage.free / usage.total * 100) if usage.total else 0.0
    if free_percent <= critical_percent:
        return ProbeResult(
            InfrastructureStatus.UNAVAILABLE,
            "disk_space_critical",
            "Required storage has critically low free space.",
            "Free storage space before accepting more work.",
        )
    if free_percent <= warning_percent:
        return ProbeResult(
            InfrastructureStatus.DEGRADED,
            "disk_space_low",
            "Required storage has low free space.",
            "Plan storage cleanup or expansion.",
        )
    return ProbeResult(
        InfrastructureStatus.READY, "storage_healthy", "Required storage is writable."
    )


def _run_slurm_query(args: list[str]) -> str:
    executable = shutil.which(args[0])
    if not executable:
        raise FileNotFoundError(args[0])
    result = subprocess.run(
        [executable, *args[1:]], capture_output=True, text=True, timeout=2, check=True
    )
    return result.stdout


def _slurm_controller_probe() -> ProbeResult:
    try:
        output = _run_slurm_query(["sinfo", "--noheader", "--format=%T"])
    except FileNotFoundError:
        return ProbeResult(
            InfrastructureStatus.UNAVAILABLE,
            "slurm_command_missing",
            "Slurm query tooling is unavailable.",
            "Install or mount the Slurm client commands.",
        )
    except (subprocess.SubprocessError, OSError):
        return ProbeResult(
            InfrastructureStatus.UNAVAILABLE,
            "slurm_controller_unreachable",
            "The Slurm controller is unavailable.",
            "Inspect controller connectivity and authentication.",
        )
    states = {line.strip().lower().rstrip("*") for line in output.splitlines() if line.strip()}
    capacity = CapacityStatus.AVAILABLE if states & {"idle", "mix", "mixed"} else CapacityStatus.BUSY
    return ProbeResult(
        InfrastructureStatus.READY,
        "slurm_controller_healthy",
        "The Slurm controller is responding.",
        capacity=capacity,
    )


def _slurm_submission_probe() -> ProbeResult:
    if shutil.which("srun") is None:
        return ProbeResult(
            InfrastructureStatus.UNAVAILABLE,
            "slurm_submission_command_missing",
            "The Slurm submission command is unavailable.",
            "Install or mount the Slurm submission client.",
        )
    return ProbeResult(
        InfrastructureStatus.READY,
        "slurm_submission_ready",
        "The Slurm submission path is available.",
    )


def _gpu_inventory_probe() -> ProbeResult:
    try:
        output = _run_slurm_query(["sinfo", "--noheader", "--format=%G|%T"])
    except FileNotFoundError:
        return ProbeResult(
            InfrastructureStatus.UNAVAILABLE,
            "gpu_inventory_command_missing",
            "GPU inventory cannot be queried.",
            "Install or mount the Slurm query client.",
            CapacityStatus.UNKNOWN,
        )
    except (subprocess.SubprocessError, OSError):
        return ProbeResult(
            InfrastructureStatus.UNAVAILABLE,
            "gpu_inventory_unavailable",
            "GPU inventory is unavailable.",
            "Inspect Slurm inventory visibility.",
            CapacityStatus.UNKNOWN,
        )
    inventory = []
    for line in output.splitlines():
        gres, _, state = line.partition("|")
        if gres.strip() and gres.strip().lower() not in {"(null)", "none"}:
            inventory.append(state.strip().lower().rstrip("*"))
    if not inventory:
        return ProbeResult(
            InfrastructureStatus.DEGRADED,
            "gpu_inventory_empty",
            "No GPU resources are visible in the scheduler inventory.",
            "Inspect compute-node GPU registration.",
            CapacityStatus.UNKNOWN,
        )
    capacity = CapacityStatus.AVAILABLE if set(inventory) & {"idle", "mix", "mixed"} else CapacityStatus.BUSY
    return ProbeResult(
        InfrastructureStatus.READY,
        "gpu_inventory_visible",
        "GPU resources are visible in the scheduler inventory.",
        capacity=capacity,
    )
