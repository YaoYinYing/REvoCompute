# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
"""Regenerate the frozen upstream scientific receipt for GREMLIN_LH.

The receipt at ``upstream_reference.json`` is the scientific acceptance baseline
for this Runner.  It must not be an unexplained JSON blob, so this script
reconstructs every value in it from the pinned upstream notebook itself.

What it does
------------

1. **Fails closed on identity before any executable step.**  Given ``--upstream``,
   it first checks the notebook's git blob hash (``git hash-object``) against the
   pinned blob, and -- because ``git hash-object`` can fall back to the SHA-1
   hash object format when git is absent -- the file SHA-256 against the pinned
   digest.  Unless both agree, the script refuses with a non-zero exit before
   reading a single cell.
2. Rebuilds the notebook's module state from ``upstream_notebook_reference.py``,
   a checked-in literal transcription of the pinned cells 7, 8, 11, 13, and 14.
   No cell content from ``--upstream`` is ever executed.  The transcription is
   validated against the pinned notebook by
   ``assert_matches_pinned_notebook``, so a drift in either the notebook pin or
   the transcription stops generation.
3. Applies the two REvoCompute-documented corrections *as explicit parameters
   with the pinned behaviour as the default*, so a single transcription produces
   all three recorded variants without textual substitution of source.
   ``expected`` applies both; ``pinned_uncorrected`` applies neither; ``d1_only``
   applies D1 only.
4. Fits the model through the notebook's own ``GREMLIN`` entry point and derives
   every observable from the notebook's own functions (``jax_apc``,
   ``get_Hamiltonian_loss``), not from this Runner's code.  The receipt therefore
   describes upstream behaviour, so a Runner regression shows up as a receipt
   mismatch rather than being absorbed by a shared helper.

The two corrections (see ``SCIENTIFIC_TRACEABILITY.md`` for the full argument):

* ``jax_weights`` reads the *last* alphabet plane as the gap plane, which is a
  stale index from the pre-``gap``-first alphabet; the correction reads the
  actual gap plane (index 0).  Parameter: ``gap_plane_index``.
* ``compute_loss_bias`` scales the field L2 penalty with integer floor division
  while every sibling term divides normally; the correction uses ordinary
  division.  Parameter: ``field_penalty_floor``.

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

sys.path.insert(0, str(Path(__file__).resolve().parent))

import upstream_notebook_reference as reference  # noqa: E402

UPSTREAM_REPOSITORY = "https://github.com/sokrypton/GREMLIN_LH"
#: Intake-pinned commit.  The notebook blob hash below is what actually pins the
#: transcribed source; the commit is the recorded repository revision it came
#: from and cannot be recovered from the blob alone offline.
UPSTREAM_COMMIT = "6b8a6beb426fd31bb10c3fdd398abd3355b782f9"

#: Pinned notebook identity, re-exported for callers that check the receipt.
PINNED_BLOB = reference.PINNED_NOTEBOOK_BLOB
PINNED_SHA256 = reference.PINNED_NOTEBOOK_SHA256

CELLS = {
    "utils": reference.CELL_UTILS,
    "matrices": reference.CELL_MTX,
    "optimizer_and_regularizers": reference.CELL_GREMLIN,
    "fit_entrypoint": reference.CELL_FIT,
    "hamiltonian": reference.CELL_HAMILTONIAN,
}

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


def assert_pinned_identity(upstream: Path) -> None:
    """Refuse unless the notebook is the pinned one.

    Both the git blob hash and the file SHA-256 must match.  This runs before any
    cell is loaded, so a wrong or edited ``--upstream`` can never reach a
    computation.
    """
    sha256 = _sha256(upstream)
    blob = _git_blob_hash(upstream)
    if blob != PINNED_BLOB or sha256 != PINNED_SHA256:
        raise SystemExit(
            f"refusing {upstream}: it is not the pinned GREMLIN_LH notebook.\n"
            f"  expected blob   {PINNED_BLOB}\n"
            f"  observed blob   {blob}\n"
            f"  expected sha256 {PINNED_SHA256}\n"
            f"  observed sha256 {sha256}\n"
            "Pass the pinned GREMLIN_LH_outline_7.ipynb (see upstream_reference.json)."
        )


def _notebook_sources(path: Path) -> list[str]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    return ["".join(cell.get("source", [])) for cell in notebook["cells"]]


def _fit(sequences: list[str], gap_plane_index: int, field_penalty_floor: bool) -> tuple:
    """Run the transcribed notebook ``GREMLIN`` and return (V, W)."""
    import numpy as np

    encoded, _one_hot = reference.mk_msa(sequences)
    np.random.seed(PARAMETERS["seed"])
    fields, couplings = reference.GREMLIN(
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
        gap_plane_index=gap_plane_index,
        field_penalty_floor=field_penalty_floor,
    )
    return np.asarray(fields), np.asarray(couplings)


def _observables(sequences: list[str], fields, couplings, gap_plane_index: int) -> dict:
    """Derive every receipt observable from the notebook's own functions."""
    import numpy as np

    _, one_hot = reference.mk_msa(sequences)
    one_hot = np.asarray(one_hot, dtype=np.float32)
    raw_jax, apc_jax = reference.jax_apc(couplings, return_raw=True)
    raw, apc = np.asarray(raw_jax), np.asarray(apc_jax)
    weights = np.asarray(reference.jax_weights(one_hot, gap_plane_index=gap_plane_index))
    states = couplings.shape[1]
    width = couplings.shape[0]
    if PARAMETERS["use_bias"]:
        hamiltonian = np.asarray(reference.get_Hamiltonian_loss(one_hot, couplings, fields, return_H=True))
        pseudo_loss = np.asarray(reference.get_Hamiltonian_loss(one_hot, couplings, fields))
    else:
        hamiltonian = np.asarray(reference.get_Hamiltonian_loss(one_hot, couplings, return_H=True))
        pseudo_loss = np.asarray(reference.get_Hamiltonian_loss(one_hot, couplings))
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

    # Fail closed before touching any cell content.
    assert_pinned_identity(upstream)
    sources = _notebook_sources(upstream)
    # Prove the checked-in transcription is the pinned notebook's own source.
    reference.assert_matches_pinned_notebook(sources)

    headers, sequences = reference.parse_fasta(str(input_path), a3m=True)

    def variant(name: str) -> dict:
        gap_plane_index, field_penalty_floor = reference.VARIANTS[name]
        fields, couplings = _fit(sequences, gap_plane_index, field_penalty_floor)
        return _observables(sequences, fields, couplings, gap_plane_index)

    expected = variant("expected")
    # The unmodified notebook: both deviations present.  Read together with
    # ``d1_only`` below, which keeps D1 and reverts D2.
    pinned = variant("pinned_uncorrected")
    # D1 applied, D2 reverted: isolates the gap-plane correction.
    d1_only = variant("d1_only")

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
            "cells": dict(CELLS),
        },
        "generator": {
            "script": "tests/data/gremlin_lh/generate_upstream_reference.py",
            "transcription": "tests/data/gremlin_lh/upstream_notebook_reference.py",
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "jax": __import__("jax").__version__,
            "numpy": np.__version__,
            "optax": __import__("optax").__version__,
            "note": (
                "Observables are produced by a checked-in transcription of the pinned notebook's "
                "own functions, not by the Runner, so a Runner regression appears as a receipt "
                "mismatch."
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
            "note": (
                "Unmodified notebook: BOTH documented corrections absent. Do not read this as "
                "isolating D1; the field scale here is driven by the floored field penalty (D2)."
            ),
            "neff": pinned["neff"],
            "sequence_weights": pinned["sequence_weights"],
            "top_apc_pairs": pinned["top_apc_pairs"],
        },
        "d1_only": {
            "note": (
                "Gap plane corrected, field penalty still floored: isolates D1. Neff and the "
                "sequence weights match `expected`; the one-body field scale does not."
            ),
            "neff": d1_only["neff"],
            "sequence_weights": d1_only["sequence_weights"],
            "top_apc_pairs": d1_only["top_apc_pairs"],
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
