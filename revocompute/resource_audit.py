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
from revocompute.placement import PlacementError, resolve_submission_placement
from revocompute.resource_policy import ResourceValidationError, ResourcePolicyValues
from revocompute.task_types import discover_plugins, get as get_task_type, list_types


def main() -> int:
    config = ComputeConfig.from_env()
    discover_plugins(config.runners_dir, set(env_csv("ENABLED_TASKRUNNERS", "")))
    globals_, task_values = read_resource_database(config.manage_db_path)
    if globals_.get("slurm_allowed_queues") is None and config.slurm_allowed_queues:
        globals_["slurm_allowed_queues"] = ",".join(config.slurm_allowed_queues)
    failed = False
    for task_type in list_types():
        _, runner = get_task_type(task_type.name)
        task_config = task_values.get(task_type.name, {})
        if task_config.get("enabled") == 0:
            print(f"[RESOURCE] {task_type.name}: disabled (not audited)")
            continue
        try:
            # The audit resolves the same placement the submission path does, from
            # the same persisted values, so a deployment cannot pass the preflight
            # audit and then reject every submission at the placement boundary.
            placement = resolve_submission_placement(
                ResourcePolicyValues(globals_, task_values), task_type, runner
            )
        except PlacementError as exc:
            failed = True
            print(f"[RESOURCE] {task_type.name}: INVALID ({exc.reason_code}): {exc}", file=sys.stderr)
            continue
        except ResourceValidationError as exc:
            failed = True
            print(f"[RESOURCE] {task_type.name}: INVALID: {exc}", file=sys.stderr)
            continue
        for decision in [placement.primary_decision, *placement.stage_decisions.values()]:
            if decision is None:
                continue
            resolved = decision.resources
            label = decision.stage or task_type.name
            print(
                f"[RESOURCE] {label}: cpus={resolved.cpus} memory={resolved.memory} "
                f"time={resolved.slurm_time} class={decision.execution_class.identifier} "
                f"reason={decision.reason_code}"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
