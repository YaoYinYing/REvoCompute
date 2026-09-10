# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

from revocompute import task_types
from revocompute.task_types import discover_plugins

ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "docker/runners/protenix"
RUNNER = FAMILY / "run.sh"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("protenix_predict", FAMILY / "predict.py")
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


def _params(**updates):
    values = {
        "num_cycles": 10,
        "diffusion_steps": 200,
        "samples_per_seed": 1,
        "seed": 101,
        "num_seeds": 1,
        "use_msa": False,
        "use_templates": False,
        "use_rna_msa": False,
        "include_atom_confidence": False,
        "use_tfg_guidance": False,
        "triangle_multiplicative_kernel": "cuequivariance",
        "triangle_attention_kernel": "cuequivariance",
        "enable_shared_cache": True,
        "enable_fusion": True,
        "enable_tf32": True,
    }
    values.update(updates)
    return values


def _write_assets(root: Path, adapter, *, templates: bool = False) -> dict:
    sources = {f"checkpoint/{adapter.MODEL_NAME}.pt": adapter.MODEL_SOURCE, **adapter.COMMON_SOURCES}
    if templates:
        sources.update(adapter.TEMPLATE_SOURCES)
    files = {}
    for index, (relative, source) in enumerate(sources.items(), start=1):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"asset-{index}".encode())
        files[relative] = {"source_url": source, "size": path.stat().st_size, "sha256": adapter.sha256(path)}
    manifest = {
        "upstream_commit": adapter.UPSTREAM_COMMIT,
        "model_name": adapter.MODEL_NAME,
        "files": files,
    }
    (root / "assets.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_protenix_plugin_owns_gpu_runtime_and_rich_structure_contract():
    with _preserve_registry():
        discover_plugins(str(ROOT / "docker/runners"), {"protenix"})
        task, runner = task_types.get("protenix_predict")

        assert task.display_name == "Protenix-v2 structure prediction"
        assert task.runtime.name == "protenix"
        assert task.gpus is True
        assert task.primary_input_extensions == (".json",)
        assert task.max_input_files == 64
        assert task.schema["additionalProperties"] is False
        assert set(task.schema["properties"]) == set(_params())
        assert task.citation_dois[0][1] == "10.64898/2026.04.10.717613"
        assert len(runner.mounts) == 1
        assert runner.mounts[0].host_path == "/mnt/db/weights/revocompute/protenix"
        assert runner.mounts[0].container_path == "/mnt/db/weights/revocompute/protenix"
        assert runner.mounts[0].mode == "ro"
        selectors = {
            selector.value
            for view in task.result_workspace
            for group in view.sources.values()
            for selector in group
        }
        assert {
            "*/*/*_sample_*.cif",
            "*/*/*_summary_confidence_sample_*.json",
            "normalized_input.json",
            "prediction.json",
        } <= selectors


def test_protenix_normalizes_only_uploaded_references_and_validates_modes(tmp_path):
    adapter = _load_adapter()
    msa = tmp_path / "query.a3m"
    msa.write_text(">query\nACDE\n", encoding="utf-8")
    ligand = tmp_path / "ligand.sdf"
    ligand.write_text("ligand\n", encoding="utf-8")
    source = tmp_path / "input.json"
    source.write_text(
        json.dumps(
            [
                {
                    "name": "protein_ligand",
                    "sequences": [
                        {
                            "proteinChain": {
                                "sequence": "acde",
                                "count": 1,
                                "unpairedMsaPath": "inputs/query.a3m",
                            }
                        },
                        {"ligand": {"ligand": "FILE_ligand.sdf", "count": 1}},
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "normalized.json"
    job = adapter.normalize_input(source, [msa, ligand], _params(use_msa=True), output)

    protein = job["sequences"][0]["proteinChain"]
    assert protein["sequence"] == "ACDE"
    assert protein["unpairedMsaPath"] == str(msa.resolve())
    assert job["sequences"][1]["ligand"]["ligand"] == f"FILE_{ligand.resolve()}"

    payload = json.loads(source.read_text(encoding="utf-8"))
    payload[0]["sequences"][0]["proteinChain"]["unpairedMsaPath"] = "https://example.test/query.a3m"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="cannot reference a URL"):
        adapter.normalize_input(source, [msa, ligand], _params(use_msa=True), output)

    source.write_text(
        json.dumps([{"name": "protein", "sequences": [{"proteinChain": {"sequence": "ACDE", "count": 1}}]}]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="use_msa requires"):
        adapter.normalize_input(source, [], _params(use_msa=True), output)


def test_protenix_resolves_duplicate_basenames_by_relative_suffix(tmp_path):
    adapter = _load_adapter()
    first = tmp_path / "uploads" / "1" / "pairing.a3m"
    second = tmp_path / "uploads" / "2" / "pairing.a3m"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text(">query\nACDE\n", encoding="utf-8")
    second.write_text(">query\nFGHI\n", encoding="utf-8")

    assert adapter._resolve_uploaded_reference("1/pairing.a3m", [first, second], "pairedMsaPath") == str(first)
    with pytest.raises(ValueError, match="ambiguous"):
        adapter._resolve_uploaded_reference("pairing.a3m", [first, second], "pairedMsaPath")
    with pytest.raises(ValueError, match="parent-directory traversal"):
        adapter._resolve_uploaded_reference("../pairing.a3m", [first], "pairedMsaPath")


def test_protenix_assets_fail_closed_and_are_content_verified(tmp_path):
    adapter = _load_adapter()
    with pytest.raises(FileNotFoundError, match="assets are incomplete"):
        adapter.validate_assets(tmp_path, False)

    manifest = _write_assets(tmp_path, adapter)
    assert adapter.validate_assets(tmp_path, False) == manifest

    checkpoint = tmp_path / f"checkpoint/{adapter.MODEL_NAME}.pt"
    checkpoint.write_bytes(b"changed")
    with pytest.raises(ValueError, match="unexpected size|failed SHA-256"):
        adapter.validate_assets(tmp_path, False)


def test_protenix_upstream_mapping_is_offline_and_deterministic(tmp_path):
    adapter = _load_adapter()
    kwargs = adapter.upstream_kwargs(
        _params(
            num_cycles=6,
            diffusion_steps=80,
            samples_per_seed=2,
            seed=17,
            num_seeds=3,
            use_templates=True,
            include_atom_confidence=True,
            use_tfg_guidance=True,
            triangle_multiplicative_kernel="torch",
            triangle_attention_kernel="triattention",
            enable_fusion=False,
        ),
        tmp_path / "input.json",
        tmp_path / "output",
    )

    assert kwargs["model_name"] == "protenix-v2"
    assert kwargs["seeds"] == [17, 18, 19]
    assert kwargs["n_cycle"] == 6
    assert kwargs["n_step"] == 80
    assert kwargs["n_sample"] == 2
    assert kwargs["use_template"] is True
    assert kwargs["need_atom_confidence"] is True
    assert kwargs["use_tfg_guidance"] is True
    assert kwargs["trimul_kernel"] == "torch"
    assert kwargs["triatt_kernel"] == "triattention"
    assert kwargs["enable_fusion"] is False
    assert "msa_server_mode" not in kwargs
    assert "seqres_database_path" not in kwargs


def test_protenix_adapter_intercepts_download_and_preprocessing_hooks(tmp_path, monkeypatch):
    adapter = _load_adapter()
    assets = tmp_path / "assets"
    asset_manifest = _write_assets(assets, adapter)
    source = tmp_path / "input.json"
    source.write_text(
        json.dumps([{"name": "Official style name", "sequences": [{"proteinChain": {"sequence": "ACDE"}}]}]),
        encoding="utf-8",
    )
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"files": [{"path": str(source)}], "params": _params()}), encoding="utf-8")
    output = tmp_path / "output"

    fake_runner = types.ModuleType("runner")
    fake_batch = types.ModuleType("runner.batch_inference")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("upstream online hook was not replaced")

    fake_batch.download_inference_cache = forbidden
    fake_batch.preprocess_input = forbidden

    def inference_jsons(**kwargs):
        assert fake_batch.download_inference_cache(object()) is None
        assert fake_batch.preprocess_input(kwargs["json_file"]) == kwargs["json_file"]
        assert kwargs["use_msa"] is False
        result = output / "Official style name" / "101"
        result.mkdir(parents=True)
        (result / "Official style name_101_sample_0.cif").write_text("data_model", encoding="utf-8")
        (result / "Official style name_101_summary_confidence_sample_0.json").write_text(
            '{"ranking_score": 0.8}', encoding="utf-8"
        )

    fake_batch.inference_jsons = inference_jsons
    fake_runner.batch_inference = fake_batch
    monkeypatch.setitem(sys.modules, "runner", fake_runner)
    monkeypatch.setitem(sys.modules, "runner.batch_inference", fake_batch)

    adapter.run(Namespace(task_manifest=task, output_dir=output, asset_root=assets))

    prediction = json.loads((output / "prediction.json").read_text(encoding="utf-8"))
    assert prediction["input"]["name"] == "Official style name"
    assert prediction["assets"] == asset_manifest
    assert prediction["artifacts"]["structures"] == [
        "Official style name/101/Official style name_101_sample_0.cif"
    ]


def test_protenix_run_wrapper_requires_complete_outputs(tmp_path):
    source = tmp_path / "input.json"
    source.write_text((ROOT / "tests/data/protenix/minimal.json").read_text(encoding="utf-8"), encoding="utf-8")
    manifest = tmp_path / "task.json"
    manifest.write_text(json.dumps({"files": [{"path": str(source)}], "params": _params()}), encoding="utf-8")
    fake = tmp_path / "fake_predict.py"
    fake.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
args = sys.argv[1:]
Path(os.environ['PROTENIX_CALL_LOG']).write_text(json.dumps(args), encoding='utf-8')
out = Path(args[args.index('--output-dir') + 1])
result = out / 'minimal_protein' / '7'
result.mkdir(parents=True, exist_ok=True)
(result / 'minimal_protein_7_sample_0.cif').write_text('data_model', encoding='utf-8')
(result / 'minimal_protein_7_summary_confidence_sample_0.json').write_text('{"ranking_score":0.8}', encoding='utf-8')
(out / 'normalized_input.json').write_text('[]', encoding='utf-8')
(out / 'prediction.json').write_text('{}', encoding='utf-8')
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    output = tmp_path / "output"
    log = tmp_path / "call.json"
    env = {
        **os.environ,
        "PROTENIX_PYTHON": "python3",
        "PROTENIX_PREDICT_SCRIPT": str(fake),
        "PROTENIX_CALL_LOG": str(log),
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
    args = json.loads(log.read_text(encoding="utf-8"))
    assert args[args.index("--task-manifest") + 1] == str(manifest)
    assert args[args.index("--output-dir") + 1] == str(output)

    failed_script = tmp_path / "fake_incomplete.py"
    failed_script.write_text(
        fake.read_text(encoding="utf-8").replace(
            "(result / 'minimal_protein_7_sample_0.cif').write_text('data_model', encoding='utf-8')",
            "pass",
        ),
        encoding="utf-8",
    )
    env["PROTENIX_PREDICT_SCRIPT"] = str(failed_script)
    missing = subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(tmp_path / "missing")],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing.returncode != 0
    assert "produced no mmCIF" in missing.stderr


def test_protenix_definition_pins_release_and_excludes_weights_and_training_tools():
    definition = (FAMILY / "protenix.def").read_text(encoding="utf-8")
    plugin = yaml.safe_load((FAMILY / "plugin.yaml").read_text(encoding="utf-8"))
    requirements = (FAMILY / "requirements.in").read_text(encoding="utf-8")

    assert "2475421477ab414b571149ad4a875c390ff8a35d" in definition
    assert "nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04" in definition
    assert "ca-certificates git kalign python3 python3-venv" in definition
    assert "command -v kalign" in definition
    assert "torch==2.7.1+cu128" in requirements
    assert "protenix-v2.pt" not in definition
    assert "HTTP_PROXY= HTTPS_PROXY=" in definition
    assert "ipywidgets" not in requirements
    assert "py3dmol" not in requirements.lower()
    assert "wandb" not in requirements
    assert "deepspeed" not in requirements
    assert plugin["runtime"]["build_inputs"] == [
        "protenix/run.sh",
        "protenix/predict.py",
        "protenix/requirements.in",
        "protenix/requirements.lock",
    ]
