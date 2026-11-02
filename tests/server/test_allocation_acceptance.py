# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Allocation start honors the accepted Task identity, not later readiness.

Admission applies to new submissions.  A Task accepted while its family was
READY keeps the SIF and Runtime Bundle it pinned, so a later readiness change
must not withhold the scientific command from an allocation the scheduler has
already handed it.  These tests drive the real accounting callback and the
adapter's grant gate; the remaining allocation-start guarantees (pinned image,
authorization, quota, accounting) are covered by their own suites.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from revocompute import task_runtime
from revocompute.admission import submission_admission
from revocompute.db import TaskDatabase
from revocompute.job.runners.slurm_runner import SlurmJob
from revocompute.resource_ledger import AdmissionReason, ReservationReason, ReservationState
from revocompute.resource_policy import ResolvedResources
from revocompute.task_types import RunnerConfig, RuntimeFamily, TaskType

RUNNER = "cpu_runner"
_IMAGE = "sha256:" + "a" * 64
_BUNDLE = "sha256:" + "b" * 64


class _ManagedDb:
    def slurm_enabled(self) -> bool:
        return True


def _attestation(server_dir: Path, status: str, ready: bool) -> None:
    target = server_dir / "readiness" / f"{RUNNER}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "runner_family": RUNNER,
                "status": status,
                "ready": ready,
                "reason_code": "SYNTHETIC",
                "message": "synthetic readiness evidence",
                "next_action": "doctor",
            }
        ),
        encoding="utf-8",
    )


def _policy(requires_gpu: bool) -> ResolvedResources:
    return ResolvedResources(
        cpus=2,
        memory="4G",
        max_runtime_seconds=60,
        partition="gpu" if requires_gpu else "cpu",
        gres="gpu:1" if requires_gpu else None,
        nodes=1,
        ntasks=1,
        qos=None,
        account=None,
        constraint=None,
        exclusive=False,
        requires_gpu=requires_gpu,
        sources={},
    )


def _task_type() -> TaskType:
    runtime = RuntimeFamily(RUNNER, ("bash", "run.sh"), "runner.def", "image.sif")
    return TaskType(RUNNER, "Synthetic runner", runtime, (), stage_markers={"execute": "Execute"})


def _accepted_task(
    tmp_path: Path, monkeypatch, *, job_id: str
) -> tuple[TaskDatabase, str, object]:
    """READY admission, an accepted Task with pinned identities, then drift."""
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    _attestation(server_dir, "READY", True)
    assert submission_admission(server_dir, RUNNER, manage_db=_ManagedDb()).accepts(RUNNER)

    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = (job_id * 16)[:32]
    database.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/immutable/input.fasta",
        uploaded_at=time.time(),
        status="queued",
        is_binary=0,
        task_type=RUNNER,
        storage_key="owner-key",
        submitted_by_user_id=67,
        input_form=json.dumps(
            {"runtime_images": {RUNNER: _IMAGE}, "runtime_bundles": {RUNNER: _BUNDLE}}
        ),
    )
    database.project_gpu_authorization(
        67, account_enabled=True, allow_gpu_use=True, entitlements={}
    )
    reservation = database.reserve_compute_admission(
        user_id=67, task_id=task_id, gres="gpu:1"
    )
    assert reservation["allowed"] is True

    # The family's current readiness moves after acceptance.  The Task's pins do
    # not move: they are the identity it was accepted under.
    _attestation(server_dir, "BUILD_STALE", False)
    monkeypatch.setattr(task_runtime, "CONFIG", SimpleNamespace(server_dir=str(server_dir)))
    monkeypatch.setattr(task_runtime, "task_store", database)
    return database, task_id, _policy(True)


def _started(database: TaskDatabase, task_id: str, policy: ResolvedResources):
    _dispatched, started, _finished = task_runtime._compute_allocation_callbacks(
        task_id=task_id,
        user_id=67,
        stage_id=RUNNER,
        resource_policy=policy,
        required_entitlements=(),
    )
    return started


def test_accepted_pinned_task_starts_after_readiness_drift(tmp_path, monkeypatch):
    database, task_id, policy = _accepted_task(tmp_path, monkeypatch, job_id="e1")

    _started(database, task_id, policy)("9101", time.time() + 1)

    allocations = database.list_task_allocations(task_id)
    assert {row["denial_code"] for row in allocations} == {None}
    assert all(row["adjudicated_at"] is not None for row in allocations)
    assert {row["slurm_job_id"] for row in database.list_unsettled_allocations()} == {"9101"}
    # The allocation consumed the Task's own submission hold, not a re-read of
    # the family's CURRENT global readiness.
    reservation = database.list_reservations(user_id=67)[0]
    assert reservation["state"] == ReservationState.RELEASED.value
    assert reservation["reason_code"] == ReservationReason.ALLOCATION_STARTED.value
    assert AdmissionReason.RUNNER_READINESS_UNAVAILABLE.value not in {
        row["denial_code"] for row in allocations
    }
    pinned = json.loads(database.get_task(task_id)["input_form"])
    assert pinned["runtime_images"][RUNNER] == _IMAGE
    assert pinned["runtime_bundles"][RUNNER] == _BUNDLE


def test_adapter_grant_gate_releases_the_wrapper_for_an_accepted_task(tmp_path, monkeypatch):
    """The real adapter entry point writes the grant the wrapper waits for."""
    database, task_id, policy = _accepted_task(tmp_path, monkeypatch, job_id="e2")
    started = _started(database, task_id, policy)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    job = SlurmJob(
        task_id,
        _task_type(),
        RunnerConfig(),
        [],
        str(output_dir),
        resource_policy=policy,
        allocation_started_callback=started,
        allocation_accounting=True,
        task_store=database,
        stage_name=RUNNER,
    )
    job._slurm_job_id = "9102"
    job._accounting_enabled = True

    job._notify_allocation_live()

    assert job.allocation_started is True
    # The wrapper proceeds past its admission-grant gate only when this file
    # exists (slurm_runner.py's grant loop), so this is the wrapper's release.
    assert Path(job._allocation_grant_path).is_file()
    allocations = database.list_task_allocations(task_id)
    assert {row["denial_code"] for row in allocations} == {None}


def test_production_dispatch_grants_an_accepted_task_after_readiness_drift(tmp_path, monkeypatch):
    """The production dispatch entry supplies the family; later drift must not deny.

    ``_run_compute_job`` is the caller that renders the allocation callbacks for
    a real Task.  The pre-fix code passed the family into the callback and
    denied here, so this test fails against that exact source even though the
    direct-callback tests above can avoid the guard by not naming a family.
    """
    database, task_id, policy = _accepted_task(tmp_path, monkeypatch, job_id="e4")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    created: dict[str, SlurmJob] = {}

    def create(*args, **kwargs):
        job = SlurmJob(*args, **kwargs)
        created["job"] = job

        def submit():
            job._slurm_job_id = "9104"
            job._accounting_enabled = True
            job._notify_allocation_live()
            return "9104"

        job.submit = submit
        job.poll = lambda: task_runtime.JobState.COMPLETED
        job.runtime_image_observation = lambda: SimpleNamespace(
            expected=_IMAGE, observed=_IMAGE
        )
        return job

    monkeypatch.setattr(task_runtime, "_create_job", create)

    state = task_runtime._run_compute_job(
        task_id,
        _task_type(),
        RunnerConfig(),
        [],
        str(output_dir),
        resource_policy=policy,
    )

    job = created["job"]
    assert state == task_runtime.JobState.COMPLETED
    assert job.allocation_started is True
    # The wrapper is released past its admission-grant gate only by this file.
    assert Path(job._allocation_grant_path).is_file()
    allocations = database.list_task_allocations(task_id)
    assert {row["denial_code"] for row in allocations} == {None}
    assert all(row["adjudicated_at"] is not None for row in allocations)
    reservation = database.list_reservations(user_id=67)[0]
    assert reservation["state"] == ReservationState.RELEASED.value
    assert reservation["reason_code"] == ReservationReason.ALLOCATION_STARTED.value


def test_a_cpu_only_accounted_allocation_records_and_settles(tmp_path, monkeypatch):
    """CPU-only allocations are still facts: recorded, granted, and settled."""
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "e3" * 16
    monkeypatch.setattr(task_runtime, "CONFIG", SimpleNamespace(server_dir=str(server_dir)))
    monkeypatch.setattr(task_runtime, "task_store", database)
    policy = _policy(False)
    _dispatched, started, finished = task_runtime._compute_allocation_callbacks(
        task_id=task_id,
        user_id=67,
        stage_id=RUNNER,
        resource_policy=policy,
        required_entitlements=(),
    )

    now = time.time()
    started("9103", now)
    allocations = database.list_task_allocations(task_id)
    assert {row["unit"] for row in allocations} == {"gpu_second", "cpu_core_second"}
    assert {row["denial_code"] for row in allocations} == {None}

    finished("9103", now + 10)
    assert database.list_unsettled_allocations() == []
