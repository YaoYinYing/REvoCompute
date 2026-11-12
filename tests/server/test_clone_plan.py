# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Clone & Reuse planning and provenance through the real HTTP boundary.

The plan is read-only: it resolves the source's recorded values against the
current Task contract, reports every incompatible value by field, and never
creates a Task, mutates the source, or exposes a source path or URL. These tests
drive the real routes against synthetic registered Tasks and a real Task row.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import conftest
from conftest import _admin_client_auth, _load_pssm_module, _task_owner, _test_client_auth
from revocompute import clone_plan
from revocompute.task_types import TaskInputRole

TASK = "clone_task"
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "seed": {"type": "integer", "default": 5, "minimum": 0, "maximum": 10},
        "enabled": {"type": "boolean", "default": True},
        "mode": {"type": "string", "enum": ["fast", "exact"], "default": "fast"},
        "label": {"type": "string", "default": "current"},
    },
}


def _module(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    base, runner = module.task_runtime._get_task_type("cpu_runner")
    conftest._inject_task_type(
        module,
        replace(
            base,
            name=TASK,
            inputs=(TaskInputRole("sequence", "Sequence", "protein_sequence", ("fasta",), 1, 1),),
            params=(),
            schema=SCHEMA,
        ),
        runner,
    )
    # Create and verify the ordinary caller before a source row exists, so
    # ``_task_owner`` reuses a credential-bearing account rather than a bare row.
    _test_client_auth(module)
    return module


def _source_input_form(module, *, task_id: str, snapshot: bool = True, digest: bool = True) -> tuple[dict, Path | None]:
    owner = _task_owner(module, "tester")
    resolver = module.app.config["storage_resolver"]
    snapshot_path = None
    if snapshot:
        root = Path(resolver.get_input_root({"md5sum": task_id, **owner})) / "inputs" / "sequence"
        root.mkdir(parents=True, exist_ok=True)
        snapshot_path = root / "source.fasta"
        snapshot_path.write_bytes(b">source\nACDEFGHIK\n")
    payload = snapshot_path.read_bytes() if snapshot_path else b">source\nACDEFGHIK\n"
    digest_value = hashlib.sha256(payload).hexdigest() if digest else ""
    return (
        {
            "entities": [
                {"name": "seed", "type": "int", "value": "0", "verified_value": 0},
                {"name": "enabled", "type": "bool", "value": "false", "verified_value": False},
                {"name": "mode", "type": "str", "value": "fast", "verified_value": "fast"},
                {
                    "name": "sequence",
                    "type": "file",
                    "role": "sequence",
                    "value": "source.fasta",
                    "format": "fasta",
                    "hash": digest_value,
                    "size": len(payload),
                    "snapshot_path": str(snapshot_path) if snapshot_path else "",
                },
            ],
            "workspace": {"version": 2, "capabilities": {}},
        },
        snapshot_path,
    )


def _create_source(module, *, status: str = "finished", form: dict | None = None) -> str:
    task_id = hashlib.md5(f"source-{status}-{bool(form)}".encode(), usedforsecurity=False).hexdigest()
    owner = _task_owner(module, "tester")
    if form is None:
        form, _path = _source_input_form(module, task_id=task_id)
    module.task_store.upsert_task(
        task_id,
        filename="source.fasta",
        file_path="",
        uploaded_at=1_700_000_000.0,
        finished_at=1_700_000_100.0,
        walltime=100.0,
        status=status,
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username="tester",
        task_type=TASK,
        input_form=json.dumps(form),
        submitted_by_user_id=int(owner["submitted_by_user_id"]),
        storage_key=str(owner["storage_key"]),
        artifact_provenance="[]",
    )
    return task_id


def _source_unchanged(module, task_id: str, before: dict) -> None:
    after = module.task_store.get_task(task_id)
    assert after is not None
    assert after["status"] == before["status"]
    assert after["input_form"] == before["input_form"]
    assert int(after["submitted_by_user_id"]) == int(before["submitted_by_user_id"])


def test_the_plan_prefills_recorded_zero_and_false_and_never_mutates_the_source(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    source_id = _create_source(module)
    before = module.task_store.get_task(source_id)
    assert before is not None
    tasks_before = len(module.task_store.list_tasks())

    response = module.app.test_client().post(
        f"/compute/api/tasks/{source_id}/clone-plan", headers=_test_client_auth(module)
    )

    assert response.status_code == 201, response.get_data(as_text=True)
    plan = response.get_json()
    parameters = {item["name"]: item for item in plan["compatible_parameters"]}
    # ``0`` and ``false`` are recorded values, not absence.
    assert parameters["seed"] == {"name": "seed", "value": "0", "source": "recorded"}
    assert parameters["enabled"] == {"name": "enabled", "value": "false", "source": "recorded"}
    assert parameters["mode"] == {"name": "mode", "value": "fast", "source": "recorded"}
    # A default the source never recorded resolves through the current schema
    # and says so.
    assert parameters["label"] == {"name": "label", "value": "current", "source": "current_default"}
    assert plan["blocked_fields"] == []
    warning_codes = {item["code"] for item in plan["warnings"]}
    assert {"source_schema_not_recorded", "resources_rechecked"} <= warning_codes
    assert plan["can_submit"] is False
    assert plan["target_task_type"] == TASK
    assert plan["target_schema_revision"] == clone_plan.schema_revision(SCHEMA)
    assert plan["source_task_id"] == source_id
    assert plan["plan_id"]
    # The one input role is reported for re-upload; its immutable snapshot is
    # verifiable and no path travelled.
    role = plan["reusable_inputs"][0]
    assert role["role"] == "sequence"
    assert role["files"][0]["reuse"] == "reupload_required"
    assert role["files"][0]["available"] is True
    serialized = json.dumps(plan)
    for secret in ("snapshot_path", "file_path", "snapshot_root", str(tmp_path)):
        assert secret not in serialized

    # Read-only: no Task was created and the source row is byte-identical.
    assert len(module.task_store.list_tasks()) == tasks_before
    _source_unchanged(module, source_id, before)


def test_a_schema_refresh_is_observed_when_the_reference_is_reopened(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    source_id = _create_source(module)
    created = module.app.test_client().post(
        f"/compute/api/tasks/{source_id}/clone-plan", headers=_test_client_auth(module)
    ).get_json()

    current, _runner = module.task_runtime._get_task_type(TASK)
    refreshed = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            # ``seed`` is renamed, ``mode`` narrows its enum, and a new bounded
            # default appears that the source never recorded.
            "seed_value": {"type": "integer", "default": 1, "minimum": 0, "maximum": 10},
            "enabled": {"type": "boolean", "default": True},
            "mode": {"type": "string", "enum": ["exact"], "default": "exact"},
            "label": {"type": "string", "default": "refreshed"},
        },
    }
    object.__setattr__(current, "schema", refreshed)

    response = module.app.test_client().get(
        f"/compute/api/clone-plans/{created['plan_id']}", headers=_test_client_auth(module)
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    plan = response.get_json()
    assert plan["target_schema_revision"] == clone_plan.schema_revision(refreshed)
    blocked = {item["field"]: item for item in plan["blocked_fields"]}
    assert blocked["seed"]["code"] == "parameter_removed"
    assert blocked["mode"]["code"] == "parameter_choice_unavailable"
    assert blocked["mode"]["recorded_value"] == "fast"
    parameters = {item["name"]: item for item in plan["compatible_parameters"]}
    assert parameters["seed_value"] == {"name": "seed_value", "value": "1", "source": "current_default"}
    assert parameters["label"]["source"] == "current_default"
    assert "mode" not in parameters


def test_a_dropped_role_and_a_changed_scientific_mode_are_reported(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    source_id = _create_source(module)
    form = json.loads(module.task_store.get_task(source_id)["input_form"])
    form["entities"].append(
        {
            "name": "ligand",
            "type": "file",
            "role": "ligand",
            "value": "ligand.sdf",
            "format": "sdf",
            "hash": "d" * 64,
            "size": 4,
            "snapshot_path": "",
        }
    )
    # A source that ran a scientific mode the current Task no longer declares.
    form["execution_graph"] = {"document": {"mode": "model_only"}}
    module.task_store.update_task(source_id, input_form=json.dumps(form))

    plan = module.app.test_client().post(
        f"/compute/api/tasks/{source_id}/clone-plan", headers=_test_client_auth(module)
    ).get_json()

    warnings = {item["code"]: item for item in plan["warnings"]}
    assert warnings["input_role_removed"]["field"] == "ligand"
    blocked = {item["field"]: item for item in plan["blocked_fields"]}
    assert blocked["execution_mode"]["code"] == "execution_mode_unavailable"
    assert blocked["execution_mode"]["recorded_value"] == "model_only"
    # Only the current roles are described; the dropped role is not offered.
    assert [role["role"] for role in plan["reusable_inputs"]] == ["sequence"]


def test_admin_sees_the_plan_but_may_not_copy_another_users_files(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    source_id = _create_source(module)

    admin = module.app.test_client().post(
        f"/compute/api/tasks/{source_id}/clone-plan", headers=_admin_client_auth(module)
    )
    assert admin.status_code == 201, admin.get_data(as_text=True)
    files = admin.get_json()["reusable_inputs"][0]["files"]
    assert files[0]["available"] is False
    assert files[0]["reason"] == "not_owner"

    # A different ordinary owner cannot learn that the Task exists.
    denied = module.app.test_client().post(
        f"/compute/api/tasks/{source_id}/clone-plan", headers=_test_client_auth(module, "other")
    )
    assert denied.status_code == 404


def test_an_expired_reference_or_a_deleted_source_is_unavailable(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    source_id = _create_source(module)
    module.app.config["CLONE_PLAN_TTL_SECONDS"] = -1
    expired = module.app.test_client().post(
        f"/compute/api/tasks/{source_id}/clone-plan", headers=_test_client_auth(module)
    ).get_json()
    response = module.app.test_client().get(
        f"/compute/api/clone-plans/{expired['plan_id']}", headers=_test_client_auth(module)
    )
    assert response.status_code == 404
    assert response.get_json()["details"][0]["code"] == "clone_plan_unavailable"

    module.app.config["CLONE_PLAN_TTL_SECONDS"] = 900
    live = module.app.test_client().post(
        f"/compute/api/tasks/{source_id}/clone-plan", headers=_test_client_auth(module)
    ).get_json()
    module.task_store.update_task(source_id, status="deleted:cancel")
    response = module.app.test_client().get(
        f"/compute/api/clone-plans/{live['plan_id']}", headers=_test_client_auth(module)
    )
    assert response.status_code == 404
    assert response.get_json()["details"][0]["code"] == "clone_source_unavailable"


def test_a_source_whose_method_left_the_catalog_blocks_the_draft(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    task_id = hashlib.md5(b"legacy-source", usedforsecurity=False).hexdigest()
    owner = _task_owner(module, "tester")
    form, _path = _source_input_form(module, task_id=task_id)
    module.task_store.upsert_task(
        task_id,
        filename="source.fasta",
        file_path="",
        uploaded_at=1_700_000_000.0,
        status="finished",
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username="tester",
        task_type="legacy_science",
        input_form=json.dumps(form),
        submitted_by_user_id=int(owner["submitted_by_user_id"]),
        storage_key=str(owner["storage_key"]),
        artifact_provenance="[]",
    )

    plan = module.app.test_client().post(
        f"/compute/api/tasks/{task_id}/clone-plan", headers=_test_client_auth(module)
    ).get_json()
    assert plan["target_task_type"] == "legacy_science"
    assert plan["target_schema_revision"] is None
    assert plan["compatible_parameters"] == []
    assert plan["reusable_inputs"] == []
    assert plan["can_submit"] is False
    codes = {item["code"] for item in plan["blocked_fields"]}
    # With no current schema every recorded parameter is also unavailable, and
    # both the missing method and the dropped fields are reported.
    assert "task_type_removed" in codes
    assert "parameter_removed" in codes


def test_an_unverifiable_snapshot_is_reported_not_offered(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    source_id = _create_source(module)
    form, path = _source_input_form(module, task_id=source_id, digest=False)
    module.task_store.update_task(source_id, input_form=json.dumps(form))
    assert path is not None and path.is_file()

    plan = module.app.test_client().post(
        f"/compute/api/tasks/{source_id}/clone-plan", headers=_test_client_auth(module)
    ).get_json()
    file = plan["reusable_inputs"][0]["files"][0]
    assert file["available"] is False
    assert file["reason"] == "record_invalid"
    assert file["sha256"] is None
    assert "input_snapshot_unavailable" in {item["code"] for item in plan["warnings"]}


def test_submit_records_cloned_from_and_only_then_creates_a_new_task(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    source_id = _create_source(module)
    before = module.task_store.get_task(source_id)
    monkeypatch.setattr(
        module.run_compute_task,
        "apply_async",
        lambda *args, **kwargs: SimpleNamespace(id="celery-clone"),
    )

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": TASK,
            "files": (io.BytesIO(b">draft\nACDEFGHIK\n"), "draft.fasta"),
            "input_roles": "sequence",
            "cloned_from": source_id,
            "params[seed]": "0",
            "params[enabled]": "false",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302, response.get_data(as_text=True)
    new_id = response.get_json()["task_id"]
    assert new_id != source_id
    task = module.task_store.get_task(new_id)
    assert task is not None
    assert json.loads(task["input_form"])["cloned_from"] == {"task_id": source_id, "task_type": TASK}
    assert before is not None
    _source_unchanged(module, source_id, before)


def test_repeating_the_same_clone_submission_returns_the_same_task(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    source_id = _create_source(module)
    monkeypatch.setattr(
        module.run_compute_task,
        "apply_async",
        lambda *args, **kwargs: SimpleNamespace(id="celery-clone"),
    )
    payload = {
        "task_type": TASK,
        "files": (io.BytesIO(b">draft\nACDEFGHIK\n"), "draft.fasta"),
        "input_roles": "sequence",
        "cloned_from": source_id,
        "params[seed]": "0",
        "params[enabled]": "false",
    }
    client = module.app.test_client()
    first = client.post(
        "/compute/api/post", headers=_test_client_auth(module), data=payload, content_type="multipart/form-data"
    )
    assert first.status_code == 302, first.get_data(as_text=True)
    task_id = first.get_json()["task_id"]

    retry = client.post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={**payload, "files": (io.BytesIO(b">draft\nACDEFGHIK\n"), "draft.fasta")},
        content_type="multipart/form-data",
    )
    assert retry.status_code in {202, 302, 409}, retry.get_data(as_text=True)
    assert retry.get_json()["task_id"] == task_id
    matching = [task for task in module.task_store.list_tasks() if task["md5sum"] == task_id]
    assert len(matching) == 1


def test_a_malformed_cloned_from_is_refused_before_any_upload(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    response = module.app.test_client().post(
        "/compute/api/preflight/" + TASK,
        headers=_test_client_auth(module),
        data={
            "task_type": TASK,
            "files": (io.BytesIO(b">draft\nACDEFGHIK\n"), "draft.fasta"),
            "input_roles": "sequence",
            "cloned_from": "not-a-task-id",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    fields = {item["field"] for item in response.get_json()["errors"]}
    assert any("cloned_from" in field for field in fields)


def test_a_parameter_conditioned_role_uses_its_effective_cardinality():
    role = {
        "id": "ligand",
        "cardinality": {"min": 0, "max": 2},
        "presence": {
            "parameter": "mode",
            "required_when": ["with_ligand"],
            "forbidden_when": ["protein_only"],
        },
    }
    # A role the current settings forbid is not reported as required, and one
    # those settings require is, before any file is uploaded.
    assert clone_plan._effective_cardinality(role, {"mode": "with_ligand"}) == (1, 2)
    assert clone_plan._effective_cardinality(role, {"mode": "protein_only"}) == (0, 0)
    assert clone_plan._effective_cardinality(role, {}) == (0, 2)


def test_provenance_naming_an_unavailable_source_is_refused(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    monkeypatch.setattr(
        module.run_compute_task,
        "apply_async",
        lambda *args, **kwargs: SimpleNamespace(id="celery-clone"),
    )
    tasks_before = module.task_store.list_tasks()

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": TASK,
            "files": (io.BytesIO(b">draft\nACDEFGHIK\n"), "draft.fasta"),
            "input_roles": "sequence",
            "cloned_from": "0" * 32,
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 404
    assert response.get_json()["details"][0]["code"] == "clone_source_unavailable"
    assert module.task_store.list_tasks() == tasks_before
