# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for Runner-catalog search matching the category the UI shows.

The catalog's search box advertises matching by category, and the category filter
beside it renders the server-owned ``Category.label`` - the same label the group
heading and the ``<option>`` show. Search and filter must agree about what
"category" means, so typing a category label exactly as displayed returns that
category's methods while the category slug keeps returning them.

Category labels are server-owned (``Category.label``): the test reads the label
from the rendered ``<option>`` at run time and never asserts a literal or a
translated value for it. It asserts only rendered behaviour - the rendered card
count, the rendered count line, and the rendered group heading.
"""

from __future__ import annotations

from playwright.sync_api import Locator, Page, expect
import pytest

from frontend_fixtures import RunnerDefinition, mount_scenario, runner_scenario
from test_playwright_application import _install_app

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"

# One category whose projected label is deliberately not a re-spelling of its
# identifier: the label shares no substring with the slug, with the slug's
# de-underscored form, or with any member's name, display name, or summary. A
# label-shaped query therefore cannot be satisfied by any field the catalog
# indexed before this contract except the label itself.
CATEGORY_SLUG = "protein_folding"
CATEGORY_LABEL = "Structure prediction"

MEMBERS = (
    RunnerDefinition(
        name="foldnet_alpha",
        display_name="FoldNet Alpha",
        category=CATEGORY_SLUG,
        category_label=CATEGORY_LABEL,
        summary="Predict a backbone from one sequence.",
    ),
    RunnerDefinition(
        name="foldnet_beta",
        display_name="FoldNet Beta",
        category=CATEGORY_SLUG,
        category_label=CATEGORY_LABEL,
        summary="Refine a backbone from one sequence.",
    ),
)


def _scenario():
    """Two methods in one category whose label is not a re-spelling of its slug."""
    return runner_scenario(MEMBERS[0]).with_catalog(MEMBERS[1:])


def _category_option(page: Page, slug: str) -> Locator:
    return page.locator(f".runner-toolbar select option[value='{slug}']")


def _search_box(page: Page) -> Locator:
    return page.locator(".runner-toolbar input[type=search]")


def _type_in_search(page: Page, query: str) -> None:
    _search_box(page).fill(query)


def _cards(page: Page) -> Locator:
    return page.locator(".runner-card")


def _open_catalog(page: Page) -> None:
    page.goto(f"{ORIGIN}/runners")
    expect(_category_option(page, CATEGORY_SLUG)).to_have_count(1)
    expect(_search_box(page)).to_be_visible()


def test_search_matches_the_category_label_the_catalog_displays(page: Page) -> None:
    """A label-shaped query returns the category's methods, as the filter already does.

    The label is read from the rendered option, so the contract holds for
    whatever label the server projects and is checked without asserting one. The
    label is also genuinely private to the category: no other field the catalog
    indexes contains it, so without the label in the haystack this query returns
    nothing - which is the failure the contract exists to prevent.
    """
    mount_scenario(page, _scenario())
    _open_catalog(page)

    label = _category_option(page, CATEGORY_SLUG).inner_text().strip()
    assert label, "the category option renders the server-owned label"
    # The label is private to the category: it is not a re-spelling of the slug
    # and occurs in none of the other fields the catalog indexes, so this query
    # can only ever be answered by the label the search box used to ignore.
    indexed_without_label = " ".join(
        [member.name for member in MEMBERS]
        + [member.display_name for member in MEMBERS]
        + [member.summary for member in MEMBERS]
        + [CATEGORY_SLUG, CATEGORY_SLUG.replace("_", " ")]
    ).lower()
    assert label.lower() not in indexed_without_label

    _type_in_search(page, label)

    expect(_cards(page)).to_have_count(len(MEMBERS))
    # Every method matches, so the visible aggregate is suppressed; the live line
    # still announces the full register.
    expect(page.locator(".catalog-count")).to_be_empty()
    expect(page.locator("[data-catalog-status]")).to_have_text(f"{len(MEMBERS)} methods")
    expect(page.locator(".runner-group h2")).to_have_text(label)


def test_search_still_matches_the_category_slug(page: Page) -> None:
    """The category slug keeps returning its methods; the label is an addition."""
    mount_scenario(page, _scenario())
    _open_catalog(page)

    _type_in_search(page, CATEGORY_SLUG)

    expect(_cards(page)).to_have_count(len(MEMBERS))
    expect(page.locator(".catalog-count")).to_be_empty()
    expect(page.locator("[data-catalog-status]")).to_have_text(f"{len(MEMBERS)} methods")


# ── register states ──────────────────────────────────────────────────────────

_STATE_COPY = {
    "en": {
        "all": "2 methods",
        "filtered": "1 of 2 methods",
        "zero": "0 of 2 methods",
        "no_match": "No methods match the current filters.",
        "empty": "No methods are available in this catalog.",
    },
    "zh-CN": {
        "all": "2 个方法",
        "filtered": "共 2 个方法，显示 1 个",
        "zero": "共 2 个方法，显示 0 个",
        "no_match": "没有符合当前筛选条件的方法。",
        "empty": "目录中暂无可用方法。",
    },
}


def _method(index: int) -> dict:
    return {
        "name": f"method_{index:02d}",
        "display_name": f"Method {index:02d}",
        "category": "evolution",
        "summary": f"Synthetic method {index:02d} for catalog state coverage.",
        "access": {"restricted": False, "granted": True, "request_status": None},
        "detail_url": f"/compute/api/types/method_{index:02d}",
        "parameters_url": f"/compute/api/task-parameters/method_{index:02d}",
    }


def _serve_catalog(page: Page, methods: list[dict]) -> None:
    categories = [{"name": "evolution", "label": "Evolution"}] if methods else []
    page.route(
        f"{ORIGIN}/compute/api/types",
        lambda route: route.fulfill(json={"version": 3, "categories": categories, "task_types": methods}),
    )


@pytest.mark.parametrize("locale", ["en", "zh-CN"])
def test_catalog_distinguishes_an_empty_register_from_a_filtered_no_match(page: Page, locale: str) -> None:
    """A catalog with no methods is not the same state as a filter matching none."""
    copy = _STATE_COPY[locale]
    page.add_init_script(f"localStorage.setItem('revocompute-locale', '{locale}')")
    _install_app(page)
    _serve_catalog(page, [])
    page.goto(f"{ORIGIN}/runners")

    expect(page.locator(".runner-catalog .empty-state")).to_have_text(copy["empty"])
    expect(page.locator(".catalog-count")).to_be_empty()
    expect(page.locator("[data-catalog-status]")).to_have_text(copy["empty"])


@pytest.mark.parametrize("locale", ["en", "zh-CN"])
def test_catalog_announces_state_changes_without_restating_the_full_register(page: Page, locale: str) -> None:
    """The visible aggregate appears only when rows are hidden; the live line never goes silent."""
    copy = _STATE_COPY[locale]
    page.add_init_script(f"localStorage.setItem('revocompute-locale', '{locale}')")
    _install_app(page)
    _serve_catalog(page, [_method(0), _method(1)])
    page.goto(f"{ORIGIN}/runners")

    count = page.locator(".catalog-count")
    status = page.locator("[data-catalog-status]")
    search = page.locator(".runner-toolbar input[type=search]")

    # Every method matches: the group heading carries the count, so the visible
    # aggregate is suppressed while the live line announces the register.
    expect(count).to_be_empty()
    expect(status).to_have_text(copy["all"])

    # A filter that hides rows shows and announces the aggregate.
    search.fill("method_00")
    expect(_cards(page)).to_have_count(1)
    expect(count).to_have_text(copy["filtered"])
    expect(status).to_have_text(copy["filtered"])

    # Clearing the search announces the restored register again.
    search.fill("")
    expect(count).to_be_empty()
    expect(status).to_have_text(copy["all"])

    # A filter that matches nothing counts zero and says so.
    search.fill("no-such-method")
    expect(page.locator(".runner-catalog .empty-state")).to_have_text(copy["no_match"])
    expect(count).to_have_text(copy["zero"])
    expect(status).to_have_text(copy["zero"])
