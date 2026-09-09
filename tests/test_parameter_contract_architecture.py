# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Architecture checks for the task.yaml-owned parameter contract."""

from __future__ import annotations

from pathlib import Path
import re

import yaml

from revocompute import task_types


ROOT = Path(__file__).resolve().parents[1]
RUNNERS = ROOT / "docker" / "runners"


def test_every_discovered_parameter_is_projected_from_task_schema(monkeypatch):
    monkeypatch.setenv("REVOCOMPUTE_IMAGE_DIR", "/tmp/images")
    task_types.discover_plugins(str(RUNNERS))
    for task in task_types.list_types():
        schema_properties = task.schema.get("properties", {})
        assert [param.name for param in task.params] == list(schema_properties)
        for param in task.params:
            declaration = schema_properties[param.name]
            assert param.default == declaration.get("default")
            assert param.minimum == declaration.get("minimum")
            assert param.maximum == declaration.get("maximum")
            assert tuple(param.choices) == tuple(declaration.get("enum", ()))


def test_runner_yaml_cannot_be_a_second_user_parameter_default_source():
    for runner_yaml in RUNNERS.glob("*/runner.yaml"):
        document = yaml.safe_load(runner_yaml.read_text(encoding="utf-8")) or {}
        assert "defaults" not in document, runner_yaml


def test_runner_scripts_do_not_supply_parameter_defaults():
    for script in RUNNERS.glob("*/run.sh"):
        text = script.read_text(encoding="utf-8")
        matches = re.findall(r"_parse_param\s+[A-Za-z_][A-Za-z0-9_]*\s+([^)]*)\)", text)
        assert all(not value.strip() or value.strip() in {'""', "''"} for value in matches), script
        assert not re.search(r'^\s*:\s+"\$\{[A-Za-z_][A-Za-z0-9_]*:=', text, re.MULTILINE), script
