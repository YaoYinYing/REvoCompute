# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""A method the server will refuse is never offered as submittable.

The server projects one submission decision per method from the published
readiness attestation.  Catalog cards, the method detail, the comparison and the
Create Task deep link all render that decision: a blocked method stays
discoverable, but its Create Task control is an explanatory, non-actionable
control carrying the server's own reason and recovery action.  The Create Task
page states the same reason at mount; its Run control remains the server's
boundary to refuse, never a client-side readiness oracle.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from test_playwright_application import _install_app

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"

READY = {
    "ready": True,
    "status": "READY",
    "reason_code": "READY",
    "message": "Active Runner SIF passed all required current smoke cases",
    "next_action": "none",
}
BLOCKED = {
    "ready": False,
    "status": "VALIDATION_STALE",
    "reason_code": "RECEIPT_STALE",
    "message": "Live-test receipt does not match the active Runner identity",
    "next_action": "live-test",
}
UNKNOWN = {
    "ready": False,
    "status": "NOT_CONFIGURED",
    "reason_code": "RUNNER_UNAVAILABLE",
    "message": "Runner readiness evidence is unavailable",
    "next_action": "doctor",
}
METHODS = (
    ("ready_method", "Ready method", READY),
    ("blocked_method", "Blocked method", BLOCKED),
    ("unknown_method", "Unknown method", UNKNOWN),
)


def _entry(name: str, label: str, submission: dict) -> dict:
    return {
        "name": name,
        "display_name": label,
        "category": "demo",
        "summary": f"{label} contract.",
        "access": {"restricted": False, "granted": True, "request_status": None},
        "submission": submission,
        "detail_url": f"/compute/api/types/{name}",
        "parameters_url": f"/compute/api/task-parameters/{name}",
    }


def _catalog() -> dict:
    return {
        "version": 3,
        "categories": [{"name": "demo", "label": "Demo"}],
        "task_types": [_entry(name, label, submission) for name, label, submission in METHODS],
    }


def _detail(name: str, label: str, submission: dict) -> dict:
    return {
        **_entry(name, label, submission),
        "use_when": "Whenever the contract is useful.",
        "input_summary": "No uploaded files.",
        "output_summary": "A synthetic report.",
        "considerations": [],
        "definition_version": 4,
        "runtime_family": "demo",
        "gpus": False,
        "requires_network": False,
        "inputs": [],
        "citations": [],
        "workflow": [],
        "max_request_bytes": 1048576,
        "input_workspace": {
            "version": 3,
            "plugins": [],
            "steps": [
                {
                    "id": "review",
                    "title": "Review",
                    "description": "Check the submission.",
                    "capabilities": [
                        {
                            "plugin": "review",
                            "id": "submission_review",
                            "title": "Review",
                            "description": "Submission summary.",
                            "options": {"show_paths": True},
                        }
                    ],
                }
            ],
        },
    }


def _install_methods(page: Page) -> None:
    def handler(payload):
        return lambda route, *_request: route.fulfill(json=payload)

    # Registered after ``_install_app`` so these responses take precedence.
    page.route(f"{ORIGIN}/compute/api/types", handler(_catalog()))
    for name, label, submission in METHODS:
        page.route(f"{ORIGIN}/compute/api/types/{name}", handler(_detail(name, label, submission)))
        page.route(
            f"{ORIGIN}/compute/api/task-parameters/{name}",
            handler(
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                }
            ),
        )


def _card(page: Page, label: str):
    return page.locator("article.runner-card", has_text=label)


def test_catalog_and_detail_render_a_blocked_method_as_non_submittable(page: Page):
    _install_app(page)
    _install_methods(page)
    page.goto(f"{ORIGIN}/runners")

    ready = _card(page, "Ready method")
    blocked = _card(page, "Blocked method")
    unknown = _card(page, "Unknown method")

    # The ready method still offers an active Create Task link.
    expect(ready.locator('a[href^="/compute/create_task"]')).to_have_count(1)
    # The blocked methods remain discoverable but offer no submission link.
    expect(blocked.locator('a[href="/runners/blocked_method"]')).to_have_count(1)
    expect(blocked.locator('a[href^="/compute/create_task"]')).to_have_count(0)
    expect(unknown.locator('a[href^="/compute/create_task"]')).to_have_count(0)
    expect(blocked.get_by_role("button", name="Create task unavailable")).to_be_disabled()
    expect(unknown.get_by_role("button", name="Create task unavailable")).to_be_disabled()
    expect(blocked).to_contain_text(BLOCKED["message"])
    expect(blocked).to_contain_text("Recommended: Run the live test")
    expect(unknown).to_contain_text(UNKNOWN["message"])
    expect(unknown).to_contain_text("Recommended: Run Runner Doctor")
    # Regression: exactly one active submission affordance, for the ready method.
    expect(page.locator(".runner-catalog a[href^='/compute/create_task']")).to_have_count(1)

    # The explanatory control carries a full server sentence; it must still wrap
    # inside a phone-width card rather than widen the page.
    page.set_viewport_size({"width": 390, "height": 844})
    expect(_card(page, "Blocked method")).to_be_visible()
    assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")

    page.goto(f"{ORIGIN}/runners/blocked_method")
    expect(page.locator(".runner-detail-page a[href^='/compute/create_task']")).to_have_count(0)
    expect(page.locator(".page-actions").get_by_role("button", name="Create task unavailable")).to_be_disabled()
    expect(page.locator(".page-actions")).to_contain_text(BLOCKED["message"])
    expect(page.locator(".page-actions")).to_contain_text("Recommended: Run the live test")


def test_compare_marks_a_blocked_method_without_offering_submission(page: Page):
    _install_app(page)
    _install_methods(page)
    page.goto(f"{ORIGIN}/runners")

    _card(page, "Ready method").locator("input[data-compare]").check()
    _card(page, "Blocked method").locator("input[data-compare]").check()
    page.get_by_role("button", name="Compare methods").click()

    dialog = page.locator("dialog.method-comparison")
    expect(dialog).to_be_visible()
    configure = dialog.locator("tr", has_text="Configure")
    expect(configure.locator("a[href^=\"/compute/create_task\"]")).to_have_count(1)
    expect(configure.get_by_role("button", name="Create task unavailable")).to_be_disabled()
    expect(configure).to_contain_text(BLOCKED["message"])


def test_create_task_deep_link_states_the_server_reason_at_mount(page: Page):
    _install_app(page)
    _install_methods(page)
    page.goto(f"{ORIGIN}/compute/create_task")

    ready = page.locator("button.ct-method", has_text="Ready method")
    blocked = page.locator("button.ct-method", has_text="Blocked method")
    expect(blocked).to_contain_text(BLOCKED["message"])
    expect(ready).not_to_contain_text(BLOCKED["message"])

    blocked.click()
    expect(page.locator(".ct-validation")).to_contain_text(BLOCKED["message"])
    expect(page.locator(".ct-validation")).to_contain_text("Recommended: Run the live test")
    # The page explains the server's decision; the Run control is not a
    # client-side readiness gate, and the server remains the boundary.
    expect(page.locator("button.ct-primary")).to_be_enabled()

    page.goto(f"{ORIGIN}/compute/create_task?task_type=unknown_method")
    expect(page.locator(".ct-validation")).to_contain_text(UNKNOWN["message"])
    expect(page.locator(".ct-validation")).to_contain_text("Recommended: Run Runner Doctor")
    expect(page.locator("button.ct-primary")).to_be_enabled()
