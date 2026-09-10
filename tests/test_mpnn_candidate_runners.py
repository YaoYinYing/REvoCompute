# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNNERS = ROOT / "docker" / "runners"


def test_mpnn_candidate_sources_and_environments_are_immutable():
    mpnn_def = (RUNNERS / "mpnn" / "mpnn.def").read_text(encoding="utf-8")
    frustra_def = (RUNNERS / "frustrampnn" / "frustrampnn.def").read_text(encoding="utf-8")
    fampnn_def = (RUNNERS / "fampnn" / "fampnn.def").read_text(encoding="utf-8")

    assert "af351ee737bdb2ca2804a308d9abc8fd7c303270" in mpnn_def
    assert "3a03cdc300bfe24c4bb70e60207118532bc73b3b" in frustra_def
    assert "aaf788b1502ad95d5c5a84455cfc53f2544f3b45" in fampnn_def
    assert "torch==2.9.1" in frustra_def and "whl/cpu" in frustra_def
    assert "torch==2.4.1" in fampnn_def and "whl/cu121" in fampnn_def
    assert "torch-geometric==2.6.1" in fampnn_def
    assert "rm -rf /opt/frustraMPNN/.git /opt/frustraMPNN/weights" in frustra_def
    assert "rm -rf /opt/fampnn/.git /opt/fampnn/weights" in fampnn_def


def test_candidate_weights_are_read_only_and_outputs_are_required():
    for family in ("frustrampnn", "fampnn"):
        runner = yaml.safe_load((RUNNERS / family / "runner.yaml").read_text(encoding="utf-8"))
        assert runner["mounts"] and all(mount["mode"] == "ro" for mount in runner["mounts"])

    dynamic_runner = yaml.safe_load((RUNNERS / "mpnn" / "runner.yaml").read_text(encoding="utf-8"))
    dynamic_mount = next(
        mount for mount in dynamic_runner["mounts"] if mount["container_path"].endswith("/dynamicmpnn")
    )
    assert dynamic_mount["mode"] == "ro"

    assert "produced no designed sequences" in (RUNNERS / "mpnn" / "run.sh").read_text(encoding="utf-8")
    assert "produced no prediction table" in (RUNNERS / "frustrampnn" / "run.sh").read_text(encoding="utf-8")
    fampnn_script = (RUNNERS / "fampnn" / "run.sh").read_text(encoding="utf-8")
    assert "produced no design structures" in fampnn_script
    assert "produced no packed structures" in fampnn_script
    assert "produced no mutation score table" in fampnn_script


def test_each_candidate_task_has_smoke_coverage():
    expected = {
        "mpnn": {"dynamicmpnn"},
        "frustrampnn": {"frustrampnn"},
        "fampnn": {"fampnn_design", "fampnn_pack", "fampnn_score"},
    }
    for family, tasks in expected.items():
        smoke = yaml.safe_load((RUNNERS / family / "test.yaml").read_text(encoding="utf-8"))
        covered = {case["task"] for case in smoke["collections"]["smoke"]["cases"]}
        assert tasks <= covered
