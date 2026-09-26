# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Isolation boundaries that no untrusted Tool or parser byte may cross.

Each test drives the real code path and fails when the corresponding bound is
not enforced before the untrusted side acts.
"""

from __future__ import annotations

import importlib
import json
import resource
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from revocompute.config import ComputeConfig, ToolConfig
from revocompute.input_validators import isolated_validation
from revocompute.tool_calls import ToolCallDatabase, new_tool_call_id
from revocompute.tool_runtime_manager import ToolRuntimeManager
from revocompute.tool_types import ToolRegistry, ToolRuntimeFamily
from revocompute.tool_workspace import ToolWorkspace, ToolWorkspaceError

REPO_ROOT = Path(__file__).resolve().parents[1]
# ``isolated_validation.subprocess`` is the global subprocess module, so a test
# that monkeypatches its Popen to observe the launcher must keep the real one.
REAL_POPEN = subprocess.Popen
IGNORES_SIGTERM = "import signal,sys,time;signal.signal(signal.SIGTERM, signal.SIG_IGN);sys.stdout.write('');time.sleep(30)"


class Calls:
    def active_by_family(self, _family: str) -> int:
        return 0


def _runtime(tmp_path: Path) -> ToolRuntimeFamily:
    image = tmp_path / "fixture.sif"
    image.touch()
    definition = tmp_path / "fixture.def"
    definition.touch()
    return ToolRuntimeFamily("fixture", "1", tmp_path, definition, image, ("tool",), ("tool", "health"), "identity")


class WritingChild:
    """Writes the requested bytes into the container-owned output slot."""

    def __init__(self, argv, *, exchange: Path, payload: int) -> None:
        self.argv = argv
        self.exchange = exchange
        self.payload = payload
        self.pid = 12345
        self.returncode = 0

    def communicate(self, timeout=None):
        (self.exchange / "output" / "result.bin").write_bytes(b"x" * self.payload)
        return "ok", ""


def _binds(tmp_path: Path) -> tuple[tuple[Path, str, str], ...]:
    call = tmp_path / "call"
    for name in ("input", "output", "scratch"):
        (call / name).mkdir(parents=True)
    return (
        (call / "input", "/tool/input", "ro"),
        (call / "output", "/tool/output", "rw"),
        (call / "scratch", "/tool/scratch", "rw"),
    )


def _manager(tmp_path: Path, payload: int) -> ToolRuntimeManager:
    state = tmp_path / "state"
    return ToolRuntimeManager(
        state,
        Calls(),
        popen=lambda argv, **_kwargs: WritingChild(argv, exchange=state / "fixture-exchange", payload=payload),
    )


def test_execute_refuses_to_promote_output_beyond_the_reserved_ceiling(tmp_path):
    """A child overrunning its admitted output headroom must not reach the workspace."""
    binds = _binds(tmp_path)

    with pytest.raises(ToolWorkspaceError):
        _manager(tmp_path, 64 * 1024).execute(
            _runtime(tmp_path), ["tool", "run"], binds=binds, timeout_seconds=10, output_max_bytes=1024
        )

    assert list(binds[1][0].iterdir()) == []
    assert list((tmp_path / "state" / "fixture-exchange" / "output").iterdir()) == []


def test_execute_promotes_output_within_the_reserved_ceiling(tmp_path):
    binds = _binds(tmp_path)

    completed = _manager(tmp_path, 1024).execute(
        _runtime(tmp_path), ["tool", "run"], binds=binds, timeout_seconds=10, output_max_bytes=4096
    )

    assert completed.returncode == 0
    assert (binds[1][0] / "result.bin").stat().st_size == 1024


class _Completed:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout, self.returncode = stdout, returncode

    def communicate(self, timeout=None):
        return self.stdout, ""


def test_isolated_launcher_bounds_the_child_before_exec(monkeypatch, tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\n", encoding="utf-8")
    marker = tmp_path / "limits.txt"
    observed: dict[str, object] = {}

    def popen(argv, **kwargs):
        observed.update(kwargs)
        # Reproduce the parent's preexec exactly as a child would run it, then
        # let a real interpreter report the limits it was born with.
        probe = (
            "import resource,pathlib;r=resource.getrlimit;"
            f"pathlib.Path({str(marker)!r}).write_text("
            "str(r(resource.RLIMIT_AS)[0])+' '+str(r(resource.RLIMIT_NOFILE)[0]))"
        )
        with REAL_POPEN(
            [sys.executable, "-I", "-c", probe], preexec_fn=kwargs["preexec_fn"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ) as child:
            assert child.wait() == 0
        return _Completed('{"error":null}')

    monkeypatch.setattr(isolated_validation.subprocess, "Popen", popen)

    assert isolated_validation.validate_in_subprocess(str(source), "yaml") is None
    assert observed["start_new_session"] is True
    assert observed["preexec_fn"] is isolated_validation._restrict_child
    assert marker.read_text(encoding="utf-8").split() == [
        str(256 * 1024 * 1024),
        str(dict(isolated_validation.ISOLATED_RLIMITS)[resource.RLIMIT_NOFILE]),
    ]


def test_isolated_parser_timeout_kills_the_whole_child_group(monkeypatch, tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\n", encoding="utf-8")
    monkeypatch.setattr(isolated_validation, "ISOLATED_TIMEOUT_SECONDS", 0.3)
    kills: list[tuple[int, int]] = []
    real_killpg = isolated_validation.os.killpg
    monkeypatch.setattr(
        isolated_validation.os, "killpg", lambda pid, sig: (kills.append((pid, sig)), real_killpg(pid, sig))
    )
    monkeypatch.setattr(
        isolated_validation.subprocess,
        "Popen",
        lambda argv, **_kwargs: REAL_POPEN(
            # A child that ignores SIGTERM must still be killed.
            [sys.executable, "-I", "-c", IGNORES_SIGTERM],
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ),
    )

    assert "time limit" in isolated_validation.validate_in_subprocess(str(source), "yaml")
    assert [sig for _pid, sig in kills] == [signal.SIGTERM, signal.SIGKILL]


def test_tool_provenance_is_server_owned_and_cannot_be_shadowed(tmp_path, monkeypatch):
    """A child naming itself like a server field cannot contradict the manifest."""
    call_id = new_tool_call_id()
    module, calls, registry, workspace = _prepared_call(tmp_path, monkeypatch, call_id)
    tool = registry.get("structure_inspect")

    class LyingManager:
        def ensure_warm(self, _runtime):
            return True

        def execute(self, _runtime, argv, *, binds, timeout_seconds, output_max_bytes=None, on_child_start=None):
            del timeout_seconds, output_max_bytes
            if on_child_start is not None:
                on_child_start()
            output = next(source for source, destination, _mode in binds if destination == "/tool/output")
            (output / "inspection.json").write_text('{"atom_count":1}\n', encoding="utf-8")
            (output / ".tool-response.json").write_text(
                '{"outputs": {"inspection": [{"path": "inspection.json", "format": "json"}]}, "warnings": [],'
                ' "backend": {"runtime_identity": "attacker", "runtime_family": "attacker", "name": "fixture"}}',
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(argv, 0, "", "")

    module.execute_tool_call(
        call_id, calls=calls, registry=registry, workspace=workspace, manager=LyingManager(), config=module.CONFIG
    )

    record = calls.get(call_id)
    assert record["status"] == "finished"
    manifest = json.loads(record["result_manifest_json"])
    assert manifest["runtime_identity"] == tool.runtime.identity
    assert manifest["runtime_family"] == tool.runtime.name
    assert manifest["provenance"]["declared"] == {
        "runtime_identity": "attacker",
        "runtime_family": "attacker",
        "name": "fixture",
    }
    assert "backend" not in manifest


def _prepared_call(tmp_path, monkeypatch, call_id: str):
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
        config.tools_dir, enabled={"bioio"}, image_root=config.image_dir, maximum_timeout=config.call_timeout_seconds
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
    workspace.write_request(call_id, tool, {"structure": [item]}, {})
    calls.reserve(
        tool_call_id=call_id,
        tool_type=tool.name,
        runtime_family=tool.runtime.name,
        runtime_identity=tool.runtime.identity,
        user_id=1,
        username="owner",
        parameter_json="{}",
        input_manifest_json=json.dumps(
            {"inputs": {"structure": [{key: item[key] for key in ("original_name", "format", "sha256", "size")}]}}
        ),
        idempotency_key=None,
        per_user_limit=3,
        global_limit=8,
        workspace_bytes=workspace.bytes_used(call_id),
        reserved_bytes=0,
        storage_max_bytes=1_000_000,
    )
    return runtime_module, calls, registry, workspace
