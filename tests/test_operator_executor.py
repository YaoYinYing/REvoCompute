# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Host Operator Executor boundary: allowlisted, bounded, fail-closed.

The web process must never be given a shell or arbitrary command construction.
These cases pin that a Web-triggered operation is a fixed argv built from a
table, that the child's environment is allowlisted, that a missing host
controller fails closed, and that an action with no stable host command is
refused rather than approximated.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from revocompute.operator_executor import (
    ExecutorUnavailable,
    UnsupportedOperation,
    availability,
    build_host_argv,
    executable_actions,
    execute,
    resolve_executor,
)
from revocompute.runner_host import ServerHostPaths


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def host(tmp_path: Path) -> ServerHostPaths:
    root = tmp_path / "checkout"
    (root / "run").mkdir(parents=True)
    (root / "run" / "restart.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (root / ".env.production").write_text("SERVER_DIR=%s\n" % (tmp_path / "server"), encoding="utf-8")
    return ServerHostPaths(
        server=str(tmp_path / "server"),
        config=str(tmp_path / "config"),
        root=str(root),
        settings={"RUNNER_SOURCE_ROOT": str(tmp_path / "runners")},
    )


def test_availability_is_a_capability_not_a_readiness_verdict(tmp_path):
    missing = ServerHostPaths(server=str(tmp_path), config=str(tmp_path), root=str(tmp_path / "absent"))
    state = availability(missing)
    assert state.available is False
    assert state.reason == "operator_executor_unavailable"


def test_a_present_controller_resolves_to_a_bounded_invocation(host):
    state = availability(host)
    assert state.available is True
    config = resolve_executor(host)
    assert config is not None
    assert config.command[1].endswith("run/restart.sh")
    assert config.working_directory == host.server_root()


def test_argv_is_fixed_and_never_shell_interpreted(host):
    config = resolve_executor(host)
    argv = build_host_argv(config, "runner.status", {"runner_family": "demo"})
    assert argv[: len(config.command)] == config.command
    assert argv[len(config.command) :] == ("runner-status", "--runner", "demo")
    # No shell metacharacter survives; the family is a single argv word.
    assert all(";" not in word and "&&" not in word for word in argv)


@pytest.mark.parametrize("hostile", ["demo; id", "demo && id", "$(id)", "../demo", "-rf", "a/b"])
def test_hostile_family_values_never_reach_argv(host, hostile):
    config = resolve_executor(host)
    from revocompute.operator_actions import OperatorActionError

    with pytest.raises(OperatorActionError):
        build_host_argv(config, "runner.status", {"runner_family": hostile})


def test_an_action_without_a_host_command_is_refused(host):
    config = resolve_executor(host)
    assert "runner.build" not in executable_actions()
    with pytest.raises(UnsupportedOperation):
        build_host_argv(config, "runner.build", {"runner_family": "demo"})


def test_unknown_action_fails_closed(host):
    config = resolve_executor(host)
    with pytest.raises(Exception):
        build_host_argv(config, "runner.exec", {"runner_family": "demo"})


def test_execute_uses_the_allowlisted_environment_and_bounded_cwd(host):
    captured = {}

    def fake_spawn(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return _Completed(returncode=0, stdout="STATUS READY\n")

    result = execute(host, action_id="runner.status", runner_family="demo", runner=fake_spawn)

    assert result.succeeded is True
    assert result.returncode == 0
    assert captured["cwd"] == host.server_root()
    assert captured["argv"][-2:] == ["--runner", "demo"]
    environment = captured["env"]
    assert environment["REVODESIGN_SERVER_ENV"].endswith(".env.production")
    # No ambient secret leaks into the child.
    assert "AWS_SECRET_ACCESS_KEY" not in environment
    # Only the allowlist is carried over.
    from revocompute.operator_executor import _ENV_ALLOWLIST

    assert set(environment) <= set(_ENV_ALLOWLIST) | {"REVODESIGN_SERVER_ENV", "HOME", "PATH"}


def test_an_unavailable_controller_fails_closed_before_any_side_effect(tmp_path):
    missing = ServerHostPaths(server=str(tmp_path), config=str(tmp_path), root=str(tmp_path / "absent"))
    with pytest.raises(ExecutorUnavailable):
        execute(missing, action_id="runner.status", runner_family="demo")


def test_a_missing_interpreter_is_reported_as_unavailable(host, monkeypatch):
    def raising(*_args, **_kwargs):
        raise FileNotFoundError("no such interpreter")

    with pytest.raises(ExecutorUnavailable):
        execute(host, action_id="runner.status", runner_family="demo", runner=raising)


def test_a_timeout_terminates_bounded_and_is_not_a_success(host):
    def timing_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="restart.sh", timeout=1)

    result = execute(host, action_id="runner.status", runner_family="demo", runner=timing_out)
    assert result.succeeded is False
    assert result.returncode == 124


def test_subprocess_failure_redacts_secrets_from_the_returned_log(host):
    def failing(*_args, **_kwargs):
        return _Completed(returncode=1, stderr="token=supersecretvalue\ntraceback...\n")

    result = execute(host, action_id="runner.status", runner_family="demo", runner=failing)
    assert result.succeeded is False
    assert "supersecretvalue" not in result.log_text


def test_oversized_output_is_bounded(host):
    def verbose(*_args, **_kwargs):
        return _Completed(returncode=0, stdout="x" * 200_000)

    result = execute(host, action_id="runner.status", runner_family="demo", runner=verbose)
    assert len(result.log_text) < 200_000
    assert result.log_text.endswith("...[truncated]")
