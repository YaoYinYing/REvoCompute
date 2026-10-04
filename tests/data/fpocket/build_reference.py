#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Rebuild the frozen fpocket scientific reference from a raw fpocket run tree.

The fpocket Runner publishes a pocket table derived from the raw output fpocket
writes beside its input.  ``upstream_reference.json`` is the frozen, checked-in
statement of what that raw output means, so a Runner regression shows up as a
mismatch instead of being absorbed by a shared helper.

This extractor is deliberately independent of the production parser
(``docker/runners/fpocket/normalize_results.py``): it imports nothing from it and
re-derives every published observable from the raw files with its own scanning
logic, so an error in the production parser cannot make the reference agree with
it.  It never executes fpocket or any file content: it only reads the pinned raw
tree and the pinned input structure.

Provenance recorded in the reference (a wrong identity fails closed):

* the pinned fpocket revision and its code license (``upstream``);
* the input structure's SHA-256 and PDB identity (``reference_case``);
* the SHA-256 of every raw output file and a digest over the whole tree
  (``raw_output``), so the reference is bound to one exact fpocket run;
* the extraction script name and version (``extraction``).

Observables are classified before any tolerance is written:

* ``exact``          -- discrete values the raw output states verbatim;
* ``tolerant``       -- quantities re-derived from coordinates, compared with a
  tolerance justified by float reduction order;
* ``ordering``       -- pocket ranking, compared as an ordering with a tie band.

Usage (maintainer only; not CI)::

    python tests/data/fpocket/build_reference.py \
        --run-dir tests/data/fpocket/1SUO_out \
        --input tests/data/pdb/1SUO.pdb \
        --output tests/data/fpocket/upstream_reference.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

EXTRACTION_VERSION = 1

#: Pinned fpocket identity.  The M_PAR_MC_ITER ('v') default is 300 and the
#: auxiliary binaries write the same "fpocket 4.0" banner, so the version string
#: is a fingerprint, not a release number; the git revision is the real pin.
UPSTREAM = {
    "project": "fpocket",
    "repository": "https://github.com/Discngine/fpocket",
    "revision": "4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066",
    "revision_label": "4.2.3",
    "code_license": "MIT",
    "method_publications": [
        "10.1186/1471-2105-10-168",
        "10.1021/jm100574m",
    ],
    "banner": "fpocket 4.0",
}

#: The reference case: the structure whose pocket output is frozen here.
REFERENCE_CASE = {
    "pdb_id": "1SUO",
    "title": "Structure of mammalian cytochrome P450 2B4 with bound 4-(4-chlorophenyl)imidazole",
    "method": "X-ray diffraction",
    "resolution_angstrom": 1.9,
    "release_date": "2004-07-20",
    "polymer": "cytochrome P450 2B4 (sequenced chain A)",
    "non_polymer_entities": ["HEM", "CPZ"],
    "pdb_doi": "10.1074/jbc.M403349200",
    "chain": "A",
    "hetero_contact_rule": (
        "A pocket's contacted-atom file may list non-polymer (HETATM) residues. The "
        "reference records which hetero residue names each pocket contacts in "
        "expected.pockets[].hetero_residues and which pockets contact any of them in "
        "expected.hetero_contacting_pockets. This is a factual statement about the "
        "contacted atoms, NOT a ligand or active-site claim: on 1SUO the leading "
        "pocket contacts the HEM cofactor only, while the co-crystallized inhibitor "
        "CPZ is present in the input but contacted by no reported pocket."
    ),
}

#: fpocket parameter vocabulary this Runner exposes, with the upstream flag and
#: the value used for the frozen run.  The Runner passes each parameter as this
#: exact CLI option (verified against src/fparams.h option macros).
PARAMETERS = {
    "min_alpha_sphere_radius": {"flag": "-m", "value": 3.4},
    "max_alpha_sphere_radius": {"flag": "-M", "value": 6.2},
    "min_alpha_spheres_per_pocket": {"flag": "-i", "value": 15},
    "clustering_distance": {"flag": "-D", "value": 2.4},
    "volume_monte_carlo_iterations": {"flag": "-v", "value": 300},
    "write_mode": {"flag": "-w", "value": "p"},
}

#: Integer/float descriptors copied verbatim from the info file, with the
#: published column each one maps to.  Compared exactly because the Runner
#: republishes upstream's own printed value without recomputation.
DESCRIPTORS = {
    "score": "Score",
    "druggability_score": "Druggability Score",
    "alpha_spheres": "Number of Alpha Spheres",
    "total_sasa_angstrom2": "Total SASA",
    "polar_sasa_angstrom2": "Polar SASA",
    "apolar_sasa_angstrom2": "Apolar SASA",
    "volume_angstrom3": "Volume",
    "mean_alpha_sphere_radius_angstrom": "Mean alpha sphere radius",
    "hydrophobicity_score": "Hydrophobicity score",
    "volume_score": "Volume score",
    "polarity_score": "Polarity score",
    "charge_score": "Charge score",
    "apolar_alpha_sphere_proportion": "Apolar alpha sphere proportion",
}

#: Descriptors whose value is the Monte-Carlo volume estimate.  fpocket seeds its
#: RNG from ``time(NULL)`` (``src/utils.c``), so this field varies run to run on
#: the same input and is NOT a cross-run golden value.  The measured spread on
#: the reference case is ~8% of the leading pocket's volume; the field is
#: deterministic within one run, so the frozen reference still records it for the
#: run it was built from.
RUN_LOCAL_DESCRIPTORS = ("volume_angstrom3",)

_POCKET_HEADER = re.compile(r"^Pocket (\d+) :\s*$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_info(path: Path) -> list[dict[str, str]]:
    """Return one descriptor mapping per ``Pocket N :`` block, in file order."""
    pockets: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        header = _POCKET_HEADER.match(raw_line)
        if header:
            current = {"pocket_index": header.group(1)}
            pockets.append(current)
            continue
        if current is None or not raw_line.startswith("\t"):
            continue
        key, _, value = raw_line.strip().partition(":")
        key, value = key.strip(), value.strip()
        if key:
            current[key] = value
    return pockets


def _parse_coordinates(path: Path) -> list[tuple[float, float, float]]:
    """Return the (x, y, z) of every ATOM/HETATM line, using PDB columns 31-54.

    PQR/PDB coordinate fields are fixed width; whitespace splitting would merge
    a negative coordinate into the preceding field, so the columns are read
    directly.
    """
    coordinates: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line[:6].strip() in {"ATOM", "HETATM"}:
            try:
                coordinates.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
            except ValueError:
                continue
    return coordinates


def _contacted_residues(path: Path) -> list[str]:
    """Return the sorted ``chain_resSeq[iCode]`` set of the atoms in a pocket.

    Columns 22 (chain), 23-27 (resSeq + iCode) are the residue identity; an
    insertion code distinguishes ``42A`` from ``42``.
    """
    residues = {
        f"{line[21].strip()}_{line[22:27].strip()}"
        for line in path.read_text(encoding="utf-8").splitlines()
        if line[:6].strip() in {"ATOM", "HETATM"}
    }
    return sorted(residues)


def _contacted_atom_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line[:6].strip() in {"ATOM", "HETATM"})


def _contacted_hetero_residues(path: Path) -> list[str]:
    """Return the HETATM residue names (e.g. ``HEM``) a pocket's atoms include.

    This is a factual statement about the contacted atoms, not a ligand or
    active-site claim: a non-polymer residue contacted by a pocket may be a
    cofactor (HEM) rather than a small-molecule ligand, and a bound ligand in the
    input is not necessarily contacted by any reported pocket.
    """
    names = {
        line[17:20].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line[:6].strip() == "HETATM"
    }
    return sorted(names)


def extract(run_dir: Path, input_path: Path) -> dict:
    info_files = list(run_dir.glob("*_info.txt"))
    if len(info_files) != 1:
        raise SystemExit(f"expected exactly one *_info.txt in {run_dir}, found {len(info_files)}")
    info_file = info_files[0]
    stem = info_file.name[: -len("_info.txt")]
    pocket_dir = info_file.parent / "pockets"

    blocks = _parse_info(info_file)
    rows: list[dict[str, object]] = []
    for index, block in enumerate(blocks, start=1):
        vert = pocket_dir / f"pocket{index}_vert.pqr"
        atm = pocket_dir / f"pocket{index}_atm.pdb"
        coordinates = _parse_coordinates(vert)
        rows.append(
            {
                "pocket": f"pocket{index}",
                "rank": index,
                "pocket_index": block["pocket_index"],
                "descriptors": {published: block[upstream] for published, upstream in DESCRIPTORS.items()},
                "center_x": sum(c[0] for c in coordinates) / len(coordinates),
                "center_y": sum(c[1] for c in coordinates) / len(coordinates),
                "center_z": sum(c[2] for c in coordinates) / len(coordinates),
                "alpha_sphere_vertices": len(coordinates),
                "residue_ids": _contacted_residues(atm),
                "residue_count": len(_contacted_residues(atm)),
                "atom_count": _contacted_atom_count(atm),
                "hetero_residues": _contacted_hetero_residues(atm),
            }
        )

    raw_files = {
        str(path.relative_to(run_dir)): _sha256(path)
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    }
    tree_digest = hashlib.sha256(
        "\n".join(f"{name} {digest}" for name, digest in sorted(raw_files.items())).encode("utf-8")
    ).hexdigest()

    def _relative(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(ROOT))
        except ValueError:
            return str(path)

    hetero_pockets = [row["pocket"] for row in rows if row["hetero_residues"]]

    return {
        "extraction": {
            "script": "tests/data/fpocket/build_reference.py",
            "version": EXTRACTION_VERSION,
            "note": (
                "Independent of docker/runners/fpocket/normalize_results.py: every "
                "observable is re-derived from the raw fpocket tree with this script's "
                "own parsing, so a production-parser error cannot make the reference agree."
            ),
        },
        "upstream": UPSTREAM,
        "reference_case": {
            **REFERENCE_CASE,
            "input_path": _relative(input_path),
            "input_sha256": _sha256(input_path),
        },
        "parameters": PARAMETERS,
        "raw_output": {
            "run_dir": _relative(run_dir),
            "files": raw_files,
            "tree_digest": tree_digest,
            "info_file": str(info_file.relative_to(run_dir)),
            "stem": stem,
        },
        "observable_classes": {
            "pocket_count": "exact",
            "pocket_ids": "exact",
            "ranking_metric": "ordering",
            "descriptor_values": "exact",
            "run_local_descriptor_values": "not-golden (Monte-Carlo volume)",
            "center_angstrom": "tolerant",
            "residue_ids": "exact",
            "residue_count": "exact",
            "atom_count": "exact",
            "alpha_sphere_vertices": "exact",
            "hetero_contacting_pockets": "exact",
        },
        "run_local_descriptors": list(RUN_LOCAL_DESCRIPTORS),
        "expected": {
            "pocket_count": len(rows),
            "pocket_ids": [row["pocket"] for row in rows],
            "ranking": [row["pocket"] for row in sorted(rows, key=lambda r: float(r["descriptors"]["score"]), reverse=True)],
            "hetero_contacting_pockets": hetero_pockets,
            "pockets": rows,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True, help="fpocket <stem>_out directory")
    parser.add_argument("--input", type=Path, required=True, help="input structure for the run")
    parser.add_argument("--output", type=Path, required=True, help="reference JSON to write")
    args = parser.parse_args()
    if not args.run_dir.is_dir():
        raise SystemExit(f"run directory not found: {args.run_dir}")
    if not args.input.is_file():
        raise SystemExit(f"input structure not found: {args.input}")
    reference = extract(args.run_dir, args.input)
    args.output.write_text(json.dumps(reference, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.output}: {reference['expected']['pocket_count']} pockets")


if __name__ == "__main__":
    main()
