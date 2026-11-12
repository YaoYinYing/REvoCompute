# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the signed-in Version page.

The page is a destination of the Account navigation region with its own
protected address (``/compute/version``). These cases drive the production
bundle through the deterministic fixture harness and assert observable browser
state: the in-document navigation and address, the identity and changelog the
reader sees, a hard load and reload, the history stack, and a phone-width
layout that does not scroll sideways. The fixture router serves the version API
from its dispatch table, so an undeclared request still fails the test.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import builders, controlled_scenario, mount_scenario

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"


def test_the_account_navigation_reaches_the_version_page(page: Page) -> None:
    """Account -> Version is an in-document navigation to the page's own address."""
    router = mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()

    page.locator("[data-nav-group='account']").get_by_role("link", name="Version", exact=True).click()
    expect(page.get_by_role("heading", name="Version", exact=True)).to_be_visible()
    expect(page).to_have_title("Version | REvoCompute")
    assert page.url == f"{ORIGIN}/compute/version"

    # The identity and changelog are the server's own facts, in one page.
    expect(page.locator(".version-display")).to_have_text("0.1.0+2890609")
    expect(page.get_by_text("Full revision")).to_be_visible()
    expect(page.get_by_text(builders.VERSION_SHA, exact=True)).to_be_visible()
    expect(page.locator("h3").first).to_have_text("Unreleased")
    expect(page.get_by_text("Development snapshot", exact=True)).to_be_visible()
    # The fixture bundle carries the same deterministic identity as the fixture
    # server, so agreeing revisions are the normal state.
    expect(page.locator(".version-build-warning")).to_have_count(0)

    expect(
        page.locator("[data-nav-group='account'] a[aria-current='page']")
    ).to_have_attribute("href", "/compute/version")
    assert [record.path for record in router.requests.navigation()] == ["/compute/dashboard"]
    assert router.requests.matching("/compute/api/version")


def test_a_hard_load_and_refresh_serve_the_same_page(page: Page) -> None:
    """A direct load or refresh of /compute/version resolves to the real page."""
    mount_scenario(page, controlled_scenario())

    page.goto(f"{ORIGIN}/compute/version")
    expect(page.get_by_role("heading", name="Version", exact=True)).to_be_visible()
    expect(page.locator(".version-display")).to_be_visible()

    page.reload()
    expect(page.get_by_role("heading", name="Version", exact=True)).to_be_visible()
    expect(page.locator(".version-changelog")).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/version"


def test_history_returns_to_the_version_page(page: Page) -> None:
    """The page's address is a real history entry, not a transient render."""
    mount_scenario(page, controlled_scenario())

    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    page.locator("[data-nav-group='account']").get_by_role("link", name="Version", exact=True).click()
    expect(page.get_by_role("heading", name="Version", exact=True)).to_be_visible()

    page.go_back()
    expect(page.get_by_role("heading", name="Tasks", exact=True)).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/dashboard"
    page.go_forward()
    expect(page.get_by_role("heading", name="Version", exact=True)).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/version"


def test_a_phone_width_version_page_does_not_scroll_sideways(page: Page) -> None:
    """The long revision and changelog text wrap inside the page."""
    page.set_viewport_size({"width": 390, "height": 844})
    mount_scenario(page, controlled_scenario())

    page.goto(f"{ORIGIN}/compute/version")
    expect(page.get_by_role("heading", name="Version", exact=True)).to_be_visible()
    expect(page.locator(".version-changelog")).to_be_visible()

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert page.evaluate("document.body.scrollWidth <= window.innerWidth + 1")


def test_a_mixed_deployment_is_diagnosed_with_a_reload(page: Page) -> None:
    """Two verified and different revisions are a visible diagnostic, not a match."""
    mount_scenario(page, controlled_scenario())
    page.route(
        f"{ORIGIN}/compute/api/version",
        lambda route: route.fulfill(
            json=builders.build_version_info(git_sha="c" * 40, app_version="0.1.0+ccccccc")
        ),
    )

    page.goto(f"{ORIGIN}/compute/version")
    expect(page.locator(".version-display")).to_have_text("0.1.0+ccccccc")
    warning = page.locator(".version-build-warning")
    expect(warning).to_be_visible()
    expect(warning).to_have_attribute("role", "alert")
    expect(warning.get_by_text("mixed or stale assets")).to_be_visible()
    expect(warning.get_by_role("button", name="Reload")).to_be_visible()


def test_an_unverified_server_revision_is_stated_honestly(page: Page) -> None:
    """A build without a verified commit says so instead of inventing one."""
    mount_scenario(page, controlled_scenario())
    page.route(
        f"{ORIGIN}/compute/api/version",
        lambda route: route.fulfill(
            json=builders.build_version_info(
                git_sha=None,
                revision_status="unknown",
                app_version="0.1.0+unknown",
                built_at=None,
            )
        ),
    )

    page.goto(f"{ORIGIN}/compute/version")
    expect(page.locator(".version-display")).to_have_text("0.1.0+unknown")
    expect(page.get_by_text("Not recorded").first).to_be_visible()
    expect(page.locator(".version-build-note")).to_contain_text("cannot be confirmed as equal")


def test_the_version_page_renders_under_the_dark_theme(page: Page) -> None:
    """The page follows the deployment's dark theme, not only the light one."""
    page.emulate_media(color_scheme="dark")
    mount_scenario(page, controlled_scenario())

    page.goto(f"{ORIGIN}/compute/version")
    expect(page.get_by_role("heading", name="Version", exact=True)).to_be_visible()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(page.locator(".version-display")).to_be_visible()
    expect(page.locator(".version-changelog")).to_be_visible()
