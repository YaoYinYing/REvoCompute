# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Foundry result-contract regression: RF3's primary structure is required.

Live-test acceptance, 2026-11-03 target-host Slurm/Apptainer run at the active
SIF identity (job 9fb09b17099667a85d5f8800884600a8, SIF fd78dcfd2b00), observed
the seeded structure beside its conditional confidence evidence:

    minimal_rf3/seed-0_sample-0/minimal_rf3_seed-0_sample-0_model.cif

The two RFD3 Tasks share the family but own separate contracts, so this file
also pins that they still resolve their own ``*.cif.gz`` design tree.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
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


def _tasks(task_ids: tuple[str, ...]) -> dict:
    with isolated_discovery(str(RUNNERS)) as manager:
        return {task_id: manager.contributions.resolve("tasks", task_id) for task_id in task_ids}


def _primary_required_source(task) -> str:
    primary = [view for view in task.result_workspace if view.role == "primary"]
    assert len(primary) == 1
    required = [selector for selector in primary[0].sources["candidates"] if selector.required]
    assert len(required) == 1
    assert required[0].is_glob
    return required[0].value


def test_rf3_fold_requires_the_seeded_primary_structure() -> None:
    task = _tasks(("foundry_rf3_fold",))["foundry_rf3_fold"]
    tree = expected_file_tree(task, str(ROOT))

    assert tree["structures"]["required"] is True
    assert tree["structures"]["type"] == "structure"
    assert fnmatchcase(OBSERVED_STRUCTURE, tree["structures"]["pattern"])
    assert tree["structures"]["pattern"] == _primary_required_source(task)

    # Confidence and ranking evidence stays conditional; only the structure is
    # the required scientific result.
    for evidence in ("summaries", "confidences", "rankings"):
        assert tree[evidence]["required"] is False


def test_rf3_fold_required_identity_resolves_the_observed_tree_and_rejects_its_absence() -> None:
    task = _tasks(("foundry_rf3_fold",))["foundry_rf3_fold"]
    tree = expected_file_tree(task, str(ROOT))
    artifacts = [
        {"path": path, "size": 128, "preview": "structure"} for path in (OBSERVED_STRUCTURE, *OBSERVED_EVIDENCE)
    ]

    resolved, _checks, problems = resolve_expected_files(tree, artifacts)
    assert problems == []
    assert [item["path"] for item in resolved["structures"]] == [OBSERVED_STRUCTURE]

    _resolved, _checks, problems = resolve_expected_files(
        tree, [{"path": path, "size": 128, "preview": "json"} for path in OBSERVED_EVIDENCE]
    )
    assert problems == ["structures: required output is missing or empty"]


def test_design_tasks_keep_their_own_required_tree() -> None:
    for task_id, task in _tasks(DESIGN_TASKS).items():
        tree = expected_file_tree(task, str(ROOT))

        assert contract_dir(task, str(ROOT)) == (FAMILY / "tasks" / task_id).resolve()
        assert tree["designs"]["pattern"] == "*.cif.gz"
        assert tree["designs"]["required"] is True
        assert "structures" not in tree
        assert _primary_required_source(task) == "*.cif.gz"
