from __future__ import annotations

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
