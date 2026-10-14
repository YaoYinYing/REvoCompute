# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the Account Quota page.

The Quota page is the reader's own resource position. It is now wired into the
application: a destination of the Account region in the shell's left navigation,
its own protected route and address (``/compute/quota``), and its own place in
the router's route switch.

These cases drive the production bundle through the deterministic fixture
harness and state the integration's own contracts, from the reader's point of
view: the Account sidebar link reaches the page by an in-document navigation, the
page renders the account's own position from the endpoints scoped to it, a hard
refresh of the page's own address serves the same page rather than a 404, the
history stack returns to it, and a signed-in non-administrator reaches their own
quota. Every assertion is made on observable browser state - the URL, the
requests the browser actually issued, the live DOM, and focus - never on a source
file.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import ADMIN_AUTH, USER_AUTH, controlled_scenario, mount_scenario

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"


def _install_quota_reads(page: Page, subject_id: int) -> None:
    """Serve the account's own canonical position from its own endpoints."""
    from frontend_fixtures import builders

    page.route(
        f"{ORIGIN}/compute/api/resource-entitlement",
        lambda route: route.fulfill(json=builders.build_resource_entitlement(subject_id)),
    )
    page.route(
        f"{ORIGIN}/compute/api/resource-ledger**",
        lambda route: route.fulfill(json=builders.build_resource_ledger(subject_id)),
    )


def test_the_quota_page_is_a_sidebar_destination_with_a_real_address(page: Page) -> None:
    """Account -> Quota in the sidebar, in-document, and the page's own address."""
    from frontend_fixtures import builders

    router = mount_scenario(page, controlled_scenario())
    subject = builders.subject_id_for(controlled_scenario().session)
    _install_quota_reads(page, subject)
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()

    # The Account region's Quota link reaches the page without loading a document.
    page.locator("[data-nav-group='account']").get_by_role("link", name="Quota", exact=True).click()
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()
    expect(page).to_have_title("Quota | REvoCompute")
    assert page.url == f"{ORIGIN}/compute/quota"
    # The page renders the account's own position, not a placeholder.
    expect(page.locator(".quota-position")).to_be_visible()
    expect(page.get_by_text("Usage against allowance")).to_be_visible()
    expect(page.locator(".quota-bar")).to_have_count(1)
    expect(page.locator(".quota-unattributed")).to_have_count(1)
    # The shell marks exactly this destination current, and only the first
    # document was ever requested: the link was an in-document navigation.
    expect(
        page.locator("[data-nav-group='account'] a[aria-current='page']")
    ).to_have_attribute("href", "/compute/quota")
    assert [record.path for record in router.requests.navigation()] == ["/compute/dashboard"]
    assert router.requests.matching("/compute/api/resource-entitlement")
    assert router.requests.matching("/compute/api/resource-ledger")


def test_a_hard_refresh_of_the_quota_page_serves_the_same_page(page: Page) -> None:
    """A direct load / refresh of /compute/quota resolves to the real page."""
    from frontend_fixtures import builders

    mount_scenario(page, controlled_scenario())
    subject = builders.subject_id_for(controlled_scenario().session)
    _install_quota_reads(page, subject)

    # A hard load of the address (as a refresh or a shared link does): the server
    # serves the entry document and the router resolves the page's own route.
    page.goto(f"{ORIGIN}/compute/quota")
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()
    expect(page.locator(".quota-position")).to_be_visible()

    # A real refresh rebuilds the page from the same address.
    page.reload()
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()
    expect(page.locator(".quota-position")).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/quota"


def test_history_back_and_forward_return_to_the_quota_page(page: Page) -> None:
    """The page's address is a real history entry, not a transient render."""
    from frontend_fixtures import builders

    mount_scenario(page, controlled_scenario())
    subject = builders.subject_id_for(controlled_scenario().session)
    _install_quota_reads(page, subject)

    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    page.locator("[data-nav-group='account']").get_by_role("link", name="Quota", exact=True).click()
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()

    page.go_back()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/dashboard"
    page.go_forward()
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/quota"


def test_the_chinese_catalog_renders_the_quota_page(page: Page) -> None:
    """The nav label and the page are authored copy in both catalogs."""
    from frontend_fixtures import builders

    mount_scenario(page, controlled_scenario())
    subject = builders.subject_id_for(controlled_scenario().session)
    _install_quota_reads(page, subject)
    page.add_init_script("localStorage.setItem('revocompute-locale', 'zh-CN')")

    page.goto(f"{ORIGIN}/compute/quota")
    expect(page.get_by_role("heading", name="资源配额", exact=True)).to_be_visible()
    expect(page.get_by_text("已用额度与总量")).to_be_visible()
    # The Account region's own destination is localized, not left English.
    expect(
        page.locator("[data-nav-group='account']").get_by_role("link", name="资源配额", exact=True)
    ).to_be_visible()


@pytest.mark.parametrize("session", [USER_AUTH, ADMIN_AUTH], ids=["user", "admin"])
def test_a_signed_in_reader_reaches_their_own_quota(page: Page, session) -> None:
    """A non-administrator reaches their own quota; an administrator's does too."""
    from frontend_fixtures import builders

    mount_scenario(page, controlled_scenario(session=session))
    subject = builders.subject_id_for(session)
    _install_quota_reads(page, subject)

    page.goto(f"{ORIGIN}/compute/dashboard")
    page.locator("[data-nav-group='account']").get_by_role("link", name="Quota", exact=True).click()
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()
    expect(page.locator(".quota-position")).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/quota"
