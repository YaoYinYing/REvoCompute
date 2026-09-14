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
FAMILY = ROOT / "docker/runners/rfdiffusion2"
RUNNER = FAMILY / "run.sh"
FIXTURE = ROOT / "tests/data/rfdiffusion2/minimal_ori_ligand.pdb"


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


def _write_fake_inference(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
args = sys.argv[1:]
Path(os.environ['RFDIFFUSION2_CALL_LOG']).write_text(json.dumps(args), encoding='utf-8')
if os.environ.get('RFDIFFUSION2_FAKE_FAIL') == '1':
    raise SystemExit(29)
prefix = next(value.split('=', 1)[1] for value in args if value.startswith('inference.output_prefix='))
num_designs = int(next(value.split('=', 1)[1] for value in args if value.startswith('inference.num_designs=')))
for index in range(num_designs):
    if os.environ.get('RFDIFFUSION2_FAKE_NO_PDB') != '1':
        Path(f'{prefix}_{index}-atomized-bb-True.pdb').write_text('ATOM\\n', encoding='utf-8')
    Path(f'{prefix}_{index}-atomized-bb-True.trb').write_bytes(b'trb')
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _runner_env(tmp_path: Path, task_type: str, params: dict, *, ori: bool = True) -> tuple[dict[str, str], Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_root = tmp_path / "source"
    inference = source_root / "rf_diffusion/run_inference.py"
    inference.parent.mkdir(parents=True)
    _write_fake_inference(inference)
    input_path = tmp_path / "input.pdb"
    content = FIXTURE.read_text(encoding="ascii")
    if not ori:
        content = "\n".join(line for line in content.splitlines() if " ORI " not in line) + "\n"
    input_path.write_text(content, encoding="ascii")
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps({"inputs": {"structure": [{"path": str(input_path)}]}, "params": params}), encoding="utf-8"
    )
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    checkpoint = asset_root / "RFD_173.pt"
    checkpoint.write_bytes(b"checkpoint")
    asset_manifest = tmp_path / "model-assets.sha256"
    asset_manifest.write_text(f"{hashlib.sha256(b'checkpoint').hexdigest()}  RFD_173.pt\n", encoding="ascii")
    call_log = tmp_path / "call.json"
    env = {
        **os.environ,
        "TASK_TYPE": task_type,
        "RFDIFFUSION2_ASSET_ROOT": str(asset_root),
        "RFDIFFUSION2_ASSET_MANIFEST": str(asset_manifest),
        "RFDIFFUSION2_SOURCE_ROOT": str(source_root),
        "RFDIFFUSION2_INFERENCE": str(inference),
        "RFDIFFUSION2_LAUNCHER": str(FAMILY / "launch.py"),
        "RFDIFFUSION2_PYTHON": "python3",
        "RFDIFFUSION2_UPSTREAM_PYTHON": "python3",
        "RFDIFFUSION2_CALL_LOG": str(call_log),
        "MODEL_ASSET_VERIFY_SRC": str(ROOT / "docker/runners/common/verify_model_asset.sh"),
    }
    return env, manifest, call_log


def _run(env: dict[str, str], manifest: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RUNNER), "-i", str(manifest), "-o", str(output)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_motif_wrapper_maps_validated_atomic_scaffolding_parameters(tmp_path: Path) -> None:
    params = {
        "contig": "5,A1-1,5",
        "contig_atoms": "A1:N,CA,C;B2:O1,C1\r\nC3:NZ",
        "ligand": "LIG",
        "motif_placement": "unindexed",
        "num_designs": 2,
        "diffusion_steps": 7,
        "num_recycles": 2,
        "seed": 13,
        "write_trajectory": True,
    }
    env, manifest, call_log = _runner_env(tmp_path, "rfdiffusion2_motif_scaffold", params)
    output = tmp_path / "output"
    completed = _run(env, manifest, output)

    assert completed.returncode == 0, completed.stderr
    args = json.loads(call_log.read_text(encoding="utf-8"))
    assert args[0] == "--config-name=aa"
    assert "inference.ckpt_path=" + str(tmp_path / "assets/RFD_173.pt") in args
    assert "inference.num_designs=2" in args
    assert "diffuser.T=7" in args
    assert "inference.num_recycles=2" in args
    assert "inference.seed_offset=13" in args
    assert "inference.write_trajectory=True" in args
    assert "inference.contig_as_guidepost=True" in args
    assert "contigmap.contigs=[\"5,A1-1,5\"]" in args
    assert "contigmap.contig_atoms='{\"A1\":\"N,CA,C\",\"B2\":\"O1,C1\",\"C3\":\"NZ\"}'" in args
    assert "inference.idealize_sidechain_outputs=False" in args
    assert (output / "rfdiffusion2-run.json").is_file()
    assert (output / "rfdiffusion2-model-assets.sha256").is_file()
    assert (output / "task_finished").is_file()


def test_ligand_wrapper_maps_rasa_conditioning(tmp_path: Path) -> None:
    params = {
        "ligand": "LIG",
        "length": 80,
        "relative_sasa": 0.25,
        "num_designs": 1,
        "diffusion_steps": 5,
        "num_recycles": 1,
        "seed": 3,
        "write_trajectory": False,
    }
    env, manifest, call_log = _runner_env(tmp_path, "rfdiffusion2_ligand_binder", params)
    completed = _run(env, manifest, tmp_path / "output")

    assert completed.returncode == 0, completed.stderr
    args = json.loads(call_log.read_text(encoding="utf-8"))
    assert "inference.ligand='LIG'" in args
    assert 'contigmap.contigs=["80"]' in args
    assert "contigmap.length=80-80" in args
    assert "inference.contig_as_guidepost=False" in args
    assert "inference.conditions.relative_sasa_v2.active=True" in args
    assert "inference.conditions.relative_sasa_v2.rasa=0.25" in args


def test_wrapper_rejects_missing_ori_and_unsafe_contig_before_inference(tmp_path: Path) -> None:
    params = {"contig": "5,A1-1,5", "contig_atoms": "", "num_designs": 1, "diffusion_steps": 1,
              "num_recycles": 1, "seed": 0, "write_trajectory": False}
    env, manifest, call_log = _runner_env(tmp_path / "no-ori", "rfdiffusion2_motif_scaffold", params, ori=False)
    missing_ori = _run(env, manifest, tmp_path / "no-ori/output")
    assert missing_ori.returncode != 0
    assert "must contain an ORI HETATM" in missing_ori.stderr
    assert not call_log.exists()

    params["contig"] = "5,A1-1;touch /tmp/unsafe"
    env, manifest, call_log = _runner_env(tmp_path / "unsafe", "rfdiffusion2_motif_scaffold", params)
    unsafe = _run(env, manifest, tmp_path / "unsafe/output")
    assert unsafe.returncode != 0
    assert "comma-separated RFdiffusion2 contig" in unsafe.stderr
    assert not call_log.exists()


def test_motif_wrapper_rejects_malformed_and_duplicate_contig_atoms_before_inference(tmp_path: Path) -> None:
    base = {"contig": "5,A1-1,5", "num_designs": 1, "diffusion_steps": 1,
            "num_recycles": 1, "seed": 0, "write_trajectory": False}
    invalid_values = [
        ({"A1": "N,CA,C"}, "must be a string"),
        ("A1-N,CA,C", "residue:atoms syntax"),
        ("1A:N,CA,C", "chain-qualified identifiers"),
        ("A1:N, CA,C", "comma-separated atom names"),
        ("A1:N,CA;A1:C", "duplicate residue A1"),
        ("A1:N,CA;", "residue:atoms syntax"),
    ]

    for index, (contig_atoms, expected_error) in enumerate(invalid_values):
        params = {**base, "contig_atoms": contig_atoms}
        case_dir = tmp_path / str(index)
        env, manifest, call_log = _runner_env(case_dir, "rfdiffusion2_motif_scaffold", params)
        completed = _run(env, manifest, case_dir / "output")
        assert completed.returncode != 0
        assert expected_error in completed.stderr
        assert not call_log.exists()


@pytest.mark.parametrize("asset_damage", ["modified", "missing"])
def test_wrapper_fails_closed_for_asset_identity_before_inference(tmp_path: Path, asset_damage: str) -> None:
    params = {"ligand": "LIG", "length": 80, "relative_sasa": 0.0, "num_designs": 1,
              "diffusion_steps": 1, "num_recycles": 1, "seed": 0, "write_trajectory": False}
    env, manifest, call_log = _runner_env(tmp_path / "bad-asset", "rfdiffusion2_ligand_binder", params)
    checkpoint = tmp_path / "bad-asset/assets/RFD_173.pt"
    checkpoint.write_bytes(b"changed") if asset_damage == "modified" else checkpoint.unlink()
    bad_asset = _run(env, manifest, tmp_path / "bad-asset/output")
    assert bad_asset.returncode != 0
    assert "RFdiffusion2 asset" in bad_asset.stderr
    assert not call_log.exists()


def test_wrapper_fails_closed_for_cli_and_output_failures(tmp_path: Path) -> None:
    params = {"ligand": "LIG", "length": 80, "relative_sasa": 0.0, "num_designs": 1,
              "diffusion_steps": 1, "num_recycles": 1, "seed": 0, "write_trajectory": False}

    env, manifest, _ = _runner_env(tmp_path / "cli", "rfdiffusion2_ligand_binder", params)
    env["RFDIFFUSION2_FAKE_FAIL"] = "1"
    failed = _run(env, manifest, tmp_path / "cli/output")
    assert failed.returncode == 29
    assert not (tmp_path / "cli/output/task_finished").exists()

    env, manifest, _ = _runner_env(tmp_path / "no-output", "rfdiffusion2_ligand_binder", params)
    env["RFDIFFUSION2_FAKE_NO_PDB"] = "1"
    missing = _run(env, manifest, tmp_path / "no-output/output")
    assert missing.returncode != 0
    assert "produced no designed PDB structure" in missing.stderr
    assert not (tmp_path / "no-output/output/task_finished").exists()
