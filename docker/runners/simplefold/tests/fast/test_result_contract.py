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

``output_format`` is a task parameter (mmcif|pdb), so the required primary
source is one bounded glob plus a declared ``.cif``/``.pdb`` extension
constraint. Both resolvers are exercised: the logical-file tree and the
published result views.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import revocompute.task_runtime as task_runtime
from revocompute.result_storyboard import expected_file_tree, resolve_expected_files
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[5]
RUNNERS = ROOT / "docker" / "runners"

CIF = "simplefold_tiny/predictions_simplefold_1.6B/simplefold_tiny_sampled_0.cif"
PDB = "simplefold_tiny/predictions_simplefold_1.6B/simplefold_tiny_sampled_0.pdb"
PDF = "simplefold_tiny/predictions_simplefold_1.6B/simplefold_tiny_sampled_0.pdf"
CDB = "simplefold_tiny/predictions_simplefold_1.6B/simplefold_tiny_sampled_0.cdb"
CONFIDENCE = "simplefold_tiny/confidence/simplefold_tiny_sampled_0.json"
RAW_NPZ = "simplefold_tiny/structures/simplefold_tiny.npz"
MULTI = tuple(
    f"simplefold_multi_{record}/predictions_simplefold_1.6B/simplefold_multi_{record}_sampled_0.cif"
    for record in "abc"
)


def _task():
    with isolated_discovery(str(RUNNERS)) as manager:
        return manager.contributions.resolve("tasks", "simplefold_predict")


def _artifacts(*paths: str) -> list[dict]:
    return [{"path": path, "size": 128, "preview": "structure", "role": "artifact"} for path in paths]


def _required_candidate_glob(task) -> str:
    primary = [view for view in task.result_workspace if view.role == "primary"]
    assert len(primary) == 1
    required = [selector for selector in primary[0].sources["candidates"] if selector.required]
    assert len(required) == 1
    assert required[0].is_glob
    return required[0].value


def _resolve_views(*paths: str):
    task = _task()
    views, _checks, problems = task_runtime._resolve_result_views(task, _artifacts(*paths), ".")
    return task, views, problems


def _primary_candidates(views) -> list[str]:
    return next(view for view in views if view["id"] == "predicted_structures")["sources"]["candidates"]


def test_the_glob_alone_would_accept_non_structure_suffixes() -> None:
    # Mutation guard: the extension constraint, not the character class, is what
    # rejects these names.
    selector = _required_candidate_glob(_task())
    assert fnmatchcase(PDF, selector)
    assert fnmatchcase(CDB, selector)


@pytest.mark.parametrize("path", [CIF, PDB])
def test_one_declared_structure_format_satisfies_both_resolvers(path: str) -> None:
    tree = expected_file_tree(_task(), str(ROOT))
    resolved, _checks, problems = resolve_expected_files(tree, _artifacts(path))
    assert problems == []
    assert [item["path"] for item in resolved["structures"]] == [path]

    _task_value, views, view_problems = _resolve_views(path)
    assert view_problems == []
    assert _primary_candidates(views) == [path]


@pytest.mark.parametrize("path", [PDF, CDB])
def test_a_matching_non_structure_suffix_fails_both_required_sources(path: str) -> None:
    tree = expected_file_tree(_task(), str(ROOT))
    resolved, _checks, problems = resolve_expected_files(tree, _artifacts(path))
    assert resolved["structures"] == []
    assert problems == ["structures: required output is missing or empty"]

    _task_value, views, view_problems = _resolve_views(path)
    assert _primary_candidates(views) == []
    assert "Predicted structures: required candidates output is missing or empty" in view_problems


def test_multi_record_cif_records_and_optional_confidence_pass() -> None:
    tree = expected_file_tree(_task(), str(ROOT))
    paths = (*MULTI, CONFIDENCE)

    resolved, _checks, problems = resolve_expected_files(tree, _artifacts(*paths))
    assert problems == []
    assert [item["path"] for item in resolved["structures"]] == list(MULTI)
    assert [item["path"] for item in resolved["confidences"]] == [CONFIDENCE]

    _task_value, views, view_problems = _resolve_views(*paths)
    assert not any("Predicted structures" in problem for problem in view_problems)
    assert _primary_candidates(views) == list(MULTI)
    confidence_view = next(view for view in views if view["id"] == "residue_confidence")
    assert confidence_view["sources"]["series"] == [CONFIDENCE]


def test_confidence_json_and_raw_arrays_are_not_structures() -> None:
    tree = expected_file_tree(_task(), str(ROOT))
    resolved, _checks, problems = resolve_expected_files(tree, _artifacts(CONFIDENCE, RAW_NPZ))
    assert resolved["structures"] == []
    assert problems == ["structures: required output is missing or empty"]

    _task_value, views, view_problems = _resolve_views(CONFIDENCE, RAW_NPZ)
    assert _primary_candidates(views) == []
    assert "Predicted structures: required candidates output is missing or empty" in view_problems
    confidence_view = next(view for view in views if view["id"] == "residue_confidence")
    assert confidence_view["sources"]["series"] == [CONFIDENCE]


def test_the_result_contract_audits_clean_and_is_tree_audited() -> None:
    from revocompute.result_audit import audit_task
    from tools.audit_runner_scientific_contracts import _coverage_state

    task = _task()
    assert audit_task(task, server_dir=str(ROOT)) == []
    assert _coverage_state(task, ROOT) == "tree_audited"


def test_a_representative_family_without_extensions_keeps_the_pre_extension_identity_shape() -> None:
    from revocompute.runner_live_test import selector_contract

    with isolated_discovery(str(RUNNERS)) as manager:
        task = manager.contributions.resolve("tasks", "boltz_predict")

    selectors = [selector for view in task.result_workspace for group in view.sources.values() for selector in group]
    assert selectors
    assert all(set(selector_contract(selector)) == {"value", "is_glob", "required"} for selector in selectors)
