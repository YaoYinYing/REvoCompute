# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import pytest
from revocompute.result_audit import DISJOINT, OVERLAP, UNKNOWN, _overlap, audit_fleet, audit_task
from revocompute.result_storyboard import ResultContractError
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[2]

RUNNERS = ROOT / "docker" / "runners"

#: Defects the audit used to record and no longer does, kept as an explicit
#: record rather than deleted: the assertion below proves they are *resolved*,
#: not that the finding was silenced.
RESOLVED_DEFECTS: dict[tuple[str, str], str] = {
    ("foundry_rfd3_design", "result.required_source_unaddressed"): (
        "RFD3 design writes '<name>_model_<n>.cif.gz' (pinned upstream "
        "rfd3/engine.py); the foundry family's one shared expected_files.yaml "
        "declared only the RF3 fold spelling '*_model.cif' under 'structures', "
        "so the design Tasks' primary candidates had no declared logical "
        "identity. Resolved by the Task-scoped result contract: each Task now "
        "resolves the tree beside its own manifest."
    ),
    ("foundry_rfd3na_design", "result.required_source_unaddressed"): (
        "Same shared-foundry-tree defect as foundry_rfd3_design."
    ),
}

def test_real_fleet_is_discovered_and_audited_end_to_end():
    """The audit runs over every Task the production loader discovers."""
    report = audit_fleet(str(RUNNERS), server_dir=str(ROOT))

    assert len(report.tasks) == len(set(report.tasks)) >= 50
    for representative in ("gremlin_lh_fit", "fpocket", "boltz_predict", "foundry_rfd3_design", "alphafold3"):
        assert representative in report.tasks

def test_real_fleet_reports_no_unrecorded_contract_defect():
    """Every remaining finding is the explicit coverage boundary, nothing else.

    The fleet is still NOT claimed clean: the 34 Tasks that require a view
    source and ship no ``expected_files.yaml`` are reported as
    ``result.required_source_undeclared_tree`` (unaudited, not green). The test
    fails if any *other* finding appears, so the reported state cannot drift
    into looking greener than it is.
    """
    report = audit_fleet(str(RUNNERS), server_dir=str(ROOT))

    unrecorded = [
        finding
        for finding in report.findings
        if finding.code != "result.required_source_undeclared_tree"
        and (finding.task, finding.code) not in RESOLVED_DEFECTS
    ]
    assert unrecorded == [], "\n".join(str(finding) for finding in unrecorded)
    for finding in report.findings:
        assert finding.task and finding.task != "-"
        if finding.code in {"result.required_source_unaddressed", "result.required_source_undeclared_tree"}:
            assert finding.view

def test_the_recorded_foundry_design_defect_is_resolved_not_silenced():
    """The formerly-recorded foundry defect is *absent*, and provably so.

    A defect that disappears when an allowlist is edited is indistinguishable
    from a defect that was fixed, so this asserts the fix's own signature: the
    design Tasks resolve the compressed design structures their own tree
    declares, and no finding at all names them. If the Task-scoped resolution
    regressed -- or the design Tasks silently fell back to the family tree --
    this fails.
    """
    from revocompute.result_storyboard import expected_file_tree
    from revocompute.task_types import isolated_discovery

    report = audit_fleet(str(RUNNERS), server_dir=str(ROOT))

    assert RESOLVED_DEFECTS  # a like-shaped control: the absence below is not vacuous
    assert not (
        {(finding.task, finding.code) for finding in report.findings} & set(RESOLVED_DEFECTS)
    ), "a resolved defect is reported again"
    with isolated_discovery(str(RUNNERS)) as manager:
        design = manager.contributions.resolve("tasks", "foundry_rfd3_design")
        fold = manager.contributions.resolve("tasks", "foundry_rf3_fold")
        design_tree = expected_file_tree(design, str(ROOT))
        fold_tree = expected_file_tree(fold, str(ROOT))
    # Each Task resolves its own tree: the design identifier is present in one
    # and the RF3 seed/sample shape in the other, so they are not one contract.
    assert design_tree != fold_tree
    assert "designs" in design_tree and design_tree["designs"]["pattern"] == "*.cif.gz"
    assert "structures" in fold_tree and fold_tree["structures"]["pattern"].endswith("_model.cif")


def test_the_shared_tree_defect_is_still_detected_when_the_split_is_undone(tmp_path, monkeypatch):
    """A control for the absence above: the audit still fires on the defect.

    A control for the assertion above, not a regression against ``main``: it
    reconstructs the pre-split tree itself, so it passes there too and does not
    by itself distinguish the two heads. What it pins is that the ``(task, code)``
    pairs the fleet no longer reports are ones the audit *does* produce when the
    Task-scoped split is undone -- the exact pre-split family, built out of the
    real one (the fold Task's contract back at the family root, the design Tasks'
    own contracts removed, every other byte identical) and audited through the
    production loader. Without it, an emptied ``RESOLVED_DEFECTS`` or a broken
    required-source check would leave the absence above looking green.
    """
    import shutil

    runners = tmp_path / "docker" / "runners"
    runners.mkdir(parents=True)
    shutil.copytree(RUNNERS / "foundry", runners / "foundry")
    shutil.copytree(RUNNERS / "common", runners / "common")
    monkeypatch.setenv("RUNNERS_DIR", str(runners))
    family = runners / "foundry"
    shutil.move(str(family / "tasks" / "foundry_rf3_fold" / "expected_files.yaml"), str(family / "expected_files.yaml"))
    shutil.move(str(family / "tasks" / "foundry_rf3_fold" / "storyboard"), str(family / "storyboard"))
    for task_id in sorted({task for task, _code in RESOLVED_DEFECTS}):
        task_directory = family / "tasks" / task_id
        (task_directory / "expected_files.yaml").unlink()
        shutil.rmtree(task_directory / "storyboard")

    report = audit_fleet(str(runners), server_dir=str(ROOT))

    assert set(report.tasks) == {"foundry_rfd3_design", "foundry_rfd3na_design", "foundry_rf3_fold"}
    assert {
        (finding.task, finding.code) for finding in report.findings
    } == set(RESOLVED_DEFECTS)
    assert report.defective == {task for task, _code in RESOLVED_DEFECTS}
    assert report.ok is False
    # The design Tasks still declare a tree here -- the family's -- which is what
    # makes this line say something: a Task can be covered by the partition and
    # still be reported defective, because coverage asks whether a declaration
    # could be evaluated, not whether it passed. (It is a tautology for the report
    # shapes below, where the defect set is empty; that is the comment's job.)
    assert report.defective <= report.covered

def test_fleet_report_separates_covered_unaudited_and_defective():
    """Coverage (a partition) and defect status (orthogonal) are both reported.

    Coverage asks whether a Task's declarations could be evaluated at all:
    covered (a declared result tree) versus unaudited (no tree), which partition
    the fleet. Defect status stays orthogonal and is now empty -- the two
    Foundry design Tasks ship a Task-scoped tree and no longer carry the defect
    that the shared family tree forced. The report still exposes both statuses
    separately so coverage can never be read as "the whole fleet passed".
    """
    report = audit_fleet(str(RUNNERS), server_dir=str(ROOT))

    # Coverage is a partition ...
    assert report.covered | report.unaudited == frozenset(report.tasks)
    assert not (report.covered & report.unaudited)
    assert len(report.covered) == 22 and len(report.unaudited) == 34
    # ... and defect status is orthogonal: it is empty here, while 34 Tasks are
    # still unaudited, so a clean defect set is not a clean coverage set.
    assert set(report.defective) == set()
    assert report.defective <= report.covered
    assert report.ok is True
    assert report.unaudited
    summary = report.as_text().splitlines()[0]
    assert "covered" in summary and "unaudited" in summary and "defect" in summary

def test_fleet_audit_surfaces_the_families_with_no_declared_result_tree():
    """The uncovered set is explicit: required sources that no tree can be checked against.

    The required-source and renderer-kind invariants are statements about a view
    and the ``expected_files.yaml`` identities a family publishes. Of the 56 Tasks,
    22 are covered (a declared tree lets their required sources be evaluated) and
    34 are unaudited -- each declaring a required view source with no shipped tree
    to check it against. This test names that gap rather than letting the audit
    report those Tasks green, and it fails if the set changes -- either a family
    gained a tree (good; update the expected set) or a required source appeared
    where nothing can validate it.
    """
    report = audit_fleet(str(RUNNERS), server_dir=str(ROOT))
    undeclared = {
        finding.task for finding in report.findings if finding.code == "result.required_source_undeclared_tree"
    }
    # Tasks whose required view sources have no declared result tree to resolve
    # against. Each entry is a family that ships a ``result_workspace`` with a
    # required source but no ``expected_files.yaml``.
    expected = {
        "deeppocket", "diffdock", "dynamicmpnn", "easifa", "esm_1v",
        "esm_if1", "esm_msa", "evosplit_cluster", "fampnn_design", "fampnn_pack", "fampnn_score",
        "freebindcraft", "frodock", "frustrampnn", "geodock", "gnina", "hypermpnn", "lasermpnn",
        "ligandmpnn", "molprobity_validate", "p2rank", "pallatom_generate", "placer", "ppiformer_ddg",
        "ppiformer_embed", "prime", "prime_dms", "proteinmpnn", "pythia_ddg", "rfdiffusion",
        "rfdiffusion2_ligand_binder", "rfdiffusion2_motif_scaffold", "solublempnn", "thermompnn",
    }
    assert undeclared == expected
    # And the tree-bearing families are not in it: those ARE fully audited.
    assert "fpocket" not in undeclared and "gremlin_lh_fit" not in undeclared
