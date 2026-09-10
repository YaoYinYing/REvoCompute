# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "docker" / "runners" / "gremlin_lh"
ADAPTER_PATH = FAMILY / "fit_model.py"
SPEC = importlib.util.spec_from_file_location("gremlin_lh_fit_model", ADAPTER_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def test_alignment_parser_removes_a3m_insertions_and_preserves_gap(tmp_path: Path) -> None:
    path = tmp_path / "input.a3m"
    path.write_text(">query\nACD-E\n>hit\nACxD-E\n", encoding="utf-8")
    headers, sequences = adapter.parse_alignment(path, a3m=True)
    assert headers == ["query", "hit"]
    assert sequences == ["ACD-E", "ACD-E"]
    encoded = adapter.encode_alignment(sequences)
    assert encoded[0, 3] == adapter.GAP_INDEX == 0


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


def test_headless_fit_emits_complete_solid_artifact_set(tmp_path: Path) -> None:
    pytest.importorskip("jax")
    pytest.importorskip("matplotlib")
    pytest.importorskip("optax")
    source = ROOT / "tests" / "data" / "msa" / "gremlin_lh_tiny.a3m"
    headers, sequences = adapter.parse_alignment(source)
    parameters = {
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
    fields, couplings, weights, history = adapter.fit_model(
        adapter.encode_alignment(sequences),
        regularization_mode="LH",
        lambda_l2=0.01,
        lambda_lh=0.1,
        lambda_lb=0.005,
        iterations=2,
        batch_size=4,
        learning_rate=1.0,
        identity_cutoff=0.8,
        gap_cutoff=0.5,
        use_bias=True,
        inverse_covariance_init=False,
        exact_lh_eigenvalue=False,
        seed=7,
    )
    adapter.write_results(tmp_path, headers, sequences, fields, couplings, weights, history, parameters)

    required = {
        "potts_model.npz",
        "coupling_raw.csv",
        "coupling_apc.csv",
        "coupling_pairs.csv",
        "position_frequencies.csv",
        "sequence_scores.csv",
        "training_history.csv",
        "normalized_alignment.fasta",
        "summary.json",
        "coupling_apc.png",
    }
    assert required <= {path.name for path in tmp_path.iterdir() if path.stat().st_size > 0}
    model = np.load(tmp_path / "potts_model.npz")
    assert model["fields"].shape == (8, 21)
    assert model["couplings"].shape == (8, 21, 8, 21)
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["upstream"]["commit"] == adapter.UPSTREAM_COMMIT
    assert summary["alignment"]["sequence_count"] == 8


def test_contract_is_bounded_and_has_smoke_coverage() -> None:
    task = yaml.safe_load((FAMILY / "tasks" / "gremlin_lh_fit" / "task.yaml").read_text(encoding="utf-8"))
    schema = task["parameters"]
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["regularization"]["enum"] == ["L2", "LH", "LB"]
    assert schema["properties"]["iterations"]["maximum"] == 5000
    smoke = yaml.safe_load((FAMILY / "test.yaml").read_text(encoding="utf-8"))
    assert {case["task"] for case in smoke["collections"]["smoke"]["cases"]} == {"gremlin_lh_fit"}


def test_plugin_is_discoverable_through_the_production_registry() -> None:
    from revocompute.task_types import discover_plugins, get

    discover_plugins(str(ROOT / "docker" / "runners"), {"gremlin_lh"})
    task, runner = get("gremlin_lh_fit")
    assert task.runtime.name == "gremlin_lh"
    assert runner.env["JAX_PLATFORM_NAME"] == "cpu"


def test_family_is_cpu_only_without_asset_mounts() -> None:
    runner = yaml.safe_load((FAMILY / "runner.yaml").read_text(encoding="utf-8"))
    task = yaml.safe_load((FAMILY / "tasks" / "gremlin_lh_fit" / "task.yaml").read_text(encoding="utf-8"))
    assert not runner.get("mounts")
    assert task.get("gpus", False) is False
    definition = (FAMILY / "gremlin_lh.def").read_text(encoding="utf-8")
    assert adapter.UPSTREAM_COMMIT not in definition  # transcribed source is Runner-owned
    assert "JAX_PLATFORM_NAME=cpu" in definition
    assert "-r /app/revocompute/requirements.lock" in definition
    requirements = (FAMILY / "requirements.lock").read_text(encoding="utf-8").splitlines()
    assert requirements and all("==" in requirement for requirement in requirements)
