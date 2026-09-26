# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Side-effect-free configuration for the REvoCompute web and worker processes."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass


def env_bool(var: str, default: bool) -> bool:
    raw = os.environ.get(var)
    if raw is None or raw == "":
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"Environment variable {var} must be a boolean value "
        "(one of: true/false/1/0/yes/no/on/off)."
    )


def env_str(var: str, default: str) -> str:
    value = os.environ.get(var)
    return value if value else default


def env_int(var: str, default: int) -> int:
    raw = os.environ.get(var, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {var} must be an integer, got {raw!r}") from exc


def env_float(var: str, default: float) -> float:
    raw = os.environ.get(var, "")
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {var} must be a finite number, got {raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"Environment variable {var} must be a finite number, got {raw!r}")
    return value


def env_path(var: str, default: str) -> str:
    value = os.environ.get(var)
    if value:
        return os.path.abspath(os.path.expanduser(value))
    return os.path.abspath(default)


def env_required_path(var: str) -> str:
    return os.path.abspath(os.path.expanduser(env_required(var)))


def env_required(var: str) -> str:
    value = os.environ.get(var, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {var} is not set")
    return value


def env_csv(var: str, default: str) -> list[str]:
    source = os.environ.get(var) or default
    return [value for raw in source.split(",") if (value := raw.strip())]


def env_choice(var: str, default: str, choices: set[str]) -> str:
    value = env_str(var, default).strip().lower()
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"Environment variable {var} must be one of: {allowed}")
    return value


_DECIMAL_ID = re.compile(r"[0-9]+")


def _canonical_identity(user_value: str, label: str) -> str:
    """Canonicalize one identity part: a decimal ID, or a name passed through.

    Docker accepts several numeric spellings besides decimal (``00``, ``+0``,
    ``0x0``) and resolves them all to uid 0, so anything that starts like a
    number but is not plain decimal is rejected rather than forwarded.
    """
    value = user_value.strip()
    if not value:
        return value
    if _DECIMAL_ID.fullmatch(value):
        return str(int(value))
    if value[0].isdigit() or value[0] in "+-":
        raise ValueError(f"Runner {label} must be a decimal ID or a name, got {user_value.strip()!r}")
    return value


def format_runner_identity(user_value: str, group_value: str) -> str:
    user = _canonical_identity(user_value, "user")
    group = _canonical_identity(group_value, "group")
    if not user or not group:
        raise RuntimeError("Runner user and group must both be provided.")
    if user in {"0", "root"} or group in {"0", "root"}:
        raise ValueError("Runner containers cannot run as root. Provide a non-root user and group.")
    return f"{user}:{group}"


def resolve_docker_user() -> str:
    username = os.environ.get("RUNNER_USERNAME")
    group = os.environ.get("RUNNER_GROUP")
    if username or group:
        if not username or not group:
            raise RuntimeError("RUNNER_USERNAME and RUNNER_GROUP must be set together.")
        return format_runner_identity(username, group)

    env_uid = os.environ.get("RUNNER_UID")
    env_gid = os.environ.get("RUNNER_GID")
    if env_uid or env_gid:
        if not env_uid or not env_gid:
            raise RuntimeError("RUNNER_UID and RUNNER_GID must both be defined.")
        return format_runner_identity(env_uid, env_gid)

    env_user = os.environ.get("RUNNER_USER")
    if env_user:
        if ":" not in env_user:
            raise RuntimeError("RUNNER_USER must be in the form '<user>:<group>'.")
        user_part, group_part = env_user.split(":", 1)
        return format_runner_identity(user_part, group_part)

    raise RuntimeError(
        "Runner user configuration missing. Set RUNNER_UID/RUNNER_GID or RUNNER_USERNAME/RUNNER_GROUP "
        "to a dedicated non-root account."
    )


def ensure_directories(*paths: str) -> None:
    for path in paths:
        os.makedirs(path, exist_ok=True)


@dataclass(frozen=True, slots=True)
class ComputeConfig:
    """Server-level configuration — task-type-specific settings live in runner YAMLs."""

    server_dir: str
    upload_folder: str
    workspace_folder: str
    results_folder: str
    db_path: str
    manage_db_path: str
    docker_user: str
    port: int
    result_download_mode: str
    runners_dir: str  # deployed runner-family root (docker/runners/)
    # Infrastructure bindings are server-owned.  Runner/task manifests may
    # provide images and commands, but cannot select these implementations.
    job_executor: str = "slurm"
    container_runtime: str = "apptainer"
    slurm_allowed_queues: list[str] = ()
    scratch_backend: str = "disk"

    def __post_init__(self) -> None:
        if self.job_executor != "slurm":
            raise ValueError("REvoCompute supports Slurm as its job executor")
        if self.container_runtime != "apptainer":
            raise ValueError("REvoCompute uses Apptainer as its container runtime")
        if self.scratch_backend not in {"disk", "ram"}:
            raise ValueError("scratch_backend must be 'disk' or 'ram'")

    @classmethod
    def from_env(cls) -> ComputeConfig:
        server_dir = env_required_path("SERVER_DIR")
        runners_dir = os.environ.get("RUNNERS_DIR", os.path.join(server_dir, "docker", "runners"))
        return cls(
            server_dir=server_dir,
            upload_folder=os.path.join(server_dir, "upload"),
            workspace_folder=os.path.join(server_dir, "workspaces"),
            results_folder=os.path.join(server_dir, "results"),
            db_path=env_path("DB_PATH", os.path.join(server_dir, "revocompute.sqlite3")),
            manage_db_path=env_path("MANAGE_DB_PATH", os.path.join(server_dir, "manage.sqlite")),
            docker_user=resolve_docker_user(),
            port=env_int("PORT", 8080),
            result_download_mode=env_choice("RESULT_DOWNLOAD_MODE", "flask", {"flask", "nginx"}),
            runners_dir=os.path.abspath(os.path.expanduser(runners_dir)),
            job_executor=env_choice("REVOCOMPUTE_JOB_EXECUTOR", "slurm", {"slurm"}),
            container_runtime=env_choice("REVOCOMPUTE_CONTAINER_RUNTIME", "apptainer", {"apptainer"}),
            slurm_allowed_queues=env_csv("SLURM_ALLOWED_QUEUES", ""),
            scratch_backend=env_choice("REVOCOMPUTE_SCRATCH_BACKEND", "disk", {"disk", "ram"}),
        )


@dataclass(frozen=True, slots=True)
class ToolConfig:
    """Server-owned limits and immutable roots for ephemeral Tool calls."""

    tools_dir: str
    image_dir: str
    workspace_root: str
    runtime_state_root: str
    enabled_families: tuple[str, ...]
    max_active_per_user: int
    max_active_global: int
    worker_concurrency: int
    call_timeout_seconds: int
    call_ttl_seconds: int
    runtime_idle_ttl_seconds: int
    storage_max_bytes: int
    request_max_bytes: int
    output_max_bytes: int

    def __post_init__(self) -> None:
        positive = {
            "TOOL_MAX_ACTIVE_PER_USER": self.max_active_per_user,
            "TOOL_MAX_ACTIVE_GLOBAL": self.max_active_global,
            "TOOL_WORKER_CONCURRENCY": self.worker_concurrency,
            "TOOL_CALL_TIMEOUT_SECONDS": self.call_timeout_seconds,
            "TOOL_CALL_TTL_SECONDS": self.call_ttl_seconds,
            "TOOL_RUNTIME_IDLE_TTL_SECONDS": self.runtime_idle_ttl_seconds,
            "TOOL_STORAGE_MAX_BYTES": self.storage_max_bytes,
            "TOOL_REQUEST_MAX_BYTES": self.request_max_bytes,
            "TOOL_OUTPUT_MAX_BYTES": self.output_max_bytes,
        }
        for name, value in positive.items():
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if self.max_active_per_user > self.max_active_global:
            raise ValueError("TOOL_MAX_ACTIVE_PER_USER cannot exceed TOOL_MAX_ACTIVE_GLOBAL")
        if self.request_max_bytes > self.storage_max_bytes or self.output_max_bytes > self.storage_max_bytes:
            raise ValueError("Per-call Tool storage limits cannot exceed TOOL_STORAGE_MAX_BYTES")

    @classmethod
    def from_env(cls, compute: ComputeConfig | None = None) -> ToolConfig:
        compute = compute or ComputeConfig.from_env()
        return cls(
            tools_dir=env_path("TOOLS_DIR", os.path.join(compute.server_dir, "docker", "tools")),
            image_dir=env_path("TOOL_IMAGE_DIR", os.path.join(compute.server_dir, "..", "images", "tools")),
            workspace_root=env_path("TOOL_WORKSPACE_ROOT", os.path.join(compute.workspace_folder, "tool_call")),
            runtime_state_root=env_path("TOOL_RUNTIME_STATE_ROOT", os.path.join(compute.server_dir, "tool-runtime")),
            enabled_families=tuple(env_csv("ENABLED_TOOL_FAMILIES", "")),
            max_active_per_user=env_int("TOOL_MAX_ACTIVE_PER_USER", 3),
            max_active_global=env_int("TOOL_MAX_ACTIVE_GLOBAL", 8),
            worker_concurrency=env_int("TOOL_WORKER_CONCURRENCY", 2),
            call_timeout_seconds=env_int("TOOL_CALL_TIMEOUT_SECONDS", 300),
            call_ttl_seconds=env_int("TOOL_CALL_TTL_SECONDS", 86400),
            runtime_idle_ttl_seconds=env_int("TOOL_RUNTIME_IDLE_TTL_SECONDS", 1800),
            storage_max_bytes=env_int("TOOL_STORAGE_MAX_BYTES", 104857600),
            request_max_bytes=env_int("TOOL_REQUEST_MAX_BYTES", 16777216),
            output_max_bytes=env_int("TOOL_OUTPUT_MAX_BYTES", 33554432),
        )
