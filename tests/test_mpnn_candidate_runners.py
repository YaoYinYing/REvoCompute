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
import yaml
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
RUNNERS = ROOT / "docker" / "runners"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _task_context(tmp_path: Path) -> Path:
    path = tmp_path / "task_context.sh"
    path.write_text(
        'primary_input() { printf "%s\\n" "$TEST_INPUT"; }\n'
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


def test_mpnn_candidate_sources_and_environments_are_immutable():
    dynamic_def = (RUNNERS / "dynamicmpnn" / "dynamicmpnn.def").read_text(encoding="utf-8")
    frustra_def = (RUNNERS / "frustrampnn" / "frustrampnn.def").read_text(encoding="utf-8")
    fampnn_def = (RUNNERS / "fampnn" / "fampnn.def").read_text(encoding="utf-8")

    assert "af351ee737bdb2ca2804a308d9abc8fd7c303270" in dynamic_def
    assert "3a03cdc300bfe24c4bb70e60207118532bc73b3b" in frustra_def
    assert "aaf788b1502ad95d5c5a84455cfc53f2544f3b45" in fampnn_def
    assert "torch==2.9.1" in frustra_def and "whl/cpu" in frustra_def
    assert "pytorch-lightning==2.6.0" in frustra_def
    assert 'hasattr(TransferModelPL, "load_from_checkpoint")' in frustra_def
    assert "torch==2.4.1" in fampnn_def and "whl/cu121" in fampnn_def
    assert "torchvision==0.19.1" in fampnn_def
    assert 'torch.version.cuda == "12.1"' in fampnn_def
    assert "UV_HTTP_TIMEOUT=300" in fampnn_def
    assert "rm -f /etc/apt/sources.list.d/cuda*.list" in fampnn_def
    assert "mirrors." not in fampnn_def
    assert fampnn_def.count("Acquire::Retries=5") == 2
    assert fampnn_def.count('test "$attempt" -ge 10 && exit 1') == 2
    assert "build-essential" not in fampnn_def
    assert "PYTHONPATH=/opt/fampnn" in fampnn_def
    assert "%test\n    set -e" in fampnn_def
    assert "torch-geometric==2.6.1" in fampnn_def
    assert "rm -rf /opt/frustraMPNN/.git /opt/frustraMPNN/weights" in frustra_def
    assert "rm -rf /opt/fampnn/.git /opt/fampnn/weights" in fampnn_def


def test_candidate_weights_are_read_only_and_outputs_are_required():
    for family in ("frustrampnn", "fampnn"):
        runner = yaml.safe_load((RUNNERS / family / "runner.yaml").read_text(encoding="utf-8"))
        assert runner["mounts"] and all(mount["mode"] == "ro" for mount in runner["mounts"])
        expected_root = f"/mnt/db/weights/revocompute/{family}"
        assert runner["mounts"] == [
            {"host_path": expected_root, "container_path": expected_root, "mode": "ro"}
        ]

    dynamic_runner = yaml.safe_load((RUNNERS / "dynamicmpnn" / "runner.yaml").read_text(encoding="utf-8"))
    dynamic_mount = dynamic_runner["mounts"][0]
    assert dynamic_mount["host_path"] == "/mnt/db/weights/ligandmpnn"
    assert dynamic_mount["container_path"] == "/mnt/db/weights/ligandmpnn"
    assert dynamic_mount["mode"] == "ro"
    assert dynamic_runner["env"]["DYNAMICMPNN_MODEL_PARAMS"] == "/mnt/db/weights/ligandmpnn"

    dynamic_model_record = (RUNNERS / "dynamicmpnn" / "MODEL_AND_LICENSE.md").read_text(encoding="utf-8")
    assert "get_model_params.sh" in dynamic_model_record
    assert "c9cb4a671d79604111231f8dbfc7c590e06f1197453b7a6854ac6661a642f5bd" in dynamic_model_record

    assert "produced no designed sequences" in (RUNNERS / "dynamicmpnn" / "run.sh").read_text(encoding="utf-8")
    assert "produced no prediction table" in (RUNNERS / "frustrampnn" / "run.sh").read_text(encoding="utf-8")
    frustra_model_record = (RUNNERS / "frustrampnn" / "MODEL_AND_LICENSE.md").read_text(encoding="utf-8")
    assert "2c9c9c59cb684af1cd631fb745adc6106a2f69c2ab19060ee45a6aa75dde2f20" in frustra_model_record
    assert "eaee71adb7eec366fc672d2aadef87f2c51243042a4518cd897634784dc2da3b" in frustra_model_record
    assert "c9cb4a671d79604111231f8dbfc7c590e06f1197453b7a6854ac6661a642f5bd" in frustra_model_record
    fampnn_script = (RUNNERS / "fampnn" / "run.sh").read_text(encoding="utf-8")
    assert "produced no design structures" in fampnn_script
    assert "seq_only=false" in fampnn_script
    fampnn_task = yaml.safe_load(
        (RUNNERS / "fampnn" / "tasks" / "fampnn_design" / "task.yaml").read_text(encoding="utf-8")
    )
    assert "seq_only" not in fampnn_task["parameters"]["properties"]
    assert "produced no packed structures" in fampnn_script
    assert "produced no mutation score table" in fampnn_script
    assert "normalize_score_table.py" in fampnn_script
    fampnn_model_record = (RUNNERS / "fampnn" / "README.md").read_text(encoding="utf-8")
    assert "afbdfda29e6f2a1bd340971bb226638afb1bf460cfbc29f115d3b5964622c006" in fampnn_model_record
    assert "8969b3f1f3c941178076c7800952595a18b56fd3828d15bb993d3ef537938a05" in fampnn_model_record
    assert "81112a9b8d436d9baf5233a3603bac911c75b9782ced59dae5a2726316802218" in fampnn_model_record


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
    assert checkpoint in (RUNNERS / "fampnn/run.sh").read_text(encoding="utf-8")
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
    task = yaml.safe_load(
        (RUNNERS / "fampnn" / "tasks" / "fampnn_score" / "task.yaml").read_text(encoding="utf-8")
    )
    assert task["result_workspace"]["views"][0]["mapping"]["key_columns"] == ["residue"]


def test_each_candidate_task_has_smoke_coverage():
    expected = {
        "dynamicmpnn": {"dynamicmpnn"},
        "frustrampnn": {"frustrampnn"},
        "fampnn": {"fampnn_design", "fampnn_pack", "fampnn_score"},
    }
    for family, tasks in expected.items():
        smoke = yaml.safe_load((RUNNERS / family / "test.yaml").read_text(encoding="utf-8"))
        covered = {case["task"] for case in smoke["collections"]["smoke"]["cases"]}
        assert tasks <= covered


def test_dynamicmpnn_uses_upstream_batch_vocabulary():
    from revocompute import task_types
    from revocompute.schemas import TaskSubmissionRequest

    task_types.discover_plugins(str(RUNNERS), {"dynamicmpnn"})
    accepted = TaskSubmissionRequest.model_validate(
        {"task_type": "dynamicmpnn", "params": {"number_of_batches": 2, "batch_size": 3}}
    )
    assert accepted.coerce_params()["number_of_batches"] == 2
    with pytest.raises(ValidationError):
        TaskSubmissionRequest.model_validate(
            {"task_type": "dynamicmpnn", "params": {"num_seq_per_target": 6, "batch_size": 3}}
        )
