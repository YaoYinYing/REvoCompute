# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""The PSSM-GREMLIN fit stage consumes only the Server's verified document."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

FAMILY = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("pssm_stage_inputs", FAMILY / "stage_inputs.py")
stage_inputs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stage_inputs
SPEC.loader.exec_module(stage_inputs)


def _document(tmp_path: Path, artifact: Path, sha256: str | None = None) -> Path:
    document = tmp_path / "stage_inputs.json"
    document.write_text(
        json.dumps({
            "version": 1,
            "stage": "gremlin_msa_to_lh_fit.fit",
            "inputs": {
                "alignment": {
                    "path": str(artifact),
                    "files": [{
                        "path": str(artifact),
                        "source_path": "gremlin_msa/2KL8.i90c75_aln.fas",
                        "sha256": sha256 or hashlib.sha256(artifact.read_bytes()).hexdigest(),
                        "size": artifact.stat().st_size,
                    }],
                    "producer": "gremlin_msa_to_lh_fit.msa",
                    "producer_attempt": 1,
                }
            },
        }),
        encoding="utf-8",
    )
    return document


def test_a_document_written_by_the_server_resolves_the_staged_alignment(tmp_path):
    artifact = tmp_path / "2KL8.i90c75_aln.fas"
    artifact.write_text(">2KL8\nACDEFG\n", encoding="utf-8")

    assert stage_inputs.resolve(_document(tmp_path, artifact), "alignment") == artifact


def test_a_changed_staged_alignment_is_refused(tmp_path):
    artifact = tmp_path / "2KL8.i90c75_aln.fas"
    artifact.write_text(">2KL8\nACDEFG\n", encoding="utf-8")
    document = _document(tmp_path, artifact)
    artifact.write_text(">2KL8\nACDEFH\n", encoding="utf-8")

    try:
        stage_inputs.resolve(document, "alignment")
    except stage_inputs.StageInputError as exc:
        assert "digest does not match" in str(exc)
    else:
        raise AssertionError("a changed staged alignment must not be modelled")


def test_a_document_without_the_role_is_refused(tmp_path):
    artifact = tmp_path / "2KL8.i90c75_aln.fas"
    artifact.write_text(">2KL8\nACDEFG\n", encoding="utf-8")

    try:
        stage_inputs.resolve(_document(tmp_path, artifact), "sequence")
    except stage_inputs.StageInputError as exc:
        assert "does not declare role" in str(exc)
    else:
        raise AssertionError("an undeclared role must be refused")
