#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Invoke the pinned P2Rank predictor against read-only provisioned model assets.

Reads the immutable Task manifest (named input role + server-resolved
parameters), runs ``prank predict`` with an explicit external model directory
and only the four default score-transform files, then writes the run provenance
artifact that ``normalize_results.py`` folds into ``summary.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


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
        raise SystemExit("P2Rank requires exactly one structure input")
    params = document.get("params", {})
    if not isinstance(params, dict):
        raise SystemExit("Task params must be an object")
    unsupported = sorted(set(params) - {"threads"})
    if unsupported:
        raise SystemExit(f"Unsupported P2Rank parameters: {', '.join(unsupported)}")
    return params


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--structure", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=Path(os.environ.get("TASK_MANIFEST", "")))
    parser.add_argument("--prank", default=os.environ.get("P2RANK_EXECUTABLE", "prank"))
    args = parser.parse_args()

    params = _load_manifest(args.manifest)
    threads = params.get('threads', 1)
    if not isinstance(threads, int) or isinstance(threads, bool) or not 1 <= threads <= 64:
        raise SystemExit("threads must be an integer between 1 and 64")

    model_dir = args.asset_root / "default"
    transforms = {
        "zscoretp_transformer": args.asset_root / "_score_transform/default_ZscoreTpTransformer.json",
        "probatp_transformer": args.asset_root / "_score_transform/default_ProbabilityScoreTransformer.json",
        "zscoretp_res_transformer": args.asset_root / "_score_transform/residue/default_ZscoreTpTransformer.json",
        "probatp_res_transformer": args.asset_root / "_score_transform/residue/default_ProbabilityScoreTransformer.json",
    }
    for asset in (model_dir, *transforms.values()):
        if not asset.exists():
            raise SystemExit(f"P2Rank asset is missing: {asset}")

    command = [
        args.prank, "predict",
        "-f", str(args.structure),
        "-o", str(args.output_dir),
        "-threads", str(threads),
        "-m", str(model_dir),
        "-visualizations", "0",
        "-output_only_stats", "false",
    ]
    for flag, path in transforms.items():
        command += [f"-{flag}", str(path)]

    provenance = {
        "task_type": "p2rank",
        "upstream_revision": "9808a7723be9a94e2ffc21ab5f724cb6ae4ba01e",
        "upstream_release": "2.5.1",
        "runtime_network": False,
        "input_structure": {"name": args.name, "sha256": _sha256(args.structure)},
        "parameters": {"threads": threads},
        "assets": {
            "default/model.zst": _sha256(model_dir / "model.zst"),
            "default/features.txt": _sha256(model_dir / "features.txt"),
            **{name: _sha256(path) for name, path in transforms.items()},
        },
    }
    provenance_file = args.output_dir / "p2rank-run.json"
    provenance_file.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
