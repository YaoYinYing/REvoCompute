# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Foundry result-contract regression: RF3 and the design Tasks own separate trees.

Live-test acceptance, 2026-11-03 target-host Slurm/Apptainer run at the active
SIF identity (job 9fb09b17099667a85d5f8800884600a8, SIF fd78dcfd2b00), observed:

    minimal_rf3/seed-0_sample-0/minimal_rf3_seed-0_sample-0_model.cif

RF3's primary structure is conditional: ``run.sh`` accepts a structure or
early-stopping ranking metrics, and the storyboard renders the metrics-only
outcome, so this file pins resolution behaviour rather than a requiredness
claim. It also pins that the two RFD3 design Tasks keep their own required
``*.cif.gz`` tree.
"""

from __future__ import annotations

from pathlib import Path

from revocompute.result_storyboard import contract_dir, expected_file_tree, resolve_expected_files
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[5]
RUNNERS = ROOT / "docker" / "runners"
FAMILY = RUNNERS / "foundry"
DESIGN_TASKS = ("foundry_rfd3_design", "foundry_rfd3na_design")

OBSERVED_STRUCTURE = "minimal_rf3/seed-0_sample-0/minimal_rf3_seed-0_sample-0_model.cif"
OBSERVED_EVIDENCE = (
    "minimal_rf3/seed-0_sample-0/minimal_rf3_seed-0_sample-0_summary_confidences.json",
    "minimal_rf3/seed-0_sample-0/minimal_rf3_seed-0_sample-0_confidences.json",
    "minimal_rf3/minimal_rf3_ranking_scores.csv",
    "foundry-run.json",
    "foundry-model-assets.json",
)
DESIGN_ARTIFACTS = (
    "specification_example_model_0.cif.gz",
    "foundry-run.json",
    "foundry-model-assets.json",
)


def _task(task_id: str):
    with isolated_discovery(str(RUNNERS)) as manager:
        return manager.contributions.resolve("tasks", task_id)


def _artifacts(*paths: str) -> list[dict]:
    return [{"path": path, "size": 128, "preview": "structure"} for path in paths]


def test_rf3_fold_resolves_the_observed_seeded_structure() -> None:
    tree = expected_file_tree(_task("foundry_rf3_fold"), str(ROOT))

    resolved, _checks, problems = resolve_expected_files(tree, _artifacts(OBSERVED_STRUCTURE, *OBSERVED_EVIDENCE))

    assert problems == []
    assert [item["path"] for item in resolved["structures"]] == [OBSERVED_STRUCTURE]


def test_rf3_fold_accepts_a_metrics_only_early_stop_tree() -> None:
    tree = expected_file_tree(_task("foundry_rf3_fold"), str(ROOT))
    metrics_only = ("minimal_rf3/minimal_rf3_ranking_scores.csv", "foundry-run.json", "foundry-model-assets.json")

    resolved, _checks, problems = resolve_expected_files(tree, _artifacts(*metrics_only))

    assert problems == []
    assert resolved["structures"] == []


def test_design_tasks_resolve_their_own_compressed_designs() -> None:
    for task_id in DESIGN_TASKS:
        task = _task(task_id)
        tree = expected_file_tree(task, str(ROOT))

        assert contract_dir(task, str(ROOT)) == (FAMILY / "tasks" / task_id).resolve()
        assert "structures" not in tree
        resolved, _checks, problems = resolve_expected_files(tree, _artifacts(*DESIGN_ARTIFACTS))
        assert problems == []
        assert [item["path"] for item in resolved["designs"]] == [DESIGN_ARTIFACTS[0]]
