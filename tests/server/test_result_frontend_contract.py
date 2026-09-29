# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""HTTP contract used to reconstruct the Result workspace from its URL."""

from __future__ import annotations

import uuid

from conftest import _load_pssm_module, _test_client_auth, _upsert_task_for_user
from jsonschema import Draft202012Validator


def _validate_openapi_schema(spec, schema_name, payload):
    Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema_name}", "components": spec["components"]}
    ).validate(payload)


def test_task_status_distinguishes_active_failed_and_hidden_results(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    client = module.app.test_client()
    owner = _test_client_auth(module)
    other = _test_client_auth(module, username="other")

    running_id = uuid.uuid4().hex
    running_dir = tmp_path / "running"
    running_dir.mkdir()
    _upsert_task_for_user(
        module,
        running_id,
        filename="query.fasta",
        file_path=running_dir / "query.fasta",
        result_dir=running_dir,
        username="tester",
        status="running",
        task_type="gremlin",
    )

    active = client.get(f"/compute/api/running/{running_id}", headers=owner)
    assert active.status_code == 202
    assert active.get_json() == {
        "md5sum": running_id,
        "display_name": "query.fasta",
        "result_available": False,
        "results_url": f"/compute/api/results/{running_id}",
        "status": "running",
        "status_url": f"/compute/api/running/{running_id}",
        "task_id": running_id,
        "task_type": "gremlin",
        "terminal": False,
    }
    spec = client.get("/openapi.json").get_json()
    _validate_openapi_schema(spec, "TaskStatus", active.get_json())

    failed_id = uuid.uuid4().hex
    failed_dir = tmp_path / "failed"
    failed_dir.mkdir()
    (failed_dir / "task_failed.txt").write_text("runner stopped\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        failed_id,
        filename="query.fasta",
        file_path=failed_dir / "query.fasta",
        result_dir=failed_dir,
        username="tester",
        status="failed",
        task_type="gremlin",
    )
    task = module.task_store.get_task(failed_id)
    module.task_runtime._finalize_results_manifest(task, execution_state="failed", finished_at=1_700_000_000)
    result_root = module.app.config["storage_resolver"].get_task_root(task)
    module.task_store.update_task(failed_id, error=f"runner failed in {result_root}")

    failed = client.get(f"/compute/api/running/{failed_id}", headers=owner)
    assert failed.status_code == 200
    assert failed.get_json()["task_type"] == "gremlin"
    assert failed.get_json()["terminal"] is True
    assert failed.get_json()["result_available"] is True
    assert failed.get_json()["error"] == "runner failed in <result_dir>"
    assert result_root not in failed.get_json()["error"]

    result = client.get(f"/compute/api/results/{failed_id}", headers=owner)
    assert result.status_code == 200
    payload = result.get_json()
    assert payload["status"] == "failed"
    assert payload["terminal"] is True
    assert payload["error"] == "runner failed in <result_dir>"
    diagnostic = next(item for item in payload["artifacts"] if item["path"] == "task_failed.txt")
    assert diagnostic["capability"] == "text"
    assert diagnostic["url"].endswith("/artifacts/task_failed.txt")
    _validate_openapi_schema(spec, "ResultManifest", payload)

    hidden = client.get(f"/compute/api/running/{failed_id}", headers=other)
    missing = client.get(f"/compute/api/running/{uuid.uuid4().hex}", headers=owner)
    anonymous = client.get(f"/compute/api/running/{failed_id}")
    assert hidden.status_code == missing.status_code == anonymous.status_code == 404


def test_cookie_session_and_openapi_describe_result_reconstruction(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    _test_client_auth(module)
    client = module.app.test_client()

    login = client.post("/compute/api/auth/login", json={"username": "tester", "password": "password"})
    assert login.status_code == 200
    profile = client.get("/compute/api/auth/me")
    assert profile.status_code == 200
    assert profile.get_json()["username"] == "tester"

    spec = client.get("/openapi.json").get_json()
    _validate_openapi_schema(spec, "CurrentUser", profile.get_json())
    assert spec["paths"]["/compute/api/auth/me"]["get"]["security"] == [
        {"cookieAuth": []},
        {"bearerAuth": []},
        {"apiKeyAuth": []},
    ]
    status_operation = spec["paths"]["/compute/api/running/{task_id}"]["get"]
    assert "404" in status_operation["responses"]
    assert status_operation["responses"]["200"]["description"] == "Terminal task status, including failures"

    status_schema = spec["components"]["schemas"]["TaskStatus"]
    assert {"task_type", "result_available"} <= set(status_schema["required"])
    artifact_schema = spec["components"]["schemas"]["Artifact"]
    assert artifact_schema["properties"]["capability"]["enum"] == [
        "molecular_structure",
        "table",
        "plot",
        "image",
        "text",
        "archive",
        "download_only",
        "unknown",
    ]
    result_schema = spec["components"]["schemas"]["ResultManifest"]
    assert result_schema["properties"]["error"]["type"] == ["string", "null"]

    client.post("/compute/api/auth/logout")
    expired = client.get("/compute/api/auth/me")
    assert expired.status_code == 401
    assert expired.get_json()["error"] == "Authentication required"
