# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

SCORE_LINE = re.compile(
    r"^\s*(?P<rank>\d+)\s+(?P<affinity>-?\d+(?:\.\d+)?)\s+"
    r"(?P<rmsd_lb>-?\d+(?:\.\d+)?)\s+(?P<rmsd_ub>-?\d+(?:\.\d+)?)\s*$"
)
FIELDS = ("ligand", "pose_rank", "affinity_kcal_mol", "rmsd_lb_angstrom", "rmsd_ub_angstrom", "pose_file")


def normalize(output_dir: Path, ligands: list[str]) -> None:
    rows: list[dict[str, str]] = []
    for index, ligand in enumerate(ligands, start=1):
        log_path = output_dir / f"vina_{index}.log"
        pose_path = output_dir / f"vina_{index}.pdbqt"
        if not log_path.is_file() or not pose_path.is_file():
            raise ValueError(f"missing native Vina results for ligand {index}")
        ligand_rows = []
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = SCORE_LINE.match(line)
            if match:
                ligand_rows.append(
                    {
                        "ligand": Path(ligand).name,
                        "pose_rank": match["rank"],
                        "affinity_kcal_mol": match["affinity"],
                        "rmsd_lb_angstrom": match["rmsd_lb"],
                        "rmsd_ub_angstrom": match["rmsd_ub"],
                        "pose_file": f"{pose_path.name}#MODEL={match['rank']}",
                    }
                )
        if not ligand_rows:
            raise ValueError(f"Vina log contains no pose scores: {log_path.name}")
        rows.extend(ligand_rows)
    _write_outputs(output_dir, rows, len(ligands))


def _write_outputs(output_dir: Path, rows: list[dict[str, str]], ligand_count: int) -> None:
    with (output_dir / "scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "runner": "autodock_vina",
        "ligand_count": ligand_count,
        "pose_count": len(rows),
        "ranking_metric": "affinity_kcal_mol",
        "ranking_order": "ascending",
        "scores_file": "scores.csv",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("ligands", nargs="+")
    args = parser.parse_args()
    normalize(args.output_dir, args.ligands)


if __name__ == "__main__":
    main()
