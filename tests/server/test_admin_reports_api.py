# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The authorization boundary around the Admin read model.

``revocompute.admin_reports`` owns no route and writes no OpenAPI path: an Admin
HTTP handler authorizes the caller and then calls the facade.  These cases pin
the two halves of that contract against the real Flask application:

* the facade is served by *no* application route today, so it cannot be read
  before an admin-guarded handler and a published operation exist;
* the canonical projections the facade composes are admin-only on the wire, and a
  regular user cannot read another subject's data through them.

The route the canonical owner must add is reported with the PR; this file asserts
the boundary that must hold wherever it lands.
"""

from __future__ import annotations

from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth

#: The paths the Admin read model should be published at, once the owning route
#: and its OpenAPI entries exist.  Until then they must not resolve to anything.
RECOMMENDED_PATHS = (
    "/compute/api/auth/admin/reports/tasks",
    "/compute/api/auth/admin/reports/resources",
    "/compute/api/auth/admin/reports/integrity",
    "/compute/api/auth/admin/reports/activity",
)


def _module(monkeypatch, tmp_path):
    return _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )


def test_the_read_model_is_not_served_by_an_unguarded_route(monkeypatch, tmp_path):
    """A facade with no guard would be an unauthenticated operational read.

    Asserting the absence keeps a handler that forgets ``require_admin()`` from
    shipping unnoticed: the moment one of these paths answers anything other than
    a not-found, this test tells the reviewer to check the guard.
    """
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()

    for path in RECOMMENDED_PATHS:
        assert client.get(path).status_code == 404


def test_no_application_rule_serves_admin_report_payloads(monkeypatch, tmp_path):
    """Every rule that serves an ``admin_reports`` payload must be admin-scoped."""
    module = _module(monkeypatch, tmp_path)
    rules = {rule.rule for rule in module.app.url_map.iter_rules()}

    for path in RECOMMENDED_PATHS:
        assert path not in rules

    # The rule the facade is meant to live behind, when the owner adds it, must be
    # under the admin namespace — the same one every other Admin read uses.
    assert all(
        rule.startswith("/compute/api/auth/admin/")
        for rule in rules
        if "reports/" in rule
    )


def test_a_non_admin_cannot_read_another_subjects_canonical_projection(monkeypatch, tmp_path):
    """The facts the read model composes are admin-only on the wire."""
    module = _module(monkeypatch, tmp_path)
    client = module.app.test_client()
    regular = _test_client_auth(module)
    admin = _admin_client_auth(module)
    target = module.app.config["user_db"].get_user_by_username("tester")
    path = f"/compute/api/auth/admin/users/{target['id']}/resource-entitlement"

    assert client.get(path).status_code in (401, 403)
    assert client.get(path, headers=regular).status_code in (401, 403)
    assert client.get(path, headers=admin).status_code == 200
