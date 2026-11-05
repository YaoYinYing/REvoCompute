# Copyright (c) 2026 The REvoDesign Developers.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

FAMILY = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("boltz2_adapter", FAMILY / "adapter.py")
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def _assets(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "assets"
    root.mkdir()
    entries = []
    for name in adapter.ASSETS:
        data = name.encode()
        (root / name).write_bytes(data)
        entries.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
    (root / "mols").mkdir()
    manifest = tmp_path / "assets.sha256"
    manifest.write_text("\n".join(entries) + "\n")
    return root, manifest


def _task(tmp_path: Path, content: str, *, affinity: bool = False) -> Path:
    source = tmp_path / "system.yaml"
    source.write_text(content)
    task = tmp_path / "task.json"
    task.write_text(json.dumps({
        "inputs": {"specification": [{"path": str(source), "relative_path": "system.yaml"}], "assets": []},
        "params": {"recycling_steps": 1, "sampling_steps": 2, "diffusion_samples": 1,
                   "preprocessing_workers": 0, "seed": 0},
    }))
    return task


def test_command_selects_boltz2_and_explicit_affinity_checkpoint(tmp_path: Path) -> None:
    args = adapter.command("boltz", tmp_path / "x.yaml", tmp_path, tmp_path / "assets",
                           {"recycling_steps": 3, "sampling_steps": 8, "diffusion_samples": 2,
                            "preprocessing_workers": 0, "seed": 9}, True)
    assert args[1:4] == ["predict", str(tmp_path / "x.yaml"), "--model"]
    assert "boltz2" in args
    assert args[args.index("--affinity_checkpoint") + 1].endswith("boltz2_aff.ckpt")
    assert "--use_msa_server" not in args
    assert "--output_format" in args and args[args.index("--output_format") + 1] == "mmcif"


def test_prepare_confines_msa_and_rejects_external_references(tmp_path: Path) -> None:
    task = _task(tmp_path, "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: ../../etc/passwd\n")
    with pytest.raises(ValueError, match="unsafe MSA reference"):
        adapter.prepare(task, tmp_path / "prepared", "boltz2_predict")


def test_prepare_requires_explicit_empty_or_supplied_msa(tmp_path: Path) -> None:
    task = _task(tmp_path, "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n")
    with pytest.raises(ValueError, match="must explicitly declare msa"):
        adapter.prepare(task, tmp_path / "prepared", "boltz2_predict")


def test_prepare_rejects_other_unconfined_file_references(tmp_path: Path) -> None:
    task = _task(
        tmp_path,
        "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: empty\ntemplates: /etc/passwd\n",
    )
    with pytest.raises(ValueError, match="unconfined file reference"):
        adapter.prepare(task, tmp_path / "prepared", "boltz2_predict")


def test_affinity_requires_ligand_binder_and_protein_target(tmp_path: Path) -> None:
    task = _task(tmp_path, "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: empty\nproperties:\n- affinity:\n    binder: A\n")
    with pytest.raises(ValueError, match="binder must identify one ligand"):
        adapter.prepare(task, tmp_path / "prepared", "boltz2_affinity")


def test_asset_digests_are_required_and_checked(tmp_path: Path) -> None:
    root, manifest = _assets(tmp_path)
    adapter.verify_assets(root, manifest)
    (root / "ccd.pkl").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest mismatch"):
        adapter.verify_assets(root, manifest)


def test_affinity_task_fails_when_upstream_omits_affinity_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, manifest = _assets(tmp_path)
    task = _task(tmp_path, "version: 1\nsequences:\n- protein:\n    id: A\n    sequence: ACDE\n    msa: empty\n- ligand:\n    id: L\n    smiles: C\nproperties:\n- affinity:\n    binder: L\n")
    cli = tmp_path / "fake-boltz"
    cli.write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
args=sys.argv
input_path=Path(args[2])
out=Path(args[args.index('--out_dir')+1])/f'boltz_results_{input_path.stem}'/'predictions'/input_path.stem
out.mkdir(parents=True)
(out/f'{input_path.stem}_model_0.cif').write_text('data_x')
(out/f'confidence_{input_path.stem}_model_0.json').write_text('{}')
""")
    cli.chmod(0o755)
    monkeypatch.setenv("TASK_TYPE", "boltz2_affinity")
    monkeypatch.setenv("BOLTZ_ASSET_ROOT", str(root))
    monkeypatch.setenv("BOLTZ_ASSET_MANIFEST", str(manifest))
    monkeypatch.setenv("BOLTZ_CLI", str(cli))
    monkeypatch.setattr(sys, "argv", ["adapter.py", "affinity", str(task), str(tmp_path / "output")])
    with pytest.raises(ValueError, match="no affinity JSON"):
        adapter.main()
