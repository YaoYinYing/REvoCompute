# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deployment-side publication of derived Runner readiness evidence.

The evaluator and its vocabulary live in ``revocompute.runner_readiness`` and
are shared by the CLI, production admission, and the Admin API.  Publishing the
result into the web process's ``SERVER_DIR/readiness`` is a deployment
operation, so it stays here with the other container-boundary code.
"""

from __future__ import annotations

import json
import shlex
import shutil
from pathlib import Path
from typing import Any

from revocompute.runner_readiness import (
    RunnerReadiness,
    invalidate_deployment_attestations,
    resolve_runner_readiness,
)
from revocompute.runner_registry import RuntimeFamily, runner_enabled
from revocompute_ctl.compose import container_fs


def _remove_host_attestation_files(state) -> None:
    """Remove files left by the pre-service publication implementation."""
    server_root = Path(state.server_dir())
    for path in (server_root / "readiness", server_root / ".readiness-publish"):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        except (FileNotFoundError, PermissionError):
            continue


def _clear_container_attestations(state) -> None:
    server_root = Path(state.server_dir())
    if not any((server_root / name).exists() for name in ("readiness", ".readiness-publish")):
        return
    container_fs(
        state,
        "set -eu; rm -rf /srv/readiness /srv/.readiness-publish",
        [(state.server_dir(), "/srv")],
    )


def clear_deployment_attestations(state) -> None:
    """Clear readiness before a deployment mutation, using the service identity."""
    invalidate_deployment_attestations(state)
    _clear_container_attestations(state)


def _publish_attestation(state, family: RuntimeFamily, payload: dict[str, Any]) -> None:
    filename = f"{family.name}.json"
    temporary = f"/srv/.readiness-publish/.{family.name}.json.$$"
    script = (
        "set -eu; umask 022; mkdir -p /srv/.readiness-publish; chmod 0755 /srv/.readiness-publish; "
        f"tmp=\"{temporary}\"; trap 'rm -f \"$tmp\"' EXIT; "
        "cat > \"$tmp\"; chmod 0644 \"$tmp\"; "
        f"mv -f \"$tmp\" /srv/.readiness-publish/{shlex.quote(filename)}; trap - EXIT"
    )
    container_fs(
        state,
        script,
        [(state.server_dir(), "/srv")],
        stdin_data=json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
    )


def write_runner_attestation(state, family: RuntimeFamily) -> None:
    """Atomically refresh one Runner without revalidating unrelated SIFs."""
    payload = resolve_runner_readiness(state, family).as_dict()
    filename = shlex.quote(f"{family.name}.json")
    script = (
        "set -eu; umask 022; mkdir -p /srv/readiness; chmod 0755 /srv/readiness; "
        f"tmp=/srv/readiness/.{filename}.$$; trap 'rm -f \"$tmp\"' EXIT; "
        "cat > \"$tmp\"; chmod 0644 \"$tmp\"; "
        f"mv -f \"$tmp\" /srv/readiness/{filename}; trap - EXIT"
    )
    try:
        container_fs(
            state,
            script,
            [(state.server_dir(), "/srv")],
            stdin_data=json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        )
    except BaseException:
        container_fs(
            state,
            f"rm -f /srv/readiness/{filename}",
            [(state.server_dir(), "/srv")],
        )
        raise


def write_submission_attestation(state, families: list[RuntimeFamily]) -> None:
    """Publish complete readiness evidence as the configured service identity."""
    try:
        payloads = [
            (family, resolve_runner_readiness(state, family).as_dict())
            for family in families
            if runner_enabled(state, family.name)
        ]
        container_fs(
            state,
            "set -eu; umask 022; rm -rf /srv/.readiness-publish; mkdir -m 0755 /srv/.readiness-publish",
            [(state.server_dir(), "/srv")],
        )
        for family, payload in payloads:
            _publish_attestation(state, family, payload)
        container_fs(
            state,
            "set -eu; rm -rf /srv/readiness; mv /srv/.readiness-publish /srv/readiness; chmod 0755 /srv/readiness",
            [(state.server_dir(), "/srv")],
        )
    except BaseException:
        try:
            clear_deployment_attestations(state)
        except BaseException:
            pass
        raise


__all__ = [
    "RunnerReadiness",
    "clear_deployment_attestations",
    "write_runner_attestation",
    "write_submission_attestation",
]
