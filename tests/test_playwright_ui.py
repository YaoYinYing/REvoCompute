# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect

UI_JS = Path(__file__).resolve().parents[1] / "revocompute" / "static" / "js" / "ui.js"


def test_preferences_persist_and_fail_safe(page: Page) -> None:
    page.route(
        "https://ui.revocompute.test/",
        lambda route: route.fulfill(
            content_type="text/html",
            body='<div id="density"><button data-value="comfortable">Comfortable</button><button data-value="compact">Compact</button></div>',
        ),
    )
    page.goto("https://ui.revocompute.test/")
    page.add_script_tag(path=UI_JS)
    page.evaluate("window.REvoComputeUI.bindSegmented(document.getElementById('density'), 'catalogDensity')")
    page.evaluate("document.querySelector('#density [data-value=compact]').click()")
    expect(page.get_by_role("button", name="Compact")).to_have_attribute("aria-pressed", "true")
    assert page.evaluate("localStorage.getItem('revocompute.ui.catalog-density.v1')") == "compact"
    assert page.evaluate("window.REvoComputeUI.preference('catalogDensity')") == "compact"
    assert page.evaluate(
        """() => {
          Storage.prototype.getItem = function () { throw new Error('blocked'); };
          return window.REvoComputeUI.preference('taskLayout');
        }"""
    ) == "detailed"


def test_custom_confirmation_is_accessible_and_settles_once(page: Page) -> None:
    page.set_content('<button id="trigger">Delete task</button>')
    page.add_script_tag(path=UI_JS)
    page.get_by_role("button", name="Delete task").focus()
    page.evaluate(
        """() => {
          window.__answer = 'waiting';
          window.REvoComputeUI.confirm({title: 'Delete task?', message: 'This removes its artifacts.', confirmLabel: 'Delete task'})
            .then(function (answer) { window.__answer = answer; });
        }"""
    )
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_have_attribute("aria-labelledby", "uiDialogTitle")
    page.get_by_role("button", name="Delete task", exact=True).last.click()
    page.wait_for_function("window.__answer === true")
    expect(dialog).not_to_be_visible()
    expect(page.locator("#trigger")).to_be_focused()


def test_escape_cancels_custom_confirmation(page: Page) -> None:
    page.set_content("")
    page.add_script_tag(path=UI_JS)
    page.evaluate(
        """() => {
          window.__answer = 'waiting';
          window.REvoComputeUI.confirm({title: 'Revoke access?', confirmLabel: 'Revoke access'})
            .then(function (answer) { window.__answer = answer; });
        }"""
    )
    page.keyboard.press("Escape")
    page.wait_for_function("window.__answer === null")


def test_custom_prompt_focuses_its_input(page: Page) -> None:
    page.set_content('<button id="trigger">Request access</button>')
    page.add_script_tag(path=UI_JS)
    page.locator("#trigger").focus()
    page.evaluate(
        """() => {
          window.__answer = 'waiting';
          window.REvoComputeUI.prompt({title: 'Request access', label: 'Research use', required: true})
            .then(function (answer) { window.__answer = answer; });
        }"""
    )
    expect(page.get_by_label("Research use")).to_be_focused()
    page.get_by_label("Research use").fill("Academic protein design")
    page.get_by_role("button", name="Continue").click()
    page.wait_for_function("window.__answer === 'Academic protein design'")
    expect(page.locator("#trigger")).to_be_focused()
