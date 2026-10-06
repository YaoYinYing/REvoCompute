# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The closed set of typed Runner operator actions.

Web administration operates the existing control-module capabilities, never an
arbitrary command.  Every action is declared here with its parameter contract,
its lease scope, and whether it needs explicit confirmation; an action that is
not in this registry cannot be requested, and a parameter that is not in an
action's schema cannot be submitted.  There is deliberately no field for shell
text, argv, environment, or a filesystem path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_ACTION_IDS = re.compile(r"^runner\.[a-z_]+$")


class ActionTier(str, Enum):
    """How much the action can change, which sets its authorization bar."""

    READ = "read"
    MUTATE = "mutate"
    ACTIVATE = "activate"


class LeaseScope(str, Enum):
    """What the action blocks while it runs."""

    READ_ONLY = "read-only"
    RUNNER_EXCLUSIVE = "runner"


class OperatorActionError(ValueError):
    """A rejected action request; the message is already operator-facing."""


@dataclass(frozen=True, slots=True)
class ActionParameter:
    """One bounded, typed parameter.  No free-form text reaches any executor."""

    name: str
    kind: str  # "family" | "collection" | "task" | "bool"
    required: bool = False
    maximum_length: int = 64


@dataclass(frozen=True, slots=True)
class OperatorAction:
    id: str
    tier: ActionTier
    lease_scope: LeaseScope
    summary: str
    parameters: tuple[ActionParameter, ...] = ()
    requires_confirmation: bool = False
    next_state_effect: str = ""

    def schema(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tier": self.tier.value,
            "lease_scope": self.lease_scope.value,
            "summary": self.summary,
            "requires_confirmation": self.requires_confirmation,
            "next_state_effect": self.next_state_effect,
            "parameters": [
                {
                    "name": parameter.name,
                    "kind": parameter.kind,
                    "required": parameter.required,
                    "maximum_length": parameter.maximum_length,
                }
                for parameter in self.parameters
            ],
        }


#: Every action names its target family.  The value is a canonical Runner
#: family identifier resolved against the discovered registry, never a path.
_FAMILY = ActionParameter("runner_family", "family", required=True)
_COLLECTION = ActionParameter("collection", "collection")
_TASK = ActionParameter("task", "task")

_ACTIONS: tuple[OperatorAction, ...] = (
    OperatorAction(
        "runner.status",
        ActionTier.READ,
        LeaseScope.READ_ONLY,
        "Inspect the family's derived readiness and evidence",
        parameters=(_FAMILY,),
        next_state_effect="none",
    ),
    OperatorAction(
        "runner.doctor",
        ActionTier.READ,
        LeaseScope.READ_ONLY,
        "Re-run the family contract diagnostics",
        parameters=(_FAMILY,),
        next_state_effect="none",
    ),
    OperatorAction(
        "runner.prepare",
        ActionTier.MUTATE,
        LeaseScope.RUNNER_EXCLUSIVE,
        "Stage a candidate Runner build",
        parameters=(_FAMILY,),
        next_state_effect="NOT_BUILT -> NOT_VALIDATED candidate",
    ),
    OperatorAction(
        "runner.build",
        ActionTier.MUTATE,
        LeaseScope.RUNNER_EXCLUSIVE,
        "Build the staged Runner candidate SIF",
        parameters=(_FAMILY,),
        next_state_effect="NOT_BUILT -> NOT_VALIDATED",
    ),
    OperatorAction(
        "runner.live_test",
        ActionTier.MUTATE,
        LeaseScope.RUNNER_EXCLUSIVE,
        "Run bounded smoke acceptance against the candidate",
        parameters=(_FAMILY, _COLLECTION, _TASK),
        next_state_effect="NOT_VALIDATED -> READY when the receipt is accepted",
    ),
    OperatorAction(
        "runner.promote",
        ActionTier.ACTIVATE,
        LeaseScope.RUNNER_EXCLUSIVE,
        "Activate the validated candidate",
        parameters=(_FAMILY,),
        requires_confirmation=True,
        next_state_effect="candidate -> active artifact",
    ),
    OperatorAction(
        "runner.rollback",
        ActionTier.ACTIVATE,
        LeaseScope.RUNNER_EXCLUSIVE,
        "Restore the previous known-validated active artifact",
        parameters=(_FAMILY,),
        requires_confirmation=True,
        next_state_effect="active artifact -> previous validated artifact",
    ),
    OperatorAction(
        "runner.repair",
        ActionTier.MUTATE,
        LeaseScope.RUNNER_EXCLUSIVE,
        "Plan and run the shortest remediation for the current invalidation",
        parameters=(_FAMILY, _COLLECTION, _TASK),
        next_state_effect="derived; see the plan's effective actions",
    ),
)

_ACTIONS_BY_ID = {action.id: action for action in _ACTIONS}


def get_action(action_id: str) -> OperatorAction:
    """Resolve a declared action, failing closed for anything undeclared."""
    if not isinstance(action_id, str) or not _ACTION_IDS.fullmatch(action_id):
        raise OperatorActionError(f"Unknown operator action: {action_id!r}")
    try:
        return _ACTIONS_BY_ID[action_id]
    except KeyError:
        raise OperatorActionError(f"Unknown operator action: {action_id!r}") from None


def list_actions() -> tuple[OperatorAction, ...]:
    return _ACTIONS


def action_schemas() -> list[dict[str, Any]]:
    return [action.schema() for action in _ACTIONS]


def normalize_parameters(action: OperatorAction, raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate and bound an action's parameters against its declared schema.

    Unknown fields are rejected rather than ignored, so a request can never carry
    a smuggled argv, environment, or path that the executor might later honour.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise OperatorActionError("Action parameters must be a mapping")
    declared = {parameter.name: parameter for parameter in action.parameters}
    unknown = set(raw) - set(declared)
    if unknown:
        raise OperatorActionError(f"Unknown parameter(s) for {action.id}: {', '.join(sorted(unknown))}")
    normalized: dict[str, Any] = {}
    for name, parameter in declared.items():
        if name not in raw:
            if parameter.required:
                raise OperatorActionError(f"{action.id} requires parameter {name!r}")
            continue
        value = raw[name]
        if parameter.kind == "bool":
            if not isinstance(value, bool):
                raise OperatorActionError(f"Parameter {name!r} must be a boolean")
            normalized[name] = value
            continue
        if not isinstance(value, str) or not value:
            raise OperatorActionError(f"Parameter {name!r} must be non-empty text")
        if len(value) > parameter.maximum_length or not _IDENTIFIER.fullmatch(value):
            raise OperatorActionError(f"Parameter {name!r} is not a valid identifier")
        normalized[name] = value
    return normalized


def lease_key(action: OperatorAction, parameters: Mapping[str, Any]) -> str:
    """The operation scope a lease covers: one family, or the whole read plane."""
    if action.lease_scope is LeaseScope.READ_ONLY:
        return "read-only"
    family = parameters.get("runner_family")
    if not runner_family_is_resolvable(family):
        raise OperatorActionError("Runner family is required for an exclusive operator action")
    return f"runner/{family}"


def runner_family_is_resolvable(value: Any) -> bool:
    """Whether a value has the shape of a canonical Runner family identifier.

    Slashes, traversal sequences, leading dashes, and control characters are all
    rejected here, before any registry or filesystem lookup.
    """
    return isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value)) and not value.startswith("-")


__all__ = [
    "ActionParameter",
    "ActionTier",
    "LeaseScope",
    "OperatorAction",
    "OperatorActionError",
    "action_schemas",
    "get_action",
    "lease_key",
    "list_actions",
    "normalize_parameters",
    "runner_family_is_resolvable",
]
