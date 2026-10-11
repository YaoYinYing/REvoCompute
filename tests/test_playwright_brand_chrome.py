# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Brand chrome acceptance: the top bar's session gate and the tour's clearance.

Both cases drive the production bundle through the deterministic fixture harness
and assert rendered behavior — which controls exist for a given session, and where
the fixed surfaces actually land — never a class name, token value, or pixel
literal.

Covered adjudications (PR74 round 5, batch ``brand-chrome``):
* O-D2 — an anonymous visitor must not be offered the authenticated create-task
  action, while every authenticated session keeps exactly one.
* L-M4-01 — with a persistent notice, a toast and the guided tour all active at a
  narrow viewport, the tour callout must not intersect the shell's feedback column
  and every control in that column must stay hit-testable at its own centre.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import ADMIN_AUTH, ANONYMOUS_AUTH, USER_AUTH, Session, controlled_scenario, mount_scenario

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"

# Server-owned demo announcement the fixture approves; the copy is fixture data,
# never asserted as translated product vocabulary.
NOTICE = {
    "id": "operator-notice-demo",
    "level": "warning",
    "title": "Scheduled maintenance",
    "body": "Storage maintenance on Saturday 02:00-04:00 UTC.",
}

# The stress viewport the campaign scores every surface at, plus the narrow phone
# the same three-surface stack is expected to clear on.
VIEWPORTS = ((320, 640), (375, 812))


def _create_task_action(page: Page):
    """The top bar's primary page action, addressed by its accessible name."""
    return page.get_by_role("link", name="New task", exact=True)


def test_anonymous_visitor_is_not_offered_the_authenticated_create_task_action(page: Page) -> None:
    # /runners is a public route: no session means no authenticated chrome. The
    # request itself is the observation — an affordance that exists only to be
    # refused must not be rendered at all.
    mount_scenario(page, controlled_scenario(session=ANONYMOUS_AUTH))
    page.goto(f"{ORIGIN}/runners")
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()
    assert page.locator(".app-shell").count() == 1
    assert _create_task_action(page).count() == 0
    # The shell's other session-dependent affordances gate the same way.
    assert page.get_by_role("button", name="Log out").count() == 0
    assert page.locator("[data-nav-group='admin']").is_hidden()
    # The page's own method-list affordances are untouched by the chrome gate.
    expect(page.locator(".app-header")).to_be_visible()


@pytest.mark.parametrize("session", [USER_AUTH, ADMIN_AUTH], ids=["user", "admin"])
def test_authenticated_session_keeps_exactly_one_create_task_action(page: Page, session: Session) -> None:
    mount_scenario(page, controlled_scenario(session=session))
    page.goto(f"{ORIGIN}/runners")
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()
    action = _create_task_action(page)
    assert action.count() == 1
    expect(action).to_be_visible()
    expect(action).to_have_attribute("href", "/compute/create_task")
    # The same session gate keeps Log out, so the anonymous assertion above is
    # discriminating rather than vacuous: the name it looks for does resolve here.
    expect(page.get_by_role("button", name="Log out")).to_be_visible()


def test_authenticated_session_keeps_the_action_on_the_create_task_page_itself(page: Page) -> None:
    # The gate reflects the session, not the current route: the action stays present
    # where the reader already is.
    mount_scenario(page, controlled_scenario(session=USER_AUTH))
    page.goto(f"{ORIGIN}/compute/create_task")
    expect(page.get_by_role("heading", name="Create task", exact=True)).to_be_visible()
    action = _create_task_action(page)
    assert action.count() == 1
    expect(action).to_be_visible()


@pytest.mark.parametrize(("width", "height"), VIEWPORTS, ids=lambda value: str(value))
def test_tour_callout_clears_the_notices_and_toast_column(page: Page, width: int, height: int) -> None:
    mount_scenario(page, controlled_scenario())
    page.set_viewport_size({"width": width, "height": height})
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": [NOTICE]}))
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    page.locator(".tour-launcher").click()
    expect(page.locator(".tour-callout")).to_be_visible()
    expect(page.locator(".sys-notice")).to_have_count(1)

    # A real toast appends to the same fixed column while the tour is up. The column
    # itself covers the card's Delete control at this width, so the action is issued
    # through the page rather than through a pointer: the toast is the state under
    # test, not the click path that reaches it.
    page.on("dialog", lambda dialog: dialog.accept())
    page.evaluate("() => document.querySelector('.task-card [data-action=\"delete\"]').click()")
    expect(page.locator(".app-notice")).to_be_visible()

    column = page.locator(".app-feedback").bounding_box()
    callout = page.locator(".tour-callout").bounding_box()
    assert column is not None and callout is not None
    intersects = not (
        callout["x"] + callout["width"] <= column["x"]
        or column["x"] + column["width"] <= callout["x"]
        or callout["y"] + callout["height"] <= column["y"]
        or column["y"] + column["height"] <= callout["y"]
    )
    assert not intersects, (callout, column)

    # Every control the column renders is reachable at its own centre point.
    covered = page.evaluate(
        """() => [...document.querySelectorAll('.app-feedback button, .app-feedback a, .app-feedback summary')]
             .filter(node => { const r = node.getBoundingClientRect();
                 if (!r.width || !r.height) return false;
                 const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                 return !(hit && (node === hit || node.contains(hit))); })
             .map(node => node.getAttribute('aria-label') || (node.textContent || '').trim().slice(0, 40))"""
    )
    assert covered == [], covered
    expect(page.get_by_role("button", name="Hide notice")).to_be_visible()
    expect(page.locator(".tour-callout")).to_be_visible()
