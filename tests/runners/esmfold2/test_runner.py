# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/esmfold2"
RUNNER = FAMILY / "run.sh"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("esmfold2_predict", FAMILY / "predict.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_esmfold2_fasta_validation(tmp_path):
    adapter = _load_adapter()
    fasta = tmp_path / "complex.fasta"
    fasta.write_text(">A\nACDE\n>B\nFGHI\n", encoding="utf-8")

    assert adapter.read_fasta(fasta) == [("A", "ACDE"), ("B", "FGHI")]
    # A record over the service limit is rejected before any output path exists.
    fasta.write_text(">A\n" + "A" * 1025 + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="supported maximum is 1024"):
        adapter.read_fasta(fasta)

    fasta.write_text(">A\nACDZ\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported residues: Z"):
        adapter.read_fasta(fasta)

    fasta.write_text(">A\nACDE\n>A\nFGHI\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate record id"):
        adapter.read_fasta(fasta)


def test_esmfold2_a3m_query_validation(tmp_path):
    adapter = _load_adapter()
    msa = tmp_path / "input.a3m"
    msa.write_text(">query\nACdDE-F\n>homolog\nAC-DEY\n", encoding="utf-8")
    assert adapter.normalized_a3m_query(msa) == "ACDEF"
    msa.write_text(">empty\n---...\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no query sequence"):
        adapter.normalized_a3m_query(msa)


def test_esmfold2_asset_validation_fails_closed_and_checks_revisions(tmp_path):
    adapter = _load_adapter()
    with pytest.raises(FileNotFoundError, match="assets are incomplete"):
        adapter.validate_assets(tmp_path, "fast")

    (tmp_path / "fast").mkdir()
    (tmp_path / "esmc-6b").mkdir()
    for name in adapter.MODEL_REQUIRED_FILES:
        (tmp_path / "fast" / name).write_text("x", encoding="utf-8")
    for name in adapter.ESMC_REQUIRED_FILES:
        (tmp_path / "esmc-6b" / name).write_text("x", encoding="utf-8")
    (tmp_path / "ccd.pkl").write_bytes(b"x")
    (tmp_path / "assets.json").write_text(
        json.dumps(
            {
                "upstream_commit": adapter.UPSTREAM_COMMIT,
                "esmc_revision": "wrong",
                "model_revisions": adapter.MODEL_REVISIONS,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unexpected esmc_revision"):
        adapter.validate_assets(tmp_path, "fast")

    (tmp_path / "assets.json").write_text(
        json.dumps(
            {
                "upstream_commit": adapter.UPSTREAM_COMMIT,
                "esmc_revision": adapter.ESMC_REVISION,
                "model_revisions": adapter.MODEL_REVISIONS,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no file inventory"):
        adapter.validate_assets(tmp_path, "fast")


def test_esmfold2_plan_rejects_a_missing_scientific_parameter(tmp_path):
    adapter = _load_adapter()
    fasta = tmp_path / "input.fasta"
    fasta.write_text(">mini\nACDE\n", encoding="utf-8")
    manifest = {
        "inputs": {"sequence": [{"path": str(fasta)}], "alignment": []},
        "params": {"model_variant": "fast", "num_loops": 2},
    }

    with pytest.raises(adapter.InputError, match="num_diffusion_samples"):
        adapter.plan_task(manifest)


def test_esmfold2_plan_rejects_a_batch_size_it_cannot_deliver(tmp_path):
    """One work item is one chain, so only batch_size 1 describes this family."""
    adapter = _load_adapter()
    fasta = tmp_path / "input.fasta"
    fasta.write_text(">mini\nACDE\n", encoding="utf-8")
    manifest = {
        "inputs": {"sequence": [{"path": str(fasta)}], "alignment": []},
        "params": {
            "model_variant": "fast",
            "num_loops": 2,
            "num_sampling_steps": 4,
            "num_diffusion_samples": 1,
            "seed": 7,
            "lm_dropout": 0.0,
            "lm_mask_pct": 0.0,
            "msa_max_depth": 1024,
            "msa_column_mask_rate": 0.1,
            "kernel_backend": "reference",
            "include_embeddings": False,
        },
    }

    assert adapter.plan_task(manifest) is not None
    manifest["execution"] = {"batch_size": 2}
    with pytest.raises(adapter.InputError, match="batch_size must be 1, got 2"):
        adapter.plan_task(manifest)


FAKE_PREDICT = """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
calls = Path(os.environ["ESMFOLD2_CALL_LOG"])
previous = json.loads(calls.read_text()) if calls.exists() else []
previous.append(args)
calls.write_text(json.dumps(previous), encoding="utf-8")

out = Path(args[args.index("--output-dir") + 1])
out.mkdir(parents=True, exist_ok=True)
if os.environ.get("ESMFOLD2_SKIP_WORK_ITEMS") != "1":
    (out / "work_items.json").write_text(
        json.dumps({"items": [{"id": "mini", "status": "SUCCEEDED"}]}), encoding="utf-8"
    )
"""


def _wrapper_env(fake, call_log):
    return {
        **os.environ,
        "ESMFOLD2_PYTHON": "python3",
        "ESMFOLD2_PREDICT_SCRIPT": str(fake),
        "ESMFOLD2_CALL_LOG": str(call_log),
    }


def test_esmfold2_run_sh_calls_the_entrypoint_once_per_task(tmp_path):
    """The script is a thin launcher: one invocation for the whole task.

    The entrypoint reads the named roles out of the immutable ``task.json``
    itself, so the script forwards no parameter or input path.
    """
    fasta = tmp_path / "input.fasta"
    fasta.write_text(">mini\nACDE\n", encoding="utf-8")
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": {"sequence": [{"path": str(fasta)}], "alignment": []},
                "params": {"model_variant": "fast"},
                "execution": {"batch_size": 1, "max_item_attempts": 3},
            }
        ),
        encoding="utf-8",
    )
    fake = tmp_path / "fake_predict.py"
    fake.write_text(FAKE_PREDICT, encoding="utf-8")
    fake.chmod(0o755)
    call_log = tmp_path / "call.json"
    output = tmp_path / "output"

    completed = subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output)],
        env=_wrapper_env(fake, call_log),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    calls = json.loads(call_log.read_text(encoding="utf-8"))
    assert len(calls) == 1, "the entrypoint must be invoked once for the whole task"
    assert calls[0][0] == "--task-manifest"
    assert (output / "task_finished").is_file()
    assert "REVODESIGN_STAGE:esmfold2_predict" in completed.stdout


def test_esmfold2_run_sh_fails_closed_without_a_work_item_manifest(tmp_path):
    fasta = tmp_path / "input.fasta"
    fasta.write_text(">mini\nACDE\n", encoding="utf-8")
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps({"inputs": {"sequence": [{"path": str(fasta)}], "alignment": []}, "params": {"model_variant": "fast"}}),
        encoding="utf-8",
    )
    fake = tmp_path / "fake_predict.py"
    fake.write_text(FAKE_PREDICT, encoding="utf-8")
    fake.chmod(0o755)
    output = tmp_path / "output"
    env = {**_wrapper_env(fake, tmp_path / "call.json"), "ESMFOLD2_SKIP_WORK_ITEMS": "1"}

    completed = subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "no durable work-item manifest" in completed.stderr
    assert not (output / "task_finished").exists()
