# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Dedicated asynchronous execution path for authenticated Tool calls."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from celery import Celery

from revocompute.config import ComputeConfig, ToolConfig
from revocompute.tool_calls import ToolCallDatabase
from revocompute.tool_runtime_manager import RuntimeUnavailable, ToolExecutionTimeout, ToolRuntimeManager
from revocompute.tool_types import ToolRegistry
from revocompute.tool_workspace import ToolWorkspace, ToolWorkspaceError

COMPUTE_CONFIG = ComputeConfig.from_env()
CONFIG = ToolConfig.from_env(COMPUTE_CONFIG)

_redis_password = os.environ.get("REDIS_PASSWORD", "")
_redis_auth = f":{_redis_password}@" if _redis_password else ""
_redis_url = os.environ.get("REDIS_URL", f"redis://{_redis_auth}localhost:6379/0")
celery = Celery(
    "revocompute_tools",
    broker=os.environ.get("BROKER_URL", _redis_url),
    backend=os.environ.get("RESULT_BACKEND", _redis_url),
)
celery.conf.update(
    broker_connection_retry_on_startup=True,
    task_default_queue="tools",
    task_routes={"revocompute.run_tool_call": {"queue": "tools"}},
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

tool_calls = ToolCallDatabase(COMPUTE_CONFIG.db_path)
tool_registry = ToolRegistry.discover(
    CONFIG.tools_dir,
    enabled=set(CONFIG.enabled_families),
    image_root=CONFIG.image_dir,
    maximum_timeout=CONFIG.call_timeout_seconds,
)
tool_workspace = ToolWorkspace(
    CONFIG.workspace_root,
    request_max_bytes=CONFIG.request_max_bytes,
    output_max_bytes=CONFIG.output_max_bytes,
)
runtime_manager = ToolRuntimeManager(
    CONFIG.runtime_state_root,
    tool_calls,
    idle_ttl_seconds=CONFIG.runtime_idle_ttl_seconds,
)


class _CallNotRunnable(RuntimeError):
    """The call left its preparing state before the child process started."""


def _public_inputs(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        role: [
            {key: item[key] for key in ("original_name", "format", "sha256", "size") if key in item}
            for item in values
        ]
        for role, values in manifest.get("inputs", {}).items()
    }


def _public_outputs(outputs: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {
        role: [{key: item[key] for key in ("path", "format", "logical_type", "sha256", "size")} for item in values]
        for role, values in outputs.items()
    }


def _finish_failed(
    tool_call_id: str,
    *,
    error_class: str,
    message: str,
    calls: ToolCallDatabase = tool_calls,
    workspace: ToolWorkspace = tool_workspace,
    config: ToolConfig = CONFIG,
) -> None:
    now = time.time()
    try:
        workspace_bytes = workspace.bytes_used(tool_call_id)
    except OSError:
        workspace_bytes = 0
    calls.transition(
        tool_call_id,
        expected=("queued", "preparing", "running"),
        status="failed",
        finished_at=now,
        expires_at=now + config.call_ttl_seconds,
        workspace_bytes=workspace_bytes,
        reserved_bytes=0,
        error_class=error_class,
        error=message,
    )


def execute_tool_call(
    tool_call_id: str,
    *,
    calls: ToolCallDatabase = tool_calls,
    registry: ToolRegistry = tool_registry,
    workspace: ToolWorkspace = tool_workspace,
    manager: ToolRuntimeManager = runtime_manager,
    config: ToolConfig = CONFIG,
) -> None:
    """Execute one persisted call through injectable protocol boundaries."""
    record = calls.get(tool_call_id)
    if record is None or record["status"] != "queued":
        return
    started = time.time()
    try:
        tool = registry.get(str(record["tool_type"]))
        if not calls.transition(
            tool_call_id, expected=("queued",), status="preparing", started_at=started, error=None, error_class=None
        ):
            return
        cold_start = manager.ensure_warm(tool.runtime)
        input_manifest = json.loads(str(record["input_manifest_json"]))
        call_root = workspace.call_root(tool_call_id)
        argv = [
            *tool.runtime.entrypoint,
            "run",
            "--tool",
            tool.name,
            "--request",
            "/tool/scratch/request.json",
            "--output",
            "/tool/output",
        ]

        def mark_running() -> None:
            # Publish `running` only once the family execution lease is held,
            # so a call queued behind a same-family sibling stays `preparing`
            # and its timeout does not start while it is merely waiting.
            if not calls.transition(tool_call_id, expected=("preparing",), status="running"):
                raise _CallNotRunnable

        execution_started = time.time()
        completed = manager.execute(
            tool.runtime,
            argv,
            binds=(
                (call_root / "input", "/tool/input", "ro"),
                (call_root / "output", "/tool/output", "rw"),
                (call_root / "scratch", "/tool/scratch", "rw"),
            ),
            timeout_seconds=min(tool.timeout_seconds, config.call_timeout_seconds),
            output_max_bytes=config.output_max_bytes,
            on_child_start=mark_running,
        )
        if completed.returncode != 0:
            logging.error("Tool call %s child failed: %s", tool_call_id, completed.stderr[-4000:])
            _finish_failed(
                tool_call_id, error_class="conversion_failed", message="Tool execution failed",
                calls=calls, workspace=workspace, config=config,
            )
            return
        outputs, warnings, backend_provenance = workspace.collect(tool_call_id, tool)
        finished = time.time()
        result_manifest = {
            "version": 1,
            "tool_call_id": tool_call_id,
            "tool_type": tool.name,
            "tool_version": tool.version,
            "runtime_family": tool.runtime.name,
            "runtime_identity": tool.runtime.identity,
            "inputs": _public_inputs(input_manifest),
            "parameters": json.loads(str(record["parameter_json"])),
            "outputs": _public_outputs(outputs),
            "warnings": warnings,
            # Server-owned runtime identity above is authoritative; the child's
            # self-declared backend is untrusted and stays explicitly nested.
            "provenance": {"declared": dict(backend_provenance.get("declared", {}))},
            "timing": {
                "cold_start": cold_start,
                "tool_execution_seconds": finished - execution_started,
                "call_total_seconds": finished - float(record["created_at"]),
            },
        }
        calls.transition(
            tool_call_id,
            expected=("running",),
            status="finished",
            finished_at=finished,
            expires_at=finished + config.call_ttl_seconds,
            result_manifest_json=json.dumps(result_manifest, separators=(",", ":"), sort_keys=True),
            workspace_bytes=workspace.bytes_used(tool_call_id),
            reserved_bytes=0,
            error=None,
            error_class=None,
        )
    except RuntimeUnavailable:
        _finish_failed(
            tool_call_id, error_class="runtime_unavailable", message="Tool runtime is temporarily unavailable",
            calls=calls, workspace=workspace, config=config,
        )
    except _CallNotRunnable:
        # Another owner resolved the call before the child started; leave it be.
        return
    except ToolExecutionTimeout:
        _finish_failed(
            tool_call_id, error_class="timeout", message="Tool execution timed out",
            calls=calls, workspace=workspace, config=config,
        )
    except ToolWorkspaceError:
        _finish_failed(
            tool_call_id, error_class="resource_limit", message="Tool output contract or resource limit failed",
            calls=calls, workspace=workspace, config=config,
        )
    except Exception:
        logging.exception("Unexpected Tool call failure for %s", tool_call_id)
        _finish_failed(
            tool_call_id, error_class="internal_error", message="Tool execution failed internally",
            calls=calls, workspace=workspace, config=config,
        )


@celery.task(name="revocompute.run_tool_call")
def run_tool_call(tool_call_id: str) -> None:
    execute_tool_call(tool_call_id)


def stop_idle_runtimes() -> list[str]:
    return runtime_manager.stop_idle(tool_registry.families())


@celery.task(name="revocompute.stop_idle_tool_runtimes")
def stop_idle_tool_runtimes() -> list[str]:
    return stop_idle_runtimes()


def recover_tool_worker() -> int:
    now = time.time()
    recovered = tool_calls.fail_orphaned(finished_at=now, expires_at=now + CONFIG.call_ttl_seconds)
    stopped = runtime_manager.reset_cold(tool_registry.families())
    if stopped:
        logging.info("Stopped %d stale Tool runtime instance(s) at worker startup", len(stopped))
    return recovered


def shutdown_tool_worker() -> list[str]:
    return runtime_manager.reset_cold(tool_registry.families())


try:
    from celery.signals import worker_ready, worker_shutdown

    @worker_ready.connect
    def _on_worker_ready(sender=None, **_kwargs):
        app = getattr(sender, "app", None)
        if app is celery:
            recovered = recover_tool_worker()
            if recovered:
                logging.warning("Failed %d orphaned Tool calls after worker restart", recovered)

    @worker_shutdown.connect
    def _on_worker_shutdown(sender=None, **_kwargs):
        app = getattr(sender, "app", None)
        if app is celery:
            stopped = shutdown_tool_worker()
            if stopped:
                logging.info("Stopped %d Tool runtime instance(s) during worker shutdown", len(stopped))
except ImportError:  # pragma: no cover - Celery is a required production dependency
    pass
