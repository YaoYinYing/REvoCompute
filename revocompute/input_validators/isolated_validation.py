# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Parent-side runner for Core-owned parser isolation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ISOLATED_TIMEOUT_SECONDS = 3.0
_MAX_PROTOCOL_BYTES = 64 * 1024


def _worker_environment(workspace: str) -> dict[str, str]:
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.defpath,
        "TMPDIR": workspace,
    }


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
                completed = subprocess.run(
                    [sys.executable, "-I", str(worker), format_name, f"/proc/self/fd/{descriptor}"],
                    cwd=workspace,
                    env=_worker_environment(workspace),
                    pass_fds=(descriptor,),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=ISOLATED_TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return "Core input parser exceeded its isolated validation time limit"
    except (OSError, subprocess.SubprocessError):
        return "Core input parser failed in isolation"
    finally:
        os.close(descriptor)
    if completed.returncode != 0 or len(completed.stdout.encode("utf-8")) > _MAX_PROTOCOL_BYTES:
        return "Core input parser failed in isolation"
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        return "Core input parser returned an invalid isolation response"
    if not isinstance(payload, dict) or set(payload) != {"error"}:
        return "Core input parser returned an invalid isolation response"
    error = payload["error"]
    if error is not None and not isinstance(error, str):
        return "Core input parser returned an invalid isolation response"
    return error
