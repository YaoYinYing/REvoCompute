# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
"""Upstream scientific-equivalence acceptance for GREMLIN_LH.

``test_runner.py`` keeps the tiny synthetic fixture as a fast protocol contract.
This module proves the *upstream-compatible* scientific path instead: it runs the
Runner's real fitting code with the pinned upstream notebook parameters
(regularized inverse-covariance initialization and the upstream LH optimizer
path) and compares sequence weights/Neff, one-site fields ``V``, pairwise
couplings ``W``, and the raw/APC coupling matrices against a frozen receipt
derived from the pinned upstream implementation.

Reference provenance: ``tests/data/gremlin_lh/upstream_reference.json`` records
the upstream repository, pinned commit, notebook blob, input hash, parameters,
and the two README-documented corrections that the Runner intentionally applies
(explicit gap state for sequence weighting; ordinary-division field L2 penalty).
The receipt also retains the uncorrected pinned values so the deliberate
deviation is explicit rather than silent.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker" / "runners" / "gremlin_lh"
ADAPTER_PATH = FAMILY / "fit_model.py"
RECEIPT_PATH = ROOT / "tests" / "data" / "gremlin_lh" / "upstream_reference.json"

SPEC = importlib.util.spec_from_file_location("gremlin_lh_equivalence_adapter", ADAPTER_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)

# Float32 optimizer trajectories diverge at the ~1e-5 level per step because the
# upstream reference and the Runner draw different (but equivalent) row
# permutations for the full-batch update.  Tolerances cover that accumulation
# order effect while staying far below any scientific signal.  Sequence weights
# and Neff are algorithmic and match exactly.
FIELD_ATOL = 2e-3
COUPLING_ATOL = 2e-3
SCORE_ATOL = 2e-3
WEIGHT_ATOL = 1e-6


def _dependency_guard() -> None:
    pytest.importorskip("jax")
    pytest.importorskip("optax")
    pytest.importorskip("matplotlib")


@pytest.fixture(scope="module")
def upstream_reference():
    _dependency_guard()
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    fixture = ROOT / receipt["input"]["path"]
    headers, sequences = adapter.parse_alignment(fixture, a3m=True)
    parameters = receipt["parameters"]
    fields, couplings, weights, _history = adapter.fit_model(
        adapter.encode_alignment(sequences),
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
    }


def test_upstream_reference_receipt_is_pinned_and_provenanced(upstream_reference) -> None:
    receipt = upstream_reference["receipt"]
    assert receipt["upstream"]["repository"] == "https://github.com/sokrypton/GREMLIN_LH"
    assert receipt["upstream"]["commit"] == adapter.UPSTREAM_COMMIT
    assert receipt["upstream"]["notebook"] == "GREMLIN_LH_outline_7.ipynb"
    assert receipt["parameters"]["inverse_covariance_init"] is True
    assert receipt["parameters"]["regularization"] == "LH"
    assert (
        hashlib.sha256(upstream_reference["fixture"].read_bytes()).hexdigest()
        == receipt["input"]["sha256"]
    )
    # The reference case is separate from the tiny fast-contract fixture.
    assert upstream_reference["fixture"].name != "gremlin_lh_tiny.a3m"
    assert len(upstream_reference["headers"]) == receipt["input"]["rows"] >= 2


def test_upstream_compatible_weights_and_neff_match_reference(upstream_reference) -> None:
    receipt = upstream_reference["receipt"]["expected"]
    weights = upstream_reference["weights"]
    np.testing.assert_allclose(np.asarray(receipt["sequence_weights"]), weights, atol=WEIGHT_ATOL)
    assert float(np.sum(weights)) == pytest.approx(receipt["neff"], abs=1e-5)


def test_upstream_compatible_fields_and_couplings_match_reference(upstream_reference) -> None:
    expected = upstream_reference["receipt"]["expected"]
    fields = upstream_reference["fields"]
    couplings = upstream_reference["couplings"]
    np.testing.assert_allclose(np.asarray(expected["fields"]), fields, atol=FIELD_ATOL)
    for block in expected["couplings_blocks"]:
        observed = couplings[block["i"], :, block["j"], :]
        np.testing.assert_allclose(np.asarray(block["block"]), observed, atol=COUPLING_ATOL)
    assert float(np.sum(np.square(couplings))) == pytest.approx(expected["couplings_l2"], rel=1e-3)
    assert float(np.max(np.abs(couplings))) == pytest.approx(expected["couplings_max_abs"], rel=1e-3)


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


def test_receipt_records_the_documented_deviations(upstream_reference) -> None:
    """The two intentional corrections must stay visible, not silently absorbed."""
    receipt = upstream_reference["receipt"]
    pinned = receipt["pinned_uncorrected"]
    assert "corrections" in receipt["reference"] or "corrections" in receipt["reference"].lower()
    # The explicit-gap-state correction changes Neff on this gap-containing
    # alignment, so the pinned and corrected references genuinely differ.
    assert abs(pinned["neff"] - receipt["expected"]["neff"]) > 0.1
    assert pinned["sequence_weights"] != receipt["expected"]["sequence_weights"]
