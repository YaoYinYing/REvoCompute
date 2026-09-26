# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Regression tests for the fourth security/ops review pass."""

from __future__ import annotations

import logging
import os
import stat
from types import SimpleNamespace

import pytest
from conftest import _test_client_auth, _upsert_task_for_user
from revocompute.maintenance import manager
from revocompute.operational_events import emit_event
from revocompute.redis_util import get_redis
from revocompute.result_storyboard import ResultContractError, runner_root


def test_maintenance_and_event_logs_are_owner_only(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    logger = logging.getLogger(f"log-mode-test-{id(tmp_path)}")
    logger.propagate = False
    try:
        maintenance_log = manager.configure_logging(logger=logger)
        emit_event("task.submitted", task_id="t")

        assert stat.S_IMODE(os.stat(maintenance_log).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(tmp_path / "operational-events.log").st_mode) == 0o600
    finally:
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)


@pytest.mark.parametrize(
    "url",
    [
        "redis://:secretpw@redis:6379/0",
        "redis://default:secretpw@redis:6379/0",
        "redis://worker:secretpw@redis:6379/0",
        "redis://secretpw@redis:6379/0",
    ],
)
def test_redis_failure_warning_never_leaks_the_password(monkeypatch, caplog, url):
    monkeypatch.setenv("REDIS_URL", url)
    get_redis.cache_clear()

    with caplog.at_level(logging.WARNING):
        assert get_redis() is None

    get_redis.cache_clear()
    assert "secretpw" not in caplog.text


def test_anonymous_task_probe_is_not_logged(monkeypatch, tmp_path, caplog):
    module = _load_module(monkeypatch, tmp_path)
    client = module.app.test_client()
    owner_header = _test_client_auth(module)
    other_header = _test_client_auth(module, "other", "password2")
    target = tmp_path / "probe"
    _upsert_task_for_user(
        module,
        "a" * 32,
        filename="input.fasta",
        file_path=target / "input.fasta",
        result_dir=target,
        username="tester",
    )

    with caplog.at_level(logging.WARNING):
        anonymous = client.get(f"/compute/api/running/{'a' * 32}")
        missing = client.get(f"/compute/api/running/{'c' * 32}")

    assert anonymous.status_code == missing.status_code == 404
    assert anonymous.json == {"status": "not_found", "md5sum": "a" * 32}
    assert missing.json == {"status": "not_found", "md5sum": "c" * 32}
    assert "Task access denied" not in caplog.text

    with caplog.at_level(logging.WARNING):
        caplog.clear()
        foreign = client.get(f"/compute/api/running/{'a' * 32}", headers=other_header)

    assert foreign.status_code == 404
    assert foreign.json == anonymous.json
    assert "Task access denied" in caplog.text


def test_authenticated_task_probe_is_still_logged(monkeypatch, tmp_path, caplog):
    module = _load_module(monkeypatch, tmp_path)
    client = module.app.test_client()
    other_header = _test_client_auth(module, "other", "password2")
    target = tmp_path / "probe_auth"
    _upsert_task_for_user(
        module,
        "a" * 32,
        filename="input.fasta",
        file_path=target / "input.fasta",
        result_dir=target,
        username="tester",
    )

    with caplog.at_level(logging.WARNING):
        response = client.get(f"/compute/api/running/{'a' * 32}", headers=other_header)

    assert response.status_code == 404
    assert "Task access denied" in caplog.text


def test_runner_root_rejects_a_root_outside_the_configured_tree(monkeypatch, tmp_path):
    runners = tmp_path / "candidate-runners"
    runners.mkdir()
    outsider = tmp_path / "image" / "baked"
    outsider.mkdir(parents=True)
    monkeypatch.setenv("RUNNERS_DIR", str(runners))

    runtime = SimpleNamespace(root=str(outsider), definition="")
    with pytest.raises(ResultContractError, match="Runner assets must live under docker/runners"):
        runner_root(SimpleNamespace(runtime=runtime), str(tmp_path / "server"))


def _load_module(monkeypatch, tmp_path):
    from conftest import _load_pssm_module

    return _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
