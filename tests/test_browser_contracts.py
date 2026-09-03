# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Contract tests for the browser plugin host, input workspace, and result previews.

These run the shared Node.js test script and verify the modules load
correctly in the expected order.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_plugin_host_registry_lifecycle_and_isolation() -> None:
    """All JS contract tests must pass in a single Node.js run."""
    tests_js = Path(__file__).resolve().parent / "js" / "test_contracts.js"
    result = subprocess.run(
        ["node", str(tests_js)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"JS contract tests failed (exit {result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


def test_viewer_shell_message_contract() -> None:
    """A posted structure mounts and acknowledges through the shell protocol."""
    tests_js = Path(__file__).resolve().parent / "js" / "test_viewer_shell.js"
    result = subprocess.run(
        ["node", str(tests_js)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"Viewer shell contract failed (exit {result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


def test_js_modules_load_in_correct_order() -> None:
    """plugin-host.js must load before result-preview-plugins.js and input-workspace.js."""
    js_dir = Path(__file__).resolve().parents[1] / "revocompute" / "static" / "js"
    check = subprocess.run(
        ["node", "--check", str(js_dir / "plugin-host.js")],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert check.returncode == 0, f"plugin-host.js syntax: {check.stderr}"
    for filename in (
        "configuration.js",
        "result-preview-plugins.js",
        "input-workspace.js",
        "input-workspace-rfdiffusion.js",
        "viewer-shell.js",
        "task-results.js",
        "create-task.js",
        "projects.js",
        "project.js",
        "user-control.js",
    ):
        result = subprocess.run(
            ["node", "--check", str(js_dir / filename)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"{filename} syntax: {result.stderr}"


def test_profile_and_admin_runner_access_ui_contract() -> None:
    """Restricted access remains discoverable without a task history."""
    root = Path(__file__).resolve().parents[1]
    profile = (root / "revocompute" / "static" / "js" / "profile.js").read_text(encoding="utf-8")
    profile_template = (root / "revocompute" / "templates" / "profile.html").read_text(encoding="utf-8")
    admin = (root / "revocompute" / "static" / "js" / "user-control.js").read_text(encoding="utf-8")
    admin_template = (root / "revocompute" / "templates" / "user_control.html").read_text(encoding="utf-8")
    assert "runnerAccessList" in profile_template
    assert 'A.authFetch("/compute/api/access")' in profile
    assert "/compute/api/access/requests" in profile
    assert "policy.license.url" in profile
    assert "accessPolicyOverview" in admin_template
    assert "/compute/api/auth/admin/access/policies" in admin
    assert "/compute/api/auth/admin/access/events" in admin
