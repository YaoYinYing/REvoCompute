# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Round-4 lifecycle regressions: allowance compare-and-set and claimed deletes."""

from __future__ import annotations

import time
import uuid

from pathlib import Path

from conftest import (
    _load_pssm_module,
    _relocate_task_artifacts,
    _task_owner,
    _test_client_auth,
    _upsert_task_for_user,
)
from revocompute.db import TaskDatabase


def _route_globals(module) -> dict:
    """Reach the real routes.py globals behind the login wrapper decorators."""
    view = module.app.view_functions["delete_task"]
    while not view.__globals__.get("__file__", "").endswith("routes.py"):
        view = view.__wrapped__
    return view.__globals__


def test_concurrent_allowance_update_is_locked_out(tmp_path):
    """The allowance read-modify-write holds the write lock from the start.

    Without that, a second admin's update reads the same stale allowance and
    the period allowance becomes the sum of both intents.  The probe below is a
    second connection attempting the same ``BEGIN IMMEDIATE`` the concurrent
    writer would need: it must fail while the first update is in flight.
    """
    import sqlalchemy as sa

    path = str(tmp_path / "tasks.sqlite3")
    database = TaskDatabase(path)
    user_id = 77
    database.gpu_credit_summary(user_id)
    probe_engine = sa.create_engine(f"sqlite:///{path}", connect_args={"timeout": 0.2})
    outcome: list[str] = []
    original_grant = database._ensure_monthly_gpu_grant

    def _probe_grant(conn, *args, **kwargs):
        with probe_engine.connect() as probe:
            try:
                probe.exec_driver_sql("BEGIN IMMEDIATE")
            except sa.exc.OperationalError:
                outcome.append("locked out")
            else:
                outcome.append("acquired")
                probe.rollback()
        return original_grant(conn, *args, **kwargs)

    database._ensure_monthly_gpu_grant = _probe_grant
    database.set_gpu_monthly_allowance(
        user_id=user_id, monthly_gpu_seconds=9_000, actor_user_id=1, idempotency_key="locked"
    )

    assert outcome == ["locked out"], "the allowance update must claim the write lock before reading"


def test_delete_keeps_artifacts_when_the_status_write_fails(monkeypatch, tmp_path):
    """A failed delete claim leaves the result tree and the row untouched."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    md5sum = uuid.uuid4().hex
    owner = _task_owner(module, "tester")
    result_dir = _relocate_task_artifacts(module, md5sum, tmp_path / "result", owner)
    artifact = result_dir / "artifact.txt"
    artifact.write_text("payload\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="input.fasta",
        file_path=tmp_path / "input.fasta",
        result_dir=result_dir,
        username="tester",
        status="finished",
    )

    def _fail_claim(*args, **kwargs):
        raise RuntimeError("database write failed")

    monkeypatch.setattr(module.task_store, "claim_task_cleanup", _fail_claim)

    response = client.delete(f"/compute/api/delete/{md5sum}", headers=auth_header)

    assert response.status_code >= 500
    assert artifact.is_file(), "artifacts must not be removed before the status write is known to succeed"
    task = module.task_store.get_task(md5sum)
    assert task is not None
    assert task["status"] == "finished"


def test_delete_claims_before_removing_artifacts(monkeypatch, tmp_path):
    """Deleting a task runs claim, then artifact removal, then completion."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    md5sum = uuid.uuid4().hex
    owner = _task_owner(module, "tester")
    result_dir = _relocate_task_artifacts(module, md5sum, tmp_path / "result", owner)
    artifact = result_dir / "artifact.txt"
    artifact.write_text("payload\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="input.fasta",
        file_path=tmp_path / "input.fasta",
        result_dir=result_dir,
        username="tester",
        status="finished",
    )

    observed: list[tuple[str, bool]] = []
    original_claim = module.task_store.claim_task_cleanup
    original_complete = module.task_store.complete_task_cleanup

    def _claim(*args, **kwargs):
        observed.append(("claim", artifact.exists()))
        return original_claim(*args, **kwargs)

    def _complete(*args, **kwargs):
        observed.append(("complete", artifact.exists()))
        return original_complete(*args, **kwargs)

    monkeypatch.setattr(module.task_store, "claim_task_cleanup", _claim)
    monkeypatch.setattr(module.task_store, "complete_task_cleanup", _complete)

    response = client.delete(f"/compute/api/delete/{md5sum}", headers=auth_header)

    assert response.status_code == 200
    assert observed == [("claim", True), ("complete", False)]
    task = module.task_store.get_task(md5sum)
    assert task is not None
    assert task["status"] == "deleted:finshed"
    assert task["error"] == "Task deleted by user"
    assert task["finished_at"] is not None
    assert not result_dir.exists()


def test_delete_race_loser_does_not_revoke_or_delete(monkeypatch, tmp_path):
    """A delete that loses the claim answers 409 and never touches the winner's files."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    md5sum = uuid.uuid4().hex
    owner = _task_owner(module, "tester")
    result_dir = _relocate_task_artifacts(module, md5sum, tmp_path / "result", owner)
    artifact = result_dir / "artifact.txt"
    artifact.write_text("payload\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="input.fasta",
        file_path=tmp_path / "input.fasta",
        result_dir=result_dir,
        username="tester",
        status="finished",
    )

    def _lose_claim(*args, **kwargs):
        return False

    monkeypatch.setattr(module.task_store, "claim_task_cleanup", _lose_claim)

    response = client.delete(f"/compute/api/delete/{md5sum}", headers=auth_header)

    assert response.status_code == 409
    assert artifact.is_file()
    assert module.task_store.get_task(md5sum)["status"] == "finished"


def test_delete_active_task_claims_before_revoking_the_worker(monkeypatch, tmp_path):
    """An active task is revoked only under a claim the caller won."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    md5sum = uuid.uuid4().hex
    owner = _task_owner(module, "tester")
    result_dir = _relocate_task_artifacts(module, md5sum, tmp_path / "result", owner)
    _upsert_task_for_user(
        module,
        md5sum,
        filename="input.fasta",
        file_path=tmp_path / "input.fasta",
        result_dir=result_dir,
        username="tester",
        status="running",
    )
    module.task_store.update_task(md5sum, celery_task_id="worker-celery-id")
    task = module.task_store.get_task(md5sum)

    observed: list[tuple[str, str]] = []
    original_claim = module.task_store.claim_task_cleanup

    def _claim(*args, **kwargs):
        observed.append(("claim", module.task_store.get_task(md5sum)["status"]))
        return original_claim(*args, **kwargs)

    def _revoke(deleted_task):
        observed.append(("revoke", module.task_store.get_task(md5sum)["status"]))

    monkeypatch.setattr(module.task_store, "claim_task_cleanup", _claim)
    monkeypatch.setitem(_route_globals(module), "_revoke_celery_task", _revoke)

    response = client.delete(f"/compute/api/delete/{md5sum}", headers=auth_header)

    assert response.status_code == 200
    # The worker is revoked only after the row is claimed, so a duplicate
    # delete cannot revoke a task it does not own.
    assert observed == [("claim", "running"), ("revoke", "deleting:cancel")]
    assert module.task_store.get_task(md5sum)["status"] == "deleted:cancel"


def test_interrupted_delete_claim_is_resumed_by_maintenance(monkeypatch, tmp_path):
    """A crash after the claim leaves a deleting:* row whose tree is removed later."""
    from revocompute.maintenance.tasks.result_cleanup import cleanup_expired_task_artifacts

    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    md5sum = uuid.uuid4().hex
    owner = _task_owner(module, "tester")
    result_dir = _relocate_task_artifacts(module, md5sum, tmp_path / "result", owner)
    artifact = result_dir / "artifact.txt"
    artifact.write_text("payload\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="input.fasta",
        file_path=tmp_path / "input.fasta",
        result_dir=result_dir,
        username="tester",
        status="finished",
    )

    def _crash(deleted_task):
        raise RuntimeError("process died before deleting artifacts")

    monkeypatch.setitem(_route_globals(module), "_delete_task_artifacts", _crash)

    response = client.delete(f"/compute/api/delete/{md5sum}", headers=auth_header)

    assert response.status_code == 500

    assert module.task_store.get_task(md5sum)["status"] == "deleting:finished"
    assert artifact.is_file()

    monkeypatch.undo()
    cleaned = cleanup_expired_task_artifacts(
        retention_days=1,
        task_store=module.task_store,
        results_folder=module.app.config["RESULTS_FOLDER"],
        now=time.time() + 2 * 86400,
    )

    assert cleaned == 1
    assert not Path(result_dir).exists()
