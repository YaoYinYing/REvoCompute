# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The adapter/reconciliation handoff for a job's scheduler stderr.

The adapter cannot learn a Slurm job id before ``srun`` runs, but Slurm creates
the per-job stderr file at allocation.  The claim must therefore exist before
the file can, and retirement must re-check it after moving the file out of the
scanned namespace -- otherwise a short-lived job loses the only stderr artifact
the adapter still has to publish.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from conftest import _load_pssm_module
from revocompute.job import JobState
from revocompute.job.runners.slurm_runner import (
    ALLOCATION_STDERR_CLAIM_NAME,
    ALLOCATION_STDERR_CLAIM_SUFFIX,
    SlurmJob,
    _process_start_ticks,
)


# -- adapter ordering ---------------------------------------------------------


def _make_runner():
    from revocompute.task_types import RunnerConfig

    return RunnerConfig()


def _make_task_type():
    from revocompute.task_types import RuntimeFamily, TaskInputRole, TaskType

    return TaskType(
        name="cpu_runner",
        display_name="GREMLIN",
        runtime=RuntimeFamily(
            name="cpu_runner",
            entrypoint=("bash", "/app/run.sh"),
            definition="docker/cpu_runner/cpu_runner.def",
            slurm_image="/opt/images/cpu_runner_v1.sif",
            image_artifact="cpu_runner_v1.sif",
        ),
        inputs=(
            TaskInputRole(
                name="sequence",
                title="Sequence",
                type="protein_sequence",
                formats=("fasta",),
                minimum=1,
                maximum=1,
            ),
        ),
        stage_markers={"cpu_runner": "GREMLIN opt"},
    )


def _make_entities():
    return [
        {
            "name": "file",
            "type": "file",
            "value": "input.fasta",
            "verified_value": "input.fasta",
            "relative_path": "input.fasta",
            "hash": "abc123",
            "mounted": "/workspace/inputs/input.fasta",
            "snapshot_path": "/srv/workspaces/tester/task-1/inputs/input.fasta",
            "snapshot_root": "/srv/workspaces/tester/task-1/inputs",
            "workspace_key": "tester",
        },
    ]


class _FakeSrunProcess:
    """A subprocess.Popen-shaped scheduler boundary fake."""

    def __init__(self, *, stdout: str, returncode: int | None = 0) -> None:
        self.stdout = StringIO(stdout)
        self.stderr = StringIO("")
        self.returncode = returncode
        self.pid = 4217

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


def _claim(output_dir: Path) -> Path:
    return output_dir.parent / f"{output_dir.name}.allocation" / ALLOCATION_STDERR_CLAIM_NAME


def test_the_directory_claim_exists_before_popen_and_is_released_on_exit(tmp_path):
    """The claim covers the exact interval in which the job id is unknown.

    ``srun`` creates ``allocation-<job>.err`` at allocation, after Popen, and
    the adapter learns the id only once a reader parses it.  A claim keyed by
    the job id would leave both moments unowned, so the claim is per directory
    and is written before the process exists.
    """
    output_dir = tmp_path / "out"
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(output_dir))
    claim = _claim(output_dir)
    observed: dict[str, bool] = {}

    def fake_popen(*_args, **_kwargs):
        observed["claim_at_popen"] = claim.is_file()
        return _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=0)

    with patch("subprocess.Popen", side_effect=fake_popen):
        assert job.submit() == "4217"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_dir.joinpath("result.csv").write_text("score\n1\n")
        assert job.poll() == JobState.COMPLETED

    assert observed["claim_at_popen"] is True
    assert not claim.exists()

    # The cancel path is terminal too: a wrapper killed before it reports is
    # still a handoff that must end.
    cancelling = SlurmJob("task-2", _make_task_type(), _make_runner(), _make_entities(), str(output_dir))
    with patch(
        "subprocess.Popen",
        return_value=_FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4218\n", returncode=None),
    ):
        cancelling.submit()
        assert _claim(output_dir).is_file()
        cancelling.cancel()

    assert not _claim(output_dir).exists()


# -- reconciliation handoff ---------------------------------------------------


def _timestamp(year: int, month: int, day: int = 1, second: int = 0) -> float:
    return datetime(year, month, day, 0, 0, second, tzinfo=timezone.utc).timestamp()


def _own_task(database, task_id: str, *, user_id: int, status: str = "running") -> None:
    database.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/immutable/input.fasta",
        uploaded_at=900.0,
        status=status,
        is_binary=0,
        username=f"user-{user_id}",
        submitted_by_user_id=user_id,
        storage_key=f"user-{user_id}",
        task_type="cpu_runner",
    )


def _allocation_dir(module, task_id: str) -> Path:
    task = module.task_store.get_task(task_id)
    result_root = Path(
        module.StorageResolver(module.CONFIG.results_folder, module.CONFIG.workspace_folder).get_task_root(task)
    )
    return result_root.parent / f"{result_root.name}.allocation"


def _plant_scheduler_log(module, task_id: str, *, job_id: str, observed_at: float) -> Path:
    directory = _allocation_dir(module, task_id)
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / f"allocation-{job_id}.err"
    log.write_text("slurmstepd: task started\n", encoding="utf-8")
    os.utime(log, (observed_at, observed_at))
    return log


def _terminal_scheduler(monkeypatch, module) -> None:
    monkeypatch.setattr(module.task_runtime.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        module.task_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="JobId=8830 JobState=COMPLETED RunTime=00:00:45 AllocTRES=cpu=2,gres/gpu=1\n"
        ),
    )


def test_a_pre_id_claim_keeps_a_terminal_jobs_stderr_until_the_adapter_reads_it(monkeypatch, tmp_path):
    """The pre-claim interval: the job is terminal, the task alive, no row yet.

    This is the interleaving the job-id-keyed claim missed.  The scheduler
    already reports the job terminal, no allocation row exists, and the adapter
    is still running but has not parsed the id -- only the directory claim says
    so.  Reconciliation must leave the file alone; once the claim is gone the
    ordinary adoption and retirement resume.
    """
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    at = _timestamp(2026, 9, 5)
    task_id = "1" * 31 + "1"
    _own_task(module.task_store, task_id, user_id=121, status="running")
    module.task_store.reserve_compute_admission(user_id=121, task_id=task_id, at=at)
    log = _plant_scheduler_log(module, task_id, job_id="8830", observed_at=at + 2)
    claim = _allocation_dir(module, task_id) / ALLOCATION_STDERR_CLAIM_NAME
    claim.write_text(f"{os.getpid()} {_process_start_ticks(os.getpid())}", encoding="ascii")
    _terminal_scheduler(monkeypatch, module)

    protected = module.task_runtime._reconcile_host_scheduler_logs()

    assert log.exists()
    assert protected["surviving"] == 1
    assert protected["recovered"] == 0
    assert module.task_store.allocation_row_exists("8830") is False

    # The adapter finished its snapshot and released the handoff.
    claim.unlink()
    assert module.task_runtime._reconcile_host_scheduler_logs()["recovered"] == 1
    assert not log.exists()

    # Its durable successor is now the allocation row, so a later pass is a
    # no-op rather than a second adoption.
    assert module.task_runtime._reconcile_host_scheduler_logs()["recovered"] == 0


def test_a_claim_appearing_between_the_check_and_the_unlink_restores_the_log(monkeypatch, tmp_path):
    """Retirement re-checks the handoff after moving the file out of the scan.

    A one-shot check cannot be atomic with the unlink.  The file is renamed
    outside the scanned namespace first; when the claim shows up in that window
    the file is restored and the pass reports it as surviving.
    """
    import revocompute.job.runners.slurm_runner as slurm_runner

    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    at = _timestamp(2026, 9, 5)
    task_id = "2" * 31 + "2"
    _own_task(module.task_store, task_id, user_id=122)
    module.task_store.reserve_compute_admission(user_id=122, task_id=task_id, at=at)
    log = _plant_scheduler_log(module, task_id, job_id="8831", observed_at=at + 2)
    _terminal_scheduler(monkeypatch, module)

    calls = 0

    def claim_appears_late(path: str) -> bool:
        nonlocal calls
        calls += 1
        # First check in the pass, first check inside retirement: absent.  The
        # re-check after the rename sees the adapter's claim.
        return calls > 2

    monkeypatch.setattr(module.task_runtime, "scheduler_log_is_claimed", claim_appears_late)
    monkeypatch.setattr(slurm_runner, "scheduler_log_is_claimed", claim_appears_late)

    result = module.task_runtime._reconcile_host_scheduler_logs()

    assert calls >= 3
    assert log.exists()
    assert result["surviving"] == 1
    directory = _allocation_dir(module, task_id)
    assert not list(directory.glob("*.retiring.*"))
    assert module.task_store.allocation_row_exists("8831") is True


@pytest.mark.parametrize("claim_kind", ["legacy-dead-pid", "stale-start-stamp"])
def test_a_dead_or_replaced_claim_never_blocks_retirement(monkeypatch, tmp_path, claim_kind):
    """Orphan recovery terminates: only a live, un-replaced pid owns the file.

    A claim left by a worker that died (the legacy per-log location, or a pid
    now running a different process) must not keep a scheduler log forever.
    """
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    at = _timestamp(2026, 9, 5)
    task_id = "3" * 31 + "3"
    _own_task(module.task_store, task_id, user_id=123)
    module.task_store.reserve_compute_admission(user_id=123, task_id=task_id, at=at)
    log = _plant_scheduler_log(module, task_id, job_id="8832", observed_at=at + 2)
    if claim_kind == "legacy-dead-pid":
        Path(str(log) + ALLOCATION_STDERR_CLAIM_SUFFIX).write_text("999999", encoding="ascii")
    else:
        directory = _allocation_dir(module, task_id)
        # The pid is alive but has a different kernel start stamp: the claim
        # belongs to a process that no longer captures this file.
        (directory / ALLOCATION_STDERR_CLAIM_NAME).write_text(f"{os.getpid()} 1", encoding="ascii")
    _terminal_scheduler(monkeypatch, module)

    assert module.task_runtime._reconcile_host_scheduler_logs()["recovered"] == 1
    assert not log.exists()
    assert not Path(str(log) + ALLOCATION_STDERR_CLAIM_SUFFIX).exists()
    # A stale directory claim is left for the next adapter to replace;
    # retirement never removes a claim that may belong to a newer stage.
