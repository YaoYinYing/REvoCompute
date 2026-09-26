# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""SimpleFold runner contract: FASTA record normalization and run.sh wiring.

The offline asset plumbing (fail-closed verification, scratch cache, pinned
environment) stays in ``run.sh`` and is exercised here with a stand-in
predictor; the record-level normalization that used to live in
``validate_fasta.py`` moved into ``work_items`` and is tested at the live path
rather than through a script the runner no longer calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/simplefold"
RUNNER = FAMILY / "run.sh"
COMMON = ROOT / "docker/runners/common"

for _path in (str(COMMON), str(FAMILY)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from work_items import InputError, read_fasta_records, sequence_work_items  # noqa: E402

MAX_RESIDUES = 1022


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (">one\nACD*\n", "unsupported residues"),
        ("ACDE\n", "precedes the first FASTA header"),
        (">one\n", "contains no residues"),
        (">\nACDE\n", "is empty"),
        (">one\n" + "A" * 1023 + "\n", "supported maximum is 1022"),
    ],
)
def test_simplefold_record_normalization_rejects_unsupported_inputs(tmp_path: Path, content: str, message: str):
    fasta = tmp_path / "input.fasta"
    fasta.write_text(content, encoding="utf-8")
    manifest = {"inputs": {"sequence": [{"path": str(fasta)}]}, "params": {}}

    with pytest.raises(InputError, match=message):
        sequence_work_items(manifest, "sequence", max_length=MAX_RESIDUES)


def test_simplefold_record_normalization_accepts_many_records(tmp_path: Path):
    fasta = tmp_path / "input.fasta"
    fasta.write_text(">target\nACDEFGHIKLMNPQRSTVWYX\n>second\nMXX\n", encoding="utf-8")

    assert read_fasta_records(fasta) == [("target", "ACDEFGHIKLMNPQRSTVWYX"), ("second", "MXX")]


def test_offline_patches_bypass_the_downloader_and_preserve_confidence(tmp_path: Path):
    """The plugin installs its patches on the upstream module it is handed."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "fake_modules"))
    try:
        from simplefold import inference

        simplefold_plugin = _load_plugin_module()
        simplefold_plugin._install_offline_patches(inference)
        assert inference.download_fasta_utilities(tmp_path) is None, "the downloader must be a no-op"
        structures = tmp_path / "predictions_simplefold_1.6B"
        inference.save_structure(
            {"id": "target"}, structures, "target_sampled_0", output_format="mmcif", plddts=inference.PerResiduePlddt([81.0, 93.0])
        )
        assert (structures / "target_sampled_0.cif").is_file()
        confidence = json.loads((tmp_path / "confidence" / "target_sampled_0.json").read_text(encoding="utf-8"))
        assert confidence == {"confidenceScore": [81.0, 93.0], "meanPlddt": 87.0}
    finally:
        sys.path.remove(str(Path(__file__).resolve().parent / "fake_modules"))


def _load_plugin_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("simplefold_plugin_patch_test", FAMILY / "offline_predict.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_fake_predictor(path: Path) -> None:
    """A stand-in for the persistent entrypoint, recording its environment."""
    path.write_text(
        """import argparse
import json
import os
from pathlib import Path
p = argparse.ArgumentParser()
for name in ('task_manifest', 'output_dir', 'checkpoint_dir', 'ccd_path', 'esm_model_sha256', 'esm_regression_sha256'):
    p.add_argument('--' + name.replace('_', '-'), required=True)
a = p.parse_args()
out = Path(a.output_dir)
manifest = json.loads(Path(a.task_manifest).read_text())
params = manifest['params']
item = out / 'target'
predictions = item / ('predictions_' + params['model'])
predictions.mkdir(parents=True)
suffix = '.cif' if params['output_format'] == 'mmcif' else '.pdb'
for index in range(int(params['num_samples'])):
    (predictions / f'target_sampled_{index}{suffix}').write_text('data_target\\n', encoding='utf-8')
    if params['predict_plddt']:
        confidence = item / 'confidence'
        confidence.mkdir(exist_ok=True)
        (confidence / f'target_sampled_{index}.json').write_text(
            json.dumps({'confidenceScore': [90.0], 'meanPlddt': 90.0}), encoding='utf-8')
(item / 'records').mkdir()
(item / 'records/target.json').write_text('{}', encoding='utf-8')
(item / 'simplefold_input_manifest.json').write_text('{"records": []}', encoding='utf-8')
(item / 'run_metadata.json').write_text('{}', encoding='utf-8')
(out / 'work_items.json').write_text(json.dumps({'items': [{'id': 'target', 'status': 'SUCCEEDED'}]}), encoding='utf-8')
(out / 'predictor-env.json').write_text(json.dumps({
    'http_proxy': os.environ.get('HTTP_PROXY'),
    'torch_home': os.environ.get('TORCH_HOME'),
    'ccd_path': a.ccd_path,
    'esm_model_sha256': a.esm_model_sha256,
}), encoding='utf-8')
""",
        encoding="utf-8",
    )


def _runner_fixture(tmp_path: Path, *, plddt: bool = True) -> tuple[dict[str, str], Path, Path]:
    weights = tmp_path / "weights"
    weights.mkdir()
    for name in ("simplefold_1.6B.ckpt", "simplefold_3B.ckpt", "plddt.ckpt"):
        (weights / name).write_bytes(b"weights")
    boltz = tmp_path / "boltz"
    boltz.mkdir()
    (boltz / "ccd.pkl").write_bytes(b"ccd")
    esm = tmp_path / "esm"
    esm.mkdir()
    (esm / "esm2_t36_3B_UR50D.pt").write_bytes(b"esm")
    (esm / "esm2_t36_3B_UR50D-contact-regression.pt").write_bytes(b"regression")
    hub = tmp_path / "esm-hub"
    hub.mkdir()
    (hub / "hubconf.py").write_text("# pinned ESM hub\n", encoding="utf-8")
    fasta = tmp_path / "input.fasta"
    fasta.write_text(">target\nACDEFGHIK\n", encoding="utf-8")
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": {"sequence": [{"path": str(fasta)}]},
                "params": {
                    "model": "simplefold_1.6B",
                    "num_steps": 2,
                    "tau": 0.01,
                    "num_samples": 1,
                    "predict_plddt": plddt,
                    "output_format": "mmcif",
                    "seed": 7,
                },
            }
        ),
        encoding="utf-8",
    )
    predictor = tmp_path / "fake_predict.py"
    _write_fake_predictor(predictor)
    env = {
        **os.environ,
        "TASK_MANIFEST": str(manifest),
        "TASK_CONTEXT_SRC": str(COMMON / "task_context.sh"),
        "SIMPLEFOLD_PREDICT": str(predictor),
        "SIMPLEFOLD_WEIGHT_DIR": str(weights),
        "SIMPLEFOLD_CCD_PATH": str(boltz / "ccd.pkl"),
        "SIMPLEFOLD_ESM_WEIGHT_DIR": str(esm),
        "SIMPLEFOLD_ESM_HUB_SOURCE": str(hub),
        "SIMPLEFOLD_16B_SHA256": hashlib.sha256(b"weights").hexdigest(),
        "SIMPLEFOLD_3B_SHA256": hashlib.sha256(b"weights").hexdigest(),
        "SIMPLEFOLD_PLDDT_SHA256": hashlib.sha256(b"weights").hexdigest(),
        "SIMPLEFOLD_CCD_SHA256": hashlib.sha256(b"ccd").hexdigest(),
        "SIMPLEFOLD_ESM_MODEL_SHA256": hashlib.sha256(b"esm").hexdigest(),
        "SIMPLEFOLD_ESM_REGRESSION_SHA256": hashlib.sha256(b"regression").hexdigest(),
    }
    return env, manifest, weights


def test_simplefold_runner_wires_offline_assets_and_emits_complete_artifacts(tmp_path: Path):
    env, manifest, _ = _runner_fixture(tmp_path)
    output = tmp_path / "result"

    completed = subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "REVODESIGN_STAGE:input_validation" in completed.stdout
    assert (output / "task_finished").is_file()
    assert (output / "work_items.json").is_file()
    assert (output / "target/predictions_simplefold_1.6B/target_sampled_0.cif").is_file()
    assert (output / "target/simplefold_input_manifest.json").is_file()
    assert (output / "target/run_metadata.json").is_file()
    assert not (output / "manifest.json").exists()
    predictor_env = json.loads((output / "predictor-env.json").read_text(encoding="utf-8"))
    assert predictor_env["http_proxy"] == ""
    assert predictor_env["torch_home"].endswith("/torch")
    assert predictor_env["esm_model_sha256"] == hashlib.sha256(b"esm").hexdigest()
    assert not Path(predictor_env["torch_home"]).exists()


def test_simplefold_runner_fails_closed_before_inference_when_an_asset_is_missing(tmp_path: Path):
    env, manifest, weights = _runner_fixture(tmp_path)
    (weights / "plddt.ckpt").unlink()
    output = tmp_path / "result"

    completed = subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "Missing SimpleFold pLDDT checkpoint" in completed.stderr
    assert not output.exists()


def test_simplefold_runner_rejects_a_tampered_model_asset(tmp_path: Path):
    env, manifest, weights = _runner_fixture(tmp_path)
    (weights / "simplefold_1.6B.ckpt").write_bytes(b"tampered")
    output = tmp_path / "result"

    completed = subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "Unexpected model asset fingerprint" in completed.stderr
    assert not output.exists()


def test_simplefold_declared_fallback_plans_are_resource_only():
    """Every plan the owning manifest declares must survive the server's parser."""
    import yaml

    from revocompute.resource_model import ADAPTATION_KEYS, FallbackPlan

    task = yaml.safe_load((FAMILY / "tasks/simplefold_predict/task.yaml").read_text(encoding="utf-8"))
    adaptation = task["resource_adaptation"]
    assert adaptation["stage"] in {"observe", "recover", "avoid"}
    plans = FallbackPlan.parse_all(adaptation["fallback_plans"])
    assert plans, "SimpleFold must declare at least one fallback plan"
    assert all(plan.title for plan in plans), "each plan must carry a user-facing title"
    for plan in plans:
        assert set(plan.adjustments) <= ADAPTATION_KEYS
        assert "num_samples" in task["parameters"]["properties"]
        assert task["parameters"]["properties"]["num_samples"]["default"] == 1
