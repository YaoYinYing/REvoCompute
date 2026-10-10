# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The fpocket Result Workspace and storyboard are expressed with generic plugins.

REvoCompute owns the fpocket result contract, not fpocket's pocket mathematics
(see ``docker/runners/fpocket/INTEGRATION.md``).  So this asserts the *published*
TaskType -- a generic primary table, a detection summary, an evidence bundle, and
the logical-file identities the storyboard binds to -- and that the declared
selectors resolve against the artifacts the normalizer writes.  It makes no claim
about which pockets or scores fpocket is "correct" to have produced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from revocompute.live_tests import load_live_test_plan
from revocompute.result_storyboard import (
    expected_file_tree,
    load_expected_file_tree,
    storyboard_declaration,
)
from revocompute.task_types import discover_plugins, get, list_types

ROOT = Path(__file__).resolve().parents[2]
FAMILY = ROOT / "docker" / "runners" / "fpocket"


@pytest.fixture(scope="module")
def fpocket_task_type():
    discover_plugins(str(ROOT / "docker" / "runners"))
    task, _runner = get("fpocket")
    return task


@pytest.fixture(scope="module")
def fpocket_files() -> dict:
    return load_expected_file_tree(FAMILY / "expected_files.yaml")


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
    assert selectors["work/*_out/*_info.txt"].is_glob
    assert selectors["work/*_out/pockets/pocket*_vert.pqr"].is_glob
    assert selectors["work/*_out/pockets/pocket*_atm.pdb"].is_glob
    assert selectors["fpocket-run.json"].value == "fpocket-run.json"
    assert all(selector.required for selector in selectors.values())


def test_logical_files_name_the_result_identities_the_storyboard_uses(fpocket_files: dict) -> None:
    """The logical-file contract gives durable identities to fpocket's own output."""
    assert set(fpocket_files) == {
        "protein_structure",
        "pockets",
        "detection_summary",
        "run_record",
        "pocket_contacts",
        "pocket_alpha_spheres",
    }
    # The structure is the immutable input snapshot, addressed by its role
    # directory; it is optional so a result that omitted the debug copy still
    # publishes.
    assert fpocket_files["protein_structure"]["pattern"] == "debug/inputs/structure/*"
    assert fpocket_files["protein_structure"]["required"] is False
    assert fpocket_files["pockets"]["path"] == "pockets.csv"
    assert fpocket_files["pockets"]["required"] is True
    assert fpocket_files["pocket_contacts"]["cardinality"] == "many"
    assert fpocket_files["pocket_alpha_spheres"]["cardinality"] == "many"
    # Roles stay within the server-owned vocabulary and never claim `primary`.
    assert all(entry.get("role") != "primary" for entry in fpocket_files.values())


def test_storyboard_declaration_binds_only_to_declared_logical_files(fpocket_task_type) -> None:
    tree = expected_file_tree(fpocket_task_type, str(ROOT))
    declaration = storyboard_declaration(fpocket_task_type, str(ROOT), set(tree))
    assert declaration is not None
    assert declaration["identifier"] == "fpocket-result"
    assert declaration["entrypoint"] == "index.js"
    # The pocket table is what the storyboard cannot render without; every other
    # identity -- the structure, the geometry files -- is optional, so a partial
    # result still presents a usable ranked list.
    assert declaration["requires"] == ["pockets"]
    assert set(declaration["optional"]) == {
        "protein_structure",
        "detection_summary",
        "run_record",
        "pocket_contacts",
        "pocket_alpha_spheres",
    }
    assert (FAMILY / "storyboard" / declaration["entrypoint"]).is_file()


def test_smoke_collection_runs_the_reference_structure_cheaply(fpocket_task_type) -> None:
    """The smoke case is the runnable evidence: one 1SUO structure, cheap volume."""
    schemas = {task.name: task.schema for task in list_types()}
    plan = load_live_test_plan(FAMILY / "test.yaml", repo_root=ROOT, task_schemas=schemas)
    smoke = plan.collections["smoke"][0]
    assert smoke.task == "fpocket"
    assert smoke.inputs["structure"] == ("tests/data/pdb/1SUO.pdb",)
    assert smoke.parameters["volume_monte_carlo_iterations"] == 100
