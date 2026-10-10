# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""HTTP contract used to reconstruct the Result workspace from its URL."""

from __future__ import annotations

import json
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
        task_type="cpu_runner",
    )

    active = client.get(f"/compute/api/running/{running_id}", headers=owner)
    assert active.status_code == 202
    assert active.get_json() == {
        "md5sum": running_id,
        "display_name": "query.fasta",
        "result_available": False,
        # A running task has published nothing: its state is the ordinary
        # not-yet case, not a quarantine of an existing result.
        "result_publication": "not_finalized",
        "results_url": f"/compute/api/results/{running_id}",
        "status": "running",
        "status_url": f"/compute/api/running/{running_id}",
        "task_id": running_id,
        "task_type": "cpu_runner",
        "terminal": False,
    }
    spec = client.get("/openapi.json").get_json()
    _validate_openapi_schema(spec, "TaskStatus", active.get_json())

    module.task_store.update_task(running_id, filename="C:\\private\\unsafe\nquery.fasta")
    safe_name = client.get(f"/compute/api/running/{running_id}", headers=owner).get_json()["display_name"]
    assert safe_name == "unsafequery.fasta"

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
        task_type="cpu_runner",
    )
    task = module.task_store.get_task(failed_id)
    module.task_runtime._finalize_results_manifest(task, execution_state="failed", finished_at=1_700_000_000)
    result_root = module.app.config["storage_resolver"].get_task_root(task)
    module.task_store.update_task(failed_id, error=f"runner failed in {result_root}")

    failed = client.get(f"/compute/api/running/{failed_id}", headers=owner)
    assert failed.status_code == 200
    assert failed.get_json()["task_type"] == "cpu_runner"
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
    assert status_operation["responses"]["200"]["description"] == (
        "Visible terminal task status, including failures; failed tasks return 200 so URL clients can reconstruct "
        "their terminal state, while missing or concealed tasks return 404"
    )

    status_schema = spec["components"]["schemas"]["TaskStatus"]
    assert {"task_type", "result_available"} <= set(status_schema["required"])
    # The publication vocabulary is server-owned and published, so a client can
    # tell a quarantined (pre-anchor) result from a task that published nothing.
    assert status_schema["properties"]["result_publication"]["enum"] == [
        "available",
        "not_finalized",
        "unanchored",
        "manifest_missing",
        "manifest_unreadable",
        "anchor_mismatch",
        "anchor_invalid",
        None,
    ]
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
    logical_file_schema = spec["components"]["schemas"]["LogicalResultFile"]
    assert logical_file_schema["properties"]["confidence_encoding"]["enum"] == ["plddt_bfactor"]
    result_schema = spec["components"]["schemas"]["ResultManifest"]
    assert result_schema["properties"]["error"]["type"] == ["string", "null"]
    projection_schema = spec["components"]["schemas"]["ArrayProjection"]
    numeric_projection, categorical_projection = projection_schema["oneOf"]
    assert numeric_projection["properties"]["kind"]["const"] == "numeric"
    assert numeric_projection["properties"]["total_elements"]["maximum"] == 1_048_576
    assert numeric_projection["properties"]["data"]["items"]["type"] == ["boolean", "integer", "number", "null"]
    assert categorical_projection["properties"]["kind"]["const"] == "categorical"
    assert categorical_projection["properties"]["dtype"]["const"] == "string"
    assert categorical_projection["properties"]["data"]["items"]["maxLength"] == 64
    assert "8 MiB" in projection_schema["description"] and "4 MiB" in projection_schema["description"]
    assert "8 MiB" in spec["components"]["schemas"]["TablePage"]["description"]
    projection_parameters = spec["paths"]["/compute/api/results/{task_id}/ndarrays/{path}"]["get"]["parameters"]
    projection_key = next(item for item in projection_parameters if item.get("name") == "key")
    assert projection_key["schema"]["maxLength"] == 512
    assert "array indices" in spec["paths"]["/compute/api/results/{task_id}/ndarrays/{path}"]["get"]["description"]
    assert next(item for item in projection_parameters if item.get("name") == "max_elements")["required"] is True
    assert spec["paths"]["/compute/api/auth/token"]["get"]["security"] == [
        {"cookieAuth": []},
        {"bearerAuth": []},
    ]

    client.post("/compute/api/auth/logout")
    expired = client.get("/compute/api/auth/me")
    assert expired.status_code == 401
    assert expired.get_json()["error"] == "Authentication required"


def test_result_logical_structure_preserves_confidence_encoding(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gpu_runner"},
    )
    client = module.app.test_client()
    headers = _test_client_auth(module)
    task_id = uuid.uuid4().hex
    result_dir = tmp_path / "confidence-result"
    structure = result_dir / "ranked" / "rank_0.cif"
    structure.parent.mkdir(parents=True)
    structure.write_text("data_prediction\n#\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        task_id,
        filename="input.fasta",
        file_path=result_dir / "input.fasta",
        result_dir=result_dir,
        username="tester",
        status="finished",
        task_type="gpu_runner",
    )
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )

    response = client.get(f"/compute/api/results/{task_id}", headers=headers)

    assert response.status_code == 200
    logical = response.get_json()["result"]["files"]["structures"][0]
    assert logical["confidence_encoding"] == "plddt_bfactor"


def test_result_url_serves_the_built_vite_entry_unchanged(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    headers = _test_client_auth(module)
    task_id = uuid.uuid4().hex
    result_dir = tmp_path / "shell-result"
    result_dir.mkdir()
    _upsert_task_for_user(
        module,
        task_id,
        filename="private-input.fasta",
        file_path=result_dir / "private-input.fasta",
        result_dir=result_dir,
        username="tester",
        status="running",
    )
    static_root = tmp_path / "static"
    app_root = static_root / "app"
    assets = static_root / "app" / "assets"
    app_root.mkdir(parents=True)
    assets.mkdir()
    entry = (
        '<!doctype html><html><head><link rel="stylesheet" href="/static/app/assets/app.css">'
        '<script type="module" src="/static/app/assets/app.js"></script></head>'
        '<body><main id="app"></main></body></html>'
    )
    (app_root / "index.html").write_text(entry, encoding="utf-8")
    for name, contents in {
        "app.js": "export {};\n",
        "app.css": "body{}\n",
    }.items():
        (assets / name).write_text(contents, encoding="utf-8")
    module.app.static_folder = str(static_root)
    client = module.app.test_client()

    direct = client.get(f"/compute/results/{task_id}", headers=headers)
    refresh = client.get(f"/compute/results/{task_id}", headers=headers)
    html = direct.get_data(as_text=True)

    assert direct.status_code == refresh.status_code == 200
    assert direct.headers["Cache-Control"] == "no-cache"
    assert html == entry
    assert html.count('<main id="app"></main>') == 1
    assert "/static/app/assets/app.js" in html
    assert "/static/app/assets/app.css" in html
    assert task_id not in html and "private-input.fasta" not in html
    assert "result-task-data" not in html and "task-results.js" not in html
    assert client.get("/static/app/assets/app.js").get_data(as_text=True) == "export {};\n"

    (app_root / "index.html").unlink()
    assert client.get(f"/compute/results/{task_id}", headers=headers).status_code == 503


def test_table_page_enforces_cell_and_serialized_response_byte_limits(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    client = module.app.test_client()
    headers = _test_client_auth(module)
    task_id = uuid.uuid4().hex
    result_dir = tmp_path / "bounded-table"
    result_dir.mkdir()
    (result_dir / "small.csv").write_text("value\nsafe\n", encoding="utf-8")
    columns = [f"column_{index}" for index in range(88)]
    escaped_cells = ["\x01" * 16_000 for _ in columns]
    (result_dir / "escaped.csv").write_text(",".join(columns) + "\n" + ",".join(escaped_cells) + "\n", encoding="utf-8")
    (result_dir / "wide-cell.csv").write_text("value\n" + ("x" * 16_385) + "\n", encoding="utf-8")
    (result_dir / "sentinel.csv").write_text("value\nsafe\n" + ("x" * 16_385) + "\n", encoding="utf-8")
    (result_dir / "offset.csv").write_text("value\n" + ("x" * 16_385) + "\nsafe\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        task_id,
        filename="input.fasta",
        file_path=result_dir / "input.fasta",
        result_dir=result_dir,
        username="tester",
        status="finished",
    )
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    small = client.get(f"/compute/api/results/{task_id}/tables/small.csv", headers=headers)
    oversized = client.get(f"/compute/api/results/{task_id}/tables/escaped.csv", headers=headers)
    wide_cell = client.get(f"/compute/api/results/{task_id}/tables/wide-cell.csv", headers=headers)
    sentinel = client.get(f"/compute/api/results/{task_id}/tables/sentinel.csv?limit=1", headers=headers)
    offset = client.get(f"/compute/api/results/{task_id}/tables/offset.csv?offset=1&limit=1", headers=headers)

    assert small.status_code == 200
    assert len(small.data) <= 8 * 1024 * 1024
    assert oversized.status_code == 400
    assert oversized.get_json() == {"error": "Table could not be previewed"}
    assert wide_cell.status_code == 400
    assert sentinel.get_json() == {
        "columns": ["value"],
        "rows": [["safe"]],
        "offset": 0,
        "limit": 1,
        "has_more": True,
    }
    assert offset.get_json() == {
        "columns": ["value"],
        "rows": [["safe"]],
        "offset": 1,
        "limit": 1,
        "has_more": False,
    }


def test_table_page_matrix_column_cap_allows_the_label_column(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    client = module.app.test_client()
    headers = _test_client_auth(module)
    task_id = uuid.uuid4().hex
    result_dir = tmp_path / "matrix-columns"
    result_dir.mkdir()
    # A 512-position matrix writes one leading row-label column beside its 512 values.
    values = [f"{index}.0" for index in range(512)]
    (result_dir / "matrix.csv").write_text(
        "position," + ",".join(str(index + 1) for index in range(512)) + "\n" + "1," + ",".join(values) + "\n",
        encoding="utf-8",
    )
    (result_dir / "values.csv").write_text("value\nsafe\n", encoding="utf-8")
    (result_dir / "wide.csv").write_text(
        ",".join(f"c{index}" for index in range(101)) + "\n" + ",".join("1" for _ in range(101)) + "\n",
        encoding="utf-8",
    )
    _upsert_task_for_user(
        module,
        task_id,
        filename="input.fasta",
        file_path=result_dir / "input.fasta",
        result_dir=result_dir,
        username="tester",
        status="finished",
    )
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    matrix = client.get(f"/compute/api/results/{task_id}/tables/matrix.csv?matrix=1", headers=headers)
    plain_matrix = client.get(f"/compute/api/results/{task_id}/tables/matrix.csv", headers=headers)
    plain_wide = client.get(f"/compute/api/results/{task_id}/tables/wide.csv", headers=headers)
    matrix_wide = client.get(f"/compute/api/results/{task_id}/tables/wide.csv?matrix=1", headers=headers)

    assert matrix.status_code == 200
    assert len(matrix.get_json()["columns"]) == 513
    assert len(matrix.get_json()["rows"][0]) == 513
    assert plain_matrix.status_code == 400
    assert plain_matrix.get_json() == {"error": "Table could not be previewed"}
    assert plain_wide.status_code == 400
    assert matrix_wide.status_code == 200
    assert len(matrix_wide.get_json()["columns"]) == 101
