# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Pythia-ddG result-contract regression, anchored to the observed live-test tree.

The contract is loaded through the same discovery, tree loader and resolver
production uses, so these assertions exercise the shipped declaration rather
than a copy of its YAML shape.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

from revocompute.result_storyboard import expected_file_tree, resolve_expected_files
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[5]
RUNNERS = ROOT / "docker" / "runners"
TASK_ID = "pythia_ddg"
PRIMARY_OUTPUT = "2KL8_pred_mask.csv"

# Observed output tree of the Nov 3 2026 target-host Slurm/Apptainer live-test
# ce24912f795b88328d6b4268f0118368 at SIF e7bc08014944. The upstream scan writes
# a TXT rendering beside the CSV; only the CSV is the matrix the Task renders.
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


def _resolve(tree, paths):
    return resolve_expected_files(tree, [{"path": path, "size": 1} for path in paths])


def _resolved_paths(resolved):
    return [artifact["path"] for artifacts in resolved.values() for artifact in artifacts]


def _primary_selectors(task):
    view = next(view for view in task.result_workspace if view.role == "primary")
    return [selector for selectors in view.sources.values() for selector in selectors]


def _owner(resolved, path):
    owners = [
        logical_id
        for logical_id, artifacts in resolved.items()
        if any(artifact["path"] == path for artifact in artifacts)
    ]
    assert len(owners) == 1
    return owners[0]


def test_declared_tree_resolves_the_observed_result() -> None:
    task, tree = _load()
    resolved, checks, problems = _resolve(tree, OBSERVED)

    assert tree
    assert problems == []
    assert all(check["status"] == "passed" for check in checks)
    assert PRIMARY_OUTPUT in _resolved_paths(resolved)


def test_primary_view_resolves_to_the_required_single_table() -> None:
    task, tree = _load()
    resolved, checks, _problems = _resolve(tree, OBSERVED)
    required_sources = [selector for selector in _primary_selectors(task) if selector.required]

    assert any(fnmatchcase(PRIMARY_OUTPUT, selector.value) for selector in required_sources)
    primary_id = _owner(resolved, PRIMARY_OUTPUT)
    assert tree[primary_id]["required"] is True
    assert tree[primary_id]["cardinality"] == "one"
    assert tree[primary_id]["type"] == "table"
    assert tree[primary_id]["role"] == "evidence"
    assert next(check for check in checks if check["file_id"] == primary_id)["status"] == "passed"


def test_txt_rendering_is_not_required_and_cannot_substitute_for_the_csv() -> None:
    task, tree = _load()
    primary_sources = _primary_selectors(task)

    # The TXT is a declared artifact, not the primary matrix.
    assert not any(fnmatchcase("2KL8_pred_mask.txt", selector.value) for selector in primary_sources)
    without_txt = [path for path in OBSERVED if path != "2KL8_pred_mask.txt"]
    assert _resolve(tree, without_txt)[2] == []

    # With only the TXT present, the required CSV matrix remains unresolved.
    without_csv = [path for path in OBSERVED if path != PRIMARY_OUTPUT]
    resolved, _checks, problems = _resolve(tree, without_csv)
    assert len(problems) == 1 and problems[0].endswith("required output is missing or empty")
    resolved_paths = _resolved_paths(resolved)
    assert PRIMARY_OUTPUT not in resolved_paths
    assert "2KL8_pred_mask.txt" in resolved_paths
    misnamed = [
        path.replace(PRIMARY_OUTPUT, "2KL8_pred_mask.tsv") if path == PRIMARY_OUTPUT else path
        for path in OBSERVED
    ]
    problems = _resolve(tree, misnamed)[2]
    assert len(problems) == 1 and problems[0].endswith("required output is missing or empty")


def test_missing_best_effort_debug_capture_does_not_invalidate_the_result() -> None:
    task, tree = _load()
    without_debug = tuple(path for path in OBSERVED if not path.startswith("debug/"))

    resolved, checks, problems = _resolve(tree, without_debug)

    assert problems == []
    assert all(check["status"] == "passed" for check in checks)
    assert PRIMARY_OUTPUT in _resolved_paths(resolved)
