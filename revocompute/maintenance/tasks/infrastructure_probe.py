# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Periodic scheduler/GPU evidence pulse.

Scheduler and GPU probes must run in the compute worker (it owns the Slurm
clients and the GPU inventory), but the web service evaluates admission from
the snapshot that worker publishes.  Nothing else drives that snapshot after
worker boot, so without this pulse the evidence ages past
``INFRA_STALE_SECONDS`` and every submission is refused within a minute of a
restart.  This task dispatches one probe pass per interval; the worker owns the
probe itself.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from celery import Celery

from revocompute.config import ComputeConfig, env_int
from revocompute.maintenance.model import PeriodicTask
from revocompute.manage_db import read_resource_database


def _slurm_enabled() -> bool:
    values, _tasks = read_resource_database(ComputeConfig.from_env().manage_db_path)
    return str(values.get("slurm_enabled", "")).strip().lower() in ("true", "1", "yes", "on")


def run_infrastructure_probe() -> None:
    """Ask the compute worker for one fresh scheduler/GPU evidence pass."""
    password = os.environ.get("REDIS_PASSWORD", "")
    auth = f":{password}@" if password else ""
    redis_url = os.environ.get("REDIS_URL", f"redis://{auth}localhost:6379/0")
    control = Celery("revocompute_infrastructure_control", broker=os.environ.get("BROKER_URL", redis_url))
    control.send_task("probe_compute_infrastructure")


class InfrastructureProbeTask(PeriodicTask):
    """Environment-configured cadence for worker-published infrastructure evidence."""

    id = "infrastructure-probe"
    max_instances = 1

    @property
    def task_method(self) -> Callable[..., Any]:
        return run_infrastructure_probe

    def configure(self) -> None:
        interval = env_int("INFRA_REFRESH_SECONDS", 15)
        slurm_enabled = _slurm_enabled()
        self.env = {"INFRA_REFRESH_SECONDS": interval, "slurm_enabled": slurm_enabled}
        self._is_enabled = interval > 0 and slurm_enabled
        self._args = {}
        if not self._is_enabled:
            return
        self._args = {
            "trigger": "interval",
            "seconds": interval,
            "misfire_grace_time": max(60, interval),
            "next_run_time": datetime.now(timezone.utc),
        }


infrastructure_probe_task = InfrastructureProbeTask()
