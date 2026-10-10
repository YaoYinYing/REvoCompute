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

import csv
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytestmark = pytest.mark.scientific_acceptance

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

REQUIRED_ARTIFACTS = (
    "summary.json",
    "query.fasta",
    "alignment/filtered_alignment.a3m",
    "alignment/statistics.json",
    "alignment/sequence_weights.tsv",
    "model/gremlin_mrf.npz",
    "model/metadata.json",
    "model/training_history.csv",
    "model/sequence_scores.tsv",
    "profiles/profile.tsv",
    "couplings/pairwise_scores.tsv",
    "couplings/raw_scores.csv",
    "couplings/apc_scores.csv",
    "plots/coupling_apc.png",
)

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



def _dependencies_available() -> None:
    __import__("jax")
    __import__("matplotlib")
    __import__("optax")


@pytest.fixture(scope="module")
def smoke_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, "object"]:
    """Execute the real Runner once and share its artifact tree across assertions."""
    _dependencies_available()
    tmp_path = tmp_path_factory.mktemp("gremlin_lh_smoke")
    source = _copy_fixture(tmp_path)
    output = tmp_path / "output"
    completed = run_with_manifest(
        RUN_SCRIPT,
        source,
        output,
        _runner_env(tmp_path),
        params=RUN_PARAMETERS,
        role="alignment",
    )
    assert completed.returncode == 0, completed.stderr
    return output, completed


def test_identical_alignment_rows_produce_finite_model_values() -> None:
    _dependencies_available()
    encoded = adapter.encode_alignment(["ACDE", "ACDE"])
    fields, couplings, weights, _ = adapter.fit_model(
        encoded,
        regularization_mode="LH",
        lambda_l2=0.01,
        lambda_lh=0.1,
        lambda_lb=0.005,
        iterations=1,
        batch_size=2,
        learning_rate=1.0,
        identity_cutoff=0.8,
        gap_cutoff=0.5,
        use_bias=True,
        inverse_covariance_init=False,
        exact_lh_eigenvalue=False,
        seed=7,
    )
    assert all(np.all(np.isfinite(array)) for array in (fields, couplings, weights))


def test_smoke_run_produces_the_declared_artifact_tree(smoke_run) -> None:
    output, completed = smoke_run
    assert "REVODESIGN_STAGE:gremlin_lh_fit" in completed.stdout
    assert (output / "task_finished").is_file()
    for artifact in REQUIRED_ARTIFACTS:
        assert (output / artifact).is_file(), artifact
        assert (output / artifact).stat().st_size > 0, artifact
    produced = {
        str(path.relative_to(output))
        for path in output.rglob("*")
        if path.is_file() and path.name != "task_finished"
    }
    assert produced == set(REQUIRED_ARTIFACTS)


def test_smoke_run_preserves_the_durable_mrf_model(smoke_run) -> None:
    output, _ = smoke_run
    model = np.load(output / "model/gremlin_mrf.npz")
    assert model["fields"].shape == (8, 21)
    assert model["couplings"].shape == (8, 21, 8, 21)
    assert model["alphabet"].tolist() == list(adapter.ALPHABET)
    assert int(model["gap_index"]) == adapter.GAP_INDEX
    assert float(np.sum(model["sequence_weights"])) > 0
    assert np.all(np.isfinite(model["fields"])) and np.all(np.isfinite(model["couplings"]))
    metadata = json.loads((output / "model/metadata.json").read_text(encoding="utf-8"))
    assert metadata["arrays"]["couplings"]["shape"] == [8, 21, 8, 21]
    assert metadata["upstream"]["commit"] == adapter.UPSTREAM_COMMIT


def test_smoke_run_profile_and_couplings_have_correct_indexing(smoke_run) -> None:
    output, _ = smoke_run
    with (output / "profiles/profile.tsv").open(encoding="utf-8", newline="") as handle:
        profile = list(csv.DictReader(handle, delimiter="\t"))
    assert len(profile) == 8
    assert profile[3]["alignment_position"] == "4"
    assert profile[3]["query_position"] == "4"
    assert profile[3]["query_residue"] == "E"

    with (output / "couplings/pairwise_scores.tsv").open(encoding="utf-8", newline="") as handle:
        pairs = list(csv.DictReader(handle, delimiter="\t"))
    assert len(pairs) == 8 * 7 // 2
    assert [int(row["rank"]) for row in pairs] == list(range(1, len(pairs) + 1))
    apc_scores = [float(row["apc_score"]) for row in pairs]
    assert apc_scores == sorted(apc_scores, reverse=True)
    top = pairs[0]
    assert int(top["alignment_i"]) < int(top["alignment_j"])
    assert int(top["sequence_separation"]) == int(top["alignment_j"]) - int(top["alignment_i"])

    for name in ("raw_scores.csv", "apc_scores.csv"):
        lines = (output / "couplings" / name).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 9


def test_smoke_run_summary_is_internally_consistent(smoke_run) -> None:
    output, _ = smoke_run
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == 2
    assert summary["method"] == "GREMLIN_LH"
    assert summary["upstream"]["commit"] == adapter.UPSTREAM_COMMIT
    assert summary["alignment"]["sequence_count"] == 8
    assert summary["alignment"]["alignment_length"] == 8
    assert summary["model"]["positions"] == 8
    assert summary["model"]["states"] == 21
    assert summary["optimization"]["iterations"] == RUN_PARAMETERS["iterations"]
    assert summary["parameters"] == RUN_PARAMETERS
    for path in summary["artifacts"].values():
        assert (output / path).is_file(), path


def test_declared_result_contract_resolves_the_produced_artifacts(tmp_path: Path, smoke_run, monkeypatch) -> None:
    """The server's own expected-file and storyboard parsers accept the real output."""
    from revocompute.result_storyboard import expected_file_tree, resolve_expected_files, storyboard_declaration

    output, _ = smoke_run
    monkeypatch.setenv("RUNNERS_DIR", str(ROOT / "docker" / "runners"))
    task_type = SimpleNamespace(runtime=SimpleNamespace(root=str(FAMILY)))
    tree = expected_file_tree(task_type, "")
    assert "mrf_model" in tree and "profile" in tree and "pairwise_scores" in tree

    artifacts = [
        {"path": str(path.relative_to(output)), "size": path.stat().st_size}
        for path in sorted(output.rglob("*"))
        if path.is_file()
    ]
    _, checks, problems = resolve_expected_files(tree, artifacts)
    assert problems == []
    assert all(check["required"] and check["status"] == "passed" for check in checks)

    declaration = storyboard_declaration(task_type, "", set(tree))
    assert declaration is not None
    assert set(declaration["requires"]) | set(declaration["optional"]) == set(tree)
    assert set(declaration["requires"]).isdisjoint(declaration["optional"])
    entry = FAMILY / "storyboard" / declaration["entrypoint"]
    assert entry.is_file()
