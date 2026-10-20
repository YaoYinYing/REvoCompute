#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""BioEmu2 equilibrium-ensemble adapter.

The adapter does three things upstream's Python API does not do for us:

* it builds the ``System`` from the Task's named ``sequence`` role instead of a
  PDB ID or a hand-written system YAML;
* it writes ``topology.pdb`` from the returned sample set, because the
  declared trajectory view parses its topology as PDB;
* it echoes the input sequence as ``sequence.fasta``.

Everything else -- MSA acquisition, embedding, denoising, physicality checking,
``samples.xtc``/``system.yaml``/``physicality.json`` -- is upstream
``sample_equilibrium`` writing into the output directory. An optional parameter
the manifest did not resolve is not passed, so upstream's own preset applies
rather than a copy of its default kept here.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

#: The protein alphabet BioEmu2's ``Protein`` entity accepts.
PROTEIN_CHARS = frozenset("ACDEFGHIKLMNPQRSTVWYX")


def query_sequence(path: Path) -> str:
    """Return the single protein sequence of a Task FASTA ``sequence`` file."""
    header = ""
    residues: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header:
                raise ValueError("BioEmu2 takes exactly one protein sequence")
            header = line[1:].strip()
            continue
        residues.append("".join(line.split()).upper())
    if not header or not residues:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--checkpoint-dir", required=True, type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.task_manifest.read_text(encoding="utf-8"))
    sequence = query_sequence(input_path(manifest, "sequence"))
    checkpoint = args.checkpoint_dir / "checkpoint.ckpt"
    if not checkpoint.is_file():
        raise SystemExit(f"BioEmu2 checkpoint not found: {checkpoint}")

    # Keep the raw ColabFold response in task-local scratch: a cache in the
    # weight namespace would be mutable shared state.
    scratch = Path(tempfile.mkdtemp(prefix="revodesign-bioemu2."))
    os.environ["BIOEMU2_MSA_CACHE"] = str(scratch / "colabfold_msa")
    try:
        import bioemu2

        system = bioemu2.System.from_description(proteins=[sequence])
        model = bioemu2.load_model(checkpoint_path=checkpoint)
        trajectory = bioemu2.sample_equilibrium(
            system, model=model, output_dir=args.output_dir, **sampling_kwargs(manifest["params"])
        )
        # The declared topology is parsed as PDB by the trajectory view; the
        # returned trajectory is the same sample set upstream just saved.
        trajectory[0].save_pdb(str(args.output_dir / "topology.pdb"))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    (args.output_dir / "sequence.fasta").write_text(f">input\n{sequence}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
