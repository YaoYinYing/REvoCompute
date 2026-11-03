# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""GeoDock result-contract regression, anchored to the observed live-test tree.

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
TASK_ID = "geodock"

# Observed output tree of the Nov 3 2026 target-host Slurm/Apptainer live-test
# 9676b7a8bc36d3ebea142aa307dddabd at SIF 778d1e07f831. That acceptance run used
# `refine=false`, so `geodock_refined.pdb` is absent: the optional branch must
# stay optional.
OBSERVED = (
    "citations.bib",
    "debug/inputs/partner_a/partner_a.pdb",
    "debug/inputs/partner_b/partner_b.pdb",
    "debug/submission.json",
    "execution/slurm-status.execution.json",
    "execution/slurm-unknown-user-geodock-9676b7a8bc36d3ebea142aa307dddabd.resource.json",
    "execution/slurm-unknown-user-geodock-9676b7a8bc36d3ebea142aa307dddabd.stderr.log",
    "execution/slurm-unknown-user-geodock-9676b7a8bc36d3ebea142aa307dddabd.stdout.log",
    "geodock-confidence.json",
    "geodock-model-assets.sha256",
    "geodock-run.json",
    "geodock_raw.pdb",
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


def test_primary_output_is_a_required_single_structure() -> None:
    task, tree = _load()
    required = [selector for selector in _primary_view(task).sources["candidates"] if selector.required]

    assert [selector.value for selector in required] == ["geodock_raw.pdb"]
    assert _entry(tree, "geodock_raw.pdb") == {
        "path": "geodock_raw.pdb",
        "cardinality": "one",
        "required": True,
        "type": "structure",
        "role": "evidence",
    }


def test_refined_branch_stays_optional_and_missing_primary_breaks_the_source() -> None:
    task, tree = _load()
    assert _entry(tree, "geodock_refined.pdb")["required"] is False
    optional = [selector for selector in _primary_view(task).sources["candidates"] if not selector.required]
    assert [selector.value for selector in optional] == ["geodock_refined.pdb"]
    required_values = [
        selector.value
        for view in task.result_workspace
        for selectors in view.sources.values()
        for selector in selectors
        if selector.required
    ]
    assert "geodock_refined.pdb" not in required_values

    without_raw = [path for path in OBSERVED if path != "geodock_raw.pdb"]
    assert _unresolved(task, without_raw) == [("docked_complex", "candidates", "geodock_raw.pdb")]
    misnamed = [
        path.replace("geodock_raw.pdb", "geodock_raw_model.pdb") if path == "geodock_raw.pdb" else path
        for path in OBSERVED
    ]
    assert _unresolved(task, misnamed) == [("docked_complex", "candidates", "geodock_raw.pdb")]
