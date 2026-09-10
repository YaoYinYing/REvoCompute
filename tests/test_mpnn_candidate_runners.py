# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
RUNNERS = ROOT / "docker" / "runners"


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
    fampnn_script = (RUNNERS / "fampnn" / "run.sh").read_text(encoding="utf-8")
    assert "produced no design structures" in fampnn_script
    assert "seq_only=false" in fampnn_script
    fampnn_task = yaml.safe_load(
        (RUNNERS / "fampnn" / "tasks" / "fampnn_design" / "task.yaml").read_text(encoding="utf-8")
    )
    assert "seq_only" not in fampnn_task["parameters"]["properties"]
    assert "produced no packed structures" in fampnn_script
    assert "produced no mutation score table" in fampnn_script
    fampnn_model_record = (RUNNERS / "fampnn" / "README.md").read_text(encoding="utf-8")
    assert "afbdfda29e6f2a1bd340971bb226638afb1bf460cfbc29f115d3b5964622c006" in fampnn_model_record
    assert "8969b3f1f3c941178076c7800952595a18b56fd3828d15bb993d3ef537938a05" in fampnn_model_record
    assert "81112a9b8d436d9baf5233a3603bac911c75b9782ced59dae5a2726316802218" in fampnn_model_record


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
