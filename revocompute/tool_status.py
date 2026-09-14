# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Operator status for ephemeral Tool runtime families."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from revocompute.config import ComputeConfig, ToolConfig
from revocompute.tool_calls import ToolCallDatabase
from revocompute.tool_runtime_manager import ToolRuntimeManager
from revocompute.tool_types import ToolRegistry


def collect_status() -> list[dict]:
    compute = ComputeConfig.from_env()
    config = ToolConfig.from_env(compute)
    calls = ToolCallDatabase(compute.db_path)
    registry = ToolRegistry.discover(
        config.tools_dir,
        enabled=set(config.enabled_families),
        image_root=config.image_dir,
        maximum_timeout=config.call_timeout_seconds,
    )
    manager = ToolRuntimeManager(
        config.runtime_state_root,
        calls,
        idle_ttl_seconds=config.runtime_idle_ttl_seconds,
    )
    try:
        return [
            asdict(manager.status(runtime))
            | {"image": str(runtime.image), "image_available": runtime.image.is_file()}
            for runtime in registry.families()
        ]
    finally:
        calls.engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="revocompute-tool-status")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    statuses = collect_status()
    if args.as_json:
        print(json.dumps({"runtimes": statuses}, indent=2, sort_keys=True))
    elif not statuses:
        print("No Tool runtime families are enabled.")
    else:
        for status in statuses:
            print(f"{status['family']}: {status['state']} active={status['active_calls']} image={status['image']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
