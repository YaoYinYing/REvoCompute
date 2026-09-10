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

from revocompute import task_types
from revocompute.task_types import discover_plugins

ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "docker/runners/esmfold2"
RUNNER = FAMILY / "run.sh"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("esmfold2_predict", FAMILY / "predict.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _preserve_registry():
    class RegistryContext:
        def __enter__(self):
            self.tasks = dict(task_types._registry)
            self.runtimes = dict(task_types._runtime_registry)
            self.categories = dict(task_types._category_registry)
            return self

        def __exit__(self, *_):
            task_types._registry.clear()
            task_types._registry.update(self.tasks)
            task_types._runtime_registry.clear()
            task_types._runtime_registry.update(self.runtimes)
            task_types._category_registry.clear()
            task_types._category_registry.update(self.categories)

    return RegistryContext()


def test_esmfold2_registry_declares_dedicated_gpu_runtime_and_outputs():
    with _preserve_registry():
        discover_plugins(str(ROOT / "docker/runners"), {"esmfold2"})
        task, runner = task_types.get("esmfold2_predict")

        assert task.runtime.name == "esmfold2"
        assert task.gpus is True
        assert task.input_extensions == (".fasta", ".fa", ".faa", ".a3m")
        assert task.primary_input_extensions == (".fasta", ".fa", ".faa")
        assert task.max_input_files == 2
        assert [mount.mode for mount in runner.mounts] == ["ro"]
        assert runner.mounts[0].host_path == "/mnt/db/weights/revocompute/esmfold2"
        assert task.schema["properties"]["model_variant"]["enum"] == ["fast", "standard"]
        selectors = {
            selector.value
            for view in task.result_workspace
            for group in view.sources.values()
            for selector in group
        }
        assert {
            "sample_*.cif",
            "sample_*_confidence.json",
            "sample_*_plddt.csv",
            "sample_*_pae.json",
            "prediction.json",
        } <= selectors


def test_esmfold2_fasta_and_manifest_validation(tmp_path):
    adapter = _load_adapter()
    fasta = tmp_path / "complex.fasta"
    fasta.write_text(">A\nACDE\n>B\nFGHI\n", encoding="utf-8")
    manifest = tmp_path / "task.json"
    manifest.write_text(json.dumps({"files": [{"path": str(fasta)}]}), encoding="utf-8")

    assert adapter.read_fasta(fasta) == [("A", "ACDE"), ("B", "FGHI")]
    assert adapter.task_inputs(manifest) == (fasta, None)

    fasta.write_text(">A\nACDZ\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported residues: Z"):
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


def test_esmfold2_wrapper_forwards_parameters_and_requires_artifacts(tmp_path):
    fasta = tmp_path / "input.fasta"
    fasta.write_text(">mini\nACDE\n", encoding="utf-8")
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [{"path": str(fasta)}],
                "params": {
                    "model_variant": "fast",
                    "num_loops": 2,
                    "num_sampling_steps": 4,
                    "num_diffusion_samples": 1,
                    "seed": 7,
                    "lm_dropout": 0.1,
                    "lm_mask_pct": 0.05,
                    "msa_max_depth": 32,
                    "msa_column_mask_rate": 0.2,
                    "kernel_backend": "reference",
                    "include_embeddings": True,
                },
            }
        ),
        encoding="utf-8",
    )
    fake = tmp_path / "fake_predict.py"
    fake.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
args = sys.argv[1:]
Path(os.environ['ESMFOLD2_CALL_LOG']).write_text(json.dumps(args), encoding='utf-8')
out = Path(args[args.index('--output-dir') + 1])
out.mkdir(parents=True, exist_ok=True)
(out / 'prediction.json').write_text('{}', encoding='utf-8')
(out / 'sample_001.cif').write_text('data_sample', encoding='utf-8')
(out / 'sample_001_confidence.json').write_text('{\"mean_plddt\":0.5}', encoding='utf-8')
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    call_log = tmp_path / "call.json"
    output = tmp_path / "output"
    env = {
        **os.environ,
        "TASK_MANIFEST": str(manifest),
        "TASK_CONTEXT_SRC": str(ROOT / "docker/runners/common/task_context.sh"),
        "ESMFOLD2_PYTHON": "python3",
        "ESMFOLD2_PREDICT_SCRIPT": str(fake),
        "ESMFOLD2_CALL_LOG": str(call_log),
    }
    completed = subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert (output / "task_finished").is_file()
    args = json.loads(call_log.read_text(encoding="utf-8"))
    assert args[args.index("--model-variant") + 1] == "fast"
    assert args[args.index("--num-sampling-steps") + 1] == "4"
    assert args[args.index("--kernel-backend") + 1] == "reference"
    assert "--include-embeddings" in args


def test_esmfold2_definition_is_pinned_direct_and_weight_free():
    definition = (FAMILY / "esmfold2.def").read_text(encoding="utf-8")
    plugin = (FAMILY / "plugin.yaml").read_text(encoding="utf-8")
    lock = (FAMILY / "requirements.lock").read_text(encoding="utf-8")

    assert "bf343ba264b650dff7a073643725f9aaa1fdbe8d" in definition
    assert "nvidia/cuda:13.0.2-cudnn-runtime-ubuntu24.04" in definition
    assert "torch==2.11.0+cu130" in lock
    assert "requirements.lock" in plugin
    assert "model.safetensors /" not in definition
    assert "HF_HUB_OFFLINE=1" in definition
