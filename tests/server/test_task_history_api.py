# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Behavior contracts for authorized Task history search and cursor pagination."""

from __future__ import annotations

import hashlib
import time

import pytest
from conftest import _admin_client_auth, _load_pssm_module, _task_owner, _test_client_auth
from revocompute import task_history
from sqlalchemy import event

BASE = 1_700_000_000.0


def _task_id(label: str) -> str:
    return hashlib.md5(label.encode("utf-8"), usedforsecurity=False).hexdigest()


def _seed(module, username: str, rows: list[dict]) -> None:
    owner = _task_owner(module, username)
    records = [
        {
            "md5sum": row["task_id"],
            "filename": row.get("filename", f"{row['task_id']}.fasta"),
            "file_path": f"/tmp/{row['task_id']}.fasta",
            "uploaded_at": row.get("uploaded_at", BASE),
            "finished_at": row.get("finished_at"),
            "status": row.get("status", "finished"),
            "is_binary": 0,
            "task_type": row.get("task_type", "cpu_runner"),
            "username": username,
            "submitted_by_user_id": int(owner["submitted_by_user_id"]),
            "storage_key": owner["storage_key"],
            "artifact_provenance": "[]",
        }
        for row in rows
    ]
    with module.task_store.engine.begin() as conn:
        conn.execute(module.task_store.tasks_table.insert(), records)


def _client(module):
    return module.app.test_client()


def _get(client, headers, **params):
    return client.get("/compute/api/tasks", headers=headers, query_string=params)


def _ids(response):
    return [item["task_id"] for item in response.get_json()["tasks"]]


def _walk(client, headers, **params):
    """Follow next_cursor to the end and return every Task ID in order."""
    seen: list[str] = []
    cursor = None
    for _ in range(1000):
        query = dict(params)
        if cursor is not None:
            query["cursor"] = cursor
        response = _get(client, headers, **query)
        assert response.status_code == 200
        body = response.get_json()
        seen.extend(item["task_id"] for item in body["tasks"])
        cursor = body["next_cursor"]
        if not body["has_more"]:
            assert cursor is None
            return seen
    raise AssertionError("cursor traversal did not terminate")


@pytest.fixture
def module(monkeypatch, tmp_path):
    return _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )


@pytest.fixture
def actors(module):
    return {
        "owner": _test_client_auth(module, "tester"),
        "other": _test_client_auth(module, "other"),
        "admin": _admin_client_auth(module),
    }


def test_page_is_bounded_and_never_materializes_the_whole_table(module, actors, monkeypatch):
    rows = [
        {"task_id": _task_id(f"many-{index}"), "filename": f"run-{index}.fasta", "uploaded_at": BASE + index}
        for index in range(2500)
    ]
    _seed(module, "tester", rows)

    def _forbidden():
        raise AssertionError("the History API must not call list_tasks()")

    monkeypatch.setattr(module.task_store, "list_tasks", _forbidden)

    statements: list[str] = []

    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(module.task_store.engine, "before_cursor_execute", _capture)
    try:
        response = _get(_client(module), actors["owner"], limit="30")
    finally:
        event.remove(module.task_store.engine, "before_cursor_execute", _capture)

    assert any("LIMIT ?" in statement.upper() for statement in statements), statements
    assert response.status_code == 200
    body = response.get_json()
    assert body["returned"] == 30
    assert len(body["tasks"]) == 30
    assert body["has_more"] is True
    assert body["next_cursor"]
    # Newest upload first.
    assert _ids(response)[0] == _task_id("many-2499")


def test_default_page_size_is_bounded_and_limit_is_clamped(module, actors):
    rows = [
        {"task_id": _task_id(f"size-{index}"), "uploaded_at": BASE + index}
        for index in range(150)
    ]
    _seed(module, "tester", rows)
    client = _client(module)
    assert len(_get(client, actors["owner"]).get_json()["tasks"]) == task_history.DEFAULT_PAGE_SIZE
    assert len(_get(client, actors["owner"], limit="1000").get_json()["tasks"]) == task_history.MAX_PAGE_SIZE
    # Invalid and non-positive page sizes normalize to the default.
    for raw in ("0", "-3", "false", "abc"):
        assert len(_get(client, actors["owner"], limit=raw).get_json()["tasks"]) == task_history.DEFAULT_PAGE_SIZE


def test_visibility_is_scoped_before_pagination(module, actors):
    _seed(module, "tester", [{"task_id": _task_id("mine")}])
    _seed(module, "other", [{"task_id": _task_id("theirs")}])
    client = _client(module)

    assert _ids(_get(client, actors["owner"])) == [_task_id("mine")]
    assert _ids(_get(client, actors["other"])) == [_task_id("theirs")]
    assert set(_ids(_get(client, actors["admin"]))) == {_task_id("mine"), _task_id("theirs")}

    owner_filtered = _get(client, actors["admin"], owner="tester")
    assert _ids(owner_filtered) == [_task_id("mine")]
    assert owner_filtered.get_json()["tasks"][0]["owner"] == "tester"
    assert _get(client, actors["owner"]).get_json()["tasks"][0]["owner"] is None


def test_owner_filter_is_administrator_only(module, actors):
    _seed(module, "tester", [{"task_id": _task_id("mine")}])
    _seed(module, "other", [{"task_id": _task_id("theirs")}])
    response = _get(_client(module), actors["owner"], owner="other")
    assert response.status_code == 403
    assert "owner" in response.get_json()["error"].lower()


def test_deleted_and_cleaned_tasks_are_hidden_but_cancelled_remain(module, actors):
    _seed(
        module,
        "tester",
        [
            {"task_id": _task_id("visible")},
            {"task_id": _task_id("cancelled"), "status": "cancelled"},
            {"task_id": _task_id("deleted"), "status": "deleted:finshed"},
            {"task_id": _task_id("cleaned"), "status": "cleaned:cancel"},
        ],
    )
    assert set(_ids(_get(_client(module), actors["owner"]))) == {
        _task_id("visible"),
        _task_id("cancelled"),
    }


def test_submitted_keyset_page_survives_same_timestamp_ties(module, actors):
    rows = [{"task_id": _task_id(f"tie-{index}"), "uploaded_at": BASE} for index in range(7)]
    _seed(module, "tester", rows)
    ids = _walk(_client(module), actors["owner"], limit="2")
    assert len(ids) == len(set(ids)) == 7
    assert set(ids) == {row["task_id"] for row in rows}
    # Descending Task ID is the documented tie-breaker.
    assert ids == sorted(ids, reverse=True)


def test_finished_sort_places_null_finishes_last_and_ties_by_task_id(module, actors):
    rows = [
        {"task_id": _task_id("finish-a"), "finished_at": BASE + 10},
        {"task_id": _task_id("finish-b"), "finished_at": BASE + 10},
        {"task_id": _task_id("finish-old"), "finished_at": BASE},
        {"task_id": _task_id("never-1"), "status": "running", "finished_at": None},
        {"task_id": _task_id("never-2"), "status": "pending", "finished_at": None},
    ]
    _seed(module, "tester", rows)
    ids = _walk(_client(module), actors["owner"], sort="finished", limit="2")
    expected = sorted([rows[0]["task_id"], rows[1]["task_id"]], reverse=True) + [rows[2]["task_id"]]
    expected += sorted([rows[3]["task_id"], rows[4]["task_id"]], reverse=True)
    assert ids == expected


def test_search_is_case_insensitive_literal_substring_of_name_and_id(module, actors):
    _seed(
        module,
        "tester",
        [
            {"task_id": _task_id("alpha"), "filename": "Alpha_model.fasta"},
            {"task_id": _task_id("beta"), "filename": "beta_model.fasta"},
            {"task_id": _task_id("wild"), "filename": "100%_done.fasta"},
        ],
    )
    client = _client(module)
    assert _ids(_get(client, actors["owner"], q="ALPHA")) == [_task_id("alpha")]
    assert _ids(_get(client, actors["owner"], q=_task_id("beta"))) == [_task_id("beta")]
    # LIKE wildcards are literals, not patterns: '_' matches itself only.
    assert _ids(_get(client, actors["owner"], q="%_")) == [_task_id("wild")]
    assert _get(client, actors["owner"], q="[").status_code == 200


def test_domain_filters_and_date_bounds_are_applied_server_side(module, actors):
    _seed(
        module,
        "tester",
        [
            {"task_id": _task_id("old-finished"), "task_type": "cpu_runner", "status": "finished",
             "uploaded_at": BASE, "finished_at": BASE + 10},
            {"task_id": _task_id("running-other"), "task_type": "gpu_runner", "status": "running",
             "uploaded_at": BASE + 90_000, "finished_at": None},
            {"task_id": _task_id("failed"), "task_type": "gpu_runner", "status": "failed",
             "uploaded_at": BASE + 95_000, "finished_at": BASE + 96_000},
        ],
    )
    client = _client(module)
    assert _ids(_get(client, actors["owner"], task_type="GPU")) == [
        _task_id("failed"),
        _task_id("running-other"),
    ]
    assert set(_ids(_get(client, actors["owner"], status="attention"))) == {
        _task_id("failed"),
    }
    assert set(_ids(_get(client, actors["owner"], submitted_from="2023-11-15T00:00:00+00:00"))) == {
        _task_id("running-other"),
        _task_id("failed"),
    }
    assert _ids(_get(client, actors["owner"], finished_from="2023-11-14", finished_to="2023-11-14")) == [
        _task_id("old-finished")
    ]
    assert _ids(_get(client, actors["owner"], finished_to="2023-11-14T22:13:30+00:00")) == [
        _task_id("old-finished")
    ]


def test_invalid_dates_and_sort_are_refused_but_literal_false_is_a_filter(module, actors):
    client = _client(module)
    for name in ("submitted_from", "submitted_to", "finished_from", "finished_to"):
        assert _get(client, actors["owner"], **{name: "not-a-date"}).status_code == 400
        assert _get(client, actors["owner"], **{name: "2026-01-01T00:00:00"}).status_code == 400
    assert _get(client, actors["owner"], sort="name").status_code == 400
    # A literal "false" status is a value the server interprets, not a boolean.
    response = _get(client, actors["owner"], status="false")
    assert response.status_code == 200
    assert response.get_json()["tasks"] == []


def test_cursor_is_rejected_under_changed_filters_sorts_and_users(module, actors):
    _seed(
        module,
        "tester",
        [
            {"task_id": _task_id(f"mine-{index}"), "filename": f"mine-{index}.fasta", "uploaded_at": BASE + index}
            for index in range(5)
        ],
    )
    _seed(module, "other", [{"task_id": _task_id("theirs"), "filename": "theirs.fasta"}])
    client = _client(module)

    first = _get(client, actors["owner"], limit="2", q="mine").get_json()
    cursor = first["next_cursor"]
    assert cursor

    changed = _get(client, actors["owner"], limit="2", q="other", cursor=cursor)
    assert changed.status_code == 200
    assert changed.get_json()["cursor_reset"] is True
    assert changed.get_json()["tasks"] == []

    resorted = _get(client, actors["owner"], limit="2", sort="finished", cursor=cursor)
    assert resorted.get_json()["cursor_reset"] is True
    assert [item["task_id"] for item in resorted.get_json()["tasks"]] == [
        _task_id("mine-4"), _task_id("mine-3"),
    ]

    foreign = _get(client, actors["other"], limit="2", q="mine", cursor=cursor)
    assert foreign.get_json()["cursor_reset"] is True
    assert foreign.get_json()["tasks"] == []

    malformed = _get(client, actors["owner"], limit="2", q="mine", cursor="not-a-cursor")
    assert malformed.status_code == 200
    assert malformed.get_json()["cursor_reset"] is True
    assert malformed.get_json()["query"]["q"] == "mine"


def test_expired_cursor_restarts_at_page_one(module, actors, monkeypatch):
    _seed(module, "tester", [{"task_id": _task_id(f"exp-{index}"), "uploaded_at": BASE + index} for index in range(4)])
    client = _client(module)
    cursor = _get(client, actors["owner"], limit="2").get_json()["next_cursor"]
    monkeypatch.setattr(task_history, "CURSOR_MAX_AGE_SECONDS", -1)
    response = _get(client, actors["owner"], limit="2", cursor=cursor)
    assert response.status_code == 200
    assert response.get_json()["cursor_reset"] is True
    assert response.get_json()["returned"] == 2


def test_concurrent_insert_newer_than_the_anchor_stays_out_of_an_in_progress_walk(module, actors):
    _seed(module, "tester", [{"task_id": _task_id(f"base-{index}"), "uploaded_at": BASE - index} for index in range(6)])
    client = _client(module)
    first = _get(client, actors["owner"], limit="3").get_json()
    _seed(module, "tester", [{"task_id": _task_id("late-arrival"), "uploaded_at": time.time() + 60}])

    cursor = first["next_cursor"]
    walked = [item["task_id"] for item in first["tasks"]]
    while cursor:
        page = _get(client, actors["owner"], limit="3", cursor=cursor).get_json()
        walked.extend(item["task_id"] for item in page["tasks"])
        cursor = page["next_cursor"]

    assert _task_id("late-arrival") not in walked
    assert len(walked) == 6
    frb = _get(client, actors["owner"], limit="3").get_json()
    assert frb["tasks"][0]["task_id"] == _task_id("late-arrival")


def test_response_reports_returned_count_and_effective_query(module, actors):
    _seed(
        module,
        "tester",
        [
            {"task_id": _task_id(f"echo-{index}"), "filename": f"echo-{index}.fasta", "uploaded_at": BASE + index}
            for index in range(3)
        ],
    )
    body = _get(_client(module), actors["owner"], limit="2", q="echo", sort="submitted").get_json()
    assert body["returned"] == 2
    assert body["has_more"] is True
    assert body["query"] == {
        "q": "echo",
        "task_type": None,
        "status": None,
        "owner": None,
        "submitted_from": None,
        "submitted_to": None,
        "finished_from": None,
        "finished_to": None,
        "sort": "submitted",
        "limit": 2,
    }
    assert "total" not in body
