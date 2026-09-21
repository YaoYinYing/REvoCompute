#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Run the open-source MolProbity validation set and normalize its tables.

Each analysis is invoked through its own ``molprobity.*`` console script with
``--json --quiet``; the scripts write a ``*_result.json`` next to the working
directory. Per-residue tables are flattened from ``flat_results`` and the
run-level values come from ``summary_results``. The MolProbity score is then
composed from clashscore, rotamer-outlier percentage, and Ramachandran-favoured
percentage using ``mmtbx.validation.utils.molprobity_score``, the same function
the upstream combined report uses.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ANALYSES = ("ramalyze", "rotalyze", "cbetadev", "omegalyze", "clashscore2")
RESIDUE_FIELDS = (
    "analysis",
    "chain_id",
    "resseq",
    "icode",
    "resname",
    "altloc",
    "evaluation",
    "score",
    "phi",
    "psi",
    "rotamer_name",
    "chi_angles",
    "deviation",
    "dihedral_nabb",
    "outlier",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_analysis(name: str, input_path: Path, work_dir: Path) -> dict[str, object]:
    executable = shutil.which(f"molprobity.{name}")
    if executable is None:
        raise SystemExit(f"MolProbity analysis is missing from the runtime: molprobity.{name}")
    completed = subprocess.run(
        [executable, str(input_path), "--json", "--quiet", "--overwrite"],
        cwd=work_dir,
        check=False,
    )
    report = work_dir / f"{name}_result.json"
    if completed.returncode != 0 or not report.is_file():
        raise SystemExit(f"MolProbity {name} failed for {input_path.name}")
    return json.loads(report.read_text(encoding="utf-8"))


def _summary(payload: dict[str, object], name: str) -> dict[str, object]:
    summaries = payload.get("summary_results")
    if not isinstance(summaries, dict) or not summaries:
        raise SystemExit(f"MolProbity {name} produced no summary for this structure")
    return next(iter(summaries.values()))


def _flat_rows(payload: dict[str, object], name: str) -> list[dict[str, object]]:
    rows = []
    for item in payload.get("flat_results") or []:
        rows.append(
            {
                "analysis": name,
                "chain_id": item.get("chain_id") or "",
                "resseq": item.get("resseq") or "",
                "icode": (item.get("icode") or "").strip(),
                "resname": item.get("resname") or "",
                "altloc": (item.get("altloc") or "").strip(),
                "evaluation": item.get("evaluation") or item.get("rama_type") or "",
                "score": item.get("score"),
                "phi": item.get("phi"),
                "psi": item.get("psi"),
                "rotamer_name": item.get("rotamer_name") or "",
                "chi_angles": json.dumps(item.get("chi_angles")) if item.get("chi_angles") else "",
                "deviation": item.get("deviation"),
                "dihedral_nabb": item.get("dihedral_NABB"),
                "outlier": item.get("outlier"),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--asset-manifest", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = args.output_dir / "work"
    work_dir.mkdir(exist_ok=True)

    results = {name: _run_analysis(name, args.input, work_dir) for name in ANALYSES}
    summaries = {name: _summary(payload, name) for name, payload in results.items()}

    rows: list[dict[str, object]] = []
    for name in ANALYSES:
        rows.extend(_flat_rows(results[name], name))
    with (args.output_dir / "validation_residues.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESIDUE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    for name, keys in (
        ("clashscore2", ("clashscore", "num_clashes")),
        ("rotalyze", ("favored_percentage", "outlier_percentage", "num_favored", "num_outliers", "num_residues")),
        ("ramalyze", ("favored_percentage", "outlier_percentage", "num_favored", "num_allowed", "num_outliers", "num_residues")),
        ("cbetadev", ("outlier_percentage", "num_outliers", "num_cbeta_residues")),
        ("omegalyze", ("num_cis_proline", "num_twisted_proline", "num_proline", "num_cis_general", "num_general")),
    ):
        absent = [key for key in keys if key not in summaries[name]]
        if absent:
            raise SystemExit(f"MolProbity {name} summary is missing: {', '.join(absent)}")

    from mmtbx.validation.utils import molprobity_score

    clash = summaries["clashscore2"]
    rota = summaries["rotalyze"]
    rama = summaries["ramalyze"]
    cbeta = summaries["cbetadev"]
    omega = summaries["omegalyze"]
    score = molprobity_score(clash["clashscore"], rota["outlier_percentage"], rama["favored_percentage"])
    if score < 0:
        raise SystemExit("MolProbity score could not be composed from the reported analyses")

    (args.output_dir / "molprobity.json").write_text(
        json.dumps(
            {
                "runner": "molprobity",
                "molprobity_score": round(score, 4),
                "clashscore": clash["clashscore"],
                "clash_count": clash.get("num_clashes"),
                "ramachandran_favored_percent": rama["favored_percentage"],
                "ramachandran_outlier_percent": rama["outlier_percentage"],
                "ramachandran_favored": rama["num_favored"],
                "ramachandran_allowed": rama["num_allowed"],
                "ramachandran_outliers": rama["num_outliers"],
                "ramachandran_residues": rama["num_residues"],
                "rotamer_favored_percent": rota["favored_percentage"],
                "rotamer_outlier_percent": rota["outlier_percentage"],
                "rotamer_favored": rota["num_favored"],
                "rotamer_outliers": rota["num_outliers"],
                "rotamer_residues": rota["num_residues"],
                "cbeta_outlier_percent": cbeta["outlier_percentage"],
                "cbeta_outliers": cbeta["num_outliers"],
                "cbeta_residues": cbeta["num_cbeta_residues"],
                "cis_proline": omega["num_cis_proline"],
                "twisted_proline": omega["num_twisted_proline"],
                "proline": omega["num_proline"],
                "cis_general": omega["num_cis_general"],
                "general_omega": omega["num_general"],
                "molprobity_score_semantics": "lower is better; upstream scores 0-1 as better than a 1.0 A reference structure",
                "ran": list(ANALYSES),
                "provenance": {
                    "task_type": "molprobity",
                    "upstream_revision": args.source_revision,
                    "runtime_network": False,
                    "input_structure": {"name": args.input.name, "sha256": _sha256(args.input)},
                    "reference_data": {
                        "rotarama_data": {
                            name: _sha256(args.asset_root / "chem_data" / "rotarama_data" / name)
                            for name in ("ala.rama.combined.data", "rota8000-arg.data")
                        },
                        "geostd_list_cif": _sha256(args.asset_root / "chem_data" / "geostd/list/mon_lib_list.cif"),
                    },
                    "asset_manifest_sha256": _sha256(args.asset_manifest),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
