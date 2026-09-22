#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Normalize P2Rank pocket prediction output into declared result artifacts.

P2Rank emits two space-padded, comma-separated tables per protein:
``<label>_predictions.csv`` (one row per ranked pocket, with space-separated
``residue_ids``/``surf_atom_ids`` columns) and ``<label>_residues.csv`` (one row
per labelled residue). Both formats are fixed by ``PredictionSummary`` and
``ResidueLabelings`` in the pinned revision.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

POCKET_FIELDS = (
    "pocket",
    "rank",
    "score",
    "probability",
    "sas_points",
    "surf_atoms",
    "center_x",
    "center_y",
    "center_z",
    "residue_count",
    "surface_atom_count",
)
RESIDUE_FIELDS = ("chain", "residue_label", "residue_name", "score", "zscore", "probability", "pocket")


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            {key.strip(): (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle, skipinitialspace=True)
        ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--provenance", type=Path, required=True)
    args = parser.parse_args()
    output_dir: Path = args.output_dir

    prediction_files = sorted(output_dir.glob("*_predictions.csv"))
    if len(prediction_files) != 1:
        raise ValueError(f"expected exactly one P2Rank predictions CSV, found {len(prediction_files)}")
    residue_files = sorted(output_dir.glob("*_residues.csv"))
    if len(residue_files) != 1:
        raise ValueError(f"expected exactly one P2Rank residues CSV, found {len(residue_files)}")

    pockets = _rows(prediction_files[0])
    if not pockets:
        raise ValueError("P2Rank predictions CSV contains no pockets")
    for column in ("name", "rank", "score", "probability", "sas_points", "surf_atoms",
                   "center_x", "center_y", "center_z", "residue_ids", "surf_atom_ids"):
        if column not in pockets[0]:
            raise ValueError(f"P2Rank predictions CSV is missing column {column}")

    pocket_rows = [
        {
            "pocket": row["name"],
            "rank": int(row["rank"]),
            "score": float(row["score"]),
            "probability": float(row["probability"]),
            "sas_points": int(row["sas_points"]),
            "surf_atoms": int(row["surf_atoms"]),
            "center_x": float(row["center_x"]),
            "center_y": float(row["center_y"]),
            "center_z": float(row["center_z"]),
            "residue_count": len(row["residue_ids"].split()),
            "surface_atom_count": len(row["surf_atom_ids"].split()),
        }
        for row in pockets
    ]
    with (output_dir / "pockets.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POCKET_FIELDS)
        writer.writeheader()
        writer.writerows(pocket_rows)

    residues = _rows(residue_files[0])
    if not residues:
        raise ValueError("P2Rank residues CSV contains no residue labels")
    missing = sorted(set(RESIDUE_FIELDS) - set(residues[0]))
    if missing:
        raise ValueError(f"P2Rank residues CSV is missing columns: {', '.join(missing)}")
    with (output_dir / "residue_scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESIDUE_FIELDS)
        writer.writeheader()
        writer.writerows({field: row[field] for field in RESIDUE_FIELDS} for row in residues)

    provenance = json.loads(args.provenance.read_text(encoding="utf-8"))
    provenance.update({"pocket_count": len(pocket_rows), "residue_count": len(residues)})
    (output_dir / "summary.json").write_text(
        json.dumps(
            {
                "runner": "p2rank",
                "pocket_count": len(pocket_rows),
                "residue_count": len(residues),
                "ranking_metric": "score",
                "ranking_order": "descending",
                "score_semantics": "P2Rank pocket score; the predicted pockets are emitted in descending score order",
                "probability_semantics": "P2Rank probability that the pocket is a true pocket (0-1)",
                "units": {"center_x": "angstrom", "center_y": "angstrom", "center_z": "angstrom"},
                "pockets_file": "pockets.csv",
                "residue_scores_file": "residue_scores.csv",
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
