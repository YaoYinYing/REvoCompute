#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""BioEmu2 adapter for equilibrium sampling, structure prediction, and propagation.

The Task manifest selects the mode; the adapter never infers it from a filename.
Equilibrium and structure prediction share the sequence-to-system construction
upstream's Python API does not do for us:

* ``equilibrium`` and ``structure`` build the ``System`` from the Task's named
  ``sequence`` role, call upstream's matching sampling entry point, and write
  ``topology.pdb`` from the returned sample set because the declared trajectory
  view parses its topology as PDB;
* ``propagate`` runs upstream's own ``bioemu2 propagate`` command against the
  named ``starting_structure`` CIF, then writes the same PDB topology from the
  CIF upstream wrote.

Everything else -- MSA acquisition, embedding, denoising, physicality checking,
``samples.xtc``/``topology.cif``/``system.yaml``/``physicality.json`` -- is
upstream writing into the output directory. An optional parameter the manifest
did not resolve is not passed, so upstream's own preset applies rather than a
copy of its default kept here.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

#: The protein alphabet BioEmu2's ``Protein`` entity accepts. Stricter than the
#: server's ``validate_fasta`` alphabet, which also admits the ambiguity codes
#: B, Z, J, and O and the stop/gap spells -- none of which names a residue
#: BioEmu2 can sample. The Task input role declares this stricter set.
PROTEIN_CHARS = frozenset("ACDEFGHIKLMNPQRSTVWYX")

#: Propagation outputs upstream refuses to overwrite. Clearing exactly these
#: before the call keeps a re-run in the same directory deterministic without
#: deleting anything the Server published.
PROPAGATION_OUTPUTS = ("samples.xtc", "physicality.json")


def query_sequence(path: Path) -> str:
    """Return the single protein sequence of a Task FASTA ``sequence`` file.

    Raises ``ValueError`` for anything but exactly one headed, non-empty record:
    a second ``>`` (even with an empty header) would otherwise fuse two proteins
    into one chain and sample the wrong molecule without any error.
    """
    records = 0
    residues: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            records += 1
            if records > 1:
                raise ValueError("BioEmu2 takes exactly one protein sequence")
            if not line[1:].strip():
                raise ValueError(f"{path.name} has an empty FASTA header")
            continue
        residues.append("".join(line.split()).upper())
    if not records or not residues:
        raise ValueError(f"{path.name} holds no FASTA sequence")
    sequence = "".join(residues)
    invalid = sorted(set(sequence) - PROTEIN_CHARS)
    if invalid:
        raise ValueError(f"BioEmu2 cannot sample residues {', '.join(invalid)}")
    return sequence


def input_path(manifest: dict, role: str) -> Path:
    """The sole file of a named input role in the immutable task manifest."""
    files = manifest.get("inputs", {}).get(role)
    if not isinstance(files, list) or len(files) != 1:
        raise ValueError(f"input role {role!r} must hold exactly one file")
    return Path(files[0]["path"])


def sampling_kwargs(params: dict) -> dict:
    """The resolved task parameters that tune upstream sampling."""
    kwargs: dict = {"num_samples": int(params["num_samples"])}
    for key in ("sampler", "physicality_mode", "batch_size", "num_steps", "seed"):
        if params.get(key) is not None:
            kwargs[key] = params[key]
    return kwargs


def physicality_summary(path: Path) -> str:
    """One log line for the per-frame physicality outcome upstream wrote.

    A rejected ensemble is a result with a stated limitation, not a failure, so
    this only reports: the counts and rejection reasons must be readable without
    opening ``physicality.json``.
    """
    frames = json.loads(path.read_text(encoding="utf-8"))
    statuses = Counter(str(frame.get("status")) for frame in frames)
    reasons = Counter(str(frame.get("reason") or "unspecified") for frame in frames if frame.get("status") == "rejected")
    summary = f"BioEmu2 physicality: {statuses.get('passed', 0)}/{len(frames)} frames accepted"
    if reasons:
        summary += " (" + ", ".join(f"{reason}: {count}" for reason, count in sorted(reasons.items())) + ")"
    for status in ("rejected", "not_checked"):
        if statuses.get(status):
            summary += f", {statuses[status]} {status.replace('_', ' ')}"
    return summary


def sample(manifest: dict, output_dir: Path, checkpoint: Path, mode: str) -> None:
    """Run upstream's equilibrium sampler or folded-structure predictor."""
    import bioemu2

    sequence = query_sequence(input_path(manifest, "sequence"))
    system = bioemu2.System.from_description(proteins=[sequence])
    model = bioemu2.load_model(checkpoint_path=checkpoint)
    entry_point = bioemu2.sample_equilibrium if mode == "equilibrium" else bioemu2.predict_structure
    trajectory = entry_point(
        system, model=model, output_dir=output_dir, **sampling_kwargs(manifest["params"])
    )
    # The declared topology is parsed as PDB by the trajectory view; the
    # returned trajectory is the same sample set upstream just saved.
    trajectory[0].save_pdb(str(output_dir / "topology.pdb"))
    (output_dir / "sequence.fasta").write_text(f">input\n{sequence}\n", encoding="utf-8")


def propagate(manifest: dict, output_dir: Path, checkpoint: Path) -> None:
    """Run upstream's ``bioemu2 propagate`` command from one starting CIF.

    The upstream command infers the molecular system from ``--x0-cif`` and saves
    one independent endpoint per requested sample at a single lag. It refuses to
    overwrite its own coordinate and physicality files, so only those are
    cleared before the call; every other output is upstream's to replace.
    """
    starting_structure = input_path(manifest, "starting_structure")
    params = manifest["params"]
    for name in PROPAGATION_OUTPUTS:
        (output_dir / name).unlink(missing_ok=True)
    for stale in output_dir.glob("samples_*.xtc"):
        stale.unlink()

    command = [
        os.environ.get("BIOEMU2_CLI", "bioemu2"),
        "propagate",
        "--x0-cif",
        str(starting_structure),
        "--checkpoint-path",
        str(checkpoint),
        "--out",
        str(output_dir),
        "--num-samples",
        str(int(params["num_samples"])),
        "--lag-time-ns",
        f"{float(params['lag_time_ns']):g}",
    ]
    optional_flags = (
        ("--seed", "seed"),
        ("--num-steps", "num_steps"),
        ("--batch-size", "batch_size"),
        ("--sampler", "sampler"),
    )
    for flag, key in optional_flags:
        if params.get(key) is not None:
            command += [flag, str(params[key])]
    if params.get("physicality_mode") is not None:
        command += ["--physicality-filter", str(params["physicality_mode"])]
    subprocess.run(command, check=True)

    topology = output_dir / "topology.cif"
    if not topology.is_file():
        raise SystemExit(f"BioEmu2 propagation did not write {topology.name}")

    import mdtraj

    samples = mdtraj.load(str(topology))
    # Upstream's CIF writer stores ``_atom_site.id`` as text, so mdtraj loads
    # each serial as a string; its PDB writer formats serials as integers and
    # raises TypeError. Renumber before writing the declared PDB topology.
    for serial, atom in enumerate(samples.topology.atoms, start=1):
        atom.serial = serial
    pdb = output_dir / "topology.pdb"
    samples.save_pdb(str(pdb))
    written = mdtraj.load(str(pdb))
    if written.n_atoms != samples.n_atoms:
        pdb.unlink(missing_ok=True)
        raise SystemExit(
            f"topology.pdb represents {written.n_atoms} of {samples.n_atoms} atoms; "
            "the propagation trajectory has no usable PDB topology"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--checkpoint-dir", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("equilibrium", "structure", "propagate"))
    args = parser.parse_args()

    manifest = json.loads(args.task_manifest.read_text(encoding="utf-8"))
    checkpoint = args.checkpoint_dir / "checkpoint.ckpt"
    if not checkpoint.is_file():
        raise SystemExit(f"BioEmu2 checkpoint not found: {checkpoint}")

    # Keep the raw ColabFold response in task-local scratch: a cache in the
    # weight namespace would be mutable shared state. Every mode queries the
    # hosted MMseqs2 service for the system's alignment.
    scratch = Path(tempfile.mkdtemp(prefix="revodesign-bioemu2."))
    os.environ["BIOEMU2_MSA_CACHE"] = str(scratch / "colabfold_msa")
    try:
        if args.mode == "propagate":
            propagate(manifest, args.output_dir, checkpoint)
        else:
            sample(manifest, args.output_dir, checkpoint, args.mode)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    print(physicality_summary(args.output_dir / "physicality.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
