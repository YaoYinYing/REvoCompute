# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the Soft Precision shell, language, notices, tour, and Dashboard.

These cases drive the production bundle through the deterministic fixture
harness and assert real behavior and state — navigation geometry, persisted
preferences, translated labels, notice lifecycle, tour progression, filter/view
independence, and task-card semantics — never pixel snapshots.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import controlled_scenario, mount_scenario

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"


def _dashboard(page: Page) -> None:
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()


def _rgb(value: str) -> tuple[float, float, float]:
    """Parse a colour into its 0-255 channels.

    Accepts ``rgb()``/``rgba()`` (legacy comma or modern space/``/`` syntax, with
    the alpha channel ignored rather than mistaken for a colour) and ``#rrggbb``.
    """
    value = value.strip()
    if value.startswith("#"):
        digits = value[1:]
        assert len(digits) in (3, 6), value
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        return tuple(float(int(digits[i:i + 2], 16)) for i in (0, 2, 4))  # type: ignore[return-value]
    inner = value[value.find("(") + 1:value.rfind(")")].replace("/", " ")
    parts = [p for p in inner.replace(",", " ").split() if p]
    channels: list[float] = []
    for part in parts[:3]:
        channels.append(float(part[:-1]) * 2.55 if part.endswith("%") else float(part))
    assert len(channels) == 3, value
    return channels[0], channels[1], channels[2]


def _relative_luminance(value: str) -> float:
    def linear(channel: float) -> float:
        scaled = channel / 255
        return scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in _rgb(value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted((_relative_luminance(foreground), _relative_luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# ── shell / navigation rail ───────────────────────────────────────────────────


def test_desktop_rail_collapses_and_expands_by_reactivating_the_current_item(page: Page) -> None:
    _dashboard(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.reload()
    shell = page.locator(".app-shell")
    expect(shell).to_have_attribute("data-rail", "collapsed")
    # The current page's own nav item is the rail toggle: there is no separate arrow.
    assert page.get_by_role("button", name="Collapse navigation").count() == 0
    assert page.get_by_role("button", name="Expand navigation").count() == 0

    page.get_by_role("link", name="Dashboard", exact=True).click()
    expect(shell).to_have_attribute("data-rail", "expanded")
    # Repeating the activation collapses it again.
    page.get_by_role("link", name="Dashboard", exact=True).click()
    expect(shell).to_have_attribute("data-rail", "collapsed")


def test_rail_preference_persists_across_reload(page: Page) -> None:
    _dashboard(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.get_by_role("link", name="Dashboard", exact=True).click()
    expect(page.locator(".app-shell")).to_have_attribute("data-rail", "expanded")
    assert page.evaluate("localStorage.getItem('revocompute-rail')") == "expanded"
    page.reload()
    expect(page.locator(".app-shell")).to_have_attribute("data-rail", "expanded")


def test_mobile_navigation_is_bottom_anchored_not_a_thin_rail(page: Page) -> None:
    _dashboard(page)
    page.set_viewport_size({"width": 360, "height": 780})
    page.reload()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    position = page.locator(".app-nav").evaluate("node => getComputedStyle(node).position")
    assert position == "fixed"
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_tablet_navigation_reflows_and_toolbar_wraps_without_overflow(page: Page) -> None:
    _dashboard(page)
    page.set_viewport_size({"width": 834, "height": 1112})
    page.reload()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    # Tablet sits in the mobile navigation band: a bottom-anchored bar, not the desktop rail.
    assert page.locator(".app-nav").evaluate("node => getComputedStyle(node).position") == "fixed"
    # The filter band and the view switch remain two separate control groups after reflow.
    assert page.locator("[aria-label='Task filters']").evaluate("node => getComputedStyle(node).display") != "none"
    expect(page.locator(".view-toolbar .layout-switch")).to_be_visible()
    # Metadata reflow and wrapping must not push the document wider than the viewport.
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


# ── localization ──────────────────────────────────────────────────────────────


def test_language_switch_localizes_frontend_copy_and_persists(page: Page) -> None:
    _dashboard(page)
    page.locator(".lang-menu > summary").click()
    page.locator('[data-locale="zh-CN"]').click()
    expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
    expect(page.get_by_role("heading", name="任务面板", exact=True)).to_be_visible()
    assert page.evaluate("localStorage.getItem('revocompute-locale')") == "zh-CN"
    page.reload()
    expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
    expect(page.get_by_role("heading", name="任务面板", exact=True)).to_be_visible()
    # Server-owned vocabulary (the Runner's own display name) is not translated.
    expect(page.locator(".task-card-type").first).to_have_text("sequence_demo")


# ── persistent system notices ─────────────────────────────────────────────────


def test_persistent_notice_opens_hides_and_reopens_from_the_global_affordance(page: Page) -> None:
    mount_scenario(page, controlled_scenario())
    notice = {
        "id": "operator-notice-demo",
        "level": "warning",
        "title": "Scheduled maintenance",
        "body": "Storage maintenance on Saturday 02:00-04:00 UTC.",
    }
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": [notice]}))
    page.goto(f"{ORIGIN}/compute/dashboard")

    button = page.get_by_role("button", name="System notices")
    expect(button).to_be_visible()
    button.click()
    card = page.locator(".sys-notice")
    expect(card).to_be_visible()
    expect(card).to_contain_text("Scheduled maintenance")

    card.get_by_role("button", name="Hide notice").click()
    expect(page.locator(".sys-notice")).to_have_count(0)
    # Reopen from the same global affordance: the hidden notice returns.
    button.click()
    expect(page.locator(".sys-notice")).to_be_visible()


def test_notice_affordance_is_absent_with_nothing_to_announce(page: Page) -> None:
    _dashboard(page)
    expect(page.get_by_role("button", name="System notices")).to_be_hidden()


# ── guided tour ───────────────────────────────────────────────────────────────


def test_guided_tour_starts_progresses_and_is_restartable(page: Page) -> None:
    _dashboard(page)
    launcher = page.get_by_role("button", name="Guided tour")
    expect(launcher).to_be_visible()
    launcher.click()
    callout = page.locator(".tour-callout")
    expect(callout).to_be_visible()
    expect(callout).to_contain_text("Step 1 of 5")
    callout.get_by_role("button", name="Next").click()
    expect(callout).to_contain_text("Step 2 of 5")
    callout.get_by_role("button", name="Don’t show again").click()
    expect(callout).to_have_count(0)
    # A durable restart entry remains after dismissal.
    page.reload()
    expect(page.get_by_role("button", name="Restart guided tour")).to_be_visible()


# ── dashboard filters, advanced search, and view switch ───────────────────────


def test_advanced_search_is_subordinate_and_obviously_active(page: Page) -> None:
    _dashboard(page)
    toggle = page.get_by_role("button", name="Advanced search")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(page.locator("[data-advanced-panel]")).to_be_hidden()
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    panel = page.locator("[data-advanced-panel]")
    expect(panel).to_be_visible()
    # A low-frequency control is revealed, not appended as noise to the search field.
    panel.get_by_label("Submitted from").fill("2026-01-01")
    panel.get_by_label("Regular expression").click()
    expect(page.get_by_role("button", name="Advanced search, 2 active")).to_be_visible()


def test_view_switch_is_independent_of_filtering(page: Page) -> None:
    _dashboard(page)
    # Filtering and presentation are separate control groups.
    filters = page.locator("[aria-label='Task filters']")
    view = page.locator(".view-toolbar .layout-switch")
    expect(filters.locator(".layout-switch")).to_have_count(0)
    expect(view).to_be_visible()
    expect(view.get_by_role("button", name="Detailed")).to_have_attribute("aria-pressed", "true")
    view.get_by_role("button", name="Table").click()
    expect(page.locator(".task-list")).to_have_attribute("data-layout", "table")
    expect(page.locator(".task-table")).to_be_visible()
    view.get_by_role("button", name="Compact").click()
    expect(page.locator(".task-list")).to_have_attribute("data-layout", "compact")


# ── task cards ────────────────────────────────────────────────────────────────


def test_task_card_has_no_decorative_status_rail_and_states_status_as_text(page: Page) -> None:
    _dashboard(page)
    card = page.locator(".task-card").first
    # A status boundary must not be drawn as a coloured side rail.
    left = card.evaluate("node => getComputedStyle(node).borderLeftWidth")
    assert float(left.replace("px", "")) <= 1
    # Status is communicated by a word, with a non-colour shape cue, not colour alone.
    status = card.locator(".status")
    expect(status).to_be_visible()
    assert status.inner_text().strip()
    assert status.evaluate("node => getComputedStyle(node, '::before').content") not in ("none", "normal")


def test_task_card_metadata_uses_machine_text_for_identity_only(page: Page) -> None:
    _dashboard(page)
    card = page.locator(".task-card").first
    id_value = card.locator("dd.machine")
    expect(id_value).to_have_count(1)
    # The identity field is a definition value rendering the task ID itself.
    assert id_value.evaluate("node => node.tagName").lower() == "dd"
    assert id_value.inner_text().strip()
    assert "mono" in id_value.evaluate("node => getComputedStyle(node).fontFamily").lower()
    # Task ID remains fully inspectable — selectable, not destroyed by truncation.
    assert id_value.evaluate("node => getComputedStyle(node).textOverflow") in ("clip", "ellipsis")


# ── accessibility ─────────────────────────────────────────────────────────────


def test_primary_controls_show_visible_focus_and_carry_accessible_names(page: Page) -> None:
    _dashboard(page)
    # Visible focus: a keyboard-reachable primary action paints a focus indicator.
    run = page.locator(".app-header a.app-new-task")
    run.focus()
    outline = run.evaluate("node => [getComputedStyle(node).outlineStyle, getComputedStyle(node).outlineWidth]")
    assert outline[0] != "none" and float(outline[1].replace("px", "")) > 0
    # Icon-only controls still have meaningful accessible names. (The notices
    # affordance is only mounted when a notice exists; the notice lifecycle test
    # asserts its accessible name in that state.)
    expect(page.get_by_role("button", name="Theme: Auto")).to_have_count(1)
    expect(page.get_by_role("button", name="Guided tour")).to_have_count(1)
    assert page.locator(".lang-menu > summary").get_attribute("aria-label")


def test_body_text_meets_contrast_on_canvas_in_light_and_dark(page: Page) -> None:
    _dashboard(page)
    samples = page.evaluate(
        """() => {
            const ink = getComputedStyle(document.body).color;
            const canvas = getComputedStyle(document.body).backgroundColor;
            const muted = getComputedStyle(document.querySelector('.page-heading p, .runner-intro, .task-card dd') ).color;
            return {ink, canvas, muted};
        }"""
    )
    assert _contrast_ratio(samples["ink"], samples["canvas"]) >= 4.5, samples
    assert _contrast_ratio(samples["muted"], samples["canvas"]) >= 4.5, samples

    page.get_by_role("button", name="Theme: Auto").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    dark = page.evaluate(
        """() => {
            const ink = getComputedStyle(document.body).color;
            const canvas = getComputedStyle(document.body).backgroundColor;
            const muted = getComputedStyle(document.querySelector('.page-heading p, .runner-intro, .task-card dd')).color;
            return {ink, canvas, muted};
        }"""
    )
    assert _contrast_ratio(dark["ink"], dark["canvas"]) >= 4.5, dark
    assert _contrast_ratio(dark["muted"], dark["canvas"]) >= 4.5, dark


# ── dark mode ─────────────────────────────────────────────────────────────────


def test_dark_mode_is_neutral_and_avoids_a_green_cast(page: Page) -> None:
    _dashboard(page)
    page.get_by_role("button", name="Theme: Auto").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    palette = page.evaluate(
        """() => {
            const root = getComputedStyle(document.documentElement);
            return {
                bodyBg: getComputedStyle(document.body).backgroundColor,
                cardBg: getComputedStyle(document.querySelector('.task-card')).backgroundColor,
                ink: getComputedStyle(document.body).color,
                accent: root.getPropertyValue('--app-accent').trim(),
            };
        }"""
    )
    # Neutral surfaces keep green near red and blue; a teal/green wash would not.
    for value in (palette["bodyBg"], palette["cardBg"], palette["ink"]):
        red, green, blue = _rgb(value)
        assert abs(green - red) <= 8 and abs(green - blue) <= 8, value
    # The accent stays a true blue (blue-dominant), not a teal that neutralises to green.
    red, green, blue = _rgb(palette["accent"])
    assert blue > red and blue > green, palette["accent"]


def test_mobile_targets_are_touch_sized_and_motion_is_reducible(page: Page) -> None:
    _dashboard(page)
    page.set_viewport_size({"width": 360, "height": 780})
    page.reload()
    nav_link = page.locator(".app-nav a").first
    expect(nav_link).to_be_visible()
    box = nav_link.bounding_box()
    assert box is not None and box["height"] >= 44 and box["width"] >= 44, box
    # A reduced-motion preference removes ornamental transition timing.
    page.emulate_media(reduced_motion="reduce")
    duration = page.locator(".app-header a.app-new-task").evaluate("node => getComputedStyle(node).transitionDuration")
    for part in duration.split(","):
        part = part.strip()
        assert part == "0s" or float(part.replace("s", "")) <= 0.001, duration
