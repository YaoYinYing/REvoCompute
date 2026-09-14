# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
ADAPTER_PATH = ROOT / "docker" / "runners" / "codontransformer" / "predict.py"
SPEC = importlib.util.spec_from_file_location("codontransformer_adapter", ADAPTER_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def test_read_single_fasta_normalizes_one_protein(tmp_path: Path) -> None:
    fasta = tmp_path / "protein.fasta"
    fasta.write_text(">example\nmww\nmw*\n", encoding="utf-8")
    assert adapter.read_single_fasta(fasta) == ("example", "MWWMW")


def test_read_single_fasta_rejects_sequence_that_upstream_would_truncate(tmp_path: Path) -> None:
    fasta = tmp_path / "too-long.fasta"
    fasta.write_text(">example\n" + "M" * 2047 + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="2046-residue"):
        adapter.read_single_fasta(fasta)


@pytest.mark.parametrize("sequence", ["MW*MW", "MW_MW"])
def test_read_single_fasta_rejects_internal_stop_markers(tmp_path: Path, sequence: str) -> None:
    fasta = tmp_path / "internal-stop.fasta"
    fasta.write_text(f">example\n{sequence}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="internal stop marker"):
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


def test_validate_model_dir_enforces_every_snapshot_fingerprint(tmp_path: Path) -> None:
    manifest = tmp_path / "model-assets.sha256"
    model = tmp_path / "model"
    model.mkdir()
    entries = []
    for name in adapter.MODEL_FILES:
        content = name.encode()
        (model / name).write_bytes(content)
        entries.append(f"{hashlib.sha256(content).hexdigest()}  {name}\n")
    manifest.write_text("".join(entries), encoding="ascii")

    adapter.validate_model_dir(model, manifest)
    (model / "model.safetensors").write_bytes(b"changed")
    with pytest.raises(ValueError, match="model.safetensors"):
        adapter.validate_model_dir(model, manifest)


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
