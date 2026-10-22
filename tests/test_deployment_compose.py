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
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "docker-compose.yml"
SLURM_COMPOSE = ROOT / "docker-compose.slurm.yml"
MCP_COMPOSE = ROOT / "docker-compose.mcp.yml"

SAFE_ENV = {
    "SERVER_DIR": str(ROOT),
    "RUNNERS_DIR": str(ROOT / "docker" / "runners"),
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


def _rendered_services(extra_env: dict[str, str]) -> dict[str, dict[str, Any]]:
    completed = _render(extra_env)
    assert completed.returncode == 0, completed.stderr
    return yaml.safe_load(completed.stdout)["services"]


def _environment(services: dict[str, dict[str, Any]], name: str) -> dict[str, str]:
    return dict(services[name].get("environment") or {})


def test_the_resource_governance_settings_reach_their_services() -> None:
    """The documented knobs are forwarded to the containers that read them.

    ``RESOURCE_MAINTENANCE_SECONDS`` belongs to the maintenance scheduler, and the
    scratch limit/guard belong to the task-executing worker path: each is read
    from the process environment of the service that acts on it, so a value an
    operator sets in the deployment env must arrive there.  The assertions go
    through the rendered Compose *model*, not through the file's text.
    """
    services = _rendered_services(
        {
            "RESOURCE_MAINTENANCE_SECONDS": "600",
            "TASK_SCRATCH_LIMIT_BYTES": "12345",
            "TASK_SCRATCH_GUARD_SECONDS": "7.5",
        }
    )

    assert _environment(services, "maintenance")["RESOURCE_MAINTENANCE_SECONDS"] == "600"
    # The task-executing worker is where the allocation wrapper -- which reads
    # both scratch settings from its own process environment -- actually runs.
    for service in ("worker", "tool-worker"):
        assert _environment(services, service)["TASK_SCRATCH_LIMIT_BYTES"] == "12345"
        assert _environment(services, service)["TASK_SCRATCH_GUARD_SECONDS"] == "7.5"
    # A scheduler that runs no allocation has no use for the maintenance interval.
    for service in ("worker", "tool-worker", "web"):
        assert "RESOURCE_MAINTENANCE_SECONDS" not in _environment(services, service)


def test_the_scratch_settings_are_not_forwarded_to_unrelated_services() -> None:
    """Only the task-executing path receives per-execution scratch settings."""
    services = _rendered_services(
        {"TASK_SCRATCH_LIMIT_BYTES": "12345", "TASK_SCRATCH_GUARD_SECONDS": "7.5"}
    )

    for service in ("redis", "gateway"):
        assert "TASK_SCRATCH_LIMIT_BYTES" not in _environment(services, service)
        assert "TASK_SCRATCH_GUARD_SECONDS" not in _environment(services, service)


def test_unset_resource_governance_settings_keep_the_shipped_defaults() -> None:
    """An unset operator value forwards as empty, which is the default.

    The runner reads an empty ``TASK_SCRATCH_LIMIT_BYTES`` as its own documented
    default, and the maintenance task reads an empty
    ``RESOURCE_MAINTENANCE_SECONDS`` as "unregistered" -- so the rendered stack
    with nothing set must carry the empty value rather than an invented one.
    """
    services = _rendered_services({})

    assert _environment(services, "maintenance")["RESOURCE_MAINTENANCE_SECONDS"] == ""
    assert _environment(services, "worker")["TASK_SCRATCH_LIMIT_BYTES"] == ""
    assert _environment(services, "worker")["TASK_SCRATCH_GUARD_SECONDS"] == ""


def test_the_slurm_override_does_not_shadow_the_forwarded_settings() -> None:
    """Layering the Slurm override must not lose a forwarded value.

    The override rewrites the worker's redis URLs and mounts the scheduler
    boundary; it must leave the environment the base file forwards intact.
    """
    without_override = subprocess.run(
        [*_compose_command(), "-f", str(BASE_COMPOSE), "config"],
        env={**SAFE_ENV, "TASK_SCRATCH_LIMIT_BYTES": "12345"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert without_override.returncode == 0, without_override.stderr
    base_worker = yaml.safe_load(without_override.stdout)["services"]["worker"]["environment"]

    layered = _rendered_services({"TASK_SCRATCH_LIMIT_BYTES": "12345"})
    assert base_worker["TASK_SCRATCH_LIMIT_BYTES"] == "12345"
    assert _environment(layered, "worker")["TASK_SCRATCH_LIMIT_BYTES"] == "12345"


def _render_mcp(extra_env: dict[str, str], *, profile: bool = False) -> subprocess.CompletedProcess[str]:
    """Render the real stack with the MCP overlay layered, as the controller does.

    ``profile=False`` matches a caller that layers the file without enabling the
    profile (a bare ``docker compose config``); ``profile=True`` adds the
    ``--profile mcp`` the deployment controller passes once a deployment opted in,
    which is what makes the profile-gated ``mcp`` service part of the model.
    """
    environment = {k: v for k, v in os.environ.items() if k != "CONFIG_DIR"}
    environment.update(SAFE_ENV)
    environment.update(extra_env)
    profile_args = ["--profile", "mcp"] if profile else []
    return subprocess.run(
        [*_compose_command(), "-f", str(BASE_COMPOSE), "-f", str(MCP_COMPOSE), *profile_args, "config"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_mcp_overlay_adds_an_internal_service_and_never_a_published_port() -> None:
    """The opt-in adds a container-internal ``mcp`` service, never a public port.

    "MCP is a protocol projection, not a second execution plane" has a Compose
    consequence: the surface is served by a service, but that service publishes
    nothing, mounts nothing new, and runs the same image as ``web`` -- the one
    entrypoint the HTTP API already runs.  The service is profile-gated, so it is
    absent from a model that layers the file without enabling the profile, and the
    web service's port and volume set is unchanged either way.  Each of those is an
    assertion below, so an overlay that grew a published port or a differently
    configured execution plane fails here rather than silently shipping.
    """
    base_run = subprocess.run(
        [*_compose_command(), "-f", str(BASE_COMPOSE), "config"],
        env={**SAFE_ENV},
        capture_output=True,
        text=True,
        check=False,
    )
    assert base_run.returncode == 0, base_run.stderr
    base = yaml.safe_load(base_run.stdout)

    # Layering the file on its own changes no service set: the profile keeps the
    # ``mcp`` service out of a model nobody opted into.
    unprofiled = _render_mcp({"MCP_ENABLED": "true", "MCP_PORT": "8081"})
    assert unprofiled.returncode == 0, unprofiled.stderr
    assert set(yaml.safe_load(unprofiled.stdout)["services"]) == set(base["services"])

    completed = _render_mcp({"MCP_ENABLED": "true", "MCP_PORT": "8081"}, profile=True)
    assert completed.returncode == 0, completed.stderr
    layered = yaml.safe_load(completed.stdout)

    assert set(layered["services"]) == set(base["services"]) | {"mcp"}
    assert _environment(layered["services"], "web")["MCP_ENABLED"] == "true"
    assert _environment(layered["services"], "web")["MCP_PORT"] == "8081"
    mcp = layered["services"]["mcp"]
    assert mcp["command"] == ["python", "-m", "revocompute.mcp"]
    assert mcp["image"] == layered["services"]["web"]["image"]
    assert mcp["build"] == layered["services"]["web"]["build"]
    assert mcp["volumes"] == layered["services"]["web"]["volumes"]
    # The MCP port is container-internal on the ``mcp`` service and nowhere else:
    # the service publishes no host port, so nothing outside the compose network
    # reaches it directly.  `!override` replaces the inherited `expose` list, so
    # the service exposes the MCP port alone rather than the web port as well.
    assert not (mcp.get("ports") or [])
    assert [str(value) for value in (mcp.get("expose") or [])] == ["8081"]
    # Enabling MCP adds no published port and no volume to any service.
    for name, service in layered["services"].items():
        assert service.get("ports") == base["services"].get(name, {}).get("ports"), name
        if name != "mcp":
            assert (service.get("volumes") or []) == (base["services"][name].get("volumes") or []), name

