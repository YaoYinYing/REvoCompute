# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The demo profile is preview and replay only, and production never sees it.

The demo deployment serves the canonical Task catalog so a designer can inspect
real contracts, and it serves validated replay bundles so the real Result
Workspace renders authentic recorded output. It must never accept a Task: the
single submission boundary refuses before parsing or reserving, the worker
refuses a row that somehow reached it, and every demo-only route is absent from
a production process. These tests drive the real application in both profiles.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import io
import json
from inspect import unwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from conftest import _admin_client_auth, _insert_pending_task, _load_pssm_module, _test_client_auth
from demo_replay_fixtures import (
    CAPTURED_ARTIFACT,
    EXCLUDED_ARTIFACT,
    SYNTHETIC_TASK_TYPE,
    TABLE_ARTIFACT,
    write_synthetic_replay_bundle,
)
from revocompute.tool_calls import ToolCallDatabase, new_tool_call_id
from revocompute.tool_workspace import ToolWorkspace

IDENTITY = {"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
DEMO_ENV = {**IDENTITY, "REVOCOMPUTE_DEMO_MODE": "true", "REVOCOMPUTE_JOB_EXECUTOR": "demo"}
SCENARIO_ID = "recorded-demo"


def _install_demo_replays(
    tmp_path: Path,
    scenario_id: str = SCENARIO_ID,
    *,
    binary_table: bool = False,
    html_artifact: bool = False,
) -> Path:
    """Leave the deployment's replay index where ``app`` loads it at import."""
    root = tmp_path / "pssm_env" / "demo" / "replays"
    root.mkdir(parents=True, exist_ok=True)
    bundle_path = write_synthetic_replay_bundle(root / f"{scenario_id}.json")
    if binary_table:
        _store_table_payload_as_binary(bundle_path)
    if html_artifact:
        _store_artifact_as_html(bundle_path)
    index = {
        "version": 1,
        "scenarios": [
            {
                "id": scenario_id,
                "title": "Recorded summary",
                "summary": "A recorded result for the demo playground.",
                "task_type": SYNTHETIC_TASK_TYPE,
                "bundle": f"{scenario_id}.json",
            }
        ],
    }
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return root


def _rewrite_payload(bundle_path: Path, path: str, data: bytes, media_type: str | None = None) -> None:
    """Replace one captured artifact's bytes and re-seal the bundle digest."""
    from revocompute.replay_bundle import bundle_digest, write_bundle

    document = json.loads(bundle_path.read_text(encoding="utf-8"))
    entry = document["payloads"][path]
    entry.pop("encoding", None)
    entry["payload"] = data.decode("utf-8")
    entry["size"] = len(data)
    entry["sha256"] = hashlib.sha256(data).hexdigest()
    if media_type is not None:
        entry["media_type"] = media_type
    for artifact in document["response"]["artifacts"]:
        if artifact["path"] == path:
            artifact["size"] = len(data)
            artifact["sha256"] = entry["sha256"]
            if media_type is not None:
                artifact["media_type"] = media_type
    for files in document["response"]["result"]["files"].values():
        for item in files:
            if item["path"] != path:
                continue
            # The served logical projection carries size but not the published
            # sha256 (that identity lives in the bundle's own logical_files).
            item["size"] = len(data)
            if "sha256" in item:
                item["sha256"] = entry["sha256"]
    for entries in (document.get("logical_files") or {}).values():
        for item in entries:
            if item.get("path") == path:
                item["size"] = len(data)
                item["sha256"] = entry["sha256"]
    document["bundle_digest"] = bundle_digest(document)
    write_bundle(bundle_path, document)


def _store_artifact_as_html(bundle_path: Path) -> None:
    """Carry the captured text artifact as an HTML document in the same bundle.

    A valid bundle may retain any published text artifact; the demo must treat
    it as untrusted bytes even when it is served inline.
    """
    _rewrite_payload(
        bundle_path,
        CAPTURED_ARTIFACT,
        b"<!doctype html><html><body><script>window.demoPwned = true</script></body></html>\n",
        media_type="text/html",
    )


def _store_table_payload_as_binary(bundle_path: Path) -> None:
    """Persist the synthetic table artifact as a valid non-UTF-8 replay payload.

    A captured coordinate stream (XTC/DCD) is checked in as base64 with the
    decoded size and sha256. The live table route refuses any bytes it cannot
    parse with a bounded 400; this makes the replay route answer the same way
    instead of letting a decode error reach the client as a 500.
    """
    from revocompute.replay_bundle import bundle_digest, write_bundle

    document = json.loads(bundle_path.read_text(encoding="utf-8"))
    data = b"\xff\xfe\x00binary table payload"
    entry = document["payloads"][TABLE_ARTIFACT]
    entry["encoding"] = "base64"
    entry["payload"] = base64.b64encode(data).decode("ascii")
    entry["size"] = len(data)
    entry["sha256"] = hashlib.sha256(data).hexdigest()
    for artifact in document["response"]["artifacts"]:
        if artifact["path"] == TABLE_ARTIFACT:
            artifact["size"] = len(data)
            artifact["sha256"] = entry["sha256"]
    for files in document["response"]["result"]["files"].values():
        for item in files:
            if item["path"] == TABLE_ARTIFACT:
                item["size"] = len(data)
                if "sha256" in item:
                    item["sha256"] = entry["sha256"]
    document["bundle_digest"] = bundle_digest(document)
    write_bundle(bundle_path, document)


def _install_frontend_entry(module, tmp_path: Path) -> str:
    """Give the app a built entry document to serve, as a deployment has."""
    static_root = tmp_path / "static"
    app_root = static_root / "app"
    app_root.mkdir(parents=True)
    entry = '<!doctype html><html><body><main id="app"></main></body></html>'
    (app_root / "index.html").write_text(entry, encoding="utf-8")
    module.app.static_folder = str(static_root)
    return entry


def test_demo_page_routes_serve_the_shell_to_a_signed_in_reader(monkeypatch, tmp_path):
    """A hard refresh or a shared deep link lands on the playground, not a 404."""
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    entry = _install_frontend_entry(module, tmp_path)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    for path in ("/compute/demo", f"/compute/demo/replays/{SCENARIO_ID}"):
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.content_type == "text/html; charset=utf-8"
        assert response.get_data(as_text=True) == entry
        assert response.headers["Cache-Control"] == "private, no-store"


def test_demo_page_routes_require_a_session_in_the_demo_profile(monkeypatch, tmp_path):
    """The playground is a signed-in destination, like every application page."""
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    _install_frontend_entry(module, tmp_path)
    client = module.app.test_client()
    for path in ("/compute/demo", f"/compute/demo/replays/{SCENARIO_ID}"):
        response = client.get(path, headers={"Accept": "text/html"})
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/compute/login")


def test_production_has_no_demo_page_routes(monkeypatch, tmp_path):
    """A production process serves no playground page, even to a signed-in reader."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=IDENTITY)
    entry = _install_frontend_entry(module, tmp_path)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    for path in ("/compute/demo", f"/compute/demo/replays/{SCENARIO_ID}"):
        response = client.get(path, headers=headers)
        assert response.status_code == 404
        assert response.get_data(as_text=True) != entry


def test_production_environment_reports_execution_available(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=IDENTITY)
    response = module.app.test_client().get("/compute/api/environment")
    assert response.status_code == 200
    assert response.get_json() == {"version": 1, "demo_mode": False, "execution": "available"}


def test_production_has_no_replay_routes(monkeypatch, tmp_path):
    """A production process answers the replay paths as absent, even signed in."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=IDENTITY)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    assert client.get("/compute/api/demo/replays", headers=headers).status_code == 404
    assert client.get(f"/compute/api/demo/replays/{SCENARIO_ID}", headers=headers).status_code == 404


def test_demo_environment_reports_preview_only(monkeypatch, tmp_path):
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    payload = module.app.test_client().get("/compute/api/environment").get_json()
    assert payload["demo_mode"] is True
    assert payload["execution"] == "preview_only"
    assert "not execute" in payload["notice"].lower()


def test_demo_catalog_still_projects_canonical_task_contracts(monkeypatch, tmp_path):
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    payload = module.app.test_client().get("/compute/api/types").get_json()
    assert payload["task_types"], "a demo must expose the canonical manifests for inspection"
    detail = module.app.test_client().get(f"/compute/api/types/{payload['task_types'][0]['name']}")
    assert detail.status_code == 200


def test_demo_submission_is_refused_without_creating_a_task(monkeypatch, tmp_path):
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    response = client.post("/compute/api/post", data={"task_type": "not-a-real-type"}, headers=headers)
    assert response.status_code == 403
    assert response.get_json()["code"] == "demo_read_only"
    assert module.task_store.list_tasks() == []


def test_demo_preflight_is_refused_the_same_way(monkeypatch, tmp_path):
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    # A type the demo catalog does serve, so the refusal cannot come from an
    # unknown method downstream of the submission gate.
    task_type = client.get("/compute/api/types").get_json()["task_types"][0]["name"]
    response = client.post(f"/compute/api/preflight/{task_type}", data={}, headers=headers)
    assert response.status_code == 403
    # The preflight envelope carries its refusal as a finding, so the stable
    # code the client matches on is ``errors[].code`` (the flat submission
    # envelope carries it at the top level).
    payload = response.get_json()
    assert payload["valid"] is False
    assert [finding["code"] for finding in payload["errors"]] == ["demo_read_only"]
    assert module.task_store.list_tasks() == []


def test_demo_replay_catalog_names_its_provenance(monkeypatch, tmp_path):
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    headers = _test_client_auth(module)
    payload = module.app.test_client().get("/compute/api/demo/replays", headers=headers).get_json()
    assert payload["version"] == 1
    scenario = payload["scenarios"][0]
    assert scenario["id"] == SCENARIO_ID
    assert scenario["task_type"] == SYNTHETIC_TASK_TYPE
    assert scenario["provenance"]["label"]
    assert scenario["bundle_digest"].startswith("sha256:")


def test_demo_manifest_points_at_demo_routes_and_serves_recorded_bytes(monkeypatch, tmp_path):
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    manifest = client.get(f"/compute/api/demo/replays/{SCENARIO_ID}", headers=headers).get_json()
    assert manifest["schema_version"] == 3 and manifest["terminal"] is True
    assert manifest["storyboard"] is None
    assert any("Storyboard" in item for item in manifest["limitations"])
    artifact = next(item for item in manifest["artifacts"] if item["path"] == CAPTURED_ARTIFACT)
    assert artifact["url"].startswith(f"/compute/api/demo/replays/{SCENARIO_ID}/artifacts/")
    body = client.get(artifact["url"], headers=headers)
    assert body.status_code == 200
    assert hashlib.sha256(body.data).hexdigest() == artifact["sha256"]


def test_demo_replay_api_routes_require_a_session(monkeypatch, tmp_path):
    """Every replay API route is private, refused at the same credential boundary."""
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    client = module.app.test_client()
    routes = (
        ("GET", "/compute/api/demo/replays"),
        ("GET", f"/compute/api/demo/replays/{SCENARIO_ID}"),
        ("GET", f"/compute/api/demo/replays/{SCENARIO_ID}/artifacts/{CAPTURED_ARTIFACT}"),
        ("GET", f"/compute/api/demo/replays/{SCENARIO_ID}/files/summary"),
        ("GET", f"/compute/api/demo/replays/{SCENARIO_ID}/tables/{TABLE_ARTIFACT}"),
        ("GET", f"/compute/api/demo/replays/{SCENARIO_ID}/ndarrays/{TABLE_ARTIFACT}?key=score&max_elements=8"),
        ("POST", f"/compute/api/demo/replays/{SCENARIO_ID}/archive"),
    )
    # The production result archive answers an anonymous caller through this same
    # ``login_required`` boundary; the demo routes must refuse identically.
    production = client.post(f"/compute/api/results/{'a' * 32}/archive")
    for method, path in routes:
        response = client.open(path, method=method)
        assert response.status_code == production.status_code == 401, path
        assert response.get_json() == production.get_json() == {
            "error": "Authentication required",
            "message": "Provide a valid Bearer token or X-API-Key credential.",
        }, path


def test_demo_logical_file_route_serves_the_captured_bytes(monkeypatch, tmp_path):
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    headers = _test_client_auth(module)
    response = module.app.test_client().get(
        f"/compute/api/demo/replays/{SCENARIO_ID}/files/summary", headers=headers
    )
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "residue pairs above threshold: 2\n"


def test_demo_byte_routes_sandbox_a_captured_html_payload(monkeypatch, tmp_path):
    """An inline recorded artifact cannot run script in the demo origin.

    The demo serves images and structures inline, so it does not default to an
    attachment; the live artifact route's ``CSP: sandbox`` is what keeps an
    untrusted HTML payload inert. ``?download=1`` remains the attachment switch.
    """
    _install_demo_replays(tmp_path, html_artifact=True)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    headers = _test_client_auth(module)
    client = module.app.test_client()
    base = f"/compute/api/demo/replays/{SCENARIO_ID}"
    inline = client.get(f"{base}/artifacts/{CAPTURED_ARTIFACT}", headers=headers)
    assert inline.status_code == 200
    assert inline.mimetype == "text/html"
    assert inline.headers["Content-Security-Policy"] == "sandbox"
    assert "Content-Disposition" not in inline.headers
    download = client.get(f"{base}/artifacts/{CAPTURED_ARTIFACT}?download=1", headers=headers)
    assert download.headers["Content-Security-Policy"] == "sandbox"
    assert download.headers["Content-Disposition"].startswith("attachment;")
    logical = client.get(f"{base}/files/summary", headers=headers)
    assert logical.mimetype == "text/html"
    assert logical.headers["Content-Security-Policy"] == "sandbox"


def test_demo_table_route_pages_the_captured_table(monkeypatch, tmp_path):
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    headers = _test_client_auth(module)
    response = module.app.test_client().get(
        f"/compute/api/demo/replays/{SCENARIO_ID}/tables/{TABLE_ARTIFACT}?offset=1&limit=1", headers=headers
    )
    assert response.status_code == 200
    assert response.get_json() == {
        "columns": ["name", "score"],
        "rows": [["beta", "2.5"]],
        "offset": 1,
        "limit": 1,
        "has_more": False,
    }


def test_demo_table_route_refuses_a_binary_payload_with_a_bounded_error(monkeypatch, tmp_path):
    """A non-UTF-8 table payload must be a bounded 400, never a decode 500.

    A captured XTC/DCD stream is binary; the live table route refuses an
    unpreviewable artifact rather than letting ``UnicodeDecodeError`` escape.
    """
    _install_demo_replays(tmp_path, binary_table=True)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    headers = _test_client_auth(module)
    response = module.app.test_client().get(
        f"/compute/api/demo/replays/{SCENARIO_ID}/tables/{TABLE_ARTIFACT}", headers=headers
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "Table could not be previewed"}


def test_demo_table_route_refuses_a_captured_non_table_artifact(monkeypatch, tmp_path):
    """A text artifact is not a table merely because its bytes are readable."""
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    headers = _test_client_auth(module)
    response = module.app.test_client().get(
        f"/compute/api/demo/replays/{SCENARIO_ID}/tables/{CAPTURED_ARTIFACT}", headers=headers
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "Artifact is not a table"}


def test_demo_array_route_refuses_the_element_limits_production_refuses(monkeypatch, tmp_path):
    """``max_elements`` is a bound, not a query decoration."""
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    headers = _test_client_auth(module)
    client = module.app.test_client()
    for query in (
        "key=score",
        "key=score&max_elements=0",
        "key=score&max_elements=1048577",
        "key=score&max_elements=abc",
    ):
        response = client.get(
            f"/compute/api/demo/replays/{SCENARIO_ID}/ndarrays/{TABLE_ARTIFACT}?{query}", headers=headers
        )
        assert response.status_code == 400, query
        assert response.get_json() == {"error": "Array projection is outside allowed bounds"}, query


def test_demo_array_route_projects_a_captured_numeric_column(monkeypatch, tmp_path):
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    headers = _test_client_auth(module)
    response = module.app.test_client().get(
        f"/compute/api/demo/replays/{SCENARIO_ID}/ndarrays/{TABLE_ARTIFACT}?key=score&max_elements=8",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["kind"] == "numeric"
    assert payload["key"] == "score"
    assert payload["data"] == [1.5, 2.5]


def test_demo_archive_route_states_the_recorded_result_contract(monkeypatch, tmp_path):
    """A replay records a result; it cannot be archived, and the route says so."""
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    headers = _test_client_auth(module)
    response = module.app.test_client().post(
        f"/compute/api/demo/replays/{SCENARIO_ID}/archive", headers=headers
    )
    assert response.status_code == 409
    assert response.get_json() == {"error": "A recorded demo result has no archive to build"}


def test_demo_replay_reports_a_missing_payload_instead_of_inventing_one(monkeypatch, tmp_path):
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    headers = _test_client_auth(module)
    response = module.app.test_client().get(
        f"/compute/api/demo/replays/{SCENARIO_ID}/artifacts/{EXCLUDED_ARTIFACT}", headers=headers
    )
    assert response.status_code == 404
    payload = response.get_json()
    assert payload["path"] == EXCLUDED_ARTIFACT
    assert "budget" in payload["reason"]


def test_unknown_replay_scenario_is_a_404(monkeypatch, tmp_path):
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    headers = _test_client_auth(module)
    assert (
        module.app.test_client().get("/compute/api/demo/replays/not-installed", headers=headers).status_code == 404
    )


def test_a_tampered_bundle_aborts_demo_startup(monkeypatch, tmp_path):
    root = _install_demo_replays(tmp_path)
    bundle_path = root / f"{SCENARIO_ID}.json"
    document = json.loads(bundle_path.read_text(encoding="utf-8"))
    document["payloads"][CAPTURED_ARTIFACT]["payload"] = "tampered"
    bundle_path.write_text(json.dumps(document), encoding="utf-8")
    from revocompute.demo import DemoReplayError

    with pytest.raises(DemoReplayError, match="invalid"):
        _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)


def test_replay_index_refuses_a_bundle_path_that_escapes(tmp_path):
    from revocompute.demo import DemoReplayError, load_demo_replays

    root = tmp_path / "replays"
    root.mkdir()
    (root / "index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "scenarios": [
                    {"id": "x", "bundle": "../outside.json", "task_type": SYNTHETIC_TASK_TYPE},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(DemoReplayError):
        load_demo_replays(root)


def test_demo_executor_requires_demo_mode():
    from revocompute.config import ComputeConfig

    with pytest.raises(ValueError):
        ComputeConfig(
            server_dir="/srv/x", upload_folder="/srv/x/upload", workspace_folder="/srv/x/work",
            results_folder="/srv/x/results", db_path="/srv/x/db", manage_db_path="/srv/x/manage",
            docker_user="1000:1000", port=8080, runners_dir="/srv/x/runners", job_executor="demo",
        )
    with pytest.raises(ValueError):
        ComputeConfig(
            server_dir="/srv/x", upload_folder="/srv/x/upload", workspace_folder="/srv/x/work",
            results_folder="/srv/x/results", db_path="/srv/x/db", manage_db_path="/srv/x/manage",
            docker_user="1000:1000", port=8080, runners_dir="/srv/x/runners", demo_mode=True,
        )


def test_demo_worker_refuses_a_row_that_reached_it(monkeypatch, tmp_path):
    """Defence in depth: the submission gate is primary, the worker is the second refusal."""
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    task_id = "a" * 32
    module.task_store.upsert_task(
        task_id, task_type=SYNTHETIC_TASK_TYPE, status="queued", filename="demo.pdb", file_path="/tmp/demo.pdb",
        uploaded_at=0.0, is_binary=0, storage_key="demo", submitted_by_user_id=1,
    )
    module.task_runtime._execute_compute_task(task_id)
    task = module.task_store.get_task(task_id)
    assert task["status"] == "failed"
    assert task["finished_at"]
    assert "demo" in str(task.get("error") or "").lower()
    # The refusal must not take the ordinary failure path, which publishes a
    # failure report and charges its bytes.
    assert [entry for entry in module.task_store.list_ledger(1, limit=200)
            if entry["reason_code"] == "storage_charged"] == []
    assert module.task_store.logical_owned_bytes(1) == 0
    assert module.task_store.get_result_publication(task_id) is None
    assert module.app.config["storage_resolver"].read_manifest_bytes(task) is None


@pytest.mark.parametrize(
    ("status", "finished_at", "walltime", "error"),
    [
        ("finished", 1_700_000_500.0, 100.0, None),
        ("failed", 1_700_000_600.0, 42.0, "original failure"),
    ],
)
def test_demo_worker_leaves_restored_terminal_rows_untouched(
    monkeypatch, tmp_path, status, finished_at, walltime, error
):
    """A redelivered dispatch must not rewrite finished/failed execution history."""
    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    task_id = "b" * 32
    module.task_store.upsert_task(
        task_id, task_type=SYNTHETIC_TASK_TYPE, status=status, filename="demo.pdb", file_path="/tmp/demo.pdb",
        uploaded_at=0.0, is_binary=0, storage_key="demo", submitted_by_user_id=1,
    )
    module.task_store.update_task(
        task_id, status=status, finished_at=finished_at, walltime=walltime, error=error, run_stage="execute",
    )
    before = module.task_store.get_task(task_id)

    module.task_runtime._execute_compute_task(task_id)

    assert module.task_store.get_task(task_id) == before
    assert [entry for entry in module.task_store.list_ledger(1, limit=200)
            if entry["reason_code"] == "storage_charged"] == []
    assert module.task_store.get_result_publication(task_id) is None


def test_demo_profile_refuses_mutating_operator_actions_before_any_row(monkeypatch, tmp_path):
    """The Admin path reaches the host controller outside the submission gate.

    ``runner.live_test`` runs ``run/restart.sh live-test``, whose executor
    upserts a Task row before the worker refuses it. A demo deployment must
    refuse the action at the operator write boundary, so a plan that is current
    and executable still reserves no Operator Job and writes no Task row.
    """
    from revocompute import operator_service as service_module
    from revocompute.admission import RunnerReadinessStatus
    from revocompute.operator_executor import ExecutorAvailability
    from revocompute.operator_service import OperatorServiceError
    from revocompute.runner_readiness import RunnerReadiness

    _install_demo_replays(tmp_path)
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)
    client = module.app.test_client()
    headers = _admin_client_auth(module)
    service = module.app.config["operator_service"]
    # Script only the expensive host boundary: a stale validation is a current,
    # executable plan, and holding the queue keeps the host command unrun so a
    # regression writes a job row instead of executing one.
    readiness = RunnerReadiness(
        runner_family="gpu_runner",
        status=RunnerReadinessStatus.VALIDATION_STALE,
        reason_code="RUNTIME_BUNDLE_CHANGED",
        message="RUNTIME_BUNDLE_CHANGED",
        doctor_ok=True,
        sif_path="/images/gpu_runner.sif",
        sif_exists=True,
        sif_sha256="sha256:sif",
        build_provenance_current=True,
        build_provenance_digest="sha256:build",
        runtime_bundle_sha256="sha256:bundle",
        receipt_exists=True,
        receipt_valid=False,
        receipt_tested_at="2026-01-01T00:00:00Z",
    )
    monkeypatch.setattr(service_module, "evaluate_runner_readiness", lambda _host, _family: readiness)
    monkeypatch.setattr(
        service_module,
        "availability",
        lambda _host: ExecutorAvailability(True, "operator_executor_available"),
    )
    monkeypatch.setattr(service, "_schedule", lambda work: None)

    plan = service.plan("runner.live_test", "gpu_runner")
    with pytest.raises(OperatorServiceError, match="preview and replay"):
        service.submit(
            "runner.live_test",
            "gpu_runner",
            plan_digest=plan.plan_digest,
            actor_user_id=1,
            actor_username="sysadmin",
        )
    assert service.jobs() == []

    # The Admin route maps the same refusal, and it is decided before plan
    # validation: a deliberately stale digest still reports the demo reason.
    for action in ("runner.live_test", "runner.build", "runner.prepare"):
        response = client.post(
            "/compute/api/auth/admin/runners/gpu_runner/actions",
            headers=headers,
            json={"action": action, "plan_digest": "sha256:" + "0" * 64},
        )
        assert response.status_code == 409, (action, response.get_json())
        assert "preview and replay" in response.get_json()["error"], action
    assert service.jobs() == []
    assert module.task_store.list_tasks() == []


def _demo_tool_module(monkeypatch, tmp_path):
    """A demo app with an enabled Tool family and its image installed.

    Today's deployed demo has no Tool images, but a missing image is an
    inventory fact rather than an authorization boundary, so the refusal must
    hold when the family is enabled and its image is present.
    """
    _install_demo_replays(tmp_path)
    images = tmp_path / "tool-images"
    images.mkdir()
    (images / "bioio.sif").write_bytes(b"fixture-sif")
    environment = {**DEMO_ENV, "ENABLED_TOOL_FAMILIES": "bioio", "TOOL_IMAGE_DIR": str(images)}
    return _load_pssm_module(monkeypatch, tmp_path, extra_env=environment)


def _tool_rows(module) -> int:
    with module.tool_calls.engine.connect() as connection:
        return connection.execute(select(func.count()).select_from(module.tool_calls.table)).scalar_one()


def test_demo_tool_submission_is_refused_before_any_durable_state(monkeypatch, tmp_path):
    module = _demo_tool_module(monkeypatch, tmp_path)
    assert module.tool_registry.get("structure_inspect").runtime.image.is_file()

    sent: list[tuple] = []
    monkeypatch.setattr(module.celery, "send_task", lambda *args, **kwargs: sent.append((args, kwargs)))
    monkeypatch.setattr(
        module.tool_calls,
        "reserve",
        lambda **_kwargs: pytest.fail("a demo Tool submission reserved admission capacity"),
    )
    client = module.app.test_client()
    headers = _test_client_auth(module)
    fixture = Path(__file__).resolve().parents[1] / "data" / "3fap_hf3_A_short.pdb"
    response = client.post(
        "/compute/api/tools/structure_inspect/call",
        headers=headers,
        data={
            "parameters": "{}",
            "file_roles": "structure",
            "files": (io.BytesIO(fixture.read_bytes()), "sample.pdb"),
        },
    )

    assert response.status_code == 403
    assert response.get_json() == {
        "error": "This demo deployment is preview and replay only; it does not execute Tools.",
        "code": "demo_read_only",
    }
    assert sent == []
    assert _tool_rows(module) == 0
    assert not module.tool_workspace.root.exists()


def test_demo_tool_worker_refuses_a_queued_call(monkeypatch, tmp_path):
    """A row that evades the boundary still cannot reach a runtime or a child."""
    module = _demo_tool_module(monkeypatch, tmp_path)
    import revocompute.tool_runtime as tool_runtime

    monkeypatch.setattr(
        tool_runtime,
        "COMPUTE_CONFIG",
        dataclasses.replace(tool_runtime.COMPUTE_CONFIG, demo_mode=True, job_executor="demo"),
    )
    calls = ToolCallDatabase(str(tmp_path / "worker-calls.sqlite3"))
    workspace = ToolWorkspace(tmp_path / "tool-workspace", request_max_bytes=1_000_000, output_max_bytes=1_000_000)
    tool = module.tool_registry.get("structure_inspect")
    call_id = new_tool_call_id()
    calls.reserve(
        tool_call_id=call_id,
        tool_type=tool.name,
        runtime_family=tool.runtime.name,
        runtime_identity=tool.runtime.identity,
        user_id=1,
        username="owner",
        parameter_json="{}",
        input_manifest_json='{"inputs":{}}',
        idempotency_key=None,
        per_user_limit=3,
        global_limit=8,
    )

    class UntouchableManager:
        def ensure_warm(self, _runtime):
            pytest.fail("the demo worker acquired a Tool runtime")

        def execute(self, *_args, **_kwargs):
            pytest.fail("the demo worker started a Tool child process")

    tool_runtime.execute_tool_call(
        call_id,
        calls=calls,
        registry=module.tool_registry,
        workspace=workspace,
        manager=UntouchableManager(),
        config=module.app.config["TOOL_CONFIG"],
    )

    record = calls.get(call_id)
    assert record["status"] == "failed"
    assert record["error_class"] == "runtime_unavailable"
    assert "demo" in record["error"].lower()
    assert record["reserved_bytes"] == 0
    assert not workspace.root.exists()


def _demo_app(monkeypatch, tmp_path):
    _install_demo_replays(tmp_path)
    return _load_pssm_module(monkeypatch, tmp_path, extra_env=DEMO_ENV)


def _assert_demo_refusal(response, refusal):
    assert response.status_code == 403
    assert response.get_json() == {
        "error": f"This demo deployment is preview and replay only; {refusal}",
        "code": "demo_read_only",
    }


def test_demo_infrastructure_refresh_is_refused_before_any_probe(monkeypatch, tmp_path):
    module = _demo_app(monkeypatch, tmp_path)

    class UntouchableReadiness:
        def report(self, **_kwargs):
            pytest.fail("the demo refresh ran infrastructure probes")

    module.app.config["infrastructure_readiness"] = UntouchableReadiness()
    response = module.app.test_client().post(
        "/compute/api/auth/admin/infrastructure/refresh",
        headers=_admin_client_auth(module),
    )

    _assert_demo_refusal(response, "it does not run infrastructure readiness probes.")


def test_demo_gpu_reconciliation_is_refused_before_the_worker(monkeypatch, tmp_path):
    module = _demo_app(monkeypatch, tmp_path)
    enqueued: list[bool] = []

    class _Result:
        def get(self, timeout):
            return {}

    monkeypatch.setattr(
        module.task_runtime.reconcile_slurm_allocations,
        "apply_async",
        lambda: enqueued.append(True) or _Result(),
    )
    client = module.app.test_client()
    headers = _admin_client_auth(module)
    response = client.post("/compute/api/auth/admin/gpu-credit/reconciliation", headers=headers)

    _assert_demo_refusal(response, "it does not run resource reconciliation.")
    assert enqueued == []
    # The read side stays available: only the worker-executing POST is refused.
    assert client.get("/compute/api/auth/admin/gpu-credit/reconciliation", headers=headers).status_code == 200


def test_demo_cancel_is_refused_without_stopping_resources_or_touching_the_row(monkeypatch, tmp_path):
    module = _demo_app(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    task_id = _insert_pending_task(module, tmp_path / "cancel-result")
    before = module.task_store.get_task(task_id)
    stopped: list[dict] = []
    route_globals = unwrap(module.app.view_functions["cancel_task"]).__globals__
    monkeypatch.setitem(
        route_globals,
        "cancel_compute_resources",
        SimpleNamespace(delay=lambda **fields: stopped.append(fields)),
    )

    response = module.app.test_client().post(f"/compute/api/cancel/{task_id}", headers=headers)

    _assert_demo_refusal(response, "it does not cancel Tasks.")
    assert stopped == []
    assert module.task_store.get_task(task_id) == before


def test_demo_archive_is_refused_without_enqueuing(monkeypatch, tmp_path):
    module = _demo_app(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    task_id = _insert_pending_task(module, tmp_path / "archive-result")
    task = module.task_store.get_task(task_id)
    task_root = Path(module.app.config["storage_resolver"].get_task_root(task))
    (task_root / "result.txt").write_text("score\n", encoding="utf-8")
    module.task_store.update_task(task_id, status="finished")
    # Finalize the publication so the only thing standing between this row and
    # ``build_results_archive.apply_async`` is the demo guard: an unguarded
    # route must reach the enqueue, not refuse publication first.
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(task_id), execution_state="completed", finished_at=1_700_000_000
    )
    assert module.app.config["storage_resolver"].publication_state(module.task_store.get_task(task_id)) == "available"
    enqueued: list[list[str]] = []
    monkeypatch.setattr(
        module.task_runtime.build_results_archive,
        "apply_async",
        lambda args: enqueued.append(args) or SimpleNamespace(id="archive-job"),
    )

    response = module.app.test_client().post(f"/compute/api/results/{task_id}/archive", headers=headers)

    _assert_demo_refusal(response, "it does not build result archives.")
    assert enqueued == []


def test_demo_delete_is_refused_and_keeps_the_row(monkeypatch, tmp_path):
    module = _demo_app(monkeypatch, tmp_path)
    headers = _test_client_auth(module)
    task_id = _insert_pending_task(module, tmp_path / "delete-result")
    before = module.task_store.get_task(task_id)
    client = module.app.test_client()

    single = client.delete(f"/compute/api/delete/{task_id}", headers=headers)
    batch = client.post("/compute/api/delete", headers=headers, json={"md5sums": [task_id]})

    for response in (single, batch):
        _assert_demo_refusal(response, "it does not delete Tasks.")
    assert module.task_store.get_task(task_id) == before


def test_production_execution_surfaces_still_reach_their_boundaries(monkeypatch, tmp_path):
    """The demo gate narrows nothing in production."""
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env=IDENTITY)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    admin_headers = _admin_client_auth(module)

    class RecordingReadiness:
        def __init__(self):
            self.calls: list[dict] = []

        def report(self, **kwargs):
            self.calls.append(kwargs)
            return {"components": []}

    readiness = RecordingReadiness()
    module.app.config["infrastructure_readiness"] = readiness
    refresh = client.post("/compute/api/auth/admin/infrastructure/refresh", headers=admin_headers)
    assert refresh.status_code == 200
    assert readiness.calls == [{"force": True, "admin": True}]

    enqueued: list[bool] = []

    class _Result:
        def get(self, timeout):
            return {"settled": 0}

    monkeypatch.setattr(
        module.task_runtime.reconcile_slurm_allocations,
        "apply_async",
        lambda: enqueued.append(True) or _Result(),
    )
    reconciled = client.post("/compute/api/auth/admin/gpu-credit/reconciliation", headers=admin_headers)
    assert reconciled.status_code == 200
    assert enqueued == [True]

    cancel_id = _insert_pending_task(module, tmp_path / "cancel-result")
    stopped: list[dict] = []
    route_globals = unwrap(module.app.view_functions["cancel_task"]).__globals__
    monkeypatch.setitem(
        route_globals,
        "cancel_compute_resources",
        SimpleNamespace(delay=lambda **fields: stopped.append(fields)),
    )
    cancelled = client.post(f"/compute/api/cancel/{cancel_id}", headers=headers)
    assert cancelled.status_code == 200
    assert stopped
    assert module.task_store.get_task(cancel_id)["status"] == "cancelled"

    delete_id = _insert_pending_task(module, tmp_path / "delete-result")
    deleted = client.delete(f"/compute/api/delete/{delete_id}", headers=headers)
    assert deleted.status_code == 200
    assert module.task_store.get_task(delete_id)["status"].startswith("deleted")


def test_demo_admin_cannot_write_accounting_or_policy_state(monkeypatch, tmp_path):
    module = _demo_app(monkeypatch, tmp_path)
    admin_headers = _admin_client_auth(module)
    _test_client_auth(module, "target")
    target_id = int(module.app.config["user_db"].get_user_by_username("target")["id"])
    before = {
        "ledger": module.task_store.list_ledger(target_id),
        "policy_audit": module.task_store.list_policy_audit(target_id),
        "quota_audit": module.task_store.list_storage_quota_audit(target_id),
        "quota_policy": module.task_store.storage_quota_policy(target_id),
    }
    client = module.app.test_client()
    requests = (
        (
            "post",
            f"/compute/api/auth/admin/users/{target_id}/gpu-credit/adjustments",
            {"gpu_seconds": 60, "reason": "demo", "idempotency_key": "demo-adjust"},
            "it does not adjust GPU credit.",
        ),
        (
            "put",
            f"/compute/api/auth/admin/users/{target_id}/gpu-credit/allowance",
            {"monthly_gpu_seconds": 7200, "idempotency_key": "demo-allowance"},
            "it does not change GPU allowances.",
        ),
        (
            "post",
            f"/compute/api/auth/admin/users/{target_id}/gpu-credit/reset",
            {"reason": "demo", "idempotency_key": "demo-reset"},
            "it does not reset GPU credit.",
        ),
        (
            "post",
            "/compute/api/auth/admin/gpu-credit/reset",
            {"reason": "demo", "idempotency_key": "demo-reset-all"},
            "it does not reset GPU credit.",
        ),
        (
            "put",
            f"/compute/api/auth/admin/users/{target_id}/storage-quota",
            {"state": "limited", "limit_bytes": 1024, "reason": "demo", "idempotency_key": "demo-quota"},
            "it does not change storage quotas.",
        ),
    )
    for method, path, body, refusal in requests:
        response = getattr(client, method)(path, headers=admin_headers, json=body)
        _assert_demo_refusal(response, refusal)

    assert {
        "ledger": module.task_store.list_ledger(target_id),
        "policy_audit": module.task_store.list_policy_audit(target_id),
        "quota_audit": module.task_store.list_storage_quota_audit(target_id),
        "quota_policy": module.task_store.storage_quota_policy(target_id),
    } == before
