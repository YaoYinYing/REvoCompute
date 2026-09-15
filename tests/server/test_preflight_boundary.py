# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import io
import json
import ntpath
import random
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


def test_runner_owned_workspace_code_runs_only_after_core_file_security(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "ENABLED_TASKRUNNERS": "placer-rfdiffusion",
        },
    )
    auth_header = _test_client_auth(module)
    user = module.app.config["user_db"].get_user_by_username("tester")
    module.app.config["user_db"].update_user(user["id"], allow_gpu_use=True)
    calls: list[object] = []

    def runner_normalizer(value):
        calls.append(value)
        return {"params": {}, "state": {}, "summary": "normalized"}

    submission_view = module.app.view_functions["upload_file"]
    while "workspace_backend" not in submission_view.__globals__:
        submission_view = submission_view.__wrapped__
    route_globals = submission_view.__globals__
    real_workspace_backend = route_globals["workspace_backend"]
    monkeypatch.setitem(
        route_globals,
        "workspace_backend",
        lambda identifier: (
            (runner_normalizer, None)
            if identifier == "rfdiffusion-regions"
            else real_workspace_backend(identifier)
        ),
    )
    queued: list[bool] = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=auth_header,
        data={
            "task_type": "rfdiffusion",
            "workspace": json.dumps(
                {
                    "version": 2,
                    "capabilities": {
                        "design_regions": {
                            "mode": "motif_scaffolding",
                            "segments": [{"kind": "fixed", "chain": "A", "start": 1, "end": 1}],
                            "hotspots": [],
                        }
                    },
                }
            ),
            "files": (io.BytesIO(b"not a structure\n"), "hostile.pdb"),
            "input_roles": "structure",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_format_invalid"
    assert calls == []
    assert module.task_store.list_tasks() == []
    assert queued == []


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
    module.task_store.require_gpu_authorization(user["id"])


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


def test_user_concurrency_policy_blocks_preflight_without_side_effects(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    headers = _test_client_auth(module)
    user = module.app.config["user_db"].get_user_by_username("tester")
    now = 1_789_499_000.0
    for index in range(5):
        module.task_store.upsert_task(
            f"{index + 1:032x}",
            filename="existing.fasta",
            file_path="/immutable/existing.fasta",
            uploaded_at=now + index,
            status="queued",
            is_binary=0,
            username=user["username"],
            submitted_by_user_id=user["id"],
            storage_key=user["storage_key"],
            task_type="gremlin",
        )
    before = module.task_store.list_tasks()
    queued = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))

    response = module.app.test_client().post(
        "/compute/api/preflight/gremlin",
        headers=headers,
        data={
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 429
    assert "Too many pending or running tasks" in response.get_data(as_text=True)
    assert module.task_store.list_tasks() == before
    assert queued == []


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
        ".hidden.fasta",
        "safe/.hidden.fasta",
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


def test_path_normalization_has_safe_properties_for_bounded_generated_inputs(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    route = module.app.view_functions["upload_file"]
    while hasattr(route, "__wrapped__"):
        route = route.__wrapped__
    normalize = route.__globals__["_safe_input_relative_path"]
    generator = random.Random(20260916)
    alphabet = "abcXYZ019._-%/\\ \x01\x7f"

    for _ in range(500):
        candidate = "".join(generator.choice(alphabet) for _ in range(generator.randint(0, 80)))
        normalized = normalize(candidate)
        if normalized is None:
            continue
        drive, _tail = ntpath.splitdrive(normalized)
        parts = normalized.split("/")
        assert not drive
        assert not normalized.startswith("/")
        assert "\\" not in normalized
        assert all(part and part not in {".", ".."} and not part.startswith(".") for part in parts)
        assert all(32 <= ord(character) < 127 for character in normalized)


def test_file_count_limit_fails_before_quarantine_or_queue(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    base, runner = module.task_runtime._get_task_type("gremlin")
    module.task_runtime._register_tt(
        replace(
            base,
            name="multi_fasta",
            inputs=(TaskInputRole("sequence", "Sequence", "protein_sequence", ("fasta",), 1, 2),),
            params=(),
        ),
        runner,
    )
    module.app.config["MAX_INPUT_FILES"] = 1
    queued = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))

    response = module.app.test_client().post(
        "/compute/api/preflight/multi_fasta",
        headers=_test_client_auth(module),
        data={
            "files": [
                (io.BytesIO(b">one\nACDE\n"), "one.fasta"),
                (io.BytesIO(b">two\nFGHI\n"), "two.fasta"),
            ],
            "input_roles": ["sequence", "sequence"],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["errors"][0]["code"] == "input_file_count_limit"
    assert module.task_store.list_tasks() == []
    assert queued == []
    assert not list(Path(module.app.config["UPLOAD_FOLDER"]).glob(".tmp_*"))


@pytest.mark.parametrize(
    ("per_file_limit", "total_limit", "payloads", "code"),
    [
        (8, 64, [b">one\nACDEFGH\n"], "input_file_size_limit"),
        (64, 19, [b">one\nACDE\n", b">two\nFGHI\n"], "input_total_size_limit"),
    ],
)
def test_upload_byte_limits_remove_quarantine_and_never_queue(
    monkeypatch, tmp_path, per_file_limit, total_limit, payloads, code
):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    base, runner = module.task_runtime._get_task_type("gremlin")
    module.task_runtime._register_tt(
        replace(
            base,
            name="bounded_fasta",
            inputs=(TaskInputRole("sequence", "Sequence", "protein_sequence", ("fasta",), 1, 2),),
            params=(),
        ),
        runner,
    )
    module.app.config["MAX_INPUT_FILE_BYTES"] = per_file_limit
    module.app.config["MAX_INPUT_TOTAL_BYTES"] = total_limit
    queued = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))

    response = module.app.test_client().post(
        "/compute/api/preflight/bounded_fasta",
        headers=_test_client_auth(module),
        data={
            "files": [(io.BytesIO(payload), f"input-{index}.fasta") for index, payload in enumerate(payloads)],
            "input_roles": ["sequence"] * len(payloads),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["errors"][0]["code"] == code
    assert module.task_store.list_tasks() == []
    assert queued == []
    assert not list(Path(module.app.config["UPLOAD_FOLDER"]).glob(".tmp_*"))


@pytest.mark.parametrize("endpoint", ["/compute/api/preflight/gremlin", "/compute/api/post"])
def test_request_body_limit_is_structured_and_has_no_side_effects(monkeypatch, tmp_path, endpoint):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    module.app.config["MAX_CONTENT_LENGTH"] = 256
    queued = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))

    response = module.app.test_client().post(
        endpoint,
        headers=_test_client_auth(module),
        data={
            "task_type": "gremlin",
            "files": (io.BytesIO(b">sequence\n" + b"A" * 512 + b"\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    payload = response.get_json()
    findings = payload["errors"] if "preflight" in endpoint else payload["details"]
    assert findings[0]["code"] == "request_size_limit"
    if "preflight" in endpoint:
        assert payload["security"] == {"status": "failed"}
        assert payload["contract"] == {"status": "not_checked"}
    assert module.task_store.list_tasks() == []
    assert queued == []
    assert not list(Path(module.app.config["UPLOAD_FOLDER"]).glob(".tmp_*"))


def test_generated_jaag_json_uses_the_same_core_security_profile(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    base, runner = module.task_runtime._get_task_type("gremlin")
    module.task_runtime._register_tt(
        replace(
            base,
            name="generated_af3",
            inputs=(
                TaskInputRole(
                    "specification",
                    "Specification",
                    "alphafold3_specification",
                    ("json",),
                    1,
                    1,
                ),
            ),
            params=(),
        ),
        runner,
    )
    queued = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))
    generated = {
        "name": "unsafe",
        "modelSeeds": [1],
        "sequences": [{"protein": {"id": "A", "sequence": "ACDE", "unpairedMsaPath": "/etc/passwd"}}],
        "dialect": "alphafold3",
        "version": 1,
    }

    response = module.app.test_client().post(
        "/compute/api/preflight/generated_af3",
        headers=_test_client_auth(module),
        data={
            "files": (io.BytesIO(json.dumps(generated).encode()), "jaag-alphafold3.json"),
            "input_roles": "specification",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["errors"][0]["code"] == "input_logical_type_invalid"
    assert module.task_store.list_tasks() == []
    assert queued == []
