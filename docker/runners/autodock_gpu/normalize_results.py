# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
RUN = re.compile(r"^DOCKED:\s+USER\s+Run\s*=\s*(\d+)\s*$", re.MULTILINE)
ENERGIES = {
    "binding_energy_kcal_mol": re.compile(rf"Estimated Free Energy of Binding\s*=\s*({NUMBER})\s+kcal/mol"),
    "intermolecular_energy_kcal_mol": re.compile(rf"Final Intermolecular Energy\s*=\s*({NUMBER})\s+kcal/mol"),
    "internal_energy_kcal_mol": re.compile(rf"Final Total Internal Energy\s*=\s*({NUMBER})\s+kcal/mol"),
}
RANKING_LINE = re.compile(rf"^\s*(\d+)\s+\d+\s+(\d+)\s+{NUMBER}(?:\s|$)", re.MULTILINE)
FIELDS = (
    "ligand",
    "run",
    "cluster_rank",
    "binding_energy_kcal_mol",
    "intermolecular_energy_kcal_mol",
    "internal_energy_kcal_mol",
    "result_reference",
)


def normalize(output_dir: Path, ligands: list[str]) -> None:
    rows: list[dict[str, str]] = []
    for index, ligand in enumerate(ligands, start=1):
        dlg_path = output_dir / f"autodock_gpu_{index}.dlg"
        if not dlg_path.is_file():
            raise ValueError(f"missing AutoDock-GPU DLG for ligand {index}")
        text = dlg_path.read_text(encoding="utf-8", errors="replace")
        ranks = {run: rank for rank, run in RANKING_LINE.findall(text)}
        matches = list(RUN.finditer(text))
        if not matches:
            raise ValueError(f"AutoDock-GPU DLG contains no docked runs: {dlg_path.name}")
        for position, match in enumerate(matches):
            run = match.group(1)
            block_end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
            block = text[match.end() : block_end]
            values = {}
            for field, pattern in ENERGIES.items():
                value = pattern.search(block)
                values[field] = value.group(1) if value else ""
            if not values["binding_energy_kcal_mol"]:
                raise ValueError(f"AutoDock-GPU run {run} has no binding energy in {dlg_path.name}")
            rows.append(
                {
                    "ligand": Path(ligand).name,
                    "run": run,
                    "cluster_rank": ranks.get(run, ""),
                    **values,
                    "result_reference": f"{dlg_path.name}#run={run}",
                }
            )
    with (output_dir / "scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "runner": "autodock_gpu",
        "ligand_count": len(ligands),
        "pose_count": len(rows),
        "ranking_metric": "binding_energy_kcal_mol",
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
