# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Architecture checks for the task.yaml-owned parameter contract."""

from __future__ import annotations

from pathlib import Path
import re

from jsonschema import Draft202012Validator
import pytest
import yaml

from revocompute import task_types


ROOT = Path(__file__).resolve().parents[1]
RUNNERS = ROOT / "docker" / "runners"
SCHEMA_TYPES = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}


def test_every_discovered_parameter_is_projected_from_task_schema(monkeypatch):
    monkeypatch.setenv("REVOCOMPUTE_IMAGE_DIR", "/tmp/images")
    task_types.discover_plugins(str(RUNNERS))
    for task in task_types.list_types():
        schema_properties = task.schema.get("properties", {})
        assert [param.name for param in task.params] == list(schema_properties)
        for param in task.params:
            declaration = schema_properties[param.name]
            assert param.type == SCHEMA_TYPES[declaration["type"]]
            assert param.default == declaration.get("default")
            assert param.minimum == declaration.get("minimum")
            assert param.maximum == declaration.get("maximum")
            assert tuple(param.choices) == tuple(declaration.get("enum", ()))
            assert param.description == declaration["description"]
            control = declaration.get("x-ui-control")
            assert param.ui_control.get("kind") == (control or {}).get("kind")
            if param.ui_control:
                assert declaration["type"] == "integer"
                assert param.minimum <= param.ui_control["random"]["minimum"]
                if param.maximum is not None:
                    assert param.ui_control["random"]["maximum"] <= param.maximum


def test_every_user_facing_parameter_has_a_description():
    for task_yaml in RUNNERS.glob("*/tasks/*/task.yaml"):
        document = yaml.safe_load(task_yaml.read_text(encoding="utf-8")) or {}
        properties = document.get("parameters", {}).get("properties", {})
        for name, declaration in properties.items():
            description = declaration.get("description")
            assert isinstance(description, str) and description.strip(), f"{task_yaml}: {name}"
            normalized_description = re.sub(r"[^a-z0-9]+", " ", description.lower()).strip()
            normalized_name = name.lower().replace("_", " ")
            assert len(normalized_description.split()) >= 3, f"{task_yaml}: {name}"
            assert normalized_description != normalized_name, f"{task_yaml}: {name}"


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


def test_runner_yaml_cannot_be_a_second_user_parameter_default_source():
    for runner_yaml in RUNNERS.glob("*/runner.yaml"):
        document = yaml.safe_load(runner_yaml.read_text(encoding="utf-8")) or {}
        assert "defaults" not in document, runner_yaml


def test_runner_scripts_do_not_supply_parameter_defaults():
    for script in RUNNERS.glob("*/run.sh"):
        text = script.read_text(encoding="utf-8")
        matches = re.findall(r"_parse_param\s+[A-Za-z_][A-Za-z0-9_]*\s+([^)]*)\)", text)
        assert not matches, script
        assert not re.search(r'^\s*:\s+"\$\{[A-Za-z_][A-Za-z0-9_]*:=', text, re.MULTILINE), script
