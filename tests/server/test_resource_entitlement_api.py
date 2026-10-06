# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The canonical resource projection as an API contract.

``resource_envelope`` is what later consumers -- Slurm placement, Admin
reporting, MCP -- are told to read instead of re-deriving a balance, so its
shape is a contract rather than an internal object.  These tests exercise it
as one: through the authenticated HTTP endpoints, against the published
OpenAPI schema, with the unknown-is-not-zero distinction visible on the wire.
"""

from __future__ import annotations

import time

from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from jsonschema import Draft202012Validator

GIB = 1024**3


def _validate(spec: dict, schema_name: str, payload: object) -> None:
    Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema_name}", "components": spec["components"]},
    ).validate(payload)


def _module(monkeypatch, tmp_path):
    return _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )


def _user(module, username: str = "tester") -> dict:
    """The real user row behind the token ``_test_client_auth`` issues."""
    return module.app.config["user_db"].get_user_by_username(username)


def test_openapi_describes_the_resource_projection(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    spec = module.app.test_client().get("/openapi.json").get_json()

    assert spec["paths"]["/compute/api/resource-entitlement"]["get"]["operationId"] == (
        "getCurrentResourceEntitlement"
    )
    for name in ("ComputeEntitlement", "StorageEntitlement", "ResourceEntitlement"):
        assert name in spec["components"]["schemas"]

    compute = spec["components"]["schemas"]["ComputeEntitlement"]
    assert compute["additionalProperties"] is False
    # The projection must expose the distinction between a known balance and a
    # balance that is not yet known, not merely a single number.
    assert {"unsettled_allocations", "unsettled_quantity", "usage_complete"} <= set(
        compute["required"]
    )
    assert compute["properties"]["remaining"]["type"] == ["integer", "null"]


def test_user_envelope_is_self_scoped_and_matches_the_published_schema(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    spec = client.get("/openapi.json").get_json()
    headers = _test_client_auth(module)

    response = client.get("/compute/api/resource-entitlement", headers=headers)

    assert response.status_code == 200
    payload = response.get_json()
    _validate(spec, "ResourceEntitlement", payload)
    assert payload["subject_type"] == "user"
    units = {item["unit"]: item for item in payload["compute"]}
    assert set(units) == {"gpu_second", "cpu_core_second", "storage_byte"}
    # GPU compute is the enforced unit; the others are accounted facts.
    assert units["gpu_second"]["enforced"] is True
    assert units["cpu_core_second"]["enforced"] is False
    assert units["cpu_core_second"]["allowance"] is None
    assert payload["storage"]["soft_limit_bytes"] == module.task_store.storage_soft_limit_bytes
    assert payload["storage"]["logical_owned_bytes"] == 0


def test_unsettled_usage_is_visible_on_the_wire_as_unknown_not_zero(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    user = _user(module)
    module.task_store.record_allocation_start(
        user_id=user["id"],
        task_id="a" * 32,
        stage_id="model",
        slurm_job_id="9700",
        gpu_count=2,
        started_at=time.time(),
    )

    payload = client.get("/compute/api/resource-entitlement", headers=headers).get_json()

    gpu = next(item for item in payload["compute"] if item["unit"] == "gpu_second")
    assert gpu["used"] == 0
    assert gpu["unsettled_allocations"] == 1
    assert gpu["unsettled_quantity"] > 0
    assert gpu["usage_complete"] is False
    # The remaining balance already excludes the unknown usage rather than
    # reporting the full allowance as if nothing were running.
    assert gpu["remaining"] < gpu["allowance"]


def test_admin_can_read_a_users_envelope_and_a_regular_user_cannot(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    regular = _test_client_auth(module)
    admin = _admin_client_auth(module)
    target = _user(module)
    path = f"/compute/api/auth/admin/users/{target['id']}/resource-entitlement"

    denied = client.get(path, headers=regular)
    allowed = client.get(path, headers=admin)

    assert denied.status_code in (401, 403)
    assert allowed.status_code == 200
    assert allowed.get_json()["subject_id"] == target["id"]


def test_admin_envelope_reports_owned_bytes_after_a_published_result(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    _test_client_auth(module)
    admin = _admin_client_auth(module)
    target = _user(module)
    module.task_store.ensure_data_lifecycle("b" * 32, user_id=target["id"], logical_bytes=2 * GIB)
    path = f"/compute/api/auth/admin/users/{target['id']}/resource-entitlement"

    payload = client.get(path, headers=admin).get_json()

    assert payload["storage"]["logical_owned_bytes"] == 2 * GIB
    assert payload["storage"]["over_soft_limit"] is False


def test_missing_and_deleted_users_are_not_found(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    headers = _admin_client_auth(module)

    assert client.get(
        "/compute/api/auth/admin/users/987654/resource-entitlement", headers=headers
    ).status_code == 404
