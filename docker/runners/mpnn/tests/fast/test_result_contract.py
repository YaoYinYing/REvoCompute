# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The ThermoMPNN Task's result contract against its observed live-test tree.

The tree is the Nov 3 2026 target-host Slurm/Apptainer live-test acceptance
output for ``thermompnn`` (live-test c677800a11695318aa414290ba7e90ec, SIF
``6194a0e7768f``). Discovery runs through the production loader, so these tests
observe the contract the Server resolves; production file contents are
ACL-masked, so the evidence is the observed path list, not the bytes.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from revocompute.result_storyboard import contract_dir, expected_file_tree, resolve_expected_files
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[5]
RUNNERS = ROOT / "docker" / "runners"
FAMILY = RUNNERS / "mpnn"
TASK_ID = "thermompnn"
PRIMARY_ID = "stability_table"

OBSERVED = [
    "citations.bib",
    "debug/inputs/structure/2KL8.pdb",
    "debug/submission.json",
    "execution/slurm-status.execution.json",
    "execution/slurm-unknown-user-thermompnn-c677800a11695318aa414290ba7e90ec.resource.json",
    "execution/slurm-unknown-user-thermompnn-c677800a11695318aa414290ba7e90ec.stderr.log",
    "execution/slurm-unknown-user-thermompnn-c677800a11695318aa414290ba7e90ec.stdout.log",
    "manifest.json",
    "task_finished",
    "thermompnn.csv",
]


@pytest.fixture(autouse=True)
def _family_contract_root(monkeypatch):
    monkeypatch.delenv("RUNNERS_DIR", raising=False)


def _artifacts(paths: list[str]) -> list[dict[str, object]]:
    return [{"path": path, "size": 1} for path in paths]


def _resolved():
    with isolated_discovery(str(RUNNERS)) as manager:
        task = manager.contributions.resolve("tasks", TASK_ID)
        return task, expected_file_tree(task, str(ROOT))


def test_thermompnn_resolves_its_own_contract() -> None:
    task, tree = _resolved()

    assert tree
    assert contract_dir(task, str(ROOT)) == (FAMILY / "tasks" / TASK_ID).resolve()
    assert not (FAMILY / "expected_files.yaml").exists()


def test_required_view_sources_resolve_on_the_observed_tree() -> None:
    task, tree = _resolved()

    resolved, checks, problems = resolve_expected_files(tree, _artifacts(OBSERVED))

    assert problems == []
    assert all(entries for logical_id, entries in resolved.items() if tree[logical_id]["required"])
    for view in task.result_workspace:
        for source_name, selectors in view.sources.items():
            for selector in selectors:
                if selector.required:
                    assert any(fnmatchcase(path, selector.value) for path in OBSERVED), (
                        source_name,
                        selector.value,
                    )
    assert all(check["status"] == "passed" for check in checks)


def test_primary_view_declares_the_observed_stability_table() -> None:
    task, tree = _resolved()
    primary = next(view for view in task.result_workspace if view.role == "primary")
    selector = primary.sources["table"][0]
    entry = tree[PRIMARY_ID]

    assert selector.required and selector.value == "thermompnn.csv"
    assert entry["required"] is True
    assert entry["cardinality"] == "one"
    assert entry["type"] == "table"
    assert entry["role"] == "evidence"


def test_missing_or_misnamed_primary_is_reported() -> None:
    _task, tree = _resolved()

    missing = [path for path in OBSERVED if path != "thermompnn.csv"]
    _resolved_files, _checks, problems = resolve_expected_files(tree, _artifacts(missing))
    assert any(problem.startswith(f"{PRIMARY_ID}:") for problem in problems)

    misnamed = [*missing, "thermompnn_scores.csv"]
    _resolved_files, _checks, problems = resolve_expected_files(tree, _artifacts(misnamed))
    assert any(problem.startswith(f"{PRIMARY_ID}:") for problem in problems)
