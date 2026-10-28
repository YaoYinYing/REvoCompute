# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Server-owned Slurm diagnostic publication and persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from revocompute.job.runners.slurm_runner import SlurmJob
from revocompute.task_types import RunnerConfig, RuntimeFamily, TaskInputRole, TaskType


def _job(tmp_path: Path) -> SlurmJob:
    task_type = TaskType(
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
    return SlurmJob(
        "task-1",
        task_type,
        RunnerConfig(),
        [
            {
                "name": "file",
                "type": "file",
                "value": "input.fasta",
                "verified_value": "input.fasta",
                "snapshot_path": "/srv/workspaces/tester/task-1/inputs/input.fasta",
                "snapshot_root": str(tmp_path / "workspace" / "inputs"),
                "workspace_key": "tester",
            }
        ],
        str(tmp_path / "out"),
        username="alice",
    )


def test_srun_error_file_is_published_and_reported_as_the_job_stderr(tmp_path):
    """A failed job's traceback goes to ``srun --error=``, not the srun pipe."""
    from revocompute.execution_diagnostics import STATUS_PATH

    job = _job(tmp_path)
    job._slurm_job_id = "4217"
    job._stderr_lines = ["srun: error: allocation failed\n"]
    (tmp_path / "out").mkdir()
    os.makedirs(job.allocation_dir, exist_ok=True)
    Path(job.allocation_dir, "allocation-4217.err").write_text(
        "Traceback (most recent call last):\nRuntimeError: Failed to find C compiler.\n", encoding="utf-8"
    )
    captured = []
    job._task_store = SimpleNamespace(
        record_task_diagnostics=lambda task_id, evidence, **kwargs: captured.append(evidence)
    )

    job._save_output()
    job._persist_execution_evidence()

    published = (tmp_path / "out" / "execution" / "slurm-alice-cpu_runner-task-1.stderr.log").read_text()
    assert published == (
        "srun: error: allocation failed\n"
        "Traceback (most recent call last):\n"
        "RuntimeError: Failed to find C compiler.\n"
    )
    record = json.loads((tmp_path / "out" / STATUS_PATH).read_text())
    assert "RuntimeError: Failed to find C compiler." in record["logs"]["stderr"]


def test_a_window_opening_inside_a_credential_still_redacts_it(tmp_path):
    """The bound must not cut a credential assignment away from its key.

    Redaction matches a whole ``KEY=value`` assignment, so a tail cut through
    the key would publish the value as ordinary text. The window opens on the
    line boundary instead, so the redactor sees the assignment whole.
    """
    from revocompute.execution_diagnostics import MAX_LOG_BYTES

    job = _job(tmp_path)
    job._slurm_job_id = "4217"
    secret = 'TOKEN_API="private-token"\n'
    cut_inside_key = 3
    tail = "z" * (MAX_LOG_BYTES + 1 - len(secret) + cut_inside_key)
    os.makedirs(job.allocation_dir, exist_ok=True)
    Path(job.allocation_dir, "allocation-4217.err").write_text("filler\n" + secret + tail, encoding="utf-8")

    job._save_output()

    published = (tmp_path / "out" / "execution" / "slurm-alice-cpu_runner-task-1.stderr.log").read_text()
    assert "private-token" not in published
    assert published.startswith("TOKEN_API=[redacted]\n")


def test_job_stderr_tail_keeps_the_begin_of_a_truncated_private_key(tmp_path):
    """A window opening inside a PEM block must include its BEGIN line.

    The redactor recognizes key material only from the BEGIN line, so a tail
    that starts mid-block would publish the body as ordinary text.
    """
    from revocompute.execution_diagnostics import MAX_LOG_BYTES, STATUS_PATH

    job = _job(tmp_path)
    job._slurm_job_id = "4217"
    body_line = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC" + "A" * 32 + "\n"
    body = body_line * (((MAX_LOG_BYTES + 200) // len(body_line)) + 1)
    pem = "-----BEGIN PRIVATE KEY-----\n" + body + "-----END PRIVATE KEY-----\n"
    os.makedirs(job.allocation_dir, exist_ok=True)
    Path(job.allocation_dir, "allocation-4217.err").write_text(
        "filler\n" * 10 + pem + "useful diagnostic context\n", encoding="utf-8"
    )
    job._save_output()
    job._task_store = SimpleNamespace(record_task_diagnostics=lambda *args, **kwargs: None)
    job._persist_execution_evidence()

    published = (tmp_path / "out" / "execution" / "slurm-alice-cpu_runner-task-1.stderr.log").read_text()
    record = json.loads((tmp_path / "out" / STATUS_PATH).read_text())
    for excerpt in (published, record["logs"]["stderr"]):
        assert "[private key redacted]" in excerpt
        assert "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC" not in excerpt
        assert "useful diagnostic context" in excerpt


def test_cancelling_a_job_releases_its_stderr_claim(tmp_path):
    """A cancelled job must not keep reconciliation from retiring its stderr."""
    from revocompute.job.runners.slurm_runner import ALLOCATION_STDERR_CLAIM_SUFFIX

    job = _job(tmp_path)
    job._slurm_job_id = "4217"
    (tmp_path / "out").mkdir()
    os.makedirs(job.allocation_dir, exist_ok=True)
    log = Path(job.allocation_dir, "allocation-4217.err")
    log.write_text("srun: error: cancelled\n", encoding="utf-8")
    job._claim_job_stderr()
    claim = Path(str(log) + ALLOCATION_STDERR_CLAIM_SUFFIX)
    assert claim.exists()

    job.cancel()

    assert not claim.exists()
    assert job._job_stderr_snapshot == ["srun: error: cancelled\n"]


@pytest.mark.parametrize("cut", [0, 13], ids=["marker-after-the-window", "inside-the-marker"])
def test_a_window_inside_an_unbroken_line_still_redacts_the_key(tmp_path, cut):
    """A marker sharing a line longer than the bound must not be dropped.

    When the window opens inside a line with no newline in reach, the partial
    first line is discarded to avoid publishing a cut credential. That line can
    also carry the key's BEGIN marker, which has to survive so the body is
    redacted rather than published.
    """
    from revocompute.execution_diagnostics import MAX_LOG_BYTES, STATUS_PATH

    job = _job(tmp_path)
    job._slurm_job_id = "4217"
    body = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC" + "A" * 32 + "\n"
    pem = "-----BEGIN PRIVATE KEY-----\n" + body + "-----END PRIVATE KEY-----\n"
    giant = "A" * 100_000
    if cut:
        needed = MAX_LOG_BYTES + 1 + cut - len(pem)
        content = giant + pem + "x" * (needed - 1) + "\n"
    else:
        # The window opens inside ``giant``; the marker follows on that line.
        tail = 50_000 + MAX_LOG_BYTES + 1 - len(giant) - len(pem)
        content = giant + pem + "x" * (tail - 1) + "\n"
    os.makedirs(job.allocation_dir, exist_ok=True)
    Path(job.allocation_dir, "allocation-4217.err").write_text(content, encoding="utf-8")

    job._save_output()
    job._task_store = SimpleNamespace(record_task_diagnostics=lambda *args, **kwargs: None)
    job._persist_execution_evidence()

    published = (tmp_path / "out" / "execution" / "slurm-alice-cpu_runner-task-1.stderr.log").read_text()
    record = json.loads((tmp_path / "out" / STATUS_PATH).read_text())
    for excerpt in (published, record["logs"]["stderr"]):
        assert "[private key redacted]" in excerpt
        assert "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC" not in excerpt


def test_the_adapter_claims_its_stderr_until_it_is_captured(tmp_path):
    """The claim is live between job-id discovery and the snapshot.

    Reconciliation in another worker process reads this claim as the handoff
    that says the scheduler log still has an owner.
    """
    from revocompute.job.runners.slurm_runner import (
        ALLOCATION_STDERR_CLAIM_SUFFIX,
        scheduler_log_is_claimed,
    )

    job = _job(tmp_path)
    job._slurm_job_id = "4217"
    os.makedirs(job.allocation_dir, exist_ok=True)
    log = Path(job.allocation_dir, "allocation-4217.err")
    log.write_text("Traceback (most recent call last):\nRuntimeError: boom\n", encoding="utf-8")

    job._claim_job_stderr()
    claim = Path(str(log) + ALLOCATION_STDERR_CLAIM_SUFFIX)
    pid_text, start_text = claim.read_text(encoding="ascii").split()
    assert int(pid_text) == os.getpid()
    assert int(start_text) > 0
    assert scheduler_log_is_claimed(str(log)) is True

    job._capture_job_stderr()
    assert not claim.exists()
    assert scheduler_log_is_claimed(str(log)) is False
    assert job._job_stderr_snapshot == [
        "Traceback (most recent call last):\n",
        "RuntimeError: boom\n",
    ]


@pytest.mark.parametrize("cut", [0, 10], ids=["at-the-begin-line", "inside-the-marker"])
def test_a_window_opening_on_the_pem_marker_still_redacts_the_key(tmp_path, cut):
    """The 64 KiB bound must not split a PEM marker from its body.

    The window is aligned to a line boundary, so a marker that straddles the
    bound is published whole and the redactor sees it. A marker cut in half
    would leave the body recognized by neither side.
    """
    from revocompute.execution_diagnostics import MAX_LOG_BYTES, STATUS_PATH

    job = _job(tmp_path)
    job._slurm_job_id = "4217"
    filler = "filler\n" * 20
    body = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC" + "A" * 32 + "\n"
    pem = "-----BEGIN PRIVATE KEY-----\n" + body + "-----END PRIVATE KEY-----\n"
    # size - MAX_LOG_BYTES - 1 == len(filler) + cut, i.e. the window opens
    # ``cut`` bytes into the marker line.
    needed = MAX_LOG_BYTES + 1 + cut - len(pem)
    content = filler + pem + "x" * (needed - 1) + "\n"
    os.makedirs(job.allocation_dir, exist_ok=True)
    Path(job.allocation_dir, "allocation-4217.err").write_text(content, encoding="utf-8")

    job._save_output()
    job._task_store = SimpleNamespace(record_task_diagnostics=lambda *args, **kwargs: None)
    job._persist_execution_evidence()

    published = (tmp_path / "out" / "execution" / "slurm-alice-cpu_runner-task-1.stderr.log").read_text()
    record = json.loads((tmp_path / "out" / STATUS_PATH).read_text())
    for excerpt in (published, record["logs"]["stderr"]):
        assert "[private key redacted]" in excerpt
        assert "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC" not in excerpt
