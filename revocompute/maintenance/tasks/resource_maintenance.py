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


#: Bound on the entries one drift measurement visits per Task.  A result tree
#: is a handful of artifacts; a tree larger than this is not measurable within
#: the pass, and the drift check reports "unmeasurable" rather than a number it
#: did not finish computing.
OWNED_PATHS_MAX_ENTRIES = 20_000


def _owned_bytes_measure(results_folder: str) -> Callable[[str], int | None]:
    """Bind a bounded, unprivileged disk-usage measurement of one Task's data.

    It measures filesystem *occupancy* — allocated blocks — of the Task's result
    tree, which is what "these bytes are actually on disk" means for the drift
    check; apparent size would report a sparse file as capacity it never used.
    A Task with no result directory measures zero: there is no data under it.

    The path is resolved from the storage layout rather than passed in, because
    the pass only has a Task id and the layout already answers where that Task's
    data lives.  A tree too large to measure within the bound returns ``None``,
    which the caller reports as unmeasurable instead of a number it never
    finished computing.
    """
    results_abs = os.path.abspath(results_folder)
    tasks_root = os.path.join(results_abs, "users")

    def measure(task_id: str) -> int | None:
        if not os.path.isdir(tasks_root):
            return 0
        total = 0
        visited = 0
        found = False
        for user_root in os.scandir(tasks_root):
            if not user_root.is_dir(follow_symlinks=False):
                continue
            candidate = os.path.join(user_root.path, "tasks", task_id)
            if not os.path.isdir(candidate) or os.path.islink(candidate):
                continue
            found = True
            for walk_root, dirs, files in os.walk(candidate, followlinks=False):
                dirs[:] = [
                    name for name in dirs if not os.path.islink(os.path.join(walk_root, name))
                ]
                for name in files:
                    visited += 1
                    if visited > OWNED_PATHS_MAX_ENTRIES:
                        return None
                    try:
                        total += os.lstat(os.path.join(walk_root, name)).st_blocks * 512
                    except OSError:
                        continue
        return total if found else 0

    return measure


def _remove_artifacts(results_folder: str) -> Callable[[dict[str, Any]], None]:
    """Bind the storage layout once, so the lifecycle module owns only the transaction."""
    workspace_folder = os.path.join(os.path.dirname(results_folder), "workspaces")

    def remove(task: dict[str, Any]) -> None:
        delete_task_artifacts(task, results_folder, workspace_folder)

    return remove


def _surviving_receipt_tasks(results_folder: str) -> set[str]:
    """Task ids whose host-only allocation receipt has not been adopted yet.

    Reconciliation reads the results tree, not the database, because the whole
    window this serves is the one before any database write: a wrapper left the
    file the instant it was running and its worker died before reading it.  The
    namespace walk is the runner's own, imported lazily so the maintenance
    scheduler does not pull the Celery application in with the adapter module.
    """
    from revocompute.job.runners.slurm_runner import surviving_allocation_receipts

    try:
        return {str(receipt["task_id"]) for receipt in surviving_allocation_receipts(results_folder)}
    except OSError:
        return set()


def run_resource_maintenance(
    *,
    task_store: TaskDatabase | None = None,
    results_folder: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Run one purge + reconciliation pass and return what it changed."""
    config = ComputeConfig.from_env()
    store = task_store or TaskDatabase(config.db_path)
    results = results_folder or config.results_folder
    remove_artifacts = _remove_artifacts(results)
    owned_paths = _owned_bytes_measure(results)
    unadopted = _surviving_receipt_tasks(results)
    timestamp = time.time() if now is None else now

    purged = resource_lifecycle.purge_requested_tasks(
        store, remove_artifacts=remove_artifacts, now=timestamp
    )
    recovered = resource_lifecycle.retry_stale_purges(
        store, remove_artifacts=remove_artifacts, now=timestamp
    )
    report = resource_lifecycle.reconcile_resources(
        store,
        settle_allocations=_settle_slurm_allocations,
        owned_paths=owned_paths,
        unadopted_tasks=unadopted,
        now=timestamp,
    )
    if purged["purged"] or recovered["recovered"] or report.drift or report.reclaimed_reservations:
        logging.info(
            "Resource maintenance: purged=%d recovered=%d expired_reservations=%d released_reservations=%d drift=%d",
            purged["purged"],
            recovered["recovered"],
            report.expired_reservations,
            report.reclaimed_reservations,
            len(report.drift),
        )
    for drift in report.drift:
        logging.warning("Resource drift [%s] %s: %s", drift.kind, drift.subject, drift.detail)
    return {
        "purged": purged["purged"],
        "purge_failures": purged["failed"],
        "recovered_purges": recovered["recovered"],
        "settled_allocations": report.settled_allocations,
        "expired_reservations": report.expired_reservations,
        "released_reservations": report.reclaimed_reservations,
        "drift": [item.to_dict() for item in report.drift],
    }


def _settle_slurm_allocations() -> dict[str, int]:
    """The worker-owned scheduler-evidence step, published as a Docker-free boundary.

    ``task_runtime`` is imported lazily: it constructs the production Celery
    app at import time, which the maintenance scheduler must not do just to run
    this pass.
    """
    from revocompute import task_runtime

    return task_runtime.reconcile_slurm_allocations.run()


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
