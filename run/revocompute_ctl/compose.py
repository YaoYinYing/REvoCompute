# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Docker / Compose helpers — the only subprocess path in the control module.

run_cmd never logs argv (proxy URLs must not leak into logs).  stdout and
stderr are inherited unless capture is requested.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Sequence

log = logging.getLogger("revocompute_ctl")


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
    """Run one command. Never log the argv — callers log their own summaries."""
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
    if shutil.which("docker") and run_cmd(["docker", "compose", "version"], check=False).returncode == 0:
        return ("docker", "compose")
    if shutil.which("docker-compose"):
        return ("docker-compose",)
    raise SystemExit("docker compose plugin was not found. Install Docker Compose v2 or docker-compose.")


def compose_args(state) -> list[str]:
    """Return the base Compose model plus the production Slurm override."""
    from revocompute_ctl import COMPOSE_FILE, COMPOSE_SLURM_FILE

    files = ["-f", str(COMPOSE_FILE)]
    if state.use_slurm():
        if COMPOSE_SLURM_FILE.is_file():
            files += ["-f", str(COMPOSE_SLURM_FILE)]
    return files


def container_fs(
    state,
    script: str,
    mounts: list[tuple[str, str]],
    *,
    stdin_data: str | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a host-filesystem operation inside a throwaway container as the
    runner identity.  Deployment-owned directories (CONFIG_DIR, SERVER_DIR)
    are reachable regardless of the invoking host user — the same pattern as
    the pre-stop sweep, which runs in the worker container for the same
    reason."""
    uid = state.runtime.get("RUNNER_UID") or state.get("RUNNER_UID") or "1000"
    gid = state.runtime.get("RUNNER_GID") or state.get("RUNNER_GID") or "1000"
    image = state.get("SERVER_IMAGE") or "revodesign-revocompute-server"
    argv = ["docker", "run", "--rm", "-i", "--user", f"{uid}:{gid}", "--entrypoint", "sh"]
    for host, target in mounts:
        argv += ["-v", f"{host}:{target}"]
    argv += [image, "-c", script]
    # Close stdin unless the script feeds from it — never inherit the caller's.
    return run_cmd(
        argv, env=state.exported(), stdin=stdin_data if stdin_data is not None else "", capture=capture, check=check
    )


def image_id(state, image: str) -> str:
    """docker image inspect --format '{{.Id}}' → the id, or '' on any failure.

    An empty id means "unknown" — promotion treats unknown as unchanged, which
    is also what keeps the fake-docker test harness (empty inspect output)
    behaviorally identical to the shell script.
    """
    result = run_cmd(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        env=state.exported(),
        check=False,
        capture=True,
    )
    return (result.stdout or "").strip()
