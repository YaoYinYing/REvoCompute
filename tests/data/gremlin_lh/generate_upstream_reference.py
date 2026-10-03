# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
"""Regenerate the frozen upstream scientific receipt for GREMLIN_LH.

The receipt at ``upstream_reference.json`` is the scientific acceptance baseline
for this Runner.  It must not be an unexplained JSON blob, so this script
reconstructs every value in it from the pinned upstream notebook itself.

What it does
------------

1. Loads the interactive Jupyter notebook given by ``--upstream``, rebuilds the
   notebook's own module state by executing the pinned cells, and records the
   notebook's git blob object hash, file SHA-256, and the SHA-256 of the input
   alignment.  No network access and no live GitHub lookup are performed.
2. Applies the two REvoCompute-documented corrections *to the notebook source
   text at execution time* and asserts that both substitutions actually fired,
   so a future notebook edit cannot silently leave the corrections unapplied.
3. Fits the model with the notebook's own ``GREMLIN`` entry point and derives
   every observable from the notebook's own functions (``jax_apc``/``get_mtx``,
   ``get_Hamiltonian_loss``), not from this Runner's code.  The receipt
   therefore describes upstream behaviour, so a Runner regression shows up as a
   receipt mismatch rather than being absorbed by a shared helper.
4. Emits a second ``pinned_uncorrected`` section produced with the unmodified
   notebook source, so the two intentional deviations stay visible rather than
   silently absorbed.

The two corrections (see ``SCIENTIFIC_TRACEABILITY.md`` for the full argument):

* ``jax_weights`` reads the *last* alphabet plane as the gap plane, which is a
  stale index from the pre-``gap``-first alphabet; the correction reads the
  actual gap plane (index 0).
* ``compute_loss_bias`` scales the field L2 penalty with integer floor division
  while every sibling term divides normally; the correction uses ordinary
  division.

This script does not run in CI.  It is intentionally runnable by a maintainer
with the pinned dependency stack installed:

    python tests/data/gremlin_lh/generate_upstream_reference.py \
        --upstream /path/to/GREMLIN_LH_outline_7.ipynb

Determinism: the notebook's mini-batch sampling is seeded explicitly
(``numpy.random.seed``) instead of relying on the notebook's unseeded global
NumPy RNG, so repeated runs under the pinned stack reproduce the receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

# Cell indices in the pinned blob 79cc0fdaba25ff1a6d6cb12ab2a2ebc8358c2c17.
CELL_UTILS = 7  # parse_fasta, parse_aln, alphabet, mk_msa
CELL_MTX = 8  # get_mtx, get_pair_pssm, get_pssm
CELL_GREMLIN = 11  # jax_cov, jax_weights, jax_apc, jax_inv_cov, reg_LH, compute_loss*, custom_adam
CELL_FIT = 13  # GREMLIN
CELL_HAMILTONIAN = 14  # get_Hamiltonian_loss

UPSTREAM_REPOSITORY = "https://github.com/sokrypton/GREMLIN_LH"
#: Intake-pinned commit.  The notebook blob hash below is what actually pins the
#: transcribed source; the commit is the recorded repository revision it came
#: from and cannot be recovered from the blob alone offline.
UPSTREAM_COMMIT = "6b8a6beb426fd31bb10c3fdd398abd3355b782f9"

#: Notebook source substitutions that express the two documented corrections.
GAP_PLANE_FROM = "jnp.mean(x_msa[:, :, -1], axis=0)"
GAP_PLANE_TO = "jnp.mean(x_msa[:, :, 0], axis=0)"
FLOOR_DIVISION_FROM = "params['b'])) * n_total * states // jnp.sqrt(neff)"
FLOOR_DIVISION_TO = "params['b'])) * n_total * states / jnp.sqrt(neff)"

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "tests/data/msa/2KL8.i90c75_aln.a3m"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "upstream_reference.json"

#: Scientific parameters of the reference case.  These are the upstream
#: notebook's own defaults with the batch size pinned to the full row count so
#: the fit is full-batch and therefore independent of sampling order.
PARAMETERS = {
    "regularization": "LH",
    "lambda_l2": 0.01,
    "lambda_lh": 0.1,
    "lambda_lb": 0.005,
    "iterations": 50,
    "batch_size": 6,
    "learning_rate": 1.0,
    "identity_cutoff": 0.8,
    "gap_cutoff": 0.5,
    "use_bias": True,
    "inverse_covariance_init": True,
    "exact_lh_eigenvalue": False,
    "seed": 0,
}

TOP_PAIRS = 10


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob_hash(path: Path) -> str | None:
    """Return the git blob object hash of a file, or None when git is absent.

    ``git hash-object`` hashes file content in git's own framing, so it is the
    canonical way to name this blob without a checkout.
    """
    try:
        completed = subprocess.run(
            ["git", "hash-object", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None


def _notebook_sources(path: Path) -> list[str]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    return ["".join(cell.get("source", [])) for cell in notebook["cells"]]


def _apply(source: str, old: str, new: str, label: str) -> str:
    patched = source.replace(old, new)
    if patched == source:
        raise SystemExit(
            f"correction {label!r} no longer matches the pinned notebook source; "
            "the notebook changed or the transcription drifted — re-audit before regenerating"
        )
    return patched


def _exec_cells(sources: list[str], indices: tuple[int, ...], *, corrected: bool) -> dict:
    """Rebuild the notebook's module state by executing its pinned cells."""
    import jax
    import jax.numpy as jnp
    import numpy as np
    import optax
    from jax import tree_util

    namespace = {
        "np": np,
        "jnp": jnp,
        "jax": jax,
        "optax": optax,
        "tree_util": tree_util,
        "__builtins__": __builtins__,
    }
    for index in indices:
        source = sources[index]
        if corrected and index == CELL_GREMLIN:
            source = _apply(source, GAP_PLANE_FROM, GAP_PLANE_TO, "explicit gap plane")
            source = _apply(source, FLOOR_DIVISION_FROM, FLOOR_DIVISION_TO, "ordinary-division field penalty")
        # ``import string`` lives in an earlier notebook cell that the model
        # path does not otherwise need; supply it so parse_fasta works.
        namespace.setdefault("string", __import__("string"))
        exec(compile(source, f"GREMLIN_LH_outline_7.ipynb:cell{index}", "exec"), namespace)
    return namespace


def _fit(namespace: dict, sequences: list[str]) -> tuple:
    """Run the notebook's GREMLIN on the alignment and return (V, W)."""
    import numpy as np

    encoded, _one_hot = namespace["mk_msa"](sequences)
    np.random.seed(PARAMETERS["seed"])
    fields, couplings = namespace["GREMLIN"](
        encoded,
        msa_weights=None,  # the notebook recomputes weights internally from the one-hot MSA
        lambda_L2=PARAMETERS["lambda_l2"],
        opt_iter=PARAMETERS["iterations"],
        batch_size=PARAMETERS["batch_size"],
        lr=PARAMETERS["learning_rate"],
        ignore_gap=False,
        use_bias=PARAMETERS["use_bias"],
        reg_mode=PARAMETERS["regularization"],
        lambda_LH=PARAMETERS["lambda_lh"],
        lambda_LB=PARAMETERS["lambda_lb"],
        Inv_init=PARAMETERS["inverse_covariance_init"],
        verbose=False,
        return_raw=True,
        power_iter=not PARAMETERS["exact_lh_eigenvalue"],
        monitering=False,
        param_flag=True,
    )
    return np.asarray(fields), np.asarray(couplings)


def _observables(namespace: dict, sequences: list[str], fields, couplings) -> dict:
    """Derive every receipt observable from the notebook's own functions."""
    import numpy as np

    _, one_hot = namespace["mk_msa"](sequences)
    one_hot = np.asarray(one_hot, dtype=np.float32)
    raw_jax, apc_jax = namespace["jax_apc"](couplings, return_raw=True)
    raw, apc = np.asarray(raw_jax), np.asarray(apc_jax)
    weights = np.asarray(namespace["jax_weights"](one_hot))
    states = couplings.shape[1]
    width = couplings.shape[0]
    if PARAMETERS["use_bias"]:
        hamiltonian = np.asarray(
            namespace["get_Hamiltonian_loss"](one_hot, couplings, fields, return_H=True)
        )
        pseudo_loss = np.asarray(namespace["get_Hamiltonian_loss"](one_hot, couplings, fields))
    else:
        hamiltonian = np.asarray(namespace["get_Hamiltonian_loss"](one_hot, couplings, return_H=True))
        pseudo_loss = np.asarray(namespace["get_Hamiltonian_loss"](one_hot, couplings))
    pairs = sorted(
        ((float(apc[i, j]), i, j, float(raw[i, j])) for i in range(width) for j in range(i + 1, width)),
        reverse=True,
    )[:TOP_PAIRS]
    block_positions = [(77, 78), (18, 32), (1, 76)]
    return {
        "sequence_weights": [float(value) for value in weights],
        "neff": float(np.sum(weights)),
        "fields": [[float(value) for value in row] for row in np.asarray(fields)],
        "raw_scores": [[float(value) for value in row] for row in raw],
        "apc_scores": [[float(value) for value in row] for row in apc],
        "couplings_blocks": [
            {"i": i, "j": j, "block": [[float(value) for value in row] for row in couplings[i, :, j, :]]}
            for i, j in block_positions
        ],
        "couplings_l2": float(np.sum(np.square(couplings))),
        "couplings_max_abs": float(np.max(np.abs(couplings))),
        "sequence_hamiltonian": [float(value) for value in hamiltonian],
        "sequence_pseudo_loss": [float(value) for value in pseudo_loss],
        "top_apc_pairs": [[int(i), int(j), raw_score, apc_score] for apc_score, i, j, raw_score in pairs],
        "positions": int(width),
        "states": int(states),
    }


def build_receipt(upstream: Path, input_path: Path) -> dict:
    import numpy as np

    sources = _notebook_sources(upstream)
    namespace = _exec_cells(
        sources, (CELL_UTILS, CELL_MTX, CELL_GREMLIN, CELL_FIT, CELL_HAMILTONIAN), corrected=True
    )
    headers, sequences = namespace["parse_fasta"](str(input_path), a3m=True)

    fields, couplings = _fit(namespace, sequences)
    expected = _observables(namespace, sequences, fields, couplings)

    pinned_namespace = _exec_cells(
        sources, (CELL_UTILS, CELL_MTX, CELL_GREMLIN, CELL_FIT, CELL_HAMILTONIAN), corrected=False
    )
    pinned_fields, pinned_couplings = _fit(pinned_namespace, sequences)
    pinned = _observables(pinned_namespace, sequences, pinned_fields, pinned_couplings)

    return {
        "schema_version": 2,
        "method": "GREMLIN_LH",
        "reference": (
            "Pinned upstream notebook with the two documented corrections applied "
            "(explicit gap plane for sequence weighting; ordinary-division field L2 "
            "penalty). Regenerate with generate_upstream_reference.py."
        ),
        "upstream": {
            "repository": UPSTREAM_REPOSITORY,
            "commit": UPSTREAM_COMMIT,
            "notebook": upstream.name,
            "notebook_blob": _git_blob_hash(upstream),
            "notebook_sha256": _sha256(upstream),
            "cells": {
                "utils": CELL_UTILS,
                "matrices": CELL_MTX,
                "optimizer_and_regularizers": CELL_GREMLIN,
                "fit_entrypoint": CELL_FIT,
                "hamiltonian": CELL_HAMILTONIAN,
            },
        },
        "generator": {
            "script": "tests/data/gremlin_lh/generate_upstream_reference.py",
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "jax": __import__("jax").__version__,
            "numpy": np.__version__,
            "optax": __import__("optax").__version__,
            "note": (
                "Observables are produced by the notebook's own functions, not by the Runner, "
                "so a Runner regression appears as a receipt mismatch."
            ),
            "seed_note": (
                "The notebook samples mini-batches with the unseeded global NumPy RNG; the "
                "generator seeds it explicitly. Full-batch settings make the reference "
                "independent of the row order."
            ),
        },
        "input": {
            "path": str(input_path.relative_to(ROOT)),
            "sha256": _sha256(input_path),
            "rows": len(sequences),
            "columns": len(sequences[0]),
            "headers": headers,
        },
        "parameters": PARAMETERS,
        "expected": expected,
        "pinned_uncorrected": {
            "note": "Pinned notebook behaviour before the two documented corrections, for reference only.",
            "neff": pinned["neff"],
            "sequence_weights": pinned["sequence_weights"],
            "top_apc_pairs": pinned["top_apc_pairs"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True, help="path to GREMLIN_LH_outline_7.ipynb")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="reference alignment")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="receipt to write")
    args = parser.parse_args()
    if not args.upstream.is_file():
        raise SystemExit(f"notebook not found: {args.upstream}")
    receipt = build_receipt(args.upstream, args.input)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
