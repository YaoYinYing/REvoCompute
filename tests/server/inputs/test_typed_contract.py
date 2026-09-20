# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import io
import json
import time
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
import conftest
from conftest import _load_pssm_module, _test_client_auth
from revocompute.task_types import TaskInputRole

ROOT = Path(__file__).resolve().parents[3]
RECEPTOR = b"ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\nEND\n"
LIGAND = (ROOT / "tests/data/docking/ethanol.sdf").read_bytes()


@pytest.fixture
def module(monkeypatch, tmp_path):
    loaded = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gnina"},
    )
    user = loaded.app.config["user_db"].create_user(
        "typed-inputs", "typed-inputs@test.local", "password", registration_status="approved", user_status="active"
    )
    loaded.app.config["user_db"].verify_email(user["id"])
    loaded.app.config["user_db"].update_user(user["id"], allow_gpu_use=True)

    class Queued:
        id = "typed-inputs"

    monkeypatch.setattr(loaded.run_compute_task, "apply_async", lambda *args, **kwargs: Queued())
    return loaded


def _headers(module):
    return _test_client_auth(module, "typed-inputs", "password")


def _submit(module, files, roles):
    return module.app.test_client().post(
        "/compute/api/post",
        headers=_headers(module),
        data={"task_type": "gnina", "files": files, "input_roles": roles},
        content_type="multipart/form-data",
    )


def test_roles_bind_independently_of_multipart_order_and_survive_cleanup(module):
    response = _submit(
        module,
        [(io.BytesIO(LIGAND), "ligand.sdf"), (io.BytesIO(RECEPTOR), "receptor.pdb")],
        ["ligand", "receptor"],
    )

    assert response.status_code == 302, response.get_json()
    task = module.task_store.get_task(response.headers["Location"].rsplit("/", 1)[-1])
    snapshot = Path(module.app.config["storage_resolver"].get_input_root(task))
    manifest = json.loads((snapshot / "inputs/task.json").read_text())
    assert manifest["version"] == 3
    assert manifest["inputs"]["receptor"][0]["path"] == "/workspace/inputs/receptor/receptor.pdb"
    assert manifest["inputs"]["ligand"][0]["path"] == "/workspace/inputs/ligand/ligand.sdf"
    module.task_runtime._cleanup_task_workspace(task)
    assert (snapshot / "inputs/receptor/receptor.pdb").read_bytes() == RECEPTOR
    assert (snapshot / "inputs/ligand/ligand.sdf").read_bytes() == LIGAND


@pytest.mark.parametrize(
    ("files", "roles", "code", "role"),
    [
        ([(io.BytesIO(RECEPTOR), "receptor.pdb")], ["receptor"], "input_role_cardinality", "ligand"),
        (
            [(io.BytesIO(RECEPTOR), "receptor.pdb"), (io.BytesIO(LIGAND), "ligand.sdf")],
            ["receptor", "unknown"],
            "input_role_unknown",
            "unknown",
        ),
        (
            [(io.BytesIO(RECEPTOR), "receptor.pdb"), (io.BytesIO(LIGAND), "ligand.sdf")],
            ["ligand", "receptor"],
            "input_role_format",
            "ligand",
        ),
    ],
)
def test_role_contract_rejections_are_structured(module, files, roles, code, role):
    response = _submit(module, files, roles)
    assert response.status_code == 400
    detail = response.get_json()["details"][0]
    assert (detail["code"], detail["role"]) == (code, role)


def test_declared_format_without_core_security_validator_fails_closed(module):
    base, runner = module.task_runtime._get_task_type("gnina")
    conftest._inject_task_type(module, 
        replace(
            base,
            name="binary_input",
            gpus=False,
            inputs=(TaskInputRole("trajectory", "Trajectory", "trajectory", ("bcif",), 1, 1),),
            params=(),
            schema={"type": "object", "additionalProperties": False, "properties": {}},
        ),
        runner,
    )
    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_headers(module),
        data={
            "task_type": "binary_input",
            "files": (io.BytesIO(b"\x00\x89BCIF\xff"), "trajectory.bcif"),
            "input_roles": "trajectory",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_format_invalid"
    assert module.task_store.list_tasks() == []


def test_artifact_and_upload_share_the_same_role_contract(module):
    user = module.app.config["user_db"].get_user_by_username("typed-inputs")
    source_id = uuid.uuid4().hex
    source = {"md5sum": source_id, "storage_key": user["storage_key"]}
    root = Path(module.app.config["storage_resolver"].get_task_root(source))
    receptor = root / "model.pdb"
    root.mkdir(parents=True)
    receptor.write_bytes(RECEPTOR)
    digest = hashlib.sha256(RECEPTOR).hexdigest()
    (root / "manifest.json").write_text(
        json.dumps({"artifacts": [{"path": "model.pdb", "sha256": digest, "size": len(RECEPTOR)}]})
    )
    module.task_store.upsert_task(
        source_id,
        filename="source.pdb",
        file_path=str(receptor),
        uploaded_at=time.time(),
        finished_at=time.time(),
        status="finished",
        is_binary=0,
        username=user["username"],
        submitted_by_user_id=user["id"],
        storage_key=user["storage_key"],
        task_type="gnina",
    )

    choices = module.app.test_client().get(
        "/compute/api/types/gnina/reusable-artifacts", headers=_headers(module)
    )
    assert choices.status_code == 200
    assert choices.get_json()["roles"]["receptor"] == [
        {"format": "pdb", "label": f"{source_id[:8]} · model.pdb", "reference": f"@{source_id}/model.pdb"}
    ]
    assert choices.get_json()["roles"]["ligand"] == []

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_headers(module),
        data={
            "task_type": "gnina",
            "files": (io.BytesIO(LIGAND), "ligand.sdf"),
            "input_roles": "ligand",
            "artifact_references": f"@{source_id}/model.pdb",
            "artifact_roles": "receptor",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302, response.get_json()
    task = module.task_store.get_task(response.headers["Location"].rsplit("/", 1)[-1])
    form = json.loads(task["input_form"])
    assert {(entity["role"], entity["format"]) for entity in form["entities"] if entity["type"] == "file"} == {
        ("receptor", "pdb"),
        ("ligand", "sdf"),
    }
