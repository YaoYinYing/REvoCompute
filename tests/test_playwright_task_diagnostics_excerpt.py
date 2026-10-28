# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the retained-excerpt panel mounted from the Dashboard.

The Dashboard opens failure evidence inside the application's native ``<dialog>``.
Escape in the excerpt search field must clear the query there without invoking the
dialog's own Escape default action, which would close the whole evidence panel.
Loading and failure feedback must be visible before an excerpt has loaded, when the
excerpt region itself is still hidden. The search screenshot this case leaves in
``tmp_path`` is captured from the production bundle with the failure evidence served
by the fixture API.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import controlled_scenario, mount_scenario

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
EXCERPT = (
    "stage fit started\n"
    "loading structure target.pdb\n"
    "residue 42 mismatch in chain A\n"
    "ERROR: grid integration failed at step 118\n"
    "retrying with a smaller step\n"
    "ERROR: grid integration failed at step 119\n"
    "srun: error: node0042: task 0: Exited with exit code 2\n"
)


def _failed_scenario():
    return controlled_scenario().with_lifecycle("queued", "running", "failed").with_result("failed_diagnostics")


def _mount_evidence(page: Page, scenario) -> str:
    """Serve a truncated stderr diagnostic and return the excerpt URL it names."""
    mount_scenario(page, scenario)
    task_id = scenario.task_id
    page.route(
        f"{ORIGIN}/compute/api/tasks/{task_id}/diagnostics",
        lambda route: route.fulfill(json={
            "task_id": task_id, "availability": "available", "summary": "Execution failed.",
            "reason_code": "nonzero_exit", "exit_code": 2, "exit_code_source": "srun",
            "scheduler_state": "FAILED", "stage": "fit",
            "logs": [{
                "stream": "stderr", "preview": "stage fit started\nERROR: grid integration failed\n",
                "truncated": True, "download_url": f"/compute/api/tasks/{task_id}/diagnostics/stderr",
            }],
        }),
    )
    return f"{ORIGIN}/compute/api/tasks/{task_id}/diagnostics/stderr"


def _open_evidence(page: Page, *, locale: str = "en", dark: bool = False) -> None:
    page.add_init_script(
        f"localStorage.setItem('revocompute-theme', '{'dark' if dark else 'light'}');"
        f"localStorage.setItem('revocompute-locale', '{locale}');"
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{ORIGIN}/compute/dashboard")
    page.get_by_role("button", name="View error" if locale == "en" else "查看错误", exact=True).click()


def test_escape_in_the_excerpt_search_keeps_the_dashboard_evidence_dialog_open(page: Page, tmp_path: Path) -> None:
    """Escape clears the search; the native dialog's own Escape action does not fire."""
    scenario = _failed_scenario()
    _mount_evidence(page, scenario)
    _open_evidence(page, locale="zh-CN", dark=True)

    # The excerpt URL is registered after the evidence route so the suite's own
    # dispatch table never answers the download the panel performs.
    excerpt_url = f"{ORIGIN}/compute/api/tasks/{scenario.task_id}/diagnostics/stderr"
    page.route(excerpt_url, lambda route: route.fulfill(
        status=200, content_type="text/plain; charset=utf-8", body=EXCERPT,
    ))

    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    page.get_by_role("button", name="查看完整保留的 stderr 片段", exact=True).click()

    search = page.locator(".task-diagnostic-search-input")
    expect(search).to_be_visible()
    search.fill("error")
    expect(page.locator("mark")).to_have_count(3)
    expect(page.locator(".task-diagnostic-search-status")).to_contain_text("3")
    page.evaluate("document.fonts.ready")
    page.locator("#app-dialog").screenshot(path=str(tmp_path / "pr121-excerpt-search-zh-dark-390.png"))

    search.focus()
    page.keyboard.press("Escape")

    expect(dialog).to_be_visible()
    expect(search).to_have_value("")
    expect(page.locator("mark")).to_have_count(0)
    page.locator("#app-dialog").screenshot(path=str(tmp_path / "pr121-excerpt-escape-zh-dark-390.png"))


def test_loading_and_failure_feedback_are_visible_before_the_excerpt_region(page: Page) -> None:
    """A pending or failed excerpt reports beside the toggle, not inside the hidden region."""
    scenario = _failed_scenario()
    excerpt_url = _mount_evidence(page, scenario)
    pending = []
    page.route(excerpt_url, lambda route: pending.append(route))
    _open_evidence(page)

    toggle = page.get_by_role("button", name="Read full retained stderr excerpt", exact=True)
    toggle.click()
    loading = page.get_by_text("Loading the retained excerpt…", exact=True)
    expect(loading).to_be_visible()
    expect(loading).to_have_role("status")
    assert loading.evaluate("node => node.checkVisibility() && node.closest('[hidden]') === null")
    expect(toggle).to_be_enabled()

    pending[0].fulfill(status=500, json={"error": "Diagnostic excerpt unavailable"})
    failure = page.locator(".task-diagnostic-error")
    expect(failure).to_be_visible()
    expect(failure).to_have_role("alert")
    assert failure.evaluate("node => node.checkVisibility() && node.closest('[hidden]') === null")
    expect(page.locator(".task-diagnostics pre")).to_be_visible()
    expect(toggle).to_be_enabled()
