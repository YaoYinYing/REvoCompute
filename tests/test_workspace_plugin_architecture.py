# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

"""Behavioral tests for runner-owned Input Workspace plugins."""

from pathlib import Path

import pytest
from revocompute.plugins import PluginManager, PluginManifest
from revocompute.task_types import discover_plugins, get


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
        "id: demo\nversion: '1'\nruntime: {definition: demo.def, image_artifact: demo.sif}\n"
        "tasks: [tasks/demo/task.yaml]\ncontributions:\n"
        "  input_workspace_plugins:\n    - id: editor\n      module: workspace/editor/index.js\n",
        encoding="utf-8",
    )
    (task_dir / "task.yaml").write_text(
        "id: demo\ninputs:\n  sequence:\n    type: protein_sequence\n"
        "    formats: [fasta]\n    cardinality: {min: 1, max: 1}\n"
        "parameters: {type: object}\ninput_workspace:\n  steps:\n"
        "  - id: design\n    title: Design\n    capabilities:\n"
        "    - {plugin: files, id: source_files}\n"
        "    - {plugin: editor, id: editor_input}\n"
        "    - {plugin: review, id: submission_review}\n",
        encoding="utf-8",
    )
    discover_plugins(str(tmp_path))
    task, _runner = get("demo")
    assert task.input_workspace[0].capabilities[1].plugin == "demo:editor"
