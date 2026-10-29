# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Task parameter schema errors name the parameter that failed."""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from revocompute.schemas import TaskSubmissionRequest

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["num_samples"],
    "properties": {
        "num_samples": {"type": "integer"},
        "use_sm": {"type": "boolean"},
        "predict_ligand": {"type": "string", "default": ""},
        "target_res": {"type": "string", "pattern": "^[A-Za-z0-9]+-[0-9]+$"},
    },
    "allOf": [
        {
            "if": {"properties": {"use_sm": {"const": False}}, "required": ["use_sm"]},
            "then": {"properties": {"predict_ligand": {"maxLength": 0}}},
        }
    ],
}


@pytest.fixture(autouse=True)
def _synthetic_task(monkeypatch):
    task_type = SimpleNamespace(schema=_SCHEMA, params=[])
    monkeypatch.setattr("revocompute.task_types.get", lambda _name: (task_type, None))


def _message(params: dict) -> str:
    with pytest.raises(ValidationError) as excinfo:
        TaskSubmissionRequest.model_validate({"task_type": "synthetic", "params": params})
    return str(excinfo.value)


def test_pattern_error_names_the_parameter():
    assert "Parameter 'target_res' is invalid" in _message({"num_samples": 1, "target_res": "not-a-residue"})


def test_composite_rule_error_names_the_parameter():
    assert "Parameter 'predict_ligand' is invalid" in _message(
        {"num_samples": 1, "use_sm": False, "predict_ligand": "LIG"}
    )


def test_missing_required_parameter_still_reports_its_name():
    assert "num_samples" in _message({})
