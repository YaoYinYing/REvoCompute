# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from revocompute.input_validators import validate_input_file, validator_isolation
from revocompute.input_validators import isolated_validation, isolated_worker


class _Completed:
    """Stand-in for a real child process launched by the isolated validator."""

    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode, self.stdout = returncode, stdout

    def communicate(self, timeout=None):
        return self.stdout, ""


def test_validator_registry_classifies_inprocess_and_isolated_parsers():
    assert validator_isolation("fasta") == "safe_inprocess"
    assert validator_isolation("yaml") == "isolated"
    assert validator_isolation("yml") == "isolated"
    assert validator_isolation("unknown") is None


def test_yaml_validation_runs_through_isolated_protocol(tmp_path):
    valid = tmp_path / "input.yaml"
    valid.write_text("version: 1\nsequences: []\n", encoding="utf-8")
    unsafe = tmp_path / "unsafe.yaml"
    unsafe.write_text("!!python/object/apply:os.system ['id']\n", encoding="utf-8")

    assert validate_input_file(str(valid), valid.name) is None
    assert validate_input_file(str(unsafe), unsafe.name) is not None


def test_isolated_parser_timeout_is_a_bounded_resource_failure(monkeypatch, tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\n", encoding="utf-8")
    monkeypatch.setattr(isolated_validation, "ISOLATED_TIMEOUT_SECONDS", 0.001)

    # A parser that runs past its budget is a resource-limit failure, reported
    # with the bounded code rather than a prose-only message.
    assert validate_input_file(str(source), source.name) == isolated_validation.VALIDATOR_RESOURCE_LIMIT_ERROR


def test_isolated_parser_crash_is_a_validation_failure(monkeypatch, tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\n", encoding="utf-8")
    # A worker that errored out (nonzero but not a resource kill) is a parser
    # crash, not a resource limit.
    monkeypatch.setattr(
        isolated_validation.subprocess,
        "Popen",
        lambda *_args, **_kwargs: _Completed(1),
    )

    assert "failed in isolation" in validate_input_file(str(source), source.name)


def test_isolated_launcher_uses_static_argv_private_workspace_and_sanitized_environment(monkeypatch, tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\n", encoding="utf-8")
    observed = {}

    def popen(argv, **kwargs):
        observed.update(argv=argv, **kwargs)
        return _Completed(0, '{"error":null}')

    monkeypatch.setattr(isolated_validation.subprocess, "Popen", popen)

    assert validate_input_file(str(source), source.name) is None
    assert observed["argv"][0] == isolated_validation.sys.executable
    assert observed["argv"][1] == "-I"
    assert Path(observed["argv"][2]).name == "isolated_worker.py"
    assert observed["argv"][3] == "yaml"
    assert observed["argv"][4].startswith("/proc/self/fd/")
    assert observed["pass_fds"]
    assert Path(observed["cwd"]).name.startswith("revocompute-validator-")
    assert set(observed["env"]) == {"LANG", "LC_ALL", "PATH", "TMPDIR"}
    assert observed["stdin"] is subprocess.DEVNULL
    assert observed["start_new_session"] is True
    assert observed["preexec_fn"] is isolated_validation._restrict_child


def test_isolated_worker_applies_resource_and_network_guards(monkeypatch):
    limits = []
    masks = []
    worker_socket = SimpleNamespace(socket=object(), create_connection=object())
    monkeypatch.setattr(
        isolated_worker.resource,
        "setrlimit",
        lambda resource_id, value: limits.append((resource_id, value)),
    )
    monkeypatch.setattr(isolated_worker.os, "umask", masks.append)
    monkeypatch.setattr(isolated_worker, "socket", worker_socket)

    isolated_worker._apply_restrictions()

    assert {resource_id for resource_id, _value in limits} == {
        isolated_worker.resource.RLIMIT_CPU,
        isolated_worker.resource.RLIMIT_AS,
        isolated_worker.resource.RLIMIT_FSIZE,
        isolated_worker.resource.RLIMIT_NOFILE,
    }
    assert masks == [0o077]
    try:
        worker_socket.socket()
    except OSError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("isolated parser networking was not disabled")


def test_isolated_parser_memory_limit_is_a_bounded_validation_failure(monkeypatch, tmp_path):
    """Address-space exhaustion is classified, not reported as an opaque crash."""
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\n", encoding="utf-8")
    monkeypatch.setattr(
        isolated_validation.subprocess,
        "Popen",
        lambda *_args, **_kwargs: _Completed(0, '{"error":"RESOURCE_LIMIT"}'),
    )

    error = validate_input_file(str(source), source.name)
    assert error == isolated_validation.VALIDATOR_RESOURCE_LIMIT_ERROR


@pytest.mark.parametrize(
    "stdout",
    [
        "",  # empty
        "not json at all",
        "null",
        "[]",
        '{"error": null, "extra": 1}',  # extra keys
        "{}",  # missing the error key
        '{"error": 5}',  # non-string error
        '{"other": null}',  # wrong key
        '{"error": "a" * 200000}',  # oversized protocol response
    ],
)
def test_a_malformed_isolated_response_is_a_validation_failure(monkeypatch, tmp_path, stdout):
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\n", encoding="utf-8")
    monkeypatch.setattr(
        isolated_validation.subprocess,
        "Popen",
        lambda *_args, **_kwargs: _Completed(0, stdout),
    )

    error = validate_input_file(str(source), source.name)
    assert error is not None
    assert "invalid isolation response" in error


def test_a_slow_isolated_parser_is_killed_with_its_whole_group(monkeypatch, tmp_path):
    """A parser that hangs is terminated as a group, not left running."""
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\n", encoding="utf-8")
    signalled: list[tuple[int, int]] = []

    class _Hanging:
        pid = 4242
        returncode = -15
        stdout = ""

        def __init__(self, *_args, **_kwargs):
            self._waits = 0

        def communicate(self, timeout=None):
            import subprocess as _sp

            # Hang on the first wait only; the second call is the parent's
            # post-kill reap and must return.
            if self._waits == 0:
                self._waits += 1
                raise _sp.TimeoutExpired(cmd="worker", timeout=timeout)
            return "", ""

    monkeypatch.setattr(isolated_validation.subprocess, "Popen", _Hanging)
    monkeypatch.setattr(
        isolated_validation, "_kill_group", lambda pid, number: signalled.append((pid, number))
    )

    error = validate_input_file(str(source), source.name)

    assert error == isolated_validation.VALIDATOR_RESOURCE_LIMIT_ERROR
    assert signalled and signalled[0] == (4242, isolated_validation.signal.SIGTERM)


def test_an_unreadable_input_is_a_validation_failure_not_a_server_error(tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\n", encoding="utf-8")
    source.chmod(0o000)

    error = validate_input_file(str(source), source.name)

    if os.geteuid() == 0:
        pytest.skip("root can read an unreadable file")
    assert error is not None
    assert "Could not open" in error
