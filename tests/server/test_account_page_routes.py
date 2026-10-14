# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The server-owned page-route contract for the Account's direct sections.

The shell links to each Account section directly and the server must serve each
one as a page: a section the navigation reaches but Flask does not register is a
production 404 — direct navigation and a browser refresh both fail. The set is
closed on both sides, so this module holds the two halves of that declaration
together: ``revocompute/account_pages.py::ACCOUNT_SECTION_SLUGS`` is the server
half and ``frontend/src/app/router.ts`` is the frontend half.

The parity is transcribed with a bounded regular expression that fails closed in
both directions: a section the shell declares but the server does not serve
fails, and a section page nobody declares fails as well.
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import _load_pssm_module, _test_client_auth
from revocompute.account_pages import ACCOUNT_SECTION_SLUGS

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROUTER = ROOT / "frontend" / "src" / "app" / "router.ts"

#: The frontend half: the set literal the router closes its section vocabulary on.
_SECTION_SET = re.compile(r"accountSections\s*=\s*new Set<string>\(\[([^\]]*)\]\)")


def _declared_sections() -> set[str]:
    match = _SECTION_SET.search(FRONTEND_ROUTER.read_text(encoding="utf-8"))
    # The transcription must be real: an unreadable or reshaped declaration would
    # otherwise make both directions pass vacuously.
    assert match, f"No Account section set parsed from {FRONTEND_ROUTER}"
    return {slug.strip().strip("'\"") for slug in match.group(1).split(",") if slug.strip()}


def _frontend_entry(module, tmp_path) -> str:
    static_root = tmp_path / "static"
    app_root = static_root / "app"
    app_root.mkdir(parents=True)
    entry = '<!doctype html><html><body><main id="app"></main></body></html>'
    (app_root / "index.html").write_text(entry, encoding="utf-8")
    module.app.static_folder = str(static_root)
    return entry


def test_frontend_account_sections_match_the_server_page_routes():
    """A section the shell links to is exactly a section the server serves.

    The router's vocabulary includes the Account root (``account``), which is
    served by ``/compute/profile``; every other slug is its own page route.
    """
    declared = _declared_sections()
    assert declared
    assert declared - {"account"} == set(ACCOUNT_SECTION_SLUGS)


def test_account_sections_serve_the_shell_at_the_account_auth_boundary(monkeypatch, tmp_path):
    """Anonymous → auth boundary; a signed-in user → the shell, never cached."""
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    entry = _frontend_entry(module, tmp_path)
    client = module.app.test_client()
    user = _test_client_auth(module)

    for slug in ACCOUNT_SECTION_SLUGS:
        path = f"/compute/account/{slug}"
        anonymous = client.get(path)
        assert anonymous.status_code == 401, f"{path} must keep the authentication boundary"

        authenticated = client.get(path, headers=user)
        assert authenticated.status_code == 200, f"{path} must serve a signed-in user the shell"
        assert authenticated.get_data(as_text=True) == entry
        assert authenticated.headers["Cache-Control"] == "private, no-store"


def test_an_unknown_account_section_is_a_not_found_page(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    _frontend_entry(module, tmp_path)
    client = module.app.test_client()
    user = _test_client_auth(module)
    assert client.get("/compute/account/does-not-exist", headers=user).status_code == 404
