# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The fpocket Result Workspace is expressed with generic plugins, not branches.

The Runner publishes a primary ranked-pocket table, a detection-summary scalar,
and a raw-output evidence bundle, all through the generic result-view plugins.
This asserts the *published* TaskType, so a runner-name special case elsewhere
could not satisfy it, and it checks that the declared selectors resolve against
the artifacts the normalizer actually writes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from revocompute.live_tests import load_live_test_plan
from revocompute.task_types import discover_plugins, get, list_types

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_PATH = ROOT / "tests/data/fpocket/upstream_reference.json"


@pytest.fixture(scope="module")
def fpocket_task_type():
    discover_plugins(str(ROOT / "docker" / "runners"))
    task, _runner = get("fpocket")
    return task


def test_primary_view_is_the_ranked_pocket_table(fpocket_task_type) -> None:
    views = fpocket_task_type.result_workspace
    primary = [view for view in views if view.role == "primary"]
    assert len(primary) == 1
    view = primary[0]
    # Generic plugin, no fpocket-specific renderer.
    assert view.plugin == "entity-table"
    assert view.mapping["entity"] == "candidate"
    # Rank and identity are separate columns, so the rank is never confused with
    # the pocket id.
    assert "pocket" in view.mapping["key_columns"]
    assert "rank" in view.mapping["key_columns"]
    # The primary table is sourced from the normalized CSV the Runner writes.
    assert [selector.value for selector in view.sources["table"]] == ["pockets.csv"]


def test_result_workspace_uses_only_generic_plugins(fpocket_task_type) -> None:
    plugins = {view.plugin for view in fpocket_task_type.result_workspace}
    assert plugins <= {"entity-table", "scalar-summary", "evidence-bundle"}
    roles = {view.role for view in fpocket_task_type.result_workspace}
    assert roles == {"primary", "evidence"}
    ids = [view.id for view in fpocket_task_type.result_workspace]
    assert len(ids) == len(set(ids))


def test_evidence_bundle_requires_the_raw_output_to_audit_the_table(fpocket_task_type) -> None:
    bundle = next(
        view for view in fpocket_task_type.result_workspace if view.plugin == "evidence-bundle"
    )
    selectors = {selector.value: selector for selector in bundle.sources["items"]}
    # The raw descriptor file, the alpha-sphere vertices, and the contacted-atom
    # lists are what let a reader audit the displayed pockets, plus the run record.
    assert selectors["work/*_out/*_info.txt"].is_glob
    assert selectors["work/*_out/pockets/pocket*_vert.pqr"].is_glob
    assert selectors["work/*_out/pockets/pocket*_atm.pdb"].is_glob
    assert selectors["fpocket-run.json"].value == "fpocket-run.json"
    assert all(selector.required for selector in selectors.values())


def test_scientific_collection_pins_the_reference_parameters(fpocket_task_type) -> None:
    """The scientific live-test case must run the exact frozen-reference profile.

    The reference JSON was built from the 1SUO structure at the detector defaults,
    so the live case that is compared to it must use those same parameters; the
    smoke case is a cheaper runtime probe and is deliberately different.
    """
    schemas = {task.name: task.schema for task in list_types()}
    plan = load_live_test_plan(ROOT / "docker/runners/fpocket/test.yaml", repo_root=ROOT, task_schemas=schemas)
    scientific = plan.collections["scientific"][0]
    smoke = plan.collections["smoke"][0]
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))

    expected = {name: spec["value"] for name, spec in reference["parameters"].items() if name in scientific.parameters}
    for name, value in expected.items():
        assert scientific.parameters[name] == value, (name, scientific.parameters[name], value)
    # The scientific and smoke cases must not be the same declaration.
    assert scientific.parameters != smoke.parameters
    assert scientific.inputs["structure"] == smoke.inputs["structure"]
    assert reference["reference_case"]["input_path"] == "tests/data/pdb/1SUO.pdb"
