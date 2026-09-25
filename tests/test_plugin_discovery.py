from __future__ import annotations

import pytest

from revocompute.access_control import list_policies
from revocompute.task_types import discover_plugins, get, list_types


INPUTS = "inputs:\n  source:\n    type: text\n    formats: [json]\n    cardinality: {min: 1, max: 1}\n"


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
        "id: echo\ndisplay_name: Echo\n" + INPUTS +
        "parameters:\n  type: object\n  additionalProperties: false\n  properties:\n    message: {type: string}\n",
        encoding="utf-8",
    )
    discover_plugins(str(tmp_path))
    task, runner = get("echo")
    assert task.display_name == "Echo"
    assert task.schema["properties"]["message"]["type"] == "string"
    assert runner.max_runtime_seconds is None


def test_schema_parameters_and_typed_inputs_are_preserved(tmp_path):
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
        "id: echo\n" + INPUTS +
        "parameters:\n  type: object\n  properties:\n    count: {type: integer, default: 2, minimum: 1, title: Count}\n",
        encoding="utf-8",
    )
    discover_plugins(str(tmp_path))
    task, _ = get("echo")
    assert [(role.name, role.type, role.formats, role.minimum, role.maximum) for role in task.inputs] == [
        ("source", "text", ("json",), 1, 1)
    ]
    assert [(param.name, param.type, param.default, param.label) for param in task.params] == [
        ("count", "int", 2, "Count")
    ]


def test_distributed_task_rejects_invalid_role_cardinality(tmp_path):
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
        "id: echo\ninputs:\n  source:\n    type: text\n    formats: [json]\n"
        "    cardinality: {min: 2, max: 1}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid cardinality"):
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
        "id: echo\ndisplay_name: Echo\n" + INPUTS, encoding="utf-8"
    )
    discover_plugins(str(tmp_path), {"demo"})
    assert get("echo")[0].runtime.name == "demo"


def test_removing_runner_family_removes_its_tasks_and_policy(tmp_path):
    family = tmp_path / "stored_name"
    (family / "tasks" / "echo").mkdir(parents=True)
    (tmp_path / "common" / "policy").mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "id: demo\nversion: '1'\nruntime: {image_artifact: demo.sif, definition: demo.def}\n"
        "tasks: [tasks/echo/task.yaml]\naccess_policies: [common/policy/demo.yaml]\n"
        "contributions:\n  access_policies: [demo_policy]\n",
        encoding="utf-8",
    )
    (family / "tasks" / "echo" / "task.yaml").write_text(
        "id: echo\ninputs: {}\nparameters: {type: object}\n", encoding="utf-8"
    )
    (tmp_path / "common" / "policy" / "demo.yaml").write_text(
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


def test_common_policy_reference_is_loaded_and_missing_policy_fails_closed(tmp_path):
    family = tmp_path / "demo"
    task_dir = family / "tasks" / "echo"
    task_dir.mkdir(parents=True)
    common_policy = tmp_path / "common" / "policy"
    common_policy.mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "id: demo\nversion: '1'\nruntime: {image_artifact: demo.sif, definition: demo.def}\n"
        "tasks: [tasks/echo/task.yaml]\naccess_policies: [common/policy/demo.yaml]\n"
        "contributions:\n  access_policies: [demo_policy]\n",
        encoding="utf-8",
    )
    (family / "demo.def").write_text("Bootstrap: demo\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text("id: echo\ninputs: {}\nparameters: {type: object}\n", encoding="utf-8")
    policy_path = common_policy / "demo.yaml"
    policy_path.write_text(
        "id: demo_policy\nlabel: Demo\ndescription: Demo policy\nrequires: [demo_entitlement]\n"
        "match: all\nrequestable: false\n",
        encoding="utf-8",
    )

    discover_plugins(str(tmp_path), {"demo"})
    assert {policy.id for policy in list_policies()} == {"demo_policy"}

    policy_path.unlink()
    with pytest.raises(FileNotFoundError):
        discover_plugins(str(tmp_path), {"demo"})


def test_family_local_policy_reference_is_rejected(tmp_path):
    family = tmp_path / "demo"
    (family / "policies").mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "id: demo\nversion: '1'\nruntime: {image_artifact: demo.sif, definition: demo.def}\n"
        "access_policies: [policies/demo.yaml]\n",
        encoding="utf-8",
    )
    (family / "demo.def").write_text("Bootstrap: demo\n", encoding="utf-8")
    (family / "policies" / "demo.yaml").write_text(
        "id: demo_policy\nlabel: Demo\ndescription: Demo policy\nrequires: [demo_entitlement]\n"
        "match: all\nrequestable: false\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="common/policy"):
        discover_plugins(str(tmp_path), {"demo"})


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
    (family / "runner.yaml").write_text("max_runtime_seconds: 42\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        "id: echo\ndisplay_name: Echo\n" + INPUTS, encoding="utf-8"
    )

    discover_plugins(str(tmp_path), {"gremlin"})
    task, runner = get("echo")
    assert task.runtime.name == "gremlin"
    assert runner.max_runtime_seconds == 42


def test_runner_yaml_env_names_and_mounts_are_validated(tmp_path):
    """runner.yaml values reach the generated wrapper script as
    ``export APPTAINERENV_<name>=…`` and Apptainer's ``--bind`` argv.  The name
    is interpolated unquoted, so a non-POSIX name is shell syntax inside the
    allocation, and a mount may not shadow the scheduler-owned workspace."""
    from revocompute.task_types import _load_runner_config

    def load(runner_yaml: str):
        path = tmp_path / "runner.yaml"
        path.write_text(runner_yaml, encoding="utf-8")
        return _load_runner_config(str(path))

    with pytest.raises(ValueError, match="POSIX environment names"):
        load("env:\n  'X; touch /tmp/PWNED; #': '1'\n")
    with pytest.raises(ValueError, match="POSIX environment names"):
        load("env:\n  'A B': '1'\n")
    with pytest.raises(ValueError, match="host_path must be an absolute path"):
        load("mounts:\n  - host_path: relative/db\n    container_path: /opt/db\n")
    with pytest.raises(ValueError, match="reserved by the scheduler"):
        load("mounts:\n  - host_path: /etc\n    container_path: /workspace/inputs\n")
    with pytest.raises(ValueError, match="mode must be 'ro' or 'rw'"):
        load("mounts:\n  - host_path: /data/db\n    container_path: /opt/db\n    mode: rw,exec\n")
    config = load("env:\n  LEGIT_MODEL_DIR: /mnt/db\nmounts:\n  - host_path: /data/db\n    container_path: /opt/db\n")
    assert config.env == {"LEGIT_MODEL_DIR": "/mnt/db"}
    assert config.mounts[0].mode == "ro"


def test_input_capability_options_are_validated_by_plugin_schema(tmp_path):
    family = tmp_path / "tree_impl"
    task_dir = family / "tasks" / "echo"
    workspace_dir = family / "workspace" / "tree-picker"
    task_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "index.js").write_text("/* demo plugin */\n", encoding="utf-8")
    (workspace_dir / "schema.json").write_text(
        "type: object\nadditionalProperties: false\nproperties:\n  target: {type: string, enum: [demo]}\n",
        encoding="utf-8",
    )
    (family / "plugin.yaml").write_text(
        "id: tree-owner\nversion: '1'\nruntime: {image_artifact: demo.sif, definition: demo.def}\n"
        "tasks: [tasks/echo/task.yaml]\n"
        "contributions:\n  input_workspace_plugins:\n  - id: tree-picker\n"
        "    module: workspace/tree-picker/index.js\n"
        "    configuration_schema: workspace/tree-picker/schema.json\n",
        encoding="utf-8",
    )
    (family / "demo.def").write_text("Bootstrap: demo\n", encoding="utf-8")
    workspace = (
        "input_workspace:\n  steps:\n  - id: input\n    title: Input\n    capabilities:\n"
        "    - {plugin: files, id: source_files}\n"
        "    - plugin: tree-picker\n      id: tree_input\n      options: {target: invalid}\n"
        "  - id: review\n    title: Review\n    capabilities:\n    - {plugin: review, id: submission_review}\n"
    )
    (task_dir / "task.yaml").write_text("id: echo\ninputs: {}\n" + workspace, encoding="utf-8")
    with pytest.raises(Exception, match="is not one of"):
        discover_plugins(str(tmp_path))
    (task_dir / "task.yaml").write_text("inputs: {}\n" + workspace.replace("invalid", "demo"), encoding="utf-8")
    discover_plugins(str(tmp_path))
    assert get("echo")[0].input_workspace[0].capabilities[1].options == {"target": "demo"}
