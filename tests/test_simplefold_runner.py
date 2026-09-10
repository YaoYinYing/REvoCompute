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
from revocompute.task_types import discover_plugins

ROOT = Path(__file__).resolve().parents[1]
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


def test_simplefold_plugin_contract_is_restricted_gpu_and_self_contained():
    with _RegistryContext():
        discover_plugins(str(ROOT / "docker/runners"), {"simplefold"})
        task, runner = task_types.get("simplefold_predict")

        assert task.runtime.name == "simplefold"
        assert task.runtime.access_policy.id == "simplefold_research_only"
        assert task.runtime.access_policy.requires == ("simplefold_research_only",)
        assert task.gpus is True
        assert task.input_extensions == (".fasta", ".fa", ".fas")
        assert task.schema["properties"]["model"]["enum"] == ["simplefold_1.6B", "simplefold_3B"]
        assert task.schema["properties"]["num_samples"]["maximum"] == 16
        assert task.schema["additionalProperties"] is False
        assert len(task.citation_dois) == 3
        assert [mount.mode for mount in runner.mounts] == ["ro", "ro", "ro"]
        assert [mount.container_path for mount in runner.mounts] == [
            "/mnt/db/weights/simplefold",
            "/mnt/db/boltz",
            "/mnt/db/weights/esm",
        ]


def test_simplefold_result_contract_requires_structures_and_provenance():
    with _RegistryContext():
        discover_plugins(str(ROOT / "docker/runners"), {"simplefold"})
        task, _ = task_types.get("simplefold_predict")
        views = {view.id: view for view in task.result_workspace}

        assert set(views) == {"predicted_structures", "residue_confidence", "prediction_provenance"}
        structure_globs = [selector.value for selector in views["predicted_structures"].sources["candidates"]]
        assert structure_globs == ["predictions_*/*_sampled_*.cif", "predictions_*/*_sampled_*.pdb"]
        assert views["predicted_structures"].mapping["confidence_encoding"] == "plddt_bfactor"
        assert views["residue_confidence"].mapping["value_path"] == "confidenceScore"
        provenance = {selector.value for selector in views["prediction_provenance"].sources["items"]}
        assert provenance == {"run_metadata.json", "simplefold_input_manifest.json", "records/*.json"}


def test_simplefold_definition_pins_software_and_never_bakes_or_downloads_weights():
    definition = (FAMILY / "simplefold.def").read_text(encoding="utf-8")
    assets = (FAMILY / "MODEL_ASSETS.md").read_text(encoding="utf-8")
    requirements = (FAMILY / "requirements.in").read_text(encoding="utf-8")
    lock = (FAMILY / "requirements.lock").read_text(encoding="utf-8")

    assert "From: nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04" in definition
    assert "torch==2.7.1+cu126" in requirements
    assert "torch==2.7.1+cu126" in lock
    assert "torch.version.cuda == \"12.6\"" in definition
    assert "fairscale==0.4.13" in requirements
    assert "fairscale==0.4.13" in lock
    assert "requirements.lock" in definition
    assert "--require-hashes" in definition
    assert "c7a5570a6be9f5c695126e27c804e77567209934" in definition
    assert "2b369911bb5b4b0dda914521b9475cad1656b2ac" in definition
    assert "5b3e9b800441a6e0543935e31bcf52937aabd189" in definition
    assert "/mnt/db/weights" not in definition
    assert "simplefold_1.6B.ckpt" not in definition
    assert "mirror" not in definition.lower()
    for excluded in ("ipykernel", "ipyvtklink", "mediapy", "py3Dmol", "seaborn"):
        assert excluded.lower() not in requirements.lower()
    for digest in (
        "aaac2d73dcc59c61153c58a1d56e74a8ada9d6057d67000f7836f3c87325312b",
        "88d4c7a240bf3815cb35342b4ddc1128ac243a2ea0256eb8a4df1209125868b5",
        "cb32fa9cdc9e80406b793a8c09a929077534d9991a1d08f4c159d2e4ed81315f",
        "2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4",
        "7de8b4082ba15891959ab368b77ce3886697af1efb16d3c9e9e7b0c5d3f07500",
        "4da500eab246481dc9c8c95bc7b1d02f2803d761c380b0e95186d4a07d0fc84e",
    ):
        assert digest in assets


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
                "files": [{"path": str(fasta)}],
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


def test_simplefold_smoke_manifest_uses_minimal_offline_prediction():
    import yaml

    smoke = yaml.safe_load((FAMILY / "test.yaml").read_text(encoding="utf-8"))
    (case,) = smoke["collections"]["smoke"]["cases"]
    assert case["task"] == "simplefold_predict"
    assert case["parameters"] == {
        "model": "simplefold_1.6B",
        "num_steps": 2,
        "tau": 0.01,
        "num_samples": 1,
        "predict_plddt": False,
        "output_format": "mmcif",
        "seed": 7,
    }
