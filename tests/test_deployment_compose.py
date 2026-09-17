# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Deployment composition regression tests.

Issue #19: the Slurm override must not assume ``CONFIG_DIR`` holds the Runner
family tree.  ``RUNNERS_DIR`` is the sole source of the materialized tree, and
``CONFIG_DIR`` is optional deployment-owned configuration.  These tests render
the real stack with Compose interpolation and fail if ``CONFIG_DIR`` ever
becomes mandatory again.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "docker-compose.yml"
SLURM_COMPOSE = ROOT / "docker-compose.slurm.yml"

SAFE_ENV = {
    "SERVER_DIR": str(ROOT),
    "LOG_DIR": str(ROOT / "logs"),
    "AUTH_DIR": str(ROOT / "auth-data"),
    "ADMIN_USERS": "admin",
    "REDIS_PASSWORD": "compose-regression-secret",
    "RUNNER_UID": "1000",
    "RUNNER_GID": "1000",
    "RUNNER_USERNAME": "revodesign",
    "RUNNER_GROUP": "revodesign",
    "GATEWAY_BIND": "127.0.0.1",
    "PORT": "8080",
}


def _compose_command() -> tuple[str, ...] | None:
    """Reuse the deployment controller's Compose detection, skipping if absent."""
    try:
        from revocompute_ctl.compose import detect_compose_cmd

        return detect_compose_cmd()
    except (ImportError, SystemExit):
        return None


def _render(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    command = _compose_command()
    if command is None:
        pytest.skip("docker compose is not available")
    environment = {k: v for k, v in os.environ.items() if k != "CONFIG_DIR"}
    environment.update(SAFE_ENV)
    environment.update(extra_env)
    return subprocess.run(
        [*command, "-f", str(BASE_COMPOSE), "-f", str(SLURM_COMPOSE), "config"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("config_env", [{}, {"CONFIG_DIR": ""}])
def test_slurm_stack_renders_without_config_dir(config_env: dict[str, str]) -> None:
    completed = _render(config_env)
    assert completed.returncode == 0, completed.stderr
    model = yaml.safe_load(completed.stdout)
    assert model["services"], "compose render produced no services"


def test_slurm_stack_mounts_the_runner_tree_and_never_config_dir() -> None:
    completed = _render({})
    assert completed.returncode == 0, completed.stderr
    model = yaml.safe_load(completed.stdout)
    runners_dir = str(ROOT / "docker" / "runners")
    for name, service in model["services"].items():
        for volume in service.get("volumes") or []:
            source = volume.get("source") if isinstance(volume, dict) else str(volume).split(":")[0]
            assert "CONFIG_DIR" not in str(source), f"{name} mounts CONFIG_DIR: {source}"
    for name in ("web", "maintenance", "worker"):
        service = model["services"][name]
        sources = [
            volume.get("source") if isinstance(volume, dict) else str(volume).split(":")[0]
            for volume in service.get("volumes") or []
        ]
        assert runners_dir in sources, f"{name} does not mount the Runner tree"
        assert service["environment"]["RUNNERS_DIR"] == runners_dir
