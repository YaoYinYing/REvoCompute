# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import pytest

from revocompute.plugins import ContributionRegistry, PluginManager, PluginManifest


def test_manifest_parses_and_preserves_unknown_metadata(tmp_path):
    manifest = PluginManifest.from_mapping(
        {
            "id": "demo-runner",
            "version": "1.2.0",
            "runner_family": "demo",
            "contributions": {"tasks": ["fold", "score"]},
            "license": "GPL-3.0-only",
        },
        path=tmp_path,
    )
    assert manifest.id == "demo-runner"
    assert manifest.contributions["tasks"] == ("fold", "score")
    assert manifest.metadata["license"] == "GPL-3.0-only"


def test_manager_discovers_plugins_and_enforces_declared_contributions(tmp_path):
    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        "id: demo\nversion: 1.0.0\ncontributions:\n  tasks: [fold]\n", encoding="utf-8"
    )
    manager = PluginManager()
    manifests = manager.discover(tmp_path)
    assert [manifest.id for manifest in manifests] == ["demo"]
    task = object()
    assert manager.register_contribution("demo", "tasks", "fold", task) is task
    assert manager.contributions.resolve("tasks", "fold") is task
    with pytest.raises(ValueError, match="did not declare"):
        manager.register_contribution("demo", "tasks", "score", object())


def test_registry_rejects_duplicates_and_unknown_values():
    registry = ContributionRegistry()
    registry.register("tasks", "fold", 1)
    with pytest.raises(ValueError, match="Duplicate tasks contribution"):
        registry.register("tasks", "fold", 2)
    with pytest.raises(KeyError, match="Unknown tasks contribution"):
        registry.resolve("tasks", "score")


def test_manager_discovers_plugins_and_enforces_declared_contributions(tmp_path):
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "plugin.yaml").write_text("id: demo\nversion: '1'\n", encoding="utf-8")
    manager = PluginManager()
    manifests = manager.discover(tmp_path)
    assert [manifest.id for manifest in manifests] == ["demo"]


@pytest.mark.parametrize("raw", [{}, {"id": "bad id"}, {"id": "demo", "contributions": {"tasks": ["bad id"]}}])
def test_manifest_rejects_invalid_identifiers(raw):
    with pytest.raises(ValueError):
        PluginManifest.from_mapping(raw)


@pytest.mark.parametrize(
    "declarations",
    [
        ["not", "a", "mapping"],
        "not a mapping",
        None,
    ],
)
def test_manifest_rejects_non_mapping_configuration_schema_declarations(declarations):
    """The parser owns the invariant that consumers iterate .items() on."""
    with pytest.raises(ValueError, match="configuration_schemas"):
        PluginManifest.from_mapping({"id": "demo", "configuration_schemas": {"input_workspace": declarations}})


def test_manifest_normalizes_configuration_schema_declarations_to_dicts():
    manifest = PluginManifest.from_mapping(
        {"id": "demo", "configuration_schemas": {"input_workspace": {"builder": {"type": "object"}}}}
    )
    assert manifest.configuration_schemas == {"input_workspace": {"builder": {"type": "object"}}}
    assert isinstance(manifest.configuration_schemas["input_workspace"], dict)
