# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Server-owned Slurm diagnostic publication and persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

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


def test_job_stderr_tail_never_publishes_a_cut_credential_line(tmp_path):
    """A window that starts inside a credential assignment drops that line.

    Redaction matches a whole ``KEY=value`` assignment, so a tail cut through
    the key would publish the value as ordinary text. The read starts one byte
    before the window precisely so the partial first line is discarded.
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
    assert published.startswith("z")


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
