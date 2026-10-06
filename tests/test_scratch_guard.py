# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The ephemeral scratch capacity guard the allocation wrapper runs.

Ephemeral workspace is a per-execution safety concern, not durable user quota,
and the guard is the thing that actually enforces it: it measures the task's own
bound workspace on the compute node and stops the task tree once that workspace
passes the ceiling.  These tests execute the real guard program against real
directories, because the claim under test is behaviour on a filesystem, not the
text of the program.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from revocompute.job.runners.slurm_runner import render_scratch_guard_script

MIB = 1024 * 1024


def _run_guard(scratch_dir, limit_bytes, *, stop_file, result_file, guard_seconds="0.05", timeout=60):
    """Run the real guard program to completion and return (rc, result fields)."""
    script = stop_file.parent / "scratch_guard.sh"
    script.write_text(render_scratch_guard_script(), encoding="utf-8")
    script.chmod(0o700)
    process = subprocess.run(
        [
            "bash",
            str(script),
            str(scratch_dir),
            str(limit_bytes),
            guard_seconds,
            str(stop_file),
            str(result_file),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    fields: dict[str, str] = {}
    if result_file.exists():
        for line in result_file.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                fields[key] = value
    return process.returncode, fields


def test_the_guard_stops_once_measured_scratch_passes_the_ceiling(tmp_path):
    """Real bytes in a real directory: the guard's measured peak is the ceiling's judge."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    control = tmp_path / "control"
    control.mkdir()
    limit_bytes = 256 * 1024
    (scratch / "blob").write_bytes(b"0" * (2 * MIB))

    returncode, fields = _run_guard(
        scratch,
        limit_bytes,
        stop_file=control / "stop",
        result_file=control / "result",
    )

    assert returncode == 0
    assert fields["exceeded"] == "1"
    assert int(fields["peak_bytes"]) > limit_bytes
    assert int(fields["samples"]) >= 1


def test_scratch_within_the_ceiling_is_measured_and_reported_as_not_exceeded(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    control = tmp_path / "control"
    control.mkdir()
    (scratch / "small").write_bytes(b"0" * 4096)
    limit_bytes = 64 * MIB

    # The stop file is what ends a task that stayed under its ceiling; the
    # wrapper touches it before waiting for the guard.
    (control / "stop").touch()
    returncode, fields = _run_guard(
        scratch,
        limit_bytes,
        stop_file=control / "stop",
        result_file=control / "result",
    )

    assert returncode == 0
    assert fields["exceeded"] == "0"
    assert 0 < int(fields["peak_bytes"]) < limit_bytes


def test_an_empty_scratch_is_a_measured_zero_not_an_unknown(tmp_path):
    """A completed measurement of an empty directory really is zero bytes."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    control = tmp_path / "control"
    control.mkdir()
    (control / "stop").touch()

    returncode, fields = _run_guard(
        scratch,
        64 * MIB,
        stop_file=control / "stop",
        result_file=control / "result",
    )

    assert returncode == 0
    assert fields["peak_bytes"] == "0"
    assert int(fields["samples"]) >= 1


def test_a_guard_that_never_measured_reports_nothing_at_all(tmp_path):
    """Unknown is not zero: a measurement that never happened is not a zero.

    A guard that could not measure its scratch tree writes no result, so the
    envelope carries no scratch facts and the server records unknown usage
    rather than a confident zero — the distinction the report relies on.
    """
    control = tmp_path / "control"
    control.mkdir()

    returncode, fields = _run_guard(
        tmp_path / "does-not-exist",
        64 * MIB,
        stop_file=control / "stop",
        result_file=control / "result",
    )

    assert returncode == 0
    assert fields == {}


def test_an_overrun_is_reported_without_the_wrapper_stopping_the_guard(tmp_path):
    """The wrapper never stops a guard that tripped: it stopped the task instead."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "blob").write_bytes(b"0" * (2 * MIB))
    control = tmp_path / "control"
    control.mkdir()

    returncode, fields = _run_guard(
        scratch,
        256 * 1024,
        stop_file=control / "stop",
        result_file=control / "result",
    )

    assert returncode == 0
    assert fields["exceeded"] == "1"
    assert not (control / "stop").exists()


def test_the_guard_script_is_valid_shell():
    import subprocess as _subprocess

    script = render_scratch_guard_script()
    assert script.startswith("#!/bin/bash")
    assert _subprocess.run(["bash", "-n"], input=script, text=True, check=False).returncode == 0


def test_the_wrapper_starts_stops_and_reports_the_guard(tmp_path):
    """The guard is wired into the allocation, not merely declared.

    The limit travels with the wrapper, the guard is stopped before the resource
    envelope is written so the facts it reports are final, and the envelope
    carries the measurement under its own field prefix.
    """
    import os as _os

    from tests.test_slurm_runner import _make_entities, _make_runner, _make_task_type

    from revocompute.job.runners.slurm_runner import SlurmJob

    workspace = tmp_path / "workspace" / "task-1"
    (workspace / "inputs").mkdir(parents=True)
    (workspace / "scratch").mkdir()
    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": str(workspace / "inputs" / "input.fasta"),
        "snapshot_root": str(workspace / "inputs"),
    }
    _os.environ["TASK_SCRATCH_LIMIT_BYTES"] = str(16 * MIB)
    try:
        job = SlurmJob(
            "task-1", _make_task_type(), _make_runner(), entities, str(tmp_path / "out"), username="alice"
        )
        script = job._render_wrapper()
    finally:
        _os.environ.pop("TASK_SCRATCH_LIMIT_BYTES", None)

    assert f"scratch_guard_limit_bytes={16 * MIB}" in script
    assert "REVODESIGN_SCRATCH_GUARD" in script
    assert "start_scratch_guard" in script
    assert "stop_scratch_guard" in script
    # The envelope republishes the guard's three facts under its own prefix, and
    # only those three: the result file is untrusted input from the compute node.
    assert "(peak_bytes|samples|exceeded)" in script
    assert "scratch_guard.%s=%s" in script
    # The guard is stopped before the envelope is written, so what it reports is
    # what it finally measured.
    assert script.index("stop_scratch_guard") < script.index("scratch_guard.%s=%s")
    # The container cannot rewrite the guard: it is written into the host-only
    # capture directory, which is not one of the container's binds.
    assert "resource_capture_dir}/scratch_guard.sh" in script
    assert "REVODESIGN_SCRATCH_GUARD'" in script


def test_the_wrapper_reports_scratch_facts_only_when_the_guard_measured_them(tmp_path):
    """A guard that never reported leaves the envelope without those fields.

    The server parses the observation against a fixed field set, so an absent
    pair means "unknown" — the opposite of a pair that says zero.
    """
    import os as _os

    from tests.test_slurm_runner import _make_entities, _make_runner, _make_task_type

    from revocompute.job.runners.slurm_runner import SlurmJob

    workspace = tmp_path / "workspace" / "task-1"
    (workspace / "inputs").mkdir(parents=True)
    (workspace / "scratch").mkdir()
    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": str(workspace / "inputs" / "input.fasta"),
        "snapshot_root": str(workspace / "inputs"),
    }
    job = SlurmJob(
        "task-1", _make_task_type(), _make_runner(), entities, str(tmp_path / "out"), username="alice"
    )
    job._resource_capture_path  # ensure the property is exercised elsewhere

    script = job._render_wrapper()
    # The envelope block is conditional on the result file existing.
    assert 'if [[ -f "${scratch_guard_result}" ]]; then' in script
    assert 'done < "${scratch_guard_result}"' in script
