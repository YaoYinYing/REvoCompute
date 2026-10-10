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

KNOWN_DEFECTS: dict[tuple[str, str], str] = {
    ("foundry_rfd3_design", "result.required_source_unaddressed"): (
        "RFD3 design writes '<name>_model_<n>.cif.gz' (pinned upstream "
        "rfd3/engine.py), but the foundry family's single shared expected_files.yaml "
        "declares only the RF3 fold spelling '*_model.cif' under 'structures', so the "
        "design tasks' primary candidates have no declared logical identity and the "
        "shared storyboard resolves no structures for them. Resolving it means giving "
        "the design tasks their own result tree/storyboard, which is a family "
        "redesign outside this audit."
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
    """Every finding beyond the recorded defects is either a defect or a coverage gap.

    The fleet is NOT claimed clean. Three categories are asserted separately:
    the covered Tasks whose declarations the audit could evaluate, the unaudited
    Tasks that require a view source but ship no ``expected_files.yaml``, and the
    recorded known defects. The test fails if any finding appears that is not one
    of the recorded defects or the explicit ``result.required_source_undeclared_tree``
    coverage boundary, so the reported state cannot drift into looking greener
    than it is.
    """
    report = audit_fleet(str(RUNNERS), server_dir=str(ROOT))

    unrecorded = [
        finding
        for finding in report.findings
        if (finding.task, finding.code) not in KNOWN_DEFECTS
        and finding.code != "result.required_source_undeclared_tree"
    ]
    assert unrecorded == [], "\n".join(str(finding) for finding in unrecorded)
    for finding in report.findings:
        assert finding.task and finding.task != "-"
        if finding.code in {"result.required_source_unaddressed", "result.required_source_undeclared_tree"}:
            assert finding.view
    # Positive control: the recorded foundry defect is genuinely *present*, not
    # merely allowed. If the audit stopped reporting it, the allowlist above would
    # silently stop covering anything and the fleet would look cleaner than it is.
    assert ("foundry_rfd3_design", "result.required_source_unaddressed") in {
        (finding.task, finding.code) for finding in report.findings
    }

def test_fleet_report_separates_covered_unaudited_and_defective():
    """Coverage (a partition) and defect status (orthogonal) are both reported.

    The audit's claim is bounded. Coverage asks whether a Task's declarations
    could be evaluated at all: covered (a declared result tree) versus unaudited
    (no tree), which partition the fleet. Defect status is orthogonal -- the two
    Foundry design Tasks are covered (they ship a tree) and still defective. The
    report exposes both so it can never be read as "the whole fleet passed", and
    never forces the defect set to fit the coverage partition.
    """
    report = audit_fleet(str(RUNNERS), server_dir=str(ROOT))

    # Coverage is a partition ...
    assert report.covered | report.unaudited == frozenset(report.tasks)
    assert not (report.covered & report.unaudited)
    assert len(report.covered) == 20 and len(report.unaudited) == 36
    # ... and defect status is orthogonal: the defective foundry Tasks are covered,
    # not a third coverage bucket.
    assert set(report.defective) == {"foundry_rfd3_design", "foundry_rfd3na_design"}
    assert report.defective <= report.covered
    # A concrete defect means the report is not "ok" even though the only other
    # findings are coverage-boundary notices.
    assert report.ok is False
    summary = report.as_text().splitlines()[0]
    assert "covered" in summary and "unaudited" in summary and "defect" in summary

def test_fleet_audit_surfaces_the_families_with_no_declared_result_tree():
    """The uncovered set is explicit: required sources that no tree can be checked against.

    The required-source and renderer-kind invariants are statements about a view
    and the ``expected_files.yaml`` identities a family publishes. Of the 56 Tasks,
    20 are covered (a declared tree lets their required sources be evaluated) and
    36 are unaudited -- each declaring a required view source with no shipped tree
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
        "autodock_vina", "bioemu", "deeppocket", "diffdock", "dynamicmpnn", "easifa", "esm_1v",
        "esm_if1", "esm_msa", "evosplit_cluster", "fampnn_design", "fampnn_pack", "fampnn_score",
        "freebindcraft", "frodock", "frustrampnn", "geodock", "gnina", "hypermpnn", "lasermpnn",
        "ligandmpnn", "molprobity_validate", "p2rank", "pallatom_generate", "placer", "ppiformer_ddg",
        "ppiformer_embed", "prime", "prime_dms", "proteinmpnn", "pythia_ddg", "rfdiffusion",
        "rfdiffusion2_ligand_binder", "rfdiffusion2_motif_scaffold", "solublempnn", "thermompnn",
    }
    assert undeclared == expected
    # And the tree-bearing families are not in it: those ARE fully audited.
    assert "fpocket" not in undeclared and "gremlin_lh_fit" not in undeclared
