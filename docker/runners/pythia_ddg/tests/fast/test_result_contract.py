# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Pythia-ddG result-contract regression, anchored to the observed live-test tree.

The contract is loaded through the same discovery and loader production uses, so
these assertions describe the shipped declaration rather than a copy of it.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

from revocompute.result_storyboard import expected_file_tree
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[5]
RUNNERS = ROOT / "docker" / "runners"
TASK_ID = "pythia_ddg"

# Observed output tree of the Nov 3 2026 target-host Slurm/Apptainer live-test
# ce24912f795b88328d6b4268f0118368 at SIF e7bc08014944. The upstream scan writes
# the CSV and TXT of the same matrix in one unconditional branch (`save_pt=False`),
# so both are present together.
OBSERVED = (
    "2KL8_pred_mask.csv",
    "2KL8_pred_mask.txt",
    "citations.bib",
    "debug/inputs/structure/2KL8.pdb",
    "debug/submission.json",
    "execution/slurm-status.execution.json",
    "execution/slurm-unknown-user-pythia_ddg-ce24912f795b88328d6b4268f0118368.resource.json",
    "execution/slurm-unknown-user-pythia_ddg-ce24912f795b88328d6b4268f0118368.stderr.log",
    "execution/slurm-unknown-user-pythia_ddg-ce24912f795b88328d6b4268f0118368.stdout.log",
    "manifest.json",
    "task_finished",
)


def _load():
    with isolated_discovery(str(RUNNERS)) as manager:
        task = manager.contributions.resolve("tasks", TASK_ID)
        return task, expected_file_tree(task, str(ROOT))


def _primary_view(task):
    return next(view for view in task.result_workspace if view.role == "primary")


def _unresolved(task, paths):
    return [
        (view.id, source, selector.value)
        for view in task.result_workspace
        for source, selectors in view.sources.items()
        for selector in selectors
        if selector.required and not any(fnmatchcase(path, selector.value) for path in paths)
    ]


def _entry(tree, value):
    return next(entry for entry in tree.values() if (entry.get("path") or entry["pattern"]) == value)


def test_declared_tree_resolves_every_required_source_on_observed_outputs() -> None:
    task, tree = _load()

    assert tree
    assert _unresolved(task, OBSERVED) == []
    for logical_id, entry in tree.items():
        selector = entry.get("path") or entry["pattern"]
        if entry["required"]:
            assert any(fnmatchcase(path, selector) for path in OBSERVED), logical_id


def test_primary_matrix_is_a_required_single_table() -> None:
    task, tree = _load()
    required = [selector for selector in _primary_view(task).sources["matrices"] if selector.required]

    assert [selector.value for selector in required] == ["*_pred_mask.csv"]
    assert _entry(tree, "*_pred_mask.csv") == {
        "pattern": "*_pred_mask.csv",
        "cardinality": "one",
        "required": True,
        "type": "table",
        "role": "evidence",
    }


def test_text_rendering_does_not_substitute_for_the_primary_and_misnaming_breaks_it() -> None:
    task, tree = _load()
    # The TXT is a second rendering written by the same unconditional branch; it
    # is required in its own right and cannot satisfy the CSV matrix source.
    assert _entry(tree, "*_pred_mask.txt")["required"] is True
    without_csv = [path for path in OBSERVED if path != "2KL8_pred_mask.csv"]
    assert _unresolved(task, without_csv) == [("mutation_scan", "matrices", "*_pred_mask.csv")]
    misnamed = [
        path.replace("2KL8_pred_mask.csv", "2KL8_pred_mask.tsv") if path == "2KL8_pred_mask.csv" else path
        for path in OBSERVED
    ]
    assert _unresolved(task, misnamed) == [("mutation_scan", "matrices", "*_pred_mask.csv")]
