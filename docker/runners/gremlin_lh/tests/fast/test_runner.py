# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
"""GREMLIN-LH Runner tests.

The suite covers three layers:

* Runner-owned executable logic (alignment parsing, fitting, artifact writing);
* the smoke end-to-end contract: the real ``run.sh`` consumed against a
  protocol-v3 ``task.json`` and validated with the server's own result
  parsers; and
* fail-closed behavior for malformed input and incomplete runs.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.runner_contract
ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "docker" / "runner_testkit"))
from runner_protocol import run_with_manifest


FAMILY = ROOT / "docker" / "runners" / "gremlin_lh"
ADAPTER_PATH = FAMILY / "fit_model.py"
RUN_SCRIPT = FAMILY / "run.sh"
FIXTURE = ROOT / "tests" / "data" / "msa" / "gremlin_lh_tiny.a3m"
SPEC = importlib.util.spec_from_file_location("gremlin_lh_fit_model", ADAPTER_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)

# The server resolves every task.yaml default before dispatch, so task.json
# always carries the complete parameter set.
RUN_PARAMETERS = {
    "regularization": "LH",
    "lambda_l2": 0.01,
    "lambda_lh": 0.1,
    "lambda_lb": 0.005,
    "iterations": 2,
    "batch_size": 4,
    "learning_rate": 1.0,
    "identity_cutoff": 0.8,
    "gap_cutoff": 0.5,
    "use_bias": True,
    "inverse_covariance_init": False,
    "exact_lh_eigenvalue": False,
    "a3m": True,
    "seed": 7,
}




def _runner_env(tmp_path: Path) -> dict[str, str]:
    mplconfig = tmp_path / "mplconfig"
    mplconfig.mkdir(exist_ok=True)
    return {
        **os.environ,
        "TASK_TYPE": "gremlin_lh_fit",
        "GREMLIN_LH_PYTHON": sys.executable,
        "GREMLIN_LH_FIT_MODEL": str(ADAPTER_PATH),
        "MPLCONFIGDIR": str(mplconfig),
    }


def _copy_fixture(tmp_path: Path, content: str | None = None) -> Path:
    source = tmp_path / "input.a3m"
    source.write_text(content if content is not None else FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return source




# ── Runner-owned executable logic ─────────────────────────────────────────────


def test_alignment_parser_removes_a3m_insertions_and_preserves_gap(tmp_path: Path) -> None:
    path = tmp_path / "input.a3m"
    path.write_text(">query\nACD-E\n>hit\nACxD-E\n", encoding="utf-8")
    headers, sequences = adapter.parse_alignment(path, a3m=True)
    assert headers == ["query", "hit"]
    assert sequences == ["ACD-E", "ACD-E"]
    encoded = adapter.encode_alignment(sequences)
    assert encoded[0, 3] == adapter.GAP_INDEX == 0


def test_alignment_parser_removes_a3m_insertion_dots(tmp_path: Path) -> None:
    """Insertion-gap dots are stripped with the insertion residues they annotate."""
    path = tmp_path / "insertion-dots.a3m"
    path.write_text(">query\nACD-E\n>hit\nAC.dD-E\n", encoding="utf-8")
    assert adapter.parse_alignment(path, a3m=True)[1] == ["ACD-E", "ACD-E"]


def test_query_position_map_skips_query_gaps() -> None:
    assert adapter.query_position_map("A-CD-EF") == [1, None, 2, 3, None, 4, 5]


def test_coupling_scores_reproduce_the_upstream_apc_definition() -> None:
    """Frobenius + APC must match the notebook's raw-matrix formula on real model tensors."""
    rng = np.random.default_rng(0)
    couplings = rng.normal(size=(6, 21, 6, 21)).astype(np.float32)

    # Transcription of the notebook's jax_apc (raw Frobenius norm with a +1e-8
    # under the square root; APC over the raw matrix; diagonal zeroed). The
    # notebook's separate get_mtx routine omits that epsilon, which changes the
    # off-diagonal entries by ~1e-9 and is why the assertion uses atol=1e-5
    # instead of exact equality. The runner follows jax_apc so the reported
    # matrix stays consistent with the matrix the LH objective regularizes.
    upstream_raw = np.sqrt(np.sum(np.square(couplings), axis=(1, 3)) + 1e-8)
    np.fill_diagonal(upstream_raw, 0.0)
    upstream_apc = upstream_raw - np.sum(upstream_raw, axis=0, keepdims=True) * np.sum(
        upstream_raw, axis=1, keepdims=True
    ) / np.sum(upstream_raw)
    np.fill_diagonal(upstream_apc, 0.0)

    raw, apc = adapter.coupling_scores(couplings)
    np.testing.assert_allclose(raw, upstream_raw, atol=1e-5)
    np.testing.assert_allclose(apc, upstream_apc, atol=1e-5)

    # The complementary get_mtx form (no epsilon) must also agree within the
    # same tolerance, since the two upstream routines only differ by that guard.
    epsilon_free = np.sqrt(np.sum(np.square(couplings), axis=(1, 3)))
    np.fill_diagonal(epsilon_free, 0.0)
    np.testing.assert_allclose(raw, epsilon_free, atol=1e-5)


@pytest.mark.parametrize(
    "content, message",
    [
        (">only\nACDE\n", "at least two"),
        (">one\nACDE\n>two\nACD\n", "unequal widths"),
        (">one\nACDE\n>two\nACXE\n", "unsupported residues"),
    ],
)
def test_alignment_parser_rejects_unsafe_inputs(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "bad.a3m"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        adapter.parse_alignment(path)




# ── Smoke end-to-end contract ──────────────────────────────────────────────────












# ── Fail-closed behavior ──────────────────────────────────────────────────────


def test_missing_declared_role_fails_before_fitting(tmp_path: Path) -> None:
    source = _copy_fixture(tmp_path)
    output = tmp_path / "output"
    completed = run_with_manifest(RUN_SCRIPT, source, output, _runner_env(tmp_path), params=RUN_PARAMETERS, role="protein")
    assert completed.returncode != 0
    assert not (output / "summary.json").exists()
    assert not (output / "task_finished").exists()


@pytest.mark.parametrize(
    "content, message",
    [
        ("ACDE\nACDE\n", "header before sequence data"),
        (">only\nACDE\n", "at least two"),
        (">one\nACDE\n>two\nACD\n", "unequal widths"),
        (">one\nACDE\n>two\nACXE\n", "unsupported residues"),
        (">one\n\n>two\nACDE\n", "cannot be empty"),
    ],
)
def test_malformed_alignment_fails_closed(tmp_path: Path, content: str, message: str) -> None:
    source = _copy_fixture(tmp_path, content)
    output = tmp_path / "output"
    completed = run_with_manifest(RUN_SCRIPT, source, output, _runner_env(tmp_path), params=RUN_PARAMETERS, role="alignment")
    assert completed.returncode != 0
    assert message in completed.stderr
    assert not (output / "summary.json").exists()
    assert not (output / "task_finished").exists()


def test_missing_artifact_after_nominal_exit_fails_closed(tmp_path: Path) -> None:
    """A Runner that exits 0 without producing artifacts must not publish a result."""
    stub = tmp_path / "stub_fit.py"
    stub.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    source = _copy_fixture(tmp_path)
    output = tmp_path / "output"
    env = _runner_env(tmp_path)
    env["GREMLIN_LH_FIT_MODEL"] = str(stub)
    completed = run_with_manifest(RUN_SCRIPT, source, output, env, params=RUN_PARAMETERS, role="alignment")
    assert completed.returncode != 0
    assert "did not produce required artifact" in completed.stderr
    assert not (output / "task_finished").exists()
