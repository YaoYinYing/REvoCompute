# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Architecture checks for the task.yaml-owned parameter contract."""

from __future__ import annotations

from jsonschema import Draft202012Validator
import pytest

from revocompute import task_types


def test_seed_ui_hint_rejects_non_integer_parameter():
    schema = {"properties": {"seed": {"type": "string", "x-ui-control": {"kind": "seed"}}}}
    with pytest.raises(ValueError, match="require an integer"):
        task_types._load_task_params(None, schema, "invalid_seed")  # pylint: disable=protected-access


def test_seed_generation_bounds_are_validated_separately_from_api_bounds():
    schema = {
        "type": "object",
        "properties": {
            "seed": {
                "type": "integer",
                "default": 0,
                "minimum": 0,
                "maximum": 10,
                "x-ui-control": {"kind": "seed", "random": {"minimum": 1, "maximum": 10}},
            }
        },
    }
    (parameter,) = task_types._load_task_params(None, schema, "sentinel_seed")  # pylint: disable=protected-access
    assert parameter.ui_control == {"kind": "seed", "random": {"minimum": 1, "maximum": 10}}
    Draft202012Validator(schema).validate({"seed": 0})

    schema["properties"]["seed"]["x-ui-control"]["random"]["minimum"] = -1
    with pytest.raises(ValueError, match="within the API-valid range"):
        task_types._load_task_params(None, schema, "invalid_bounds")  # pylint: disable=protected-access
