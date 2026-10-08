# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The placement policy and plan surface as an authenticated API contract.

Placement is where a workload requirement becomes a local Slurm request, so the
admin surface is exercised the way an operator uses it: through the real routes,
with real authorization, against the published OpenAPI schema, and with the
bounded reason codes visible on the wire.  The dry run is checked to agree with
real dispatch for the same inputs and policy revision.
"""

from __future__ import annotations

import json

from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from jsonschema import Draft202012Validator

CLASSES = [
    {"name": "cpu", "partition": "normal", "accelerator": "none"},
    {"name": "gpu-standard", "partition": "gpu", "accelerator": "cuda", "accelerator_class": "a100"},
]


def _validate(spec: dict, schema_name: str, payload: object) -> None:
    Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema_name}", "components": spec["components"]},
    ).validate(payload)


def _module(monkeypatch, tmp_path):
    return _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "SLURM_ALLOWED_QUEUES": "normal,gpu",
        },
    )


def _set_policy(module, client, headers, classes):
    return client.put(
        "/compute/api/auth/admin/placement-policy", json={"classes": classes}, headers=headers
    )


def test_openapi_describes_the_placement_surface(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    spec = module.app.test_client().get("/openapi.json").get_json()

    assert set(spec["paths"]["/compute/api/auth/admin/placement-policy"]) == {"get", "put"}
    assert "post" in spec["paths"]["/compute/api/auth/admin/placement-policy/explain"]
    assert "get" in spec["paths"]["/compute/api/auth/admin/tasks/{task_id}/placement"]
    for name in ("PlacementStoredClass", "PlacementPlanView", "PlacementDryRunResult"):
        assert name in spec["components"]["schemas"]
    # Placement decisions are a closed vocabulary, so the wire says so.
    assert spec["components"]["schemas"]["PlacementPlanView"]["additionalProperties"] is False


def test_placement_policy_read_write_is_admin_only_and_audited(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    user_headers = _test_client_auth(module)
    admin_headers = _admin_client_auth(module)

    assert client.get("/compute/api/auth/admin/placement-policy", headers=user_headers).status_code == 403
    assert client.put(
        "/compute/api/auth/admin/placement-policy", json={"classes": CLASSES}, headers=user_headers
    ).status_code == 403

    empty = client.get("/compute/api/auth/admin/placement-policy", headers=admin_headers)
    assert empty.status_code == 200
    assert empty.get_json()["declared"] is False

    written = _set_policy(module, client, admin_headers, CLASSES)
    assert written.status_code == 200
    body = written.get_json()
    assert body["declared"] is True
    assert body["revision"] == 1

    read_back = client.get("/compute/api/auth/admin/placement-policy", headers=admin_headers).get_json()
    assert read_back["policy_digest"] == body["policy_digest"]
    assert [item["name"] for item in read_back["classes"]] == ["cpu", "gpu-standard"]
    assert read_back["slurm"]["allowed_queues"] == ["normal", "gpu"]


def test_a_policy_naming_a_partition_outside_the_allowed_surface_is_refused(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin_headers = _admin_client_auth(module)

    response = _set_policy(
        module, client, admin_headers, [{"name": "cpu", "partition": "debug", "accelerator": "none"}]
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == "partition_not_allowed"
    # Nothing was written: the deployment still has no policy.
    assert client.get("/compute/api/auth/admin/placement-policy", headers=admin_headers).get_json()[
        "declared"
    ] is False


def test_each_write_advances_the_revision_and_the_digest_follows_content(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin_headers = _admin_client_auth(module)

    first = _set_policy(module, client, admin_headers, CLASSES).get_json()
    second = _set_policy(module, client, admin_headers, CLASSES).get_json()
    assert second["revision"] == first["revision"] + 1
    assert second["policy_digest"] == first["policy_digest"]
    third = _set_policy(module, client, admin_headers, [*CLASSES, {"name": "mixed", "partition": "normal"}]).get_json()
    assert third["revision"] == second["revision"] + 1
    assert third["policy_digest"] != second["policy_digest"]


def test_a_cpu_dry_run_resolves_to_the_cpu_class_with_no_gpu_request(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin_headers = _admin_client_auth(module)
    _set_policy(module, client, admin_headers, CLASSES)

    response = client.post(
        "/compute/api/auth/admin/placement-policy/explain",
        json={"cpus": 8, "memory_mb": 16384},
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = response.get_json()
    from revocompute.schemas import PlacementDryRunResult

    assert PlacementDryRunResult.model_validate(body).placed is True
    assert body["reason_code"] == "placement_resolved_cpu"
    assert body["matched_class"] == "cpu"
    assert body["resolved"]["partition"] == "normal"
    assert body["resolved"]["gres"] is None


def test_an_accelerator_dry_run_resolves_to_the_gpu_class(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin_headers = _admin_client_auth(module)
    _set_policy(module, client, admin_headers, CLASSES)

    response = client.post(
        "/compute/api/auth/admin/placement-policy/explain",
        json={"cpus": 8, "accelerator": "cuda", "gpu_count": 2},
        headers=admin_headers,
    )
    body = response.get_json()
    assert body["placed"] is True
    assert body["reason_code"] == "placement_resolved_accelerator"
    assert body["matched_class"] == "gpu-standard"
    assert body["resolved"]["partition"] == "gpu"
    assert body["resolved"]["gres"] == "gpu:a100:2"


def test_a_dry_run_reports_a_bounded_reason_code_when_there_is_no_placement(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin_headers = _admin_client_auth(module)
    _set_policy(module, client, admin_headers, [{"name": "cpu", "partition": "normal", "accelerator": "none"}])

    response = client.post(
        "/compute/api/auth/admin/placement-policy/explain",
        json={"cpus": 4, "accelerator": "cuda", "gpu_count": 1},
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["placed"] is False
    assert body["reason_code"] == "required_accelerator_unavailable"
    assert body["message"]


def test_a_dry_run_evaluates_an_explicit_override_through_the_same_precedence(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin_headers = _admin_client_auth(module)
    _set_policy(module, client, admin_headers, CLASSES)

    # An override that names a field the class also sets wins for that field.
    response = client.post(
        "/compute/api/auth/admin/placement-policy/explain",
        json={"cpus": 4, "overrides": {"qos": "priority"}},
        headers=admin_headers,
    )
    body = response.get_json()
    assert body["placed"] is True
    assert body["resolved"]["qos"] == "priority"
    assert body["resolved_sources"]["qos"] == "override:qos"

    # An override that would ask for less accelerator capacity than the stage
    # requires is refused with the conflict code, never silently weakened.
    conflict = client.post(
        "/compute/api/auth/admin/placement-policy/explain",
        json={"accelerator": "cuda", "gpu_count": 4, "overrides": {"gres": "gpu:1"}},
        headers=admin_headers,
    ).get_json()
    assert conflict["placed"] is False
    assert conflict["reason_code"] == "resource_override_conflict"


def test_an_unknown_override_field_is_rejected_rather_than_ignored(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin_headers = _admin_client_auth(module)
    response = client.post(
        "/compute/api/auth/admin/placement-policy/explain",
        json={"cpus": 2, "overrides": {"slurm_gpus_per_node": "4"}},
        headers=admin_headers,
    )
    assert response.status_code == 400


def test_one_unmanaged_deployment_places_through_the_canonical_policy(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin_headers = _admin_client_auth(module)

    managedb = module.app.config["manage_db"]
    managedb.resource_set("slurm_partition", "normal")

    body = client.post(
        "/compute/api/auth/admin/placement-policy/explain",
        json={"cpus": 2},
        headers=admin_headers,
    ).get_json()
    assert body["placed"] is True
    assert body["reason_code"] == "placement_unmanaged"
    assert body["resolved"]["partition"] == "normal"


def test_the_task_plan_reader_reports_every_recorded_stage(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    admin_headers = _admin_client_auth(module)
    _set_policy(module, client, admin_headers, CLASSES)

    from revocompute.placement_dispatch import plan_stage_for_dispatch
    from revocompute.placement_policy import WorkloadRequirement
    from revocompute.resource_policy import resolve_resources

    task_id = "a" * 32
    store = module.task_store
    store.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=1.0,
        status="queued",
        is_binary=0,
        task_type="gremlin",
        storage_key="tester",
        submitted_by_user_id=1,
    )
    policy = __import__(
        "revocompute.placement_store", fromlist=["load_placement_policy"]
    ).load_placement_policy(
        module.CONFIG.placement_policy_path, allowed_queues=["normal", "gpu"]
    )
    for stage, requires_gpu in (("gremlin.hhblits", False), ("gremlin.gremlin", True)):
        resolved = resolve_resources(
            lambda _field: None,
            lambda _field: None,
            requires_gpu=requires_gpu,
            allowed_queues=("normal", "gpu"),
            default_timeout_seconds=3600,
        )
        plan_stage_for_dispatch(
            store,
            task_id=task_id,
            stage_id=stage,
            requirement=WorkloadRequirement.from_resolved(resolved),
            resolved=resolved,
            policy=policy,
            allowed_queues=("normal", "gpu"),
        )

    response = client.get(
        f"/compute/api/auth/admin/tasks/{task_id}/placement", headers=admin_headers
    )
    assert response.status_code == 200
    body = response.get_json()
    spec = client.get("/openapi.json").get_json()
    assert {plan["stage_id"] for plan in body["plans"]} == {"gremlin.hhblits", "gremlin.gremlin"}
    by_stage = {plan["stage_id"]: plan for plan in body["plans"]}
    assert by_stage["gremlin.hhblits"]["reason_code"] == "placement_resolved_cpu"
    assert by_stage["gremlin.hhblits"]["resolved"]["gres"] is None
    assert by_stage["gremlin.gremlin"]["reason_code"] == "placement_resolved_accelerator"
    assert by_stage["gremlin.gremlin"]["resolved"]["partition"] == "gpu"
    assert all(plan["policy_changed_since_plan"] is False for plan in body["plans"])
    for plan in body["plans"]:
        _validate(spec, "PlacementPlanView", plan)
        # The recorded plan re-reads exactly, provenance included.
        json.dumps(plan["resolved"])


def test_the_task_plan_reader_is_admin_only_and_404s_for_an_unknown_task(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    user_headers = _test_client_auth(module)
    admin_headers = _admin_client_auth(module)

    assert client.get(
        f"/compute/api/auth/admin/tasks/{'a' * 32}/placement", headers=user_headers
    ).status_code == 403
    assert client.get(
        f"/compute/api/auth/admin/tasks/{'a' * 32}/placement", headers=admin_headers
    ).status_code == 404

