# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from conftest import _load_pssm_module, _test_client_auth
from revocompute.tool_calls import new_tool_call_id

REPO_ROOT = Path(__file__).resolve().parents[2]


def _app(monkeypatch, tmp_path):
    return _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "structure_runner"},
    )


def _finished_tool_call(module, username: str = "tester") -> str:
    _test_client_auth(module, username)
    user = module.app.config["user_db"].get_user_by_username(username)
    call_id = new_tool_call_id()
    root = module.tool_workspace.create(call_id)
    content = (REPO_ROOT / "tests" / "data" / "3fap_hf3_A_short.pdb").read_bytes()
    (root / "output" / "reference.pdb").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    result = {
        "version": 1,
        "tool_call_id": call_id,
        "tool_type": "md_trajectory_convert",
        "outputs": {
            "reference": [
                {
                    "path": "reference.pdb",
                    "format": "pdb",
                    "logical_type": "protein_structure",
                    "sha256": digest,
                    "size": len(content),
                }
            ]
        },
        "warnings": [],
    }
    module.tool_calls.reserve(
        tool_call_id=call_id,
        tool_type="md_trajectory_convert",
        runtime_family="mdconvert",
        runtime_identity="fixture-runtime",
        user_id=int(user["id"]),
        username=username,
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
        result_manifest_json=json.dumps(result),
    )
    return call_id


def _submit(module, headers, call_id: str, name: str = "reference.pdb"):
    return module.app.test_client().post(
        "/compute/api/post",
        headers=headers,
        data={
            "task_type": "structure_runner",
            "params[iter]": "100",
            "tool_output_references": f"@{call_id}/{name}",
            "tool_output_roles": "structure",
        },
        content_type="multipart/form-data",
    )


def test_finished_tool_output_is_bound_as_a_task_input_with_provenance(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    call_id = _finished_tool_call(module)

    class _DummyAsyncResult:
        id = "celery-test-id"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *a, **kw: _DummyAsyncResult())
    response = _submit(module, headers, call_id)

    assert response.status_code == 302, response.get_data(as_text=True)[:500]
    task = module.task_store.get_task(response.get_json()["md5sum"])
    manifest_path = Path(module.app.config["storage_resolver"].get_input_root(task)) / "inputs" / "task.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["inputs"]["structure"][0]
    assert entry["relative_path"] == "reference.pdb"
    source_bytes = (REPO_ROOT / "tests" / "data" / "3fap_hf3_A_short.pdb").read_bytes()
    assert entry["sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert entry["source"] == {
        "kind": "tool_output",
        "tool_call_id": call_id,
        "tool_type": "md_trajectory_convert",
        "artifact_path": "reference.pdb",
        "sha256": entry["sha256"],
        "size": len(source_bytes),
    }
    copied = manifest_path.parent / "structure" / "reference.pdb"
    assert copied.read_bytes() == (REPO_ROOT / "tests" / "data" / "3fap_hf3_A_short.pdb").read_bytes()


def test_another_user_cannot_bind_a_tool_output(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    call_id = _finished_tool_call(module, "tester")
    other = _test_client_auth(module, "other")

    response = _submit(module, other, call_id)

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "tool_output_reference_unavailable"


def test_tampered_tool_output_is_refused(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    call_id = _finished_tool_call(module)
    (module.tool_workspace.call_root(call_id) / "output" / "reference.pdb").write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\nEND\n",
        encoding="utf-8",
    )

    response = _submit(module, headers, call_id)

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "tool_output_reference_mismatch"


def test_unknown_tool_output_path_is_refused(monkeypatch, tmp_path):
    module = _app(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    call_id = _finished_tool_call(module)

    response = _submit(module, headers, call_id, name="other.pdb")

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "tool_output_reference_invalid"
