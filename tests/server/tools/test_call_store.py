# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import time

import pytest
from celery import Celery

from revocompute.config import ComputeConfig, ToolConfig
from revocompute.maintenance.tasks.tool_cleanup import run_tool_cleanup
from revocompute.tool_calls import ToolAdmissionError, ToolCallDatabase, new_tool_call_id, normalize_tool_call_id
from revocompute.tool_workspace import ToolWorkspace


def _reserve(
    store: ToolCallDatabase,
    *,
    user_id: int = 1,
    key: str | None = None,
    workspace_bytes: int = 0,
    storage_max_bytes: int | None = None,
):
    return store.reserve(
        tool_call_id=new_tool_call_id(),
        tool_type="inspect",
        runtime_family="fixture",
        runtime_identity="fixture-identity",
        user_id=user_id,
        username=f"user-{user_id}",
        parameter_json="{}",
        input_manifest_json='{"inputs":{}}',
        idempotency_key=key,
        per_user_limit=2,
        global_limit=3,
        workspace_bytes=workspace_bytes,
        storage_max_bytes=storage_max_bytes,
        created_at=100.0,
    )


def test_tool_ids_have_a_strict_separate_namespace():
    call_id = new_tool_call_id()
    assert normalize_tool_call_id(call_id) == call_id
    assert normalize_tool_call_id("a" * 32) is None
    assert normalize_tool_call_id("tool_call_../escape") is None


def test_reservation_is_user_scoped_and_idempotent(tmp_path):
    store = ToolCallDatabase(str(tmp_path / "revocompute.sqlite3"))

    first = _reserve(store, user_id=1, key="retry-1")
    second = _reserve(store, user_id=1, key="retry-1")
    other_user = _reserve(store, user_id=2, key="retry-1")

    assert first.created is True
    assert second.created is False
    assert second.call["tool_call_id"] == first.call["tool_call_id"]
    assert other_user.call["tool_call_id"] != first.call["tool_call_id"]
    assert store.get_owned(first.call["tool_call_id"], 2) is None


def test_admission_counts_all_outstanding_work(tmp_path):
    store = ToolCallDatabase(str(tmp_path / "revocompute.sqlite3"))
    _reserve(store, user_id=1)
    _reserve(store, user_id=1)

    try:
        _reserve(store, user_id=1)
    except ToolAdmissionError as exc:
        assert exc.reason == "user_limit"
    else:
        raise AssertionError("per-user outstanding-call limit was not enforced")

    _reserve(store, user_id=2)
    try:
        _reserve(store, user_id=3)
    except ToolAdmissionError as exc:
        assert exc.reason == "global_limit"
    else:
        raise AssertionError("global outstanding-call limit was not enforced")


def test_terminal_transition_and_cleanup_never_select_active_calls(tmp_path):
    store = ToolCallDatabase(str(tmp_path / "revocompute.sqlite3"))
    finished = _reserve(store).call["tool_call_id"]
    active = _reserve(store).call["tool_call_id"]

    assert store.transition(finished, expected=("queued",), status="preparing", started_at=101.0)
    assert store.transition(finished, expected=("preparing",), status="running")
    assert store.transition(
        finished,
        expected=("running",),
        status="finished",
        finished_at=102.0,
        expires_at=202.0,
        result_manifest_json='{"outputs":{}}',
    )
    assert store.cleanup_candidates(now=201.0) == []
    assert [item["tool_call_id"] for item in store.cleanup_candidates(now=203.0)] == [finished]
    assert [item["tool_call_id"] for item in store.cleanup_candidates(now=0.0, storage_pressure=True)] == [finished]
    assert store.delete_terminal(active) is False
    assert store.delete_terminal(finished) is True
    assert store.get(finished) is None


def test_storage_admission_is_atomic_and_active_calls_are_not_reclaimable(tmp_path):
    store = ToolCallDatabase(str(tmp_path / "revocompute.sqlite3"))
    active = _reserve(store, workspace_bytes=60, storage_max_bytes=100).call["tool_call_id"]

    with pytest.raises(ToolAdmissionError, match="storage_limit"):
        _reserve(store, user_id=2, workspace_bytes=50, storage_max_bytes=100)

    assert store.cleanup_candidates(now=0.0, storage_pressure=True) == []
    assert store.delete_terminal(active) is False


def test_ttl_cleanup_removes_expired_row_and_workspace_but_preserves_running(monkeypatch, tmp_path):
    server = tmp_path / "server"
    server.mkdir()
    monkeypatch.setenv("SERVER_DIR", str(server))
    monkeypatch.setenv("RUNNER_UID", "1234")
    monkeypatch.setenv("RUNNER_GID", "5678")
    monkeypatch.setenv("ENABLED_TOOL_FAMILIES", "bioio")
    monkeypatch.setattr(Celery, "send_task", lambda *_args, **_kwargs: None)
    compute = ComputeConfig.from_env()
    config = ToolConfig.from_env(compute)
    store = ToolCallDatabase(compute.db_path)
    workspace = ToolWorkspace(
        config.workspace_root,
        request_max_bytes=config.request_max_bytes,
        output_max_bytes=config.output_max_bytes,
    )
    expired = _reserve(store).call["tool_call_id"]
    running = _reserve(store, user_id=2).call["tool_call_id"]
    workspace.create(expired)
    workspace.create(running)
    (workspace.call_root(expired) / "output" / "old.txt").write_text("old", encoding="utf-8")
    (workspace.call_root(running) / "scratch" / "active.txt").write_text("active", encoding="utf-8")
    now = time.time()
    assert store.transition(
        expired,
        expected=("queued",),
        status="finished",
        finished_at=now - 2,
        expires_at=now - 1,
    )
    assert store.transition(running, expected=("queued",), status="preparing", started_at=now)
    assert store.transition(running, expected=("preparing",), status="running")
    store.engine.dispose()

    assert run_tool_cleanup() == 1

    reopened = ToolCallDatabase(compute.db_path)
    assert reopened.get(expired) is None
    assert not workspace.call_root(expired).exists()
    assert reopened.get(running)["status"] == "running"
    assert workspace.call_root(running).exists()
