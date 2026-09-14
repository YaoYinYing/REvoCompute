# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import csv
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
RUNNERS = ROOT / "docker" / "runners"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _task_context(tmp_path: Path) -> Path:
    path = tmp_path / "task_context.sh"
    path.write_text(
        'primary_input() { printf "%s\\n" "$TEST_INPUT"; }\n'
        'task_input() { printf "%s\\n" "$TEST_INPUT"; }\n'
        '_parse_param() { if [ "$1" = checkpoint ]; then printf "%s\\n" "$TEST_CHECKPOINT"; '
        'else printf "1\\n"; fi; }\n',
        encoding="utf-8",
    )
    return path


def _asset_manifest(path: Path, assets: dict[str, bytes]) -> None:
    path.write_text("".join(f"{_digest(data)}  {name}\n" for name, data in assets.items()), encoding="ascii")
    for name, data in assets.items():
        target = path.parent / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


@pytest.mark.parametrize(
    ("task_type", "checkpoint"),
    [
        ("fampnn_design", "fampnn_0_3.pt"),
        ("fampnn_pack", "fampnn_0_0.pt"),
        ("fampnn_score", "fampnn_0_3_cath.pt"),
    ],
)
def test_fampnn_executes_only_after_selected_checkpoint_identity_passes(tmp_path, task_type, checkpoint):
    assets = {"fampnn_0_0.pt": b"pack", "fampnn_0_3.pt": b"design", "fampnn_0_3_cath.pt": b"score"}
    asset_root = tmp_path / "assets"
    manifest = asset_root / "model-assets.sha256"
    asset_root.mkdir()
    _asset_manifest(manifest, assets)
    input_path = tmp_path / "input.pdb"
    input_path.write_text("ATOM\n", encoding="ascii")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python3"
    fake_python.write_text(
        "#!/bin/bash\nset -e\necho called >> \"$MODEL_CALL_LOG\"\n"
        "for arg in \"$@\"; do case \"$arg\" in out_dir=*) out=${arg#out_dir=};; esac; done\n"
        "case \"$*\" in *seq_design.py*) mkdir -p \"$out/samples\" \"$out/fastas\"; echo ATOM > \"$out/samples/a.pdb\"; echo '>a' > \"$out/fastas/a.fasta\";;"
        " *pack.py*) mkdir -p \"$out/samples\"; echo ATOM > \"$out/samples/a.pdb\";;"
        " *score_all_muts.py*) echo 'residue,A' > \"$out/all_scores.csv\";; esac\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    output = tmp_path / "output"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TASK_TYPE": task_type,
        "TASK_CONTEXT_SRC": str(_task_context(tmp_path)),
        "TEST_INPUT": str(input_path),
        "FAMPNN_PATH": str(tmp_path),
        "FAMPNN_WEIGHT_DIR": str(asset_root),
        "FAMPNN_ASSET_MANIFEST": str(manifest),
        "MODEL_ASSET_VERIFY_SRC": str(RUNNERS / "common/verify_model_asset.sh"),
        "MODEL_CALL_LOG": str(tmp_path / "calls"),
    }

    completed = subprocess.run(
        ["bash", str(RUNNERS / "fampnn/run.sh"), "-i", str(input_path), "-o", str(output)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "calls").is_file()


@pytest.mark.parametrize("damage", ["modified", "missing", "swapped"])
def test_fampnn_rejects_bad_checkpoint_before_inference(tmp_path, damage):
    assets = {"fampnn_0_0.pt": b"pack", "fampnn_0_3.pt": b"design", "fampnn_0_3_cath.pt": b"score"}
    asset_root = tmp_path / "assets"
    manifest = asset_root / "model-assets.sha256"
    asset_root.mkdir()
    _asset_manifest(manifest, assets)
    if damage == "modified":
        (asset_root / "fampnn_0_3.pt").write_bytes(b"changed")
    elif damage == "missing":
        (asset_root / "fampnn_0_3.pt").unlink()
    else:
        first, second = asset_root / "fampnn_0_0.pt", asset_root / "fampnn_0_3.pt"
        first.write_bytes(b"design")
        second.write_bytes(b"pack")
    input_path = tmp_path / "input.pdb"
    input_path.write_text("ATOM\n", encoding="ascii")
    call_log = tmp_path / "calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "frustrampnn"
    fake.write_text('#!/bin/bash\ntouch "$MODEL_CALL_LOG"\n', encoding="utf-8")
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TASK_TYPE": "fampnn_design",
        "TASK_CONTEXT_SRC": str(_task_context(tmp_path)),
        "TEST_INPUT": str(input_path),
        "FAMPNN_PATH": str(tmp_path),
        "FAMPNN_WEIGHT_DIR": str(asset_root),
        "FAMPNN_ASSET_MANIFEST": str(manifest),
        "MODEL_ASSET_VERIFY_SRC": str(RUNNERS / "common/verify_model_asset.sh"),
        "MODEL_CALL_LOG": str(call_log),
    }

    completed = subprocess.run(
        ["bash", str(RUNNERS / "fampnn/run.sh"), "-i", str(input_path), "-o", str(tmp_path / "out")],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert not call_log.exists()


@pytest.mark.parametrize("selected", ["fireprot", "megascale"])
def test_frustrampnn_verifies_selected_checkpoint_and_backbone_before_inference(tmp_path, selected):
    assets = {
        "fireprot_train_weights.ckpt": b"fireprot",
        "megascale_train_weights.ckpt": b"megascale",
        "vanilla_model_weights/v_48_020.pt": b"backbone",
    }
    asset_root = tmp_path / "assets"
    manifest = asset_root / "model-assets.sha256"
    asset_root.mkdir()
    _asset_manifest(manifest, assets)
    input_path = tmp_path / "input.pdb"
    input_path.write_text("ATOM\n", encoding="ascii")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "frustrampnn"
    fake.write_text(
        '#!/bin/bash\necho called > "$MODEL_CALL_LOG"\nwhile [ "$1" != --output ]; do shift; done\n'
        'shift; printf "score\\n1\\n" > "$1"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    call_log = tmp_path / "calls"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TASK_TYPE": "frustrampnn",
        "TASK_CONTEXT_SRC": str(_task_context(tmp_path)),
        "TEST_INPUT": str(input_path),
        "TEST_CHECKPOINT": selected,
        "FRUSTRAMPNN_WEIGHT_DIR": str(asset_root),
        "FRUSTRAMPNN_ASSET_MANIFEST": str(manifest),
        "MODEL_ASSET_VERIFY_SRC": str(RUNNERS / "common/verify_model_asset.sh"),
        "MODEL_CALL_LOG": str(call_log),
    }

    completed = subprocess.run(
        ["bash", str(RUNNERS / "frustrampnn/run.sh"), "-i", str(input_path), "-o", str(tmp_path / "out")],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert call_log.is_file()


@pytest.mark.parametrize("damage", ["modified", "missing", "swapped", "backbone"])
def test_frustrampnn_rejects_bad_model_identity_before_inference(tmp_path, damage):
    assets = {
        "fireprot_train_weights.ckpt": b"fireprot",
        "megascale_train_weights.ckpt": b"megascale",
        "vanilla_model_weights/v_48_020.pt": b"backbone",
    }
    asset_root = tmp_path / "assets"
    manifest = asset_root / "model-assets.sha256"
    asset_root.mkdir()
    _asset_manifest(manifest, assets)
    target = asset_root / "fireprot_train_weights.ckpt"
    if damage == "modified":
        target.write_bytes(b"changed")
    elif damage == "missing":
        target.unlink()
    elif damage == "swapped":
        target.write_bytes(b"megascale")
        (asset_root / "megascale_train_weights.ckpt").write_bytes(b"fireprot")
    else:
        (asset_root / "vanilla_model_weights/v_48_020.pt").write_bytes(b"changed")
    input_path = tmp_path / "input.pdb"
    input_path.write_text("ATOM\n", encoding="ascii")
    call_log = tmp_path / "calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "frustrampnn"
    fake.write_text('#!/bin/bash\ntouch "$MODEL_CALL_LOG"\n', encoding="utf-8")
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TASK_TYPE": "frustrampnn",
        "TASK_CONTEXT_SRC": str(_task_context(tmp_path)),
        "TEST_INPUT": str(input_path),
        "TEST_CHECKPOINT": "fireprot",
        "FRUSTRAMPNN_WEIGHT_DIR": str(asset_root),
        "FRUSTRAMPNN_ASSET_MANIFEST": str(manifest),
        "MODEL_ASSET_VERIFY_SRC": str(RUNNERS / "common/verify_model_asset.sh"),
        "MODEL_CALL_LOG": str(call_log),
    }

    completed = subprocess.run(
        ["bash", str(RUNNERS / "frustrampnn/run.sh"), "-i", str(input_path), "-o", str(tmp_path / "out")],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert not call_log.exists()


def test_fampnn_score_table_names_the_upstream_residue_index(tmp_path: Path):
    table = tmp_path / "all_scores.csv"
    table.write_text(",A,R\n1M,-5.4,-5.9\n", encoding="utf-8")

    subprocess.run(
        [sys.executable, str(RUNNERS / "fampnn" / "normalize_score_table.py"), str(table)],
        check=True,
    )

    with table.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [["residue", "A", "R"], ["1M", "-5.4", "-5.9"]]
