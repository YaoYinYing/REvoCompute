#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Prepare and execute one CAVER 3.0.2 tunnel analysis Task.

The server-resolved ``task.json`` is the only input: named roles carry immutable
paths and digests, and ``params`` carries defaults already applied by the owning
``task.yaml``. This module resolves the typed start point against the deposited
coordinates, stages a deterministic snapshot series, renders the allowlisted
CAVER configuration, runs the pinned JAR with a bounded heap and timeout, then
normalizes the authentic output files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import normalize_results
from caver_config import ALLOWED_PARAMETERS, ConfigError, build_command, render_config
from pdb_selection import (
    SelectionError,
    assert_snapshot_matches,
    parse_pdb,
    resolve_start_point,
    validate_exclusions,
)

#: CAVER writes the initial start point it actually used to data/origins.pdb.
#: The resolved point must match it; the slack absorbs the file's 3 decimals.
ORIGIN_TOLERANCE_ANGSTROM = 0.05

MAX_SNAPSHOTS = 50


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepared_input(item: object, root: Path) -> Path:
    """Resolve one manifest input and refuse anything outside the prepared input root.

    The Server writes ``task.json`` inside the immutable role snapshot and its
    ``path`` values are mounted siblings under that same root, so the manifest's
    own directory is the only tree this Runner may read. A traversal, an
    absolute path elsewhere or a symlink pointing out of the root is refused
    instead of being parsed.
    """
    raw = item.get("path") if isinstance(item, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        raise SystemExit("CAVER input entry has no path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise SystemExit(f"CAVER input is missing: {candidate.name}") from None
    if not resolved.is_relative_to(root):
        raise SystemExit(f"CAVER input {candidate.name} escapes the prepared input root")
    if not resolved.is_file():
        raise SystemExit(f"CAVER input is missing: {candidate.name}")
    return resolved


def load_manifest(path: Path) -> tuple[dict[str, object], list[Path], list[Path]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid task manifest: {exc}") from exc
    if document.get("task_type") != "caver":
        raise SystemExit(f"Unsupported task type: {document.get('task_type')!r}")
    params = document.get("params")
    inputs = document.get("inputs")
    if not isinstance(params, dict) or not isinstance(inputs, dict):
        raise SystemExit("Task manifest must carry params and inputs objects")
    unknown = sorted(set(params) - ALLOWED_PARAMETERS)
    if unknown:
        raise SystemExit(f"Unsupported CAVER parameters: {', '.join(unknown)}")
    structure = inputs.get("structure")
    snapshots = inputs.get("snapshots", [])
    if not isinstance(structure, list) or len(structure) != 1:
        raise SystemExit("CAVER requires exactly one structure input")
    if not isinstance(snapshots, list) or len(snapshots) > MAX_SNAPSHOTS:
        raise SystemExit(f"CAVER accepts at most {MAX_SNAPSHOTS} additional snapshots")
    root = path.resolve().parent
    structure_paths = [prepared_input(item, root) for item in structure]
    snapshot_paths = [prepared_input(item, root) for item in snapshots]
    return params, structure_paths, snapshot_paths


def stage_frames(reference: Path, snapshots: list[Path], pdb_dir: Path) -> list[dict[str, object]]:
    """Write the reference and snapshots as a deterministic, ordered frame series."""
    pdb_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, object]] = []
    reference_atoms = parse_pdb(reference)
    for index, source in enumerate([reference, *snapshots], start=1):
        atoms = reference_atoms if index == 1 else parse_pdb(source)
        if index > 1:
            assert_snapshot_matches(reference_atoms, atoms, source.name)
        # CAVER labels results with the file stem, so frame_1.pdb yields the
        # same "frame_1.pdb" snapshot label that provenance records.
        target = pdb_dir / f"frame_{index}.pdb"
        shutil.copyfile(source, target)
        frames.append(
            {
                "index": index,
                "frame": target.name,
                "source_name": source.name,
                "sha256": sha256_file(target),
                "atom_count": len(atoms),
            }
        )
    return frames


def _distribution(root: Path) -> dict[str, object]:
    """Describe the pinned binaries that are about to execute."""
    jar = root / "caver.jar"
    library_dir = root / "lib"
    if not jar.is_file() or not library_dir.is_dir():
        raise SystemExit(f"CAVER distribution is incomplete under {root}")
    libraries = {path.name: sha256_file(path) for path in sorted(library_dir.glob("*.jar"))}
    if not libraries:
        raise SystemExit("CAVER distribution carries no libraries")
    return {
        "jar_sha256": sha256_file(jar),
        "library_sha256": libraries,
        "atom_radii_sha256": sha256_file(root / "bin" / "atom_radii.csv"),
    }


def required_environment(name: str) -> str:
    """Read one value the runner entrypoint exports; never guess a default."""
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} must be set by the runner entrypoint")
    return value


def read_origin(path: Path) -> tuple[float, float, float]:
    """Read the initial start point CAVER used from its origins.pdb."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise SystemExit("CAVER origins.pdb is not valid UTF-8 text") from exc
    for line in lines:
        if line.startswith(("ATOM", "HETATM")):
            try:
                return float(line[30:38]), float(line[38:46]), float(line[46:54])
            except ValueError as exc:
                raise SystemExit(f"CAVER origin record is malformed: {exc}") from exc
    raise SystemExit("CAVER origins.pdb carries no origin record")


def run(argv: list[str], timeout: int, cwd: Path, log_dir: Path, env: dict[str, str]) -> None:
    with (log_dir / "caver.stdout.log").open("w", encoding="utf-8") as stdout, (
        log_dir / "caver.stderr.log"
    ).open("w", encoding="utf-8") as stderr:
        try:
            completed = subprocess.run(argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr, check=False, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise SystemExit(f"CAVER exceeded its {timeout}s timeout") from exc
        except OSError as exc:
            raise SystemExit(f"Cannot start the CAVER Java runtime {argv[0]!r}: {exc}") from exc
    if completed.returncode != 0:
        raise SystemExit(f"CAVER exited with status {completed.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--distribution", type=Path, default=Path(os.environ.get("CAVER_HOME", "/opt/caver302/caver")))
    parser.add_argument("--java", default=os.environ.get("CAVER_JAVA", "java"))
    parser.add_argument("--upstream", type=Path, default=Path(__file__).resolve().parent / "upstream.json")
    args = parser.parse_args()

    params, structures, snapshots = load_manifest(args.task)
    output_dir = args.output_dir.resolve()
    work = output_dir / "work"
    pdb_dir = work / "pdbs"
    raw_out = work / "caver_out"
    for directory in (work, raw_out, work / "tmp"):
        directory.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    reference_atoms = parse_pdb(structures[0])
    validate_exclusions(params, reference_atoms)
    start_point = resolve_start_point(reference_atoms, params)
    frames = stage_frames(structures[0], snapshots, pdb_dir)
    if params.get("start_point_mode") == "atom":
        serial = start_point.provenance["atom_serial"]
        selected_identity = (
            start_point.provenance["chain"],
            start_point.provenance["residue_number"],
            start_point.provenance["atom_name"],
            start_point.provenance["altloc"],
        )
        for frame in frames[1:]:
            matches = [atom for atom in parse_pdb(pdb_dir / str(frame["frame"])) if atom.serial == serial]
            if len(matches) != 1 or (
                matches[0].chain,
                matches[0].resseq,
                matches[0].name,
                matches[0].altloc,
            ) != selected_identity:
                raise SystemExit(
                    f"frame {frame['frame']} does not carry atom serial {serial} at the selected identity"
                )

    config_text = render_config(params, start_point)
    config_path = work / "config.txt"
    config_path.write_text(config_text, encoding="utf-8")

    upstream: dict[str, object] = {}
    if args.upstream.is_file():
        upstream = json.loads(args.upstream.read_text(encoding="utf-8"))
    distribution = _distribution(args.distribution)
    # run.sh is the single place these defaults live: the SIF supplies the heap
    # bound and the entrypoint sets an internal timeout below the declared
    # maximum runtime so a stuck JVM is killed before the scheduler kills the job.
    heap = required_environment("CAVER_JAVA_XMX")
    try:
        timeout = int(required_environment("CAVER_TIMEOUT_SECONDS"))
    except ValueError as exc:
        raise SystemExit("CAVER_TIMEOUT_SECONDS must be an integer") from exc
    argv = build_command(
        java=args.java,
        heap=heap,
        library_dir=str(args.distribution / "lib"),
        jar=str(args.distribution / "caver.jar"),
        home=str(args.distribution),
        pdb_dir=str(pdb_dir),
        config=str(config_path),
        output_dir=str(raw_out),
        tmp_dir=str(work / "tmp"),
    )
    env = {key: value for key, value in os.environ.items() if key not in {"_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS"}}
    env.update({"HOME": str(work), "TMPDIR": str(work / "tmp"), "PYTHONNOUSERSITE": "1"})

    provenance = {
        "task_type": "caver",
        "upstream": upstream,
        "distribution": distribution,
        "runtime_network": False,
        "java_heap": heap,
        "start_point": start_point.provenance,
        "parameters": params,
        "structure": {
            "name": structures[0].name,
            "sha256": sha256_file(structures[0]),
            "atom_count": len(reference_atoms),
        },
        "frames": frames,
        "config_directives": config_text.splitlines(),
        "command": argv[1:],
    }
    provenance_path = output_dir / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("REVODESIGN_STAGE:compute_tunnels")
    run(argv, timeout, work, output_dir, env)

    # CAVER's own origin is the authoritative initial point; publish it and
    # refuse to attach provenance to a point CAVER did not use. A missing file
    # is a failure: without it the selection cannot be verified at all.
    origin_path = raw_out / "data" / "origins.pdb"
    if not origin_path.is_file():
        raise SystemExit("CAVER did not produce data/origins.pdb; the resolved start point cannot be verified")
    origin = read_origin(origin_path)
    first_frame = int(params["first_frame"])
    # CAVER writes one origin per analyzed frame, starting with the first one it
    # analyzed, and resolves atom/residue selections per frame.
    analyzed_start = (
        start_point
        if first_frame == 1
        else resolve_start_point(parse_pdb(pdb_dir / f"frame_{first_frame}.pdb"), params)
    )
    delta = math.dist(origin, (analyzed_start.x, analyzed_start.y, analyzed_start.z))
    provenance["caver_origin_angstrom"] = list(origin)
    provenance["origin_delta_angstrom"] = round(delta, 4)
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if delta > ORIGIN_TOLERANCE_ANGSTROM:
        raise SystemExit(
            f"CAVER started from {origin} but the resolved start point for frame {first_frame} is "
            f"({analyzed_start.x:.3f}, {analyzed_start.y:.3f}, {analyzed_start.z:.3f}); "
            f"the difference of {delta:.3f} A means the selection does not describe CAVER's origin"
        )

    print("REVODESIGN_STAGE:normalize_results")
    shutil.copyfile(config_path, output_dir / "caver_config.txt")
    try:
        normalize_results.normalize(raw_out, output_dir, json.loads(provenance_path.read_text(encoding="utf-8")))
    except normalize_results.OutputError as exc:
        raise SystemExit(f"CAVER output validation failed: {exc}") from exc


if __name__ == "__main__":
    try:
        main()
    except (ConfigError, SelectionError) as exc:
        sys.stderr.write(f"CAVER task rejected: {exc}\n")
        raise SystemExit(2) from exc
