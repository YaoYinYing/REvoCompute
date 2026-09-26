# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""SCRATCH repro for round-5 finding F2 — delete this file once the fix lands.

A cancelled task keeps its task id: ``_derive_task_id`` hashes only the task
type, the coerced params and the input hashes, so the identical form derives
the identical id.  ``_existing_upload_response`` answers ``finished`` with 302
and ``pending/queued/running`` with 202, but a ``cancelled`` row falls through
to ``_prepare_task_record`` — a claim-free rmtree + ``upsert_task(status=
"pending")`` — followed by a second ``run_compute_task.apply_async``.

Cancellation asks the worker to stop Slurm resources *asynchronously*
(``cancel_compute_resources.delay``, and the Celery revoke does not reach an
already-executing task), so the first allocation can still be live when the
second is dispatched for the same id: two allocations, and the first one's
outcome discarded by the terminal-status guard.
"""

from __future__ import annotations

import io

from conftest import _load_pssm_module, _test_client_auth


def _submit(client, auth_header):
    return client.post(
        "/compute/api/post",
        data={
            "task_type": "gremlin",
            "files": (io.BytesIO(b">x\nACDE\n"), "in.fasta"),
            "input_roles": "sequence",
        },
        headers=auth_header,
        content_type="multipart/form-data",
    )


def test_a_cancelled_task_can_be_resubmitted_and_dispatched_twice(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gremlin"},
    )
    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    dispatches: list[str] = []

    class _Queued:
        id = "queued-resubmit"

    def _record(*args, **kwargs):
        dispatches.append(args[0] if args else kwargs.get("args"))
        return _Queued()

    monkeypatch.setattr(module.run_compute_task, "apply_async", _record)

    first = _submit(client, auth_header)
    assert first.status_code == 302, first.get_json()
    md5sum = first.headers["Location"].rsplit("/", 1)[-1]
    assert len(dispatches) == 1

    # The user cancels; the worker is asked to stop resources asynchronously.
    assert module.task_store.claim_task_cancellation(md5sum) is True
    assert module.task_store.get_task(md5sum)["status"] == "cancelled"

    second = _submit(client, auth_header)
    row = module.task_store.get_task(md5sum)
    print(
        "\nF2: identical resubmit ->",
        second.status_code,
        "| dispatches:",
        len(dispatches),
        "| row status:",
        row["status"],
    )
    assert second.status_code in (200, 302), second.get_json()
    assert len(dispatches) == 2, "the cancelled task id was dispatched a second time"
    assert row["status"] == "pending"
