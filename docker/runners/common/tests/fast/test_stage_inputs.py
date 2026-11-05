# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
STAGE_INPUTS = ROOT / "docker" / "runners" / "common" / "runtime" / "stage_inputs.py"

SPEC = importlib.util.spec_from_file_location("common_stage_inputs", STAGE_INPUTS)
assert SPEC and SPEC.loader
stage_inputs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage_inputs)


def _file(path: Path, content: bytes, *, sha256: str | None = None, size: int | None = None) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "path": str(path),
        "sha256": sha256 or hashlib.sha256(content).hexdigest(),
        "size": len(content) if size is None else size,
    }


def _document(tmp_path: Path, role: str, files: list[dict], *, path: str | None = None) -> Path:
    document = tmp_path / "stage_inputs.json"
    document.write_text(
        json.dumps(
            {
                "version": 1,
                "stage": "model",
                "inputs": {
                    role: {
                        "path": path or (files[0]["path"] if len(files) == 1 else str(tmp_path / role)),
                        "files": files,
                        "producer": "features",
                        "producer_attempt": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return document


def test_resolve_returns_the_verified_file_of_a_one_file_role(tmp_path):
    artifact = tmp_path / "stage" / "prepared_features" / "sequence" / "features.pkl"
    document = _document(tmp_path, "prepared_features", [_file(artifact, b"FEATURES\n")])

    assert stage_inputs.resolve(document, "prepared_features") == artifact


def test_resolve_refuses_bytes_the_document_does_not_authorize(tmp_path):
    artifact = tmp_path / "stage" / "prepared_features" / "features.pkl"
    document = _document(tmp_path, "prepared_features", [_file(artifact, b"FEATURES\n")])
    artifact.write_bytes(b"TAMPERED\n")

    with pytest.raises(stage_inputs.StageInputError, match="digest does not match"):
        stage_inputs.resolve(document, "prepared_features")


def test_resolve_refuses_a_size_the_document_does_not_authorize(tmp_path):
    artifact = tmp_path / "stage" / "prepared_features" / "features.pkl"
    document = _document(tmp_path, "prepared_features", [_file(artifact, b"FEATURES\n", size=99)])

    with pytest.raises(stage_inputs.StageInputError, match="size does not match"):
        stage_inputs.resolve(document, "prepared_features")


def test_resolve_refuses_a_role_the_document_does_not_declare(tmp_path):
    artifact = tmp_path / "stage" / "prepared_features" / "features.pkl"
    document = _document(tmp_path, "prepared_features", [_file(artifact, b"FEATURES\n")])

    with pytest.raises(stage_inputs.StageInputError, match="does not declare role 'features'"):
        stage_inputs.resolve(document, "features")


def test_materialize_keeps_the_staged_layout_below_the_role_directory(tmp_path):
    artifact = tmp_path / "stage" / "prepared_features" / "test_job" / "test_job_data.json"
    document = _document(tmp_path, "prepared_features", [_file(artifact, b'{"name": "Test Job"}')])
    destination = tmp_path / "output"

    copied = stage_inputs.materialize(document, "prepared_features", destination)

    assert copied == [destination / "test_job" / "test_job_data.json"]
    assert copied[0].read_bytes() == b'{"name": "Test Job"}'


def test_materialize_flat_places_a_one_file_role_in_the_destination_directory(tmp_path):
    artifact = tmp_path / "stage" / "prepared_features" / "sequence" / "features.pkl"
    document = _document(tmp_path, "prepared_features", [_file(artifact, b"FEATURES\n")])
    destination = tmp_path / "output" / "sequence"

    copied = stage_inputs.materialize(document, "prepared_features", destination, flat=True)

    assert copied == [destination / "features.pkl"]
    assert copied[0].read_bytes() == b"FEATURES\n"


def test_materialize_refuses_a_path_that_escapes_the_role_directory(tmp_path):
    artifact = tmp_path / "features.pkl"
    document = _document(tmp_path, "prepared_features", [_file(artifact, b"FEATURES\n")])

    with pytest.raises(stage_inputs.StageInputError, match="outside the role directory"):
        stage_inputs.materialize(document, "prepared_features", tmp_path / "output")


def test_declares_distinguishes_a_reuse_role_from_an_in_graph_role(tmp_path):
    artifact = tmp_path / "stage" / "prepared_features" / "features.pkl"
    document = _document(tmp_path, "prepared_features", [_file(artifact, b"FEATURES\n")])

    assert stage_inputs.declares(document, "prepared_features") is True
    assert stage_inputs.declares(document, "features") is False


def test_cli_reports_a_missing_document_as_a_stage_input_error(tmp_path, capsys):
    assert stage_inputs.main(["resolve", str(tmp_path / "absent.json"), "prepared_features"]) == 1
    assert "cannot read stage input document" in capsys.readouterr().err
