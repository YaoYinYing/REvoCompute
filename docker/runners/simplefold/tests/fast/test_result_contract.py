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
MISNAMED = "simplefold_tiny/predictions_simplefold_1.6B/simplefold_tiny.cif"
MULTI = tuple(
    f"simplefold_multi_{record}/predictions_simplefold_1.6B/simplefold_multi_{record}_sampled_0.cif"
    for record in "abc"
)


def _task():
    with isolated_discovery(str(RUNNERS)) as manager:
        return manager.contributions.resolve("tasks", "simplefold_predict")


def _required_candidate_glob(task) -> str:
    primary = [view for view in task.result_workspace if view.role == "primary"]
    assert len(primary) == 1
    required = [selector for selector in primary[0].sources["candidates"] if selector.required]
    assert len(required) == 1
    assert required[0].is_glob
    return required[0].value


def _artifacts(*paths: str) -> list[dict]:
    return [{"path": path, "size": 128, "preview": "structure"} for path in paths]


def _resolve(*paths: str):
    tree = expected_file_tree(_task(), str(ROOT))
    assert tree["structures"]["required"] is True
    return resolve_expected_files(tree, _artifacts(*paths))


def test_cif_only_path_set_satisfies_the_required_primary_source() -> None:
    assert fnmatchcase(CIF, _required_candidate_glob(_task()))

    resolved, _checks, problems = _resolve(CIF)
    assert problems == []
    assert [item["path"] for item in resolved["structures"]] == [CIF]


def test_pdb_only_path_set_satisfies_the_required_primary_source() -> None:
    assert fnmatchcase(PDB, _required_candidate_glob(_task()))

    resolved, _checks, problems = _resolve(PDB)
    assert problems == []
    assert [item["path"] for item in resolved["structures"]] == [PDB]


def test_confidence_and_raw_arrays_do_not_satisfy_the_required_primary_source() -> None:
    selector = _required_candidate_glob(_task())
    assert not fnmatchcase(CONFIDENCE, selector)
    assert not fnmatchcase(RAW_NPZ, selector)

    resolved, _checks, problems = _resolve(CONFIDENCE, RAW_NPZ)
    assert resolved["structures"] == []
    assert problems == ["structures: required output is missing or empty"]


def test_missing_or_misnamed_structure_leaves_the_primary_source_unresolved() -> None:
    assert not fnmatchcase(MISNAMED, _required_candidate_glob(_task()))

    resolved, _checks, problems = _resolve(CONFIDENCE, MISNAMED)
    assert resolved["structures"] == []
    assert problems == ["structures: required output is missing or empty"]


def test_multi_record_tree_resolves_every_observed_structure() -> None:
    resolved, _checks, problems = _resolve(*MULTI)
    assert problems == []
    assert [item["path"] for item in resolved["structures"]] == list(MULTI)
