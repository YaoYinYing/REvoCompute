#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Normalize a DeepPocket run directory into the declared pocket result tables.

The adapter leaves three upstream products behind:

``pocket_confidence.txt``
    One classifier confidence per candidate, already in descending order, with
    one line per candidate pocket that fpocket proposed.
``<stem>_<N>.dx``
    The U-Net segmentation mask for the Nth top-ranked pocket, in the crate
    format ``molgrid.write_dx`` emits.
``<stem>_pocket<N>.pdb``
    The protein residues the Nth mask contacts, written by upstream's own
    ``output_pocket_pdb`` as a ProDy selection of the input structure and
    omitted entirely when a mask contacts no residue.

This module joins the ranking with the candidate centres to build the pocket
table and reads the segmented pocket PDBs to build the residue table.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

POCKET_FIELDS = (
    "rank",
    "pocket",
    "confidence",
    "center_x",
    "center_y",
    "center_z",
    "segmented",
    "residue_count",
)
RESIDUE_FIELDS = ("pocket", "rank", "chain", "resseq", "icode", "resname")
POCKET_PDB = re.compile(r"_pocket(?P<index>\d+)\.pdb$")


def _barycenters(path: Path) -> list[tuple[int, float, float, float]]:
    centers: list[tuple[int, float, float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) != 4:
            raise ValueError(f"Unexpected fpocket barycenter line: {line!r}")
        centers.append((int(fields[0]), float(fields[1]), float(fields[2]), float(fields[3])))
    return centers


def _ranked_candidates(types_path: Path, centers: list[tuple[int, float, float, float]]) -> list[dict[str, object]]:
    by_number = {number: (x, y, z) for number, x, y, z in centers}
    ranked: list[dict[str, object]] = []
    for line in types_path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 4:
            raise ValueError(f"Unexpected DeepPocket ranked candidate line: {line!r}")
        number = int(fields[0])
        if number not in by_number:
            raise ValueError(f"Ranked candidate {number} has no fpocket barycenter")
        x, y, z = by_number[number]
        ranked.append({"pocket": number, "center_x": x, "center_y": y, "center_z": z})
    return ranked


def _segmented_residues(pocket_pdb: Path) -> list[tuple[str, int, str, str]]:
    residues: set[tuple[str, int, str, str]] = set()
    for line in pocket_pdb.read_text(encoding="utf-8").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        residues.add((line[21:22].strip(), int(line[22:26]), line[26:27].strip(), line[17:20].strip()))
    return sorted(residues)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--provenance", type=Path, required=True)
    args = parser.parse_args()
    output_dir: Path = args.output_dir

    confidence_path = output_dir / "pocket_confidence.txt"
    if not confidence_path.is_file():
        raise ValueError("DeepPocket produced no classifier confidence file")
    confidences = [float(line) for line in confidence_path.read_text(encoding="utf-8").split() if line.strip()]
    if not confidences:
        raise ValueError("DeepPocket classifier ranked no candidate pocket")

    barycenter_files = sorted(output_dir.glob("work/*_nowat_out/pockets/bary_centers.txt"))
    if len(barycenter_files) != 1:
        raise ValueError(f"expected exactly one fpocket barycenter file, found {len(barycenter_files)}")
    centers = _barycenters(barycenter_files[0])

    ranked_files = sorted(output_dir.glob("work/*_nowat_out/pockets/bary_centers_ranked.types"))
    if len(ranked_files) != 1:
        raise ValueError(f"expected exactly one ranked candidate file, found {len(ranked_files)}")
    ranked = _ranked_candidates(ranked_files[0], centers)
    if len(ranked) != len(confidences):
        raise ValueError(
            f"classifier produced {len(confidences)} scores for {len(ranked)} ranked candidates"
        )

    # Upstream omits a pocket PDB whose mask contacts no residue, so zero
    # pocket PDBs is a legitimate outcome rather than a missing artifact. The
    # ``*_*.dx`` masks the segmentation wrote prove the step actually ran.
    pocket_pdbs = sorted(output_dir.glob("*_pocket*.pdb"))
    segmented: dict[int, Path] = {}
    for path in pocket_pdbs:
        match = POCKET_PDB.search(path.name)
        if match is None:
            continue
        segmented[int(match.group("index"))] = path

    residue_rows: list[dict[str, object]] = []
    pocket_rows: list[dict[str, object]] = []
    for rank, (candidate, confidence) in enumerate(zip(ranked, confidences), start=1):
        pocket_number = int(candidate["pocket"])
        residues = _segmented_residues(segmented[rank]) if rank in segmented else []
        for chain, resseq, icode, resname in residues:
            residue_rows.append(
                {
                    "pocket": pocket_number,
                    "rank": rank,
                    "chain": chain,
                    "resseq": resseq,
                    "icode": icode,
                    "resname": resname,
                }
            )
        pocket_rows.append(
            {
                **candidate,
                "rank": rank,
                "confidence": confidence,
                "segmented": rank in segmented,
                "residue_count": len(residues),
            }
        )

    with (output_dir / "pockets.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POCKET_FIELDS)
        writer.writeheader()
        writer.writerows(pocket_rows)

    # Upstream omits a pocket PDB whose mask contacts no residue, so an empty
    # residue table is a legitimate outcome rather than a missing artifact.
    with (output_dir / "residues.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESIDUE_FIELDS)
        writer.writeheader()
        writer.writerows(residue_rows)

    provenance = json.loads(args.provenance.read_text(encoding="utf-8"))
    provenance.update({"candidate_count": len(pocket_rows), "segmented_pocket_count": len(segmented)})
    (output_dir / "summary.json").write_text(
        json.dumps(
            {
                "runner": "deeppocket",
                "candidate_count": len(pocket_rows),
                "segmented_pocket_count": len(segmented),
                "segmented_residue_count": len(residue_rows),
                "ranking_metric": "confidence",
                "ranking_order": "descending",
                "score_semantics": "DeepPocket classifier probability that the fpocket candidate pocket is a true binding site",
                "segmentation_semantics": "U-Net mask over the pocket region, reduced to the protein residues within the resolved mask distance",
                "units": {"center_x": "angstrom", "center_y": "angstrom", "center_z": "angstrom"},
                "pockets_file": "pockets.csv",
                "residues_file": "residues.csv",
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
