# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import io
import hashlib
import json
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from conftest import _load_pssm_module, _test_client_auth
from revocompute.tool_calls import new_tool_call_id


def _app(monkeypatch, tmp_path, extra_env=None):
    images = tmp_path / "tool-images"
    images.mkdir()
    (images / "bioio.sif").write_bytes(b"fixture-sif")
    environment = {
        "RUNNER_UID": "1234",
        "RUNNER_GID": "5678",
        "ENABLED_TOOL_FAMILIES": "bioio",
        "TOOL_IMAGE_DIR": str(images),
    }
    environment.update(extra_env or {})
    return _load_pssm_module(
        monkeypatch,
        tmp_path,
        environment,
    )


def test_all_tool_discovery_routes_require_authentication(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    client = module.app.test_client()

    assert client.get("/compute/api/tools").status_code == 401
    assert client.get("/compute/api/tools/structure_inspect").status_code == 401
    assert client.get("/compute/api/tool-parameters/structure_inspect").status_code == 401
    assert client.get("/compute/api/tool-calls/tool_call_" + "A" * 32).status_code == 401
    assert client.get("/compute/api/tool-calls").status_code == 404


def test_authenticated_progressive_discovery_exposes_typed_contract(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _test_client_auth(module)

    catalog = client.get("/compute/api/tools", headers=headers)
    detail = client.get("/compute/api/tools/structure_convert", headers=headers)
    parameters = client.get("/compute/api/tool-parameters/structure_convert", headers=headers)

    assert catalog.status_code == 200
    assert {tool["id"] for tool in catalog.get_json()["tools"]} == {
        "structure_inspect", "structure_convert", "structure_to_fasta", "fasta_inspect"
    }
    assert detail.get_json()["inputs"][0]["id"] == "structure"
    assert detail.get_json()["outputs"][0]["id"] == "structure"
    assert detail.get_json()["available"] is True
    assert parameters.get_json()["properties"]["output_format"]["enum"] == ["pdb", "mmcif"]


def test_submission_is_asynchronous_idempotent_and_owned(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    queued: list[tuple] = []

    def send_task(*args, **kwargs):
        queued.append((args, kwargs))
        return SimpleNamespace(id="celery-tool-1")

    monkeypatch.setattr(module.celery, "send_task", send_task)
    client = module.app.test_client()
    owner_headers = _test_client_auth(module, "owner") | {"Idempotency-Key": "inspect-once"}
    fixture = Path(__file__).resolve().parents[2] / "data" / "3fap_hf3_A_short.pdb"

    def submit():
        return client.post(
            "/compute/api/tools/structure_inspect/call",
            headers=owner_headers,
            data={"parameters": "{}", "file_roles": "structure", "files": (io.BytesIO(fixture.read_bytes()), "sample.pdb")},
        )

    first = submit()
    second = submit()
    call_id = first.get_json()["tool_call_id"]

    assert first.status_code == 202
    assert first.headers["Location"].endswith(call_id)
    assert second.status_code == 202
    assert second.get_json()["tool_call_id"] == call_id
    assert len(queued) == 1
    assert queued[0][1]["queue"] == "tools"
    assert client.get(f"/compute/api/tool-calls/{call_id}", headers=owner_headers).status_code == 200

    other_headers = _test_client_auth(module, "other")
    assert client.get(f"/compute/api/tool-calls/{call_id}", headers=other_headers).status_code == 404
    assert client.get(f"/compute/api/tool-calls/{call_id}/results", headers=other_headers).status_code == 404


def test_submission_rejects_unbound_and_invalid_parameters(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    fixture = Path(__file__).resolve().parents[2] / "data" / "3fap_hf3_A_short.pdb"

    unbound = client.post(
        "/compute/api/tools/structure_inspect/call",
        headers=headers,
        data={"parameters": "{}", "files": (io.BytesIO(fixture.read_bytes()), "sample.pdb")},
    )
    invalid = client.post(
        "/compute/api/tools/structure_convert/call",
        headers=headers,
        data={
            "parameters": '{"output_format":"pdbqt"}',
            "file_roles": "structure",
            "files": (io.BytesIO(fixture.read_bytes()), "sample.pdb"),
        },
    )

    assert unbound.status_code == 400
    assert invalid.status_code == 400
    assert invalid.get_json()["error_class"] == "invalid_parameters"


def test_task_artifact_to_tool_is_materialized_for_owner_only(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    queued = []
    monkeypatch.setattr(
        module.celery,
        "send_task",
        lambda *args, **kwargs: queued.append((args, kwargs)) or SimpleNamespace(id="tool-from-task"),
    )
    owner_headers = _test_client_auth(module, "owner")
    owner = module.app.config["user_db"].get_user_by_username("owner")
    source_id = uuid.uuid4().hex
    source = {"md5sum": source_id, "storage_key": owner["storage_key"]}
    root = Path(module.app.config["storage_resolver"].get_task_root(source))
    artifact = root / "sequence.fasta"
    root.mkdir(parents=True)
    artifact.write_text(">source\nACDEFG\n", encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (root / "manifest.json").write_text(
        json.dumps({"artifacts": [{"path": "sequence.fasta", "sha256": digest, "size": artifact.stat().st_size}]}),
        encoding="utf-8",
    )
    module.task_store.upsert_task(
        source_id,
        filename="sequence.fasta",
        file_path=str(artifact),
        uploaded_at=time.time(),
        finished_at=time.time(),
        status="finished",
        is_binary=0,
        username="owner",
        submitted_by_user_id=owner["id"],
        storage_key=owner["storage_key"],
        task_type="gremlin",
    )

    response = module.app.test_client().post(
        "/compute/api/tools/fasta_inspect/call",
        headers=owner_headers,
        data={
            "parameters": "{}",
            "artifact_references": f"@{source_id}/sequence.fasta",
            "artifact_roles": "sequence",
        },
    )

    assert response.status_code == 202, response.get_json()
    record = module.tool_calls.get(response.get_json()["tool_call_id"])
    copied = module.tool_workspace.call_root(record["tool_call_id"]) / "input" / "sequence" / "sequence.fasta"
    assert copied.read_bytes() == artifact.read_bytes()
    assert json.loads(record["input_manifest_json"])["inputs"]["sequence"][0]["source"] == {
        "kind": "task_artifact",
        "task_id": source_id,
        "artifact_path": "sequence.fasta",
        "sha256": digest,
    }
    assert len(queued) == 1

    other_headers = _test_client_auth(module, "other")
    rejected = module.app.test_client().post(
        "/compute/api/tools/fasta_inspect/call",
        headers=other_headers,
        data={
            "parameters": "{}",
            "artifact_references": f"@{source_id}/sequence.fasta",
            "artifact_roles": "sequence",
        },
    )
    assert rejected.status_code == 403
    assert len(queued) == 1


def test_storage_pressure_evicts_terminal_calls_but_never_active_calls(monkeypatch, tmp_path):
    module = _app(
        monkeypatch,
        tmp_path,
        {
            "TOOL_STORAGE_MAX_BYTES": "900",
            "TOOL_REQUEST_MAX_BYTES": "500",
            "TOOL_OUTPUT_MAX_BYTES": "500",
        },
    )
    monkeypatch.setattr(module.celery, "send_task", lambda *_args, **_kwargs: SimpleNamespace(id="queued"))
    owner_headers = _test_client_auth(module, "owner")
    owner = module.app.config["user_db"].get_user_by_username("owner")

    terminal_id = new_tool_call_id()
    terminal_root = module.tool_workspace.create(terminal_id)
    (terminal_root / "output" / "old.bin").write_bytes(b"x" * 700)
    module.tool_calls.reserve(
        tool_call_id=terminal_id,
        tool_type="fasta_inspect",
        runtime_family="bioio",
        runtime_identity="fixture",
        user_id=int(owner["id"]),
        username="owner",
        parameter_json="{}",
        input_manifest_json='{"inputs":{}}',
        idempotency_key=None,
        per_user_limit=3,
        global_limit=8,
        workspace_bytes=700,
    )
    now = time.time()
    assert module.tool_calls.transition(
        terminal_id,
        expected=("queued",),
        status="finished",
        finished_at=now,
        expires_at=now + 86400,
        result_manifest_json='{"outputs":{}}',
    )
    accepted = module.app.test_client().post(
        "/compute/api/tools/fasta_inspect/call",
        headers=owner_headers,
        data={
            "parameters": "{}",
            "file_roles": "sequence",
            "files": (io.BytesIO(b">sample\nACDE\n"), "sample.fasta"),
        },
    )
    assert accepted.status_code == 202, accepted.get_json()
    assert module.tool_calls.get(terminal_id) is None
    assert not terminal_root.exists()

    active_id = new_tool_call_id()
    active_root = module.tool_workspace.create(active_id)
    (active_root / "scratch" / "active.bin").write_bytes(b"y" * 700)
    module.tool_calls.reserve(
        tool_call_id=active_id,
        tool_type="fasta_inspect",
        runtime_family="bioio",
        runtime_identity="fixture",
        user_id=int(owner["id"]),
        username="owner",
        parameter_json="{}",
        input_manifest_json='{"inputs":{}}',
        idempotency_key=None,
        per_user_limit=3,
        global_limit=8,
        workspace_bytes=700,
    )
    assert module.tool_calls.transition(active_id, expected=("queued",), status="preparing", started_at=now)
    assert module.tool_calls.transition(active_id, expected=("preparing",), status="running")
    other_headers = _test_client_auth(module, "other")
    rejected = module.app.test_client().post(
        "/compute/api/tools/fasta_inspect/call",
        headers=other_headers,
        data={
            "parameters": "{}",
            "file_roles": "sequence",
            "files": (io.BytesIO(b">other\nACDE\n"), "other.fasta"),
        },
    )
    assert rejected.status_code == 507
    assert rejected.get_json()["reason"] == "storage_limit"
    assert module.tool_calls.get(active_id)["status"] == "running"
    assert active_root.exists()

def test_finished_tool_output_becomes_an_independent_durable_task_input(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _test_client_auth(module, "owner")
    user = module.app.config["user_db"].get_user_by_username("owner")
    call_id = new_tool_call_id()
    call_root = module.tool_workspace.create(call_id)
    output = call_root / "output" / "sequence.fasta"
    output.write_text(">A\nACDEFG\n", encoding="utf-8")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest = {
        "outputs": {
            "sequence": [
                {
                    "path": "sequence.fasta",
                    "format": "fasta",
                    "logical_type": "protein_sequence",
                    "sha256": digest,
                    "size": output.stat().st_size,
                }
            ]
        }
    }
    reservation = module.tool_calls.reserve(
        tool_call_id=call_id,
        tool_type="structure_to_fasta",
        runtime_family="bioio",
        runtime_identity="runtime-fixture",
        user_id=int(user["id"]),
        username="owner",
        parameter_json="{}",
        input_manifest_json='{"inputs":{}}',
        idempotency_key=None,
        per_user_limit=3,
        global_limit=8,
    )
    now = time.time()
    assert module.tool_calls.transition(
        call_id,
        expected=("queued",),
        status="finished",
        finished_at=now,
        expires_at=now + 86400,
        result_manifest_json=json.dumps(manifest),
        workspace_bytes=output.stat().st_size,
    )
    results = client.get(f"/compute/api/tool-calls/{call_id}/results", headers=headers)
    download = client.get(f"/compute/api/tool-calls/{call_id}/outputs/sequence", headers=headers)
    other_headers = _test_client_auth(module, "other")

    assert results.status_code == 200
    assert results.get_json()["outputs"]["sequence"][0]["sha256"] == digest
    assert download.status_code == 200
    assert download.data == b">A\nACDEFG\n"
    assert client.get(f"/compute/api/tool-calls/{call_id}/outputs/sequence", headers=other_headers).status_code == 404
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *_args, **_kwargs: SimpleNamespace(id="task-queue-1"))

    response = client.post(
        "/compute/api/post",
        headers=headers,
        data={
            "task_type": "gremlin",
            "artifact_references": f"@{call_id}/sequence",
            "artifact_roles": "sequence",
        },
    )

    assert response.status_code == 302, response.get_json()
    task_id = response.headers["Location"].rsplit("/", 1)[-1]
    task = module.task_store.get_task(task_id)
    form = json.loads(task["input_form"])
    snapshot = Path(form["snapshot_root"]) / "sequence" / "sequence.fasta"
    provenance = json.loads(task["artifact_provenance"])[0]
    module.tool_workspace.delete(call_id)
    module.tool_calls.delete_terminal(call_id)

    assert snapshot.read_text(encoding="utf-8") == ">A\nACDEFG\n"
    assert provenance["source_tool_call_id"] == call_id
    assert provenance["source_tool_type"] == "structure_to_fasta"
    assert provenance["source_tool_output_id"] == "sequence"
    assert provenance["source_runtime_identity"] == "runtime-fixture"

    expired_id = new_tool_call_id()
    expired_root = module.tool_workspace.create(expired_id)
    expired_output = expired_root / "output" / "sequence.fasta"
    expired_output.write_bytes(snapshot.read_bytes())
    module.tool_calls.reserve(
        tool_call_id=expired_id,
        tool_type="structure_to_fasta",
        runtime_family="bioio",
        runtime_identity="runtime-fixture",
        user_id=int(user["id"]),
        username="owner",
        parameter_json="{}",
        input_manifest_json='{"inputs":{}}',
        idempotency_key=None,
        per_user_limit=3,
        global_limit=8,
    )
    assert module.tool_calls.transition(
        expired_id,
        expected=("queued",),
        status="finished",
        finished_at=now - 2,
        expires_at=now - 1,
        result_manifest_json=json.dumps(manifest),
        workspace_bytes=expired_output.stat().st_size,
    )
    expired = client.post(
        "/compute/api/post",
        headers=headers,
        data={
            "task_type": "gremlin",
            "artifact_references": f"@{expired_id}/sequence",
            "artifact_roles": "sequence",
        },
    )
    assert expired.status_code == 403
