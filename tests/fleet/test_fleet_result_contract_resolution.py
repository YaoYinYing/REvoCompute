# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The shipped fleet's result-contract resolution, through the real loader.

A task-scoped contract is a *deployment* property: which Task owns which
directory is decided by the manifests the Server discovers, so the assertions
that the split took effect belong to the fleet collection rather than a
synthetic-tree unit test.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from revocompute.result_storyboard import (
    contract_dir,
    expected_file_tree,
    storyboard_asset_root,
    storyboard_declaration,
)
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = ROOT / "docker" / "runners"
DESIGN_TASKS = ("foundry_rfd3_design", "foundry_rfd3na_design")


def _declaration(manager, task_id: str):
    task = manager.contributions.resolve("tasks", task_id)
    tree = expected_file_tree(task, str(ROOT))
    return task, tree, storyboard_declaration(task, str(ROOT), set(tree))


def test_the_foundry_design_tasks_resolve_their_own_compressed_design_tree() -> None:
    """`foundry` hosts one folding Task and two designing Tasks in one family.

    Before the split, the designing Tasks' `*.cif.gz` candidates had no declared
    logical identity: the family's one tree described the RF3 seed/sample
    spelling. Now each Task resolves the tree beside its own manifest, while the
    folding Task keeps the seed/sample tree verbatim.
    """
    with isolated_discovery(str(RUNNERS)) as manager:
        trees = {task_id: _declaration(manager, task_id)[1]
                 for task_id in ("foundry_rf3_fold", *DESIGN_TASKS)}

    fold = trees["foundry_rf3_fold"]
    assert fold["structures"]["pattern"].endswith("_model.cif")
    assert "designs" not in fold
    for design_id in DESIGN_TASKS:
        assert trees[design_id]["designs"]["pattern"] == "*.cif.gz"
        assert trees[design_id]["designs"]["type"] == "structure"
        # The design tree is that Task's own; the fold spelling is absent from it.
        assert "structures" not in trees[design_id]
        assert trees[design_id] != fold


def test_the_design_tasks_serve_a_storyboard_of_their_own() -> None:
    """Two TaskTypes in one runtime family answer with different modules."""
    with isolated_discovery(str(RUNNERS)) as manager:
        fold_task, fold_tree, fold_declaration = _declaration(manager, "foundry_rf3_fold")
        resolved = {task_id: _declaration(manager, task_id) for task_id in DESIGN_TASKS}

        assert fold_declaration["identifier"] == "foundry-rf3-result"
        for task_id, (task, tree, declaration) in resolved.items():
            # The module binds only to logical files this Task's own tree
            # declares, and the served directory is the one it was read from.
            assert declaration["requires"] == ["designs", "run_record", "model_assets"]
            assert set(declaration["requires"] + declaration["optional"]) <= set(tree)
            root = storyboard_asset_root(task, str(ROOT))
            assert root == (RUNNERS / "foundry" / "tasks" / task_id / "storyboard").resolve()
            assert root != storyboard_asset_root(fold_task, str(ROOT))
        assert resolved["foundry_rfd3_design"][2]["identifier"] == "foundry-rfd3-result"
        assert resolved["foundry_rfd3na_design"][2]["identifier"] == "foundry-rfd3na-result"
        # The three modules are three distinct files, not one reached three ways.
        modules = {(storyboard_asset_root(task, str(ROOT)) / declaration["entrypoint"]).resolve()
                   for task, _tree, declaration in [*resolved.values(), (fold_task, fold_tree, fold_declaration)]}
        assert len(modules) == 3 and all(path.is_file() for path in modules)


def test_the_family_scoped_families_still_resolve_from_the_family_directory() -> None:
    """fpocket and GREMLIN_LH keep the exact contract they had.

    Both ship a family-level `expected_files.yaml` and `storyboard/` with their
    Task manifests one level down, so this is the regression proving the
    migration was additive rather than a silent re-pointing: the resolved tree
    and module directory are the family's own, parsed identically to the file.
    """
    with isolated_discovery(str(RUNNERS)) as manager:
        for task_id, family_name in (("fpocket", "fpocket"), ("gremlin_lh_fit", "gremlin_lh")):
            family = RUNNERS / family_name
            task = manager.contributions.resolve("tasks", task_id)
            tree = expected_file_tree(task, str(ROOT))
            declared = yaml.safe_load((family / "expected_files.yaml").read_text(encoding="utf-8"))["result"]["files"]

            assert contract_dir(task, str(ROOT)) == family.resolve()
            assert tree == {logical_id: {**entry, "cardinality": entry.get("cardinality", "one")}
                            for logical_id, entry in declared.items()}
            declaration = storyboard_declaration(task, str(ROOT), set(tree))
            assert declaration is not None and declaration["entrypoint"] == "index.js"
            assert storyboard_asset_root(task, str(ROOT)) == (family / "storyboard").resolve()
            assert (storyboard_asset_root(task, str(ROOT)) / declaration["entrypoint"]).is_file()
