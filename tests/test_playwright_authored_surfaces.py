# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Work-first geometry and keyboard behavior for the register and method reference."""
from __future__ import annotations

from dataclasses import replace

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import (
    ParameterSpec,
    build_task_summary,
    controlled_runner,
    controlled_scenario,
    mount_scenario,
    runner_scenario,
)
from frontend_fixtures.results import PDB_BODY

pytestmark = pytest.mark.browser
ORIGIN = "https://revocompute.example"


def _parameter_reference_scenario():
    """A generic CPU Runner whose control list is deep enough to scroll like a real method.

    The keyboard-jump contract - focusing a method-index link and pressing Enter
    lands the Task parameters region at the top of the viewport - is only
    observable when the page is tall enough to scroll. A Runner with one control
    renders short enough that the browser cannot scroll the section into place,
    so this synthetic ``sequence_demo`` declares a realistic control list. It is
    still a generic identity, never a production Runner.
    """
    parameters = tuple(
        ParameterSpec.integer(
            f"option_{index}",
            default=index,
            has_default=True,
            minimum=0,
            maximum=100,
            description="Controls one synthetic setting for this run and its output.",
        )
        for index in range(6)
    )
    return runner_scenario(replace(controlled_runner(), parameters=parameters))


def _mount_dashboard_with_preview(page: Page, width: int, role: str = "user") -> None:
    page.set_viewport_size({"width": width, "height": 960})
    scenario = controlled_scenario().with_role(role)
    preview_url = f"/compute/api/tasks/{scenario.task_id}/input"
    with_preview = build_task_summary(
        scenario.task_id, scenario.runner, owner=scenario.session.username,
        input_preview={"capability": "molecular_structure", "format": "pdb", "url": preview_url},
    )
    without_preview = build_task_summary("f" * 32, scenario.runner, owner=scenario.session.username)
    with_preview["display_name"] = "With input preview"
    without_preview["display_name"] = "Without input preview"
    mount_scenario(page, scenario.with_task_summaries([with_preview, without_preview]))
    page.route(f"{ORIGIN}{preview_url}", lambda route: route.fulfill(content_type="chemical/x-pdb", body=PDB_BODY))
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card")).to_have_count(2)


@pytest.mark.parametrize("width", [1024, 1440])
@pytest.mark.parametrize("role", ["user", "admin"])
def test_detailed_task_preview_uses_the_register_measure_and_keeps_actions_reachable(
    page: Page, width: int, role: str,
) -> None:
    _mount_dashboard_with_preview(page, width, role)
    card = page.locator(".task-card").filter(has=page.get_by_role("heading", name="With input preview", exact=True))
    preview = card.locator(".input-preview")
    with page.expect_response(f"{ORIGIN}/compute/api/tasks/{controlled_scenario().task_id}/input"):
        preview.locator("summary").click()
    expect(preview).to_have_attribute("open", "")
    row = card.bounding_box()
    expanded = preview.bounding_box()
    host = preview.locator(".input-preview-host").bounding_box()
    actions = card.locator(".task-actions").bounding_box()
    facts = card.locator("dl").bounding_box()
    assert row and expanded and host and actions and facts
    assert abs(expanded["x"] - row["x"]) <= 1
    assert abs(expanded["width"] - row["width"]) <= 1
    assert host["width"] >= row["width"] - 2
    assert actions["y"] >= expanded["y"] + expanded["height"] - 1
    assert abs(actions["x"] - facts["x"]) <= 1
    confirmations: list[str] = []
    page.once("dialog", lambda dialog: (confirmations.append(dialog.message), dialog.dismiss()))
    card.get_by_role("button", name="Delete", exact=True).click()
    assert confirmations and "With input preview" in confirmations[0]
    preview.locator("summary").click()
    collapsed = card.bounding_box()
    assert collapsed and collapsed["height"] < row["height"] - 250
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("role", ["user", "admin"])
def test_detailed_task_without_preview_has_no_empty_grid_slot(page: Page, role: str) -> None:
    _mount_dashboard_with_preview(page, 1440, role)
    card = page.locator(".task-card").filter(has=page.get_by_role("heading", name="Without input preview", exact=True))
    expect(card.locator(".input-preview")).to_have_count(0)
    assert card.evaluate("""node => !Array.from(node.children).some(child => {
        const box = child.getBoundingClientRect();
        return !child.children.length && !child.textContent.trim() && box.width > 0 && box.height > 0;
    })""")
    header = card.locator("header").bounding_box()
    facts = card.locator("dl").bounding_box()
    actions = card.locator(".task-actions").bounding_box()
    assert header and facts and actions
    assert abs(actions["x"] - facts["x"]) <= 1
    assert abs(actions["y"] - max(header["y"] + header["height"], facts["y"] + facts["height"])) <= 1
    expect(card.get_by_role("link", name="Results", exact=True)).to_be_visible()


@pytest.mark.parametrize("width", [390, 1440])
def test_preview_tasks_preserve_mobile_compact_and_table_views(page: Page, width: int) -> None:
    _mount_dashboard_with_preview(page, width)
    if width == 390:
        preview = page.locator(".input-preview")
        preview.locator("summary").click()
        row = page.locator(".task-card").first.bounding_box()
        expanded = preview.bounding_box()
        assert row and expanded and abs(expanded["width"] - row["width"]) <= 1
        preview.locator("summary").click()
    page.get_by_role("button", name="Compact", exact=True).click()
    expect(page.locator(".task-card")).to_have_count(2)
    expect(page.locator(".input-preview")).to_be_hidden()
    expect(page.locator(".task-card").first.get_by_role("link", name="Results", exact=True)).to_be_visible()
    page.get_by_role("button", name="Table", exact=True).click()
    expect(page.locator(".task-table tbody tr")).to_have_count(2)
    expect(page.locator(".input-preview")).to_have_count(0)
    expect(page.locator(".task-table").get_by_role("link", name="Results", exact=True)).to_have_count(2)
    page.get_by_role("button", name="Detailed", exact=True).click()
    expect(page.locator(".task-card")).to_have_count(2)
    expect(page.locator(".input-preview")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


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
    scenario = _parameter_reference_scenario()
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
    scenario = controlled_scenario()
    mount_scenario(page, scenario)
    page.goto(f"{ORIGIN}/runners/{scenario.runner.name}")
    summary = page.get_by_text("Runtime facts · CPU", exact=True)
    expect(page.locator(".runner-facts")).to_be_hidden()
    closed = page.get_by_role("region", name="When to use this method").bounding_box()
    summary.focus()
    page.keyboard.press("Enter")
    expect(page.locator(".runner-facts")).to_be_visible()
    # The disclosure's fact list states the Runner's own runtime family, not a
    # generic label: ``controlled_runner()`` declares ``example``.
    expect(page.locator(".runner-facts")).to_contain_text(scenario.runner.runtime_family)
    opened = page.get_by_role("region", name="When to use this method").bounding_box()
    assert closed and opened and opened["y"] > closed["y"] + 100
    summary.click()
    expect(page.locator(".runner-facts")).to_be_hidden()
    page.set_viewport_size({"width": 1440, "height": 780})
    expect(page.locator(".runner-facts")).to_be_visible()
    expect(summary).to_be_hidden()


@pytest.mark.parametrize("tour_completed", [False, True])
def test_narrow_admin_register_tolerates_wider_font_metrics(page: Page, tour_completed: bool) -> None:
    page.set_viewport_size({"width": 320, "height": 780})
    if tour_completed:
        page.add_init_script("localStorage.setItem('revocompute-tour-done', 'true')")
    mount_scenario(page, controlled_scenario().with_role("admin"))
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card")).to_be_visible()
    page.add_style_tag(content=":root { --font-sans: monospace; }")
    actions = page.locator(".dashboard-page .page-actions")
    box = actions.bounding_box()
    navigation = page.locator(".app-nav-group[data-nav-group='admin']").bounding_box()
    heading = page.locator(".task-card h2").bounding_box()
    assert box and navigation and heading
    assert heading["y"] + heading["height"] <= navigation["y"]
    for control in actions.locator(":scope > *").all():
        target = control.bounding_box()
        assert target and target["height"] >= 44
        assert target["x"] >= box["x"] and target["x"] + target["width"] <= box["x"] + box["width"] + 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
