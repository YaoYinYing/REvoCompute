# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for one persistent shell and the History API router.

These cases drive the production bundle through the deterministic fixture
harness and state the router's own contracts: an in-app navigation reuses the
document and the shell rather than loading another one; the address bar and the
browser's back/forward stack hold the real page; crossing between the public
pages and the workspaces mounts the other chrome without a reload; a route change
disposes the view it replaces and announces the new page; and a navigation that
lands on the page already being read leaves an in-progress form untouched.

Every assertion is made on observable browser state - the URL, the requests the
browser actually issued, the live DOM, and focus - never on a source file.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import EXPIRED_AUTH, controlled_scenario, mount_scenario

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
RESULT_ID = controlled_scenario().task_id

# What the document itself records. A client-side route change keeps both values;
# a real document load replaces them with a fresh window, so their survival is
# the difference between the two kinds of navigation, read from the browser
# rather than inferred. The announcement recorder is installed before any route
# runs, so a live region that is created and removed within one route change is
# still observed.
PROBE = """
window.__documentIdentity = (window.__documentIdentity || 0) + 1;
window.__announcements = window.__announcements || [];
function __recordAnnouncements() {
  new MutationObserver(records => {
    for (const entry of records) for (const node of entry.addedNodes) {
      if (node.nodeType === 1 && node.matches('[data-route-announcement]')) window.__announcements.push(node.textContent);
    }
  }).observe(document.body, { childList: true, subtree: true });
}
if (document.body) __recordAnnouncements(); else document.addEventListener('DOMContentLoaded', __recordAnnouncements, { once: true });
"""

CHROME_STATE = """
() => ({
  appShell: document.querySelectorAll('.app-shell').length,
  publicHeader: document.querySelectorAll('.public-header').length,
  outlet: document.querySelector('.app-outlet, .public-outlet')?.className ?? null,
  headings: [...document.querySelectorAll('.app-outlet h1, .public-outlet h1')].map(node => node.textContent.trim()),
  mains: document.querySelectorAll('main').length,
})"""


def _probe(page: Page) -> None:
    """Record the document's own identity and every route announcement it makes."""
    page.add_init_script(PROBE)


def _document_identity(page: Page) -> int:
    value = page.evaluate("window.__documentIdentity")
    assert value is not None, "the document identity probe was not installed"
    return int(value)


def _announcements(page: Page) -> list[str]:
    value = page.evaluate("window.__announcements")
    assert value is not None, "the announcement recorder was not installed"
    return list(value)


def _navigation_requests(router) -> list[str]:
    """The requests for entry documents, as opposed to API calls or assets."""
    return [record.path for record in router.requests.navigation()]


def test_in_app_navigation_reuses_the_document_and_the_shell(page: Page) -> None:
    router = mount_scenario(page, controlled_scenario())
    _probe(page)
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    identity = _document_identity(page)
    assert identity == 1
    page.evaluate("() => { window.__shellNode = document.querySelector('.app-shell'); }")

    page.locator(".app-nav").get_by_role("link", name="Runners", exact=True).click()
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()
    page.locator("[data-nav-group='account']").get_by_role("link", name="Account", exact=True).click()
    expect(page.get_by_role("heading", name="Account", exact=True)).to_be_visible()

    # Same document, same shell node, one chrome: three routes, no reload.
    assert _document_identity(page) == identity
    assert page.evaluate("() => window.__shellNode === document.querySelector('.app-shell')") is True
    state = page.evaluate(CHROME_STATE)
    assert state["appShell"] == 1 and state["publicHeader"] == 0, state
    # The address bar holds the route the reader is on.
    assert page.url == f"{ORIGIN}/compute/profile"
    # Only the first document was ever requested: no route made the browser fetch
    # another entry document.
    assert _navigation_requests(router) == ["/compute/dashboard"]


def test_history_back_and_forward_return_to_the_real_pages(page: Page) -> None:
    router = mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    page.locator(".app-nav").get_by_role("link", name="Runners", exact=True).click()
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()

    page.go_back()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/dashboard"
    page.go_forward()
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()
    assert page.url == f"{ORIGIN}/runners"

    # A traversal is the same document moving through its own stack: it remounts
    # the page the entry holds, and never requests an entry document.
    assert _navigation_requests(router) == ["/compute/dashboard"]


def test_a_traversal_during_a_slow_render_still_lands_on_the_page_it_names(page: Page) -> None:
    router = mount_scenario(page, controlled_scenario())
    # Hold the catalog's data so its page is reliably still mid-mount when the
    # reader traverses. The page paints its heading synchronously but needs the
    # response to become the catalog, which is exactly the window a real network
    # leaves open.
    gate = []
    page.route(f"{ORIGIN}/compute/api/types", lambda route: gate.append(route))

    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    page.locator(".app-nav").get_by_role("link", name="Runners", exact=True).click()
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()
    assert gate, "the catalog request was never issued"

    # The reader leaves before the catalog page finished loading. The address bar
    # goes back; the outlet must follow it rather than showing the page they left.
    page.go_back()
    for held in gate:
        held.fallback()
    expect(page).to_have_url(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    # The address bar and the outlet agree: the late response did not repaint the
    # page the reader already left.
    assert page.evaluate("() => document.querySelectorAll('.runner-catalog').length") == 0
    assert _navigation_requests(router) == ["/compute/dashboard"]


def test_crossing_between_public_and_workspace_chrome_does_not_reload(page: Page) -> None:
    router = mount_scenario(page, controlled_scenario())
    _probe(page)
    page.goto(f"{ORIGIN}/")
    expect(page.locator(".public-header")).to_be_visible()
    identity = _document_identity(page)

    # The public navigation reaches the workspace pages; the brand link comes home.
    page.evaluate("() => { document.querySelector('.public-navigation').open = true; }")
    page.locator(".public-navigation").get_by_role("link", name="Runners", exact=True).click()
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()
    workspace = page.evaluate(CHROME_STATE)
    assert workspace["appShell"] == 1 and workspace["publicHeader"] == 0, workspace
    assert page.url == f"{ORIGIN}/runners"

    page.locator("a.app-brand").click()
    expect(page.locator(".public-header")).to_be_visible()
    expect(page.locator(".public-outlet h1")).to_have_text("REvoCompute")
    public = page.evaluate(CHROME_STATE)
    assert public["appShell"] == 0 and public["publicHeader"] == 1, public
    assert page.url == f"{ORIGIN}/"

    # The chrome changed twice, the document did not: the router is one router.
    # Each chrome owns exactly one content region, and the page it carries renders
    # its own level-one heading inside it.
    assert _document_identity(page) == identity
    assert _navigation_requests(router) == ["/"]
    assert workspace["outlet"] is not None and workspace["headings"] == ["Runner catalog"], workspace
    assert public["outlet"] == "public-outlet", public
    # Back returns to the workspace page inside the same document.
    page.go_back()
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()
    assert page.url == f"{ORIGIN}/runners"
    assert _document_identity(page) == identity
    assert _navigation_requests(router) == ["/"]


def test_route_change_disposes_the_replaced_view(page: Page) -> None:
    router = mount_scenario(page, controlled_scenario().with_result("multi_structure"))
    page.goto(f"{ORIGIN}/compute/results/{RESULT_ID}")
    expect(page.locator(".structure-host")).to_be_visible()
    assert page.evaluate("window.__viewerMounts") == 1
    assert page.evaluate("window.__viewerDisposals || 0") == 0

    page.locator(".app-nav").get_by_role("link", name="Runners", exact=True).click()
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()

    # The route that owned the molecular viewer disposed it before the next route
    # mounted: no instance outlives the page that created it.
    assert page.evaluate("window.__viewerDisposals") == 1
    assert page.locator(".structure-host").count() == 0
    assert _navigation_requests(router) == [f"/compute/results/{RESULT_ID}"]


def test_history_navigation_names_and_focuses_the_page_it_lands_on(page: Page) -> None:
    mount_scenario(page, controlled_scenario())
    _probe(page)
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    page.locator(".app-nav").get_by_role("link", name="Runners", exact=True).click()
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()

    page.go_back()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    # The document is named for the page the reader is now on, and focus moves to
    # that page's own heading rather than staying on the control they left.
    expect(page).to_have_title("Dashboard | REvoCompute")
    expect(page.locator(".app-outlet h1")).to_be_focused()

    # Each traversal announces the page it landed on, once, and the
    # announcements do not accumulate as regions in the document.
    page.go_forward()
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()
    page.go_back()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    announcements = _announcements(page)
    assert len(announcements) == 3, announcements
    assert announcements[-1].endswith("Dashboard | REvoCompute"), announcements
    # Each announcement is transient: the regions are removed after the reader has
    # had time to hear them, so repeated traversals never accumulate regions.
    page.wait_for_function("() => document.querySelectorAll('[data-route-announcement]').length === 0")


def test_a_traversal_that_lands_on_the_same_page_keeps_an_unsaved_form(page: Page) -> None:
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")
    field = page.locator("textarea[aria-label='Protein sequence']")
    expect(field).to_be_visible()
    field.fill(">sample\nACDEFGHIK")

    # The router's own state is part of the history: this traversal lands on the
    # location the outlet already holds, so there is nothing to remount and the
    # reader's in-progress input is not silently discarded. The same holds in the
    # other direction.
    page.evaluate("() => history.pushState(null, '', '#input')")
    page.go_back()
    page.wait_for_timeout(600)
    expect(field).to_have_value(">sample\nACDEFGHIK")
    assert page.url.endswith("/compute/create_task?task_type=sequence_demo")
    page.go_forward()
    page.wait_for_timeout(600)
    expect(field).to_have_value(">sample\nACDEFGHIK")
    assert page.url.endswith("#input")


def test_expired_session_at_a_protected_route_redirects_once_to_sign_in(page: Page) -> None:
    router = mount_scenario(page, controlled_scenario(session=EXPIRED_AUTH))
    page.goto(f"{ORIGIN}/runners")
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()

    page.locator(".app-nav").get_by_role("link", name="Dashboard", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/compute/login?return_to=%2Fcompute%2Fdashboard")
    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
    # The protected page never mounted, and the sign-in page was reached once.
    assert _navigation_requests(router) == ["/runners", "/compute/login"], _navigation_requests(router)


def test_repeated_navigation_leaves_no_duplicate_chrome(page: Page) -> None:
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    for _ in range(3):
        page.locator(".app-nav").get_by_role("link", name="Runners", exact=True).click()
        expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()
        page.locator(".app-nav").get_by_role("link", name="Dashboard", exact=True).click()
        expect(page.locator(".task-card").first).to_be_visible()
    # One shell, one navigation, one outlet, one feedback column, one main
    # landmark: a listener registered per route would have multiplied these, and a
    # second router or a second auth owner would have doubled the chrome.
    assert page.evaluate(CHROME_STATE) == {
        "appShell": 1, "publicHeader": 0, "outlet": "app-outlet",
        "headings": ["Dashboard"], "mains": 1,
    }