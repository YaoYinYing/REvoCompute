# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Level 0 security: the typed operator-action model, without HTTP or execution.

These cases pin the lowest-level contract of the control plane: the action set is
closed, parameters are bounded and typed, and no action can carry a shell
command, argv element, environment variable, or filesystem path.
"""

from __future__ import annotations

import pytest
from revocompute.operator_actions import (
    ActionTier,
    LeaseScope,
    OperatorActionError,
    action_schemas,
    get_action,
    lease_key,
    list_actions,
    normalize_parameters,
)

#: Adversarial parameter values that must never resolve to another family, an
#: argv element, an environment variable, or a path outside the owned root.
_HOSTILE = [
    ";",
    "&&",
    "|",
    "$(id)",
    "`id`",
    "a\nb",
    "a\r\nb",
    "../etc/passwd",
    "/etc/passwd",
    "demo/../other",
    "-rf",
    "--runner",
    "0x00\x00",
    "‮ demo",
    "demo\x7f",
    "d" * 4096,
]


def test_action_ids_are_a_closed_registry():
    ids = {action.id for action in list_actions()}
    assert ids == {
        "runner.status",
        "runner.doctor",
        "runner.prepare",
        "runner.build",
        "runner.live_test",
        "runner.promote",
        "runner.rollback",
        "runner.repair",
    }
    assert {schema["id"] for schema in action_schemas()} == ids


@pytest.mark.parametrize("action_id", ["runner.exec", "runner", "", "runner.", "../runner.status", "runner.status;id"])
def test_unknown_actions_fail_closed(action_id):
    with pytest.raises(OperatorActionError, match="Unknown operator action"):
        get_action(action_id)


def test_no_action_declares_an_injection_field():
    forbidden = {"command", "argv", "args", "env", "environment", "path", "shell", "executable", "cmd"}
    for schema in action_schemas():
        declared = {parameter["name"] for parameter in schema["parameters"]}
        assert not (declared & forbidden), schema["id"]


def test_read_actions_are_read_only_and_activation_requires_confirmation():
    for action in list_actions():
        if action.tier is ActionTier.READ:
            assert action.lease_scope is LeaseScope.READ_ONLY
        if action.tier is ActionTier.ACTIVATE:
            assert action.requires_confirmation is True
            assert action.lease_scope is LeaseScope.RUNNER_EXCLUSIVE


def test_parameter_bounds_and_types_are_enforced():
    action = get_action("runner.live_test")
    # Bounds.
    with pytest.raises(OperatorActionError, match="not a valid identifier"):
        normalize_parameters(action, {"runner_family": "d" * 4096})
    # Type.
    with pytest.raises(OperatorActionError, match="non-empty text"):
        normalize_parameters(action, {"runner_family": 7})
    # Required.
    with pytest.raises(OperatorActionError, match="requires parameter"):
        normalize_parameters(action, {})


@pytest.mark.parametrize("value", _HOSTILE)
def test_hostile_parameter_values_are_rejected(value):
    for action in list_actions():
        if not any(parameter.name == "runner_family" for parameter in action.parameters):
            continue
        with pytest.raises(OperatorActionError):
            normalize_parameters(action, {"runner_family": value})


def test_unknown_parameters_are_rejected_not_ignored():
    action = get_action("runner.build")
    for extra in ({"command": "rm -rf /"}, {"env": {"PATH": "/tmp"}}, {"path": "/etc/passwd"}, {"argv": ["sh"]}):
        with pytest.raises(OperatorActionError, match="Unknown parameter"):
            normalize_parameters(action, {"runner_family": "demo", **extra})


def test_lease_key_is_one_family_or_the_read_plane():
    read = get_action("runner.status")
    assert lease_key(read, normalize_parameters(read, {"runner_family": "demo"})) == "read-only"

    exclusive = get_action("runner.build")
    assert lease_key(exclusive, normalize_parameters(exclusive, {"runner_family": "demo"})) == "runner/demo"

    # A missing family cannot mint an exclusive lease.
    with pytest.raises(OperatorActionError, match="Runner family is required"):
        lease_key(exclusive, {})
