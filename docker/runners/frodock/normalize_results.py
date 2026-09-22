#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Normalize FRODOCK's clustered solution file into the declared pose table.

``frodockcluster`` rewrites the raw binary solution file as
``int32 count, float32[3] origin, count * float32[7] records``, where each
record is ``eulerZ eulerY eulerZ2 posX posY posZ correlation`` in degrees,
angstroms, and FRODOCK energy units — the exact layout
``SCollection::write_solutions`` emits and ``frodockview`` reads back. The file
is already sorted by descending correlation, so the record index is the rank.
"""

from __future__ import annotations

import argparse
import csv
import json
import struct
from pathlib import Path

POSE_FIELDS = (
    "pose_file",
    "rank",
    "correlation_score",
    "euler_z_deg",
    "euler_y_deg",
    "euler_z2_deg",
    "translation_x_angstrom",
    "translation_y_angstrom",
    "translation_z_angstrom",
)


def _records(path: Path) -> list[tuple[float, ...]]:
    payload = path.read_bytes()
    if len(payload) < 16:
        raise ValueError(f"FRODOCK clustered solution file is truncated: {path.name}")
    count = struct.unpack("<i", payload[:4])[0]
    if count < 1:
        raise ValueError("FRODOCK clustered solution file stores no solutions")
    if len(payload) != 16 + 28 * count:
        raise ValueError(f"FRODOCK solution file length does not match its declared {count} solutions")
    return [struct.unpack("<7f", payload[16 + 28 * index : 16 + 28 * (index + 1)]) for index in range(count)]


def _pose_generation(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"FRODOCK pose record is unreadable: {exc}") from exc
    poses = payload.get("poses")
    if not isinstance(poses, list) or not poses:
        raise ValueError("FRODOCK pose record contains no poses")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--provenance", type=Path, required=True)
    args = parser.parse_args()
    output_dir: Path = args.output_dir

    solution_file = output_dir / "clustered_solutions.dat"
    if not solution_file.is_file():
        raise ValueError("FRODOCK clustering produced no solution file")
    records = _records(solution_file)
    generation = _pose_generation(output_dir / "poses.json")
    poses = generation["poses"]
    if int(generation.get("raw_solution_count", 0)) != len(records):
        raise ValueError("FRODOCK pose record disagrees with the clustered solution file")

    rows = []
    for pose in poses:
        pose_file = output_dir / str(pose["posed_file"])
        if not pose_file.is_file() or pose_file.stat().st_size == 0:
            raise ValueError(f"FRODOCK pose {pose_file.name} is missing or empty")
        rows.append(
            {
                "pose_file": pose_file.name,
                "rank": pose["rank"],
                "correlation_score": pose["correlation_score"],
                "euler_z_deg": pose["euler_z_deg"],
                "euler_y_deg": pose["euler_y_deg"],
                "euler_z2_deg": pose["euler_z2_deg"],
                "translation_x_angstrom": pose["translation_x_angstrom"],
                "translation_y_angstrom": pose["translation_y_angstrom"],
                "translation_z_angstrom": pose["translation_z_angstrom"],
            }
        )

    scores = [float(row["correlation_score"]) for row in rows]
    if scores != sorted(scores, reverse=True):
        raise ValueError("FRODOCK pose order does not match its descending correlation order")

    with (output_dir / "poses.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POSE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    provenance = json.loads(args.provenance.read_text(encoding="utf-8"))
    provenance["pose_count"] = len(rows)
    provenance["raw_solution_count"] = len(records)
    (output_dir / "summary.json").write_text(
        json.dumps(
            {
                "runner": "frodock",
                "pose_count": len(rows),
                "raw_solution_count": len(records),
                "ranking_metric": "correlation_score",
                "ranking_order": "descending",
                "score_semantics": "FRODOCK correlation is the absolute energy score of the solution; higher is better, and rank 1 is the best-scoring cluster representative",
                "translation_semantics": "translation of the ligand centre of mass in angstroms relative to the ligand PDB centre",
                "rotation_semantics": "ZYZ Euler angles in degrees",
                "poses_file": "poses.csv",
                "provenance": provenance,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
