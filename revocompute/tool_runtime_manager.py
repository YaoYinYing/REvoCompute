# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""On-demand, process-isolated Apptainer runtime-family lifecycle."""

from __future__ import annotations

import fcntl
import json
import os
import signal
import shutil
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol

from revocompute.tool_types import ToolRuntimeFamily


class ActiveCallCounter(Protocol):
    def active_by_family(self, family: str) -> int: ...


class RuntimeUnavailable(RuntimeError):
    pass


class ToolExecutionTimeout(TimeoutError):
    pass


@dataclass(frozen=True)
class RuntimeStatus:
    family: str
    runtime_identity: str
    state: str
    active_calls: int
    last_used: float | None
    recent_startup_failure: str | None
    unavailable_until: float | None
    cold_start_count: int
    warm_hit_count: int
    idle_shutdown_count: int
    runtime_start_seconds: float
    tool_execution_seconds: float
    execution_count: int
    timeout_count: int


class ToolRuntimeManager:
    """Coordinate one warm instance per family across Tool worker processes."""

    def __init__(
        self,
        state_root: str | Path,
        calls: ActiveCallCounter,
        *,
        idle_ttl_seconds: int = 1800,
        failure_threshold: int = 3,
        failure_window_seconds: int = 300,
        cooldown_seconds: int = 60,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        popen: Callable[..., Any] = subprocess.Popen,
        killpg: Callable[[int, int], None] = os.killpg,
    ) -> None:
        self.root = Path(state_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.calls = calls
        self.idle_ttl_seconds = idle_ttl_seconds
        self.failure_threshold = failure_threshold
        self.failure_window_seconds = failure_window_seconds
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self.monotonic = monotonic
        self.run = run
        self.popen = popen
        self.killpg = killpg

    @staticmethod
    def instance_name(runtime: ToolRuntimeFamily) -> str:
        return f"revocompute-tool-{runtime.name}-{runtime.identity}"

    @contextmanager
    def _lock(self, family: str) -> Iterator[None]:
        lock_path = self.root / f"{family}.lock"
        with lock_path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _state_path(self, family: str) -> Path:
        return self.root / f"{family}.json"

    def _exchange_root(self, family: str) -> Path:
        return self.root / f"{family}-exchange"

    def _reset_exchange(self, family: str) -> Path:
        exchange = self._exchange_root(family)
        for name in ("input", "output", "scratch"):
            slot = exchange / name
            slot.mkdir(parents=True, mode=0o700, exist_ok=True)
            for item in slot.iterdir():
                if item.is_dir() and not item.is_symlink():
                    shutil.rmtree(item)
                else:
                    item.unlink()
        return exchange

    def _read_state(self, family: str) -> dict[str, Any]:
        try:
            raw = json.loads(self._state_path(family).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write_state(self, family: str, state: dict[str, Any]) -> None:
        target = self._state_path(family)
        temporary = target.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        os.replace(temporary, target)

    def _instances(self) -> set[str]:
        completed = self.run(
            ["apptainer", "instance", "list", "--json"], capture_output=True, text=True, timeout=10, check=False
        )
        if completed.returncode != 0:
            raise RuntimeUnavailable("Apptainer instance inventory is unavailable")
        try:
            payload = json.loads(completed.stdout or "{}")
            return {str(item["instance"]) for item in payload.get("instances", ()) if item.get("instance")}
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise RuntimeUnavailable("Apptainer returned an invalid instance inventory") from exc

    def _is_warm(self, runtime: ToolRuntimeFamily) -> bool:
        return self.instance_name(runtime) in self._instances()

    def _record_start_failure(self, runtime: ToolRuntimeFamily, message: str) -> None:
        now = self.clock()
        state = self._read_state(runtime.name)
        failures = [float(item) for item in state.get("startup_failures", ()) if now - float(item) <= self.failure_window_seconds]
        failures.append(now)
        state.update({"runtime_identity": runtime.identity, "startup_failures": failures, "recent_startup_failure": message})
        if len(failures) >= self.failure_threshold:
            state["unavailable_until"] = now + self.cooldown_seconds
        self._write_state(runtime.name, state)

    def ensure_warm(self, runtime: ToolRuntimeFamily) -> bool:
        """Return True for a cold start and False for a warm hit."""
        with self._lock(runtime.name):
            now = self.clock()
            state = self._read_state(runtime.name)
            unavailable_until = float(state.get("unavailable_until") or 0)
            if unavailable_until > now:
                raise RuntimeUnavailable(f"Tool runtime is cooling down until {unavailable_until:.3f}")
            if self._is_warm(runtime):
                state.update(
                    {
                        "runtime_identity": runtime.identity,
                        "last_used": now,
                        "warm_hit_count": int(state.get("warm_hit_count", 0)) + 1,
                    }
                )
                self._write_state(runtime.name, state)
                return False
            if not runtime.image.is_file():
                self._record_start_failure(runtime, "Configured Tool SIF is missing")
                raise RuntimeUnavailable("Configured Tool runtime image is unavailable")
            instance = self.instance_name(runtime)
            exchange = self._reset_exchange(runtime.name)
            startup_started = self.monotonic()
            start = self.run(
                [
                    "apptainer", "instance", "start", "--containall", "--cleanenv", "--no-home",
                    "--net", "--network", "none",
                    "--bind", f"{exchange / 'input'}:/tool/input:ro",
                    "--bind", f"{exchange / 'output'}:/tool/output:rw",
                    "--bind", f"{exchange / 'scratch'}:/tool/scratch:rw",
                    str(runtime.image), instance,
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if start.returncode != 0:
                self._record_start_failure(runtime, "Apptainer instance startup failed")
                raise RuntimeUnavailable("Tool runtime instance could not start")
            probe = self.run(
                ["apptainer", "exec", "--cleanenv", f"instance://{instance}", *runtime.health_command],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if probe.returncode != 0:
                self.run(
                    ["apptainer", "instance", "stop", instance],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                self._record_start_failure(runtime, "Tool runtime health probe failed")
                raise RuntimeUnavailable("Tool runtime health probe failed")
            state.update(
                {
                    "runtime_identity": runtime.identity,
                    "last_used": now,
                    "startup_failures": [],
                    "recent_startup_failure": None,
                    "unavailable_until": None,
                    "cold_start_count": int(state.get("cold_start_count", 0)) + 1,
                    "runtime_start_seconds": float(state.get("runtime_start_seconds", 0.0))
                    + self.monotonic() - startup_started,
                }
            )
            self._write_state(runtime.name, state)
            return True

    def execute(
        self,
        runtime: ToolRuntimeFamily,
        argv: list[str],
        *,
        binds: tuple[tuple[Path, str, str], ...],
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        expected_binds = {"/tool/input": "ro", "/tool/output": "rw", "/tool/scratch": "rw"}
        sources = {destination: source.resolve() for source, destination, mode in binds if expected_binds.get(destination) == mode}
        if set(sources) != set(expected_binds) or len(binds) != len(expected_binds):
            raise ValueError("Tool execution requires the fixed isolated input, output, and scratch binds")
        with self._lock(runtime.name):
            exchange = self._reset_exchange(runtime.name)
            shutil.copytree(sources["/tool/input"], exchange / "input", dirs_exist_ok=True, symlinks=True)
            shutil.copytree(sources["/tool/scratch"], exchange / "scratch", dirs_exist_ok=True, symlinks=True)
            instance = self.instance_name(runtime)
            command = ["apptainer", "exec", "--cleanenv", f"instance://{instance}", *argv]
            process = self.popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            execution_started = self.monotonic()
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                self.killpg(process.pid, signal.SIGTERM)
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    self.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = process.communicate()
                raise ToolExecutionTimeout("Tool call exceeded its execution timeout") from exc
            finally:
                shutil.copytree(exchange / "output", sources["/tool/output"], dirs_exist_ok=True, symlinks=True)
                state = self._read_state(runtime.name)
                state["last_used"] = self.clock()
                state["tool_execution_seconds"] = float(state.get("tool_execution_seconds", 0.0)) + (
                    self.monotonic() - execution_started
                )
                state["execution_count"] = int(state.get("execution_count", 0)) + 1
                if timed_out:
                    state["timeout_count"] = int(state.get("timeout_count", 0)) + 1
                self._write_state(runtime.name, state)
                self._reset_exchange(runtime.name)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    def stop_idle(self, runtimes: tuple[ToolRuntimeFamily, ...]) -> list[str]:
        stopped: list[str] = []
        for runtime in runtimes:
            with self._lock(runtime.name):
                if self.calls.active_by_family(runtime.name) != 0:
                    continue
                state = self._read_state(runtime.name)
                last_used = float(state.get("last_used") or 0)
                if not last_used or self.clock() - last_used < self.idle_ttl_seconds or not self._is_warm(runtime):
                    continue
                completed = self.run(
                    ["apptainer", "instance", "stop", self.instance_name(runtime)],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                if completed.returncode == 0:
                    state["idle_shutdown_count"] = int(state.get("idle_shutdown_count", 0)) + 1
                    self._write_state(runtime.name, state)
                    stopped.append(runtime.name)
        return stopped

    def reset_cold(self, runtimes: tuple[ToolRuntimeFamily, ...]) -> list[str]:
        """Discard warm state owned by enabled families at worker-generation start."""
        stopped: list[str] = []
        instances = self._instances()
        for runtime in runtimes:
            prefix = f"revocompute-tool-{runtime.name}-"
            with self._lock(runtime.name):
                for instance in sorted(name for name in instances if name.startswith(prefix)):
                    completed = self.run(
                        ["apptainer", "instance", "stop", instance],
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    )
                    if completed.returncode == 0:
                        stopped.append(instance)
                self._state_path(runtime.name).unlink(missing_ok=True)
                self._reset_exchange(runtime.name)
        return stopped

    def status(self, runtime: ToolRuntimeFamily) -> RuntimeStatus:
        with self._lock(runtime.name):
            state = self._read_state(runtime.name)
            now = self.clock()
            unavailable_until = float(state.get("unavailable_until") or 0) or None
            if unavailable_until and unavailable_until > now:
                runtime_state = "UNAVAILABLE"
            else:
                runtime_state = "WARM" if self._is_warm(runtime) else "COLD"
            return RuntimeStatus(
                family=runtime.name,
                runtime_identity=runtime.identity,
                state=runtime_state,
                active_calls=self.calls.active_by_family(runtime.name),
                last_used=float(state["last_used"]) if state.get("last_used") else None,
                recent_startup_failure=state.get("recent_startup_failure"),
                unavailable_until=unavailable_until,
                cold_start_count=int(state.get("cold_start_count", 0)),
                warm_hit_count=int(state.get("warm_hit_count", 0)),
                idle_shutdown_count=int(state.get("idle_shutdown_count", 0)),
                runtime_start_seconds=float(state.get("runtime_start_seconds", 0.0)),
                tool_execution_seconds=float(state.get("tool_execution_seconds", 0.0)),
                execution_count=int(state.get("execution_count", 0)),
                timeout_count=int(state.get("timeout_count", 0)),
            )
