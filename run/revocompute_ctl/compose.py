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

__all__ = [
    "MCP_SERVICE",
    "compose_args",
    "compose_files",
    "container_fs",
    "detect_compose_cmd",
    "image_id",
    "mcp_enabled",
    "mcp_overlay_args",
    "remove_mcp_service",
    "run_cmd",
    "stack_services",
]

log = logging.getLogger("revocompute_ctl")

#: The compose service ``docker-compose.mcp.yml`` declares for the MCP surface.
#: It is profile-gated in the overlay, so naming it is what starts it and the
#: profile below is what makes the layered model agree with that.
MCP_SERVICE = "mcp"


def mcp_enabled(state) -> bool:
    """One switch for the whole opt-in: the controller, the service, the route.

    The controller's process environment is not the container's: ``MCP_ENABLED``
    lives in the deployment env file, which Compose interpolates into the ``mcp``
    and ``web`` services. The accepted spellings are the listener's
    (``env_bool``), so the two cannot disagree about what "enabled" means.
    """
    return (state.get("MCP_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


def stack_services(state, *names: str) -> list[str]:
    """``names``, plus the MCP service when this deployment opted in.

    The ``mcp`` service exists only in the layered model, so it must be named
    wherever the stack is started, stopped, or waited on -- otherwise an opt-in
    deployment would start it and never stop it.  A deployment that never opted in
    gets exactly the list it always had.
    """
    return [*names, MCP_SERVICE] if mcp_enabled(state) else [*names]


def compose_files(state) -> list[str]:
    """Return the base Compose model plus the production Slurm override.

    This is the model without the MCP overlay: the deployment's own services,
    which every command speaks to.  The overlay is a separate layer
    (:func:`mcp_overlay_args`) because one command needs it while the switch is
    *off* -- see :func:`remove_mcp_service`.
    """
    from revocompute_ctl import COMPOSE_FILE, COMPOSE_SLURM_FILE

    files = ["-f", str(COMPOSE_FILE)]
    if state.use_slurm() and COMPOSE_SLURM_FILE.is_file():
        files += ["-f", str(COMPOSE_SLURM_FILE)]
    return files


def mcp_overlay_args() -> list[str]:
    """Return the MCP overlay and the profile that makes it declare ``mcp``.

    The overlay's ``mcp`` service is profile-gated, so the profile travels with
    the file: a command over this layer sees the service the controller names,
    and a bare ``docker compose up`` over the layered model still starts nothing
    the operator did not ask for.
    """
    from revocompute_ctl import COMPOSE_MCP_FILE

    return ["-f", str(COMPOSE_MCP_FILE), "--profile", MCP_SERVICE]


def compose_args(state) -> list[str]:
    """Return the base Compose model plus the production Slurm and MCP overrides.

    The MCP overlay is layered only when the deployment opted in, so a stack that
    never enables the surface renders exactly the model it did before.
    """
    from revocompute_ctl import COMPOSE_MCP_FILE

    files = compose_files(state)
    if mcp_enabled(state) and COMPOSE_MCP_FILE.is_file():
        files += mcp_overlay_args()
    return files


def remove_mcp_service(state, compose_cmd: tuple[str, ...]) -> bool:
    """Stop and remove a ``mcp`` container the current model no longer declares.

    A rollback flips ``MCP_ENABLED`` off, which drops the overlay *and* its
    profile from :func:`compose_args`, so ``mcp`` leaves :func:`stack_services`
    and a ``stop`` of the declared services misses the container the deployment
    is still running.  The ordinary ``down`` path sweeps orphans; this path must
    keep the gateway serving the maintenance page, so it names the one service
    instead of sweeping the project.  ``mcp`` is the only service an overlay can
    leave behind -- ``docker-compose.slurm.yml`` overrides ``redis``, ``worker``,
    and ``tool-worker``, all of which the base model already declares.

    The project is asked what containers it has before anything is issued, so a
    deployment that never opted in sends no MCP command at all.  That question is
    asked without the overlay: Compose answers by project, and the base model
    lists the project's containers the way ``ps -a`` does, orphans included.  An
    unanswered question falls through to the cleanup, because removing a service
    that is not there is harmless and leaving a live protocol process behind is
    not.
    """
    from revocompute_ctl import COMPOSE_MCP_FILE

    if mcp_enabled(state) or not COMPOSE_MCP_FILE.is_file():
        return False
    present = run_cmd(
        [*compose_cmd, *compose_files(state), "--env-file", state.env_file, "ps", "-a", "--services"],
        env=state.exported(),
        check=False,
        capture=True,
    )
    if present.returncode == 0 and MCP_SERVICE not in (present.stdout or "").split():
        return False
    print("Removing the MCP service this deployment no longer declares...")
    run_cmd(
        [
            *compose_cmd,
            *compose_files(state),
            *mcp_overlay_args(),
            "--env-file",
            state.env_file,
            # ``--force --stop`` is what makes this one command the whole
            # cleanup: ``rm`` alone refuses a running container, and a separate
            # ``stop`` would be a second command that can fail on its own.
            "rm",
            "--force",
            "--stop",
            MCP_SERVICE,
        ],
        env=state.exported(),
    )
    return True


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
