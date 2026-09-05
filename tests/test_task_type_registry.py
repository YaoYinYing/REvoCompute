# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Distributed plugin task contract tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from revocompute import task_types

SERVER_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SERVER_ROOT / "docker" / "runners"


def _discover(*enabled: str) -> None:
    task_types.discover_plugins(str(PLUGIN_ROOT), set(enabled))


def test_all_plugin_manifests_are_discoverable():
    _discover()
    names = {task.name for task in task_types.list_types()}
    assert "gremlin" in names
    manifest_ids = {
        (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("id")
        for path in PLUGIN_ROOT.glob("*/plugin.yaml")
    }
    assert manifest_ids <= {runtime.name for runtime in task_types.list_runtimes()}


def test_shared_tasks_resolve_one_runtime_and_runner_config():
    _discover("esm", "mpnn", "placer-rfdiffusion")
    esm_tasks = [task_types.get(name) for name in ("esm_extract", "esm_1v", "esm_if1")]
    assert {task.runtime.name for task, _ in esm_tasks} == {"esm"}
    assert all(runner == esm_tasks[0][1] for _, runner in esm_tasks)
    mpnn_tasks = [task_types.get(name) for name in ("proteinmpnn", "solublempnn", "ligandmpnn")]
    assert {task.runtime.name for task, _ in mpnn_tasks} == {"mpnn"}
    placer, placer_runner = task_types.get("placer")
    rfdiffusion, rfdiffusion_runner = task_types.get("rfdiffusion")
    assert placer.runtime is rfdiffusion.runtime
    assert placer_runner == rfdiffusion_runner


def test_distributed_workflows_and_workspace_contracts():
    _discover("alphafold", "colabfold_af2", "placer-rfdiffusion", "easifa")
    alphafold, _ = task_types.get("alphafold")
    assert [(stage.name, stage.requires_gpu) for stage in alphafold.workflow] == [
        ("alphafold.features", False),
        ("alphafold.model", True),
    ]
    assert alphafold.workflow[0].runner_args == ("-s", "features")
    rfdiffusion, _ = task_types.get("rfdiffusion")
    assert [cap.plugin for cap in task_types.iter_capabilities(rfdiffusion)] == [
        "files", "structure", "placer-rfdiffusion:rfdiffusion-regions", "parameters", "review"
    ]
    easifa, _ = task_types.get("easifa")
    assert easifa.result_workspace[0].plugin == "entity-table"


def test_plugin_task_manifests_declare_scientific_guidance():
    for task_path in PLUGIN_ROOT.glob("*/tasks/*/task.yaml"):
        task = yaml.safe_load(task_path.read_text(encoding="utf-8")) or {}
        for field in ("summary", "use_when", "input_summary", "output_summary"):
            assert isinstance(task.get(field), str) and task[field].strip(), (task_path, field)
        considerations = task.get("considerations")
        assert isinstance(considerations, list) and considerations and all(str(item).strip() for item in considerations)
