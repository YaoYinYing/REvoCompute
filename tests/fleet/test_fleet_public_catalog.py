# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The anonymous public catalog must not leak host mounts or entitlement identity.

An unauthenticated visitor can read both the method catalog and a single method's
detail projection.  A restricted family appears there, but only as an opaque
access gate: it must carry ``restricted``/``granted`` and nothing that names the
host filesystem (the runner.yaml ``mounts`` host paths), the access-policy
identifier, or the entitlement list the policy ``requires``.  Those belong to
the runner's scheduled process and the authenticated access flow, not to the
public catalog.

The projection source is the real installed fleet, so the test discovers the
runners the same way production does rather than through a fixture-shaped copy.
"""

from __future__ import annotations

import json

from conftest import _load_fleet_module

# The restricted GPU family the frontend projection suite already leans on; the
# invariant is general, this is just the concrete family that declares an access
# policy and operator-managed host mounts.
RESTRICTED_FAMILY = "alphafold3"

# Host paths declared in that family's runner.yaml ``mounts``.  Hard-coding the
# paths keeps the assertion meaningful even if a future edit drops a mount: the
# leak would then be a name the operator host actually uses.
HOST_MOUNT_PATHS = ("/mnt/db", "/mnt/alphafold3")


def test_anonymous_catalog_does_not_expose_mounts_or_entitlements(monkeypatch, tmp_path):
    module = _load_fleet_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()

    catalog = client.get("/compute/api/types")
    assert catalog.status_code == 200
    summary = next(task for task in catalog.get_json()["task_types"] if task["name"] == RESTRICTED_FAMILY)
    serialized = json.dumps(summary)

    assert summary["access"]["restricted"] is True
    assert summary["access"]["granted"] is False
    assert summary["access"]["request_status"] is None
    assert "requires" not in summary["access"]
    for host_path in HOST_MOUNT_PATHS:
        assert host_path not in serialized
    assert "alphafold3_noncommercial" not in serialized


def test_anonymous_method_detail_does_not_expose_runner_mounts(monkeypatch, tmp_path):
    """The full detail projection names the policy, never the host filesystem.

    The detail endpoint intentionally carries the policy identity (it renders the
    restricted-method page), so the leak it must still avoid is the operator's
    host mount layout, which the customer-facing projection has no reason to
    know.
    """
    module = _load_fleet_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    client = module.app.test_client()

    response = client.get(f"/compute/api/types/{RESTRICTED_FAMILY}")
    assert response.status_code == 200, response.get_data(as_text=True)
    detail = response.get_json()
    serialized = json.dumps(detail)

    assert detail["access"]["restricted"] is True
    for host_path in HOST_MOUNT_PATHS:
        assert host_path not in serialized
