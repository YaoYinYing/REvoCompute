#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Run the fpocket detector on the resolved named input role and record provenance.

fpocket has no output-directory flag: it writes ``<stem>_out/`` beside its input
file, so the caller runs it inside the task workspace. Every detector parameter
is resolved from the immutable task manifest, which is the only parameter
vocabulary owner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

DEFAULTS = {
    "min_alpha_sphere_radius": 3.4,
    "max_alpha_sphere_radius": 6.2,
    "min_alpha_spheres_per_pocket": 15,
    "clustering_distance": 2.4,
    "volume_monte_carlo_iterations": 300,
}
FLAGS = {
    "min_alpha_sphere_radius": "-m",
    "max_alpha_sphere_radius": "-M",
    "min_alpha_spheres_per_pocket": "-i",
    "clustering_distance": "-D",
    "volume_monte_carlo_iterations": "-v",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid task manifest: {exc}") from exc
    structures = document.get("inputs", {}).get("structure")
    if not isinstance(structures, list) or len(structures) != 1:
        raise SystemExit("fpocket requires exactly one structure input")
    params = document.get("params", {})
    if not isinstance(params, dict):
        raise SystemExit("Task params must be an object")
    unsupported = sorted(set(params) - set(DEFAULTS))
    if unsupported:
        raise SystemExit(f"Unsupported fpocket parameters: {', '.join(unsupported)}")
    return params


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=Path(os.environ.get("TASK_MANIFEST", "")))
    parser.add_argument("--fpocket", default=os.environ.get("FPOCKET_EXECUTABLE", "fpocket"))
    args = parser.parse_args()

    params = _load_manifest(args.manifest)
    resolved = {name: params.get(name, default) for name, default in DEFAULTS.items()}
    for name, value in resolved.items():
        if isinstance(DEFAULTS[name], int):
            if not isinstance(value, int) or isinstance(value, bool):
                raise SystemExit(f"{name} must be an integer")
        elif not isinstance(value, (int, float)) or isinstance(value, bool):
            raise SystemExit(f"{name} must be a number")

    input_path = args.workspace / args.input
    command = [args.fpocket, "-f", args.input, "-w", "p"]
    for name, flag in FLAGS.items():
        command += [flag, f"{resolved[name]:g}" if isinstance(resolved[name], float) else str(resolved[name])]

    completed = subprocess.run(command, cwd=args.workspace, check=False)
    (args.output_dir / "fpocket-run.json").write_text(
        json.dumps(
            {
                "task_type": "fpocket",
                "upstream_revision": "4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066",
                "upstream_release": "4.2.3",
                "runtime_network": False,
                "input_structure": {"name": args.input, "sha256": _sha256(input_path)},
                "parameters": resolved,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
