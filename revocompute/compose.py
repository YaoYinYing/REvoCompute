# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Host command execution for the control plane.

The only place the Runner control code starts a subprocess.  ``run_cmd`` never
logs argv (proxy URLs and credentials must not leak into logs); stdout and
stderr are inherited unless ``capture`` is requested.  Commands are fixed and
structured — never ``shell=True`` and never built from request data.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence


def run_cmd(
    argv: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    check: bool = True,
    capture: bool = False,
    timeout: float | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one command with a fixed argv. Never log the argv."""
    completed = subprocess.run(
        list(argv),
        env=env if env is not None else dict(os.environ),
        input=stdin,
        text=True,
        check=False,
        capture_output=capture,
        timeout=timeout,
        cwd=cwd,
    )
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, list(argv))
    return completed


def detect_compose_cmd() -> tuple[str, ...]:
    """Return the compose command array (docker compose or docker-compose)."""
    if shutil.which("docker") and run_cmd(
        ["docker", "compose", "version"], check=False, capture=True
    ).returncode == 0:
        return ("docker", "compose")
    if shutil.which("docker-compose"):
        return ("docker-compose",)
    raise SystemExit("docker compose plugin was not found. Install Docker Compose v2 or docker-compose.")
