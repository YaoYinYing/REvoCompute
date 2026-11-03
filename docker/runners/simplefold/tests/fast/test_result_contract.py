# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""SimpleFold result-contract regression: one required structure format.

Live-test acceptance, 2026-11-03 target-host Slurm/Apptainer runs at the active
SIF identity (SIF 3d060238b528) observed nested structures under one item:

    simplefold_tiny/predictions_simplefold_1.6B/simplefold_tiny_sampled_0.cif
    (job 69263b0625c9b574b4c138679a4effee, single record)
    simplefold_multi_{a,b,c}/predictions_simplefold_1.6B/
    simplefold_multi_{a,b,c}_sampled_0.cif
    (job 9ddbce9683c3583040e00b3589b555f8, multi-record)

``output_format`` is a task parameter (mmcif|pdb), so the primary source is one
bounded glob that accepts either observed suffix and nothing else.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

from revocompute.result_storyboard import expected_file_tree, resolve_expected_files
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[5]
RUNNERS = ROOT / "docker" / "runners"

CIF = "simplefold_tiny/predictions_simplefold_1.6B/simplefold_tiny_sampled_0.cif"
PDB = "simplefold_tiny/predictions_simplefold_1.6B/simplefold_tiny_sampled_0.pdb"
CONFIDENCE = "simplefold_tiny/confidence/simplefold_tiny_sampled_0.json"
RAW_NPZ = "simplefold_tiny/structures/simplefold_tiny.npz"
MULTI = tuple(
    f"simplefold_multi_{record}/predictions_simplefold_1.6B/simplefold_multi_{record}_sampled_0.cif"
    for record in "abc"
)


def _task() -> object:
    with isolated_discovery(str(RUNNERS)) as manager:
        return manager.contributions.resolve("tasks", "simplefold_predict")


def _primary_required_source(task) -> str:
    primary = [view for view in task.result_workspace if view.role == "primary"]
    assert len(primary) == 1
    required = [selector for selector in primary[0].sources["candidates"] if selector.required]
    assert len(required) == 1
    assert required[0].is_glob
    return required[0].value


def test_required_source_accepts_both_observed_structure_formats() -> None:
    selector = _primary_required_source(_task())
    assert fnmatchcase(CIF, selector)
    assert fnmatchcase(PDB, selector)


def test_required_source_excludes_confidence_json_and_raw_arrays() -> None:
    selector = _primary_required_source(_task())
    assert not fnmatchcase(CONFIDENCE, selector)
    assert not fnmatchcase(RAW_NPZ, selector)


def test_result_tree_declares_one_required_structure_identity() -> None:
    task = _task()
    tree = expected_file_tree(task, str(ROOT))

    assert set(tree) == {"structures", "confidences"}
    assert tree["structures"]["type"] == "structure"
    assert tree["structures"]["required"] is True
    assert tree["structures"]["pattern"] == _primary_required_source(task)
    assert tree["confidences"]["required"] is False


def test_multi_record_tree_resolves_every_observed_structure() -> None:
    tree = expected_file_tree(_task(), str(ROOT))
    artifacts = [{"path": path, "size": 128, "preview": "structure"} for path in MULTI]

    resolved, _checks, problems = resolve_expected_files(tree, artifacts)
    assert problems == []
    assert [item["path"] for item in resolved["structures"]] == list(MULTI)


def test_missing_or_misnamed_structure_does_not_satisfy_the_required_identity() -> None:
    tree = expected_file_tree(_task(), str(ROOT))
    misnamed = "simplefold_tiny/predictions_simplefold_1.6B/simplefold_tiny.cif"

    assert not fnmatchcase(misnamed, tree["structures"]["pattern"])

    resolved, _checks, problems = resolve_expected_files(
        tree,
        [{"path": path, "size": 128, "preview": "json"} for path in (CONFIDENCE, misnamed, RAW_NPZ)],
    )
    assert resolved["structures"] == []
    assert problems == ["structures: required output is missing or empty"]
