# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
"""Produced-artifact consumption for a composed GREMLIN_LH stage.

The Server writes a digest-bound stage input document after it verifies the
producer's artifact. These tests cover the Runner's own resolution rule and the
``run.sh`` path that uses it, with the real fitting code on a tiny fixture.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.runner_contract

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "docker" / "runner_testkit"))
from runner_protocol import run_with_manifest

FAMILY = ROOT / "docker" / "runners" / "gremlin_lh"
RUN_SCRIPT = FAMILY / "run.sh"
STAGE_INPUTS = FAMILY / "stage_inputs.py"
FIXTURE = ROOT / "tests" / "data" / "msa" / "gremlin_lh_tiny.a3m"

SPEC = importlib.util.spec_from_file_location("gremlin_lh_stage_inputs", STAGE_INPUTS)
assert SPEC and SPEC.loader
stage_inputs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage_inputs)

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


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _document(tmp_path: Path, artifact: Path, sha256: str | None = None, role: str = "alignment") -> Path:
    document = tmp_path / "stage_inputs.json"
    document.write_text(
        json.dumps(
            {
                "version": 1,
                "stage": "pssm_msa_to_lh.fit",
                "inputs": {
                    role: {
                        "path": str(artifact),
                        "sha256": sha256 or _digest(artifact),
                        "size": artifact.stat().st_size,
                        "producer": "gremlin.msa",
                        "producer_attempt": 1,
                        "source_path": "gremlin_msa/2KL8.i90c75_aln.fas",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return document


def _runner_env(tmp_path: Path, document: Path | None = None) -> dict[str, str]:
    mplconfig = tmp_path / "mplconfig"
    mplconfig.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "TASK_TYPE": "pssm_msa_to_lh-fit",
        "GREMLIN_LH_PYTHON": sys.executable,
        "GREMLIN_LH_FIT_MODEL": str(FAMILY / "fit_model.py"),
        "MPLCONFIGDIR": str(mplconfig),
    }
    if document is not None:
        env["TASK_STAGE_INPUTS"] = str(document)
    return env


# ── Runner-owned resolution logic ─────────────────────────────────────────────


def test_resolve_returns_the_digest_verified_path(tmp_path: Path) -> None:
    artifact = tmp_path / "alignment.a3m"
    artifact.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    assert stage_inputs.resolve(_document(tmp_path, artifact), "alignment") == artifact


def test_resolve_rejects_a_changed_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "alignment.a3m"
    artifact.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    document = _document(tmp_path, artifact, sha256="0" * 64)
    with pytest.raises(stage_inputs.StageInputError, match="digest does not match"):
        stage_inputs.resolve(document, "alignment")


def test_resolve_rejects_a_role_the_document_does_not_declare(tmp_path: Path) -> None:
    artifact = tmp_path / "alignment.a3m"
    artifact.write_text(">q\nACDE\n>h\nACDE\n", encoding="utf-8")
    document = _document(tmp_path, artifact)
    with pytest.raises(stage_inputs.StageInputError, match="does not declare role"):
        stage_inputs.resolve(document, "sequence")


def test_resolve_rejects_a_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.a3m"
    real.write_text(">q\nACDE\n>h\nACDE\n", encoding="utf-8")
    link = tmp_path / "link.a3m"
    link.symlink_to(real)
    document = _document(tmp_path, link)
    with pytest.raises(stage_inputs.StageInputError, match="not a regular file"):
        stage_inputs.resolve(document, "alignment")


def test_cli_reports_an_unverified_document(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    artifact = tmp_path / "alignment.a3m"
    artifact.write_text(">q\nACDE\n>h\nACDE\n", encoding="utf-8")
    document = _document(tmp_path, artifact, sha256="f" * 64)
    assert stage_inputs.main(["resolve", str(document), "alignment"]) == 1
    assert "digest does not match" in capsys.readouterr().err


# ── run.sh consumes the declared stage input ─────────────────────────────────


def test_run_sh_uses_the_stage_input_instead_of_the_task_manifest(tmp_path: Path) -> None:
    artifact = tmp_path / "produced.a3m"
    artifact.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    document = _document(tmp_path, artifact)
    # The manifest's own role is malformed, so a fallback to task.json would fail.
    malformed = tmp_path / "manifest-input.a3m"
    malformed.write_text("ACDE\n", encoding="utf-8")
    output = tmp_path / "output"
    completed = run_with_manifest(
        RUN_SCRIPT, malformed, output, _runner_env(tmp_path, document), params=RUN_PARAMETERS, role="alignment"
    )
    assert completed.returncode == 0, completed.stderr
    assert (output / "summary.json").is_file()
    assert (output / "task_finished").is_file()


def test_run_sh_fails_closed_on_a_changed_stage_input(tmp_path: Path) -> None:
    artifact = tmp_path / "produced.a3m"
    artifact.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    document = _document(tmp_path, artifact, sha256="0" * 64)
    output = tmp_path / "output"
    completed = run_with_manifest(
        RUN_SCRIPT, artifact, output, _runner_env(tmp_path, document), params=RUN_PARAMETERS, role="alignment"
    )
    assert completed.returncode != 0
    assert "digest does not match" in completed.stderr
    assert not (output / "summary.json").exists()
    assert not (output / "task_finished").exists()
