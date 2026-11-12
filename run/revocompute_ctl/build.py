# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Runner/web image builds."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from revocompute_ctl.compose import compose_args, run_cmd


def collect_build_identity(server_root: str, release_channel: str = "development") -> dict[str, str]:
    """Capture one immutable build identity for this build.

    A full commit is recorded only when the working tree is clean: an image
    built from uncommitted code is not that commit, so it reports an unknown
    revision instead of claiming one. A release build refuses outright. The
    time and the opaque build identifier are captured once, here.
    """
    clean = False
    sha = ""
    try:
        status = subprocess.run(
            ["git", "-C", server_root, "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        clean = status.returncode == 0 and not status.stdout.strip()
        if clean:
            completed = subprocess.run(
                ["git", "-C", server_root, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            candidate = completed.stdout.strip().lower()
            if completed.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", candidate):
                sha = candidate
            else:
                clean = False
    except OSError:
        clean = False
    if release_channel == "release" and not (clean and sha):
        raise RuntimeError(
            "A release build requires a clean working tree with an exact commit; commit or stash changes first"
        )
    built_at = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = built_at.strftime("%Y%m%dT%H%M%SZ")
    base_version = ""
    try:
        with open(os.path.join(server_root, "pyproject.toml"), "rb") as handle:
            base_version = str(tomllib.load(handle).get("project", {}).get("version") or "")
    except (OSError, ValueError):
        base_version = ""
    return {
        "REVOCOMPUTE_BUILD_GIT_SHA": sha,
        "REVOCOMPUTE_BUILD_TIME": built_at.isoformat().replace("+00:00", "Z"),
        "REVOCOMPUTE_BUILD_ID": f"{sha[:7]}-{stamp}" if sha else "",
        "REVOCOMPUTE_BASE_VERSION": base_version,
        "REVOCOMPUTE_RELEASE_CHANNEL": release_channel,
    }


def build_web_images(state, compose_cmd: tuple[str, ...], proxy_build_args: list[str], uid: str, gid: str) -> None:
    print("Building web/worker images...")
    username = state.get("RUNNER_USERNAME") or "revodesign"
    group = state.get("RUNNER_GROUP") or "revodesign_appgroup"
    identity = collect_build_identity(
        state.server_root(), state.get("REVOCOMPUTE_RELEASE_CHANNEL") or "development"
    )
    if proxy_build_args:
        server_dockerfile = os.path.join(state.server_root(), "docker", "server", "Dockerfile")
        run_cmd(
            [
                "docker",
                "build",
                *proxy_build_args,
                "--build-arg",
                f"RUNNER_UID={uid}",
                "--build-arg",
                f"RUNNER_GID={gid}",
                "--build-arg",
                f"RUNNER_USERNAME={username}",
                "--build-arg",
                f"RUNNER_GROUP={group}",
                "--build-arg",
                f"PORT={state.get('PORT') or '8080'}",
                "--build-arg",
                f"REVOCOMPUTE_EXTRAS={state.get('REVOCOMPUTE_EXTRAS') or 'resend'}",
                *[item for name, value in identity.items() for item in ("--build-arg", f"{name}={value}")],
                "-t",
                state.get("SERVER_IMAGE") or "revodesign-revocompute-server",
                "-f",
                server_dockerfile,
                state.server_root(),
            ],
            env=state.exported(),
        )
    else:
        # The compose file interpolates the same identity into its build args;
        # runtime exports take precedence over the env file, so one snapshot
        # reaches both the frontend builder and the server image.
        state.runtime.update(identity)
        run_cmd(
            [*compose_cmd, *compose_args(state), "--env-file", state.env_file, "build", "web", "worker", "tool-worker"],
            env=state.exported(),
        )


def cmd_build(
    state,
    compose_cmd: tuple[str, ...],
    use_proxy_from_env: bool,
    use_proxy: str,
    *,
    runners_only: bool = False,
    server_only: bool = False,
    materialize: bool = True,
) -> None:
    """Materialize the prepared Runner snapshot and optionally build server images.

    Materialization always writes the candidate trees.  The running worker
    bind-mounts the active trees live, so a build/prepare that rewrote them
    could hand the old Server code a contract it cannot parse before the stop
    step ever runs.
    """
    from revocompute_ctl.steps import materialize_prepared_snapshot, prepared_runner_root

    # The gateway route is deployment state reconciled from MCP_ENABLED, so it is
    # resolved before anything starts a container that would read it.
    from revocompute_ctl.mcp import apply_gateway

    if not materialize:
        apply_gateway(state)

    if materialize:
        materialize_prepared_snapshot(state)
    proxy_build_args = resolve_proxy_args(state, use_proxy_from_env, use_proxy)
    from revocompute_ctl.storage import resolve_runner_identity

    from revocompute.runner_registry import migrate_legacy_sif_evidence, validate_runtime_files

    # A materializing build validates the candidate it just wrote; a
    # non-materializing build (the dev restart, after activation) validates the
    # active tree that is already in place.
    if materialize:
        families = validate_runtime_files(state, plugin_root=prepared_runner_root(state))
    else:
        families = validate_runtime_files(state)
    uid, gid = resolve_runner_identity(state)
    if state.use_slurm():
        migrate_legacy_sif_evidence(state, families)
    if not runners_only:
        build_web_images(state, compose_cmd, proxy_build_args, uid, gid)


def resolve_proxy_args(state, use_proxy_from_env: bool, use_proxy: str) -> list[str]:
    if use_proxy_from_env:
        use_proxy = state.get("REVODESIGN_BUILD_PROXY")
        if not use_proxy:
            print(f"--use-proxy requires REVODESIGN_BUILD_PROXY in {state.env_file}.", file=sys.stderr)
            raise SystemExit(1)
        state.runtime["HTTP_PROXY"] = use_proxy
        state.runtime["HTTPS_PROXY"] = use_proxy
        state.runtime["NO_PROXY"] = state.get("NO_PROXY") or "localhost,127.0.0.1,.local"
    if not use_proxy:
        return []
    print("Using configured proxy for dependency downloads (credential redacted).")
    http_proxy = state.runtime.get("HTTP_PROXY") or use_proxy
    https_proxy = state.runtime.get("HTTPS_PROXY") or use_proxy
    no_proxy = state.runtime.get("NO_PROXY") or "localhost,127.0.0.1,.local"
    return [
        "--build-arg",
        f"HTTP_PROXY={http_proxy}",
        "--build-arg",
        f"HTTPS_PROXY={https_proxy}",
        "--build-arg",
        f"NO_PROXY={no_proxy}",
        "--build-arg",
        f"http_proxy={http_proxy}",
        "--build-arg",
        f"https_proxy={https_proxy}",
        "--build-arg",
        f"no_proxy={no_proxy}",
    ]
