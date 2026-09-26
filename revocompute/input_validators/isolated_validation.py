# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Parent-side runner for Core-owned parser isolation."""

from __future__ import annotations

import json
import os
import resource
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ISOLATED_TIMEOUT_SECONDS = 3.0
_MAX_PROTOCOL_BYTES = 64 * 1024

# One authoritative limit table, installed by the parent before the worker
# interpreter starts and re-applied in-process by isolated_worker.
ISOLATED_RLIMITS = (
    (resource.RLIMIT_CPU, 2),
    (resource.RLIMIT_AS, 256 * 1024 * 1024),
    (resource.RLIMIT_FSIZE, 1024 * 1024),
    (resource.RLIMIT_NOFILE, 32),
)


def _restrict_child() -> None:
    """Bound the forked child before it execs, so no untrusted byte is read unbounded."""
    for resource_id, limit in ISOLATED_RLIMITS:
        resource.setrlimit(resource_id, (limit, limit))


def _worker_environment(workspace: str) -> dict[str, str]:
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.defpath,
        "TMPDIR": workspace,
    }


def _kill_group(pid: int, signal_number: int) -> None:
    """Signal the whole child process group, matching the Runner's killpg pattern."""
    try:
        os.killpg(pid, signal_number)
    except ProcessLookupError:
        pass


def validate_in_subprocess(path: str, format_name: str) -> str | None:
    """Validate one open input through the static isolated-worker protocol."""
    worker = Path(__file__).with_name("isolated_worker.py")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        return f"Could not open uploaded {format_name} file for isolated validation: {exc}"
    try:
        with tempfile.TemporaryDirectory(prefix="revocompute-validator-") as workspace:
            try:
                process = subprocess.Popen(
                    [sys.executable, "-I", str(worker), format_name, f"/proc/self/fd/{descriptor}"],
                    cwd=workspace,
                    env=_worker_environment(workspace),
                    pass_fds=(descriptor,),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    start_new_session=True,
                    preexec_fn=_restrict_child,
                )
            except OSError:
                return "Core input parser failed in isolation"
            try:
                stdout, _stderr = process.communicate(timeout=ISOLATED_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                _kill_group(process.pid, signal.SIGTERM)
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    _kill_group(process.pid, signal.SIGKILL)
                    process.communicate()
                return "Core input parser exceeded its isolated validation time limit"
    except (OSError, subprocess.SubprocessError):
        return "Core input parser failed in isolation"
    finally:
        os.close(descriptor)
    if process.returncode != 0 or len(stdout.encode("utf-8")) > _MAX_PROTOCOL_BYTES:
        return "Core input parser failed in isolation"
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return "Core input parser returned an invalid isolation response"
    if not isinstance(payload, dict) or set(payload) != {"error"}:
        return "Core input parser returned an invalid isolation response"
    error = payload["error"]
    if error is not None and not isinstance(error, str):
        return "Core input parser returned an invalid isolation response"
    return error
