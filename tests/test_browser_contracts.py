# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Behavior contracts for server-owned browser surfaces."""

from __future__ import annotations

from pathlib import Path


def test_profile_and_admin_runner_access_ui_contract() -> None:
    """Restricted access remains discoverable without a task history."""
    root = Path(__file__).resolve().parents[1]
    profile = (root / "revocompute" / "static" / "js" / "profile.js").read_text(encoding="utf-8")
    admin = (root / "revocompute" / "static" / "js" / "user-control.js").read_text(encoding="utf-8")
    assert 'A.authFetch("/compute/api/access")' in profile
    assert "/compute/api/access/requests" in profile
    assert "policy.license.url" in profile
    assert "/compute/api/auth/admin/access/policies" in admin
    assert "/compute/api/auth/admin/access/events" in admin
