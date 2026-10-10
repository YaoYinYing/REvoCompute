# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from frontend_fixtures import pssm_gremlin_scenario, validate_payload


def test_named_real_runner_scenario_projects_the_declared_view_set() -> None:
    """The named scenario carries every view ``gremlin_lh_fit`` declares.

    The five declared views are the real shipped vocabulary: raw and APC
    coupling matrices, ranked residue pairs, the filtered alignment, and the fit
    summary. A generic harness test must not pin this production view-id set, so
    the authentic acceptance lives here at the fleet boundary.
    """
    scenario = pssm_gremlin_scenario()
    validate_payload("TaskTypeDetail", scenario.detail())
    manifest = scenario.result_manifest()
    assert manifest is not None
    assert {view["id"] for view in manifest["views"]} >= {
        "raw_couplings",
        "apc_couplings",
        "ranked_pairs",
        "filtered_alignment",
    }


def test_named_real_runner_scenario_keeps_the_manifest_primary_relationship() -> None:
    """A named real-Runner fixture must not invert the manifest's science.

    ``gremlin_lh_fit`` declares ``raw_couplings`` as its primary matrix and
    ``apc_couplings`` as evidence. If a fixture promotes APC or drops raw, a
    browser test would pass against a contract the product does not ship.
    """
    manifest = pssm_gremlin_scenario().result_manifest()
    assert manifest is not None
    roles = {view["id"]: view["role"] for view in manifest["views"]}
    assert roles["raw_couplings"] == "primary"
    assert roles["apc_couplings"] == "evidence"
    # The primary view must actually be sourced from the raw matrix.
    raw = next(view for view in manifest["views"] if view["id"] == "raw_couplings")
    assert raw["sources"] == {"matrices": ["couplings/raw_scores.csv"]}
    artifacts = {artifact["path"]: artifact["role"] for artifact in manifest["artifacts"]}
    assert artifacts["couplings/raw_scores.csv"] == "primary"
    assert artifacts["couplings/apc_scores.csv"] == "evidence"
    assert manifest["task_type"] == pssm_gremlin_scenario().runner.name
