# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The RFdiffusion2 Tasks' result contracts against observed live-test trees.

Each Task owns its own ``expected_files.yaml``; these tests discover the fleet
through the production loader, so they observe the contract the Server resolves
rather than the files beside the test. The observed trees are the Nov 3 2026
target-host Slurm/Apptainer live-test acceptance outputs:

* ``rfdiffusion2_ligand_binder`` -- live-test 2886dfa53326d5d884ae84443220e15a
* ``rfdiffusion2_motif_scaffold`` -- live-test cfb96a334bff66d8e6ac11aa047c1995

Both ran on SIF ``b730d95f44b8``. Production file contents are ACL-masked, so
the evidence is the observed path list, not the bytes.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from revocompute.result_storyboard import contract_dir, expected_file_tree, resolve_expected_files
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[5]
RUNNERS = ROOT / "docker" / "runners"
FAMILY = RUNNERS / "rfdiffusion2"
TASKS = ("rfdiffusion2_ligand_binder", "rfdiffusion2_motif_scaffold")
PRIMARY = {
    "rfdiffusion2_ligand_binder": "designed_backbones",
    "rfdiffusion2_motif_scaffold": "designed_scaffolds",
}

OBSERVED = {
    "rfdiffusion2_ligand_binder": [
        ".cache/cache_igso3_s0.100-1.500-1000_l1000_o1000-3.npz",
        "citations.bib",
        "debug/inputs/structure/minimal_ori_ligand.pdb",
        "debug/submission.json",
        "design_0-atomized-bb-False.pdb",
        "design_0-atomized-bb-False.trb",
        "execution/slurm-status.execution.json",
        "execution/slurm-unknown-user-rfdiffusion2_ligand_binder-2886dfa53326d5d884ae84443220e15a.resource.json",
        "execution/slurm-unknown-user-rfdiffusion2_ligand_binder-2886dfa53326d5d884ae84443220e15a.stderr.log",
        "execution/slurm-unknown-user-rfdiffusion2_ligand_binder-2886dfa53326d5d884ae84443220e15a.stdout.log",
        ".hydra/config.yaml",
        ".hydra/hydra.yaml",
        ".hydra/overrides.yaml",
        "manifest.json",
        "rfdiffusion2-model-assets.sha256",
        "rfdiffusion2-run.json",
        "run_inference.log",
        "task_finished",
        "unidealized/design_0-atomized-bb-False.pdb",
    ],
    "rfdiffusion2_motif_scaffold": [
        ".cache/cache_igso3_s0.100-1.500-1000_l1000_o1000-3.npz",
        "citations.bib",
        "debug/inputs/structure/M0584_1ldm.pdb",
        "debug/submission.json",
        "design_0-atomized-bb-True.pdb",
        "design_0-atomized-bb-True.trb",
        "execution/slurm-status.execution.json",
        "execution/slurm-unknown-user-rfdiffusion2_motif_scaffold-cfb96a334bff66d8e6ac11aa047c1995.resource.json",
        "execution/slurm-unknown-user-rfdiffusion2_motif_scaffold-cfb96a334bff66d8e6ac11aa047c1995.stderr.log",
        "execution/slurm-unknown-user-rfdiffusion2_motif_scaffold-cfb96a334bff66d8e6ac11aa047c1995.stdout.log",
        ".hydra/config.yaml",
        ".hydra/hydra.yaml",
        ".hydra/overrides.yaml",
        "manifest.json",
        "rfdiffusion2-model-assets.sha256",
        "rfdiffusion2-run.json",
        "run_inference.log",
        "task_finished",
        "unidealized/design_0-atomized-bb-True.pdb",
    ],
}


@pytest.fixture(autouse=True)
def _family_contract_root(monkeypatch):
    monkeypatch.delenv("RUNNERS_DIR", raising=False)


def _artifacts(paths: list[str]) -> list[dict[str, object]]:
    return [{"path": path, "size": 1} for path in paths]


def _resolved(task_id: str):
    with isolated_discovery(str(RUNNERS)) as manager:
        task = manager.contributions.resolve("tasks", task_id)
        return task, expected_file_tree(task, str(ROOT))


@pytest.mark.parametrize("task_id", TASKS)
def test_each_task_resolves_its_own_contract(task_id: str) -> None:
    """Two TaskTypes in one family must not share one result tree."""
    task, tree = _resolved(task_id)

    assert tree
    assert contract_dir(task, str(ROOT)) == (FAMILY / "tasks" / task_id).resolve()
    assert not (FAMILY / "expected_files.yaml").exists()


@pytest.mark.parametrize("task_id", TASKS)
def test_required_view_sources_resolve_on_the_observed_tree(task_id: str) -> None:
    """Every required view selector matches a file the live test actually wrote."""
    task, tree = _resolved(task_id)
    observed = OBSERVED[task_id]

    resolved, checks, problems = resolve_expected_files(tree, _artifacts(observed))

    assert problems == []
    assert all(entries for logical_id, entries in resolved.items() if tree[logical_id]["required"])
    for view in task.result_workspace:
        for source_name, selectors in view.sources.items():
            for selector in selectors:
                if selector.required:
                    assert any(fnmatchcase(path, selector.value) for path in observed), (
                        task_id,
                        source_name,
                        selector.value,
                    )
    assert all(check["status"] == "passed" for check in checks)


@pytest.mark.parametrize("task_id", TASKS)
def test_primary_output_is_selected_from_the_observed_tree(task_id: str) -> None:
    task, tree = _resolved(task_id)
    primary = next(view for view in task.result_workspace if view.role == "primary")
    assert all(selector.required for selectors in primary.sources.values() for selector in selectors)

    resolved, _checks, problems = resolve_expected_files(tree, _artifacts(OBSERVED[task_id]))
    selected = resolved[PRIMARY[task_id]]
    entry = tree[PRIMARY[task_id]]

    assert problems == []
    assert selected
    assert {item["cardinality"] for item in selected} == {"many"}
    assert entry["required"] is True
    assert entry["type"] == "structure"
    assert entry["role"] == "evidence"


@pytest.mark.parametrize("task_id", TASKS)
def test_missing_or_misnamed_primary_is_reported(task_id: str) -> None:
    _task, tree = _resolved(task_id)
    observed = OBSERVED[task_id]
    design = next(path for path in observed if fnmatchcase(path, "design_*.pdb"))

    missing = [path for path in observed if path != design]
    _resolved_files, _checks, problems = resolve_expected_files(tree, _artifacts(missing))
    assert len(problems) == 1 and "required output is missing" in problems[0]

    misnamed = [*missing, "design_0-atomized-bb-False.pdb.bak"]
    _resolved_files, _checks, problems = resolve_expected_files(tree, _artifacts(misnamed))
    assert len(problems) == 1 and "required output is missing" in problems[0]


@pytest.mark.parametrize("task_id", TASKS)
def test_missing_best_effort_debug_capture_does_not_invalidate_result(task_id: str) -> None:
    """Core captures debug inputs and submission best-effort, so their absence is not a defect."""
    _task, tree = _resolved(task_id)
    scientific = [path for path in OBSERVED[task_id] if not path.startswith("debug/")]

    _resolved_files, checks, problems = resolve_expected_files(tree, _artifacts(scientific))

    assert problems == []
    assert all(check["status"] == "passed" for check in checks)


@pytest.mark.parametrize("task_id", TASKS)
def test_trajectory_source_stays_optional_when_absent(task_id: str) -> None:
    _task, tree = _resolved(task_id)
    trajectory_ids = [
        logical_id
        for logical_id, entry in tree.items()
        if (entry.get("pattern") or entry.get("path", "")).startswith("traj/")
    ]
    assert trajectory_ids

    _resolved_files, checks, problems = resolve_expected_files(tree, _artifacts(OBSERVED[task_id]))
    assert problems == []
    for logical_id in trajectory_ids:
        check = next(check for check in checks if check["file_id"] == logical_id)
        assert tree[logical_id]["required"] is False
        assert check["matched"] == 0
        assert check["status"] == "passed"
