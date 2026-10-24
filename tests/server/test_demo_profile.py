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
import hashlib
import json
from pathlib import Path

import pytest

from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from demo_replay_fixtures import (
    CAPTURED_ARTIFACT,
    EXCLUDED_ARTIFACT,
    SYNTHETIC_TASK_TYPE,
    TABLE_ARTIFACT,
    write_synthetic_replay_bundle,
)

IDENTITY = {"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
DEMO_ENV = {**IDENTITY, "REVOCOMPUTE_DEMO_MODE": "true", "REVOCOMPUTE_JOB_EXECUTOR": "demo"}
SCENARIO_ID = "recorded-demo"


def _install_demo_replays(
    tmp_path: Path, scenario_id: str = SCENARIO_ID, *, binary_table: bool = False
) -> Path:
    """Leave the deployment's replay index where ``app`` loads it at import."""
    root = tmp_path / "pssm_env" / "demo" / "replays"
    root.mkdir(parents=True, exist_ok=True)
    bundle_path = write_synthetic_replay_bundle(root / f"{scenario_id}.json")
    if binary_table:
        _store_table_payload_as_binary(bundle_path)
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
    assert "demo" in str(task.get("error") or "").lower()


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
