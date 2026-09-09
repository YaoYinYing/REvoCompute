# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""End-to-end authorization, snapshot, and provenance tests for @ references."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

import pytest
from conftest import _load_pssm_module, _test_client_auth


@pytest.fixture
def module(monkeypatch, tmp_path):
    loaded = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gremlin"},
    )

    class Queued:
        id = "artifact-reference-test"

    monkeypatch.setattr(loaded.run_compute_task, "apply_async", lambda *args, **kwargs: Queued())
    return loaded


def _user(module, username):
    headers = _test_client_auth(module, username)
    return module.app.config["user_db"].get_user_by_username(username), headers


def _source_task(module, owner, *, status="finished", publish=True, symlink=False):
    task_id = uuid.uuid4().hex
    identity = {"storage_key": owner["storage_key"], "md5sum": task_id}
    root = Path(module.app.config["storage_resolver"].get_task_root(identity))
    root.mkdir(parents=True)
    artifact = root / "models" / "source.fasta"
    artifact.parent.mkdir()
    content = b">source\nACDEFG\n"
    if symlink:
        outside = root.parent / "outside.fasta"
        outside.write_bytes(content)
        artifact.symlink_to(outside)
    else:
        artifact.write_bytes(content)
    artifacts = []
    if publish:
        artifacts.append(
            {
                "path": "models/source.fasta",
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
                "media_type": "text/plain",
                "role": "artifact",
            }
        )
    (root / "manifest.json").write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
    module.task_store.upsert_task(
        task_id,
        filename="input.fasta",
        file_path=str(artifact),
        uploaded_at=time.time(),
        started_at=time.time(),
        finished_at=time.time() if status == "finished" else None,
        status=status,
        is_binary=0,
        username=owner["username"],
        submitted_by_user_id=int(owner["id"]),
        storage_key=owner["storage_key"],
        task_type="gremlin",
    )
    return module.task_store.get_task(task_id), artifact


def _submit_reference(module, headers, source, *, path="models/source.fasta", extra=None):
    data = {
        "task_type": "gremlin",
        "artifact_references": f"@{source['md5sum']}/{path}",
        **(extra or {}),
    }
    return module.app.test_client().post(
        "/compute/api/post", headers=headers, data=data, content_type="multipart/form-data"
    )


def _disable_cancel_dispatch(module, monkeypatch):
    route_globals = module.app.view_functions["cancel_task"].__wrapped__.__globals__
    monkeypatch.setattr(route_globals["cancel_compute_resources"], "delay", lambda *args, **kwargs: None)


def test_own_artifact_becomes_immutable_snapshot_with_provenance(module):
    alice, headers = _user(module, "alice")
    source, source_path = _source_task(module, alice)

    response = _submit_reference(module, headers, source)

    assert response.status_code == 302, response.get_data(as_text=True)
    task = module.task_store.get_task(response.headers["Location"].rsplit("/", 1)[-1])
    snapshot = Path(module.app.config["storage_resolver"].get_input_root(task)) / "inputs" / "source.fasta"
    assert snapshot.read_bytes() == source_path.read_bytes()
    assert "/users/" in module.app.config["storage_resolver"].get_task_root(task)
    provenance = json.loads(task["artifact_provenance"])
    assert provenance[0]["downstream_task_id"] == task["md5sum"]
    assert provenance[0]["source_task_id"] == source["md5sum"]
    assert provenance[0]["source_artifact_path"] == "models/source.fasta"
    assert provenance[0]["sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert "scope_type" not in provenance[0]
    assert "scope_id" not in provenance[0]
    source_path.unlink()
    assert snapshot.is_file()


def test_cross_user_reuse_is_denied_even_to_admin(module):
    alice, _ = _user(module, "alice")
    _, bob_headers = _user(module, "bob")
    source, _ = _source_task(module, alice)

    assert _submit_reference(module, bob_headers, source).status_code == 403

    admin_headers = _test_client_auth(module, "sysadmin")
    admin = module.app.config["user_db"].get_user_by_username("sysadmin")
    module.app.config["user_db"].update_user(admin["id"], role="admin")
    assert _submit_reference(module, admin_headers, source).status_code == 403


def test_task_mutation_uses_immutable_submitter_id_across_username_rename(module, monkeypatch):
    alice, alice_headers = _user(module, "alice")
    source, _ = _source_task(module, alice)
    submitted = _submit_reference(module, alice_headers, source)
    task_id = submitted.headers["Location"].rsplit("/", 1)[-1]
    _disable_cancel_dispatch(module, monkeypatch)
    module.app.config["user_db"].update_user(alice["id"], username="alice-renamed")
    impostor = module.app.config["user_db"].create_user(
        "alice", "alice-impostor@test.local", "password", registration_status="approved", user_status="active"
    )
    module.app.config["user_db"].verify_email(impostor["id"])
    from revocompute.auth import generate_token

    impostor_headers = {"Authorization": f"Bearer {generate_token(impostor['id'])}"}
    client = module.app.test_client()
    assert client.post(f"/compute/api/cancel/{task_id}", headers=impostor_headers).status_code == 403
    assert client.post(f"/compute/api/cancel/{task_id}", headers=alice_headers).status_code == 200


def test_obsolete_scope_submission_fields_are_rejected(module):
    alice, headers = _user(module, "alice")
    source, _ = _source_task(module, alice)

    response = _submit_reference(module, headers, source, extra={"scope_type": "personal"})

    assert response.status_code == 400
    assert b"Extra inputs are not permitted" in response.data


@pytest.mark.parametrize("condition", ["non_final", "not_manifest", "traversal", "absolute", "symlink"])
def test_unusable_artifact_references_fail_closed(module, condition):
    alice, headers = _user(module, "alice")
    source, _ = _source_task(
        module,
        alice,
        status="running" if condition == "non_final" else "finished",
        publish=condition != "not_manifest",
        symlink=condition == "symlink",
    )
    path = {"traversal": "../models/source.fasta", "absolute": "/etc/passwd"}.get(condition, "models/source.fasta")

    response = _submit_reference(module, headers, source, path=path)

    assert response.status_code in {400, 403}
    assert b"/tmp/" not in response.data
