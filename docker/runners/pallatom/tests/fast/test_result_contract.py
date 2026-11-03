# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Pallatom result-contract regression, anchored to the observed live-test tree.

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
TASK_ID = "pallatom_generate"

# Observed output tree of the Nov 3 2026 target-host Slurm/Apptainer live-test
# fb7b02f92af4afc3584eff3ec926991b at SIF 2be064a6ae9e, for one sample.
OBSERVED = (
    "citations.bib",
    "debug/submission.json",
    "design_0001.pdb",
    "execution/slurm-status.execution.json",
    "execution/slurm-unknown-user-pallatom_generate-fb7b02f92af4afc3584eff3ec926991b.resource.json",
    "execution/slurm-unknown-user-pallatom_generate-fb7b02f92af4afc3584eff3ec926991b.stderr.log",
    "execution/slurm-unknown-user-pallatom_generate-fb7b02f92af4afc3584eff3ec926991b.stdout.log",
    "generation_metadata.json",
    "manifest.json",
    "sample_seq.fasta",
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


def test_primary_output_is_a_required_structure_collection() -> None:
    task, tree = _load()
    required = [selector for selector in _primary_view(task).sources["candidates"] if selector.required]

    assert [selector.value for selector in required] == ["design_*.pdb"]
    assert _entry(tree, "design_*.pdb") == {
        "pattern": "design_*.pdb",
        "cardinality": "many",
        "required": True,
        "type": "structure",
        "role": "evidence",
    }


def test_sample_count_is_not_pinned_and_missing_primary_breaks_the_source() -> None:
    task, tree = _load()
    # `num_samples` is a run parameter, so a second sample must resolve too; the
    # primary selector is a collection, not a fixed filename.
    assert _unresolved(task, (*OBSERVED, "design_0002.pdb")) == []

    without_design = [path for path in OBSERVED if path != "design_0001.pdb"]
    assert _unresolved(task, without_design) == [("generated_structures", "candidates", "design_*.pdb")]
    misnamed = [
        path.replace("design_0001.pdb", "design_0001.cif") if path == "design_0001.pdb" else path
        for path in OBSERVED
    ]
    assert _unresolved(task, misnamed) == [("generated_structures", "candidates", "design_*.pdb")]
