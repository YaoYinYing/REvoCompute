# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

PROPERTY = re.compile(r">\s*<([^>]+)>\s*\r?\n([^\r\n]*)")
FIELDS = ("pose_rank", "minimizedAffinity", "CNNscore", "CNNaffinity", "pose_file")


def normalize(output_dir: Path) -> None:
    sdf_path = output_dir / "gnina.sdf"
    if not sdf_path.is_file():
        raise ValueError("missing native Gnina SDF")
    records = [
        record
        for record in sdf_path.read_text(encoding="utf-8", errors="replace").split("$$$$")
        if record.strip()
    ]
    rows = []
    for rank, record in enumerate(records, start=1):
        properties = dict(PROPERTY.findall(record))
        if "minimizedAffinity" not in properties:
            raise ValueError(f"Gnina pose {rank} has no minimizedAffinity property")
        rows.append(
            {
                "pose_rank": str(rank),
                "minimizedAffinity": properties["minimizedAffinity"].strip(),
                "CNNscore": properties.get("CNNscore", "").strip(),
                "CNNaffinity": properties.get("CNNaffinity", "").strip(),
                "pose_file": f"gnina.sdf#record={rank}",
            }
        )
    if not rows:
        raise ValueError("Gnina SDF contains no poses")
    with (output_dir / "scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "runner": "gnina",
        "pose_count": len(rows),
        "ranking_metrics": ["minimizedAffinity", "CNNscore", "CNNaffinity"],
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
