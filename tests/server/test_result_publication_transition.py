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
from revocompute.storage import ResultPublicationError

from conftest import _load_pssm_module, _test_client_auth, _upsert_task_for_user


def _task(module, tmp_path, *, status: str = "finished") -> tuple[str, Path]:
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
        task_type="gremlin",
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
