# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Docker / Compose helpers — the deployment control module's subprocess surface.

Process execution itself lives in ``revocompute.compose`` so the shared Runner
control core can start commands without importing the deployment package.
``container_fs`` and the Compose model helpers stay here: they are deployment
concerns, not Runner contract.
"""

from __future__ import annotations

import logging
import os

from revocompute.compose import detect_compose_cmd, run_cmd

__all__ = ["run_cmd", "detect_compose_cmd", "compose_args", "container_fs", "image_id"]

log = logging.getLogger("revocompute_ctl")


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
