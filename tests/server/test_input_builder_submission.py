# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Submission and preflight reject a builder envelope that no longer matches its bytes."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

from conftest import _load_pssm_module, _test_client_auth

CONTENT = (
    b'{"name":"synthetic","modelSeeds":[1],"dialect":"alphafold3","version":1,'
    b'"sequences":[{"protein":{"id":"A","sequence":"ACDE"}}]}\n'
)
DIGEST = hashlib.sha256(CONTENT).hexdigest()


def _workspace(**overrides):
    envelope = {
        "version": 1,
        "builder": "bionuta",
        "builder_version": 2,
        "state_schema_version": 1,
        "target": "alphafold3",
        "revision": 2,
        "state": {"document": {"job": {"entities": []}}},
        "dependencies": [],
        "outputs": [
            {"logical": "input", "role": "specification", "name": "af3.json", "size": len(CONTENT), "sha256": DIGEST}
        ],
    }
    envelope.update(overrides)
    return {"version": 2, "capabilities": {"bionuta_builder": envelope}}


def _module(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "builder_runner"},
    )
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *_a, **_k: SimpleNamespace(id="queued"))
    return module


def _submit(client, auth, workspace, *, endpoint="/compute/api/post"):
    return client.post(
        endpoint,
        headers=auth,
        data={
            "task_type": "builder_runner",
            "workspace": json.dumps(workspace),
            "files": (io.BytesIO(CONTENT), "af3.json"),
            "input_roles": "specification",
        },
        content_type="multipart/form-data",
    )


def test_submission_persists_the_verified_builder_envelope(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth = _test_client_auth(module)

    response = _submit(client, auth, _workspace())
    assert response.status_code == 302, response.get_data(as_text=True)[:400]
    task_id = response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    form = json.loads(module.task_store.get_task(task_id)["input_form"])
    assert form["workspace"]["capabilities"]["bionuta_builder"]["outputs"][0]["sha256"] == DIGEST


def test_clone_authoring_is_owner_scoped_and_returns_the_recorded_state(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth = _test_client_auth(module)
    other = _test_client_auth(module, "other")

    submitted = _submit(client, auth, _workspace())
    assert submitted.status_code == 302
    task_id = submitted.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    plan = client.post(f"/compute/api/tasks/{task_id}/clone-plan", headers=auth).get_json()
    assert plan["authoring"][0]["capability_id"] == "bionuta_builder"
    assert plan["authoring"][0]["state_available"] is True

    own = client.get(
        f"/compute/api/clone-plans/{plan['plan_id']}/authoring/bionuta_builder", headers=auth
    )
    assert own.status_code == 200
    assert own.get_json()["state"]["document"]["job"]["entities"] == []
    assert own.headers["Cache-Control"] == "private, no-store"
    assert client.get(
        f"/compute/api/clone-plans/{plan['plan_id']}/authoring/bionuta_builder", headers=other
    ).status_code == 404


def test_submission_rejects_a_stale_digest_and_commits_nothing(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth = _test_client_auth(module)
    before = list(module.task_store.list_tasks())

    response = _submit(
        client,
        auth,
        _workspace(outputs=[
            {"logical": "input", "role": "specification", "name": "af3.json", "size": len(CONTENT), "sha256": "0" * 64}
        ]),
    )
    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "builder_output_digest_mismatch"
    assert module.task_store.list_tasks() == before


def test_submission_rejects_dependency_bearing_state_explicitly(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth = _test_client_auth(module)

    response = _submit(client, auth, _workspace(dependencies=[{"id": "dep-1", "kind": "msa"}]))
    assert response.status_code == 400
    detail = response.get_json()["details"][0]
    assert detail["code"] == "builder_dependency_unsupported"


def test_identical_bytes_deduplicate_without_overwriting_authoring_state(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth = _test_client_auth(module)

    first = _submit(client, auth, _workspace())
    assert first.status_code == 302
    task_id = first.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    recorded = json.loads(module.task_store.get_task(task_id)["input_form"])["workspace"]["capabilities"]
    second_state = _workspace(revision=9, state={"document": {"job": {"entities": [{"other": True}]}}})
    second = _submit(client, auth, second_state)
    # The accepted bytes are the Task identity, so the second submission is the
    # existing Task. Its authoring state is never silently overwritten.
    assert second.status_code == 202
    assert second.headers["Location"].rstrip("/").rsplit("/", 1)[-1] == task_id
    persisted = json.loads(module.task_store.get_task(task_id)["input_form"])["workspace"]["capabilities"]
    assert persisted == recorded
    assert len(module.task_store.list_tasks()) == 1


def test_plain_upload_without_builder_state_still_submits(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth = _test_client_auth(module)

    response = _submit(client, auth, {"version": 2, "capabilities": {}})
    assert response.status_code == 302, response.get_data(as_text=True)[:400]


def test_preflight_applies_the_same_envelope_check(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    auth = _test_client_auth(module)

    accepted = _submit(client, auth, _workspace(), endpoint="/compute/api/preflight/builder_runner")
    assert accepted.status_code == 200, accepted.get_data(as_text=True)[:400]
    rejected = _submit(
        client,
        auth,
        _workspace(builder="other"),
        endpoint="/compute/api/preflight/builder_runner",
    )
    assert rejected.status_code == 400, rejected.get_data(as_text=True)
    assert "builder_binding_mismatch" in rejected.get_data(as_text=True), rejected.get_data(as_text=True)
