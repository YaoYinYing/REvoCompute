#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Drive the pinned FRODOCK executables for one two-partner docking run.

The pipeline and every binary name mirror the upstream ``run_frodock.sh``:
potential-map generation with ``frodockgrid``, the exhaustive search with
``frodock``, clustering with ``frodockcluster``, and coordinate generation with
``frodockview``. ``soap.bin`` and the ``_gcc`` binaries are located inside the
read-only installation directory so the workspace stays free of install data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

UPSTREAM_REVISION = "8bc416f66e6c0c0427576218d7c3336853906ed5"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid task manifest: {exc}") from exc
    params = document.get("params", {})
    if not isinstance(params, dict):
        raise SystemExit("Task params must be an object")
    if params.get("interaction_type") not in (None, "O", "E", "A"):
        raise SystemExit("interaction_type must be one of O, E, A")
    unsupported = sorted(set(params) - {"pose_count", "clustering_rmsd", "interaction_type"})
    if unsupported:
        raise SystemExit(f"Unsupported FRODOCK parameters: {', '.join(unsupported)}")
    return params


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receptor", required=True, type=Path)
    parser.add_argument("--ligand", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ligand-name", required=True)
    parser.add_argument("--install-dir", type=Path, default=Path(os.environ.get("FRODOCK_INSTALL_DIR", "/opt/frodock")))
    parser.add_argument("--manifest", type=Path, default=Path(os.environ.get("TASK_MANIFEST", "")))
    args = parser.parse_args()

    params = _load_manifest(args.manifest)
    pose_count = params.get("pose_count", 10)
    if not isinstance(pose_count, int) or isinstance(pose_count, bool) or not 1 <= pose_count <= 50:
        raise SystemExit("pose_count must be an integer between 1 and 50")
    clustering_rmsd = params.get("clustering_rmsd", 5.0)
    if not isinstance(clustering_rmsd, (int, float)) or isinstance(clustering_rmsd, bool):
        raise SystemExit("clustering_rmsd must be a number")
    interaction_type = params.get("interaction_type") or "O"

    binaries = {
        name: args.install_dir / "bin" / f"{name}_gcc"
        for name in ("frodockgrid", "frodock", "frodockcluster", "frodockview")
    }
    soap = args.install_dir / "bin/soap.bin"
    missing = [str(path) for path in (*binaries.values(), soap) if not path.is_file()]
    if missing:
        raise SystemExit(f"FRODOCK installation is incomplete: {', '.join(missing)}")

    work = args.workspace
    work.mkdir(parents=True, exist_ok=True)
    receptor = work / "receptor.pdb"
    ligand = work / "ligand.pdb"
    shutil.copyfile(args.receptor, receptor)
    shutil.copyfile(args.ligand, ligand)

    def run(command: list[str], label: str, produced: Path) -> None:
        # The 3.12 frodockgrid exits 1 after a successful VdW/electrostatic map
        # because its main path ends in exit(1); the produced map is the
        # reliable success signal, and the docking stages do return 0.
        subprocess.run(command, cwd=work, check=False)
        if not produced.is_file() or produced.stat().st_size == 0:
            raise SystemExit(f"FRODOCK {label} step produced no output")

    run([str(binaries["frodockgrid"]), "receptor.pdb", "-o", "receptor_W.mrc"], "receptor vdW map", work / "receptor_W.mrc")
    run(
        [str(binaries["frodockgrid"]), "receptor.pdb", "-o", "receptor_E.mrc", "-m", "1", "-t", interaction_type],
        "receptor electrostatic map",
        work / "receptor_E.mrc",
    )
    run([str(binaries["frodockgrid"]), "receptor.pdb", "-o", "receptor_DS.mrc", "-m", "3"], "receptor desolvation map",
        work / "receptor_DS.mrc")
    run([str(binaries["frodockgrid"]), "ligand.pdb", "-o", "ligand_DS.mrc", "-m", "3"], "ligand desolvation map",
        work / "ligand_DS.mrc")
    run([
        str(binaries["frodock"]), "receptor_ASA.pdb", "ligand_ASA.pdb",
        "-w", "receptor_W.mrc", "-e", "receptor_E.mrc",
        "-d", "receptor_DS.mrc,ligand_DS.mrc",
        "-t", interaction_type,
        "-s", str(soap),
        "-o", "solutions.dat",
    ], "docking search", work / "solutions.dat")
    if not (work / "solutions.dat").is_file() or not (work / "solutions.dat").stat().st_size:
        raise SystemExit("FRODOCK docking search produced no solutions file")
    run([
        str(binaries["frodockcluster"]), "solutions.dat", "ligand.pdb",
        "--nc", str(pose_count), "-d", f"{float(clustering_rmsd):g}", "-o", "clustered_solutions.dat",
    ], "clustering", work / "clustered_solutions.dat")
    clustered = work / "clustered_solutions.dat"
    if not clustered.is_file() or not clustered.stat().st_size:
        raise SystemExit("FRODOCK clustering produced no solution file")
    shutil.copyfile(clustered, args.output_dir / "clustered_solutions.dat")
    run(
        [str(binaries["frodockview"]), "clustered_solutions.dat", "-r", f"1-{pose_count}", "-p", "ligand.pdb"],
        "pose generation",
        work / f"ligand_{pose_count}.pdb",
    )
    clustered_payload = clustered.read_bytes()
    stored = struct.unpack("<i", clustered_payload[:4])[0]
    if len(clustered_payload) != 16 + 28 * stored:
        raise SystemExit("FRODOCK clustered solution file does not match its declared solution count")
    records = [
        struct.unpack("<7f", clustered_payload[16 + 28 * index : 16 + 28 * (index + 1)])
        for index in range(stored)
    ]
    if stored < pose_count:
        raise SystemExit(f"FRODOCK clustered only {stored} solutions but {pose_count} poses were requested")
    poses = []
    for index in range(1, pose_count + 1):
        produced = work / f"ligand_{index}.pdb"
        if not produced.is_file() or produced.stat().st_size == 0:
            raise SystemExit(f"FRODOCK produced no coordinates for pose {index}")
        target = args.output_dir / f"{args.ligand_name}_{index}.pdb"
        shutil.copyfile(produced, target)
        record = records[index - 1]
        poses.append(
            {
                "posed_file": target.name,
                "rank": index,
                "correlation_score": round(record[6], 4),
                "euler_z_deg": round(float(record[0]), 4),
                "euler_y_deg": round(float(record[1]), 4),
                "euler_z2_deg": round(float(record[2]), 4),
                "translation_x_angstrom": round(float(record[3]), 4),
                "translation_y_angstrom": round(float(record[4]), 4),
                "translation_z_angstrom": round(float(record[5]), 4),
            }
        )
    (args.output_dir / "poses.json").write_text(
        json.dumps(
            {
                "raw_solution_count": stored,
                "ranking_metric": "correlation_score",
                "poses": poses,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    (args.output_dir / "frodock-run.json").write_text(
        json.dumps(
            {
                "task_type": "frodock",
                "upstream_revision": UPSTREAM_REVISION,
                "upstream_release": "3.12",
                "runtime_network": False,
                "partners": [
                    {"role": role, "name": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}
                    for role, path in (("receptor", args.receptor), ("ligand", args.ligand))
                ],
                "parameters": {
                    "pose_count": pose_count,
                    "clustering_rmsd": float(clustering_rmsd),
                    "interaction_type": interaction_type,
                },
                "executables": {name: str(path.name) for name, path in binaries.items()},
                "soap_potential": {"name": soap.name, "sha256": _sha256(soap)},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
