# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Structural invariants of the Runner scientific-contract inventory.

These tests assert that the inventory is *internally coherent and complete*, not
that the fleet is scientifically validated. The audit's own claim is bounded:
coverage and defect status are two independent statuses, and the fleet result is a
coverage partition plus an orthogonal defect set rather than "the whole fleet
passed". These tests pin that structure — a partition that sums, a classification
that is total, a corpus whose labels are decided by provenance — so the inventory
can be regenerated against another fleet revision without editing a roster, and so
it can never quietly read greener than it is.

Nothing here restates manifest text. Every assertion below is a relational
property of values the tool obtained from the production loaders
(``isolated_discovery``, ``audit_fleet``, ``result_storyboard``, ``live_tests``,
the ``input_validators`` registries).

The five evidence levels are asserted to be *separately recorded and never
summed*. A family at ``static_contract`` is not thereby at ``real_runner_cli``,
no test may collapse the levels into a single score, and a declared
``scientific_acceptance`` marker is its own level rather than a stand-in for a run.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = ROOT / "docker" / "runners"

#: A checked-in real-result replay bundle is target-host evidence only when it was
#: captured from a finished task store row; the label is decided from the
#: bundle's own re-verified provenance, never from this file.
REPLAY_BUNDLE_GLOB = "*_replay/*.json"


def _load_tool():
    """Import the inventory generator without requiring it on ``sys.path``."""
    path = ROOT / "tools" / "audit_runner_scientific_contracts.py"
    spec = importlib.util.spec_from_file_location("audit_runner_scientific_contracts", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def inventory() -> dict:
    """Build the inventory against the real fleet root, not the fixture root.

    The shared conftest points ``RUNNERS_DIR`` at a synthetic fixture tree; this
    module is a fleet projection, so it pins discovery to the shipped tree for the
    duration of the build and restores whatever the session had installed.
    """
    previous = os.environ.get("RUNNERS_DIR")
    os.environ["RUNNERS_DIR"] = str(RUNNERS)
    try:
        tool = _load_tool()
        return tool.build_inventory(RUNNERS, ROOT)
    finally:
        if previous is None:
            os.environ.pop("RUNNERS_DIR", None)
        else:
            os.environ["RUNNERS_DIR"] = previous


def test_every_discovered_task_and_family_is_accounted_for_without_a_roster(inventory):
    """Discovery is dynamic: every loader-discovered Task has exactly one row.

    The inventory must not hard-code a count, so this checks that the rows are a
    function of what the production loader discovered rather than of a list the
    tool carries: one row per discovered Task, no row for a Task that was not
    discovered, and every Task's family present exactly once in the family rows.
    """
    from revocompute.task_types import isolated_discovery

    with isolated_discovery(str(RUNNERS)) as manager:
        discovered = sorted(value.name for _identifier, value in manager.contributions.items("tasks"))

    rows = inventory["tasks"]
    assert sorted(row["task"] for row in rows) == discovered
    assert len(rows) == len({row["task"] for row in rows})
    assert inventory["discovery"]["task_count"] == len(discovered)

    families = inventory["families"]
    assert len(families) == len({row["family"] for row in families})
    family_tasks = {task for row in families for task in row["tasks"]}
    assert family_tasks == set(discovered)
    for row in families:
        assert row["tasks"] == sorted(set(row["tasks"]))
        assert row["family"] in {task_row["family"] for task_row in rows if task_row["task"] in row["tasks"]}


def test_coverage_states_partition_the_fleet_and_reconcile_with_the_audit(inventory):
    """The four coverage states are total, disjoint, and agree with the audit.

    ``tree_audited`` is "a declared tree let the required sources be evaluated";
    ``no_required_source`` is a real state (every source optional, or no views);
    ``no_views`` is a Task that declares no result workspace; ``tree_absent`` is
    the unaudited state. They must partition the fleet, and the states with a tree
    or no obligation must equal the audit's covered set — so a Task cannot be
    reported as tree-covered without the tree that makes it so.
    """
    states = inventory["coverage"]["states"]
    assert set(states) == {"tree_audited", "tree_absent", "no_required_source", "no_views"}

    seen: list[str] = []
    for members in states.values():
        seen.extend(members)
    tasks = [row["task"] for row in inventory["tasks"]]
    assert sorted(seen) == sorted(tasks)
    assert len(seen) == len(set(seen))

    covered = set(inventory["coverage"]["covered"]) | set(inventory["coverage"]["unaudited"])
    assert covered == set(tasks)
    assert not (set(inventory["coverage"]["covered"]) & set(inventory["coverage"]["unaudited"]))
    unaudited_from_states = set(states["tree_absent"])
    assert unaudited_from_states == set(inventory["coverage"]["unaudited"])

    for row in inventory["tasks"]:
        if row["coverage_state"] == "tree_audited":
            assert row["declares_result_tree"] is True
        if row["coverage_state"] == "no_views":
            # No result workspace is not the same as no declared tree: a family
            # may publish an ``expected_files.yaml`` while declaring no view.
            assert row["view_count"] == 0
        if row["coverage_state"] == "tree_absent":
            assert row["declares_result_tree"] is False and row["view_count"] > 0


def test_the_recorded_foundry_defect_survives_as_a_concrete_finding(inventory):
    """A coverage boundary is not a clean bill of health, and the defect is present.

    The audit's defect set is orthogonal to its coverage partition. The two Foundry
    design Tasks ship a result tree (covered) and still carry a concrete
    unaddressed-required-source finding. This asserts the finding is genuinely
    reported — not merely tolerated by an allowlist — and that the defective set is
    a subset of the covered set rather than a third coverage bucket.
    """
    codes = {(finding["task"], finding["code"]) for finding in inventory["findings"]}
    assert ("foundry_rfd3_design", "result.required_source_unaddressed") in codes
    assert ("foundry_rfd3na_design", "result.required_source_unaddressed") in codes

    defective = set(inventory["coverage"]["defective"])
    assert defective == {"foundry_rfd3_design", "foundry_rfd3na_design"}
    assert defective <= set(inventory["coverage"]["covered"])
    assert inventory["coverage"]["ok"] is False


def test_every_input_role_is_classified_by_a_real_semantic_validator_registry(inventory):
    """Every declared logical input type resolves to one lifecycle class.

    The classes are decided by the real ``input_validators`` registries, not by a
    list in this file: types ``profiles.validate_logical_input`` checks inline, the
    types with a ``_SPECIFICATION_VALIDATORS`` entry, the types with a format
    dialect, and the remainder — which have no semantic validator and are reported
    as such rather than silently assumed validated. Every declared format must also
    fall inside the Core upload security boundary, or the Server would reject the
    Task's own live-test fixture.
    """
    lifecycle = _load_tool()._input_type_lifecycle()
    allowed = {
        "inline_logical_validation",
        "specification_validation",
        "format_dialect_validation",
        "no_semantic_validator",
    }

    roles = [role for row in inventory["tasks"] for role in row["input_roles"]]
    assert roles, "the fleet declares at least one named input role"
    for role in roles:
        assert role["lifecycle"] in allowed
        # A dialect or specification entry is authoritative; an unregistered type
        # must be exactly the reported fallback, never a missing key.
        if role["lifecycle"] != "no_semantic_validator":
            assert str(role["type"]) in lifecycle
        assert role["formats_inside_core_boundary"] is True
        assert role["cardinality"][0] <= role["cardinality"][1]


def test_every_family_live_test_plan_the_loader_accepts_covers_its_own_tasks(inventory):
    """The real ``load_live_test_plan`` is the reader, and smoke must cover the family.

    A family whose plan the loader rejects is reported as ``invalid`` with the
    loader's own message rather than dropped; a family with an accepted plan must
    have every one of its discovered Tasks in the smoke collection, which is the
    same invariant the production Doctor enforces.
    """
    families = inventory["families"]
    accepted = [row for row in families if row["live_test_plan"] == "valid"]
    assert accepted, "at least one family ships a loader-accepted plan"
    for row in families:
        assert row["live_test_plan"] in {"valid", "invalid", "absent"}
        if row["live_test_plan"] == "invalid":
            assert row["live_test_plan_error"]
            continue
        if row["live_test_plan"] == "absent":
            continue
        assert row["smoke_missing_tasks"] == []
        assert set(row["smoke_cases"]) >= set(row["tasks"])
        assert row["smoke_cases"] == sorted(set(row["smoke_cases"]))


def test_forwarding_candidates_are_candidates_never_verdicts(inventory):
    """A parameter no adapter asset names is reported as a candidate, not a defect.

    The Server owns no param->upstream-flag mapping, so a static scan cannot prove
    forwarding or its absence. The inventory therefore reports candidates and
    carries that caveat explicitly; this test pins the caveat to the data and
    asserts a candidate is a declared parameter, so the field cannot drift into
    looking like a validated forwarding verdict.
    """
    caveat = inventory["parameter_forwarding"]["caveat"]
    assert "candidate" in caveat and "not a verdict" in caveat

    for row in inventory["families"]:
        declared = set()
        for task_row in inventory["tasks"]:
            if task_row["family"] == row["family"]:
                declared |= set(task_row["parameters"])
        assert set(row["forwarding_candidates"]) <= declared
        assert row["forwarding_candidates"] == sorted(set(row["forwarding_candidates"]))


def test_evidence_levels_are_recorded_separately_and_never_summed(inventory):
    """The five levels are a per-family record, not a score.

    Levels are ordered weakest to strongest and each family's record is a subset
    of the ordered list; no aggregation is computed, and a stronger level never
    implies a weaker one was skipped in a way the report hides. The tool must not
    publish a single number a reader could mistake for "how validated" a family is.
    """
    levels = inventory["evidence_levels"]
    ordered = list(levels["levels"])
    assert ordered == [
        "static_contract",
        "fake_runner_contract",
        "declared_scientific_acceptance",
        "real_runner_cli",
        "target_host_slurm_apptainer",
    ]

    by_family = levels["by_family"]
    assert set(by_family) == {row["family"] for row in inventory["families"]}
    for family, record in by_family.items():
        assert set(record) == set(ordered)
        assert record["static_contract"] is True
        # A family is at a level only if the record says so; the summary and the
        # per-family record must agree, so neither can be edited alone.
        present = [name for name in ordered if record[name]]
        assert present == [
            name
            for name in ordered
            if levels["families_at_level"][name] and family in levels["families_at_level"][name]
        ]

    by_task = levels["by_task"]
    assert set(by_task) == {row["task"] for row in inventory["tasks"]}
    for record in by_task.values():
        assert record == sorted(record, key=ordered.index) or record == []
        assert set(record) <= set(ordered)
        assert "static_contract" in record

    # Every published level has a member on this fleet, so a merger cannot leave a
    # dead level behind and a level cannot be removed without failing here.
    for name in ordered:
        assert levels["families_at_level"][name], f"level {name!r} has no member on this fleet"


def test_a_declared_scientific_marker_is_a_level_of_its_own_and_not_a_run(inventory):
    """A pytest marker is a declaration; only execution evidence is a CLI run.

    The scanner reads test files and never executes them, so the only decision-grade
    ``real_runner_cli`` basis is a replay bundle whose provenance re-verifies. The
    weaker ``declared_scientific_acceptance`` level exists so a marker cannot be
    promoted by itself: a family whose scientific module sets the marker and replaces
    the upstream program with a fake must be recorded at the declaration level and
    NOT at ``real_runner_cli``.

    The distinction is read from the family's own test text, not restated here, so a
    marker-plus-mock family cannot silently re-earn the stronger level and no family
    name is written into this file.
    """
    levels = inventory["evidence_levels"]
    by_family = levels["by_family"]
    rows = {row["family"]: row for row in inventory["families"]}

    # A re-verified replay bundle is the one decision-grade basis for the CLI level,
    # so the family set that reaches it that way is read from the corpus labels.
    replay_families = {
        family
        for family, row in rows.items()
        if any(
            item["label"]
            in {"real_target_host_slurm_apptainer", "real_runner_local_no_scheduler"}
            and item.get("task_type") in row["tasks"]
            for item in inventory["evidence_corpus"]["items"]
        )
    }

    marked = [family for family, record in by_family.items() if record["declared_scientific_acceptance"]]
    assert marked, "the fleet ships at least one family that declares a scientific acceptance"
    for family in marked:
        row = rows[family]
        assert row["declares_scientific_acceptance"] is True
        if row["scientific_executes_program"] or family in replay_families:
            continue
        # Marker set, no execution evidence and no replay bundle: the declaration
        # level is true and the stronger CLI level MUST be false. This is the
        # regression that a marker-plus-mock module cannot re-earn.
        assert by_family[family]["real_runner_cli"] is False, (
            f"{family} reaches real_runner_cli from a scientific marker alone"
        )

    # The marker and the run are different predicates, so a family whose acceptance
    # module mocks the upstream program is at the declaration level and below the CLI
    # level; the two levels are never the same fact under two names.
    if marked:
        assert any(
            by_family[family]["declared_scientific_acceptance"]
            and not by_family[family]["real_runner_cli"]
            for family in marked
        )


def test_evidence_corpus_real_items_are_verified_and_mocks_never_claim_science(inventory):
    """A label is decided by the item's own provenance, and a mock claims no science.

    The corpus is discovered from disk and labeled from each bundle's re-verified
    provenance, so a synthetic fixture can never be presented as scientific
    validation: only a bundle whose production receipt re-verifies is target-host
    evidence, and every synthetic or unverified item must carry
    ``scientific_claim == "none"``.
    """
    corpus = inventory["evidence_corpus"]
    labels = set(corpus["labels"])
    discovered = sorted(
        path.relative_to(ROOT).as_posix() for path in (ROOT / "tests" / "data").glob(REPLAY_BUNDLE_GLOB)
    )
    items = corpus["items"]
    if discovered:
        assert sorted(item["path"] for item in items) == discovered
    assert len(items) == len({item["path"] for item in items})

    for item in items:
        assert item["label"] in labels
        assert item["reason"]
        if item["label"] in {"real_target_host_slurm_apptainer", "real_runner_local_no_scheduler"}:
            assert item["scientific_claim"] == "runner_output_replayed"
        else:
            assert item["scientific_claim"] == "none"

    # A target-host label requires a re-verified receipt, so a bundle that merely
    # names one cannot reach the strongest label.
    target_host = [item for item in items if item["label"] == "real_target_host_slurm_apptainer"]
    for item in target_host:
        assert item.get("receipt_path")
        assert (ROOT / str(item["receipt_path"])).is_file()
    # No item in the corpus is allowed to claim a scientific result that the
    # frontend replay boundary explicitly does not establish.
    assert all(item["scientific_claim"] in {"none", "runner_output_replayed"} for item in items)
