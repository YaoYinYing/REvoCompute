# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Responsive-layout browser contracts.

Covers the known tablet/mobile regressions: discoverable navigation, a Runner
filter that stays in normal flow, compact Dashboard controls, and Runner cards
that wrap long names.  Assertions are semantic and geometric, matching the
repository's existing browser-test convention.
"""

from __future__ import annotations

from pathlib import Path
import re

from playwright.sync_api import Page, expect
import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "revocompute" / "static" / "css"
TEMPLATES = ROOT / "revocompute" / "templates"


def _template(name: str) -> str:
    source = (TEMPLATES / name).read_text(encoding="utf-8")
    source = re.sub(r'<script[^>]+src="[^"]+"[^>]*></script>', "", source)
    source = re.sub(r"{{.*?}}", "Example", source, flags=re.DOTALL)
    return re.sub(r"{%-?.*?-?%}", "", source, flags=re.DOTALL)


def _add_styles(page: Page, *names: str) -> None:
    page.add_style_tag(path=CSS / "base.css")
    for name in names:
        page.add_style_tag(path=CSS / name)


def _assert_no_document_overflow(page: Page) -> None:
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def _assert_contained(page: Page, selector: str, width: int) -> None:
    boxes = page.locator(selector).evaluate_all(
        "nodes => nodes.map(node => { const r = node.getBoundingClientRect(); return [r.left, r.right]; })"
    )
    assert boxes, selector
    for left, right in boxes:
        assert left >= -1, (selector, left, right)
        assert right <= width + 1, (selector, left, right)


@pytest.mark.parametrize("template", ["index.html", "runners.html", "api_docs.html"])
@pytest.mark.parametrize("width", [320, 390, 768, 1024])
def test_landing_navigation_stays_discoverable_at_narrow_widths(page: Page, template: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(_template(template))
    _add_styles(page, "index.css", "runners.css")

    toggle = page.locator(".nav-menu-toggle")
    expect(toggle).to_be_visible()
    checkbox = page.get_by_role("checkbox", name="More navigation")
    expect(checkbox).to_be_visible()
    expect(checkbox).not_to_be_checked()
    expect(page.locator(".nav-links")).to_be_hidden()

    toggle.click()
    expect(checkbox).to_be_checked()
    expect(page.locator(".nav-menu .nav-links")).to_be_visible()
    expect(page.locator(".nav-links").get_by_role("link").first).to_be_visible()
    _assert_contained(page, ".nav-menu .nav-links", width)
    _assert_contained(page, ".nav-menu .nav-links a", width)
    _assert_no_document_overflow(page)


def test_landing_navigation_is_keyboard_operable(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 900})
    page.set_content(_template("runners.html"))
    _add_styles(page, "index.css", "runners.css")

    checkbox = page.get_by_role("checkbox", name="More navigation")
    checkbox.focus()
    page.keyboard.press("Space")
    expect(checkbox).to_be_checked()
    expect(page.locator(".nav-menu .nav-links")).to_be_visible()
    assert page.locator(".nav-menu-toggle").evaluate("node => getComputedStyle(node).outlineStyle") != "none"


def test_landing_navigation_links_remain_inline_on_desktop(page: Page) -> None:
    page.set_viewport_size({"width": 1366, "height": 900})
    page.set_content(_template("runners.html"))
    _add_styles(page, "index.css", "runners.css")

    expect(page.locator(".nav-links")).to_be_visible()
    expect(page.locator(".nav-menu-toggle")).to_be_hidden()
    _assert_no_document_overflow(page)


@pytest.mark.parametrize("width", [834, 620, 390])
def test_runner_toolbar_leaves_the_catalog_in_normal_flow(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(_template("runners.html"))
    _add_styles(page, "index.css", "runners.css")

    position = page.locator(".runner-toolbar").evaluate("node => getComputedStyle(node).position")
    assert position == "static", position
    toolbar_bottom = page.locator(".runner-toolbar").bounding_box()["y"] + page.locator(
        ".runner-toolbar"
    ).bounding_box()["height"]
    card_top = page.locator(".runner-card").first.bounding_box()["y"]
    assert card_top >= toolbar_bottom - 1, (card_top, toolbar_bottom)
    _assert_no_document_overflow(page)


def test_dashboard_controls_share_rows_at_tablet_width(page: Page) -> None:
    page.set_viewport_size({"width": 834, "height": 1200})
    page.set_content(_template("dashboard.html"))
    _add_styles(page, "dashboard.css")

    # Non-admin: no selection controls, so the view row uses the full width.
    content_width = page.locator(".controls").evaluate(
        "node => { const s = getComputedStyle(node);"
        " return node.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight); }"
    )
    view_width = page.locator(".view-controls").bounding_box()["width"]
    assert view_width >= content_width - 2, (view_width, content_width)

    page.locator("#adminTools").evaluate("node => node.hidden = false")
    view_top, selection_top = page.locator(".view-controls, .selection-controls").evaluate_all(
        "nodes => nodes.map(node => Math.round(node.getBoundingClientRect().top))"
    )
    assert abs(view_top - selection_top) <= 1, (view_top, selection_top)

    # Empty per-field error rows must not reserve vertical space.
    assert page.locator(".filter-error:visible").count() == 0
    assert page.locator(".controls").evaluate("node => node.scrollWidth <= node.clientWidth + 1")
    _assert_no_document_overflow(page)


@pytest.mark.parametrize("density", ["comfortable", "compact"])
@pytest.mark.parametrize("width", [320, 390, 834])
def test_method_cards_wrap_unbroken_runner_names(page: Page, width: int, density: str) -> None:
    long_name = "A" * 120
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(
        f"<main class='experiment-page'><section class='method-groups' data-density='{density}'>"
        "<div class='method-grid'>"
        f"<button class='method-card'><strong>{long_name}</strong>"
        "<span>A long scientific description that should wrap rather than force the card to overflow its grid track.</span>"
        "<small class='access-state'>Restricted family</small></button>"
        "</div></section></main>"
    )
    _add_styles(page, "create-task.css")

    card = page.locator(".method-card")
    expect(card).to_be_visible()
    assert card.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
    assert page.locator(".method-card strong").evaluate("node => node.scrollWidth <= node.clientWidth + 1")
    _assert_no_document_overflow(page)
