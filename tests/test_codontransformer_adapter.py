# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "docker" / "runners" / "codontransformer" / "predict.py"
SPEC = importlib.util.spec_from_file_location("codontransformer_adapter", ADAPTER_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)
TASK_PATH = ROOT / "docker" / "runners" / "codontransformer" / "tasks" / "codon_optimize" / "task.yaml"


def test_read_single_fasta_normalizes_one_protein(tmp_path: Path) -> None:
    fasta = tmp_path / "protein.fasta"
    fasta.write_text(">example\nmww\nmw*\n", encoding="utf-8")
    assert adapter.read_single_fasta(fasta) == ("example", "MWWMW")


def test_read_single_fasta_rejects_sequence_that_upstream_would_truncate(tmp_path: Path) -> None:
    fasta = tmp_path / "too-long.fasta"
    fasta.write_text(">example\n" + "M" * 2047 + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="2046-residue"):
        adapter.read_single_fasta(fasta)


@pytest.mark.parametrize("content", ["MWWMW\n", ">one\nMW\n>two\nMW\n", ">empty\n"])
def test_read_single_fasta_rejects_invalid_cardinality(tmp_path: Path, content: str) -> None:
    fasta = tmp_path / "invalid.fasta"
    fasta.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        adapter.read_single_fasta(fasta)


def test_validate_model_dir_reports_all_missing_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="model.safetensors"):
        adapter.validate_model_dir(tmp_path)


def test_write_results_emits_fasta_and_machine_readable_metadata(tmp_path: Path) -> None:
    @dataclass
    class Prediction:
        organism: str
        protein: str
        processed_input: str
        predicted_dna: str

    prediction = Prediction("Escherichia coli general", "M", "M_UNK __UNK", "ATGTAA")
    adapter.write_results(tmp_path, "example", [prediction], {"deterministic": True})
    assert (tmp_path / "optimized_sequences.fasta").read_text(encoding="utf-8").endswith("ATGTAA\n")
    payload = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert payload["predictions"][0]["rank"] == 1
    assert payload["parameters"] == {"deterministic": True}


def test_task_contract_exposes_all_164_organisms_and_rejects_unlisted_names() -> None:
    schema = yaml.safe_load(TASK_PATH.read_text(encoding="utf-8"))["parameters"]
    organisms = schema["properties"]["organism"]["enum"]
    assert len(organisms) == len(set(organisms)) == 164
    assert organisms[0] == "Arabidopsis thaliana"
    assert organisms[-1] == "Yokenella regensburgei"
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors({"organism": "Homo sapiens"}))
    assert any(error.validator == "enum" for error in validator.iter_errors({"organism": "Unlisted organism"}))


def test_submission_schema_rejects_unlisted_organism() -> None:
    from revocompute import task_types
    from revocompute.schemas import TaskSubmissionRequest

    task_types.discover_plugins(str(ROOT / "docker" / "runners"), {"codontransformer"})
    accepted = TaskSubmissionRequest.model_validate(
        {"task_type": "codon_optimize", "params": {"organism": "Escherichia coli general"}}
    )
    assert accepted.coerce_params()["organism"] == "Escherichia coli general"
    with pytest.raises(ValidationError, match="Unlisted organism"):
        TaskSubmissionRequest.model_validate(
            {"task_type": "codon_optimize", "params": {"organism": "Unlisted organism"}}
        )
