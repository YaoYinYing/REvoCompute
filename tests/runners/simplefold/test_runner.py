# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from revocompute import task_types

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/simplefold"
RUNNER = FAMILY / "run.sh"


class _RegistryContext:
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


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (">one\nACDE\n>two\nFGHI\n", "exactly one FASTA record"),
        (">one\nACD*\n", "unsupported protein residue symbols"),
        ("ACDE\n", "precedes the FASTA header"),
        (">one\n", "contains no residues"),
        (">one\n" + "A" * 1023 + "\n", "supported maximum is 1022"),
    ],
)
def test_simplefold_fasta_validation_rejects_unsupported_inputs(tmp_path: Path, content: str, message: str):
    fasta = tmp_path / "input.fasta"
    fasta.write_text(content, encoding="utf-8")

    completed = subprocess.run(
        ["python", str(FAMILY / "validate_fasta.py"), str(fasta)], text=True, capture_output=True, check=False
    )

    assert completed.returncode == 1
    assert message in completed.stderr


def test_simplefold_fasta_validation_accepts_one_standard_sequence(tmp_path: Path):
    fasta = tmp_path / "input.fasta"
    fasta.write_text(">target\nACDEFGHIKLMNPQRSTVWYX\n", encoding="utf-8")

    completed = subprocess.run(
        ["python", str(FAMILY / "validate_fasta.py"), str(fasta)], text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "21"


def test_offline_adapter_bypasses_upstream_download_and_preserves_confidence(tmp_path: Path):
    package = tmp_path / "modules/simplefold"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "inference.py").write_text(
        """from pathlib import Path

def process_fastas(*, data, out_dir, ccd_path):
    Path(out_dir, 'ccd-used.txt').write_text(str(ccd_path), encoding='utf-8')

def download_fasta_utilities(cache):
    raise RuntimeError('network downloader was called')

class Values:
    def detach(self): return self
    def cpu(self): return self
    def tolist(self): return [81.0, 93.0]

def save_structure(structure, save_dir, outname, output_format='mmcif', plddts=None):
    suffix = '.cif' if output_format == 'mmcif' else '.pdb'
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    Path(save_dir, outname + suffix).write_text('structure', encoding='utf-8')

def predict_structures_from_fastas(args):
    download_fasta_utilities(Path(args.output_dir, 'cache'))
    process_fastas(data=[Path(args.fasta_path)], out_dir=args.output_dir, ccd_path=Path('wrong.pkl'))
    save_structure(None, Path(args.output_dir, 'predictions_' + args.simplefold_model), 'target_sampled_0',
                   output_format=args.output_format, plddts=Values())
""",
        encoding="utf-8",
    )
    fasta = tmp_path / "input.fasta"
    fasta.write_text(">target\nACDE\n", encoding="utf-8")
    ccd = tmp_path / "ccd.pkl"
    ccd.write_bytes(b"ccd")
    output = tmp_path / "output"
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "modules")}

    completed = subprocess.run(
        [
            "python",
            str(FAMILY / "offline_predict.py"),
            "--fasta-path",
            str(fasta),
            "--output-dir",
            str(output),
            "--checkpoint-dir",
            str(tmp_path),
            "--ccd-path",
            str(ccd),
            "--model",
            "simplefold_1.6B",
            "--num-steps",
            "2",
            "--tau",
            "0.01",
            "--num-samples",
            "1",
            "--output-format",
            "mmcif",
            "--seed",
            "7",
            "--plddt",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (output / "ccd-used.txt").read_text(encoding="utf-8") == str(ccd)
    confidence = json.loads((output / "confidence/target_sampled_0.json").read_text(encoding="utf-8"))
    assert confidence == {"confidenceScore": [81.0, 93.0], "meanPlddt": 87.0}


def _write_fake_predictor(path: Path) -> None:
    path.write_text(
        """import argparse
import json
from pathlib import Path
p = argparse.ArgumentParser()
for name in ('fasta_path', 'output_dir', 'checkpoint_dir', 'ccd_path', 'model', 'num_steps', 'tau',
             'num_samples', 'output_format', 'seed'):
    p.add_argument('--' + name.replace('_', '-'), required=True)
p.add_argument('--plddt', action='store_true')
a = p.parse_args()
out = Path(a.output_dir)
suffix = '.cif' if a.output_format == 'mmcif' else '.pdb'
predictions = out / ('predictions_' + a.model)
predictions.mkdir(parents=True)
for index in range(int(a.num_samples)):
    (predictions / f'target_sampled_{index}{suffix}').write_text('data_target\\n', encoding='utf-8')
    if a.plddt:
        confidence = out / 'confidence'
        confidence.mkdir(exist_ok=True)
        (confidence / f'target_sampled_{index}.json').write_text(
            json.dumps({'confidenceScore': [90.0], 'meanPlddt': 90.0}), encoding='utf-8')
(out / 'records').mkdir()
(out / 'records/target.json').write_text('{}', encoding='utf-8')
(out / 'manifest.json').write_text('{"records": []}', encoding='utf-8')
(out / 'predictor-env.json').write_text(json.dumps({
    'http_proxy': __import__('os').environ.get('HTTP_PROXY'),
    'torch_home': __import__('os').environ.get('TORCH_HOME'),
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
        "TASK_CONTEXT_SRC": str(ROOT / "docker/runners/common/task_context.sh"),
        "SIMPLEFOLD_VALIDATE": str(FAMILY / "validate_fasta.py"),
        "SIMPLEFOLD_PREDICT": str(predictor),
        "SIMPLEFOLD_FINALIZE": str(FAMILY / "finalize.py"),
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
    assert "REVODESIGN_STAGE:structure_sampling" in completed.stdout
    assert "REVODESIGN_STAGE:output_validation" in completed.stdout
    assert (output / "task_finished").is_file()
    assert (output / "predictions_simplefold_1.6B/target_sampled_0.cif").is_file()
    assert (output / "simplefold_input_manifest.json").is_file()
    assert not (output / "manifest.json").exists()
    metadata = json.loads((output / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["upstream_revision"] == "c7a5570a6be9f5c695126e27c804e77567209934"
    assert metadata["parameters"]["predict_plddt"] is True
    assert metadata["asset_sha256"]["esm2_t36_3B_UR50D.pt"] == hashlib.sha256(b"esm").hexdigest()
    predictor_env = json.loads((output / "predictor-env.json").read_text(encoding="utf-8"))
    assert predictor_env["http_proxy"] == ""
    assert predictor_env["torch_home"].endswith("/torch")
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
