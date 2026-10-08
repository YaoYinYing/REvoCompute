# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Work-first geometry and keyboard behavior for the register and method reference."""
from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import controlled_scenario, mount_scenario, pssm_gremlin_scenario

pytestmark = pytest.mark.browser
ORIGIN = "https://revocompute.example"


@pytest.mark.parametrize("width", [320, 390, 834, 1440])
@pytest.mark.parametrize("role", ["user", "admin"])
def test_dashboard_opens_on_task_identity_and_keeps_machine_facts_readable(page: Page, width: int, role: str) -> None:
    page.set_viewport_size({"width": width, "height": 780})
    mount_scenario(page, controlled_scenario().with_role(role))
    page.goto(f"{ORIGIN}/compute/dashboard")
    card = page.locator(".task-card").first
    expect(card).to_be_visible()
    heading = card.get_by_role("heading").bounding_box()
    assert heading
    if width <= 834:
        selector = ".app-nav-group[data-nav-group='admin']" if role == "admin" else ".app-nav"
        navigation = page.locator(selector).bounding_box()
        assert navigation
        assert heading["y"] + heading["height"] <= navigation["y"]
    else:
        assert heading["y"] + heading["height"] <= 780
    identity = card.locator("dd.machine")
    # The ID is usable at every width, including a complete selection/copy.
    assert identity.evaluate("node => node.scrollWidth <= node.clientWidth")
    assert identity.evaluate("node => getComputedStyle(node).userSelect") == "all"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("width", [320, 390])
def test_mobile_filters_keep_their_effect_when_closed_and_survive_view_changes(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 780})
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    summary = page.locator(".dashboard-filters > summary")
    expect(page.locator("[data-filter='status']")).to_be_hidden()
    summary.focus()
    page.keyboard.press("Enter")
    expect(page.locator("[data-filter='status']")).to_be_visible()
    page.locator("[data-filter='status']").select_option("running")
    expect(page.locator(".task-card")).to_have_count(0)
    expect(summary).to_have_text("Filters & order · active")
    summary.click()
    closed = page.locator(".dashboard-filters").bounding_box()
    page.get_by_role("button", name="Compact", exact=True).click()
    expect(page.locator(".task-card")).to_have_count(0)
    summary.click()
    opened = page.locator(".dashboard-filters").bounding_box()
    assert opened and closed and opened["height"] > closed["height"] + 44
    expect(page.locator("[data-filter='status']")).to_have_value("running")
    page.locator("[data-filter='status']").select_option("")
    summary.click()
    expect(summary).to_have_text("Filters & order")
    expect(page.locator(".task-card")).to_have_count(1)


@pytest.mark.parametrize("width", [320, 834, 1440])
def test_method_index_keyboard_jump_reaches_the_complete_parameter_reference(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 780})
    scenario = pssm_gremlin_scenario()
    mount_scenario(page, scenario)
    page.goto(f"{ORIGIN}/runners/{scenario.runner.name}")
    index = page.get_by_role("navigation", name="On this method")
    controls = index.get_by_role("link", name="Controls", exact=True)
    controls.focus()
    page.keyboard.press("Enter")
    section = page.get_by_role("region", name="Task parameters")
    expect(section).to_be_focused()
    heading = section.get_by_role("heading", name="Task parameters").bounding_box()
    assert heading and 0 <= heading["y"] < 100
    expect(section.locator(".parameter-list > article")).to_have_count(len(scenario.runner.parameters))
    # Names, descriptions and values wrap inside the viewport, rather than
    # trading away the actual contract to retain a desktop column count.
    assert section.locator(".parameter-list").evaluate("node => node.scrollWidth <= node.clientWidth")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width > 834:
        index_box = index.bounding_box()
        assert index_box and index_box["y"] >= 0


def test_mobile_method_runtime_disclosure_returns_space_without_losing_facts(page: Page) -> None:
    page.set_viewport_size({"width": 320, "height": 780})
    scenario = pssm_gremlin_scenario()
    mount_scenario(page, scenario)
    page.goto(f"{ORIGIN}/runners/{scenario.runner.name}")
    summary = page.get_by_text("Runtime facts · CPU", exact=True)
    expect(page.locator(".runner-facts")).to_be_hidden()
    closed = page.get_by_role("region", name="When to use this method").bounding_box()
    summary.focus()
    page.keyboard.press("Enter")
    expect(page.locator(".runner-facts")).to_be_visible()
    expect(page.locator(".runner-facts")).to_contain_text(scenario.runner.runtime_family)
    opened = page.get_by_role("region", name="When to use this method").bounding_box()
    assert closed and opened and opened["y"] > closed["y"] + 100
    summary.click()
    expect(page.locator(".runner-facts")).to_be_hidden()
    page.set_viewport_size({"width": 1440, "height": 780})
    expect(page.locator(".runner-facts")).to_be_visible()
    expect(summary).to_be_hidden()
