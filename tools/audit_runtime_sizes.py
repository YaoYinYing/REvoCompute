# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Report Docker and SIF bytes once runtime artifacts exist on a builder.

This tool is deliberately inspect-only: it never builds, pulls, or runs an
image. Run it on the production builder after the normal build pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml


def _docker_size(image: str) -> int | None:
    docker = shutil.which("docker")
    if not docker:
        return None
    result = subprocess.run(  # nosec B603 -- fixed executable and arguments
        [docker, "image", "inspect", "--format", "{{.Size}}", image],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def collect_sizes(runners_dir: Path) -> list[dict[str, Any]]:
    """Inspect Docker/SIF artifacts declared by distributed plugin manifests."""
    rows: list[dict[str, Any]] = []
    for manifest_path in sorted(runners_dir.glob("*/plugin.yaml")):
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(manifest, dict):
            raise ValueError(f"Plugin manifest must be a mapping: {manifest_path}")
        runtime_name = str(manifest.get("id") or manifest_path.parent.name)
        runtime = manifest.get("runtime") or {}
        if not isinstance(runtime, dict):
            raise ValueError(f"Plugin runtime must be a mapping: {manifest_path}")
        sif_path = str(runtime.get("slurm_image") or runtime.get("image") or "")
        docker_image = str(runtime.get("docker_image") or f"revodesign-revocompute-runner-{runtime_name}:latest")
        tasks: list[str] = []
        for task_ref in manifest.get("tasks") or ():
            task_path = manifest_path.parent / str(task_ref)
            task = yaml.safe_load(task_path.read_text(encoding="utf-8")) or {}
            if isinstance(task, dict):
                tasks.append(str(task.get("id") or task.get("name") or task_path.parent.name))
        rows.append(
            {
                "runtime_family": runtime_name,
                "tasks": sorted(tasks),
                "docker_image": docker_image,
                "docker_bytes": _docker_size(docker_image),
                "sif_path": sif_path or None,
                "sif_bytes": os.path.getsize(sif_path) if sif_path and os.path.isfile(sif_path) else None,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    server_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--runners-dir", type=Path, default=server_root / "docker" / "runners")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Exit non-zero unless every declared Docker image and SIF is present",
    )
    args = parser.parse_args()
    rows = collect_sizes(args.runners_dir)
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        print("runtime_family\ttasks\tdocker_bytes\tsif_bytes\tdocker_image\tsif_path")
        for row in rows:
            print(
                "\t".join(
                    [
                        row["runtime_family"],
                        ",".join(row["tasks"]),
                        str(row["docker_bytes"] or "missing"),
                        str(row["sif_bytes"] or "missing"),
                        row["docker_image"],
                        row["sif_path"] or "-",
                    ]
                )
            )
    if args.require_all and any(row["docker_bytes"] is None or row["sif_bytes"] is None for row in rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
