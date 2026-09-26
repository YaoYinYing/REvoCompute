# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import io
import json
import threading
import uuid

from pathlib import Path

import pytest
from conftest import (
    _admin_client_auth,
    _extract_md5,
    _insert_pending_task,
    _load_pssm_module,
    _relocate_task_artifacts,
    _task_owner,
    _test_client_auth,
    _upsert_task_for_user,
)

# Auth endpoint tests — /api/auth/me, API keys, password reset, etc.
# ==================================================================
# Race condition tests — TOCTOU and concurrent state manipulation
# ==================================================================


def test_race_cancel_finished_task_rejected(monkeypatch, tmp_path):
    """Cancelling an already-finished task returns 400 (TOCTOU after completion)."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    module.task_store

    # Simulate task that finished while user was about to click cancel
    result_dir = tmp_path / "race_cancel"
    result_dir.mkdir(parents=True, exist_ok=True)
    md5sum = uuid.uuid4().hex
    fasta_path = result_dir / "seqs.fasta"
    fasta_path.write_text(">race\nACDE\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="seqs.fasta",
        file_path=fasta_path,
        result_dir=result_dir,
        username="tester",
        status="finished",
    )
    resp = client.post(f"/compute/api/cancel/{md5sum}", headers=auth_header)
    assert resp.status_code == 400
    assert "not pending or running" in resp.json["error"]


def test_race_cancel_loses_atomic_claim_to_completion(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    from revocompute import routes

    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    md5sum = _insert_pending_task(module, tmp_path / "result")

    def finish_before_claim(task_id, **fields):
        assert task_id == md5sum
        module.task_store.update_task(md5sum, status="finished")
        return False

    monkeypatch.setattr(module.task_store, "claim_task_cancellation", finish_before_claim)
    monkeypatch.setattr(
        routes.cancel_compute_resources,
        "delay",
        lambda **kwargs: pytest.fail("completed task resources must not be cancelled"),
    )

    response = client.post(f"/compute/api/cancel/{md5sum}", headers=auth_header)

    assert response.status_code == 409
    assert module.task_store.get_task(md5sum)["status"] == "finished"


def test_race_cancel_already_cancelled_task(monkeypatch, tmp_path):
    """Re-cancelling a cancelled task returns 400."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    module.task_store

    result_dir = tmp_path / "race_recancel"
    result_dir.mkdir(parents=True, exist_ok=True)
    md5sum = uuid.uuid4().hex
    fasta_path = result_dir / "seqs.fasta"
    fasta_path.write_text(">race\nACDE\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="seqs.fasta",
        file_path=fasta_path,
        result_dir=result_dir,
        username="tester",
        status="cancelled",
    )
    resp = client.post(f"/compute/api/cancel/{md5sum}", headers=auth_header)
    assert resp.status_code == 400
    assert "not pending or running" in resp.json["error"]


def test_race_delete_already_cancelled_task(monkeypatch, tmp_path):
    """Deleting a cancelled task succeeds (cleanup is idempotent)."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    module.task_store

    result_dir = tmp_path / "race_del_cancelled"
    result_dir.mkdir(parents=True, exist_ok=True)
    md5sum = uuid.uuid4().hex
    fasta_path = result_dir / "seqs.fasta"
    fasta_path.write_text(">race\nACDE\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="seqs.fasta",
        file_path=fasta_path,
        result_dir=result_dir,
        username="tester",
        status="cancelled",
    )
    resp = client.delete(f"/compute/api/delete/{md5sum}", headers=auth_header)
    assert resp.status_code == 200
    assert resp.json["status"] == "deleted"


def test_race_upload_dedup_race_condition(monkeypatch, tmp_path):
    """Two rapid uploads with identical content get proper dedup."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})

    class _DummyAsyncResult:
        id = "celery-test-id"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *a, **kw: _DummyAsyncResult())

    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    content = b">same\nACDEFGHIKLMNPQRSTVWY\n"

    # First upload
    r1 = client.post(
        "/compute/api/post",
        data={
            "task_type": "gremlin",
            "file": (io.BytesIO(content), "same.fasta"),
            "input_roles": "sequence",
        },
        headers=auth_header,
    )
    assert r1.status_code == 302
    # Second upload — same content, no delay
    r2 = client.post(
        "/compute/api/post",
        data={
            "task_type": "gremlin",
            "file": (io.BytesIO(content), "same.fasta"),
            "input_roles": "sequence",
        },
        headers=auth_header,
    )
    # Already queued → 202 dedup
    assert r2.status_code == 202
    assert r2.json["status"] == "Task already queued or running"


class _ReentrantClaimStore:
    """Task store double: the first claim wins, later dispatches see it taken.

    The worker re-reads the task immediately before claiming, so the loser is
    the dispatch that starts after the winner has already queued the row.
    """

    def __init__(self, store: object, md5sum: str) -> None:
        self._store = store
        self._claimed = False
        self._md5sum = md5sum

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)

    def get_task(self, _md5sum: str) -> dict:
        task = self._store.get_task(self._md5sum)
        task["status"] = "queued" if self._claimed else "pending"
        return task

    def claim_task_execution(self, _md5sum: str, **kwargs: object) -> bool:
        if self._claimed:
            return False
        self._claimed = True
        return True


def test_execute_compute_task_claims_dispatch_exactly_once(monkeypatch, tmp_path):
    """Two dispatches of one task id start exactly one allocation."""
    import hashlib
    import time

    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    owner = _task_owner(module, "tester")
    md5sum = uuid.uuid4().hex
    result_dir = _relocate_task_artifacts(module, md5sum, tmp_path / "result", owner)
    snapshot = Path(module.app.config["storage_resolver"].get_input_root({"md5sum": md5sum, **owner})) / "seq.fasta"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    content = b">race\nACDE\n"
    snapshot.write_bytes(content)
    blob = Path(module.task_runtime.CONFIG.upload_folder) / f"{hashlib.sha256(content).hexdigest()}.upload"
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(content)
    module.task_store.upsert_task(
        md5sum,
        filename="seq.fasta",
        file_path=str(snapshot),
        uploaded_at=time.time(),
        status="pending",
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username="tester",
        task_type="gremlin",
        submitted_by_user_id=int(owner["submitted_by_user_id"]),
        storage_key=owner["storage_key"],
        input_form=json.dumps(
            {
                "entities": [
                    {
                        "name": "sequence",
                        "type": "file",
                        "role": "sequence",
                        "value": "seq.fasta",
                        "relative_path": "seq.fasta",
                        "hash": hashlib.sha256(content).hexdigest(),
                        "format": "fasta",
                        "logical_type": "sequence_alignment",
                        "snapshot_path": str(snapshot),
                        "snapshot_root": str(snapshot.parent),
                        "workspace_key": owner["storage_key"],
                    }
                ]
            }
        ),
    )
    assert result_dir.is_dir()

    launches: list[str] = []
    winner_launched = threading.Event()
    duplicate_returned = threading.Event()

    def _fake_job(task_id, tt, runner, entities, output_dir, **kwargs):
        launches.append(task_id)
        winner_launched.set()
        # Hold the first allocation open while the duplicate dispatch runs.
        duplicate_returned.wait(timeout=10)
        return module.task_runtime.JobState.COMPLETED

    monkeypatch.setattr(module.task_runtime, "_run_compute_job", _fake_job)

    errors: list[BaseException] = []

    def _dispatch() -> None:
        try:
            module.task_runtime._execute_compute_task(md5sum)
        except BaseException as exc:  # pylint: disable=broad-except
            errors.append(exc)

    # A duplicate dispatch reads the row after the winner queued it.  Let the
    # first claim through, then block every later one so the loser proves it
    # returns instead of queueing behind the live allocation.
    claim_store = _ReentrantClaimStore(module.task_store, md5sum)
    monkeypatch.setitem(module.task_runtime._execute_compute_task.__globals__, "task_store", claim_store)

    winner = threading.Thread(target=_dispatch)
    winner.start()
    assert winner_launched.wait(timeout=10), "the first dispatch must reach the scheduler"

    duplicate = threading.Thread(target=_dispatch)
    duplicate.start()
    duplicate.join(timeout=10)
    assert not duplicate.is_alive(), "the duplicate dispatch must return without waiting on the allocation"
    duplicate_returned.set()
    winner.join(timeout=10)

    assert not errors, errors
    assert launches == [md5sum], "a duplicated dispatch must not start a second allocation"
    assert snapshot.is_file(), "the winner's immutable input snapshot must survive the duplicate dispatch"
    # The winner ran to completion; the loser left no second status behind.
    assert module.task_store.get_task(md5sum)["status"] == "finished"


def test_race_token_usage_after_concurrent_logout(monkeypatch, tmp_path):
    """Token used after logout is rejected (token_version incremented on logout)."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    _test_client_auth(module)
    # Get token
    login = client.post(
        "/compute/api/auth/login",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "tester", "password": "password"}),
    )
    token = login.json["token"]
    # Logout — increments token_version, invalidating all tokens
    client.post("/compute/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    # Old token must be rejected
    resp = client.get("/compute/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_race_status_polling_during_task_transition(monkeypatch, tmp_path):
    """Polling GET /api/running during status transitions returns consistent state."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    module.task_store

    result_dir = tmp_path / "poll_race"
    result_dir.mkdir(parents=True, exist_ok=True)
    md5sum = uuid.uuid4().hex
    fasta_path = result_dir / "s.fasta"
    fasta_path.write_text(">x\nACDE\n", encoding="utf-8")

    # Simulate rapid polling across status transitions
    transitions = ["pending", "queued", "running", "finished"]
    for status in transitions:
        _upsert_task_for_user(
            module,
            md5sum,
            filename="s.fasta",
            file_path=fasta_path,
            result_dir=result_dir,
            username="tester",
            status=status,
        )
        resp = client.get(f"/compute/api/running/{md5sum}", headers=auth_header)
        valid_statuses = {200, 202}
        assert resp.status_code in valid_statuses, f"Status {status}: got {resp.status_code}"


def test_race_batch_delete_duplicate_ids(monkeypatch, tmp_path):
    """Batch delete with duplicate task IDs handles dedup correctly."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    module.task_store

    result_dir = tmp_path / "dedup_race"
    result_dir.mkdir(parents=True, exist_ok=True)
    md5sum = uuid.uuid4().hex
    fasta_path = result_dir / "s.fasta"
    fasta_path.write_text(">x\nACDE\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="s.fasta",
        file_path=fasta_path,
        result_dir=result_dir,
        username="tester",
        status="cancelled",
    )
    # Send the same md5sum 3 times
    resp = client.post(
        "/compute/api/delete",
        headers={**auth_header, "Content-Type": "application/json"},
        data=json.dumps({"md5sums": [md5sum, md5sum, md5sum]}),
    )
    assert resp.status_code == 200
    assert len(resp.json["deleted"]) == 1


def test_race_batch_delete_with_nonexistent_and_duplicate(monkeypatch, tmp_path):
    """Batch delete with mix of valid, invalid, duplicate, and nonexistent IDs."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    module.task_store

    result_dir = tmp_path / "mixed_race"
    result_dir.mkdir(parents=True, exist_ok=True)
    valid_md5 = uuid.uuid4().hex
    another_md5 = uuid.uuid4().hex
    fasta_path = result_dir / "s.fasta"
    fasta_path.write_text(">x\nACDE\n", encoding="utf-8")
    for md5 in (valid_md5, another_md5):
        _upsert_task_for_user(
            module,
            md5,
            filename="s.fasta",
            file_path=fasta_path,
            result_dir=result_dir,
            username="tester",
            status="cancelled",
        )

    nonexistent = "0" * 32
    resp = client.post(
        "/compute/api/delete",
        headers={**auth_header, "Content-Type": "application/json"},
        data=json.dumps({"md5sums": [valid_md5, nonexistent, valid_md5, another_md5]}),
    )
    assert resp.status_code == 200
    result = resp.json
    assert valid_md5 in result["deleted"]
    assert another_md5 in result["deleted"]
    assert nonexistent in result["not_found"]
    assert len(result["deleted"]) == 2


def test_race_cancel_concurrent_with_worker_completion(monkeypatch, tmp_path):
    """Cancel while worker completes — DB terminal-status guard prevents resurrection."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    db = module.task_store

    result_dir = tmp_path / "worker_race"
    result_dir.mkdir(parents=True, exist_ok=True)
    md5sum = uuid.uuid4().hex
    fasta_path = result_dir / "s.fasta"
    fasta_path.write_text(">x\nACDE\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="s.fasta",
        file_path=fasta_path,
        result_dir=result_dir,
        username="tester",
        status="cancelled",
    )
    # Simulate worker trying to write "finished" after user cancelled
    db.update_task(md5sum, status="finished", error=None)
    task = db.get_task(md5sum)
    # Terminal status guard: cancelled tasks stay cancelled
    assert task["status"] == "cancelled", f"Task resurrected to {task['status']}"


def test_race_status_polling_on_deleted_task(monkeypatch, tmp_path):
    """Polling a deleted task returns the correct deleted status."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    module.task_store

    result_dir = tmp_path / "deleted_poll"
    result_dir.mkdir(parents=True, exist_ok=True)
    md5sum = uuid.uuid4().hex
    # Covers both delete-status variants
    for d_status in ("deleted:cancel", "deleted:finshed"):
        fasta_path = result_dir / f"{d_status.replace(':', '_')}.fasta"
        fasta_path.write_text(">x\nACDE\n", encoding="utf-8")
        _upsert_task_for_user(
            module,
            md5sum,
            filename="s.fasta",
            file_path=fasta_path,
            result_dir=result_dir,
            username="tester",
            status=d_status,
        )
        resp = client.get(f"/compute/api/running/{md5sum}", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json
        assert data["md5sum"] == md5sum
