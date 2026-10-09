# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Behavioral counterexamples for the Server/Runner dependency checker."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_test_boundaries", ROOT / "tools/check_test_boundaries.py")
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


@pytest.mark.parametrize("source", [
    'import docker.runners.new_family.adapter',
    'from docker.runner_testkit import runner_protocol',
    'importlib.import_module("docker.runners.new_family.adapter")',
    'family = "new_family"',
    'manifest = root / "docker/runners/new_family/plugin.yaml"',
    'endpoint = "/compute/api/types/new_family"',
])
def test_new_concrete_family_dependencies_are_rejected(source: str) -> None:
    assert checker.inspect_source(source, "tests/server/test_protocol.py", {"new_family"})


def test_comments_and_generic_protocol_vocabulary_are_allowed() -> None:
    source = '''"""new_family explains the motivating regression."""
# new_family is a motivating case only
role = "alignment"
name = manifest.id
root = Path("docker/runners")
'''
    assert checker.inspect_source(source, "tests/server/test_protocol.py", {"new_family"}) == []


def test_manifest_inventory_includes_added_families_and_task_ids(tmp_path: Path) -> None:
    family = tmp_path / "added_family"
    family.mkdir()
    (family / "plugin.yaml").write_text("id: added_runtime\ntasks: [task.yaml]\n", encoding="utf-8")
    (family / "task.yaml").write_text("id: added_task\n", encoding="utf-8")
    assert checker.runner_identities(tmp_path) == {"added_family", "added_runtime", "added_task"}


def test_empty_runner_inventory_cannot_authorize_a_boundary_receipt(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inventory is empty"):
        checker.runner_identities(tmp_path)


def test_explicit_exception_is_value_and_path_scoped(monkeypatch) -> None:
    monkeypatch.setattr(checker, "VALUE_EXCEPTIONS", {"revocompute/routes.py": {"/legacy/demo_family"}})
    source = 'redirect("/legacy/demo_family")'
    assert checker.inspect_source(source, "revocompute/routes.py", {"demo_family"}) == []
    assert checker.inspect_source(source, "tests/server/test_protocol.py", {"demo_family"})
    assert checker.inspect_source('task_type = "demo_family"', "revocompute/routes.py", {"demo_family"})


@pytest.mark.parametrize("source", [
    'origin = "https://revocompute.example"',
    'origin = "https://example.invalid"',
    'email = "person@example.test"',
])
def test_reserved_documentation_hosts_are_not_runner_identities(source: str) -> None:
    assert checker.inspect_source(source, "tests/server/test_http.py", {"example"}) == []


def test_documentation_host_normalization_does_not_allow_runner_dependencies() -> None:
    assert checker.inspect_source('family = "example"', "tests/server/test_http.py", {"example"})
    assert checker.inspect_source('path = "docker/runners/example/plugin.yaml"', "tests/server/test_http.py", {"example"})
