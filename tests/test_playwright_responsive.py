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

    # One dense toolbar: the primary controls wrap into shared rows instead of
    # each control taking a full-width row of its own.
    row_tops = page.locator(
        ".task-name-filter, .status-filter, .task-type-filter, #taskSort, .layout-control"
    ).evaluate_all("nodes => nodes.map(node => Math.round(node.getBoundingClientRect().top))")
    assert 1 < len(set(row_tops)) < len(row_tops), row_tops

    toolbar = page.locator(".controls .ui-toolbar")
    assert toolbar.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
    _assert_contained(page, ".controls .ui-toolbar > *", 834)

    # Secondary filters stay reachable behind the disclosure.
    assert page.locator("#finishFrom").is_hidden()
    page.locator(".filters-disclosure > summary").click()
    expect(page.locator("#finishFrom")).to_be_visible()
    _assert_contained(page, ".filters-extra > *", 834)

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


SEARCH_PAGES = [
    ("user_control.html", "user-control.css"),
    ("configuration.html", "configuration.css"),
    ("runners.html", "runners.css"),
    ("create_task.html", "create-task.css"),
]


def _search_metrics(page: Page) -> dict:
    return page.locator(".ui-search input.search-input").first.evaluate(
        "node => { const s = getComputedStyle(node); const r = node.getBoundingClientRect();"
        " return {height: Math.round(r.height), minHeight: s.minHeight, radius: s.borderRadius,"
        " paddingLeft: s.paddingLeft, paddingRight: s.paddingRight, fontSize: s.fontSize,"
        " fontFamily: s.fontFamily, backgroundImage: s.backgroundImage, borderWidth: s.borderWidth}; }"
    )


@pytest.mark.parametrize("template,stylesheet", SEARCH_PAGES)
@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_search_controls_share_one_component(page: Page, template: str, stylesheet: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(_template(template))
    _add_styles(page, stylesheet)

    control = page.locator(".ui-search").first
    expect(control).to_be_visible()
    _assert_contained(page, ".ui-search", width)
    _assert_no_document_overflow(page)

    metrics = _search_metrics(page)
    assert metrics["radius"] == "12px", metrics
    assert metrics["minHeight"] == "37.6px", metrics
    assert 34 <= metrics["height"] <= 44, metrics
    assert float(metrics["paddingLeft"][:-2]) > float(metrics["paddingRight"][:-2]), metrics
    assert "svg" in metrics["backgroundImage"], metrics

    # Keyboard focus stays visible on the shared control.
    field = page.locator(".ui-search input.search-input").first
    field.focus()
    focus_ring = field.evaluate("node => getComputedStyle(node).boxShadow")
    assert focus_ring not in ("", "none"), focus_ring


def _canonical_search_metrics(page: Page) -> dict:
    metrics = _search_metrics(page)
    metrics.pop("height")
    return metrics


def test_user_control_and_task_type_search_controls_match(page: Page) -> None:
    page.set_viewport_size({"width": 1280, "height": 900})
    page.set_content(_template("user_control.html"))
    _add_styles(page, "user-control.css")
    user_metrics = _canonical_search_metrics(page)

    page.set_content(_template("configuration.html"))
    _add_styles(page, "configuration.css")
    task_type_metrics = _canonical_search_metrics(page)

    assert user_metrics == task_type_metrics, (user_metrics, task_type_metrics)


def _open_create_task_workbench(page: Page, width: int, method_name: str) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(_template("create_task.html"))
    _add_styles(page, "create-task.css")
    page.evaluate(
        """name => {
          document.getElementById("methodChooser").hidden = true;
          document.getElementById("experimentWorkbench").hidden = false;
          document.getElementById("activeTaskCategory").textContent = "structure_prediction";
          document.getElementById("activeTaskName").textContent = name;
          document.getElementById("taskSummary").textContent = "A scientific summary that wraps at narrow widths.";
          document.getElementById("taskAccelerator").textContent = "GPU method";
          document.getElementById("taskDetails").textContent = "About this method →";
        }""",
        method_name,
    )


@pytest.mark.parametrize("width", [834, 390, 1440, 2560])
def test_create_task_form_owns_the_page_and_review_sits_by_the_run_action(page: Page, width: int) -> None:
    _open_create_task_workbench(page, width, "Fold")

    # No vertical protocol rail and no standalone readiness side panel.
    assert page.locator(".protocol-track, .readiness-panel").count() == 0
    expect(page.locator("#validationChecks")).to_be_attached()
    expect(page.locator("#validationSummary")).to_be_attached()

    form_box = page.locator(".experiment-form-panel").bounding_box()
    page_box = page.locator(".experiment-page").bounding_box()
    assert form_box["width"] >= page_box["width"] - 2, (form_box, page_box)

    # Validation and the Run action are one submission flow, review above run.
    readiness = page.locator(".submission-readiness").bounding_box()
    run = page.locator(".run-actions").bounding_box()
    assert run["y"] >= readiness["y"] - 1, (readiness, run)
    assert run["y"] <= readiness["y"] + readiness["height"], (readiness, run)
    _assert_no_document_overflow(page)


@pytest.mark.parametrize("width", [390, 768, 1280, 1440])
def test_create_task_method_header_groups_runtime_docs_and_switching(page: Page, width: int) -> None:
    _open_create_task_workbench(page, width, "Fold")

    actions = page.locator(".method-actions")
    expect(actions.locator("#taskAccelerator")).to_be_visible()
    expect(actions.locator("#taskDetails")).to_be_visible()
    expect(actions.locator("#changeMethod")).to_be_visible()
    _assert_contained(page, ".method-actions", width)
    _assert_no_document_overflow(page)

    short_box = page.locator("#changeMethod").bounding_box()
    _open_create_task_workbench(page, width, "A" * 120)
    long_box = page.locator("#changeMethod").bounding_box()
    # A long method name must not stretch the control.
    assert abs(short_box["width"] - long_box["width"]) <= 1, (short_box, long_box)
    assert abs(short_box["height"] - long_box["height"]) <= 1, (short_box, long_box)
    _assert_no_document_overflow(page)

    if width <= 720:
        # Narrow screens stack the action column below the method identity.
        identity_bottom = page.locator(".method-identity").bounding_box()["y"] + page.locator(
            ".method-identity"
        ).bounding_box()["height"]
        assert actions.bounding_box()["y"] >= identity_bottom - 1
        actions_width = actions.bounding_box()["width"]
        assert long_box["width"] >= actions_width - 1, (long_box, actions_width)
    else:
        # Desktop keeps the action column beside the identity, not stacked.
        assert short_box["width"] <= 220, short_box
        identity = page.locator(".method-identity").bounding_box()
        actions_box = actions.bounding_box()
        assert actions_box["x"] >= identity["x"] + identity["width"] - 1, (identity, actions_box)
        assert short_box["width"] < actions_box["width"], (short_box, actions_box)
