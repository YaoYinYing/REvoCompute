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
    # The reader is told how many of the total the query still shows.
    expect(page.locator(".catalog-count")).to_have_text(f"{len(MEMBERS)} of {len(MEMBERS)} methods")
    expect(page.locator(".runner-group h2")).to_have_text(label)


def test_search_still_matches_the_category_slug(page: Page) -> None:
    """The category slug keeps returning its methods; the label is an addition."""
    mount_scenario(page, _scenario())
    _open_catalog(page)

    _type_in_search(page, CATEGORY_SLUG)

    expect(_cards(page)).to_have_count(len(MEMBERS))
    expect(page.locator(".catalog-count")).to_have_text(f"{len(MEMBERS)} of {len(MEMBERS)} methods")
