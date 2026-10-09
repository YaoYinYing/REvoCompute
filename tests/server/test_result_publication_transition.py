# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Publication is one transition, and a result that is not one says why.

The manifest anchor is the authority ``StorageResolver`` verifies against, so an
anchor that was not established means the publication did not happen: no
``manifest.published`` event, no finished task, and no result Core's own reader
would refuse.  These cases drive that split point directly -- the anchor store
fails after the manifest bytes have been serialized -- and then the rollout rule
for results that predate the anchor entirely.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import uuid

import pytest
from revocompute import resource_lifecycle
from revocompute.db import TaskDatabase
from revocompute.storage import ResultPublicationError

from conftest import _load_pssm_module, _test_client_auth, _upsert_task_for_user


def _task(module, tmp_path, *, status: str = "finished", task_type: str = "gremlin") -> tuple[str, Path]:
    task_id = uuid.uuid4().hex
    result_dir = tmp_path / f"result-{task_id[:8]}"
    result_dir.mkdir()
    _upsert_task_for_user(
        module,
        task_id,
        filename="input.fasta",
        file_path=result_dir / "input.fasta",
        result_dir=result_dir,
        username="tester",
        status=status,
        task_type=task_type,
    )
    return task_id, result_dir


def _capture_events(module, monkeypatch) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(module.task_runtime, "emit_event", lambda event, **fields: events.append((event, fields)))
    return events


def _fail_anchor(module, monkeypatch, *, error=OSError("database is locked")) -> None:
    def _raise(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(module.task_store, "record_result_publication", _raise)


# ---------------------------------------------------------------------------
# A published-but-uncharged result is discoverable and repairable
# ---------------------------------------------------------------------------


def _fail_charge(module, monkeypatch, *, error=OSError("database is locked")) -> None:
    """Make the live charge transition fail, leaving the publication pending."""

    def _raise(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(module.task_store, "charge_result_publication", _raise)


def _publish(module, task_id: str, result_dir: Path, *, bytes_written: int = 4096) -> None:
    (result_dir / "result.txt").write_text("x" * bytes_written, encoding="utf-8")
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )


def _upgrade_pre_charge_anchor(database: TaskDatabase) -> None:
    """Reopen an actual pre-column database through the production migration."""
    path = str(database.engine.url.database)
    with database.engine.begin() as connection:
        for column in ("charge_bytes", "charge_state", "charged_at"):
            connection.exec_driver_sql(f"ALTER TABLE result_publications DROP COLUMN {column}")
    database.engine.dispose()
    reopened = TaskDatabase(path)
    reopened.engine.dispose()


@pytest.mark.parametrize("completion_order", ["older_first", "newer_first"])
def test_two_live_publishers_settle_only_the_current_revision(monkeypatch, tmp_path, completion_order):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path, task_type="synthetic-storage")
    store = module.task_store
    charge = module.task_runtime._charge_logical_storage
    user_id = store.get_task(task_id)["submitted_by_user_id"]
    newer_call = []

    def older_paused_after_publication(*args, **kwargs):
        older = store.get_result_publication(task_id)
        with monkeypatch.context() as pause_newer:
            pause_newer.setattr(
                module.task_runtime, "_charge_logical_storage",
                lambda *new_args, **new_kwargs: newer_call.append((new_args, new_kwargs)),
            )
            _publish(module, task_id, result_dir, bytes_written=8192)
        newer = store.get_result_publication(task_id)
        assert newer["revision"] == older["revision"] + 1
        assert newer["manifest_sha256"] != older["manifest_sha256"]
        assert older["charge_bytes"] == 4096 and newer["charge_bytes"] == 8192
        if completion_order == "older_first":
            charge(*args, **kwargs)
            assert store.get_result_publication(task_id) == newer
            assert store.get_data_lifecycle(task_id) is None
            assert store.list_ledger(user_id) == []
            charge(*newer_call[0][0], **newer_call[0][1])
        else:
            charge(*newer_call[0][0], **newer_call[0][1])
            settled = store.get_result_publication(task_id)
            lifecycle = store.get_data_lifecycle(task_id)
            facts = store.list_ledger(user_id)
            charge(*args, **kwargs)
            assert store.get_result_publication(task_id) == settled
            assert store.get_data_lifecycle(task_id) == lifecycle
            assert store.list_ledger(user_id) == facts

    monkeypatch.setattr(module.task_runtime, "_charge_logical_storage", older_paused_after_publication)
    _publish(module, task_id, result_dir, bytes_written=4096)
    publication = store.get_result_publication(task_id)
    assert publication["revision"] == 2 and publication["charge_state"] == "charged"
    assert publication["charge_bytes"] == 8192
    lifecycle = store.get_data_lifecycle(task_id)
    assert lifecycle["logical_bytes"] == lifecycle["accounted_bytes"] == 8192
    assert [fact["quantity"] for fact in store.list_ledger(user_id)] == [-8192]
    charge(*newer_call[0][0], **newer_call[0][1])
    assert [fact["quantity"] for fact in store.list_ledger(user_id)] == [-8192]


@pytest.mark.parametrize("newer_settled", [False, True])
def test_a_repair_snapshot_cannot_settle_a_newer_publication(monkeypatch, tmp_path, newer_settled):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path, task_type="synthetic-storage")
    with monkeypatch.context() as failure:
        _fail_charge(module, failure)
        _publish(module, task_id, result_dir, bytes_written=4096)
    storage = module.task_runtime._storage()
    publication_state = storage.publication_state
    newer, newer_lifecycle, newer_facts = [], [], []

    def replace_after_pending_snapshot(task):
        if not newer:
            with monkeypatch.context() as failure:
                if not newer_settled:
                    _fail_charge(module, failure)
                _publish(module, task_id, result_dir, bytes_written=8192)
            newer.append(module.task_store.get_result_publication(task_id))
            newer_lifecycle.append(module.task_store.get_data_lifecycle(task_id))
            newer_facts.append(module.task_store.list_ledger(task["submitted_by_user_id"]))
        return publication_state(task)

    with monkeypatch.context() as race:
        race.setattr(module.task_runtime, "_storage", lambda: storage)
        race.setattr(storage, "publication_state", replace_after_pending_snapshot)
        assert module.task_runtime._reconcile_pending_storage_charges()["charged"] == 0
    assert module.task_store.get_result_publication(task_id) == newer[0]
    assert module.task_store.get_data_lifecycle(task_id) == newer_lifecycle[0]
    assert module.task_store.list_ledger(module.task_store.get_task(task_id)["submitted_by_user_id"]) == newer_facts[0]
    assert module.task_runtime._reconcile_pending_storage_charges()["charged"] == (0 if newer_settled else 1)
    lifecycle = module.task_store.get_data_lifecycle(task_id)
    assert lifecycle["logical_bytes"] == lifecycle["accounted_bytes"] == 8192
    assert module.task_store.get_result_publication(task_id)["charge_bytes"] == 8192
    assert [fact["quantity"] for fact in module.task_store.list_ledger(lifecycle["subject_id"])] == [-8192]


def test_failure_closing_a_publication_rolls_back_its_lifecycle_and_facts(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path, task_type="synthetic-storage")
    store = module.task_store
    with store.engine.begin() as conn:
        conn.exec_driver_sql("""CREATE TRIGGER interrupt_charge BEFORE UPDATE OF charge_state ON result_publications
            WHEN NEW.charge_state = 'charged' BEGIN SELECT RAISE(ABORT, 'marker write interrupted'); END""")
    _publish(module, task_id, result_dir)
    assert store.get_result_publication(task_id)["charge_state"] == "pending"
    assert store.get_data_lifecycle(task_id) is None
    assert store.list_ledger(store.get_task(task_id)["submitted_by_user_id"]) == []
    with store.engine.begin() as conn:
        conn.exec_driver_sql("DROP TRIGGER interrupt_charge")
    assert module.task_runtime._reconcile_pending_storage_charges()["charged"] == 1
    lifecycle = store.get_data_lifecycle(task_id)
    assert store.get_result_publication(task_id)["charge_bytes"] == lifecycle["accounted_bytes"] == 4096
    assert [fact["quantity"] for fact in store.list_ledger(lifecycle["subject_id"])] == [-4096]
    assert module.task_runtime._reconcile_pending_storage_charges()["charged"] == 0


@pytest.mark.parametrize("new_size", [8192, 2048, 0])
def test_a_new_publication_rebalances_the_append_only_storage_facts(monkeypatch, tmp_path, new_size):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path, task_type="synthetic-storage")
    _publish(module, task_id, result_dir, bytes_written=4096)
    user_id = module.task_store.get_task(task_id)["submitted_by_user_id"]
    first_facts = module.task_store.list_ledger(user_id)
    _publish(module, task_id, result_dir, bytes_written=new_size)
    publication = module.task_store.get_result_publication(task_id)
    lifecycle = module.task_store.get_data_lifecycle(task_id)
    assert publication["charge_state"] == "charged"
    assert publication["charge_bytes"] == lifecycle["logical_bytes"] == lifecycle["accounted_bytes"] == new_size
    facts = module.task_store.list_ledger(user_id)
    assert all(fact in facts for fact in first_facts)
    assert sum(fact["quantity"] for fact in facts) == -new_size
    assert module.task_runtime._reconcile_pending_storage_charges()["charged"] == 0
    assert module.task_store.list_ledger(user_id) == facts


@pytest.mark.parametrize("infra_refresh", ["15", "0"])
def test_the_ordinary_worker_pulse_repairs_a_charge_without_a_restart(monkeypatch, tmp_path, infra_refresh):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={
        "RUNNER_UID": "1234", "RUNNER_GID": "5678", "RESOURCE_MAINTENANCE_SECONDS": "0",
        "INFRA_REFRESH_SECONDS": infra_refresh,
    })
    task_id, result_dir = _task(module, tmp_path, task_type="synthetic-storage")
    with monkeypatch.context() as failure:
        _fail_charge(module, failure)
        _publish(module, task_id, result_dir)
    assert module.task_store.get_result_publication(task_id)["charge_state"] == "pending"
    calls = []

    class ThreePulses:
        def wait(self, interval):
            assert interval > 0
            calls.append(interval)
            return len(calls) > 3

    started = []

    class InlineThread:
        def __init__(self, *, target, args, kwargs=None, **_):
            self.target, self.args, self.kwargs = target, args, kwargs or {}

        def start(self):
            started.append(True)
            self.target(*self.args, **self.kwargs)

    monkeypatch.setattr(module.task_runtime.threading, "Thread", InlineThread)
    monkeypatch.setattr(module.task_runtime.threading, "Event", ThreePulses)
    real_charge = module.task_store.charge_result_publication
    attempts = []

    def fail_first_pulse(*args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("transient database interruption during repair")
        return real_charge(*args, **kwargs)

    monkeypatch.setattr(module.task_store, "charge_result_publication", fail_first_pulse)
    monkeypatch.setattr(module.task_runtime, "_manage_db", type("DisabledSlurm", (), {"slurm_enabled": lambda _: False})())
    module.task_runtime.start_infrastructure_pulse()
    assert started == [True]
    assert attempts == [True, True]  # failed pass, repaired pass, then no pending work
    publication = module.task_store.get_result_publication(task_id)
    lifecycle = module.task_store.get_data_lifecycle(task_id)
    assert publication["charge_state"] == "charged"
    assert publication["charge_bytes"] == lifecycle["logical_bytes"] == lifecycle["accounted_bytes"] == 4096
    assert [fact["quantity"] for fact in module.task_store.list_ledger(lifecycle["subject_id"])] == [-4096]


def test_unresolved_older_anchors_cannot_starve_a_later_pending_charge(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path, task_type="synthetic-storage")
    store = module.task_store
    task = store.get_task(task_id)
    with store.engine.begin() as conn:
        for number in range(1001):
            older_id = f"{number:032x}"
            conn.execute(store.tasks_table.insert().values(
                md5sum=older_id, filename="input.fasta", file_path="input.fasta", uploaded_at=1,
                status="finished", is_binary=0, task_type="synthetic-storage",
                submitted_by_user_id=task["submitted_by_user_id"], storage_key=task["storage_key"],
            ))
            # Legitimate crash after anchoring, before any manifest was installed.
            # Equal timestamps exercise the task-ID tie breaker in pagination.
            conn.execute(store.result_publications_table.insert().values(
                task_id=older_id, manifest_sha256="0" * 64, manifest_size=2,
                revision=1, published_at=1, charge_bytes=7, charge_state="pending",
            ))
    with monkeypatch.context() as failure:
        _fail_charge(module, failure)
        _publish(module, task_id, result_dir)
    assert module.task_runtime._reconcile_pending_storage_charges() == {"charged": 0, "released": 0, "skipped": 500}
    assert module.task_runtime._reconcile_pending_storage_charges() == {"charged": 0, "released": 0, "skipped": 500}
    assert module.task_runtime._reconcile_pending_storage_charges() == {"charged": 1, "released": 0, "skipped": 1}
    assert store.get_result_publication(task_id)["charge_state"] == "charged"
    lifecycle = store.get_data_lifecycle(task_id)
    assert lifecycle["logical_bytes"] == lifecycle["accounted_bytes"] == 4096
    facts = store.list_ledger(task["submitted_by_user_id"])
    assert [fact["quantity"] for fact in facts] == [-4096]
    # End-of-scan wraps so unresolved records stay retryable. Restart discards
    # only the cursor and cannot replay an already settled charge.
    assert module.task_runtime._reconcile_pending_storage_charges()["skipped"] == 500
    module.task_runtime._pending_storage_charge_cursor = None
    assert module.task_runtime._reconcile_pending_storage_charges()["skipped"] == 500
    assert store.list_ledger(task["submitted_by_user_id"]) == facts


def test_a_charge_that_fails_leaves_a_pending_publication_and_is_repaired(monkeypatch, tmp_path) -> None:
    """The split the review found: manifest installed, charge missing, no marker.

    The publication anchor carries the amount owed and the fact that it is unpaid,
    so the result is discoverable by reconciliation instead of being published
    forever with no lifecycle row and no storage charge.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    _fail_charge(module, monkeypatch)

    _publish(module, task_id, result_dir)

    # The result really is published...
    task = module.task_store.get_task(task_id)
    assert module.app.config["storage_resolver"].publication_state(task) == "available"
    # ...and nothing was charged, while the anchor still records what is owed.
    assert module.task_store.get_data_lifecycle(task_id) is None
    assert module.task_store.logical_owned_bytes(task.get("submitted_by_user_id")) == 0
    pending = module.task_store.list_pending_storage_publications()
    assert [row["task_id"] for row in pending] == [task_id]
    assert pending[0]["charge_bytes"] > 0

    monkeypatch.undo()

    # Repair charges exactly the amount the anchor recorded, from the anchor's own
    # metadata -- never from a directory walk.
    outcome = module.task_runtime._reconcile_pending_storage_charges()
    assert outcome == {"charged": 1, "released": 0, "skipped": 0}
    user_id = task.get("submitted_by_user_id")
    assert module.task_store.logical_owned_bytes(user_id) == pending[0]["charge_bytes"]
    assert module.task_store.list_pending_storage_publications() == []


def test_a_failed_storage_fact_rolls_back_ownership_and_is_repairable(monkeypatch, tmp_path) -> None:
    """Neither half of the charge survives a failed durable transaction."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    store = module.task_store
    append = store._append_storage_fact

    def fail_after_fact(*args, **kwargs):
        append(*args, **kwargs)
        raise OSError("storage transaction interrupted")

    with monkeypatch.context() as failure:
        failure.setattr(store, "_append_storage_fact", fail_after_fact)
        _publish(module, task_id, result_dir)

    task = store.get_task(task_id)
    user_id = task["submitted_by_user_id"]
    assert module.app.config["storage_resolver"].publication_state(task) == "available"
    assert store.get_data_lifecycle(task_id) is None
    assert store.list_ledger(user_id) == []
    pending = store.list_pending_storage_publications()
    assert [row["task_id"] for row in pending] == [task_id]

    assert module.task_runtime._reconcile_pending_storage_charges() == {"charged": 1, "released": 0, "skipped": 0}
    assert store.logical_owned_bytes(user_id) == pending[0]["charge_bytes"]
    charges = [entry for entry in store.list_ledger(user_id) if entry["reason_code"] == "storage_charged"]
    assert [entry["quantity"] for entry in charges] == [-pending[0]["charge_bytes"]]
    assert module.task_runtime._reconcile_pending_storage_charges() == {"charged": 0, "released": 0, "skipped": 0}
    assert store.list_ledger(user_id) == charges


def test_the_repair_is_idempotent_across_restarts(monkeypatch, tmp_path) -> None:
    """A second pass over the same publication adds nothing."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    _fail_charge(module, monkeypatch)
    _publish(module, task_id, result_dir)
    monkeypatch.undo()

    first = module.task_runtime._reconcile_pending_storage_charges()
    charged = module.task_store.logical_owned_bytes(module.task_store.get_task(task_id)["submitted_by_user_id"])
    second = module.task_runtime._reconcile_pending_storage_charges()

    assert first == {"charged": 1, "released": 0, "skipped": 0}
    assert second == {"charged": 0, "released": 0, "skipped": 0}
    assert module.task_store.logical_owned_bytes(
        module.task_store.get_task(task_id)["submitted_by_user_id"]
    ) == charged


def test_a_purged_result_is_never_charged_by_the_repair(monkeypatch, tmp_path) -> None:
    """Deletion before repair must not manufacture a charge for bytes that are gone.

    The purge is authoritative over these bytes: it removed them and released the
    charge it made.  A repair pass must not resurrect a zero-byte or non-zero
    lifecycle row for data that no longer exists.
    """
    from revocompute import resource_lifecycle

    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    _fail_charge(module, monkeypatch)
    _publish(module, task_id, result_dir)
    monkeypatch.undo()

    task = module.task_store.get_task(task_id)
    resource_lifecycle.request_data_deletion(module.task_store, task, actor_user_id=None)
    resource_lifecycle.purge_task_data(
        module.task_store, task, remove_artifacts=lambda _task: None
    )

    assert module.task_store.get_data_lifecycle(task_id)["state"] == "PURGED"
    assert module.task_store.logical_owned_bytes(task["submitted_by_user_id"]) == 0

    # Repair must not charge, and must close the marker rather than leave it
    # pending forever.
    outcome = module.task_runtime._reconcile_pending_storage_charges()
    assert outcome["charged"] == 0
    assert module.task_store.logical_owned_bytes(task["submitted_by_user_id"]) == 0
    assert module.task_store.list_pending_storage_publications() == []


def test_a_legacy_publication_charges_the_anchored_manifest_bytes_not_zero(monkeypatch, tmp_path) -> None:
    """A publication that predates the charge column must not charge zero.

    The upgrade path backfills ``charge_bytes = NULL`` and ``charge_state =
    pending``.  Reading that NULL as zero would permanently mark an anchored
    publication charged as 0 bytes, so the amount is derived from the verified
    anchored manifest's own declared artifact sizes instead -- once, and never
    from a directory walk.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    with monkeypatch.context() as failure:
        _fail_charge(module, failure)
        _publish(module, task_id, result_dir)
    task = module.task_store.get_task(task_id)
    user_id = task["submitted_by_user_id"]
    # A declared artifact with non-zero bytes is what the anchor must resolve.
    manifest = module.app.config["storage_resolver"].load_manifest(task)
    declared = sum(int(item["size"]) for item in manifest["artifacts"])
    assert declared > 0
    _upgrade_pre_charge_anchor(module.task_store)
    assert module.task_store.get_result_publication(task_id)["charge_bytes"] is None
    assert module.task_store.get_data_lifecycle(task_id) is None
    assert module.task_store.list_ledger(user_id) == []

    outcome = module.task_runtime._reconcile_pending_storage_charges()

    assert outcome == {"charged": 1, "released": 0, "skipped": 0}
    assert module.task_store.logical_owned_bytes(user_id) == declared
    record = module.task_store.get_result_publication(task_id)
    assert record["charge_state"] == "charged"
    assert int(record["charge_bytes"]) == declared
    charges = [entry for entry in module.task_store.list_ledger(user_id) if entry["reason_code"] == "storage_charged"]
    assert [entry["quantity"] for entry in charges] == [-declared]
    # A repeated pass over the same (now charged) publication adds nothing.
    assert module.task_runtime._reconcile_pending_storage_charges() == {
        "charged": 0,
        "released": 0,
        "skipped": 0,
    }
    assert module.task_store.logical_owned_bytes(user_id) == declared


@pytest.mark.parametrize("damage", ["mismatch", "missing"])
def test_a_legacy_publication_whose_anchor_does_not_match_stays_unresolved(monkeypatch, tmp_path, damage) -> None:
    """A pre-column publication that is no longer available is not charged at zero.

    The amount is unknown and the publication is quarantined: the marker must
    stay pending (reviewable) rather than being closed as a zero charge no later
    pass would re-examine.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    with monkeypatch.context() as failure:
        _fail_charge(module, failure)
        _publish(module, task_id, result_dir)
    task = module.task_store.get_task(task_id)
    user_id = task["submitted_by_user_id"]
    # Replace the manifest with a valid regular file that no longer matches the
    # anchor, then present the row as the release upgrade would.
    manifest_path = result_dir / "manifest.json"
    if damage == "mismatch":
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["total_size"] += 1
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        manifest_path.unlink()
    _upgrade_pre_charge_anchor(module.task_store)

    assert module.app.config["storage_resolver"].publication_state(task) != "available"
    outcome = module.task_runtime._reconcile_pending_storage_charges()

    assert outcome == {"charged": 0, "released": 0, "skipped": 1}
    assert module.task_store.get_data_lifecycle(task_id) is None
    assert module.task_store.logical_owned_bytes(user_id) == 0
    # Still pending: the amount is unknown, not zero, and stays reviewable.
    assert [row["task_id"] for row in module.task_store.list_pending_storage_publications()] == [task_id]


def test_an_ownerless_live_publication_is_closed_without_a_subject_zero_charge(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    module.task_store.update_task(task_id, submitted_by_user_id=0)

    _publish(module, task_id, result_dir)

    assert module.task_store.get_result_publication(task_id)["charge_state"] == "unowned"
    assert module.task_store.get_data_lifecycle(task_id) is None
    assert module.task_store.list_ledger(0) == []
    assert module.task_runtime._reconcile_pending_storage_charges() == {"charged": 0, "released": 0, "skipped": 0}


def test_an_ownerless_publication_is_closed_ownerlessly_not_charged_to_subject_zero(
    monkeypatch, tmp_path
) -> None:
    """A publication with no owning user must not become a subject-0 charge.

    The live charge deliberately returns for ``user_id <= 0``, so a pending
    publication for such a Task would otherwise be inherited by the repair pass
    and billed to subject 0.  Closing the marker ownerless is the transition's
    own ownerless branch.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    (result_dir / "result.txt").write_text("x" * 4096, encoding="utf-8")
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    # Present the Task as ownerless, exactly as a publication with user_id <= 0,
    # and with its live charge never recorded.
    with module.task_store.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE tasks SET submitted_by_user_id = 0 WHERE md5sum = ?", (task_id,))
        connection.exec_driver_sql(
            "UPDATE result_publications SET charge_bytes = NULL, charge_state = 'pending'"
        )
        connection.exec_driver_sql("DELETE FROM data_lifecycle")

    outcome = module.task_runtime._reconcile_pending_storage_charges()

    assert outcome["charged"] == 0
    record = module.task_store.get_result_publication(task_id)
    assert record["charge_state"] == "unowned"
    assert module.task_store.get_data_lifecycle(task_id) is None
    assert module.task_store.logical_owned_bytes(0) == 0


def test_a_purge_that_lands_mid_repair_leaves_the_publication_released(monkeypatch, tmp_path) -> None:
    """A stale ownership read must not re-open a lifecycle the purge closed.

    The repair reads the anchored bytes and then charges.  A purge that completes
    between that read and the charge is authoritative: the charge transition
    answers ``released``, no lifecycle row is re-opened, no new storage fact is
    appended, and the publication stays released.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    _fail_charge(module, monkeypatch)
    _publish(module, task_id, result_dir)
    monkeypatch.undo()

    task = module.task_store.get_task(task_id)
    user_id = task["submitted_by_user_id"]
    # Establish ownership, then let a purge complete exactly at the repair's
    # charge transition -- after its ownership read, before its charge.
    module.task_store.ensure_data_lifecycle(task_id, user_id=user_id, logical_bytes=4096)
    real_charge = module.task_store.charge_result_publication
    purged: list[bool] = []

    def _purge_then_charge(task_id_arg, **fields):
        if not purged:
            resource_lifecycle.request_data_deletion(module.task_store, task, actor_user_id=None)
            resource_lifecycle.purge_task_data(
                module.task_store, task, remove_artifacts=module._delete_task_artifacts
            )
            purged.append(True)
        return real_charge(task_id_arg, **fields)

    monkeypatch.setattr(module.task_store, "charge_result_publication", _purge_then_charge)
    charges_before = [
        entry
        for entry in module.task_store.list_ledger(user_id)
        if entry["reason_code"] == "storage_charged"
    ]

    outcome = module.task_runtime._reconcile_pending_storage_charges()

    assert outcome["charged"] == 0
    assert outcome["released"] == 1
    # No lifecycle re-open: the purge stands.
    assert module.task_store.get_data_lifecycle(task_id)["state"] == "PURGED"
    assert not result_dir.exists()
    assert module.task_store.logical_owned_bytes(user_id) == 0
    # No new charge was appended by the repair; the only new fact is the release
    # the purge itself made.
    charges_after = [
        entry
        for entry in module.task_store.list_ledger(user_id)
        if entry["reason_code"] == "storage_charged"
    ]
    assert charges_after == charges_before
    # The publication is released and never re-charged by a repeated pass.
    assert module.task_store.get_result_publication(task_id)["charge_state"] == "released"
    assert module.task_store.list_pending_storage_publications() == []
    assert module.task_runtime._reconcile_pending_storage_charges() == {
        "charged": 0,
        "released": 0,
        "skipped": 0,
    }
    assert module.task_store.get_data_lifecycle(task_id)["state"] == "PURGED"


def test_a_quarantined_or_unanchored_result_is_never_auto_charged(monkeypatch, tmp_path) -> None:
    """Only the verified anchored identity is charged.

    A publication whose bytes changed after it was anchored is not the one Core
    published, so a repair driven from it would bill a subject for bytes an
    untrusted tree merely claims to hold.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    _fail_charge(module, monkeypatch)
    _publish(module, task_id, result_dir)
    monkeypatch.undo()

    # Replace the manifest with a valid regular file that no longer matches the
    # anchor.
    manifest = result_dir / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["total_size"] = payload["total_size"] + 1
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    task = module.task_store.get_task(task_id)
    assert module.app.config["storage_resolver"].publication_state(task) == "anchor_mismatch"

    outcome = module.task_runtime._reconcile_pending_storage_charges()

    assert outcome["charged"] == 0
    assert module.task_store.get_data_lifecycle(task_id) is None
    assert module.task_store.logical_owned_bytes(task["submitted_by_user_id"]) == 0


def test_the_repair_charges_the_anchored_amount_not_the_tree_size(monkeypatch, tmp_path) -> None:
    """The amount is the publication's own declaration, never a directory walk.

    A file planted beside the published artifacts is not a user's bytes, and the
    repair must not bill for it.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    _fail_charge(module, monkeypatch)
    _publish(module, task_id, result_dir)
    monkeypatch.undo()

    pending = module.task_store.list_pending_storage_publications()[0]
    anchored = int(pending["charge_bytes"])

    # Plant a large file that is not part of the anchored manifest.
    planted = result_dir / "planted.bin"
    planted.write_bytes(b"z" * (1024 * 1024))
    assert planted.stat().st_size > anchored

    module.task_runtime._reconcile_pending_storage_charges()

    user_id = module.task_store.get_task(task_id)["submitted_by_user_id"]
    assert module.task_store.logical_owned_bytes(user_id) == anchored


def test_the_repair_skips_a_task_that_no_longer_exists(monkeypatch, tmp_path) -> None:
    """Nothing to charge when the owning Task row is gone."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    _fail_charge(module, monkeypatch)
    _publish(module, task_id, result_dir)
    monkeypatch.undo()

    module.task_store.delete_task(task_id)

    assert module.task_runtime._reconcile_pending_storage_charges()["charged"] == 0


# ---------------------------------------------------------------------------
# The anchor is part of publication success.
# ---------------------------------------------------------------------------


def test_a_failed_anchor_publishes_nothing_and_emits_nothing(monkeypatch, tmp_path) -> None:
    """Anchor persistence failure after serialization leaves no publication.

    The manifest bytes were serialized and the anchor could not be recorded, so
    the canonical manifest must not become visible and no publication may be
    claimed: the durable authority precedes the artifact, and a reader can never
    find a result that asserts a publication it then refuses.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    (result_dir / "result.txt").write_text("score\n", encoding="utf-8")
    events = _capture_events(module, monkeypatch)
    _fail_anchor(module, monkeypatch)

    with pytest.raises(ResultPublicationError):
        module.task_runtime._finalize_results_manifest(
            module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
        )

    assert [event for event, _fields in events if event == "manifest.published"] == []
    assert not (result_dir / "manifest.json").exists()
    assert not (result_dir / ".manifest.json.tmp").exists()
    task = module.task_store.get_task(task_id)
    assert module.app.config["storage_resolver"].publication_state(task) == "not_finalized"
    assert module.task_store.get_result_publication(task_id) is None


def test_the_anchor_is_established_before_the_manifest_becomes_visible(monkeypatch, tmp_path) -> None:
    """Ordering, asserted at the moment the anchor is recorded."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    (result_dir / "result.txt").write_text("score\n", encoding="utf-8")
    observed: list[bool] = []
    real_record = module.task_store.record_result_publication

    def _record(*args, **kwargs):
        # At the instant the anchor is written, no reader may be able to see the
        # manifest yet: otherwise a crash here would leave a visible, anchored-
        # unreachable publication.
        observed.append((result_dir / "manifest.json").exists())
        return real_record(*args, **kwargs)

    monkeypatch.setattr(module.task_store, "record_result_publication", _record)

    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )

    assert observed == [False]
    assert (result_dir / "manifest.json").is_file()


def test_a_published_event_never_exists_without_a_matching_anchor(monkeypatch, tmp_path) -> None:
    """Every ``manifest.published`` is emitted with its anchor already durable."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    (result_dir / "result.txt").write_text("score\n", encoding="utf-8")
    anchored_at_emit: list[bool] = []
    real_emit = module.task_runtime.emit_event

    def _emit(event, **fields):
        if event == "manifest.published":
            anchored_at_emit.append(module.task_store.get_result_publication(task_id) is not None)
        return real_emit(event, **fields)

    monkeypatch.setattr(module.task_runtime, "emit_event", _emit)

    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )

    assert anchored_at_emit == [True]


def test_an_anchor_failure_settles_the_task_as_failed_not_finished(monkeypatch, tmp_path) -> None:
    """The bounded, non-lying state after the split point, through a real caller.

    ``_finalize_after_poll`` is the recovered-job publication path.  A run whose
    publication could not be established must end ``failed`` -- never
    ``finished`` -- so nothing downstream reads it as a published result.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path, status="running")
    (result_dir / "result.txt").write_text("score\n", encoding="utf-8")
    _fail_anchor(module, monkeypatch)
    statuses: list[str] = []
    real_update = module.task_store.update_task

    def _update(md5sum, **fields):
        if "status" in fields:
            statuses.append(fields["status"])
        return real_update(md5sum, **fields)

    monkeypatch.setattr(module.task_store, "update_task", _update)

    class _TaskType:
        stage_markers = {"running": "Running", "done": "Done"}

    task = module.task_store.get_task(task_id)
    module.task_runtime._finalize_after_poll(task_id, task, _TaskType(), module.task_runtime.JobState.COMPLETED)

    assert statuses and statuses[-1] == "failed"
    assert "finished" not in statuses
    assert not (result_dir / "manifest.json").exists()


def test_a_settled_task_republication_after_an_anchor_failure_succeeds(monkeypatch, tmp_path) -> None:
    """The split state is recoverable by the authority that publishes."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path, status="running")
    (result_dir / "result.txt").write_text("score\n", encoding="utf-8")
    _fail_anchor(module, monkeypatch)

    class _TaskType:
        stage_markers = {"running": "Running", "done": "Done"}

    module.task_runtime._finalize_after_poll(
        task_id,
        module.task_store.get_task(task_id),
        _TaskType(),
        module.task_runtime.JobState.COMPLETED,
    )
    assert not (result_dir / "manifest.json").exists()

    # A retry publishes through the same single transition and the task is finished.
    monkeypatch.undo()
    module.task_runtime._finalize_after_poll(
        task_id,
        module.task_store.get_task(task_id),
        _TaskType(),
        module.task_runtime.JobState.COMPLETED,
    )

    task = module.task_store.get_task(task_id)
    storage = module.app.config["storage_resolver"]
    assert task["status"] == "finished"
    assert storage.publication_state(task) == "available"
    assert storage.load_manifest(task) is not None


# ---------------------------------------------------------------------------
# The rollout rule for results that predate the anchor.
# ---------------------------------------------------------------------------


def _unanchored_task(module, tmp_path, *, status: str = "finished") -> tuple[str, Path]:
    """A finished task with a manifest on disk and no anchor row.

    This is the installed corpus at upgrade time: results finalized by the
    authority that recorded no publication identity.
    """
    task_id, result_dir = _task(module, tmp_path, status=status)
    (result_dir / "result.txt").write_text("score\n1.0\n", encoding="utf-8")
    manifest = {
        "schema_version": 3,
        "task_id": task_id,
        "task_type": "gremlin",
        "output_check": {"state": "not_configured", "checks": [], "problems": []},
        "artifacts": [],
        "result": {"files": {}},
    }
    (result_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert module.task_store.get_result_publication(task_id) is None
    return task_id, result_dir


def test_a_pre_anchor_result_is_quarantined_with_a_reason_not_a_bare_404(monkeypatch, tmp_path) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    # The caller identity exists before the task, as it does in production: the
    # test helper only pre-verifies an account it just created, so a task created
    # first would leave its owner unverified.
    headers = _test_client_auth(module)
    task_id, _result_dir = _unanchored_task(module, tmp_path)
    client = module.app.test_client()

    status = client.get(f"/compute/api/running/{task_id}", headers=headers)
    assert status.status_code == 200
    body = status.get_json()
    assert body["terminal"] is True
    assert body["result_available"] is False
    assert body["result_publication"] == "unanchored"

    results = client.get(f"/compute/api/results/{task_id}", headers=headers)
    assert results.status_code == 404
    payload = results.get_json()
    assert payload["result_publication"] == "unanchored"
    # A reason, not a bare not-found: the message names the state.
    assert "predate" in payload["message"]

    summary = next(
        item
        for item in client.get("/compute/api/tasks", headers=headers).get_json()["tasks"]
        if item["task_id"] == task_id
    )
    assert summary["result"]["available"] is False
    assert summary["result"]["publication"] == "unanchored"


def test_the_reconciliation_reports_the_pre_anchor_corpus_and_writes_nothing(monkeypatch, tmp_path) -> None:
    """The rollout rule: classify, report, and never backfill an anchor."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, _result_dir = _unanchored_task(module, tmp_path)
    events = _capture_events(module, monkeypatch)

    first = module.task_runtime._reconcile_result_publications()
    second = module.task_runtime._reconcile_result_publications()

    assert first.get("unanchored") == 1
    assert second.get("unanchored") == 1
    # Reconciliation is a report: the quarantined result is still quarantined and
    # still unanchored, because the only bytes available are the ones the runner's
    # identity wrote.
    assert module.task_store.get_result_publication(task_id) is None
    assert (
        module.app.config["storage_resolver"].publication_state(module.task_store.get_task(task_id)) == "unanchored"
    )
    quarantined = [fields for event, fields in events if event == "manifest.publication_quarantined"]
    assert len(quarantined) == 2
    assert all(fields["reason_code"] == "unanchored" for fields in quarantined)
    assert all(fields["task_id"] == task_id for fields in quarantined)


def test_a_republication_by_the_authority_settles_the_quarantine(monkeypatch, tmp_path) -> None:
    """The trusted re-publication path: a fresh run publishes through the
    ordinary transition, and the reconciliation then reports it available."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, _result_dir = _unanchored_task(module, tmp_path)
    assert module.task_runtime._reconcile_result_publications().get("unanchored") == 1

    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )

    storage = module.app.config["storage_resolver"]
    assert storage.publication_state(module.task_store.get_task(task_id)) == "available"
    assert module.task_runtime._reconcile_result_publications() == {"available": 1}


def test_a_replaced_manifest_is_reported_as_a_mismatch_not_as_unanchored(monkeypatch, tmp_path) -> None:
    """A tampered publication and a pre-anchor result are different facts."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    headers = _test_client_auth(module)
    task_id, result_dir = _task(module, tmp_path)
    (result_dir / "result.txt").write_text("score\n", encoding="utf-8")
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    (result_dir / "manifest.json").write_text(json.dumps({"schema_version": 3, "artifacts": []}), encoding="utf-8")

    body = module.app.test_client().get(f"/compute/api/results/{task_id}", headers=headers).get_json()

    assert body["result_publication"] == "anchor_mismatch"
    assert module.task_runtime._reconcile_result_publications() == {"anchor_mismatch": 1}


def test_a_task_that_never_finalized_is_not_reported_as_quarantined(monkeypatch, tmp_path) -> None:
    """No published payload means nothing to quarantine, and no false alarm."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    assert not (result_dir / "manifest.json").exists()

    task = module.task_store.get_task(task_id)
    assert module.app.config["storage_resolver"].publication_state(task) == "not_finalized"
    assert module.task_runtime._reconcile_result_publications() == {"not_finalized": 1}


def test_a_quarantined_result_cannot_be_published_into_a_new_archive(monkeypatch, tmp_path) -> None:
    """Building a new ZIP from a quarantined tree is itself a publication."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    headers = _test_client_auth(module)
    task_id, _result_dir = _unanchored_task(module, tmp_path)

    response = module.app.test_client().post(f"/compute/api/results/{task_id}/archive", headers=headers)

    assert response.status_code == 409
    body = response.get_json()
    assert body["result_publication"] == "unanchored"
    assert body["message"]
    assert not list(Path(module.app.config["RESULTS_FOLDER"]).glob("*_results.zip"))


# ---------------------------------------------------------------------------
# Serving a cached ZIP is the same publication decision as building one.
# ---------------------------------------------------------------------------


def _cached_archive(module, task_id: str, payload: bytes = b"PK archive bytes") -> Path:
    """Place a pre-existing results ZIP where the download route looks for it.

    A quarantined task's ZIP is exactly this: bytes written before the result was
    refused, still sitting in the archive namespace.  Nothing about the ZIP
    proves it is a publication, which is why the download route may not decide
    from its presence.
    """
    archive = Path(module.app.config["storage_resolver"].get_archive_path(module.task_store.get_task(task_id)))
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(payload)
    return archive


def test_a_quarantined_cached_archive_is_refused_with_a_reason_not_served(monkeypatch, tmp_path) -> None:
    """An old ZIP behind a quarantined result is not downloadable."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    headers = _test_client_auth(module)
    task_id, _result_dir = _unanchored_task(module, tmp_path)
    payload = b"PK\x03\x04 pre-anchor bytes\n"
    _cached_archive(module, task_id, payload)
    client = module.app.test_client()

    response = client.get(f"/compute/api/download/{task_id}", headers=headers)

    assert response.status_code == 409
    body = response.get_json()
    assert body["result_publication"] == "unanchored"
    # The reason names the state, and the bytes are nowhere in the response.
    assert "predate" in body["message"]
    assert payload not in response.data

    # The archive POST refuses the same result with the same state.
    assert client.post(f"/compute/api/results/{task_id}/archive", headers=headers).status_code == 409


def test_a_quarantined_result_advertises_no_download_or_archive_affordance(monkeypatch, tmp_path) -> None:
    """No surface offers a link the download route would refuse."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    headers = _test_client_auth(module)
    task_id, _result_dir = _unanchored_task(module, tmp_path)
    _cached_archive(module, task_id)
    client = module.app.test_client()

    summary = next(
        item
        for item in client.get("/compute/api/tasks", headers=headers).get_json()["tasks"]
        if item["task_id"] == task_id
    )
    assert summary["result"]["publication"] == "unanchored"
    assert summary["result"]["download_url"] is None
    assert summary["result"]["archive_ready"] is False
    assert summary["result"]["archive_request_allowed"] is False

    status = client.get(f"/compute/api/running/{task_id}", headers=headers).get_json()
    assert status["result_available"] is False
    assert status["result_publication"] == "unanchored"


def test_an_available_archive_is_downloaded_unchanged(monkeypatch, tmp_path) -> None:
    """The ordinary download still returns exactly the cached bytes."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    headers = _test_client_auth(module)
    task_id, result_dir = _task(module, tmp_path)
    (result_dir / "result.txt").write_text("score\n", encoding="utf-8")
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    payload = b"PK\x03\x04 published archive bytes\n"
    _cached_archive(module, task_id, payload)

    response = module.app.test_client().get(f"/compute/api/download/{task_id}", headers=headers)

    assert response.status_code == 200
    assert response.data == payload
    assert response.headers["Content-Length"] == str(len(payload))


def test_a_task_that_never_finalized_is_not_served_an_archive(monkeypatch, tmp_path) -> None:
    """A task with no published manifest refuses a download by its own state."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    headers = _test_client_auth(module)
    task_id, result_dir = _task(module, tmp_path)
    assert not (result_dir / "manifest.json").exists()
    # Even a ZIP left behind by an aborted run is not a publication.
    _cached_archive(module, task_id)

    response = module.app.test_client().get(f"/compute/api/download/{task_id}", headers=headers)

    assert response.status_code == 409
    body = response.get_json()
    assert body["result_publication"] == "not_finalized"
    assert body["message"]


def test_the_archive_request_for_an_available_result_is_unchanged(monkeypatch, tmp_path) -> None:
    """The ordinary path keeps its contract."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    headers = _test_client_auth(module)
    task_id, result_dir = _task(module, tmp_path)
    (result_dir / "result.txt").write_text("score\n", encoding="utf-8")
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    queued: list[list[str]] = []

    class _Queued:
        id = "archive-job"

    monkeypatch.setattr(
        module.task_runtime.build_results_archive, "apply_async", lambda args: queued.append(args) or _Queued()
    )

    response = module.app.test_client().post(f"/compute/api/results/{task_id}/archive", headers=headers)

    assert response.status_code == 202
    assert queued == [[task_id]]


def test_the_operator_view_reports_the_same_states_as_the_api(monkeypatch, tmp_path) -> None:
    """One classification for the CLI and the HTTP surfaces."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    quarantined_id, _dir = _unanchored_task(module, tmp_path)
    available_id, available_dir = _task(module, tmp_path)
    (available_dir / "result.txt").write_text("score\n", encoding="utf-8")
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(available_id), execution_state="completed", finished_at=1_700_000_000
    )

    from revocompute.publications import collect_publications

    entries = {
        entry.task_id: entry
        for entry in collect_publications(
            module.task_store, module.app.config["storage_resolver"]
        )
    }

    assert entries[quarantined_id].publication == "unanchored"
    assert entries[quarantined_id].quarantined is True
    assert entries[available_id].publication == "available"
    assert entries[available_id].quarantined is False


def test_publication_states_never_leave_a_stale_temp_manifest(monkeypatch, tmp_path) -> None:
    """A refusal leaves the result tree as it found it, minus the manifest."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, result_dir = _task(module, tmp_path)
    (result_dir / "result.txt").write_text("score\n", encoding="utf-8")
    _fail_anchor(module, monkeypatch, error=RuntimeError("anchor unavailable"))

    with pytest.raises(ResultPublicationError):
        module.task_runtime._finalize_results_manifest(
            module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
        )

    leftover = [name for name in os.listdir(result_dir) if name.startswith(".manifest")]
    assert leftover == []
