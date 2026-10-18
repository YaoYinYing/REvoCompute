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


def test_the_recorded_foundry_defect_is_resolved_not_silenced(inventory):
    """The design Tasks now carry a tree of their own, so the old defect is gone.

    The audit's defect set is orthogonal to its coverage partition, and the two
    Foundry design Tasks used to be *both*: they shipped a tree (covered) and still
    carried a concrete unaddressed-required-source finding, because the family tree
    spelled RF3's uncompressed `<example_id>_model.cif` while RFD3/RFD3NA publish
    `<example_id>_model_<n>.cif.gz`. Resolving each design Task to its own
    task-scoped tree fixes the finding instead of allowlisting it, so the assertion
    is that the finding is genuinely absent — not merely tolerated — while the two
    Tasks stay covered and keep their declared trees.

    The assertions are relational rather than literal: the defect set, the
    coverage partition, and ``ok`` are all read off the same audit report, so a
    fleet that grows or shrinks moves them together instead of failing on a count
    that only records today's fleet size.
    """
    codes = {(finding["task"], finding["code"]) for finding in inventory["findings"]}
    assert ("foundry_rfd3_design", "result.required_source_unaddressed") not in codes
    assert ("foundry_rfd3na_design", "result.required_source_unaddressed") not in codes

    coverage = inventory["coverage"]
    defective = set(coverage["defective"])
    covered = set(coverage["covered"])
    unaudited = set(coverage["unaudited"])
    tasks = {row["task"] for row in inventory["tasks"]}

    # Defect and coverage are orthogonal *statuses*, not one set: the two
    # partitions must each be a subset of the fleet, and ``ok`` is exactly
    # "no concrete defect" rather than "everything covered".
    assert defective == set()
    assert coverage["ok"] is (defective == set())
    assert covered <= tasks and unaudited <= tasks
    assert covered | unaudited <= tasks
    # A coverage-boundary finding is not a defect, so the two never name the same
    # Task -- the invariant ``result_audit._defective_tasks`` implements.
    assert defective.isdisjoint(unaudited)

    # Resolving the defect did not drop the Tasks out of coverage: they still
    # declare a tree, still have views, and the partition still reconciles.
    states = {row["task"]: row for row in inventory["tasks"]}
    for task in ("foundry_rfd3_design", "foundry_rfd3na_design"):
        assert states[task]["coverage_state"] == "tree_audited"
        assert states[task]["declares_result_tree"] is True and states[task]["view_count"] > 0
    assert covered == {task for task in tasks if task not in unaudited}


def test_every_input_role_is_classified_by_a_real_semantic_validator_registry(inventory):
    """Every declared logical input type resolves to one lifecycle class.

    The classes are decided by the real Core dispatch, not by a list in this file:
    the tool probes ``validate_input_file`` and ``validate_logical_input`` for each
    declared ``(logical type, format)`` pair and reports which validator refused.
    A role therefore carries the *set* of classes its formats occupy rather than a
    single label that has to pick one of several true answers. Every declared
    format must also fall inside the Core upload security boundary, or the Server
    would reject the Task's own live-test fixture.
    """
    tool = _load_tool()
    allowed = set(tool.LIFECYCLE_CLASSES)
    order = list(tool.LIFECYCLE_CLASSES)

    roles = [role for row in inventory["tasks"] for role in row["input_roles"]]
    assert roles, "the fleet declares at least one named input role"
    for role in roles:
        classes = role["lifecycles"]
        assert classes, f"{role['name']} declares no lifecycle at all"
        assert set(classes) <= allowed
        # Ordered and de-duplicated, so the record reads the same every run.
        assert classes == [name for name in order if name in set(classes)]
        assert role["formats_inside_core_boundary"] is True
        assert role["cardinality"][0] <= role["cardinality"][1]


def test_the_lifecycle_probe_distinguishes_a_format_dialect_from_a_logical_arm(inventory, tmp_path):
    """The Boltz type is the case a per-type label cannot express.

    ``boltz_specification`` reuses two serializations of one logical contract: a
    header-framed FASTA handled by a registered physical *dialect*, and a YAML
    document handled by a logical arm and registered nowhere. Probing Core for
    both must give two different answers, because reporting one class for the type
    was exactly the misclassification this replaces. The assertion runs the same
    probe the inventory runs, so it cannot drift from the report it explains.
    """
    tool = _load_tool()
    fasta = tool._input_dispatch_class("boltz_specification", "fasta", tmp_path)
    yaml = tool._input_dispatch_class("boltz_specification", "yaml", tmp_path)
    assert fasta == "format_dialect_validation"
    assert yaml != fasta

    boltz = [
        role
        for row in inventory["tasks"]
        for role in row["input_roles"]
        if str(role["type"]) == "boltz_specification"
    ]
    assert boltz, "the fleet declares a boltz_specification role"
    for role in boltz:
        assert "format_dialect_validation" in role["lifecycles"]

    # A type the registries know nothing about is reported as having no semantic
    # validator rather than being given the nearest-sounding class.
    assert tool._input_dispatch_class("alignment", "pqt", tmp_path) == "no_semantic_validator"
    assert tool._input_dispatch_class("protein_structure", "pdb", tmp_path) == "inline_logical_validation"
    assert tool._input_dispatch_class("alphafold3_specification", "json", tmp_path) == "specification_validation"



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


def test_real_runner_cli_is_decided_by_a_bundle_never_by_test_text(inventory):
    """`real_runner_cli` is exactly the set of families a re-verified bundle covers.

    The scanner reads test files and never executes them, so a bundle whose
    provenance re-verifies is the only decision-grade CLI basis. The weaker
    ``declared_scientific_acceptance`` level exists so a marker cannot be promoted
    by itself -- and no test-text fact may promote anything either, because a
    comment naming `subprocess.run` is not a call and a substitution cannot be
    detected by token scan (`MagicMock`, `mocker.patch.object` and a lambda
    assignment all mock silently).

    The equality below is total: it holds for EVERY family, so there is no skip a
    mock-slipped family could hide behind. A family the tool calls ``real_runner_cli``
    without a covering bundle fails here, whether the extra flag came from a marker,
    a comment, or a denylist miss.
    """
    levels = inventory["evidence_levels"]
    by_family = levels["by_family"]
    rows = {row["family"]: row for row in inventory["families"]}
    corpus_items = inventory["evidence_corpus"]["items"]
    decision_grade = {"real_target_host_slurm_apptainer", "reproduced_published_result"}

    # A family is bundle-covered when a decision-grade bundle names one of its Tasks.
    bundle_covered = {
        family
        for family, row in rows.items()
        if any(
            item["label"] in decision_grade and item.get("task_type") in row["tasks"] for item in corpus_items
        )
    }
    assert bundle_covered, "the fleet ships at least one re-verified replay bundle"

    for family, record in by_family.items():
        assert record["real_runner_cli"] is (family in bundle_covered), (
            f"{family} has real_runner_cli={record['real_runner_cli']} with a bundle basis of "
            f"{family in bundle_covered}; the CLI level is only ever a re-verified bundle"
        )

    # The declaration level is not a renaming of the CLI level, and it is not a
    # stepping stone to it: a marked family without a bundle stays below the CLI level.
    marked = [family for family, record in by_family.items() if record["declared_scientific_acceptance"]]
    assert marked, "the fleet ships at least one family that declares a scientific acceptance"
    for family in marked:
        assert rows[family]["declares_scientific_acceptance"] is True
        if family in bundle_covered:
            continue
        assert by_family[family]["real_runner_cli"] is False, (
            f"{family} reaches real_runner_cli without a re-verified bundle"
        )

    # The split is observable: at least one marked family sits at the declaration
    # level alone, so the two levels are never the same fact under two names.
    assert any(
        by_family[family]["declared_scientific_acceptance"] and not by_family[family]["real_runner_cli"]
        for family in marked
    )


def test_evidence_corpus_real_items_are_verified_and_mocks_never_claim_science(inventory):
    """A label is decided by the item's own provenance, and a mock claims no science.

    The corpus is discovered from disk and labeled from each bundle's re-verified
    provenance, so a synthetic fixture can never be presented as scientific
    validation: only a bundle whose *stored* production receipt pointer re-verifies
    field for field is target-host evidence, only a bundle whose capture recorded a
    reproduced result is local-CLI evidence, and every other item must carry
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
        if item["label"] in {"real_target_host_slurm_apptainer", "reproduced_published_result"}:
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


def _lifecycle_rows(inventory: dict) -> dict[tuple[str, str, str], tuple[str, ...]]:
    """Every declared role's lifecycle set, keyed by (task, role, type)."""
    return {
        (row["task"], role["name"], str(role["type"])): tuple(role["lifecycles"])
        for row in inventory["tasks"]
        for role in row["input_roles"]
    }


def _reworded_kind(kind: str) -> str:
    """A subject wording that shares no substring with Core's own.

    Hyphenating the spaces is what makes the rewording a real perturbation: the old
    classification matched the subject text, so a rewrite that left the matched
    phrase inside the string would have proved nothing.
    """
    return "rewritten-" + kind.replace(" ", "-") + "-subject"


def test_revording_a_core_validator_leaves_the_lifecycle_inventory_unchanged(monkeypatch, tmp_path):
    """The class comes from dispatch identity, not from a refusal's wording.

    The classification used to be decided by matching the ``kind=`` wording Core
    interpolates into a refusal, so the inventory depended on prose *inside* Core:
    rewording a validator's subject silently rewrote a column of the report, and the
    matching constants were a second source of truth for a fact the dispatch already
    owns. The class now comes from the registry that decides the pair -- ``_DIALECTS``,
    the specification registry, the inline logical-type identifiers -- with the NUL
    probe kept only as a reachability guard.

    This is the negative regression: it rewrites the wording of every ``kind=``
    subject Core uses, then requires the *whole* lifecycle column of the real
    inventory to be byte-identical to the unperturbed one -- while first proving the
    rewording reached the refusal text, so the equality cannot hold vacuously. The
    same perturbation applied to the wording-matching implementation moves 36 of the
    70 declared role rows (35 through ``profiles``, which carries the inline
    subjects, and one through ``fasta``), so the equality below is a property of
    this implementation, not of the fleet.
    """
    import revocompute.input_validators.fasta as fasta_module
    import revocompute.input_validators.profiles as profiles_module

    tool = _load_tool()
    baseline = _lifecycle_rows(_fleet_inventory(tool))
    assert baseline, "the fleet declares at least one input role"

    # The inline logical arm's refusal is where the rewording must be observable:
    # that is the wording the old predicate matched on.
    probe = tmp_path / "core-probe.pdb"
    probe.write_bytes(bytes([0]))

    def refusal() -> str:
        return str(tool.validate_logical_input(str(probe), "pdb", "protein_structure"))

    before = refusal()
    assert "protein structure" in before

    original = profiles_module._read_text

    def reworded(path, *, kind, max_bytes=None):
        return original(path, kind=_reworded_kind(kind), max_bytes=max_bytes)

    monkeypatch.setattr(profiles_module, "_read_text", reworded)
    try:
        after = refusal()
        assert after != before, "the rewording did not reach the refusal text"
        assert "protein structure" not in after
        assert _reworded_kind("protein structure") in after
        assert _lifecycle_rows(_fleet_inventory(tool)) == baseline
    finally:
        monkeypatch.setattr(profiles_module, "_read_text", original)

    # The physical pass speaks through the same helper for the registered dialects,
    # so the dialect class must survive a rewording there too.
    original_fasta = fasta_module._read_text

    def reworded_fasta(path, *, kind, max_bytes=None):
        return original_fasta(path, kind=_reworded_kind(kind), max_bytes=max_bytes)

    monkeypatch.setattr(fasta_module, "_read_text", reworded_fasta)
    try:
        assert _lifecycle_rows(_fleet_inventory(tool)) == baseline
    finally:
        monkeypatch.setattr(fasta_module, "_read_text", original_fasta)

    # The dialect pair is genuinely classified as a dialect, so the equality above is
    # not the equality of an all-absent column.
    assert tool._input_dispatch_class("chai_entity_specification", "fasta", tmp_path) == "format_dialect_validation"


def test_a_probe_no_validator_observes_reports_no_semantic_validator(tmp_path):
    """The probe is a reachability guard: no observation means no class.

    A registry identity is never reported for a pair Core does not inspect. Both
    declared pairs that reach no arm -- an unregistered extension, and a registered
    format whose logical arm does not apply to it -- are reported absent, so the
    report cannot claim a validator saw a pair it never saw.
    """
    tool = _load_tool()
    # Inside the Core boundary, but no arm: the alignment logical arm is gated on the
    # alignment formats, so a parquet payload reaches no semantic validator.
    assert tool._input_dispatch_class("alignment", "pqt", tmp_path) == "no_semantic_validator"
    assert tool._input_dispatch_class("protein_sequence", "fasta", tmp_path) == "no_semantic_validator"
    # Outside the Core boundary entirely.
    assert tool._input_dispatch_class("protein_structure", "xyz", tmp_path) == "no_semantic_validator"
    # And the three classes the registries do decide.
    assert tool._input_dispatch_class("protein_structure", "pdb", tmp_path) == "inline_logical_validation"
    assert tool._input_dispatch_class("alphafold3_specification", "json", tmp_path) == "specification_validation"
    assert tool._input_dispatch_class("boltz_specification", "yaml", tmp_path) == "inline_logical_validation"
    assert tool._input_dispatch_class("boltz_specification", "fasta", tmp_path) == "format_dialect_validation"


def _fleet_inventory(tool) -> dict:
    """Build the fleet inventory through the tool, pinned to the shipped tree.

    The module-scoped ``inventory`` fixture is the report under test; a test that
    perturbs Core needs a document built *while* perturbed, so this reads the same
    fleet through the same public entry point rather than a cached document.
    """
    previous = os.environ.get("RUNNERS_DIR")
    os.environ["RUNNERS_DIR"] = str(RUNNERS)
    try:
        return tool.build_inventory(RUNNERS, ROOT)
    finally:
        if previous is None:
            os.environ.pop("RUNNERS_DIR", None)
        else:
            os.environ["RUNNERS_DIR"] = previous


def test_the_auditors_capture_mode_vocabulary_is_the_captures_own(inventory):
    """The auditor branches on the capture's words, not on a copy of them.

    The two modes decide the two evidence labels, so a second copy of the
    vocabulary is exactly the drift this audit exists to expose: rename the
    capture's mode and the auditor would silently stop recognising every bundle.
    The assertion is an equality between the tool's constants and the capture
    module's exported tuple, not a check that either says a particular string.
    """
    from frontend_fixtures import CAPTURE_MODES

    tool = _load_tool()
    assert (tool._CAPTURE_MODE_REPRODUCED, tool._CAPTURE_MODE_SYNTHETIC) == tuple(CAPTURE_MODES)


def test_a_capture_with_no_observed_publication_cannot_reach_a_real_label(tmp_path):
    """The promotion needs the capture's observation, not prose a caller writes.

    The label used to be decided from ``provenance.capture.scheduler``, a free-form
    mapping the *caller* supplies -- so a synthetic capture whose caller wrote
    ``"none"`` into that field was promoted to a real-runner label and its family to
    ``real_runner_cli``, while no branch could ever emit the declared
    ``synthetic_mock`` label. The promotion now needs what the capture *resolved*:
    this drives the real capture and the real auditor together, with a caller that
    supplies every string the old predicate read *and* the whole promoted record,
    and requires that the promotion is not reproducible.
    """
    import sys

    from frontend_fixtures import capture_replay_bundle, write_bundle

    # The real capture test module owns the canonical synthetic result fixture;
    # reuse it rather than building a second one that could drift from it.
    sys.path.insert(0, str(ROOT / "tests" / "fleet"))
    from test_replay_bundle import TASK_ID, _synthetic_fixture, _write_result_root

    repo = tmp_path / "repo"
    result = repo / "tests" / "data" / "demo_replay"
    result.mkdir(parents=True)
    root = _write_result_root(repo, _synthetic_fixture())
    bundle = capture_replay_bundle(
        task_id=TASK_ID,
        result_root=root,
        # The caller's own claim: the promoted mode, a task source, an anchor, and
        # the scheduler prose the old predicate read.
        provenance={
            "capture": {
                "mode": "reproduced_real_result",
                "task_source": "a canonical finished task row resolved from the deployment task database",
                "publication_anchor": {"manifest_sha256": "0" * 64, "manifest_size": 1, "revision": 1},
                "scheduler": "none - executed locally, no Slurm allocation",
                "captured_from": "canonical finished task result root",
            }
        },
    )
    # The capture owns those keys, so the caller's promotion is dropped.
    assert bundle["provenance"]["capture"]["mode"] == "synthetic"
    assert "publication_anchor" not in bundle["provenance"]["capture"]
    path = write_bundle(result / "synthetic.json", bundle)

    item = _load_tool()._label_corpus_item(repo, path)
    assert item["label"] == "synthetic_mock"


def test_the_auditors_corpus_vocabulary_names_no_scheduler(tmp_path):
    """No corpus label may name a fact the auditor never reads.

    A label is a claim about the artifact, so it must not name a mechanism the tool
    does not decide. The auditor reads the capture's resolved publication and a
    re-verified production receipt; it reads no scheduler field at all. This pins
    that by driving a real capture *with* scheduler prose and requiring the emitted
    label to come from the tool's declared vocabulary -- so a label whose name
    restated a scheduler fact can never come back.
    """
    import sys

    from frontend_fixtures import capture_replay_bundle, write_bundle

    sys.path.insert(0, str(ROOT / "tests" / "fleet"))
    from test_replay_bundle import TASK_ID, _synthetic_fixture, _write_result_root

    tool = _load_tool()
    assert all("scheduler" not in label for label in tool.CORPUS_LABELS)

    repo = tmp_path / "repo"
    result = repo / "tests" / "data" / "demo_replay"
    result.mkdir(parents=True)
    root = _write_result_root(repo, _synthetic_fixture())
    bundle = capture_replay_bundle(
        task_id=TASK_ID,
        result_root=root,
        provenance={"capture": {"scheduler": "slurm: job 12345 on the gpu queue"}},
    )
    assert bundle["provenance"]["capture"]["scheduler"].startswith("slurm:")
    path = write_bundle(result / "scheduled.json", bundle)

    item = tool._label_corpus_item(repo, path)
    assert item["label"] in tool.CORPUS_LABELS
    assert item["label"] == "synthetic_mock"
    # The claim that pairs with a label is assigned by ``build_inventory``; the
    # reason string is the tool's own statement of the predicate, so require it to
    # name provenance and not a scheduler.
    assert tool._corpus_label_reason(item["label"])
    assert "scheduler" not in tool._corpus_label_reason(item["label"])


def test_a_stale_production_receipt_pointer_is_not_promoted(tmp_path):
    """A stored pointer that disagrees with its own receipt must not reach the top label.

    The strongest label used to be decided by "did ``production_receipt_pointer``
    raise", with the recomputed pointer discarded -- so a stored pointer whose
    digest, deployment, or runtime SIF had drifted from the receipt it cites still
    earned ``real_target_host_slurm_apptainer``. This drives the real checked-in
    bundle and the real checked-in receipt through the auditor, perturbs ONE stored
    field per case, re-digests so only that field is at fault, and requires the
    downgrade that names the field. The unperturbed pair is the control: it stays at
    the top label.
    """
    import json
    import shutil
    import sys

    from frontend_fixtures import bundle_digest, load_bundle

    sys.path.insert(0, str(ROOT / "tests" / "fleet"))
    from test_replay_bundle import GREMLIN_RECEIPT, REAL_BUNDLE

    if not REAL_BUNDLE.is_file() or not GREMLIN_RECEIPT.is_file():
        pytest.skip("the checked-in GREMLIN_LH replay bundle or its receipt is absent")

    tool = _load_tool()
    # The control: the shipped pair is target-host evidence.
    assert tool._label_corpus_item(ROOT, REAL_BUNDLE)["label"] == "real_target_host_slurm_apptainer"

    # Rebuild the same relative layout in a scratch root so the perturbed copies
    # live beside a byte-identical copy of the receipt they cite.
    stored = json.loads(json.dumps(load_bundle(REAL_BUNDLE)))
    receipt_relative = str(stored["provenance"]["production_receipt"]["receipt_path"])
    scratch = tmp_path / "repo"
    copied_receipt = scratch / receipt_relative
    copied_receipt.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(GREMLIN_RECEIPT, copied_receipt)

    for field, stale in (("receipt_digest", "sha256:" + "0" * 64), ("deployment_commit", "0" * 40)):
        bundle = json.loads(json.dumps(stored))
        bundle["provenance"]["production_receipt"][field] = stale
        bundle["bundle_digest"] = bundle_digest(bundle)
        destination = scratch / "tests" / "data" / "gremlin_lh_replay" / f"stale-{field}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(bundle), encoding="utf-8")

        item = tool._label_corpus_item(scratch, destination)
        assert item["label"] == "unverified_declaration", field
        assert field in item["detail"], item["detail"]

    # A pointer with no resolvable receipt at all is downgraded for that reason.
    bundle = json.loads(json.dumps(stored))
    bundle["provenance"]["production_receipt"]["receipt_path"] = "docker/runners/gremlin_lh/receipts/absent.json"
    bundle["bundle_digest"] = bundle_digest(bundle)
    missing = scratch / "tests" / "data" / "gremlin_lh_replay" / "absent-receipt.json"
    missing.write_text(json.dumps(bundle), encoding="utf-8")
    item = tool._label_corpus_item(scratch, missing)
    assert item["label"] == "unverified_declaration"
    assert "is not present" in item["detail"]
