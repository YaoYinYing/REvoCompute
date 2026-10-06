# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Data-lifecycle purge and resource reconciliation as a periodic task.

Two jobs with one thing in common: both must be safe to run again after a crash,
and neither may guess.

*Purge* finishes deletions that were *authorized* — a user or an Admin already
moved the Task to ``DELETE_REQUESTED`` — and re-drives a purge whose worker died
between its claim and its completion.  It deliberately never decides on its own
that data is old enough to delete: automatic retention is a policy nobody has
opted into yet (see ``docs/``), and the same env knob that would carry it is
what disables this task entirely.

*Reconciliation* releases admission holds whose submission never started and
reports the inconsistencies it can see but must not repair.  The scheduler-side
settlement step belongs to the worker (it owns ``scontrol``), so it is not
duplicated here.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from revocompute import resource_lifecycle
from revocompute.config import ComputeConfig, env_int
from revocompute.db import TaskDatabase
from revocompute.maintenance.model import PeriodicTask
from revocompute.maintenance.tasks.result_cleanup import delete_task_artifacts

#: Opt-in cadence, in seconds.  Zero (the default) leaves the task unregistered:
#: a deployment that never sets it is exactly as it was before, and an operator
#: who wants interrupted deletions finished turns it on deliberately — the same
#: opt-in shape as result retention.  A purge is a bounded filesystem walk and a
#: reconciliation pass is a handful of indexed reads, so a small value is cheap.
DEFAULT_RESOURCE_MAINTENANCE_SECONDS = 0


def _remove_artifacts(results_folder: str) -> Callable[[dict[str, Any]], None]:
    """Bind the storage layout once, so the lifecycle module owns only the transaction."""
    workspace_folder = os.path.join(os.path.dirname(results_folder), "workspaces")

    def remove(task: dict[str, Any]) -> None:
        delete_task_artifacts(task, results_folder, workspace_folder)

    return remove


def run_resource_maintenance(
    *,
    task_store: TaskDatabase | None = None,
    results_folder: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Run one purge + reconciliation pass and return what it changed."""
    config = ComputeConfig.from_env()
    store = task_store or TaskDatabase(config.db_path)
    remove_artifacts = _remove_artifacts(results_folder or config.results_folder)
    timestamp = time.time() if now is None else now

    purged = resource_lifecycle.purge_requested_tasks(
        store, remove_artifacts=remove_artifacts, now=timestamp
    )
    recovered = resource_lifecycle.retry_stale_purges(
        store, remove_artifacts=remove_artifacts, now=timestamp
    )
    report = resource_lifecycle.reconcile_resources(store, now=timestamp)
    if purged["purged"] or recovered["recovered"] or report.drift:
        logging.info(
            "Resource maintenance: purged=%d recovered=%d expired_reservations=%d drift=%d",
            purged["purged"],
            recovered["recovered"],
            report.expired_reservations,
            len(report.drift),
        )
    for drift in report.drift:
        logging.warning("Resource drift [%s] %s: %s", drift.kind, drift.subject, drift.detail)
    return {
        "purged": purged["purged"],
        "purge_failures": purged["failed"],
        "recovered_purges": recovered["recovered"],
        "expired_reservations": report.expired_reservations,
        "drift": [item.to_dict() for item in report.drift],
    }


class ResourceMaintenanceTask(PeriodicTask):
    """Authorized-deletion completion plus bounded resource reconciliation."""

    id = "resource-maintenance"

    @property
    def task_method(self) -> Callable[..., Any]:
        return run_resource_maintenance

    def configure(self) -> None:
        interval = env_int("RESOURCE_MAINTENANCE_SECONDS", DEFAULT_RESOURCE_MAINTENANCE_SECONDS)
        self.env = {"RESOURCE_MAINTENANCE_SECONDS": interval}
        if interval < 0:
            raise ValueError("RESOURCE_MAINTENANCE_SECONDS must be zero or positive")
        # Zero disables the pass rather than spinning: the interval feeds
        # APScheduler, where a zero-second trigger would re-run immediately.
        self._is_enabled = interval > 0
        self._args = (
            {
                "trigger": "interval",
                "seconds": interval,
                "misfire_grace_time": max(interval, 60),
                "next_run_time": datetime.now(timezone.utc),
            }
            if self._is_enabled
            else {}
        )


resource_maintenance_task = ResourceMaintenanceTask()
