# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""GREMLIN_LH result contract: declared matrix scale semantics and live-test scope.

The raw Frobenius coupling matrix ``M_ij = sqrt(sum_ab W_ia,jb^2)`` is a norm, so
every entry is non-negative and the view must use a *sequential* scale. The APC
matrix ``C_ij`` is signed after the correction, so it must keep a *diverging*
scale centred at zero. Both are read through the server's own task-type loader,
which is the public consumer of the owning ``task.yaml``.

The same owning family declares two live-test collections: a tiny runtime/smoke
case and the real 2KL8 scientific golden case at the pinned upstream profile.
They must stay distinct so a runtime acceptance can never be read as a
scientific one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from revocompute.live_tests import load_live_test_plan
from revocompute.task_types import discover_plugins, get, list_types

ROOT = Path(__file__).resolve().parents[2]
FAMILY = ROOT / "docker" / "runners" / "gremlin_lh"
TASK_YAML = FAMILY / "tasks" / "gremlin_lh_fit" / "task.yaml"
TEST_YAML = FAMILY / "test.yaml"


@pytest.fixture(scope="module")
def gremlin_views():
    discover_plugins(str(ROOT / "docker" / "runners"), enabled={"gremlin_lh"})
    task, _runner = get("gremlin_lh_fit")
    return {view.id: view for view in task.result_workspace}


def test_raw_coupling_view_uses_a_sequential_scale(gremlin_views) -> None:
    raw = gremlin_views["raw_couplings"]
    assert raw.plugin == "matrix"
    assert raw.role == "primary"
    # A Frobenius norm is non-negative, so a diverging scale centred at zero
    # would encode a sign the quantity does not have.
    assert raw.mapping["scale"] == "sequential"
    assert "center" not in raw.mapping


def test_apc_coupling_view_keeps_a_diverging_scale_centred_at_zero(gremlin_views) -> None:
    apc = gremlin_views["apc_couplings"]
    assert apc.plugin == "matrix"
    assert apc.role == "evidence"
    # APC scores are signed after the correction.
    assert apc.mapping["scale"] == "diverging"
    assert apc.mapping["center"] == 0


def test_raw_and_apc_views_do_not_share_one_scale_semantics(gremlin_views) -> None:
    raw_scale = gremlin_views["raw_couplings"].mapping["scale"]
    apc_scale = gremlin_views["apc_couplings"].mapping["scale"]
    assert raw_scale != apc_scale


def _plan():
    schemas = {task.name: task.schema for task in list_types()}
    return load_live_test_plan(TEST_YAML, repo_root=ROOT, task_schemas=schemas)


def test_smoke_and_scientific_collections_use_different_alignments() -> None:
    plan = _plan()
    smoke = plan.collections["smoke"]
    scientific = plan.collections["scientific"]
    smoke_alignment = smoke[0].inputs["alignment"]
    scientific_alignment = scientific[0].inputs["alignment"]
    assert smoke_alignment == ("tests/data/msa/gremlin_lh_tiny.a3m",)
    assert scientific_alignment == ("tests/data/msa/2KL8.i90c75_aln.a3m",)
    # The two scopes must not silently collapse into one another.
    assert smoke_alignment != scientific_alignment
    assert smoke[0].id != scientific[0].id


def test_scientific_collection_uses_the_pinned_upstream_profile() -> None:
    plan = _plan()
    case = plan.collections["scientific"][0]
    assert case.task == "gremlin_lh_fit"
    # The exact profile the frozen upstream-equivalence receipt records, so the
    # live result is directly comparable to the pinned notebook.
    assert case.parameters == {
        "regularization": "LH",
        "lambda_l2": 0.01,
        "lambda_lh": 0.1,
        "lambda_lb": 0.005,
        "iterations": 50,
        "batch_size": 6,
        "learning_rate": 1.0,
        "identity_cutoff": 0.8,
        "gap_cutoff": 0.5,
        "use_bias": True,
        "inverse_covariance_init": True,
        "exact_lh_eigenvalue": False,
        "seed": 0,
    }
