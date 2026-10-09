# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations
from pathlib import Path
import pytest
from revocompute.task_types import discover_plugins, get, list_policies, list_types
ROOT = Path(__file__).resolve().parents[2]


def test_every_production_workflow_declares_both_capability_keys():
    """Every shipped workflow stage states both capabilities explicitly.

    The loader already rejects a missing key, so this asserts the *content* of
    the loaded fleet: a stage must not silently carry a default that disagrees
    with what its Runner does.
    """
    discover_plugins(str(ROOT / "docker" / "runners"))
    workflows = [task for task in list_types() if task.workflow]
    assert workflows, "no production workflow task was discovered"
    declared = set()
    for task in workflows:
        for stage in task.workflow:
            declared.add((task.name, stage.name, stage.requires_gpu, stage.requires_network))
    # The known network-dependent stages must say so; the known offline ones
    # must not claim a capability they do not use.
    by_stage = {(name, stage): (gpu, net) for name, stage, gpu, net in declared}
    assert by_stage[("colabfold_af2", "colabfold_af2.features")][1] is True
    assert by_stage[("colabfold_af2", "colabfold_af2.model")][1] is False
    assert by_stage[("alphafold", "alphafold.features")][1] is False
    assert by_stage[("alphafold3", "alphafold3.features")][1] is False

def test_every_production_workflow_partitions_its_stage_markers():
    """Every shipped composed task partitions its markers through the loader.

    The loader rejects an omitted/duplicated/out-of-order marker, so this
    asserts the *content* of the loaded fleet: each task's concatenated stage
    markers must equal its ordered task-level marker sequence.  A manifest that
    emitted a marker no stage owns would otherwise load and silently drop that
    marker at run time.
    """
    discover_plugins(str(ROOT / "docker" / "runners"))
    workflows = [task for task in list_types() if task.workflow]
    assert workflows, "no production workflow task was discovered"
    for task in workflows:
        declared = [marker for stage in task.workflow for marker in stage.stage_markers]
        assert declared == list(task.stage_markers), (
            f"{task.name} workflow stage markers {declared} do not partition {list(task.stage_markers)}"
        )
