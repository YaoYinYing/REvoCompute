# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

"""Architecture gates for runner-owned Input Workspace plugins.

These checks deliberately inspect the materialized runner tree and Core's
entrypoint/template.  They prevent a regression to statically bundled
scientific editors while leaving the plugin protocol implementation free to
evolve.
"""

from pathlib import Path

import pytest
import yaml

from revocompute.plugins import PluginManager, PluginManifest
from revocompute.task_types import discover_plugins, get


ROOT = Path(__file__).resolve().parents[1]
CORE_JS = ROOT / "revocompute" / "static" / "js"
RUNNERS = ROOT / "docker" / "runners"


def test_core_template_only_loads_workspace_host_assets() -> None:
    template = (ROOT / "revocompute" / "templates" / "create_task.html").read_text(encoding="utf-8")
    assert 'src="/static/js/plugin-host.js' in template
    assert 'src="/static/js/input-workspace.js' in template
    assert 'src="/static/js/create-task.js' in template
    # Scientific editors are lazy runner contributions, never page-level
    # scripts.  Keep this assertion explicit so a new editor cannot silently
    # reintroduce the old global bundle.
    for name in ("input-workspace-jaag.js", "input-workspace-rfdiffusion.js"):
        assert name not in template


def test_core_does_not_ship_advanced_editor_implementations() -> None:
    assert not (CORE_JS / "input-workspace-jaag.js").exists()
    assert not (CORE_JS / "input-workspace-rfdiffusion.js").exists()


def test_declared_workspace_assets_are_runner_relative_and_contained() -> None:
    """Every declared editor asset is local to its owning runner family."""
    seen: set[tuple[str, str]] = set()
    for manifest_path in sorted(RUNNERS.glob("*/plugin.yaml")):
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        contributions = (raw.get("contributions") or {}).get("input_workspace_plugins") or []
        if isinstance(contributions, dict):
            contributions = list(contributions.values())
        for declaration in contributions:
            assert isinstance(declaration, dict), f"{manifest_path}: workspace declaration must be a mapping"
            plugin_id = declaration.get("id")
            module = declaration.get("module")
            assert isinstance(plugin_id, str) and plugin_id.strip()
            assert isinstance(module, str) and module.strip()
            assert not Path(module).is_absolute()
            assert ".." not in Path(module).parts
            owner = manifest_path.parent.resolve()
            module_path = (owner / module).resolve()
            assert module_path.is_relative_to(owner)
            assert module_path.is_file(), f"missing workspace module: {module_path}"
            for style in declaration.get("styles", ()) or ():
                assert isinstance(style, str) and style.strip()
                style_path = (owner / style).resolve()
                assert style_path.is_relative_to(owner)
                assert style_path.is_file(), f"missing workspace stylesheet: {style_path}"
            schema = declaration.get("configuration_schema")
            if schema is not None:
                assert isinstance(schema, str) and schema.strip()
                schema_path = (owner / schema).resolve()
                assert schema_path.is_relative_to(owner)
                assert schema_path.is_file(), f"missing workspace schema: {schema_path}"
                parsed = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
                assert isinstance(parsed, dict), f"workspace schema is not an object: {schema_path}"
            identity = (manifest_path.parent.name, plugin_id)
            assert identity not in seen
            seen.add(identity)


def test_zero_runner_tree_keeps_core_workspace_entrypoints(tmp_path: Path) -> None:
    """An empty deployed runner tree cannot remove the generic workspace SDK."""
    empty = tmp_path / "docker" / "runners"
    empty.mkdir(parents=True)
    assert (CORE_JS / "plugin-host.js").is_file()
    assert (CORE_JS / "input-workspace.js").is_file()
    assert not list(empty.glob("*/plugin.yaml"))


def test_synthetic_workspace_plugin_is_namespaced_and_removed_with_runner(tmp_path: Path) -> None:
    family = tmp_path / "demo"
    family.mkdir()
    (family / "workspace").mkdir()
    (family / "workspace" / "editor.js").write_text("export function mount() {}\n", encoding="utf-8")
    (family / "plugin.yaml").write_text(
        "id: demo\nversion: '1'\ncontributions:\n"
        "  input_workspace_plugins:\n    - id: editor\n      module: workspace/editor.js\n",
        encoding="utf-8",
    )
    manager = PluginManager()
    manager.discover(tmp_path)
    descriptor = manager.workspace_plugin("editor", owner="demo")
    assert descriptor is not None
    assert descriptor.global_id == "demo:editor"
    assert manager.workspace_plugin("demo:editor") == descriptor
    manager.deactivate("demo")
    assert manager.workspace_plugin("demo:editor") is None


def test_workspace_plugin_rejects_traversal_and_absolute_assets(tmp_path: Path) -> None:
    for module in ("../outside.js", "/tmp/outside.js"):
        with pytest.raises(ValueError, match="asset path"):
            PluginManifest.from_mapping(
                {
                    "id": "demo",
                    "version": "1",
                    "contributions": {"input_workspace_plugins": [{"id": "editor", "module": module}]},
                },
                path=tmp_path,
            )


def test_task_capability_resolves_runner_owned_plugin_without_core_changes(tmp_path: Path) -> None:
    family = tmp_path / "demo"
    task_dir = family / "tasks" / "demo"
    editor_dir = family / "workspace" / "editor"
    task_dir.mkdir(parents=True)
    editor_dir.mkdir(parents=True)
    (family / "demo.def").write_text("Bootstrap: demo\n", encoding="utf-8")
    (editor_dir / "index.js").write_text("export function mount() {}\n", encoding="utf-8")
    (family / "plugin.yaml").write_text(
        "id: demo\nversion: '1'\nruntime: {definition: demo.def}\n"
        "tasks: [tasks/demo/task.yaml]\ncontributions:\n"
        "  input_workspace_plugins:\n    - id: editor\n      module: workspace/editor/index.js\n",
        encoding="utf-8",
    )
    (task_dir / "task.yaml").write_text(
        "id: demo\nparameters: {type: object}\ninput_workspace:\n  steps:\n"
        "  - id: design\n    title: Design\n    capabilities:\n"
        "    - {plugin: files, id: source_files}\n"
        "    - {plugin: editor, id: editor_input}\n"
        "    - {plugin: review, id: submission_review}\n",
        encoding="utf-8",
    )
    discover_plugins(str(tmp_path))
    task, _runner = get("demo")
    assert task.input_workspace[0].capabilities[1].plugin == "editor"
