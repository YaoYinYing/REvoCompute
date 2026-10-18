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


def _mount_dense_admin_dashboard(page: Page, width: int, tasks: int) -> None:
    """Open the admin register on a wide list: thirty rows with mixed statuses.

    A register holding only the canonical fixture's single short task fits even
    the narrowest viewport, so a layout that escapes its own scroll container
    stays invisible. Mixed lifecycle states and their action affordances give
    the Table its real column widths.
    """
    page.set_viewport_size({"width": width, "height": 960})
    scenario = controlled_scenario().with_role("admin")
    statuses = ("finished", "running", "failed")
    summaries = []
    for index in range(tasks):
        status = statuses[index % len(statuses)]
        summary = build_task_summary(
            f"{index:032x}", scenario.runner, status=status,
            result_available=status == "finished", owner=scenario.session.username,
        )
        summary["display_name"] = f"Dense task {index:02d} with a long descriptive name"
        summaries.append(summary)
    mount_scenario(page, scenario.with_task_summaries(summaries))
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card")).to_have_count(tasks)


def _reveal_navigation(page: Page, width: int) -> None:
    """Put the navigation where the reader reaches it at this width.

    Above the desktop breakpoint the sidebar is the column the shell lays out.
    Below it #88 withdraws the sidebar and one control reveals the same
    navigation, regions included, in a modal drawer.
    """
    if width >= 1024:
        expect(page.locator(".app-sidebar")).to_be_visible()
        return
    opener = page.locator(".app-shell .app-nav-open")
    expect(opener).to_be_visible()
    opener.click()
    expect(page.locator(".app-nav-drawer")).to_be_visible()


def _centre_is_reachable(page: Page, locator) -> bool:
    """Whether the element's own centre point resolves back to it."""
    return bool(locator.evaluate(
        """node => { const box = node.getBoundingClientRect();
             if (!box.width || !box.height) return false;
             const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
             return !!(hit && (node === hit || node.contains(hit))); }"""
    ))


def _content_inset(card) -> tuple[float, float]:
    """The card's own left and right content inset, in px."""
    return tuple(card.evaluate(
        "node => [parseFloat(getComputedStyle(node).paddingLeft),"
        " parseFloat(getComputedStyle(node).paddingRight)]"
    ))


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
    identity = card.locator(".task-identity").bounding_box()
    assert row and expanded and host and actions and identity
    # #88 made the card a ruled register row rather than a closed grid card, so the
    # measure the preview takes is the row's own content box — from its left inset
    # to its right inset — and the preview host fills that measure rather than
    # opening a second, narrower column inside the row.
    left_inset, right_inset = _content_inset(card)
    assert abs(expanded["x"] - (row["x"] + left_inset)) <= 1, (expanded, row, left_inset)
    assert abs(expanded["width"] - (row["width"] - left_inset - right_inset)) <= 1, (expanded, row, left_inset, right_inset)
    assert abs(host["width"] - expanded["width"]) <= 1, (host, expanded)
    # The preview is a band below the identity, and the row's own action cluster stays
    # on the row's first line: expanding one Task's input does not displace its
    # actions, and it consumes no neighbouring Task's column because it takes the
    # full measure of its own row.
    assert expanded["y"] >= identity["y"] + identity["height"] - 1, (expanded, identity)
    assert actions["y"] + actions["height"] <= expanded["y"] + 1, (actions, expanded)
    # Deletion is confirmed through the application's own dialog, which names the
    # Task it is about to destroy. Dismissing it leaves the Task untouched.
    card.locator(".task-overflow > summary").click()
    card.locator(".task-overflow-menu").get_by_role("button", name="Delete", exact=True).click()
    confirm = page.locator("#app-dialog")
    expect(confirm).to_be_visible()
    expect(confirm).to_contain_text("With input preview")
    confirm.get_by_role("button", name="Cancel", exact=True).click()
    expect(confirm).to_be_hidden()
    preview.locator("summary").click()
    expect(preview).not_to_have_attribute("open", "")
    collapsed = card.bounding_box()
    assert collapsed and collapsed["height"] < row["height"] - 250, (collapsed, row)
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
    # A Task with no input preview is a single register row: it reserves no band for
    # the preview it does not have, so it is far shorter than its neighbour whose
    # preview is open, and every part of it is laid out inside its own row.
    row = card.bounding_box()
    with_preview = page.locator(".task-card").filter(
        has=page.get_by_role("heading", name="With input preview", exact=True)
    )
    plain_height = card.evaluate("node => node.getBoundingClientRect().height")
    assert with_preview.bounding_box() is not None and plain_height < 400, (plain_height, row)
    assert row and row["height"] == pytest.approx(plain_height, abs=1)
    for selector in (".task-identity", ".task-state", ".task-time", ".task-actions"):
        part = card.locator(selector).bounding_box()
        assert part, selector
        assert part["y"] >= row["y"] - 1 and part["y"] + part["height"] <= row["y"] + row["height"] + 1, (selector, part, row)
    expect(card.get_by_role("link", name="Results", exact=True)).to_be_visible()


@pytest.mark.parametrize("width", [390, 1440])
def test_preview_tasks_preserve_mobile_compact_and_table_views(page: Page, width: int) -> None:
    _mount_dashboard_with_preview(page, width)
    if width == 390:
        preview = page.locator(".input-preview")
        preview.locator("summary").click()
        card = page.locator(".task-card").first
        row = card.bounding_box()
        expanded = preview.bounding_box()
        left_inset, right_inset = _content_inset(card)
        assert row and expanded
        # The register row carries its own horizontal inset at this width, so the
        # measure the preview takes is the row's content box: the band spans the
        # row from inset to inset rather than only part of it.
        assert abs(expanded["x"] - (row["x"] + left_inset)) <= 1, (expanded, row, left_inset)
        assert abs(expanded["width"] - (row["width"] - left_inset - right_inset)) <= 1, (expanded, row)
        preview.locator("summary").click()
        expect(preview).not_to_have_attribute("open", "")
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
    # The register opens on the work: the first Task identity is inside the opening
    # viewport, not below a column of page chrome the reader has to scroll past. #88
    # gives the register its own stats band, filter band and view toolbar above the
    # list, so at a phone width the identity sits below them where the pre-#88 fixed
    # bottom bar used to be; what is asserted is that the work leads the register,
    # which is a bound against the viewport the reader opened, not against a bar.
    identity = card.locator(".task-identity-id")
    first_row = card.bounding_box()
    assert first_row and 0 < heading["y"] - first_row["y"] < 40, (heading, first_row)
    assert heading["y"] + heading["height"] <= 780, (width, role, heading)
    # The navigation never covers it: above the desktop breakpoint it is the
    # sidebar column beside the outlet, and below it #88 withdraws the sidebar
    # entirely, so the work is unobstructed until the reader opens the drawer,
    # which is modal and is therefore not painted over the register.
    if width <= 834:
        expect(page.locator(".app-sidebar")).to_be_hidden()
        expect(page.locator(".app-nav-drawer")).to_be_hidden()
        opener = page.locator(".app-shell .app-nav-open")
        assert opener.bounding_box() is not None
        expect(opener).to_have_attribute("aria-expanded", "false")
        # The navigation is genuinely reachable from this width, in one control.
        _reveal_navigation(page, width)
        expect(page.locator(".app-nav-drawer .app-nav")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator(".app-nav-drawer")).to_be_hidden()
    else:
        expect(page.locator(".app-sidebar")).to_be_visible()
    expect(identity).to_have_count(1)
    # The ID is usable at every width: it stays complete inside its own box rather
    # than being clipped, and it is selectable as the machine value it is.
    assert identity.evaluate("node => node.scrollWidth <= node.clientWidth")
    assert identity.evaluate("node => getComputedStyle(node).userSelect") != "none"
    assert identity.evaluate("node => getComputedStyle(node).overflowWrap") in ("anywhere", "break-word")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("width", [320, 390])
def test_mobile_filters_keep_their_effect_when_closed_and_survive_view_changes(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 780})
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    summary = page.locator(".dashboard-filters > summary")
    fields = page.locator(".dashboard-filter-fields")
    expect(page.locator("[data-filter='status']")).to_be_hidden()
    summary.focus()
    page.keyboard.press("Enter")
    expect(page.locator("[data-filter='status']")).to_be_visible()
    # #88 anchors the fields to the disclosure as an absolute panel, so the open
    # panel overlays the register instead of pushing it: what must hold is that the
    # fields are painted, inside the viewport, and that their own controls are
    # reachable at their centres.
    assert fields.bounding_box() and _centre_is_reachable(page, page.locator("[data-filter='status']")), fields
    page.locator("[data-filter='status']").select_option("running")
    expect(page.locator(".task-card")).to_have_count(0)
    expect(summary).to_have_text("Filters & order · active")
    for control in ("[data-filter='status']", "[data-filter='sort']"):
        box = page.locator(control).bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= width, (control, box)
    summary.click()
    expect(fields).to_be_hidden()
    page.get_by_role("button", name="Compact", exact=True).click()
    expect(page.locator(".task-card")).to_have_count(0)
    summary.click()
    expect(fields).to_be_visible()
    expect(page.locator("[data-filter='status']")).to_have_value("running")
    page.locator("[data-filter='status']").select_option("")
    summary.click()
    expect(fields).to_be_hidden()
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
    heading = page.locator(".task-card h2").bounding_box()
    assert box and heading
    # Wider font metrics re-lay the masthead, but the register still leads with the
    # work: the first Task identity is the head of the first register row, every page
    # action stays inside its own group rather than spilling out of the page, and the
    # reflowed masthead still fits above the first row.
    row = page.locator(".task-card").first.bounding_box()
    assert row
    assert 0 < heading["y"] - row["y"] < 40, (heading, row)
    for control in actions.locator(":scope > *").all():
        if not control.is_visible():
            # #88 withdraws the register's tour entry below the container breakpoint
            # rather than reflowing it, so an invisible action is not a target a
            # reader can reach or miss; the entry itself is asserted reachable at
            # every width by the register's own navigation and tour cases.
            assert control.evaluate("node => getComputedStyle(node).display") == "none"
            continue
        target = control.bounding_box()
        assert target and target["height"] >= 44, (control, target)
        assert target["x"] >= box["x"] and target["x"] + target["width"] <= box["x"] + box["width"] + 1, target
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def _overflow(page: Page) -> int:
    return page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )


@pytest.mark.parametrize("width", [320, 375])
def test_dense_table_layout_keeps_the_page_within_the_viewport(page: Page, width: int) -> None:
    _mount_dense_admin_dashboard(page, width, 30)
    page.get_by_role("button", name="Table", exact=True).click()
    expect(page.locator(".task-table tbody tr")).to_have_count(30)
    # The visually hidden Actions heading is absolutely positioned, so without a
    # positioned ancestor it escapes the Table's own horizontal scroll container
    # and stretches the document past the viewport. The overflow is measurable,
    # not inferred: the page must not scroll sideways at all.
    assert _overflow(page) == 0
    # Clipping the label must not remove it: the Actions cells still need their
    # heading in the accessibility tree.
    heading = page.get_by_role("columnheader", name="Actions", exact=True)
    expect(heading).to_have_count(1)
    assert heading.evaluate("node => !!(node.getClientRects().length)")


@pytest.mark.parametrize("width", [320, 375, 768, 1280])
def test_card_layouts_keep_the_page_within_the_viewport(page: Page, width: int) -> None:
    # The Table gained a positioned ancestor; the card layouts must stay equally
    # clean at every width they are offered.
    _mount_dense_admin_dashboard(page, width, 30)
    assert _overflow(page) == 0
    page.get_by_role("button", name="Compact", exact=True).click()
    expect(page.locator(".task-card")).to_have_count(30)
    assert _overflow(page) == 0


@pytest.mark.parametrize("width", [320, 1280])
def test_invalid_search_pattern_error_is_announced_by_a_pre_existing_live_region(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 780})
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card")).to_be_visible()
    # The region has to exist before the message so assistive technology
    # receives the update; a region created alongside its text is silent.
    region = page.locator("[data-query-error]")
    expect(region).to_have_count(1)
    expect(region).to_have_role("status")
    assert region.evaluate("node => node.closest('[aria-live]') !== null")
    expect(region).to_be_empty()
    if not page.locator("[data-filter='status']").is_visible():
        page.locator(".dashboard-filters > summary").click()
    if not page.locator("[data-toggle-regex]").is_visible():
        page.locator("[data-advanced]").click()
    page.locator("[data-toggle-regex]").click()
    page.locator("[data-filter='search']").fill("[")
    expect(region).to_have_text("Invalid regular expression")
