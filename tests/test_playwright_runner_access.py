# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Runner Access is grouped by the reader's next decision.

The page renders the server's policy states, never its own: a granted policy is
a compact fact, a pending request is answered state with no further control, a
requestable / expired / rejected policy carries a full-width request form, and a
policy that accepts no requests offers none. A request emits exactly the
server-owned ``policy_id`` and moves the answered row into review without a
second submission being possible.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import controlled_scenario, mount_scenario
from frontend_fixtures.models import AccessState

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
URL = f"{ORIGIN}/compute/account/runner-access"

GRANTED = AccessState.granted_policy(policy_id="granted-policy", label="Granted model", expires_at=1893456000)
REQUESTABLE = AccessState.requestable_policy(policy_id="request-policy", label="Requestable model")
PENDING = AccessState.pending_policy(policy_id="pending-policy", label="Pending model")
EXPIRED = AccessState(
    restricted=True, granted=False, requestable=True, expired=True, expires_at=1704067200,
    policy_id="expired-policy", label="Expired model",
)
REJECTED = AccessState(
    restricted=True, granted=False, requestable=True, request_status="rejected",
    policy_id="rejected-policy", label="Rejected model",
)
RESTRICTED = AccessState(restricted=True, granted=False, requestable=False, policy_id="closed-policy", label="Closed model")


def _evidence(page: Page, name: str) -> None:
    """Save a screenshot only when a caller names an evidence directory."""
    directory = os.environ.get("REVOCOMPUTE_UI_EVIDENCE_DIR")
    if not directory:
        return
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=target / f"{name}.png")


def _mount(page: Page) -> None:
    scenario = controlled_scenario().with_access_policies([GRANTED, REQUESTABLE, PENDING, EXPIRED, REJECTED, RESTRICTED])
    mount_scenario(page, scenario)
    page.goto(URL)
    expect(page.get_by_role("heading", name="Runner access", exact=True)).to_be_visible()
    expect(page.locator("[data-access-group]")).to_have_count(4)


def _posts(page: Page) -> list[dict | None]:
    posted: list[dict | None] = []
    page.on(
        "request",
        lambda request: posted.append(request.post_data_json)
        if urlsplit(request.url).path.endswith("/access/requests") else None,
    )
    return posted


def test_policy_states_are_grouped_and_only_requestable_states_offer_a_form(page: Page) -> None:
    _mount(page)

    groups = page.locator("[data-access-group]")
    assert groups.evaluate_all("elements => elements.map(element => element.dataset.accessGroup)") == [
        "action", "pending", "granted", "restricted",
    ]
    expect(page.locator('[data-access-group="action"] > h2')).to_have_text("Access you can request")
    expect(page.locator('[data-access-group="pending"] > h2')).to_have_text("Awaiting review")
    expect(page.locator('[data-access-group="granted"] > h2')).to_have_text("Granted access")
    expect(page.locator('[data-access-group="restricted"] > h2')).to_have_text("Not requestable")

    # Requestable, expired and rejected each carry a form; pending and a policy
    # that accepts no requests never do.
    action_rows = page.locator('[data-access-group="action"] .access-row')
    expect(action_rows).to_have_count(3)
    expect(action_rows.locator(".access-request")).to_have_count(3)
    expect(page.locator('[data-access-group="pending"] .access-request')).to_have_count(0)
    expect(page.locator('[data-access-group="restricted"] .access-request')).to_have_count(0)

    # The state sentences are the server's facts, including the expiry dates.
    expect(page.locator('[data-access-state="expired"] .access-detail')).to_contain_text("expired on")
    expect(page.locator('[data-access-state="rejected"] .access-detail')).to_contain_text("not approved")
    expect(page.locator('[data-access-state="pending"] .access-detail')).to_contain_text(
        "awaiting an administrator decision"
    )
    expect(page.locator('[data-access-state="expired"] .access-policy')).to_be_visible()

    # Granted is a compact list, not another request surface.
    granted = page.locator(".access-granted")
    expect(granted).to_have_count(1)
    expect(granted).to_contain_text("Granted model")
    expect(granted).to_contain_text("Valid until")
    expect(granted.locator(".access-request")).to_have_count(0)

    # The owning policy's licence notice remains reachable from the request row.
    requestable = page.locator('[data-access-state="requestable"]')
    requestable.get_by_text("Policy details").click()
    expect(requestable).to_contain_text("Academic use only")
    expect(requestable).to_contain_text("The upstream licence requires verified academic eligibility.")
    expect(requestable.get_by_role("link", name="Upstream terms")).to_have_attribute(
        "href", "https://example.org/terms"
    )
    _evidence(page, "runner-access-grouped")


def test_runner_access_is_readable_in_the_dark_theme(page: Page) -> None:
    page.add_init_script("localStorage.setItem('revocompute-theme', 'dark')")
    _mount(page)
    expect(page.locator('[data-access-group="action"] .access-request')).to_have_count(3)
    _evidence(page, "runner-access-dark")


def test_the_request_form_is_full_width_and_inside_a_narrow_viewport(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    _mount(page)
    form = page.locator('[data-access-state="requestable"] .access-request')
    expect(form).to_be_visible()
    widths = form.evaluate(
        """element => ({
            form: element.getBoundingClientRect().width,
            field: element.querySelector('textarea').getBoundingClientRect().width,
            right: element.getBoundingClientRect().right,
        })"""
    )
    # The textarea takes the form's content width, not a column beside its button.
    assert widths["field"] >= widths["form"] - 40, widths
    assert widths["right"] <= 390, widths
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    _evidence(page, "runner-access-mobile")


def test_requesting_access_sends_one_policy_and_moves_the_row_into_review(page: Page) -> None:
    _mount(page)
    posted = _posts(page)
    row = page.locator('[data-access-state="requestable"]')
    row.get_by_label("Research use and affiliation").fill("Non-commercial work at Example Institute")
    row.get_by_role("button", name="Request access", exact=True).click()

    expect(page.locator('[data-access-group="pending"] .access-row')).to_have_count(2)
    expect(page.locator('[data-access-state="requestable"]')).to_have_count(0)
    expect(page.locator('[data-access-group="action"] .access-row')).to_have_count(2)
    expect(page.get_by_text("Access request submitted.")).to_be_visible()
    # The answered row is focusable so a keyboard reader is not dropped to the page.
    assert page.evaluate("document.activeElement && document.activeElement.dataset.accessState === 'pending'")
    assert posted == [{"policy_id": "request-policy", "reason": "Non-commercial work at Example Institute"}]

    # No form survives on the answered row, so the request cannot be repeated.
    expect(page.locator('[data-access-state="pending"] .access-request')).to_have_count(0)
    assert len(posted) == 1


def test_the_empty_and_failed_states_are_answers_not_a_broken_page(page: Page) -> None:
    mount_scenario(page, controlled_scenario().with_access_policies([]))
    page.goto(URL)
    expect(page.get_by_text("No restricted Runner policies are configured.")).to_be_visible()

    page.route(
        f"{ORIGIN}/compute/api/access",
        lambda route: route.fulfill(status=503, content_type="application/json", body='{"error": "unavailable"}'),
    )
    page.reload()
    expect(page.locator("[data-error]")).to_be_visible()
    expect(page.locator("[data-error]")).not_to_be_empty()


def test_pending_and_restricted_policies_never_post_on_interaction(page: Page) -> None:
    _mount(page)
    posted = _posts(page)
    # There is no control in these groups to interact with: assert the absence
    # survives a user tabbing through the page.
    for _ in range(30):
        page.keyboard.press("Tab")
    expect(page.locator('[data-access-group="pending"] button')).to_have_count(0)
    expect(page.locator('[data-access-group="restricted"] button')).to_have_count(0)
    assert posted == []
