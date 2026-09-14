# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Ephemeral Tool workspace cleanup and worker-side idle-runtime control."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

from celery import Celery

from revocompute.config import ComputeConfig, ToolConfig
from revocompute.maintenance.model import PeriodicTask
from revocompute.tool_calls import ToolCallDatabase
from revocompute.tool_workspace import ToolWorkspace


def run_tool_cleanup() -> int:
    compute = ComputeConfig.from_env()
    config = ToolConfig.from_env(compute)
    calls = ToolCallDatabase(compute.db_path)
    workspace = ToolWorkspace(
        config.workspace_root,
        request_max_bytes=config.request_max_bytes,
        output_max_bytes=config.output_max_bytes,
    )
    removed = 0
    for record in calls.cleanup_candidates(now=time.time()):
        call_id = str(record["tool_call_id"])
        workspace.delete(call_id)
        removed += int(calls.delete_terminal(call_id))
    if calls.total_workspace_bytes() > config.storage_max_bytes:
        for record in calls.cleanup_candidates(now=time.time(), storage_pressure=True):
            call_id = str(record["tool_call_id"])
            workspace.delete(call_id)
            removed += int(calls.delete_terminal(call_id))
            if calls.total_workspace_bytes() <= config.storage_max_bytes:
                break
    calls.engine.dispose()

    password = os.environ.get("REDIS_PASSWORD", "")
    auth = f":{password}@" if password else ""
    redis_url = os.environ.get("REDIS_URL", f"redis://{auth}localhost:6379/0")
    control = Celery("revocompute_tool_control", broker=os.environ.get("BROKER_URL", redis_url))
    try:
        control.send_task("revocompute.stop_idle_tool_runtimes", queue="tools")
    except Exception:
        logging.exception("Could not enqueue Tool runtime idle-shutdown control")
    if removed:
        logging.info("Removed %d expired or storage-pressure Tool call(s)", removed)
    return removed


class ToolCleanupTask(PeriodicTask):
    id = "tool-call-cleanup"

    @property
    def task_method(self) -> Callable[..., Any]:
        return run_tool_cleanup

    def configure(self) -> None:
        enabled_families = tuple(value.strip() for value in os.environ.get("ENABLED_TOOL_FAMILIES", "").split(",") if value.strip())
        self.env = {"ENABLED_TOOL_FAMILIES": enabled_families}
        self._is_enabled = bool(enabled_families)
        self._args = {
            "trigger": "interval",
            "minutes": 1,
            "misfire_grace_time": 60,
            "next_run_time": datetime.now(timezone.utc),
        }
        if not self._is_enabled:
            self._args = {}


tool_cleanup_task = ToolCleanupTask()
