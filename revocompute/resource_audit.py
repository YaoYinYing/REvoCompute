# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Read-only deployment resource-policy preflight.

Designed to run inside the already-prepared worker image before Compose stops
the healthy stack. It never writes the management database.
"""

from __future__ import annotations

import sys

from revocompute.config import ComputeConfig, env_csv
from revocompute.manage_db import read_resource_database
from revocompute.resource_policy import ResourceValidationError, resolve_resources
from revocompute.task_types import get as get_task_type
from revocompute.task_types import discover_plugins, list_types


def main() -> int:
    config = ComputeConfig.from_env()
    discover_plugins(config.runners_dir, set(env_csv("ENABLED_TASKRUNNERS", "")))
    globals_, task_values = read_resource_database(config.manage_db_path)
    stored_allowed = globals_.get("slurm_allowed_queues")
    allowed = (
        tuple(value.strip() for value in stored_allowed.split(",") if value.strip())
        if stored_allowed is not None
        else tuple(config.slurm_allowed_queues)
    )
    failed = False
    for task_type in list_types():
        _, runner = get_task_type(task_type.name)
        task_config = task_values.get(task_type.name, {})
        if task_config.get("enabled") == 0:
            print(f"[RESOURCE] {task_type.name}: disabled (not audited)")
            continue
        profiles = [(task_type.name, task_type.gpus)]
        if task_type.workflow:
            profiles = [(stage.name, stage.requires_gpu) for stage in task_type.workflow]
        for profile_name, requires_gpu in profiles:
            values = task_values.get(profile_name, task_config if requires_gpu else {})
            try:
                resolved = resolve_resources(
                    values.get,
                    globals_.get,
                    requires_gpu=requires_gpu,
                    allowed_queues=allowed,
                    default_timeout_seconds=runner.max_runtime_seconds,
                )
                accelerator = resolved.gres or "cpu"
                partition = resolved.partition or "scheduler-default"
                print(
                    f"[RESOURCE] {profile_name}: cpus={resolved.cpus} memory={resolved.memory} "
                    f"time={resolved.slurm_time} accelerator={accelerator} partition={partition}"
                )
            except ResourceValidationError as exc:
                failed = True
                print(f"[RESOURCE] {profile_name}: INVALID: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
