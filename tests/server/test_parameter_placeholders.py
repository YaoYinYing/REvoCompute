# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The optional-field placeholder is presentation only.

The owning schema may carry ``x-ui-placeholder`` on an optional string field.
Discovery validates the annotation, the schema endpoint projects it unchanged,
and the annotation never becomes a default, a required value, a stored form
value, or a submitted parameter.
"""

from __future__ import annotations

import io
import json
from dataclasses import replace

import pytest
from jsonschema import Draft202012Validator

import conftest
from conftest import _load_pssm_module, _test_client_auth
from revocompute.task_types import TaskInputRole, _validate_ui_annotations

TASK = "hinted_task"
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "note": {
            "type": "string",
            "title": "Note",
            "x-ui-placeholder": "e.g. a short free-text note",
        },
        "seed": {"type": "integer", "default": 0, "minimum": 0},
    },
}


def _module(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    base, runner = module.task_runtime._get_task_type("cpu_runner")
    conftest._inject_task_type(
        module,
        replace(
            base,
            name=TASK,
            inputs=(TaskInputRole("sequence", "Sequence", "protein_sequence", ("fasta",), 1, 1),),
            params=(),
            schema=SCHEMA,
        ),
        runner,
    )
    return module


def test_a_placeholder_is_accepted_only_on_an_optional_string_field():
    _validate_ui_annotations(SCHEMA, TASK)

    required = json.loads(json.dumps(SCHEMA))
    required["required"] = ["note"]
    with pytest.raises(ValueError, match="required field"):
        _validate_ui_annotations(required, TASK)

    non_string = json.loads(json.dumps(SCHEMA))
    non_string["properties"]["seed"]["x-ui-placeholder"] = "5"
    with pytest.raises(ValueError, match="non-string field"):
        _validate_ui_annotations(non_string, TASK)

    blank = json.loads(json.dumps(SCHEMA))
    blank["properties"]["note"]["x-ui-placeholder"] = "   "
    with pytest.raises(ValueError, match="invalid"):
        _validate_ui_annotations(blank, TASK)

    too_long = json.loads(json.dumps(SCHEMA))
    too_long["properties"]["note"]["x-ui-placeholder"] = "x" * 201
    with pytest.raises(ValueError, match="invalid"):
        _validate_ui_annotations(too_long, TASK)


def test_the_annotation_is_projected_but_is_not_a_default_or_required_value(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    served = module.app.test_client().get(f"/compute/api/task-parameters/{TASK}").get_json()
    assert served["properties"]["note"]["x-ui-placeholder"] == "e.g. a short free-text note"
    assert "default" not in served["properties"]["note"]
    assert "required" not in served

    # The annotation does not change what the schema accepts: the optional field
    # may be absent, and a placeholder string is not implicitly a value.
    Draft202012Validator(served).validate({"seed": 0})
    Draft202012Validator(served).validate({})


def test_preflight_keeps_an_empty_optional_field_absent(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    response = module.app.test_client().post(
        f"/compute/api/preflight/{TASK}",
        headers=_test_client_auth(module),
        data={
            "task_type": TASK,
            "files": (io.BytesIO(b">sample\nACDEFG\n"), "sequence.fasta"),
            "input_roles": "sequence",
            "workspace": json.dumps({"version": 2, "capabilities": {}}),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["valid"] is True
    assert "note" not in payload["normalized_params"]
    assert payload["normalized_params"]["seed"] == 0
    assert module.task_store.list_tasks() == []
