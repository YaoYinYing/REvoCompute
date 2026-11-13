# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Stale purge reclaim and disposal completion are single-writer, provenance-kept facts.

A stale ``PURGING`` claim may be reclaimed by exactly one worker: the reclaim is
a compare-and-set on the claim the caller observed, so a second reclaimer holding
the same observation cannot steal the fresh claim the first one took.  A completed
disposal settles in the lane its *request* names — a user or Admin request to
``deleted:*``, automatic retention to ``cleaned:*`` — no matter which pass ran it.
"""

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
from revocompute import resource_lifecycle, task_state
from revocompute.db import TaskDatabase
from revocompute.maintenance.tasks import result_cleanup as cleanup
from revocompute.resource_ledger import DataLifecycleState
from revocompute.storage import StorageResolver

GIB = 1024**3


def _database(tmp_path: Path) -> TaskDatabase:
    return TaskDatabase(str(tmp_path / "tasks.sqlite3"))


def _own_task(
    database: TaskDatabase,
    task_id: str,
    *,
    user_id: int,
    status: str = task_state.FINISHED,
    finished_at: float = 1_000.0,
) -> None:
    database.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/immutable/input.fasta",
        uploaded_at=900.0,
        finished_at=finished_at,
        status=status,
        is_binary=0,
        username=f"user-{user_id}",
        submitted_by_user_id=user_id,
        storage_key=f"user-{user_id}",
        task_type="cpu_runner",
    )


def _task(task_id: str, *, user_id: int) -> dict:
    return {"md5sum": task_id, "submitted_by_user_id": user_id, "storage_key": f"user-{user_id}"}


def _charge(database: TaskDatabase, task_id: str, *, user_id: int, owned: int = GIB) -> None:
    database.ensure_data_lifecycle(task_id, user_id=user_id, logical_bytes=owned, at=900.0)


def _artifacts(tmp_path: Path, task_id: str, *, user_id: int) -> tuple[Path, Path]:
    """Place one owned artifact at the path the retention remover walks."""
    results = tmp_path / "results"
    resolver = StorageResolver(
        workspace_dir=str(tmp_path / "workspaces"), results_dir=str(results)
    )
    result_dir = Path(resolver.get_task_root(_task(task_id, user_id=user_id)))
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "artifact.txt").write_text("payload\n", encoding="utf-8")
    return results, result_dir


def _releases(database: TaskDatabase, user_id: int) -> list[int]:
    return [
        entry["quantity"]
        for entry in database.list_ledger(user_id)
        if entry["reason_code"] == "storage_released"
    ]


def test_a_second_reclaimer_cannot_steal_a_fresh_claim(tmp_path):
    """Both reclaimers read the same stale claim; only the first may act on it."""
    database = _database(tmp_path)
    task_id = "a1" + "0" * 30
    user_id = 41
    _own_task(database, task_id, user_id=user_id, status=task_state.DELETING_FINISHED)
    _charge(database, task_id, user_id=user_id)
    assert database.claim_data_deletion(task_id, user_id=user_id, actor_user_id=user_id, at=1_000.0)
    assert database.begin_data_purge(task_id, at=1_001.0)
    observed = float(database.get_data_lifecycle(task_id)["claimed_at"])

    now = 1_001.0 + resource_lifecycle.PURGE_STALE_SECONDS + 10
    # Reclaimer A wins the stale observation and takes a fresh claim.
    assert database.reclaim_stale_purge(task_id, expected_claimed_at=observed, at=now)
    fresh = now + 1
    assert database.begin_data_purge(task_id, at=fresh)

    # Reclaimer B holds the same old observation.  Its expectation no longer
    # matches the claim A owns, so it mutates nothing.
    assert database.reclaim_stale_purge(
        task_id, expected_claimed_at=observed, at=now + 2
    ) is False

    record = database.get_data_lifecycle(task_id)
    assert record["state"] == DataLifecycleState.PURGING.value
    assert record["claimed_at"] == fresh


def _app(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    return module, module.app.test_client(), _test_client_auth(module)


def _seed(module, tmp_path, *, status: str = task_state.FINISHED):
    md5sum = uuid.uuid4().hex
    owner = _task_owner(module, "tester")
    result_dir = _relocate_task_artifacts(module, md5sum, tmp_path / "result", owner)
    (result_dir / "artifact.txt").write_text("payload\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="input.fasta",
        file_path=tmp_path / "input.fasta",
        result_dir=result_dir,
        username="tester",
        status=status,
    )
    user_id = int(owner["submitted_by_user_id"])
    module.task_store.ensure_data_lifecycle(md5sum, user_id=user_id, logical_bytes=GIB)
    return md5sum, result_dir, user_id


def _route_globals(module) -> dict:
    """Reach the real routes.py globals behind the login wrapper decorators."""
    view = module.app.view_functions["delete_task"]
    while not view.__globals__.get("__file__", "").endswith("routes.py"):
        view = view.__wrapped__
    return view.__globals__


def test_the_winning_owner_completes_and_the_user_delete_settles_without_a_release(monkeypatch, tmp_path):
    """After the interleave, the fresh owner purges once and the user delete only settles."""
    module, client, auth = _app(monkeypatch, tmp_path)
    md5sum, result_dir, user_id = _seed(module, tmp_path, status=task_state.DELETING_FINISHED)
    database = module.task_store
    stale_at = time.time() - resource_lifecycle.PURGE_STALE_SECONDS - 10
    assert database.claim_data_deletion(
        md5sum, user_id=user_id, actor_user_id=user_id, at=stale_at
    )
    assert database.begin_data_purge(md5sum, at=stale_at + 1)
    observed = float(database.get_data_lifecycle(md5sum)["claimed_at"])

    now = time.time()
    assert database.reclaim_stale_purge(md5sum, expected_claimed_at=observed, at=now)
    fresh = now + 1
    assert database.begin_data_purge(md5sum, at=fresh)
    # The loser still holds the old observation and cannot reclaim A's claim.
    assert database.reclaim_stale_purge(md5sum, expected_claimed_at=observed, at=now + 2) is False

    routes = _route_globals(module)
    real_remove = routes["_delete_task_artifacts"]
    removals: list[str] = []

    def counting_remove(task):
        removals.append(str(task["md5sum"]))
        real_remove(task)

    monkeypatch.setitem(routes, "_delete_task_artifacts", counting_remove)
    task = database.get_task(md5sum)
    counting_remove(task)
    assert database.complete_data_purge(md5sum, at=now + 3)

    response = client.delete(f"/compute/api/delete/{md5sum}", headers=auth)

    assert response.status_code == 200
    assert removals == [md5sum]
    assert not result_dir.exists()
    assert database.get_data_lifecycle(md5sum)["state"] == DataLifecycleState.PURGED.value
    settled = database.get_task(md5sum)
    assert settled["status"] == task_state.DELETED_FINISHED
    assert settled["error"] == "Task deleted by user"
    assert _releases(database, user_id) == [GIB]


def test_retention_finishes_a_user_requested_purge_in_the_user_lane(tmp_path):
    """Retention resuming a user's DELETE_REQUESTED row still settles ``deleted:*``."""
    database = _database(tmp_path)
    task_id = "c3" + "0" * 30
    user_id = 52
    _own_task(database, task_id, user_id=user_id, status=task_state.DELETING_FINISHED)
    _charge(database, task_id, user_id=user_id)
    results, result_dir = _artifacts(tmp_path, task_id, user_id=user_id)
    task = database.get_task(task_id)
    resource_lifecycle.request_data_deletion(database, task, actor_user_id=user_id, at=1_100.0)

    cleaned = cleanup.cleanup_expired_task_artifacts(
        30, task_store=database, results_folder=str(results), now=1_200.0
    )

    assert cleaned == 1
    assert not result_dir.exists()
    settled = database.get_task(task_id)
    assert settled["status"] == task_state.DELETED_FINISHED
    assert settled["error"] == "Task deleted by user"
    assert _releases(database, user_id) == [GIB]


def test_a_user_delete_records_provenance_on_a_retention_request(tmp_path):
    """A named actor arriving on a retention-requested row makes the settle a user deletion."""
    database = _database(tmp_path)
    task_id = "d4" + "0" * 30
    user_id = 53
    _own_task(database, task_id, user_id=user_id, status=task_state.DELETING_FINISHED)
    _charge(database, task_id, user_id=user_id)
    results, result_dir = _artifacts(tmp_path, task_id, user_id=user_id)
    task = database.get_task(task_id)
    resource_lifecycle.request_data_deletion(database, task, actor_user_id=None, at=1_100.0)
    assert database.get_data_lifecycle(task_id)["requested_by_user_id"] is None

    # The user DELETE arrives before the retention worker completes.
    resource_lifecycle.request_data_deletion(database, task, actor_user_id=user_id, at=1_150.0)
    assert database.get_data_lifecycle(task_id)["requested_by_user_id"] == user_id

    cleaned = cleanup.cleanup_expired_task_artifacts(
        30, task_store=database, results_folder=str(results), now=1_200.0
    )

    assert cleaned == 1
    assert not result_dir.exists()
    assert database.get_task(task_id)["status"] == task_state.DELETED_FINISHED
    assert _releases(database, user_id) == [GIB]


def test_a_live_purge_cannot_be_settled_by_retention(tmp_path):
    """A fresh PURGING claim is still owned: retention removes nothing and settles nothing."""
    database = _database(tmp_path)
    task_id = "e5" + "0" * 30
    user_id = 54
    _own_task(database, task_id, user_id=user_id, status=task_state.DELETING_FINISHED)
    _charge(database, task_id, user_id=user_id)
    results, result_dir = _artifacts(tmp_path, task_id, user_id=user_id)
    task = database.get_task(task_id)
    resource_lifecycle.request_data_deletion(database, task, actor_user_id=None, at=1_100.0)
    assert database.begin_data_purge(task_id, at=1_101.0)

    cleaned = cleanup.cleanup_expired_task_artifacts(
        30, task_store=database, results_folder=str(results), now=1_102.0
    )

    assert cleaned == 0
    assert result_dir.exists()
    assert database.get_task(task_id)["status"] == task_state.DELETING_FINISHED
    assert database.get_data_lifecycle(task_id)["state"] == DataLifecycleState.PURGING.value
    assert _releases(database, user_id) == []


def test_a_failed_purge_cannot_be_settled_by_retention(monkeypatch, tmp_path):
    """A raising remover leaves the claim and the charge; no disposal lane is written."""
    database = _database(tmp_path)
    task_id = "f6" + "0" * 30
    user_id = 55
    _own_task(database, task_id, user_id=user_id, status=task_state.DELETING_FINISHED)
    _charge(database, task_id, user_id=user_id)
    results, result_dir = _artifacts(tmp_path, task_id, user_id=user_id)
    task = database.get_task(task_id)
    resource_lifecycle.request_data_deletion(database, task, actor_user_id=user_id, at=1_100.0)

    def refuse_removal(_task, _results_folder, _workspace_folder):
        raise cleanup.ArtifactRemovalError("owned tree could not be removed")

    monkeypatch.setattr(cleanup, "delete_task_artifacts", refuse_removal)

    cleaned = cleanup.cleanup_expired_task_artifacts(
        30, task_store=database, results_folder=str(results), now=1_200.0
    )

    assert cleaned == 0
    assert (result_dir / "artifact.txt").is_file()
    assert database.get_task(task_id)["status"] == task_state.DELETING_FINISHED
    assert database.get_data_lifecycle(task_id)["state"] == DataLifecycleState.ERROR.value
    assert _releases(database, user_id) == []


def test_a_user_delete_records_provenance_on_a_purging_claim(tmp_path):
    """An explicit actor replaces provenance without moving the PURGING state."""
    database = _database(tmp_path)
    task_id = "18" + "0" * 30
    user_id = 57
    _own_task(database, task_id, user_id=user_id, status=task_state.DELETING_FINISHED)
    _charge(database, task_id, user_id=user_id)
    task = database.get_task(task_id)
    resource_lifecycle.request_data_deletion(database, task, actor_user_id=None, at=1_100.0)
    assert database.begin_data_purge(task_id, at=1_101.0)

    # The user DELETE arrives while retention's purge owns the claim.
    resource_lifecycle.request_data_deletion(database, task, actor_user_id=user_id, at=1_102.0)
    record = database.get_data_lifecycle(task_id)
    assert record["state"] == DataLifecycleState.PURGING.value
    assert record["requested_by_user_id"] == user_id
    assert record["claimed_at"] == 1_101.0

    assert database.complete_data_purge(task_id, at=1_103.0)
    assert resource_lifecycle.settle_purged_claims(database, at=1_104.0) == 1

    settled = database.get_task(task_id)
    assert (settled["status"], settled["error"]) == (
        task_state.DELETED_FINISHED,
        "Task deleted by user",
    )
    assert _releases(database, user_id) == [GIB]


def test_retention_preserves_a_cancelled_tasks_finished_at(tmp_path):
    """Retention settles ``cleaned:cancel`` without overwriting the real cancellation time."""
    database = _database(tmp_path)
    now = 2_000_000_000.0
    task_id = "19" + "0" * 30
    user_id = 58
    cancelled_at = now - 31 * 86400
    _own_task(
        database,
        task_id,
        user_id=user_id,
        status=task_state.CANCELLED,
        finished_at=cancelled_at,
    )
    _charge(database, task_id, user_id=user_id)

    assert cleanup.cleanup_expired_task_artifacts(
        30, task_store=database, results_folder=str(tmp_path / "results"), now=now
    ) == 1

    settled = database.get_task(task_id)
    assert settled["status"] == task_state.CLEANED_CANCELLED
    assert settled["finished_at"] == cancelled_at
    assert settled["error"] is None
    assert _releases(database, user_id) == [GIB]


def test_a_user_delete_of_a_cancelled_task_dates_the_completion(tmp_path):
    """The user-owned cancel lane still stamps the completion time."""
    database = _database(tmp_path)
    task_id = "1a" + "0" * 30
    user_id = 59
    _own_task(
        database,
        task_id,
        user_id=user_id,
        status=task_state.DELETING_CANCELLED,
        finished_at=1_000.0,
    )
    _charge(database, task_id, user_id=user_id)
    task = database.get_task(task_id)
    resource_lifecycle.request_data_deletion(database, task, actor_user_id=user_id, at=1_100.0)
    assert resource_lifecycle.purge_task_data(
        database, task, remove_artifacts=lambda _task: None, at=1_200.0
    )

    assert resource_lifecycle.settle_purged_claims(database, at=1_300.0) == 1

    settled = database.get_task(task_id)
    assert settled["status"] == task_state.DELETED_CANCELLED
    assert settled["finished_at"] == 1_300.0
    assert settled["error"] == "Task deleted by user"
    assert _releases(database, user_id) == [GIB]
