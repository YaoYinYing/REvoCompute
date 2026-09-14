# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

RANKED_POSE = re.compile(r"^rank(\d+)_confidence(-?(?:\d+(?:\.\d*)?|\.\d+))\.sdf$")
FIELDS = ("pose_rank", "confidence", "pose_file")


def normalize(output_dir: Path) -> None:
    rows = []
    for path in output_dir.rglob("rank*_confidence*.sdf"):
        match = RANKED_POSE.match(path.name)
        if match and path.stat().st_size:
            rows.append(
                {
                    "pose_rank": match.group(1),
                    "confidence": match.group(2),
                    "pose_file": path.relative_to(output_dir).as_posix(),
                }
            )
    rows.sort(key=lambda row: int(row["pose_rank"]))
    if not rows:
        raise ValueError("DiffDock produced no confidence-ranked pose files")
    if len({row["pose_rank"] for row in rows}) != len(rows):
        raise ValueError("DiffDock produced duplicate confidence ranks")
    with (output_dir / "scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "runner": "diffdock",
        "pose_count": len(rows),
        "ranking_metric": "confidence",
        "ranking_order": "descending",
        "scores_file": "scores.csv",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    normalize(args.output_dir)


if __name__ == "__main__":
    main()
