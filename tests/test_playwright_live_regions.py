# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the two live regions the a11y round owns.

Both cases assert what a screen reader consumes: a role and an accessible name
read from the accessibility tree, the live-region ancestry of the message the
reader is being told about, and whether the region node is connected, visible,
and still the same node across a state transition.

* The dashboard's transient query error used to share the search field's
  ``<label>``. A wrapping label is the field's accessible-name source, so the
  error text became part of the field's name ("Search" plus the message) for as
  long as the error showed. The field must stay named by its own visible label
  while the error text stays announced from the live region that carries it.
* The create-task feedback region was appended only inside the workbench, so in
  the chooser state it was not in the document at all. The region must be
  connected, visible, and reachable in both states; the chooser's own status
  message must live inside it; and the one region - never two - must still carry
  the workbench validation summary after the transition.

Each case is non-vacuous: it first drives the product into the state the defect
describes (the error rendered, the region reparented) and compares the same
field/region across the transition rather than asserting a fresh render.

Selector constants are stable hooks the suite already drives (``data-filter``,
``data-query-error``). Where an element can be reached by role - the searchbox,
the method buttons, the "Change method" button - the case uses the role so the
assertion lands on the computed accessibility tree rather than the markup.
The class-named hooks (``.ct-feedback``, ``.ct-catalog-status``,
``.ct-validation``) exist because the case compares one node's identity and
ancestry across a transition, which a role query cannot express.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import controlled_scenario, mount_scenario

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"

# The one field the dashboard search control renders, addressed by the product's
# own data contract rather than a class name.
SEARCH = "input[data-filter='search']"
QUERY_ERROR = "[data-query-error]"
CHOOSER_STATUS = ".ct-catalog-status"
FEEDBACK = ".ct-feedback"


def _reveal_dashboard_filter(page: Page, selector: str) -> None:
    """Open the disclosure and advanced panel that hold a filter control.

    The register collapses its filters on a narrow viewport, so a control can be
    present and correct while it is not on screen; the test opens the state the
    reader would open rather than asserting against a hidden control.
    """
    if not page.locator("[data-filter='status']").is_visible():
        page.locator(".dashboard-filters > summary").click()
    if not page.locator(selector).is_visible():
        page.locator("[data-advanced]").click()


def _connected_label_target(region) -> bool:
    """Whether the region's ``aria-labelledby`` names a node still in the document.

    A live region named from a node the current state does not hold has no name
    there, which is the wiring defect this case guards.
    """
    return region.evaluate(
        "node => { const id = node.getAttribute('aria-labelledby');"
        " const target = id ? document.getElementById(id) : null;"
        " return !!target && target.isConnected; }"
    )


def test_the_dashboard_search_name_survives_its_transient_query_error(page: Page) -> None:
    """The error is announced, but it never becomes the search field's name.

    The field is named by the label the chooser renders; triggering the invalid
    regular expression makes the error visible inside the live region. The name
    read off the accessibility tree must be the field's own label before and
    after, and must not contain the error text the reader is being told about.
    """
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card")).to_be_visible()

    search = page.locator(SEARCH)
    expect(search).to_have_role("searchbox")
    # The name the product gives the field, read from the label it renders rather
    # than a hardcoded copy, and captured before the error exists.
    label_text = search.evaluate(
        "node => node.labels && node.labels.length ? node.labels[0].textContent.trim() : ''"
    )
    assert label_text, "the search field renders no label of its own"
    expect(search).to_have_accessible_name(label_text)
    error = page.locator(QUERY_ERROR)
    expect(error).to_be_empty()

    _reveal_dashboard_filter(page, "[data-toggle-regex]")
    page.locator("[data-toggle-regex]").click()
    search.fill("[")
    # Non-vacuous: the error is actually rendered and announced before the name is
    # asserted, so the field is measured in the contaminated state, not a clean one.
    error_text = error.text_content() or ""
    assert error_text.strip(), "no query error was rendered to announce"
    expect(error).to_be_visible()
    assert error.evaluate("node => node.closest('[aria-live]') !== null"), "the error left its live region"

    # The same name as before, even though the error text now sits beside the
    # field: the field is still called what its label says and nothing else.
    expect(search).to_have_accessible_name(label_text)
    assert error_text not in search.evaluate("node => node.labels[0].textContent"), (
        "the transient error text is inside the field's own label"
    )


def test_the_create_task_feedback_region_survives_the_chooser_transition(page: Page) -> None:
    """One feedback region is connected, visible, and named in both view states.

    The chooser, the workbench, and the chooser reached again by "Change method"
    are three states of the same view; the region that announces each of them
    must be reachable in all three. The case marks the region in the chooser and
    asserts the same node comes home, so it proves the region travelled rather
    than being re-created where it happened to be looked for.
    """
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/create_task")
    method = page.get_by_role("button", name="Sequence demo").first
    expect(method).to_be_visible()

    region = page.locator(FEEDBACK)
    expect(region).to_have_count(1)
    expect(region).to_be_visible()
    assert _connected_label_target(region), "the region is named from an absent node in the chooser"
    chooser_status = page.locator(CHOOSER_STATUS)
    expect(chooser_status).to_be_visible()
    assert chooser_status.evaluate(
        "node => !!node.closest('.ct-feedback')"
    ), "the chooser's own status is outside the announced region"
    region.evaluate("node => { node.dataset.pr74Case = 'chooser'; }")

    # The workbench: the method's page, and the same single region carrying the
    # validation summary rather than a second one created for the new state.
    method.click()
    expect(page.locator(".ct-workbench textarea")).to_be_visible()
    expect(region).to_have_count(1)
    expect(region).to_be_visible()
    assert _connected_label_target(region), "the region is named from an absent node in the workbench"
    expect(page.locator(".ct-validation")).to_be_visible()
    assert page.locator(".ct-validation").evaluate(
        "node => !!node.closest('.ct-feedback')"
    ), "the validation summary is outside the announced region"

    # Drive the workbench validate path: a refused preflight reports its blocker
    # and its status through the same region, without leaving the page.
    page.route(f"{ORIGIN}/compute/api/preflight/**", lambda route: route.fulfill(json={
        "valid": False, "security": {"status": "passed"}, "contract": {"status": "failed"},
        "admission": {"allowed": True, "runner_ready": True, "infrastructure_ready": True, "infrastructure_status": "READY"},
        "normalized_params": {}, "inputs": [], "warnings": [],
        "errors": [{"message": "Sequence is too short."}],
    }))
    page.locator("textarea[aria-label='Protein sequence']").fill(">sample\nACDEFG")
    run = page.get_by_role("button", name="Run task", exact=True)
    expect(run).to_be_enabled()
    run.click()
    expect(page.locator(".ct-validation-row.error").first).to_be_visible()
    expect(page.locator(".ct-status")).to_be_visible()
    expect(region).to_have_count(1)
    expect(region).to_be_visible()
    assert page.locator(".ct-status").evaluate(
        "node => !!node.closest('.ct-feedback')"
    ), "the action status is outside the announced region"
    assert region.evaluate("node => node.dataset.pr74Case") == "chooser", (
        "the region was re-created instead of carried into the workbench"
    )

    # Back to the chooser: the region comes home with its status message, and it
    # is the node marked before the transition, not a replacement.
    page.get_by_role("button", name="Change method", exact=True).click()
    expect(page.locator(CHOOSER_STATUS)).to_be_visible()
    expect(region).to_have_count(1)
    expect(region).to_be_visible()
    assert region.evaluate("node => node.dataset.pr74Case") == "chooser", (
        "the region was re-created instead of carried across the transition"
    )
    assert _connected_label_target(region), "the region is named from an absent node after the transition"
    assert page.locator(CHOOSER_STATUS).evaluate(
        "node => !!node.closest('.ct-feedback')"
    ), "the chooser's returning status is outside the announced region"
