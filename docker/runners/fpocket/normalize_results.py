#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Normalize an fpocket run directory into the declared pocket result tables.

fpocket writes ``<stem>_out/<stem>_info.txt`` (one descriptor block per pocket),
``<stem>_out/pockets/pocket<N>_atm.pdb`` (the protein atoms contacted by the
pocket's alpha spheres) and ``pocket<N>_vert.pqr`` (the alpha-sphere centres).
Descriptors are read by their upstream key strings; the pocket centre is the
mean of the pocket's own alpha-sphere centres, which is the barycenter fpocket
computes internally.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

POCKET_HEADER = re.compile(r"^Pocket (\d+) :\s*$")
DESCRIPTOR = re.compile(r"^\t(?P<key>[^:]+):\s*(?P<value>\S+)\s*$")

POCKET_FIELDS = (
    "pocket",
    "rank",
    "score",
    "druggability_score",
    "alpha_spheres",
    "mean_alpha_sphere_radius_angstrom",
    "total_sasa_angstrom2",
    "apolar_sasa_angstrom2",
    "polar_sasa_angstrom2",
    "volume_angstrom3",
    "hydrophobicity_score",
    "volume_score",
    "polarity_score",
    "charge_score",
    "apolar_alpha_sphere_proportion",
    "center_x",
    "center_y",
    "center_z",
    "residue_count",
    "residue_ids",
    "atom_count",
)


def _info_blocks(path: Path) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        header = POCKET_HEADER.match(line)
        if header:
            current = {"pocket_index": header.group(1)}
            blocks.append(current)
            continue
        descriptor = DESCRIPTOR.match(line)
        if descriptor and current is not None:
            current[descriptor["key"].strip()] = descriptor["value"]
    return blocks


def _vertices(path: Path) -> list[tuple[float, float, float]]:
    coordinates: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("ATOM", "HETATM")):
            coordinates.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    return coordinates


def _residue_id(line: str) -> str:
    """Return the residue identity of one ATOM/HETATM line.

    Columns 23-26 are ``resSeq`` and column 27 is ``iCode``; a residue with an
    insertion code (``42A``) is a different residue from ``42``, so both
    columns belong in the identity.
    """
    chain = line[21].strip()
    return f"{chain}_{line[22:27].strip()}"


def _residue_sort_key(item: str) -> tuple[str, int, str, str]:
    """Order residue identities by chain, then sequence number, then iCode.

    ``resSeq`` is normally digits, but PDB hybrid-36 uses letters once a
    structure exceeds 9999 residues; such a field is ordered at 0 and then by
    its literal text, and the literal text is always the final tiebreaker so
    the order cannot depend on set iteration order.
    """
    chain, _, residue = item.partition("_")
    number = residue[: -1] if residue and not residue[-1].isdigit() else residue
    insertion = residue[len(number) :]
    return chain, int(number) if number.isdigit() else 0, insertion, residue


def _residues(path: Path) -> list[str]:
    residues: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("ATOM", "HETATM")):
            residues.add(_residue_id(line))
    return sorted(residues, key=_residue_sort_key)


def _atom_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.startswith(("ATOM", "HETATM")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--provenance", type=Path, required=True)
    args = parser.parse_args()
    output_dir: Path = args.output_dir

    info_files = sorted(output_dir.glob("work/*_out/*_info.txt")) + sorted(output_dir.glob("*_out/*_info.txt"))
    if len(info_files) != 1:
        raise ValueError(f"expected exactly one fpocket info file, found {len(info_files)}")
    info_file = info_files[0]
    stem = info_file.name[: -len("_info.txt")]
    pocket_dir = info_file.parent / "pockets"
    if not pocket_dir.is_dir():
        raise ValueError(f"fpocket produced no pocket directory: {pocket_dir.name}")

    blocks = _info_blocks(info_file)
    if not blocks:
        raise ValueError("fpocket reported no pockets for this structure")

    rows: list[dict[str, object]] = []
    for index, block in enumerate(blocks, start=1):
        declared = block.get("pocket_index")
        if declared != str(index):
            raise ValueError(f"fpocket pocket numbering is not contiguous at pocket {declared}")
        vertices = pocket_dir / f"pocket{index}_vert.pqr"
        atoms = pocket_dir / f"pocket{index}_atm.pdb"
        if not vertices.is_file() or not atoms.is_file():
            raise ValueError(f"fpocket pocket {index} is missing its vertex or atom file")
        coordinates = _vertices(vertices)
        if not coordinates:
            raise ValueError(f"fpocket pocket {index} declares no alpha-sphere centres")
        residues = _residues(atoms)
        required = (
            "Score",
            "Druggability Score",
            "Number of Alpha Spheres",
            "Total SASA",
            "Polar SASA",
            "Apolar SASA",
            "Volume",
            "Mean alpha sphere radius",
            "Hydrophobicity score",
            "Volume score",
            "Polarity score",
            "Charge score",
            "Apolar alpha sphere proportion",
        )
        missing = [key for key in required if key not in block]
        if missing:
            raise ValueError(f"fpocket pocket {index} is missing descriptors: {', '.join(missing)}")
        rows.append(
            {
                "pocket": f"pocket{index}",
                "rank": index,
                "score": block["Score"],
                "druggability_score": block["Druggability Score"],
                "alpha_spheres": block["Number of Alpha Spheres"],
                "mean_alpha_sphere_radius_angstrom": block["Mean alpha sphere radius"],
                "total_sasa_angstrom2": block["Total SASA"],
                "apolar_sasa_angstrom2": block["Apolar SASA"],
                "polar_sasa_angstrom2": block["Polar SASA"],
                "volume_angstrom3": block["Volume"],
                "hydrophobicity_score": block["Hydrophobicity score"],
                "volume_score": block["Volume score"],
                "polarity_score": block["Polarity score"],
                "charge_score": block["Charge score"],
                "apolar_alpha_sphere_proportion": block["Apolar alpha sphere proportion"],
                "center_x": f"{sum(c[0] for c in coordinates) / len(coordinates):.4f}",
                "center_y": f"{sum(c[1] for c in coordinates) / len(coordinates):.4f}",
                "center_z": f"{sum(c[2] for c in coordinates) / len(coordinates):.4f}",
                "residue_count": len(residues),
                "residue_ids": " ".join(residues),
                "atom_count": _atom_count(atoms),
            }
        )

    with (output_dir / "pockets.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POCKET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    scores = [float(str(row["score"])) for row in rows]
    if scores != sorted(scores, reverse=True):
        raise ValueError("fpocket pocket order does not match its descending score order")

    provenance = json.loads(args.provenance.read_text(encoding="utf-8"))
    provenance["pocket_count"] = len(rows)
    provenance["largest_pocket_alpha_spheres"] = max(int(str(row["alpha_spheres"])) for row in rows)
    (output_dir / "summary.json").write_text(
        json.dumps(
            {
                "runner": "fpocket",
                "pocket_count": len(rows),
                "ranking_metric": "score",
                "ranking_order": "descending",
                "score_semantics": "fpocket pocket score (likeliness that the pocket is a small-molecule binding site)",
                "druggability_semantics": "fpocket druggability score in [0, 1]; 0.5 is the upstream decision threshold",
                "center_semantics": "mean of the pocket's alpha-sphere centres, the barycenter fpocket reports internally",
                "units": {
                    "center_x": "angstrom",
                    "center_y": "angstrom",
                    "center_z": "angstrom",
                    "total_sasa_angstrom2": "angstrom^2",
                    "polar_sasa_angstrom2": "angstrom^2",
                    "apolar_sasa_angstrom2": "angstrom^2",
                    "volume_angstrom3": "angstrom^3",
                },
                "pockets_file": "pockets.csv",
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
