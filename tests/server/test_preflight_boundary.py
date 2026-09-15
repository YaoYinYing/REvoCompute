# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import _load_pssm_module, _test_client_auth
from revocompute.task_types import TaskInputRole


@pytest.mark.parametrize("endpoint", ["/compute/api/post", "/compute/api/preflight/pdb_only"])
def test_security_rejection_has_no_durable_or_queue_side_effects(monkeypatch, tmp_path, endpoint):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    base, runner = module.task_runtime._get_task_type("gremlin")
    module.task_runtime._register_tt(
        replace(
            base,
            name="pdb_only",
            inputs=(TaskInputRole("structure", "Structure", "protein_structure", ("pdb",), 1, 2),),
            params=(),
        ),
        runner,
    )
    queued: list[bool] = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))
    roots = [Path(module.app.config[key]) for key in ("UPLOAD_FOLDER", "WORKSPACE_FOLDER", "RESULTS_FOLDER")]
    before = {root: sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file()) for root in roots}

    response = module.app.test_client().post(
        endpoint,
        headers=_test_client_auth(module),
        data={
            "task_type": "pdb_only",
            "files": [
                (io.BytesIO(b"ATOM      1  CA  ALA A   1\n"), "valid.pdb"),
                (io.BytesIO(b"this is not a pdb\n"), "hostile.pdb"),
            ],
            "input_roles": ["structure", "structure"],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    if "preflight" in endpoint:
        payload = response.get_json()
        assert payload["valid"] is False
        assert payload["security"] == {"status": "failed"}
        assert payload["contract"] == {"status": "not_checked"}
        assert payload["admission"] == {"allowed": False}
        assert payload["errors"][0] == {
            "blocking": True,
            "code": "input_format_invalid",
            "format": "pdb",
            "message": "PDB file must contain ATOM, HETATM, or END records near the start",
            "path": "hostile.pdb",
            "role": "structure",
        }
    assert module.task_store.list_tasks() == []
    assert queued == []
    assert {
        root: sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file()) for root in roots
    } == before


def test_read_only_preflight_reuses_validation_without_side_effects(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    queued: list[bool] = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))
    roots = [Path(module.app.config[key]) for key in ("UPLOAD_FOLDER", "WORKSPACE_FOLDER", "RESULTS_FOLDER")]
    before = {root: sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file()) for root in roots}

    response = module.app.test_client().post(
        "/compute/api/preflight/gremlin",
        headers=_test_client_auth(module),
        data={
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload.pop("normalized_params")["iter"] == 100
    assert payload == {
        "admission": {"allowed": True},
        "contract": {"status": "passed"},
        "errors": [],
        "inputs": [{"format": "fasta", "path": "sequence.fasta", "role": "sequence"}],
        "security": {"status": "passed"},
        "valid": True,
        "warnings": [],
    }
    assert module.task_store.list_tasks() == []
    assert queued == []
    assert {
        root: sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file()) for root in roots
    } == before


def test_preflight_classifies_contract_rejection(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    response = module.app.test_client().post(
        "/compute/api/preflight/gremlin",
        headers=_test_client_auth(module),
        data={
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "unknown",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["contract"] == {"status": "failed"}
    assert response.get_json()["errors"][0]["code"] == "input_role_unknown"


def test_preflight_classifies_admission_denial(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "ENABLED_TASKRUNNERS": "gnina",
        },
    )
    response = module.app.test_client().post(
        "/compute/api/preflight/gnina",
        headers=_test_client_auth(module),
    )

    assert response.status_code == 403
    assert response.get_json()["admission"] == {"allowed": False}
    assert response.get_json()["errors"][0]["code"] == "admission_denied"


@pytest.mark.parametrize("endpoint", ["/compute/api/preflight/gremlin", "/compute/api/post"])
def test_infrastructure_rejection_runs_after_security_and_leaves_no_durable_task(monkeypatch, tmp_path, endpoint):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.app.config["manage_db"].resource_set("slurm_enabled", "true")
    route = module.app.view_functions["upload_file"]
    while hasattr(route, "__wrapped__"):
        route = route.__wrapped__
    monkeypatch.setitem(
        route.__globals__,
        "resolve_submission_readiness",
        lambda *_args: SimpleNamespace(ready=True),
    )
    queued = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))
    upload_root = Path(module.app.config["UPLOAD_FOLDER"])
    observed_quarantine = []

    class UnavailableInfrastructure:
        def report(self):
            observed_quarantine.extend(upload_root.glob(".tmp_*"))
            return {"status": "UNAVAILABLE", "stale": False, "summary": {}}

    module.app.config["infrastructure_readiness"] = UnavailableInfrastructure()

    response = module.app.test_client().post(
        endpoint,
        headers=_test_client_auth(module),
        data={
            "task_type": "gremlin",
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 503
    if "preflight" in endpoint:
        payload = response.get_json()
        assert payload["admission"] == {"allowed": False}
        assert payload["errors"][0]["code"] == "infrastructure_unavailable"
    assert observed_quarantine
    assert not list(upload_root.glob(".tmp_*"))
    assert module.task_store.list_tasks() == []
    assert queued == []


def test_preflight_projects_degraded_readiness_and_busy_capacity_without_blocking(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.app.config["manage_db"].resource_set("slurm_enabled", "true")
    route = module.app.view_functions["upload_file"]
    while hasattr(route, "__wrapped__"):
        route = route.__wrapped__
    monkeypatch.setitem(
        route.__globals__,
        "resolve_submission_readiness",
        lambda *_args: SimpleNamespace(ready=True),
    )
    module.app.config["infrastructure_readiness"] = SimpleNamespace(
        report=lambda: {
            "status": "DEGRADED",
            "stale": False,
            "summary": {
                "scheduler": {"capacity": "BUSY"},
                "gpu": {"capacity": "BUSY"},
            },
        }
    )

    response = module.app.test_client().post(
        "/compute/api/preflight/gremlin",
        headers=_test_client_auth(module),
        data={
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["admission"] == {
        "allowed": True,
        "gpu_capacity": "BUSY",
        "infrastructure_ready": True,
        "infrastructure_stale": False,
        "infrastructure_status": "DEGRADED",
        "runner_ready": True,
        "scheduler_capacity": "BUSY",
    }


def _register_gpu_test_type(module):
    base, runner = module.task_runtime._get_task_type("gremlin")
    module.task_runtime._register_tt(replace(base, name="gpu_test", gpus=True), runner)


@pytest.mark.parametrize("endpoint", ["/compute/api/preflight/gpu_test", "/compute/api/post"])
def test_exhausted_gpu_credit_fails_after_security_without_durable_side_effects(monkeypatch, tmp_path, endpoint):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    _register_gpu_test_type(module)
    headers = _test_client_auth(module)
    user = module.app.config["user_db"].get_user_by_username("tester")
    module.app.config["user_db"].update_user(user["id"], allow_gpu_use=True)
    module.task_store.adjust_gpu_credit(
        user_id=user["id"],
        gpu_seconds=-60_000,
        actor_user_id=user["id"],
        reason="Test exhaustion",
        idempotency_key="exhaust",
    )
    queued = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))

    response = module.app.test_client().post(
        endpoint,
        headers=headers,
        data={
            "task_type": "gpu_test",
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 403
    if "preflight" in endpoint:
        assert response.get_json()["errors"][0]["code"] == "gpu_credit_exhausted"
    assert module.task_store.list_tasks() == []
    assert queued == []
    assert not list(Path(module.app.config["UPLOAD_FOLDER"]).glob(".tmp_*"))


def test_gpu_preflight_reports_credit_without_consuming_it(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    _register_gpu_test_type(module)
    headers = _test_client_auth(module)
    user = module.app.config["user_db"].get_user_by_username("tester")
    module.app.config["user_db"].update_user(user["id"], allow_gpu_use=True)

    response = module.app.test_client().post(
        "/compute/api/preflight/gpu_test",
        headers=headers,
        data={
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["admission"]["gpu_credit_sufficient"] is True
    assert response.get_json()["admission"]["gpu_credit_remaining_seconds"] == 60_000
    assert module.task_store.gpu_credit_summary(user["id"])["remaining_gpu_seconds"] == 60_000


def test_cpu_preflight_is_accepted_with_exhausted_gpu_credit(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    headers = _test_client_auth(module)
    user = module.app.config["user_db"].get_user_by_username("tester")
    module.task_store.adjust_gpu_credit(
        user_id=user["id"],
        gpu_seconds=-60_000,
        actor_user_id=user["id"],
        reason="Test exhaustion",
        idempotency_key="cpu-still-allowed",
    )

    response = module.app.test_client().post(
        "/compute/api/preflight/gremlin",
        headers=headers,
        data={
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert "gpu_credit_sufficient" not in response.get_json()["admission"]


@pytest.mark.parametrize(
    "hostile_path",
    [
        "../../etc/passwd.fasta",
        "nested/../../../etc/passwd.fasta",
        "/etc/passwd.fasta",
        "C:\\Windows\\system32\\evil.fasta",
        "\\\\server\\share\\evil.fasta",
        "safe/..\\evil.fasta",
        "safe//evil.fasta",
        "safe/./evil.fasta",
        "safe/%2e%2e/evil.fasta",
        "．．/evil.fasta",
        "evil\x01.fasta",
    ],
)
def test_adversarial_input_paths_fail_before_quarantine_or_queue(monkeypatch, tmp_path, hostile_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    queued = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))

    response = module.app.test_client().post(
        "/compute/api/preflight/gremlin",
        headers=_test_client_auth(module),
        data={
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
            "input_paths": hostile_path,
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["errors"][0]["code"] == "input_path_invalid"
    assert module.task_store.list_tasks() == []
    assert queued == []
    assert not list(Path(module.app.config["UPLOAD_FOLDER"]).glob(".tmp_*"))


def test_path_policy_rejects_nul_before_multipart_storage(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    route = module.app.view_functions["upload_file"]
    while hasattr(route, "__wrapped__"):
        route = route.__wrapped__

    assert route.__globals__["_safe_input_relative_path"]("safe\x00evil.fasta") is None
