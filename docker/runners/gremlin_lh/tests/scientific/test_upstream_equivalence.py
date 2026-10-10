# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
"""Upstream scientific-equivalence acceptance for GREMLIN_LH.

``test_runner.py`` keeps the tiny synthetic fixture as a fast protocol contract.
This module proves the *upstream-compatible* scientific path instead: it runs the
Runner's real fitting code with the pinned upstream notebook parameters
(regularized inverse-covariance initialization and the upstream LH optimizer
path) and compares sequence weights/Neff, the one-site fields ``V``, pairwise
coupling blocks ``W``, the raw/APC coupling matrices, and the per-sequence
pseudo-likelihood/Hamiltonian scores against a frozen receipt derived from the
pinned upstream implementation.

Reference provenance: ``docker/runners/gremlin_lh/tests/scientific/references/upstream_reference.json`` records
the upstream repository, pinned commit, notebook blob and file hashes, input
hash, parameters, seed, and the two documented corrections that the Runner
intentionally applies (explicit gap plane for sequence weighting; ordinary-
division field L2 penalty).  It also retains the uncorrected pinned values so the
deliberate deviation stays visible.  Regenerate it with
``docker/runners/gremlin_lh/tests/scientific/references/generate_upstream_reference.py`` (see
``SCIENTIFIC_TRACEABILITY.md``); the generator runs the notebook's own functions,
so a mismatch here is a real Runner regression, not a shared-helper artefact.

Tolerance rationale
-------------------
The receipt is produced by the notebook and the Runner reaches the same fixed
point through a different float32 reduction order (consecutive full-batch Adam
steps accumulate mm/additions differently under JAX/optax versus the notebook's
loop, so the residual is reduction-order noise, not sampling: at full batch both
draw the same six rows and the fit is seed-insensitive).  Measured agreement on
the current pinned stack is 20-100x tighter than these bounds:

* sequence weights / Neff: algorithmic and identical, so exact to 1e-6.
* fields, W blocks, raw and APC matrices: 2e-3 absolute (measured <= 5.8e-5).
* coupling tensor L2 norm and max magnitude: 1e-3 relative (measured <= 6.8e-6);
  aggregates over 2.7M entries amplify per-entry float32 noise.
* per-sequence pseudo-loss and Hamiltonian: 5e-2 absolute on quantities whose
  scale is ~20 and ~376 respectively (measured <= 5.5e-4).

These bounds are not to be widened to accommodate a regression: a failure means
the science changed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.scientific_acceptance

ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / "docker" / "runners" / "gremlin_lh"
ADAPTER_PATH = FAMILY / "fit_model.py"
RECEIPT_PATH = Path(__file__).resolve().parent / "references" / "upstream_reference.json"
GENERATOR_PATH = Path(__file__).resolve().parent / "references" / "generate_upstream_reference.py"

SPEC = importlib.util.spec_from_file_location("gremlin_lh_equivalence_adapter", ADAPTER_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)

WEIGHT_ATOL = 1e-6
NEFF_ATOL = 1e-5
FIELD_ATOL = 2e-3
COUPLING_ATOL = 2e-3
SCORE_ATOL = 2e-3
AGGREGATE_RTOL = 1e-3
SEQUENCE_ATOL = 5e-2


def _dependency_guard() -> None:
    __import__("jax")
    __import__("optax")
    __import__("matplotlib")


@pytest.fixture(scope="module")
def upstream_reference():
    _dependency_guard()
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    fixture = ROOT / receipt["input"]["path"]
    headers, sequences = adapter.parse_alignment(fixture, a3m=True)
    encoded = adapter.encode_alignment(sequences)
    parameters = receipt["parameters"]
    fields, couplings, weights, _history = adapter.fit_model(
        encoded,
        regularization_mode=parameters["regularization"],
        lambda_l2=parameters["lambda_l2"],
        lambda_lh=parameters["lambda_lh"],
        lambda_lb=parameters["lambda_lb"],
        iterations=parameters["iterations"],
        batch_size=parameters["batch_size"],
        learning_rate=parameters["learning_rate"],
        identity_cutoff=parameters["identity_cutoff"],
        gap_cutoff=parameters["gap_cutoff"],
        use_bias=parameters["use_bias"],
        inverse_covariance_init=parameters["inverse_covariance_init"],
        exact_lh_eigenvalue=parameters["exact_lh_eigenvalue"],
        seed=parameters["seed"],
    )
    raw, apc = adapter.coupling_scores(couplings)
    pseudo_loss, hamiltonian = adapter.sequence_statistics(encoded, fields, couplings)
    return {
        "receipt": receipt,
        "fixture": fixture,
        "headers": headers,
        "sequences": sequences,
        "fields": fields,
        "couplings": couplings,
        "weights": weights,
        "raw": raw,
        "apc": apc,
        "pseudo_loss": pseudo_loss,
        "hamiltonian": hamiltonian,
    }


def test_upstream_reference_receipt_is_pinned_and_provenanced(upstream_reference) -> None:
    receipt = upstream_reference["receipt"]
    assert receipt["upstream"]["repository"] == "https://github.com/sokrypton/GREMLIN_LH"
    assert receipt["upstream"]["commit"] == adapter.UPSTREAM_COMMIT
    assert receipt["upstream"]["notebook"] == "GREMLIN_LH_outline_7.ipynb"
    assert receipt["upstream"]["notebook_blob"] == "79cc0fdaba25ff1a6d6cb12ab2a2ebc8358c2c17"
    assert receipt["generator"]["script"].endswith("generate_upstream_reference.py")
    assert GENERATOR_PATH.is_file()
    assert receipt["parameters"]["inverse_covariance_init"] is True
    assert receipt["parameters"]["regularization"] == "LH"
    assert (
        hashlib.sha256(upstream_reference["fixture"].read_bytes()).hexdigest()
        == receipt["input"]["sha256"]
    )
    # The reference case is separate from the tiny fast-contract fixture.
    assert upstream_reference["fixture"].name != "gremlin_lh_tiny.a3m"
    assert len(upstream_reference["headers"]) == receipt["input"]["rows"] >= 2
    # Every observable the generator is contracted to record is present.
    expected = receipt["expected"]
    for key in (
        "sequence_weights",
        "neff",
        "fields",
        "couplings_blocks",
        "couplings_l2",
        "couplings_max_abs",
        "raw_scores",
        "apc_scores",
        "sequence_pseudo_loss",
        "sequence_hamiltonian",
        "top_apc_pairs",
    ):
        assert key in expected, key
    assert expected["positions"] == receipt["input"]["columns"]
    assert expected["states"] == len(adapter.ALPHABET)


def test_upstream_compatible_weights_and_neff_match_reference(upstream_reference) -> None:
    receipt = upstream_reference["receipt"]["expected"]
    weights = upstream_reference["weights"]
    np.testing.assert_allclose(np.asarray(receipt["sequence_weights"]), weights, atol=WEIGHT_ATOL)
    assert float(np.sum(weights)) == pytest.approx(receipt["neff"], abs=NEFF_ATOL)


def test_upstream_compatible_fields_and_couplings_match_reference(upstream_reference) -> None:
    expected = upstream_reference["receipt"]["expected"]
    fields = upstream_reference["fields"]
    couplings = upstream_reference["couplings"]
    assert fields.shape == (expected["positions"], expected["states"])
    np.testing.assert_allclose(np.asarray(expected["fields"]), fields, atol=FIELD_ATOL)
    assert expected["couplings_blocks"], "receipt must pin at least one coupling block"
    for block in expected["couplings_blocks"]:
        observed = couplings[block["i"], :, block["j"], :]
        np.testing.assert_allclose(np.asarray(block["block"]), observed, atol=COUPLING_ATOL)
    assert float(np.sum(np.square(couplings))) == pytest.approx(expected["couplings_l2"], rel=AGGREGATE_RTOL)
    assert float(np.max(np.abs(couplings))) == pytest.approx(expected["couplings_max_abs"], rel=AGGREGATE_RTOL)


def test_upstream_compatible_coupling_scores_match_reference(upstream_reference) -> None:
    expected = upstream_reference["receipt"]["expected"]
    raw = upstream_reference["raw"]
    apc = upstream_reference["apc"]
    np.testing.assert_allclose(np.asarray(expected["raw_scores"]), raw, atol=SCORE_ATOL)
    np.testing.assert_allclose(np.asarray(expected["apc_scores"]), apc, atol=SCORE_ATOL)

    reference_ranking = [(int(i), int(j)) for i, j, _raw, _apc in expected["top_apc_pairs"]]
    observed = sorted(
        ((apc[i, j], i, j) for i in range(apc.shape[0]) for j in range(i + 1, apc.shape[0])),
        reverse=True,
    )[: len(reference_ranking)]
    observed_ranking = [(int(i), int(j)) for _score, i, j in observed]
    # The strongest pair is unambiguous; lower ranks can swap when two APC
    # scores are numerically tied at the float32 tolerance, so require a high
    # set overlap rather than an exact ordering.
    assert observed_ranking[0] == reference_ranking[0]
    overlap = len(set(observed_ranking) & set(reference_ranking))
    assert overlap >= len(reference_ranking) - 2, (observed_ranking, reference_ranking)
    # The strongest pair's raw and APC scores must also agree locally.
    top_i, top_j = reference_ranking[0]
    assert raw[top_i, top_j] == pytest.approx(expected["top_apc_pairs"][0][2], abs=SCORE_ATOL)
    assert apc[top_i, top_j] == pytest.approx(expected["top_apc_pairs"][0][3], abs=SCORE_ATOL)


def test_upstream_compatible_sequence_scores_match_reference(upstream_reference) -> None:
    expected = upstream_reference["receipt"]["expected"]
    np.testing.assert_allclose(
        np.asarray(expected["sequence_pseudo_loss"]), upstream_reference["pseudo_loss"], atol=SEQUENCE_ATOL
    )
    np.testing.assert_allclose(
        np.asarray(expected["sequence_hamiltonian"]), upstream_reference["hamiltonian"], atol=SEQUENCE_ATOL
    )


def test_receipt_records_the_documented_deviations(upstream_reference) -> None:
    """Both intentional corrections must stay visible and independently checkable.

    ``pinned_uncorrected`` is the unmodified notebook, so it differs from
    ``expected`` by *both* corrections; on this reference case the difference is
    dominated by the field-penalty floor (D2), so a D1-only revert would not have
    been caught by that section alone.  ``d1_only`` isolates D1: it carries the
    same weights/Neff as ``expected`` while its fit still reflects the floored
    penalty.  Asserting on both makes a revert of either correction observable.
    """
    receipt = upstream_reference["receipt"]
    pinned = receipt["pinned_uncorrected"]
    d1_only = receipt["d1_only"]
    expected = receipt["expected"]
    assert "corrections" in receipt["reference"] or "corrections" in receipt["reference"].lower()

    # D1 changes Neff on this gap-containing alignment; D2 does not.
    assert abs(pinned["neff"] - expected["neff"]) > 0.1
    assert abs(d1_only["neff"] - expected["neff"]) < 1e-5
    assert pinned["sequence_weights"] != expected["sequence_weights"]
    assert d1_only["sequence_weights"] == expected["sequence_weights"]
    assert d1_only["neff"] == pytest.approx(float(np.sum(upstream_reference["weights"])), abs=1e-5)
    # D1 alone must still differ from the fully corrected reference, so D2 cannot
    # be reverted without the receipt comparison moving too.
    assert d1_only["top_apc_pairs"] != pinned["top_apc_pairs"]
    assert d1_only["top_apc_pairs"] != expected["top_apc_pairs"]
    # The receipt must state what each baseline does and does not isolate.
    assert "both" in pinned["note"].lower()
    assert "d1" in d1_only["note"].lower()
