from __future__ import annotations

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
        "api_version: 1\nid: demo\nversion: '1'\nruntime:\n  image: demo\n  definition: demo.def\n"
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


def test_manifest_id_selects_plugin_when_directory_name_differs(tmp_path):
    family = tmp_path / "implementation_detail"
    task_dir = family / "tasks" / "echo"
    task_dir.mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "id: demo\nversion: '1'\nruntime:\n  image: demo\n  definition: demo.def\n"
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
        "id: demo\nversion: '1'\nruntime: {}\n"
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
        "id: gremlin\nversion: '1'\nruntime:\n  image: demo\n  definition: demo.def\n"
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
