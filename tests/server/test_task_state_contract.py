# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Task lifecycle is one explicit, enforced machine.

The vocabulary and its groups are a contract every consumer reads; the store's
guarded writes make an illegal step lose cleanly instead of corrupting the row.
"""

from __future__ import annotations

import time

import pytest

from revocompute import task_state
from revocompute.db import TaskDatabase


def _insert(database: TaskDatabase, task_id: str, *, status: str, **fields) -> None:
    database.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=time.time(),
        status=status,
        is_binary=0,
        task_type="cpu_runner",
        storage_key="owner-key",
        submitted_by_user_id=1,
        **fields,
    )


def test_the_groups_describe_one_partition_of_the_vocabulary():
    assert set(task_state.STATUSES) == task_state.ACTIVE | task_state.SETTLED
    assert not task_state.ACTIVE & task_state.SETTLED
    # A cleanup claim is settled but not finished: its purge is still running.
    assert task_state.SETTLED - task_state.POLLING_COMPLETE == task_state.DISPOSAL_CLAIMS
    assert task_state.LOCKED <= task_state.SETTLED
    assert task_state.DISPOSED == task_state.USER_DELETED | task_state.RETENTION_CLEANED
    assert task_state.HISTORY_HIDDEN == task_state.DISPOSED
    assert task_state.PUBLISHED_RESULTS <= task_state.OUTCOMES


def test_every_listed_target_names_its_source_as_a_predecessor():
    for source, targets in task_state.TRANSITIONS.items():
        assert source in task_state.STATUSES
        for target in targets:
            assert target in task_state.STATUSES
            assert source in task_state.predecessors(target)
            assert source in task_state.accepted_from(target)
    # A same-status write is a field update, except on a locked row, which a
    # cancel, deletion, or retire owns.
    for status in task_state.STATUSES:
        assert (status in task_state.accepted_from(status)) == (status not in task_state.LOCKED)


def test_a_locked_row_refuses_even_a_same_status_write(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    try:
        task_id = "c" * 32
        _insert(database, task_id, status=task_state.CANCELLED, finished_at=1_000.0)
        assert database.update_task(task_id, status=task_state.CANCELLED, error="late") is False
        assert database.update_task(task_id, error="late") is False
        assert database.get_task(task_id)["error"] is None
    finally:
        database.engine.dispose()


def test_a_committed_outcome_cannot_be_rewritten(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    try:
        for index, (settled, late) in enumerate((
            (task_state.FINISHED, task_state.FAILED),
            (task_state.FINISHED, task_state.CANCELLED),
            (task_state.CANCELLED, task_state.FINISHED),
        )):
            task_id = f"{index:032x}"
            _insert(database, task_id, status=settled)
            assert database.update_task(task_id, status=late) is False
            assert database.get_task(task_id)["status"] == settled
    finally:
        database.engine.dispose()


def test_recovery_returns_a_live_task_to_pending_and_a_late_start_resumes_it(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    try:
        task_id = "a" * 32
        _insert(database, task_id, status=task_state.QUEUED)
        assert database.claim_task_recovery(task_id, expected_status=task_state.QUEUED)
        assert database.get_task(task_id)["status"] == task_state.PENDING
        # The original worker may observe its allocation after recovery returned
        # the row to pending; only the StageRun record decides ownership.
        assert database.update_task(task_id, status=task_state.RUNNING)
        assert database.get_task(task_id)["status"] == task_state.RUNNING
    finally:
        database.engine.dispose()


def test_a_cleanup_claim_must_match_the_outcome_lane(tmp_path):
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    try:
        finished = "b" * 32
        _insert(database, finished, status=task_state.FINISHED, finished_at=1_000.0)
        assert database.claim_task_cleanup(
            finished,
            expected_status=task_state.FINISHED,
            expected_finished_at=1_000.0,
            claim_status=task_state.DELETING_FINISHED,
        )
        with pytest.raises(ValueError):
            database.claim_task_cleanup(
                finished,
                expected_status=task_state.DELETING_FINISHED,
                expected_finished_at=None,
                claim_status=task_state.DELETING_CANCELLED,
            )
        with pytest.raises(ValueError):
            database.complete_task_cleanup(
                finished, claim_status=task_state.DELETING_FINISHED, cleaned_status=task_state.CLEANED_CANCELLED
            )
        assert database.complete_task_cleanup(
            finished, claim_status=task_state.DELETING_FINISHED, cleaned_status=task_state.CLEANED_FINISHED
        )
        assert database.get_task(finished)["status"] == task_state.CLEANED_FINISHED
    finally:
        database.engine.dispose()


def test_disposal_follows_the_outcome_not_who_requested_it():
    assert task_state.disposal(task_state.FINISHED) == task_state.Disposal(
        task_state.DELETING_FINISHED, task_state.CLEANED_FINISHED, task_state.DELETED_FINISHED
    )
    for status in (task_state.PENDING, task_state.QUEUED, task_state.RUNNING, task_state.FAILED, task_state.CANCELLED):
        assert task_state.disposal(status).deleted == task_state.DELETED_CANCELLED
    # Already claimed or already gone: the caller resumes or does nothing.
    for status in task_state.DISPOSAL_CLAIMS | task_state.DISPOSED:
        assert task_state.disposal(status) is None
    assert task_state.cleanup_completion(task_state.DELETING_CANCELLED) == task_state.CLEANED_CANCELLED
    assert task_state.cleanup_termination(task_state.DELETING_FINISHED) == task_state.DELETED_FINISHED
