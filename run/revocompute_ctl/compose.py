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

__all__ = ["run_cmd", "detect_compose_cmd", "compose_args", "container_fs", "image_id", "mcp_enabled"]

log = logging.getLogger("revocompute_ctl")


def mcp_enabled(state) -> bool:
    """One switch for the whole opt-in: the controller, the listener, the route.

    The controller's process environment is not the container's: ``MCP_ENABLED``
    lives in the deployment env file, which Compose interpolates into the web
    service. The accepted spellings are the listener's (``env_bool``), so the two
    cannot disagree about what "enabled" means.
    """
    return (state.get("MCP_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


def compose_args(state) -> list[str]:
    """Return the base Compose model plus the production Slurm and MCP overrides.

    The MCP overlay is layered only when the deployment opted in, so a stack that
    never enables the surface renders exactly the model it did before: the
    override adds the environment the web service otherwise never sees.
    """
    from revocompute_ctl import COMPOSE_FILE, COMPOSE_MCP_FILE, COMPOSE_SLURM_FILE

    files = ["-f", str(COMPOSE_FILE)]
    if state.use_slurm():
        if COMPOSE_SLURM_FILE.is_file():
            files += ["-f", str(COMPOSE_SLURM_FILE)]
    if mcp_enabled(state) and COMPOSE_MCP_FILE.is_file():
        files += ["-f", str(COMPOSE_MCP_FILE)]
    return files


def container_fs(
    state,
    script: str,
    mounts: list[tuple[str, str]],
    *,
    args: list[str] | None = None,
    stdin_data: str | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a host-filesystem operation inside a throwaway container as the
    runner identity.  Deployment-owned directories (CONFIG_DIR, SERVER_DIR)
    are reachable regardless of the invoking host user — the same pattern as
    the pre-stop sweep, which runs in the worker container for the same
    reason.

    ``args`` are passed to ``sh`` as positional parameters (``$0``, ``$1``, …)
    so a value that contains shell or nginx metacharacters — ``$host``,
    ``%s`` — reaches the script literally instead of being expanded by the
    host shell or a here-doc."""
    uid = state.runtime.get("RUNNER_UID") or state.get("RUNNER_UID") or "1000"
    gid = state.runtime.get("RUNNER_GID") or state.get("RUNNER_GID") or "1000"
    image = state.get("SERVER_IMAGE") or "revodesign-revocompute-server"
    argv = ["docker", "run", "--rm", "-i", "--user", f"{uid}:{gid}", "--entrypoint", "sh"]
    for host, target in mounts:
        argv += ["-v", f"{host}:{target}"]
    argv += [image, "-c", script, *(args or [])]
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
