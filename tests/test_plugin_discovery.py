from __future__ import annotations

import pytest

from revocompute.access_control import list_policies
from revocompute.task_types import discover_plugins, get, list_types


def test_zero_runner_root_is_valid(tmp_path):
    root = tmp_path / "runners"
    root.mkdir()
    discover_plugins(str(root))
    assert list_types() == []


def test_synthetic_runner_is_loaded_without_core_registry_changes(tmp_path):
    family = tmp_path / "demo"
    task_dir = family / "tasks" / "echo"
    task_dir.mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "api_version: 1\nid: demo\nversion: '1'\nruntime:\n  image_artifact: demo.sif\n  definition: demo.def\n"
        "tasks:\n  - tasks/echo/task.yaml\n",
        encoding="utf-8",
    )
    (family / "demo.def").write_text("Bootstrap: demo\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        "id: echo\ndisplay_name: Echo\ninput_extension: .json\ninput_label: JSON\n"
        "parameters:\n  type: object\n  additionalProperties: false\n  properties:\n    message: {type: string}\n",
        encoding="utf-8",
    )
    discover_plugins(str(tmp_path))
    task, runner = get("echo")
    assert task.display_name == "Echo"
    assert task.schema["properties"]["message"]["type"] == "string"
    assert runner.max_runtime_seconds is None


def test_schema_parameters_and_extension_defaults_are_preserved(tmp_path):
    family = tmp_path / "demo"
    task_dir = family / "tasks" / "echo"
    task_dir.mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "id: demo\nversion: '1'\nruntime: {image_artifact: demo.sif, definition: demo.def}\n"
        "tasks: [tasks/echo/task.yaml]\n",
        encoding="utf-8",
    )
    (family / "demo.def").write_text("Bootstrap: demo\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        "id: echo\ninput_extension: .json\ninput_label: JSON\n"
        "parameters:\n  type: object\n  properties:\n    count: {type: integer, default: 2, minimum: 1, title: Count}\n",
        encoding="utf-8",
    )
    discover_plugins(str(tmp_path))
    task, _ = get("echo")
    assert task.input_extensions == (".json",)
    assert task.primary_input_extensions == (".json",)
    assert [(param.name, param.type, param.default, param.label) for param in task.params] == [
        ("count", "int", 2, "Count")
    ]


def test_distributed_task_rejects_primary_extension_outside_accepted_set(tmp_path):
    family = tmp_path / "demo"
    task_dir = family / "tasks" / "echo"
    task_dir.mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "id: demo\nversion: '1'\nruntime: {image_artifact: demo.sif, definition: demo.def}\n"
        "tasks: [tasks/echo/task.yaml]\n",
        encoding="utf-8",
    )
    (family / "demo.def").write_text("Bootstrap: demo\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        "id: echo\ninput_extension: .json\ninput_extensions: [.json]\n"
        "primary_input_extensions: [.pdb]\ninput_label: JSON\n",
        encoding="utf-8",
    )
    import pytest

    with pytest.raises(ValueError, match="primary input extensions"):
        discover_plugins(str(tmp_path))


def test_manifest_id_selects_plugin_when_directory_name_differs(tmp_path):
    family = tmp_path / "implementation_detail"
    task_dir = family / "tasks" / "echo"
    task_dir.mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "id: demo\nversion: '1'\nruntime:\n  image_artifact: demo.sif\n  definition: demo.def\n"
        "tasks: [tasks/echo/task.yaml]\n",
        encoding="utf-8",
    )
    (family / "demo.def").write_text("Bootstrap: demo\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        "id: echo\ndisplay_name: Echo\ninput_extension: .json\ninput_label: JSON\n", encoding="utf-8"
    )
    discover_plugins(str(tmp_path), {"demo"})
    assert get("echo")[0].runtime.name == "demo"


def test_removing_runner_family_removes_its_tasks_and_policy(tmp_path):
    family = tmp_path / "stored_name"
    (family / "tasks" / "echo").mkdir(parents=True)
    (family / "policies").mkdir()
    (family / "plugin.yaml").write_text(
        "id: demo\nversion: '1'\nruntime: {image_artifact: demo.sif, definition: demo.def}\n"
        "tasks: [tasks/echo/task.yaml]\naccess_policies: [policies/demo.yaml]\n"
        "contributions:\n  access_policies: [demo_policy]\n",
        encoding="utf-8",
    )
    (family / "tasks" / "echo" / "task.yaml").write_text("id: echo\nparameters: {type: object}\n", encoding="utf-8")
    (family / "policies" / "demo.yaml").write_text(
        "id: demo_policy\nlabel: Demo\ndescription: Demo policy\nrequires: [demo_entitlement]\n"
        "match: all\nrequestable: false\n",
        encoding="utf-8",
    )

    discover_plugins(str(tmp_path), {"demo"})
    assert get("echo")[0].runtime.name == "demo"
    assert {policy.id for policy in list_policies()} == {"demo_policy"}

    empty = tmp_path / "empty"
    empty.mkdir()
    discover_plugins(str(empty))
    assert list_types() == []
    assert list_policies() == []


def test_runner_configuration_is_loaded_from_manifest_family_tree(tmp_path):
    family = tmp_path / "storage-name"
    task_dir = family / "tasks" / "echo"
    task_dir.mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "id: gremlin\nversion: '1'\nruntime:\n  image_artifact: demo.sif\n  definition: demo.def\n"
        "tasks: [tasks/echo/task.yaml]\n",
        encoding="utf-8",
    )
    (family / "demo.def").write_text("Bootstrap: demo\n", encoding="utf-8")
    (family / "runner.yaml").write_text("max_runtime_seconds: 42\ndefaults: {iter: 7}\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        "id: echo\ndisplay_name: Echo\ninput_extension: .json\ninput_label: JSON\n", encoding="utf-8"
    )

    discover_plugins(str(tmp_path), {"gremlin"})
    task, runner = get("echo")
    assert task.runtime.name == "gremlin"
    assert runner.max_runtime_seconds == 42
    assert runner.defaults == {"iter": 7}


def test_input_capability_options_are_validated_by_plugin_schema(tmp_path):
    family = tmp_path / "jaag_impl"
    task_dir = family / "tasks" / "echo"
    task_dir.mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "id: jaag-owner\nversion: '1'\nruntime: {image_artifact: demo.sif, definition: demo.def}\n"
        "tasks: [tasks/echo/task.yaml]\n"
        "contributions:\n  input_workspace_plugins: [jaag-builder]\n"
        "configuration_schemas:\n  input_workspace:\n    jaag-builder:\n"
        "      type: object\n      additionalProperties: false\n      properties:\n"
        "        target: {type: string, enum: [demo]}\n",
        encoding="utf-8",
    )
    (family / "demo.def").write_text("Bootstrap: demo\n", encoding="utf-8")
    workspace = (
        "input_workspace:\n  steps:\n  - id: input\n    title: Input\n    capabilities:\n"
        "    - {plugin: files, id: source_files}\n"
        "    - plugin: jaag-builder\n      id: jaag_input\n      options: {target: invalid}\n"
        "  - id: review\n    title: Review\n    capabilities:\n    - {plugin: review, id: submission_review}\n"
    )
    (task_dir / "task.yaml").write_text("id: echo\n" + workspace, encoding="utf-8")
    with pytest.raises(Exception, match="is not one of"):
        discover_plugins(str(tmp_path))
    (task_dir / "task.yaml").write_text(workspace.replace("invalid", "demo"), encoding="utf-8")
    discover_plugins(str(tmp_path))
    assert get("echo")[0].input_workspace[0].capabilities[1].options == {"target": "demo"}
