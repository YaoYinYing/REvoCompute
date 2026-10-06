# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Plan before execute: determinism, effective actions, and stale-plan rejection.

These cases pin the control-plane contract that a privileged action is planned
against a content-addressed evidence snapshot, that the plan is deterministic for
identical evidence, and that execution against changed evidence fails closed
rather than silently rebasing onto a different operation.
"""

from __future__ import annotations

import pytest
from revocompute.admission import RunnerReadinessStatus
from revocompute.operator_plan import (
    OperatorPlanError,
    StalePlanError,
    build_plan,
    evidence_digest,
    verify_plan,
)
from revocompute.runner_readiness import RunnerReadiness


def _readiness(
    family: str = "demo",
    *,
    status: RunnerReadinessStatus = RunnerReadinessStatus.VALIDATION_STALE,
    reason_code: str = "RUNTIME_BUNDLE_CHANGED",
    receipt_valid: bool = False,
    receipt_tested_at: str | None = "2026-01-01T00:00:00Z",
    runtime_bundle_sha256: str | None = "sha256:bundle",
) -> RunnerReadiness:
    return RunnerReadiness(
        runner_family=family,
        status=status,
        reason_code=reason_code,
        message="stale",
        doctor_ok=True,
        sif_path=f"/images/{family}.sif",
        sif_exists=True,
        sif_sha256="sha256:sif",
        build_provenance_current=True,
        build_provenance_digest="sha256:build",
        runtime_bundle_sha256=runtime_bundle_sha256,
        receipt_exists=receipt_tested_at is not None,
        receipt_valid=receipt_valid,
        receipt_tested_at=receipt_tested_at,
    )


def test_plan_is_deterministic_for_identical_evidence():
    first = build_plan("runner.repair", runner_family="demo", readiness=_readiness())
    second = build_plan("runner.repair", runner_family="demo", readiness=_readiness())
    assert first.plan_digest == second.plan_digest
    assert first.evidence_digest == second.evidence_digest


def test_a_changed_evidence_snapshot_changes_the_plan_digest():
    stale = build_plan("runner.live_test", runner_family="demo", readiness=_readiness())
    moved = build_plan(
        "runner.live_test",
        runner_family="demo",
        readiness=_readiness(receipt_tested_at="2026-03-03T00:00:00Z"),
    )
    assert stale.plan_digest != moved.plan_digest


def test_repair_of_a_stale_validation_reuses_the_sif_without_rebuilding():
    plan = build_plan("runner.repair", runner_family="demo", readiness=_readiness())
    assert plan.effective_actions == ("live_test",)
    assert "build_sif" in plan.not_required
    assert "restart_server" in plan.not_required
    assert "cancel_running_tasks" in plan.not_required


def test_repair_of_a_stale_build_rebuilds_before_validating():
    plan = build_plan(
        "runner.repair",
        runner_family="demo",
        readiness=_readiness(status=RunnerReadinessStatus.BUILD_STALE, reason_code="BUILD_PROVENANCE_STALE"),
    )
    assert plan.effective_actions == ("build", "live_test")


def test_repaired_configuration_is_refused_not_approximated():
    for status in (RunnerReadinessStatus.NOT_CONFIGURED,):
        with pytest.raises(OperatorPlanError, match="misconfiguration"):
            build_plan("runner.repair", runner_family="demo", readiness=_readiness(status=status, reason_code="DOCTOR_FAILED"))


def test_an_already_ready_runner_has_nothing_to_repair():
    with pytest.raises(OperatorPlanError, match="already READY"):
        build_plan(
            "runner.repair",
            runner_family="demo",
            readiness=_readiness(status=RunnerReadinessStatus.READY, reason_code="READY", receipt_valid=True),
        )


def test_a_plan_for_a_different_family_is_refused():
    with pytest.raises(OperatorPlanError, match="does not match"):
        build_plan("runner.status", runner_family="other", readiness=_readiness())


def test_mutation_tier_plans_hold_an_exclusive_lease():
    plan = build_plan("runner.repair", runner_family="demo", readiness=_readiness())
    assert plan.lease_scope == "runner/demo"
    assert plan.tier == "mutate"
    status = build_plan("runner.status", runner_family="demo", readiness=_readiness())
    assert status.lease_scope == "read-only"


def test_confirmation_is_declared_not_assumed():
    promote = build_plan(
        "runner.promote",
        runner_family="demo",
        readiness=_readiness(status=RunnerReadinessStatus.READY, reason_code="READY", receipt_valid=True),
    )
    assert promote.requires_confirmation is True
    assert build_plan("runner.doctor", runner_family="demo", readiness=_readiness()).requires_confirmation is False


def test_unknown_action_fails_closed():
    with pytest.raises(Exception):
        build_plan("runner.exec", runner_family="demo", readiness=_readiness())


def test_verifying_a_current_plan_succeeds():
    readiness = _readiness()
    plan = build_plan("runner.repair", runner_family="demo", readiness=readiness)
    verify_plan(plan, readiness)  # no exception


def test_a_plan_is_rejected_when_evidence_changed_since_planning():
    plan = build_plan("runner.repair", runner_family="demo", readiness=_readiness())
    # A new receipt was written / the runtime bundle moved between plan and execute.
    changed = _readiness(receipt_valid=True, receipt_tested_at="2026-02-02T00:00:00Z", runtime_bundle_sha256="sha256:moved")
    with pytest.raises(StalePlanError, match="review the new plan"):
        verify_plan(plan, changed)


def test_a_plan_is_rejected_when_the_family_changed():
    plan = build_plan("runner.repair", runner_family="demo", readiness=_readiness())
    with pytest.raises(StalePlanError, match="family changed"):
        verify_plan(plan, _readiness(family="other"))


def test_evidence_digest_ignores_display_only_fields():
    plan = build_plan("runner.repair", runner_family="demo", readiness=_readiness())
    assert evidence_digest(_readiness()) == plan.evidence_digest


def test_cli_reference_is_present_only_where_a_stable_cli_exists():
    plan = build_plan("runner.repair", runner_family="demo", readiness=_readiness())
    assert plan.cli_reference is None  # repair has no single CLI equivalent
    live = build_plan("runner.live_test", runner_family="demo", readiness=_readiness())
    assert live.cli_reference == "restart.sh live-test --runner demo"


def test_the_plan_serializes_the_impact_before_confirmation():
    payload = build_plan("runner.repair", runner_family="demo", readiness=_readiness()).as_dict()
    assert payload["current_state"] == "VALIDATION_STALE"
    assert payload["reason_code"] == "RUNTIME_BUNDLE_CHANGED"
    assert payload["effective_actions"] == ["live_test"]
    assert payload["plan_digest"].startswith("sha256:")
    assert any(item["operation"] == "build_sif" for item in payload["not_required"])
    assert any(item["label"] == "Build a new Runner SIF" for item in payload["not_required"])

