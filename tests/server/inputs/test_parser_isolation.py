# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import subprocess
from pathlib import Path

from revocompute.input_validators import validate_input_file, validator_isolation
from revocompute.input_validators import isolated_validation, isolated_worker


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


def test_isolated_parser_timeout_is_a_validation_failure(monkeypatch, tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\n", encoding="utf-8")
    monkeypatch.setattr(isolated_validation, "ISOLATED_TIMEOUT_SECONDS", 0.001)

    assert "time limit" in validate_input_file(str(source), source.name)


def test_isolated_parser_crash_is_a_validation_failure(monkeypatch, tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\n", encoding="utf-8")
    monkeypatch.setattr(
        isolated_validation.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], returncode=-9, stdout="", stderr=""),
    )

    assert "failed in isolation" in validate_input_file(str(source), source.name)


def test_isolated_launcher_uses_static_argv_private_workspace_and_sanitized_environment(monkeypatch, tmp_path):
    source = tmp_path / "input.yaml"
    source.write_text("version: 1\n", encoding="utf-8")
    observed = {}

    def run(argv, **kwargs):
        observed.update(argv=argv, **kwargs)
        return subprocess.CompletedProcess(argv, returncode=0, stdout='{"error":null}', stderr="")

    monkeypatch.setattr(isolated_validation.subprocess, "run", run)

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


def test_isolated_worker_applies_resource_and_network_guards(monkeypatch):
    limits = []
    masks = []
    monkeypatch.setattr(
        isolated_worker.resource,
        "setrlimit",
        lambda resource_id, value: limits.append((resource_id, value)),
    )
    monkeypatch.setattr(isolated_worker.os, "umask", masks.append)

    isolated_worker._apply_restrictions()

    assert {resource_id for resource_id, _value in limits} == {
        isolated_worker.resource.RLIMIT_CPU,
        isolated_worker.resource.RLIMIT_AS,
        isolated_worker.resource.RLIMIT_FSIZE,
        isolated_worker.resource.RLIMIT_NOFILE,
    }
    assert masks == [0o077]
    try:
        isolated_worker.socket.socket()
    except OSError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("isolated parser networking was not disabled")
