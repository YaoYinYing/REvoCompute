# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from unittest.mock import Mock

import pytest
from full_stack_smoke import _wait_for_task, _wait_for_worker, run_full_stack_checks


def test_production_smoke_allows_long_running_cpu_runner_jobs() -> None:
    assert run_full_stack_checks.__defaults__ == (7200.0,)


def test_wait_for_task_rejects_http_error_before_parsing_json() -> None:
    response = Mock(status_code=500, text="upstream unavailable")
    response.json.side_effect = AssertionError("non-200 response must not be parsed")
    session = Mock()
    session.get.return_value = response

    with pytest.raises(AssertionError, match="returned HTTP 500: upstream unavailable"):
        _wait_for_task(session, "http://server.test", "task-id", {}, timeout=1)

    response.json.assert_not_called()


def test_wait_for_worker_retries_a_booting_worker_before_asserting(monkeypatch: pytest.MonkeyPatch) -> None:
    """The web can serve pages long before the Celery worker answers a ping."""
    booting = Mock(status_code=200)
    booting.json.return_value = {"status": "UNAVAILABLE", "stale": False}
    ready = Mock(status_code=200)
    ready.json.return_value = {"status": "HEALTHY", "stale": False}
    session = Mock()
    session.post.side_effect = [booting, ready]
    monkeypatch.setattr("full_stack_smoke.time.sleep", lambda _: None)

    payload = _wait_for_worker(session, "http://server.test", {}, timeout=5)

    assert payload == {"status": "HEALTHY", "stale": False}
    assert session.post.call_count == 2


def test_wait_for_worker_returns_the_last_response_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The caller still sees the failing evidence; the wait only bounds it."""
    booting = Mock(status_code=200)
    booting.json.return_value = {"status": "UNAVAILABLE", "stale": False}
    session = Mock()
    session.post.return_value = booting
    monkeypatch.setattr("full_stack_smoke.time.sleep", lambda _: None)

    payload = _wait_for_worker(session, "http://server.test", {}, timeout=0)

    assert payload["status"] == "UNAVAILABLE"
    assert session.post.call_count == 1


def test_wait_for_task_accepts_pending_202_response(monkeypatch: pytest.MonkeyPatch) -> None:
    pending = Mock(status_code=202, text='{"status":"pending"}')
    pending.json.return_value = {"status": "pending"}
    finished = Mock(status_code=200, text='{"status":"finished"}')
    finished.json.return_value = {"status": "finished"}
    session = Mock()
    session.get.side_effect = [pending, finished]
    monkeypatch.setattr("full_stack_smoke.time.sleep", lambda _: None)

    _wait_for_task(session, "http://server.test", "task-id", {}, timeout=1)

    assert session.get.call_count == 2
