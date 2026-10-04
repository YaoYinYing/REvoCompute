# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Behavior contracts for the frontend-owned application surfaces."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth, _upsert_task_for_user
from jsonschema import Draft202012Validator
from revocompute.auth import generate_token


def _validate(spec: dict, name: str, payload: object) -> None:
    Draft202012Validator(
        {"$ref": f"#/components/schemas/{name}", "components": spec["components"]},
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(payload)


def _frontend_entry(module, tmp_path) -> str:
    static_root = tmp_path / "static"
    app_root = static_root / "app"
    app_root.mkdir(parents=True)
    entry = '<!doctype html><html><body><main id="app"></main></body></html>'
    (app_root / "index.html").write_text(entry, encoding="utf-8")
    module.app.static_folder = str(static_root)
    return entry


def test_application_pages_serve_one_inert_frontend_entry_with_existing_auth(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    entry = _frontend_entry(module, tmp_path)
    client = module.app.test_client()
    user = _test_client_auth(module)

    assert client.get("/runners").get_data(as_text=True) == entry
    assert client.get("/runners/not-an-installed-runner").get_data(as_text=True) == entry
    for path in ("/compute/create_task", "/compute/dashboard"):
        anonymous = client.get(path)
        authenticated = client.get(path, headers=user)
        assert anonymous.status_code == 401
        assert authenticated.status_code == 200
        assert authenticated.get_data(as_text=True) == entry
        assert authenticated.headers["Cache-Control"] == "private, no-store"

    # The two known legacy browser entry points redirect (temporarily) to their
    # canonical modern destinations; the redirect is application-owned, not a
    # wildcard shim. Any other legacy path stays retired and 404s.
    legacy = {
        "/PSSM_GREMLIN/dashboard": "/compute/dashboard",
        "/PSSM_GREMLIN/create_task": "/compute/create_task?task_type=gremlin",
    }
    for legacy_path, destination in legacy.items():
        response = client.get(legacy_path)
        assert response.status_code == 302
        assert response.headers["Location"] == destination
        # The destination keeps its own authentication boundary after the redirect.
        anonymous = client.get(destination)
        landed = client.get(destination, headers=user)
        assert anonymous.status_code == 401
        assert landed.status_code == 200
        assert landed.get_data(as_text=True) == entry

    for path in (
        # The legacy surface is closed to the two known entry points above;
        # every other retired legacy path stays gone.
        "/PSSM_GREMLIN/",
        "/PSSM_GREMLIN/results",
        "/static/js/dashboard.js",
        "/static/js/runners.js",
        "/static/js/create-task.js",
        "/static/js/input-workspace.js",
        "/static/js/plugin-host.js",
        "/static/js/py2dmol-preview.js",
        "/static/css/dashboard.css",
        "/static/css/runners.css",
        "/static/css/create-task.css",
    ):
        assert client.get(path).status_code == 404


def test_task_list_enforces_visibility_and_projects_domain_capabilities(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    client = module.app.test_client()
    owner = _test_client_auth(module)
    _test_client_auth(module, username="other")
    admin = _admin_client_auth(module)
    task_id = uuid.uuid4().hex
    other_id = uuid.uuid4().hex
    task_root = tmp_path / "task"
    other_root = tmp_path / "other-task"
    task_root.mkdir()
    other_root.mkdir()
    structure = Path(module.app.config["UPLOAD_FOLDER"]) / "input.cif"
    structure.parent.mkdir(parents=True, exist_ok=True)
    structure.write_text("data_demo\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        task_id,
        filename="input.cif",
        file_path=structure,
        result_dir=task_root,
        username="tester",
        status="running",
    )
    _upsert_task_for_user(
        module,
        other_id,
        filename="private.fasta",
        file_path=other_root / "private.fasta",
        result_dir=other_root,
        username="other",
        status="finished",
    )
    module.task_store.update_task(
        task_id,
        input_form=json.dumps(
            {
                "entities": [
                    {
                        "type": "file",
                        "logical_type": "protein_structure",
                        "format": "mmcif",
                        "snapshot_path": str(structure),
                    }
                ]
            }
        ),
        finished_at=None,
    )

    assert client.get("/compute/api/tasks").status_code == 401
    own = client.get("/compute/api/tasks", headers=owner)
    assert own.status_code == 200
    assert [item["task_id"] for item in own.json["tasks"]] == [task_id]
    summary = own.json["tasks"][0]
    assert summary["owner"] is None
    assert summary["terminal"] is False
    assert summary["actions"]["cancel"]["allowed"] is True
    assert summary["result"]["available"] is False
    assert summary["input_preview"] == {
        "capability": "molecular_structure",
        "format": "mmcif",
        "url": f"/compute/api/tasks/{task_id}/input",
    }
    assert not ({"sequence", "submitted_time", "walltime", "fasta_fn"} & set(summary))

    all_tasks = client.get("/compute/api/tasks", headers=admin)
    assert {item["task_id"] for item in all_tasks.json["tasks"]} == {task_id, other_id}
    assert {item["owner"] for item in all_tasks.json["tasks"]} == {"tester", "other"}

    spec = client.get("/openapi.json").get_json()
    _validate(spec, "TaskList", own.get_json())
    _validate(spec, "TaskList", all_tasks.get_json())

    module.task_store.update_task(task_id, input_form=json.dumps({"entities": [None, "invalid"]}))
    malformed = client.get("/compute/api/tasks", headers=owner)
    assert malformed.status_code == 200
    assert malformed.get_json()["tasks"][0]["input_preview"] is None

    module.task_store.update_task(
        task_id,
        input_form=json.dumps(
            {
                "entities": [
                    {
                        "type": "file",
                        "logical_type": "protein_structure",
                        "format": ["mmcif"],
                        "snapshot_path": str(structure),
                    }
                ]
            }
        ),
    )
    malformed_format = client.get("/compute/api/tasks", headers=owner)
    assert malformed_format.status_code == 200
    assert malformed_format.get_json()["tasks"][0]["input_preview"]["format"] == "pdb"


def test_guest_task_list_does_not_advertise_forbidden_delete(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    database = module.app.config["user_db"]
    guest = database.create_user(
        username="guest-list",
        email="guest-list@test.local",
        password="guest-password",
        role="guest",
        registration_status="approved",
        user_status="active",
    )
    database.verify_email(guest["id"])
    task_id = uuid.uuid4().hex
    task_root = tmp_path / "guest-task"
    task_root.mkdir()
    _upsert_task_for_user(
        module,
        task_id,
        filename="guest.fasta",
        file_path=task_root / "guest.fasta",
        result_dir=task_root,
        username="guest-list",
        status="finished",
    )
    headers = {"Authorization": f"Bearer {generate_token(guest['id'])}"}

    response = module.app.test_client().get("/compute/api/tasks", headers=headers)

    assert response.status_code == 200
    assert response.get_json()["tasks"][0]["actions"]["delete"]["allowed"] is False


def test_workspace_plugin_descriptor_is_explicit_same_origin_module_contract(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    client = module.app.test_client()
    detail = next(
        client.get(item["detail_url"]).get_json()
        for item in client.get("/compute/api/types").get_json()["task_types"]
        if client.get(item["detail_url"]).get_json()["input_workspace"]["plugins"]
    )
    embedded = detail["input_workspace"]["plugins"][0]
    descriptor = client.get(embedded["descriptor_url"])

    assert descriptor.status_code == 200
    assert descriptor.get_json() == embedded
    assert embedded["module"]["type"] == "module"
    assert embedded["module"]["url"].startswith("/compute/api/workspace/assets/")
    assert all(item["media_type"] == "text/css" for item in embedded["stylesheets"])
    assert "module_url" not in embedded and "stylesheet_urls" not in embedded
    assert "workspace_plugins" not in detail
    auth = _test_client_auth(module)
    assert client.get(embedded["module"]["url"], headers=auth).content_type in {
        "text/javascript; charset=utf-8",
        "application/javascript; charset=utf-8",
    }
    if embedded["stylesheets"]:
        assert client.get(embedded["stylesheets"][0]["url"], headers=auth).content_type == "text/css; charset=utf-8"
    spec = client.get("/openapi.json").get_json()
    _validate(spec, "TaskTypeDetail", detail)
    _validate(spec, "WorkspacePlugin", embedded)
