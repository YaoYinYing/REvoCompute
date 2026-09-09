# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Negative architecture checks for the removed collaboration domain."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_project_domain_files_and_routes_are_absent():
    removed = (
        "revocompute/collaboration.py",
        "revocompute/templates/project.html",
        "revocompute/templates/projects.html",
        "revocompute/static/js/project.js",
        "revocompute/static/js/projects.js",
        "revocompute/static/css/projects.css",
    )
    assert not [relative for relative in removed if (ROOT / relative).exists()]
    routes = (ROOT / "revocompute/routes.py").read_text(encoding="utf-8")
    assert "/compute/projects" not in routes
    assert "/compute/api/projects" not in routes
    assert "/compute/api/invitations" not in routes


def test_production_schema_and_storage_have_no_scope_dispatch():
    sources = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "revocompute/app.py",
            "revocompute/routes.py",
            "revocompute/storage.py",
            "revocompute/schemas.py",
        )
    )
    for obsolete in ("scope_type", "scope_id", "CollaborationDatabase", '"projects"'):
        assert obsolete not in sources
    storage = (ROOT / "revocompute/storage.py").read_text(encoding="utf-8")
    assert 'safe_join(base, "users", storage_key)' in storage


def test_scope_columns_survive_only_as_epoch_rejection_markers():
    for relative in ("revocompute/db.py", "revocompute/auth.py"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for marker in ("scope_type", "scope_id"):
            assert text.count(marker) == 1
        assert "forbidden_columns" in text
