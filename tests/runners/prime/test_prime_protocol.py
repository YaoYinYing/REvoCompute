# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVER_ROOT = ROOT
PRIME_DIR = ROOT / "docker/runners/prime"

def _write_fake_prime_model(tmp_path, auto_map=True) -> Path:
    model_dir = tmp_path / "weights" / "ProPrime_650M_OGT_Prediction-91490f95c707"
    model_dir.mkdir(parents=True)
    config = {"model_type": "prime"}
    if auto_map:
        config["auto_map"] = {
            "AutoConfig": ["modeling_prime.PrimeConfig"],
            "AutoModel": ["modeling_prime.PrimeForPrediction"],
            "AutoTokenizer": ["tokenization_prime.PrimeTokenizer"],
        }
    (model_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return model_dir

def test_prime_runner_fails_closed_without_model_code_manifest(tmp_path):
    model_dir = _write_fake_prime_model(tmp_path)
    input_file = tmp_path / "input.fasta"
    input_file.write_text(">test\nACDEFGHIK\n", encoding="utf-8")
    output_dir = tmp_path / "outputs"

    manifest_path = input_file.parent / "task.json"
    manifest_path.write_text(
        json.dumps(
            {
                "params": {},
                "inputs": {"sequence": [{"path": str(input_file), "relative_path": "input.fasta", "sha256": "x"}]},
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["TASK_MANIFEST"] = str(manifest_path)
    env["TASK_CONTEXT_SRC"] = str(SERVER_ROOT / "docker" / "runners" / "common" / "task_context.sh")
    env["PRIME_MODEL_DIR"] = str(model_dir)
    env["PRIME_CODE_MANIFEST"] = str(tmp_path / "missing.sha256")
    completed = subprocess.run(
        ["bash", str(PRIME_DIR / "run.sh"), "ogt", "-i", str(manifest_path), "-o", str(output_dir)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "Pinned PRIME model-code manifest not found" in completed.stderr
    assert not (output_dir / "task_finished").exists()
def test_prime_runner_rejects_weights_manifest_mismatch(tmp_path):
    model_dir = _write_fake_prime_model(tmp_path)
    (model_dir / "weights.bin").write_bytes(b"checkpoint")
    input_file = tmp_path / "input.fasta"
    input_file.write_text(">test\nACDEFGHIK\n", encoding="utf-8")
    output_dir = tmp_path / "outputs"
    manifest = tmp_path / "model-code.sha256"
    manifest.write_text(
        "0" * 64 + "  ProPrime_650M_OGT_Prediction-91490f95c707/weights.bin\n",
        encoding="utf-8",
    )

    manifest_path = input_file.parent / "task.json"
    manifest_path.write_text(
        json.dumps(
            {
                "params": {},
                "inputs": {"sequence": [{"path": str(input_file), "relative_path": "input.fasta", "sha256": "x"}]},
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["TASK_MANIFEST"] = str(manifest_path)
    env["TASK_CONTEXT_SRC"] = str(SERVER_ROOT / "docker" / "runners" / "common" / "task_context.sh")
    env["PRIME_MODEL_DIR"] = str(model_dir)
    env["PRIME_CODE_MANIFEST"] = str(manifest)
    completed = subprocess.run(
        ["bash", str(PRIME_DIR / "run.sh"), "ogt", "-i", str(manifest_path), "-o", str(output_dir)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "model-code integrity check FAILED" in completed.stderr
    assert not (output_dir / "task_finished").exists()
