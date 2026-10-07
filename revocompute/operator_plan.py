# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Plan before execute: the typed, content-addressed plan for an operator action.

A privileged action is never executed from a bare request.  The control core
first produces a plan that names the target, the current derived state and its
machine-readable reason, the ordered effective actions it will take, the
operations it explicitly will *not* take, the lease it will hold, and the
evidence snapshot it was computed against.  The plan is content-addressed, so
identical evidence always yields the same digest, and an execution that arrives
against changed evidence is rejected as stale rather than silently rebased onto
a materially different operation.

This module owns planning only.  Execution, leases, and leases' durability live
in :mod:`revocompute.operator_jobs`; the closed action vocabulary lives in
:mod:`revocompute.operator_actions`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from revocompute.admission import RunnerReadinessStatus
from revocompute.operator_actions import (
    LeaseScope,
    OperatorAction,
    get_action,
    lease_key,
    normalize_parameters,
    runner_family_is_resolvable,
)
from revocompute.runner_readiness import RunnerReadiness
from revocompute.serialization import canonical_digest

#: Operations a plan can name as *not required*, so the operator sees that a
#: narrow repair will not, for example, rebuild the SIF or restart the server.
_NOT_REQUIRED_LIBRARY = {
    "build_sif": "Build a new Runner SIF",
    "prepare_candidate": "Stage a new Runner candidate",
    "write_receipt": "Write a new live-test receipt",
    "promote_artifact": "Activate a different artifact",
    "restart_server": "Restart the server",
    "cancel_running_tasks": "Cancel or disturb running scientific tasks",
}

#: The read-only CLI spelling of an action, shown to the operator for handoff.
#: It is reference text only — never the execution mechanism — and is absent
#: when no stable CLI equivalent exists.
_CLI_REFERENCE = {
    "runner.status": "restart.sh runner-status --runner {family}",
    "runner.live_test": "restart.sh live-test --runner {family}",
    "runner.prepare": "restart.sh prepare",
}


class OperatorPlanError(ValueError):
    """A plan could not be produced; the message is operator-facing."""


class StalePlanError(OperatorPlanError):
    """The evidence changed between planning and execution.

    The caller must discard the plan and replan; it must not execute the old
    plan against the new evidence.
    """


@dataclass(frozen=True, slots=True)
class OperatorPlan:
    """A deterministic, content-addressed plan for one operator action."""

    action_id: str
    runner_family: str
    requested_intent: str
    current_state: str
    reason_code: str
    #: The evidence snapshot the plan was computed against (content-addressed).
    evidence_digest: str
    effective_actions: tuple[str, ...]
    expected_effects: tuple[str, ...]
    not_required: tuple[str, ...]
    lease_scope: str
    requires_confirmation: bool
    next_state_effect: str
    cli_reference: str | None
    plan_digest: str
    #: Wall-clock time the plan was produced.  Excluded from ``plan_digest`` so
    #: identical evidence stays byte-identical; carried for display/audit only.
    evaluated_at: float = field(default=0.0)

    @property
    def tier(self) -> str:
        return get_action(self.action_id).tier.value

    def as_dict(self) -> dict[str, object]:
        return {
            "action": self.action_id,
            "tier": self.tier,
            "runner_family": self.runner_family,
            "requested_intent": self.requested_intent,
            "current_state": self.current_state,
            "reason_code": self.reason_code,
            "evidence_digest": self.evidence_digest,
            "effective_actions": list(self.effective_actions),
            "expected_effects": list(self.expected_effects),
            "not_required": [
                {"operation": name, "label": _NOT_REQUIRED_LIBRARY.get(name, name)} for name in self.not_required
            ],
            "lease_scope": self.lease_scope,
            "requires_confirmation": self.requires_confirmation,
            "next_state_effect": self.next_state_effect,
            "cli_reference": self.cli_reference,
            "plan_digest": self.plan_digest,
            "evaluated_at": self.evaluated_at,
        }


def evidence_snapshot(readiness: RunnerReadiness) -> dict[str, object]:
    """The plan-relevant identity of a readiness evaluation."""
    return {
        "runner_family": readiness.runner_family,
        "status": readiness.status.value,
        "reason_code": readiness.reason_code,
        "build_provenance_digest": readiness.build_provenance_digest,
        "sif_sha256": readiness.sif_sha256,
        "runtime_bundle_sha256": readiness.runtime_bundle_sha256,
        "receipt_exists": readiness.receipt_exists,
        "receipt_valid": readiness.receipt_valid,
        "receipt_tested_at": readiness.receipt_tested_at,
        "receipt_sif_sha256": readiness.receipt_sif_sha256,
        "receipt_runtime_bundle_sha256": readiness.receipt_runtime_bundle_sha256,
        "receipt_configuration_digest": readiness.receipt_configuration_digest,
        "receipt_test_definition_digest": readiness.receipt_test_definition_digest,
    }


def evidence_digest(readiness: RunnerReadiness) -> str:
    return canonical_digest(evidence_snapshot(readiness))


def _effective_actions(action: OperatorAction, readiness: RunnerReadiness) -> tuple[str, ...]:
    """The ordered operations the control core will actually perform."""
    if action.id == "runner.repair":
        if readiness.status in (RunnerReadinessStatus.NOT_BUILT, RunnerReadinessStatus.BUILD_STALE):
            return ("build", "live_test")
        if readiness.status in (RunnerReadinessStatus.NOT_VALIDATED, RunnerReadinessStatus.VALIDATION_STALE):
            return ("live_test",)
        if readiness.status is RunnerReadinessStatus.READY:
            raise OperatorPlanError("Runner is already READY; there is nothing to repair")
        # NOT_CONFIGURED / a doctor failure is a configuration defect, not a
        # stale evidence state: no automated repair is safe.
        raise OperatorPlanError("Runner misconfiguration must be corrected before an automated repair can be planned")
    return {
        "runner.status": ("inspect",),
        "runner.doctor": ("doctor",),
        "runner.prepare": ("prepare",),
        "runner.build": ("build",),
        "runner.live_test": ("live_test",),
        "runner.promote": ("promote",),
        "runner.rollback": ("rollback",),
    }[action.id]


_EFFECT_TEXT = {
    "inspect": "Read the current derived readiness and evidence",
    "doctor": "Re-run the Runner contract diagnostics",
    "prepare": "Stage a candidate Runner build",
    "build": "Build the candidate SIF from its definition",
    "live_test": "Run bounded smoke acceptance and write a receipt on success",
    "promote": "Activate the validated candidate artifact",
    "rollback": "Restore the previous known-validated active artifact",
}

#: Operations a plan will not perform, given its own effective actions.
_NOT_REQUIRED_FOR: dict[str, tuple[str, ...]] = {
    "inspect": ("build_sif", "write_receipt", "promote_artifact", "restart_server", "cancel_running_tasks"),
    "doctor": ("build_sif", "write_receipt", "promote_artifact", "restart_server", "cancel_running_tasks"),
    "prepare": ("promote_artifact", "restart_server", "cancel_running_tasks"),
    "build": ("restart_server", "cancel_running_tasks"),
    "live_test": ("build_sif", "restart_server", "cancel_running_tasks"),
    "promote": ("build_sif", "write_receipt", "restart_server", "cancel_running_tasks"),
    "rollback": ("build_sif", "write_receipt", "restart_server", "cancel_running_tasks"),
}


def _expected_effects(actions: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_EFFECT_TEXT[action] for action in actions)


def _not_required(actions: tuple[str, ...]) -> tuple[str, ...]:
    """Every library operation this plan will not perform.

    An operation is listed here when none of the plan's effective actions
    performs it, so the operator can see that a narrow repair will not, say,
    rebuild the SIF or restart the server.
    """
    performed: set[str] = set()
    for action in actions:
        # A library operation is performed when some effective action does not
        # list it as "not required".
        performed.update(name for name in _NOT_REQUIRED_LIBRARY if name not in _NOT_REQUIRED_FOR.get(action, ()))
    return tuple(sorted(name for name in _NOT_REQUIRED_LIBRARY if name not in performed))


def _cli_reference(action: OperatorAction, family: str) -> str | None:
    template = _CLI_REFERENCE.get(action.id)
    return template.format(family=family) if template else None


def build_plan(
    action_id: str,
    *,
    runner_family: str,
    readiness: RunnerReadiness,
    parameters: dict[str, object] | None = None,
    clock: Callable[[], float] = time.time,
) -> OperatorPlan:
    """Produce the deterministic plan for one action against one readiness snapshot.

    Raises :class:`OperatorPlanError` when the action cannot be planned (an
    unknown action, an unresolvable family, a request for a repair that has no
    safe automatic path).  An action whose declared tier requires confirmation
    yields a plan that says so; it is never silently auto-confirmed.
    """
    action = get_action(action_id)
    if not runner_family_is_resolvable(runner_family):
        raise OperatorPlanError("A canonical Runner family is required to plan an action")
    if readiness.runner_family != runner_family:
        raise OperatorPlanError("Readiness snapshot does not match the planned Runner family")
    supplied = dict(parameters or {})
    # The target family is the canonical resolved identifier, never a caller
    # field: it comes from the plan request and is validated as an identifier.
    supplied["runner_family"] = runner_family
    normalized = normalize_parameters(action, supplied)
    effective = _effective_actions(action, readiness)
    scope = lease_key(action, normalized)
    digest = canonical_digest(
        {
            "action": action.id,
            "runner_family": runner_family,
            "evidence_digest": evidence_digest(readiness),
            "effective_actions": list(effective),
            "lease_scope": scope,
            "next_state_effect": action.next_state_effect,
        }
    )
    return OperatorPlan(
        action_id=action.id,
        runner_family=runner_family,
        requested_intent=action.id,
        current_state=readiness.status.value,
        reason_code=readiness.reason_code,
        evidence_digest=evidence_digest(readiness),
        effective_actions=effective,
        expected_effects=_expected_effects(effective),
        not_required=_not_required(effective),
        lease_scope=scope,
        requires_confirmation=action.requires_confirmation,
        next_state_effect=action.next_state_effect,
        cli_reference=_cli_reference(action, runner_family),
        plan_digest=digest,
        evaluated_at=clock(),
    )


def verify_plan(plan: OperatorPlan, readiness: RunnerReadiness) -> None:
    """Revalidate a plan against the evidence present at execution time.

    A plan is rejected — never silently rebased — when the target family's
    evidence digest, effective actions, or lease scope changed between planning
    and execution.  The caller must replan and re-confirm.
    """
    if readiness.runner_family != plan.runner_family:
        raise StalePlanError("Runner family changed since planning; replan before executing")
    current = evidence_digest(readiness)
    if current != plan.evidence_digest:
        raise StalePlanError("State changed; review the new plan")
    action = get_action(plan.action_id)
    if _effective_actions(action, readiness) != plan.effective_actions:
        raise StalePlanError("State changed; review the new plan")
    if action.lease_scope is not LeaseScope.READ_ONLY and plan.lease_scope == LeaseScope.READ_ONLY.value:
        raise StalePlanError("Plan no longer holds the required exclusive lease; replan before executing")


__all__ = [
    "OperatorPlan",
    "OperatorPlanError",
    "StalePlanError",
    "build_plan",
    "evidence_digest",
    "evidence_snapshot",
    "verify_plan",
]
