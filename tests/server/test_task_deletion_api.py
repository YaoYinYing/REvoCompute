# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""User deletion resumes the data lifecycle instead of settling over live bytes.

Every case drives the real HTTP delete path and the real store and ledger: the
Task may settle to ``deleted:*`` only once the lifecycle records ``PURGED`` and
the charged bytes were released exactly once.
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
from revocompute import resource_lifecycle
from revocompute.resource_ledger import DataLifecycleState

GIB = 1024**3


def _route_globals(module) -> dict:
    """Reach the real routes.py globals behind the login wrapper decorators."""
    view = module.app.view_functions["delete_task"]
    while not view.__globals__.get("__file__", "").endswith("routes.py"):
        view = view.__wrapped__
    return view.__globals__


def _app(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    return module, module.app.test_client(), _test_client_auth(module)


def _seed_task(module, tmp_path, *, status: str = "finished", charge: int | None = GIB):
    """A real Task with an artifact file and, by default, a charged lifecycle."""
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
        status=status,
    )
    user_id = int(owner["submitted_by_user_id"])
    if charge:
        module.task_store.ensure_data_lifecycle(md5sum, user_id=user_id, logical_bytes=charge)
    return md5sum, result_dir, artifact, user_id


def _releases(module, user_id: int) -> list[int]:
    return [
        entry["quantity"]
        for entry in module.task_store.list_ledger(user_id)
        if entry["reason_code"] == "storage_released"
    ]


def test_delete_reclaims_a_stale_purge_and_releases_the_charge_once(monkeypatch, tmp_path):
    """A crash after the purge claim is finished by the next delete, once."""
    module, client, auth = _app(monkeypatch, tmp_path)
    md5sum, result_dir, _artifact, user_id = _seed_task(module, tmp_path)
    task = module.task_store.get_task(md5sum)
    stale = time.time() - resource_lifecycle.PURGE_STALE_SECONDS - 10
    assert resource_lifecycle.request_data_deletion(module.task_store, task, actor_user_id=None, at=stale)
    assert module.task_store.begin_data_purge(md5sum, at=stale + 1)

    response = client.delete(f"/compute/api/delete/{md5sum}", headers=auth)

    assert response.status_code == 200
    assert not result_dir.exists()
    assert module.task_store.get_data_lifecycle(md5sum)["state"] == DataLifecycleState.PURGED.value
    assert module.task_store.get_task(md5sum)["status"] == "deleted:finshed"
    assert _releases(module, user_id) == [GIB]


def test_delete_while_a_purge_is_live_does_not_race_it(monkeypatch, tmp_path):
    """A fresh PURGING claim owns the Task; the delete leaves it resumable."""
    module, client, auth = _app(monkeypatch, tmp_path)
    md5sum, result_dir, artifact, user_id = _seed_task(module, tmp_path)
    now = time.time()
    task = module.task_store.get_task(md5sum)
    assert resource_lifecycle.request_data_deletion(module.task_store, task, actor_user_id=None, at=now)
    assert module.task_store.begin_data_purge(md5sum, at=now)

    response = client.delete(f"/compute/api/delete/{md5sum}", headers=auth)

    assert response.status_code == 409
    status = module.task_store.get_task(md5sum)["status"]
    assert status == "deleting:finished"
    assert not status.startswith("deleted:")
    assert module.task_store.get_data_lifecycle(md5sum)["state"] == DataLifecycleState.PURGING.value
    assert artifact.is_file()
    assert result_dir.exists()
    assert _releases(module, user_id) == []


def test_failed_purge_keeps_the_claim_and_a_retry_finishes_it(monkeypatch, tmp_path):
    """A destructive failure answers 500 and a later delete completes the purge."""
    module, client, auth = _app(monkeypatch, tmp_path)
    md5sum, result_dir, artifact, user_id = _seed_task(module, tmp_path)
    routes = _route_globals(module)
    original = routes["_delete_task_artifacts"]

    def _crash(_task):
        raise RuntimeError("filesystem went away")

    monkeypatch.setitem(routes, "_delete_task_artifacts", _crash)

    failed = client.delete(f"/compute/api/delete/{md5sum}", headers=auth)

    assert failed.status_code == 500
    status = module.task_store.get_task(md5sum)["status"]
    assert status == "deleting:finished"
    assert not status.startswith("deleted:")
    assert module.task_store.get_data_lifecycle(md5sum)["state"] == DataLifecycleState.ERROR.value
    assert artifact.is_file()
    assert _releases(module, user_id) == []

    monkeypatch.setitem(routes, "_delete_task_artifacts", original)
    response = client.delete(f"/compute/api/delete/{md5sum}", headers=auth)

    assert response.status_code == 200
    assert not result_dir.exists()
    assert module.task_store.get_data_lifecycle(md5sum)["state"] == DataLifecycleState.PURGED.value
    assert module.task_store.get_task(md5sum)["status"] == "deleted:finshed"
    assert _releases(module, user_id) == [GIB]


def test_settled_purge_is_not_rerun(monkeypatch, tmp_path):
    """A crash after PURGED settles the Task without reopening the purge."""
    module, client, auth = _app(monkeypatch, tmp_path)
    md5sum, result_dir, _artifact, user_id = _seed_task(module, tmp_path, status="deleting:finished")
    task = module.task_store.get_task(md5sum)
    assert resource_lifecycle.request_data_deletion(module.task_store, task, actor_user_id=None)
    assert resource_lifecycle.purge_task_data(
        module.task_store, task, remove_artifacts=_route_globals(module)["_delete_task_artifacts"]
    )
    before = module.task_store.get_data_lifecycle(md5sum)
    assert before["state"] == DataLifecycleState.PURGED.value
    assert not result_dir.exists()
    released_before = _releases(module, user_id)
    assert released_before == [GIB]

    routes = _route_globals(module)

    def _must_not_run(_task):
        raise AssertionError("a settled purge must not remove artifacts again")

    monkeypatch.setitem(routes, "_delete_task_artifacts", _must_not_run)

    response = client.delete(f"/compute/api/delete/{md5sum}", headers=auth)

    assert response.status_code == 200
    assert module.task_store.get_task(md5sum)["status"] == "deleted:finshed"
    after = module.task_store.get_data_lifecycle(md5sum)
    assert after["purged_at"] == before["purged_at"]
    assert _releases(module, user_id) == released_before


def _purged_claim(module, md5sum, *, actor_user_id):
    """Leave the durable state of a crash after PURGED and before the status write."""
    task = module.task_store.get_task(md5sum)
    assert resource_lifecycle.request_data_deletion(module.task_store, task, actor_user_id=actor_user_id)
    assert resource_lifecycle.purge_task_data(
        module.task_store, task, remove_artifacts=_route_globals(module)["_delete_task_artifacts"]
    )
    return module.task_store.get_data_lifecycle(md5sum)


def _settle_with_maintenance(module, monkeypatch):
    from revocompute.maintenance.tasks import resource_maintenance

    def _must_not_run(_task):
        raise AssertionError("a completed purge must not remove artifacts again")

    monkeypatch.setattr(resource_maintenance, "delete_task_artifacts", _must_not_run)
    monkeypatch.setattr(resource_maintenance, "fetch_scheduler_evidence", lambda store, *args, **kwargs: {})
    return resource_maintenance.run_resource_maintenance(
        task_store=module.task_store,
        results_folder=str(module.app.config["RESULTS_FOLDER"]),
    )


def test_maintenance_settles_a_user_purge_left_in_its_claim(monkeypatch, tmp_path):
    """A crash after PURGED and before the status write is finished without a re-purge."""
    module, _client, _auth = _app(monkeypatch, tmp_path)
    md5sum, result_dir, _artifact, user_id = _seed_task(module, tmp_path, status="deleting:finished")
    before = _purged_claim(module, md5sum, actor_user_id=user_id)
    assert _releases(module, user_id) == [GIB]

    report = _settle_with_maintenance(module, monkeypatch)

    assert report["settled_claims"] == 1
    task = module.task_store.get_task(md5sum)
    assert (task["status"], task["error"]) == ("deleted:finshed", "Task deleted by user")
    assert not result_dir.exists()
    assert module.task_store.get_data_lifecycle(md5sum)["purged_at"] == before["purged_at"]
    assert _releases(module, user_id) == [GIB]


def test_maintenance_keeps_retention_provenance(monkeypatch, tmp_path):
    """A claim retention requested settles as cleaned, never as a user deletion."""
    module, _client, _auth = _app(monkeypatch, tmp_path)
    md5sum, _result_dir, _artifact, user_id = _seed_task(module, tmp_path, status="deleting:finished")
    _purged_claim(module, md5sum, actor_user_id=None)

    report = _settle_with_maintenance(module, monkeypatch)

    assert report["settled_claims"] == 1
    status = module.task_store.get_task(md5sum)["status"]
    assert status == "cleaned:finished"
    assert not status.startswith("deleted:")


def test_maintenance_settles_the_cancel_lane_and_dates_it(monkeypatch, tmp_path):
    """A cancelled Task's claim gains the completion time the live route would write."""
    module, _client, _auth = _app(monkeypatch, tmp_path)
    md5sum, _result_dir, _artifact, user_id = _seed_task(module, tmp_path, status="deleting:cancel")
    before = module.task_store.get_task(md5sum)
    _purged_claim(module, md5sum, actor_user_id=user_id)

    report = _settle_with_maintenance(module, monkeypatch)

    assert report["settled_claims"] == 1
    after = module.task_store.get_task(md5sum)
    assert after["status"] == "deleted:cancel"
    assert after["finished_at"] != before["finished_at"]


def test_batch_delete_reports_a_live_purge_as_ignored(monkeypatch, tmp_path):
    """A batch entry whose purge is live is not reported deleted and stays resumable."""
    module, client, auth = _app(monkeypatch, tmp_path)
    md5sum, result_dir, artifact, user_id = _seed_task(module, tmp_path)
    now = time.time()
    task = module.task_store.get_task(md5sum)
    assert resource_lifecycle.request_data_deletion(module.task_store, task, actor_user_id=None, at=now)
    assert module.task_store.begin_data_purge(md5sum, at=now)

    response = client.post("/compute/api/delete", headers=auth, json={"md5sums": [md5sum]})

    assert response.status_code == 200
    body = response.get_json()
    assert body["deleted"] == []
    assert body["ignored"] == [md5sum]
    assert module.task_store.get_task(md5sum)["status"] == "deleting:finished"
    assert artifact.is_file()
    assert result_dir.exists()
    assert _releases(module, user_id) == []


def test_a_repeated_delete_resumes_the_interrupted_claim(monkeypatch, tmp_path):
    """The claim is durable, so the same request can finish what a crash left."""
    module, client, auth = _app(monkeypatch, tmp_path)
    md5sum, result_dir, _artifact, _user_id = _seed_task(module, tmp_path, charge=None)

    def _crash(_task):
        raise RuntimeError("process died before deleting artifacts")

    monkeypatch.setitem(_route_globals(module), "_delete_task_artifacts", _crash)
    assert client.delete(f"/compute/api/delete/{md5sum}", headers=auth).status_code == 500
    assert module.task_store.get_task(md5sum)["status"] == "deleting:finished"

    monkeypatch.undo()
    response = client.delete(f"/compute/api/delete/{md5sum}", headers=auth)

    assert response.status_code == 200
    assert module.task_store.get_task(md5sum)["status"] == "deleted:finshed"
    assert not Path(result_dir).exists()


def test_deleting_an_already_deleted_task_changes_nothing(monkeypatch, tmp_path):
    """Retirement is idempotent; a second delete neither re-dates nor relanes it."""
    module, client, auth = _app(monkeypatch, tmp_path)
    md5sum, _result_dir, _artifact, _user_id = _seed_task(module, tmp_path, status="deleted:finshed", charge=None)
    before = module.task_store.get_task(md5sum)

    response = client.delete(f"/compute/api/delete/{md5sum}", headers=auth)

    assert response.status_code == 200
    after = module.task_store.get_task(md5sum)
    assert (after["status"], after["finished_at"]) == (before["status"], before["finished_at"])
