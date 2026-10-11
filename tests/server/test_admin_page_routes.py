# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The server-owned page-route contract for every Administration destination.

The frontend shell navigates to a closed set of Administration destinations and
the server must serve each one as a page.  A destination the navigation links to
but Flask does not register is a production 404 — direct navigation and a browser
refresh both fail — so this module holds the two halves of that declaration
together: ``revocompute/routes.py::ADMIN_PAGE_ROUTES`` is the server half and
``frontend/src/app/admin-destinations.ts`` is the frontend half.

The frontend declaration is transcribed with a bounded regular expression that
fails closed in both directions: a destination the shell declares but the server
does not serve fails, and a page route nobody declares fails as well.
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import _admin_client_auth, _load_pssm_module, _test_client_auth
from revocompute.admin_pages import ADMIN_PAGE_ROUTES

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DESTINATIONS = ROOT / "frontend" / "src" / "app" / "admin-destinations.ts"

#: One destination entry in the frontend declaration.  ``path`` is the only
#: property spelled with a leading-slash string literal, so the scan cannot pick
#: up an unrelated value.
_DESTINATION = re.compile(r"\{\s*path:\s*'(/[^']+)'")

#: Browser page routes that are deliberately not Administration destinations:
#: the shell reaches them as a signed-in user, as an anonymous visitor, or not at
#: all.  Each is a page the server must keep serving; none is an Admin workspace.
_NON_ADMIN_PAGE_ROUTES = frozenset(
    {
        "/",
        "/api-docs",
        "/openapi.json",
        "/skills.md",
        "/runners",
        "/runners/<name>",
        "/static/<path:filename>",
        "/compute/health",
        "/compute/login",
        "/compute/register",
        "/compute/reset_password",
        "/compute/user_verify",
        "/compute/terms",
        "/compute/profile",
        "/compute/create_task",
        "/compute/dashboard",
        "/compute/results/<md5sum>",
        "/PSSM_GREMLIN/dashboard",
        "/PSSM_GREMLIN/create_task",
    }
)


def _declared_destinations() -> list[str]:
    return _DESTINATION.findall(FRONTEND_DESTINATIONS.read_text(encoding="utf-8"))


def _browser_page_rules(module) -> set[str]:
    """Every registered GET rule that is not an API endpoint."""
    return {
        str(rule.rule)
        for rule in module.app.url_map.iter_rules()
        if "GET" in (rule.methods or set()) and not str(rule.rule).startswith("/compute/api/")
    }


def _frontend_entry(module, tmp_path) -> str:
    static_root = tmp_path / "static"
    app_root = static_root / "app"
    app_root.mkdir(parents=True)
    entry = '<!doctype html><html><body><main id="app"></main></body></html>'
    (app_root / "index.html").write_text(entry, encoding="utf-8")
    module.app.static_folder = str(static_root)
    return entry


def test_frontend_administration_destinations_match_the_server_page_routes():
    """The shell's Administration destinations are exactly the server's."""
    declared = _declared_destinations()
    # The transcription must be real: an unreadable or reshaped declaration would
    # otherwise make both directions pass vacuously.
    assert declared, f"No Administration destinations parsed from {FRONTEND_DESTINATIONS}"
    assert len(declared) == len(set(declared))
    assert {path for path, _ in ADMIN_PAGE_ROUTES} == set(declared)


def test_admin_page_routes_are_distinct_registered_endpoints(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    registered = _browser_page_rules(module)
    for path, endpoint in ADMIN_PAGE_ROUTES:
        assert path in registered, f"{path} is not a registered page route"
        assert module.app.view_functions.get(endpoint) is not None, f"{endpoint} is not registered"
    endpoints = [endpoint for _, endpoint in ADMIN_PAGE_ROUTES]
    assert len(endpoints) == len(set(endpoints))


def test_admin_page_routes_serve_the_shell_at_the_existing_auth_boundary(monkeypatch, tmp_path):
    """admin → shell; authenticated non-admin → 403; anonymous → auth boundary."""
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    entry = _frontend_entry(module, tmp_path)
    client = module.app.test_client()
    admin = _admin_client_auth(module)
    user = _test_client_auth(module)

    for path, _ in ADMIN_PAGE_ROUTES:
        anonymous = client.get(path)
        assert anonymous.status_code == 401, f"{path} must keep the authentication boundary"

        authenticated = client.get(path, headers=user)
        assert authenticated.status_code == 403, f"{path} must 403 for a non-administrator"
        assert authenticated.get_data(as_text=True) == entry
        assert authenticated.headers["Cache-Control"] == "private, no-store"

        administrator = client.get(path, headers=admin)
        assert administrator.status_code == 200, f"{path} must serve an administrator the shell"
        assert administrator.get_data(as_text=True) == entry
        assert administrator.headers["Cache-Control"] == "private, no-store"


def test_browser_page_route_set_is_closed(monkeypatch, tmp_path):
    """No undeclared browser page route exists, and none is silently dropped."""
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    declared = {path for path, _ in ADMIN_PAGE_ROUTES} | _NON_ADMIN_PAGE_ROUTES
    undeclared = sorted(_browser_page_rules(module) - declared)
    assert undeclared == []
