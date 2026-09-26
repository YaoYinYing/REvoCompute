# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Round-5 regression: a reserved Task ID is never re-prepared or re-dispatched.

``_derive_task_id`` hashes only the task type, the coerced params and the input
hashes, so the identical form derives the identical id.  A ``cancelled`` row
used to fall through ``_existing_upload_response`` into ``_prepare_task_record``
— a claim-free ``rmtree`` of the task's input snapshot and output root — followed
by ``upsert_task(status="pending")``, which overwrote the terminal row in place,
and a second ``run_compute_task.apply_async``.

Cancellation is asynchronous (``cancel_compute_resources.delay``, and the Celery
revoke does not reach an already-executing task), so the first allocation could
still be live: the live job's snapshot was deleted underneath it, its row was
rewritten to ``pending`` with ``slurm_job_id`` still set, and a second allocation
was dispatched for the same id.

A terminal or claimed row now reserves its Task ID: the store refuses the
clobber and the submit route answers the resubmission with the existing task.
"""

from __future__ import annotations

import inspect
import io
import threading
import pathlib
import time
import uuid

import pytest

from conftest import _load_pssm_module, _task_owner, _test_client_auth, _upsert_task_for_user
from revocompute.db import TaskIdReservedError


def _submit(client, auth_header, filename="in.fasta"):
    return client.post(
        "/compute/api/post",
        data={
            "task_type": "gremlin",
            "files": (io.BytesIO(b">x\nACDE\n"), filename),
            "input_roles": "sequence",
        },
        headers=auth_header,
        content_type="multipart/form-data",
    )


def _recording_dispatch(module, monkeypatch) -> list[str]:
    dispatches: list[str] = []

    class _Queued:
        id = "queued-resubmit"

    def _record(*args, **kwargs):
        dispatches.append(args[0] if args else kwargs.get("args"))
        return _Queued()

    monkeypatch.setattr(module.run_compute_task, "apply_async", _record)
    return dispatches


def test_a_cancelled_task_id_is_not_reused_or_dispatched_twice(monkeypatch, tmp_path):
    """A cancelled row keeps its id, its snapshot, and its single allocation."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gremlin"},
    )
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    dispatches = _recording_dispatch(module, monkeypatch)

    first = _submit(client, auth_header)
    assert first.status_code == 302, first.get_json()
    md5sum = first.headers["Location"].rsplit("/", 1)[-1]
    assert len(dispatches) == 1
    owner = {"md5sum": md5sum, "storage_key": module.task_store.get_task(md5sum)["storage_key"]}
    snapshot_root = module.app.config["storage_resolver"].get_input_root(owner)
    manifest = pathlib.Path(str(snapshot_root)) / "inputs" / "task.json"
    assert manifest.is_file()

    # The user cancels; the worker is asked to stop resources asynchronously,
    # so the first allocation can still be live when the form is sent again.
    assert module.task_store.claim_task_cancellation(md5sum) is True
    assert module.task_store.get_task(md5sum)["status"] == "cancelled"

    second = _submit(client, auth_header)

    row = module.task_store.get_task(md5sum)
    print(
        "\nreserved-id resubmit ->",
        second.status_code,
        "| dispatches:",
        len(dispatches),
        "| row status:",
        row["status"],
    )
    assert second.status_code == 409, second.get_json()
    assert second.json["task_id"] == md5sum
    assert second.json["status"] == "cancelled"
    assert len(dispatches) == 1, "the reserved task id was dispatched a second time"
    assert row["status"] == "cancelled"
    assert manifest.is_file(), "the live allocation's input snapshot was destroyed"


def test_a_deleted_task_id_is_reserved_against_resubmission(monkeypatch, tmp_path):
    """A deleted row still owns its id; the artifacts stay deleted."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gremlin"},
    )
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    dispatches = _recording_dispatch(module, monkeypatch)

    first = _submit(client, auth_header)
    assert first.status_code == 302, first.get_json()
    md5sum = first.headers["Location"].rsplit("/", 1)[-1]

    deleted = client.delete(f"/compute/api/delete/{md5sum}", headers=auth_header)
    assert deleted.status_code == 200, deleted.get_json()
    assert module.task_store.get_task(md5sum)["status"] in {"deleted:cancel", "deleted:finshed"}

    second = _submit(client, auth_header)

    assert second.status_code == 409, second.get_json()
    assert len(dispatches) == 1
    assert module.task_store.get_task(md5sum)["status"] in {"deleted:cancel", "deleted:finshed"}


def test_a_fresh_input_path_still_creates_a_new_id(monkeypatch, tmp_path):
    """Reserving the id must not make the method unrunnable again.

    The reserved id is content-derived, so the same science re-run as a new
    upload (a different input path, or changed parameters) derives a different
    id and is dispatched normally.
    """
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gremlin"},
    )
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    dispatches = _recording_dispatch(module, monkeypatch)

    first = _submit(client, auth_header)
    assert first.status_code == 302, first.get_json()
    first_id = first.headers["Location"].rsplit("/", 1)[-1]

    second = _submit(client, auth_header, filename="again.fasta")
    assert second.status_code == 302, second.get_json()
    second_id = second.headers["Location"].rsplit("/", 1)[-1]

    assert second_id != first_id
    assert len(dispatches) == 2
    assert module.task_store.get_task(second_id)["status"] == "pending"


def test_upsert_refuses_a_reserved_row_without_wiping_it(monkeypatch, tmp_path):
    """Store-level backstop: a caller that derived an ID cannot clobber a
    terminal row; a caller that names an ID may still refresh its own row."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    md5sum = uuid.uuid4().hex
    _upsert_task_for_user(
        module,
        md5sum,
        filename="in.fasta",
        file_path=tmp_path / "in.fasta",
        result_dir=tmp_path / "result",
        username="tester",
        status="cancelled",
    )

    # The submit path derives the ID from content, so it must refuse.
    with pytest.raises(TaskIdReservedError):
        module.task_store.upsert_task(
            md5sum, refuse_reserved=True, status="pending", uploaded_at=time.time(), started_at=None
        )

    row = module.task_store.get_task(md5sum)
    assert row is not None
    assert row["status"] == "cancelled"
    assert row["task_type"] == "gremlin"
    assert row["filename"] == "in.fasta"

    # A caller that *names* the ID (a live-test fixture, a re-seed) is not
    # deriving it and keeps the default behaviour.
    _upsert_task_for_user(
        module,
        md5sum,
        filename="reseeded.fasta",
        file_path=tmp_path / "in.fasta",
        result_dir=tmp_path / "result",
        username="tester",
        status="finished",
    )
    assert module.task_store.get_task(md5sum)["filename"] == "reseeded.fasta"

def test_a_failed_row_that_still_owns_an_allocation_is_reserved(monkeypatch, tmp_path):
    """Status alone is not the reservation: orphan recovery records `failed`
    *without* confirming cancellation and leaves `slurm_job_id` on the row, so
    that id still owns an allocation and must not be re-prepared.

    The symmetric case — a `failed` row whose handle was cleared — must still be
    re-runnable, so this also pins that the guard is not simply "any failed row".
    """
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gremlin"},
    )
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    dispatches = _recording_dispatch(module, monkeypatch)

    first = _submit(client, auth_header)
    assert first.status_code == 302, first.get_json()
    md5sum = first.headers["Location"].rsplit("/", 1)[-1]
    manifest = pathlib.Path(module.app.config["storage_resolver"].get_input_root(
        {"md5sum": md5sum, "storage_key": _task_owner(module, "tester")["storage_key"]}
    )) / "inputs" / "task.json"
    assert manifest.is_file()

    # The worker records a failure while the scheduler handle is still set.
    module.task_store.update_task(md5sum, status="failed", slurm_job_id="4217")

    reserved = _submit(client, auth_header)
    print("\norphaned failed row: resubmit ->", reserved.status_code, "| dispatches:", len(dispatches))
    assert reserved.status_code == 409, reserved.get_json()
    assert len(dispatches) == 1, "an allocation-owning failed id was re-dispatched"
    assert manifest.is_file(), "the failed row's snapshot was destroyed"

    # With the handle cleared the row no longer owns anything and may re-run.
    module.task_store.update_task(md5sum, slurm_job_id=None)
    rerun = _submit(client, auth_header)
    print("handle cleared: resubmit ->", rerun.status_code, "| dispatches:", len(dispatches))
    assert rerun.status_code in (200, 302), rerun.get_json()
    assert len(dispatches) == 2


def test_concurrent_first_submissions_do_not_destroy_each_others_snapshot(monkeypatch, tmp_path):
    """Two simultaneous *first* submissions of identical content.

    Both derive the same Task ID.  Before the fix both found no row, both
    rmtree-and-rebuilt the same content-derived tree, and only afterwards did
    the database arbitrate — so the loser had already destroyed the winner's
    snapshot, and both requests dispatched an allocation for one ID.

    The interleaving is forced deterministically rather than with racing
    threads: request A is held inside its own snapshot creation while request B
    runs the whole submit path.  It observes only what both the old and new
    code do through the route module's globals (``os.makedirs`` /
    ``shutil.rmtree``), so the same assertions discriminate: a destructive
    preparation by the loser, and a second dispatch, are both failures.
    """
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gremlin"},
    )
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    dispatches = _recording_dispatch(module, monkeypatch)

    # The handler resolves `os`/`shutil` from its own module globals, and the
    # registered view is wrapped by decorators from other modules, so unwrap to
    # reach the live routes globals.  (`from revocompute import routes` would
    # hand back a different module: the test loader drops it from sys.modules.)
    route_globals = inspect.unwrap(module.app.view_functions["upload_file"]).__globals__
    real_os = route_globals["os"]
    real_shutil = route_globals["shutil"]

    counters = {"rmtree": 0, "makedirs": 0}
    release = threading.Event()
    held = threading.Event()

    class _OS:
        @staticmethod
        def makedirs(path, *args, **kwargs):
            result = real_os.makedirs(path, *args, **kwargs)
            if str(path).endswith("inputs"):
                counters["makedirs"] += 1
                if not held.is_set():
                    held.set()
                    assert release.wait(15), "the second submission never completed"
            return result

        def __getattr__(self, name):
            return getattr(real_os, name)

    class _Shutil:
        @staticmethod
        def rmtree(path, *args, **kwargs):
            counters["rmtree"] += 1
            return real_shutil.rmtree(path, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(real_shutil, name)

    monkeypatch.setitem(route_globals, "os", _OS())
    monkeypatch.setitem(route_globals, "shutil", _Shutil())

    outcome: dict[str, object] = {}

    def _submit_a():
        outcome["a"] = _submit(client, auth_header)

    first = threading.Thread(target=_submit_a)
    first.start()
    assert held.wait(15), "the first submission never reached its snapshot step"

    second = _submit(client, auth_header)
    release.set()
    first.join(20)

    task_id = str(module.task_store.list_tasks()[0]["md5sum"])
    snapshot = pathlib.Path(
        module.app.config["storage_resolver"].get_input_root(
            {"md5sum": task_id, "storage_key": _task_owner(module, "tester")["storage_key"]}
        )
    ) / "inputs"
    print(
        f"\nconcurrent first submits: A -> {outcome['a'].status_code} | B -> {second.status_code}"
        f" | rmtrees: {counters['rmtree']} | dispatches: {len(dispatches)}"
    )
    assert second.status_code in (200, 202, 302, 409), second.get_json()
    assert counters["rmtree"] == 0, "the losing submission destroyed the winner's tree"
    assert len(dispatches) == 1, f"one task id was dispatched {len(dispatches)} times"
    assert (snapshot / "task.json").is_file(), "the winner's snapshot did not survive"
