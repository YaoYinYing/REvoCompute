# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib
import json
import subprocess
import threading
from pathlib import Path

from revocompute.config import ComputeConfig, ToolConfig
from revocompute.tool_calls import ToolCallDatabase, new_tool_call_id
from revocompute.tool_types import ToolRegistry
from revocompute.tool_workspace import ToolWorkspace

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeRuntimeManager:
    def __init__(self) -> None:
        self.acquisitions = 0
        self.executions = 0

    def ensure_warm(self, _runtime) -> bool:
        self.acquisitions += 1
        return True

    def execute(self, _runtime, argv, *, binds, timeout_seconds, on_child_start=None):
        del timeout_seconds
        if on_child_start is not None:
            on_child_start()
        self.executions += 1
        output = next(source for source, destination, _mode in binds if destination == "/tool/output")
        (output / "inspection.json").write_text('{"atom_count":88}\n', encoding="utf-8")
        (output / ".tool-response.json").write_text(
            json.dumps(
                {
                    "outputs": {"inspection": [{"path": "inspection.json", "format": "json"}]},
                    "warnings": [],
                    "backend": {"name": "fixture"},
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_accepted_call_executes_to_typed_manifest_and_cleanup(tmp_path, monkeypatch):
    call_id = new_tool_call_id()
    runtime_module, config, calls, registry, workspace = _prepared_call(tmp_path, monkeypatch, call_id)
    manager = FakeRuntimeManager()

    runtime_module.execute_tool_call(
        call_id,
        calls=calls,
        registry=registry,
        workspace=workspace,
        manager=manager,
        config=config,
    )

    record = calls.get(call_id)
    manifest = json.loads(record["result_manifest_json"])
    assert record["status"] == "finished"
    assert manifest["outputs"]["inspection"][0]["logical_type"] == "inspection"
    assert manifest["timing"]["cold_start"] is True
    assert manager.acquisitions == manager.executions == 1

    workspace.delete(call_id)
    assert calls.delete_terminal(call_id)
    assert calls.get(call_id) is None
    assert not workspace.call_root(call_id).exists()


class BlockingRuntimeManager:
    """A manager that blocks on the family execution lease before starting."""

    def __init__(self) -> None:
        self.waiting = threading.Event()
        self.release = threading.Event()
        self.executions = 0

    def ensure_warm(self, _runtime) -> bool:
        return True

    def execute(self, _runtime, argv, *, binds, timeout_seconds, on_child_start=None):
        del timeout_seconds
        self.waiting.set()
        assert self.release.wait(timeout=5), "test never released the execution lease"
        if on_child_start is not None:
            on_child_start()
        self.executions += 1
        output = next(source for source, destination, _mode in binds if destination == "/tool/output")
        (output / "inspection.json").write_text('{"atom_count":88}\n', encoding="utf-8")
        (output / ".tool-response.json").write_text(
            json.dumps(
                {
                    "outputs": {"inspection": [{"path": "inspection.json", "format": "json"}]},
                    "warnings": [],
                    "backend": {"name": "fixture"},
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, "", "")


def _prepared_call(tmp_path, monkeypatch, call_id: str, *, reserved_bytes: int = 0):
    server = tmp_path / "server"
    images = tmp_path / "images"
    server.mkdir()
    images.mkdir()
    (images / "bioio.sif").touch()
    monkeypatch.setenv("SERVER_DIR", str(server))
    monkeypatch.setenv("TOOLS_DIR", str(REPO_ROOT / "docker" / "tools"))
    monkeypatch.setenv("TOOL_IMAGE_DIR", str(images))
    monkeypatch.setenv("ENABLED_TOOL_FAMILIES", "bioio")

    import revocompute.tool_runtime as runtime_module

    runtime_module = importlib.reload(runtime_module)
    config = ToolConfig.from_env(ComputeConfig.from_env())
    calls = ToolCallDatabase(str(tmp_path / "calls.sqlite3"))
    registry = ToolRegistry.discover(
        config.tools_dir,
        enabled={"bioio"},
        image_root=config.image_dir,
        maximum_timeout=config.call_timeout_seconds,
    )
    workspace = ToolWorkspace(tmp_path / "workspace", request_max_bytes=1_000_000, output_max_bytes=1_000_000)
    tool = registry.get("structure_inspect")
    workspace.create(call_id)
    item = workspace.materialize_file(
        call_id,
        role="structure",
        filename="sample.pdb",
        accepted_formats=tool.inputs[0].formats,
        source=REPO_ROOT / "tests" / "data" / "3fap_hf3_A_short.pdb",
    )
    inputs = {"structure": [item]}
    workspace.write_request(call_id, tool, inputs, {})
    calls.reserve(
        tool_call_id=call_id,
        tool_type=tool.name,
        runtime_family=tool.runtime.name,
        runtime_identity=tool.runtime.identity,
        user_id=1,
        username="owner",
        parameter_json="{}",
        input_manifest_json=json.dumps(
            {"inputs": {"structure": [{key: item[key] for key in ("original_name", "format", "sha256", "size")}]}},
        ),
        idempotency_key=None,
        per_user_limit=3,
        global_limit=8,
        workspace_bytes=workspace.bytes_used(call_id),
        reserved_bytes=reserved_bytes,
        storage_max_bytes=1_000_000,
    )
    return runtime_module, config, calls, registry, workspace


def test_call_stays_preparing_until_the_family_lease_starts_the_child(tmp_path, monkeypatch):
    call_id = new_tool_call_id()
    runtime_module, config, calls, registry, workspace = _prepared_call(
        tmp_path, monkeypatch, call_id, reserved_bytes=1234
    )
    manager = BlockingRuntimeManager()
    outcome: list[BaseException] = []

    def run() -> None:
        try:
            runtime_module.execute_tool_call(
                call_id, calls=calls, registry=registry, workspace=workspace, manager=manager, config=config
            )
        except BaseException as exc:  # pragma: no cover - surfaced through the assertion below
            outcome.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert manager.waiting.wait(timeout=5)
    # While the call waits for the single-family execution lease it must not
    # claim to be running, and its timeout must not have started.
    assert calls.get(call_id)["status"] == "preparing"
    manager.release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert outcome == []
    assert manager.executions == 1
    record = calls.get(call_id)
    assert record["status"] == "finished"
    assert record["reserved_bytes"] == 0
