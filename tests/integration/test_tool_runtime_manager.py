# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import signal
import subprocess
import threading
from pathlib import Path

import pytest

from revocompute.tool_runtime_manager import RuntimeUnavailable, ToolRuntimeManager
from revocompute.tool_types import ToolRuntimeFamily


class Calls:
    def __init__(self) -> None:
        self.active = 0

    def active_by_family(self, _family: str) -> int:
        return self.active


class FakeApptainer:
    def __init__(self, *, fail_start: bool = False) -> None:
        self.instances: set[str] = set()
        self.starts = 0
        self.stops = 0
        self.fail_start = fail_start

    def __call__(self, argv, **_kwargs):
        if argv[1:4] == ["instance", "list", "--json"]:
            stdout = json.dumps({"instances": [{"instance": name} for name in sorted(self.instances)]})
            return subprocess.CompletedProcess(argv, 0, stdout, "")
        if argv[1:3] == ["instance", "start"]:
            self.starts += 1
            if self.fail_start:
                return subprocess.CompletedProcess(argv, 1, "", "failed")
            self.instances.add(argv[-1])
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[1:3] == ["instance", "stop"]:
            self.stops += 1
            self.instances.discard(argv[-1])
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[1] == "exec":
            return subprocess.CompletedProcess(argv, 0, "healthy", "")
        raise AssertionError(f"Unexpected command: {argv}")


def _runtime(tmp_path: Path) -> ToolRuntimeFamily:
    image = tmp_path / "fixture.sif"
    image.touch()
    definition = tmp_path / "fixture.def"
    definition.touch()
    return ToolRuntimeFamily(
        "fixture", "1", tmp_path, definition, image, ("tool",), ("tool", "health"), "identity"
    )


def test_concurrent_cold_acquisition_starts_one_family_instance(tmp_path):
    fake = FakeApptainer()
    runtime = _runtime(tmp_path)
    manager = ToolRuntimeManager(tmp_path / "state", Calls(), run=fake)
    results: list[bool] = []

    threads = [threading.Thread(target=lambda: results.append(manager.ensure_warm(runtime))) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert fake.starts == 1
    assert sorted(results) == [False, False, True]
    assert manager.status(runtime).state == "WARM"
    assert manager.status(runtime).cold_start_count == 1
    assert manager.status(runtime).warm_hit_count == 2


def test_startup_failures_open_a_temporary_circuit(tmp_path):
    now = [100.0]
    fake = FakeApptainer(fail_start=True)
    runtime = _runtime(tmp_path)
    manager = ToolRuntimeManager(
        tmp_path / "state", Calls(), run=fake, clock=lambda: now[0], failure_threshold=3, cooldown_seconds=60
    )

    for _ in range(3):
        with pytest.raises(RuntimeUnavailable):
            manager.ensure_warm(runtime)
    with pytest.raises(RuntimeUnavailable, match="cooling down"):
        manager.ensure_warm(runtime)
    assert fake.starts == 3
    assert manager.status(runtime).state == "UNAVAILABLE"

    now[0] = 161.0
    fake.fail_start = False
    assert manager.ensure_warm(runtime) is True
    assert manager.status(runtime).state == "WARM"


def test_idle_shutdown_is_blocked_by_active_family_calls(tmp_path):
    now = [100.0]
    calls = Calls()
    fake = FakeApptainer()
    runtime = _runtime(tmp_path)
    manager = ToolRuntimeManager(tmp_path / "state", calls, run=fake, clock=lambda: now[0], idle_ttl_seconds=10)
    manager.ensure_warm(runtime)
    now[0] = 111.0
    calls.active = 1

    assert manager.stop_idle((runtime,)) == []
    assert fake.stops == 0

    calls.active = 0
    assert manager.stop_idle((runtime,)) == ["fixture"]
    assert fake.stops == 1
    assert manager.status(runtime).state == "COLD"


def test_worker_generation_reset_stops_only_its_enabled_family_and_clears_state(tmp_path):
    fake = FakeApptainer()
    runtime = _runtime(tmp_path)
    manager = ToolRuntimeManager(tmp_path / "state", Calls(), run=fake)
    manager.ensure_warm(runtime)
    fake.instances.add("revocompute-tool-other-unrelated")

    assert manager.reset_cold((runtime,)) == ["revocompute-tool-fixture-identity"]
    assert fake.instances == {"revocompute-tool-other-unrelated"}
    assert manager.status(runtime).state == "COLD"
    assert manager.status(runtime).cold_start_count == 0


class FakeChild:
    def __init__(self, argv, *, exchange: Path, timeouts: int = 0) -> None:
        self.argv = argv
        self.exchange = exchange
        self.timeouts = timeouts
        self.pid = 12345
        self.returncode = 0

    def communicate(self, timeout=None):
        if self.timeouts:
            self.timeouts -= 1
            raise subprocess.TimeoutExpired(self.argv, timeout)
        (self.exchange / "output" / "result.txt").write_text("result", encoding="utf-8")
        return "ok", ""


def _execution_binds(tmp_path: Path) -> tuple[tuple[Path, str, str], ...]:
    call = tmp_path / "call"
    for name in ("input", "output", "scratch"):
        (call / name).mkdir(parents=True)
    (call / "input" / "current.txt").write_text("current", encoding="utf-8")
    (tmp_path / "other-call-secret.txt").write_text("secret", encoding="utf-8")
    return (
        (call / "input", "/tool/input", "ro"),
        (call / "output", "/tool/output", "rw"),
        (call / "scratch", "/tool/scratch", "rw"),
    )


def test_fresh_child_uses_only_current_exchange_and_copies_outputs_back(tmp_path):
    fake = FakeApptainer()
    runtime = _runtime(tmp_path)
    state = tmp_path / "state"
    observed = []

    def launch(argv, **_kwargs):
        exchange = state / "fixture-exchange"
        observed.append(sorted(path.name for path in (exchange / "input").iterdir()))
        return FakeChild(argv, exchange=exchange)

    manager = ToolRuntimeManager(state, Calls(), run=fake, popen=launch)
    manager.ensure_warm(runtime)
    binds = _execution_binds(tmp_path)

    completed = manager.execute(runtime, ["trusted-tool", "run"], binds=binds, timeout_seconds=10)

    assert completed.returncode == 0
    assert observed == [["current.txt"]]
    assert (binds[1][0] / "result.txt").read_text(encoding="utf-8") == "result"
    assert list((state / "fixture-exchange" / "input").iterdir()) == []


def test_timeout_terminates_process_group_and_updates_telemetry(tmp_path):
    fake = FakeApptainer()
    runtime = _runtime(tmp_path)
    state = tmp_path / "state"
    signals = []
    manager = ToolRuntimeManager(
        state,
        Calls(),
        run=fake,
        popen=lambda argv, **_kwargs: FakeChild(argv, exchange=state / "fixture-exchange", timeouts=1),
        killpg=lambda pid, sig: signals.append((pid, sig)),
    )
    manager.ensure_warm(runtime)

    with pytest.raises(TimeoutError):
        manager.execute(runtime, ["trusted-tool", "run"], binds=_execution_binds(tmp_path), timeout_seconds=1)

    assert signals == [(12345, signal.SIGTERM)]
    assert manager.status(runtime).timeout_count == 1
