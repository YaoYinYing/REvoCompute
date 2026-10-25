# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the Runner-facing states the fixture harness exposes.

``test_playwright_application.py`` owns the ordinary navigation → create →
submit → finished journey. This file covers the states around it that a real
Runner deployment produces and that the harness now makes cheap: a preflight
rejection and a preflight warning, infrastructure readiness, catalog
cardinality, a failed lifecycle with diagnostics, restricted-Runner access
pending versus granted, narrow-screen rendering of a loaded workspace, and one
representative real contract shape (a GPU structure Runner). The authentic
PSSM-GREMLIN contract lives at the fleet boundary, in
``tests/fleet/browser/test_playwright_gremlin_runner_contract.py``.

Every case drives the production bundle through ``tests/frontend_fixtures/`` and
states the behavior the frontend actually exhibits today. The Create Task
surface owns a single ``Run task`` action that preflights and submits in one
step, so an admission or contract rejection stops before any ``/post``.
"""

from __future__ import annotations

from typing import Sequence

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import (
    AccessState,
    build_task_summary,
    controlled_runner,
    controlled_scenario,
    mount_scenario,
    structure_scenario,
)

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
TASK_ID = "0123456789abcdef0123456789abcdef"


def _mount_create_task(page: Page, task_type: str = "sequence_demo") -> None:
    """Open Create Task on a Runner and wait for its interactive workbench."""
    page.goto(f"{ORIGIN}/compute/create_task?task_type={task_type}")
    expect(page.locator(".ct-workbench")).to_be_visible()


def _provide_sequence(page: Page) -> None:
    """Supply the single valid local input the controlled Runner declares."""
    page.locator("textarea[aria-label='Protein sequence']").fill(">sample\nACDEFG")


def _run_task(page: Page):
    """Return the single Create Task action the flow submits through."""
    return page.get_by_role("button", name="Run task", exact=True)


def _open_result_after_lifecycle(page: Page, pending: Sequence[str], terminal_text: str) -> None:
    """Load the Result Workspace and drive its poll-counted lifecycle to the end.

    The router advances one lifecycle step per status poll and the workspace
    polls on mount, so each ``reload`` is exactly one deterministic step. Once a
    terminal state also reports ``result_available`` the manifest renders in the
    same load, so the terminal *manifest* state - not a final pending status - is
    what the last reload shows.
    """
    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")
    expect(page.locator(".result-status")).to_contain_text(pending[0])
    for status in pending[1:]:
        page.reload()
        expect(page.locator(".result-status")).to_contain_text(status)
    page.reload()
    expect(page.locator(".result-status")).to_contain_text(terminal_text)


# ── preflight outcomes ────────────────────────────────────────────────────────


def test_preflight_rejection_stops_before_submission_and_states_the_problem(page: Page) -> None:
    """A rejected contract check surfaces a finding and never posts the task."""
    scenario = controlled_scenario().with_preflight("invalid_contract")
    requests = mount_scenario(page, scenario).requests

    _mount_create_task(page)
    _provide_sequence(page)
    _run_task(page).click()

    expect(page.locator(".ct-validation")).to_contain_text("Parameter 'iterations' must be at least 1.")
    # The rejection is summarised and the same action control stays available to
    # retry; the form is not replaced by a confirmation stage.
    expect(page.locator(".ct-validation-summary")).to_contain_text("issue to fix")
    expect(_run_task(page)).to_be_enabled()
    expect(page).to_have_url(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")
    assert requests.preflight("sequence_demo")
    assert requests.submit() == ()


@pytest.mark.parametrize("outcome", ["warning", "capacity_busy"])
def test_preflight_warning_is_inline_and_keeps_one_submit_action(page: Page, outcome: str) -> None:
    """A non-blocking finding is reported inline with no extra confirmation stage."""
    scenario = controlled_scenario().with_preflight(outcome)
    requests = mount_scenario(page, scenario).requests
    # Hold the submission in flight so a completed preflight does not navigate
    # away: the single action preflights and then submits, and the inline finding
    # is only observable while the workbench stays mounted.
    held: list = []
    page.route(f"{ORIGIN}/compute/api/post", lambda route: held.append(route))

    _mount_create_task(page)
    _provide_sequence(page)
    with page.expect_request(f"{ORIGIN}/compute/api/post"):
        _run_task(page).click()

    expect(page.locator(".ct-validation")).to_contain_text("Checks passed")
    expect(page.locator(".ct-validation")).to_contain_text(
        "Inputs will be re-numbered from 1." if outcome == "warning" else "The scheduler is busy; the task will queue."
    )
    # The warning does not introduce a dialog or a second gate: the same action
    # control has already advanced from review to submission.
    assert page.get_by_role("dialog").count() == 0
    assert requests.submit(), "a completed preflight submits through the same action"
    for route in held:
        route.fulfill(status=500, json={"error": "not exercised"})


def test_runner_not_ready_preflight_blocks_with_a_distinct_message(page: Page) -> None:
    """An unavailable Runner is an admission error, and the method stays addressable."""
    scenario = controlled_scenario().with_preflight("runner_not_ready")
    requests = mount_scenario(page, scenario).requests

    _mount_create_task(page)
    _provide_sequence(page)
    _run_task(page).click()

    # The server's own blocking finding is the row: wait for it to land before
    # counting, and then the panel must not restate the same condition as a
    # client-authored sentence, so one blocker is one row.
    expect(page.locator(".ct-validation")).to_contain_text("Runner is currently unavailable for new submissions")
    expect(page.locator(".ct-validation-row")).to_have_count(1)
    # The rejection is recoverable: the method and its input stay on screen.
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Change method", exact=True)).to_be_visible()
    assert requests.preflight("sequence_demo")
    assert requests.submit() == ()


# ── readiness ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "banner"),
    [
        ("READY", "Infrastructure ready"),
        ("DEGRADED", "Infrastructure degraded"),
        ("UNAVAILABLE", "Infrastructure unavailable"),
    ],
)
def test_catalog_reports_infrastructure_readiness_without_hiding_methods(page: Page, status: str, banner: str) -> None:
    """The catalog banner carries the aggregate state; the method stays listed."""
    mount_scenario(page, controlled_scenario().with_readiness(status))

    page.goto(f"{ORIGIN}/runners")
    expect(page.get_by_role("heading", name="Runner catalog")).to_be_visible()
    readiness = page.locator(".readiness-state")
    expect(readiness).to_contain_text(banner)
    expect(readiness).to_have_attribute("data-status", status)
    # Readiness never implies the method does not exist.
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="View method")).to_be_visible()


def test_unavailable_infrastructure_keeps_runner_detail_inspectable(page: Page) -> None:
    """An unavailable deployment does not remove the Runner contract page."""
    mount_scenario(page, controlled_scenario().with_readiness("UNAVAILABLE"))

    page.goto(f"{ORIGIN}/runners/sequence_demo")
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="Create task").first).to_be_visible()
    expect(page.get_by_role("heading", name="When to use this method")).to_be_visible()


def test_create_task_gates_on_preflight_admission_not_the_readiness_banner(page: Page) -> None:
    """An unavailable-infrastructure admission preflight blocks the submission.

    Create Task does not gate on the readiness banner; the block is a server
    admission decision reported back through the preflight response.
    """
    requests = mount_scenario(
        page, controlled_scenario().with_readiness("UNAVAILABLE").with_preflight("infrastructure_not_ready")
    ).requests

    _mount_create_task(page)
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    _provide_sequence(page)
    _run_task(page).click()

    expect(page.locator(".ct-validation")).to_contain_text("Compute infrastructure is currently unavailable for new submissions")
    assert requests.preflight("sequence_demo")
    assert requests.submit() == ()


# ── catalog cardinality ───────────────────────────────────────────────────────


@pytest.mark.parametrize("count", [1, 3, 12])
def test_runner_catalog_cardinality_stays_intentional(page: Page, count: int) -> None:
    """1, 3, and 12 Runners each produce a scannable, overflow-free catalog."""
    extras = [controlled_runner(name=f"method_{index}", display_name=f"Method {index}") for index in range(1, count)]
    scenario = controlled_scenario().with_catalog(extras)
    mount_scenario(page, scenario)

    page.goto(f"{ORIGIN}/runners")
    expect(page.locator(".runner-card")).to_have_count(count)
    expect(page.locator(".catalog-count")).to_contain_text(f"{count} {'method' if count == 1 else 'methods'}")
    # A single Runner still renders as one complete group, not an empty grid.
    expect(page.locator(".runner-group")).to_have_count(1)
    expect(page.locator(".runner-group").first.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    page.set_viewport_size({"width": 320, "height": 760})
    page.reload()
    expect(page.locator(".runner-card")).to_have_count(count)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


# ── failure lifecycle ─────────────────────────────────────────────────────────


def test_failed_lifecycle_surfaces_on_dashboard_and_in_result_diagnostics(page: Page) -> None:
    """Running → failed reaches the Dashboard and publishes a diagnostic Result Workspace."""
    scenario = controlled_scenario().with_lifecycle("queued", "running", "failed").with_result("failed_diagnostics")
    requests = mount_scenario(page, scenario).requests

    page.goto(f"{ORIGIN}/compute/dashboard")
    failed = page.locator(".task-card .status-failed")
    expect(failed).to_be_visible()
    expect(failed).to_have_text("failed")
    page.get_by_role("button", name="View error", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("Runner stopped before publishing a model")
    page.keyboard.press("Escape")
    page.get_by_text("Execution error").click()
    expect(page.locator("#main-content").get_by_text("Runner stopped before publishing a model", exact=True)).to_be_visible()

    _open_result_after_lifecycle(page, ("queued", "running"), "Runner stopped before publishing a model")
    expect(page.locator(".result-status")).to_contain_text("Runner stopped before publishing a model")
    page.get_by_role("button", name="Open Files and diagnostics", exact=True).click()
    expect(page.get_by_role("heading", name="Diagnostics")).to_be_visible()
    expect(page.locator(".result-file-list, .result-files").get_by_text("task_failed.txt", exact=True)).to_be_visible()
    assert requests.status_polls()
    assert requests.result_manifest()


def test_dashboard_table_status_cell_reads_like_the_card_pill(page: Page) -> None:
    """A finalized Task with no outcome is named the same way in both views.

    The Dashboard register presents one Task two ways, and both must read the
    same word for it. `no_outcome` is a finished Task whose server-projected
    outcome is absent, so each view falls back to the lifecycle enum; the casing
    a reader sees comes from CSS, which only the browser can resolve.
    """
    scenario = controlled_scenario()
    no_outcome = build_task_summary(scenario.task_id, scenario.runner, outcome=None)
    mount_scenario(page, scenario.with_task_summaries([no_outcome]))
    page.goto(f"{ORIGIN}/compute/dashboard")

    pill = page.locator(".task-card").first.locator(".status")
    expect(pill).to_be_visible()
    card_text = pill.inner_text().strip()

    page.get_by_role("button", name="Table", exact=True).click()
    expect(page.locator(".task-table")).to_be_visible()
    # The table's first column is the dedicated selection column for an
    # administrator; the Task's own status cell is not index-fixed by column
    # count, so name the semantic column the header declares.
    row = page.locator(".task-table tbody tr").first
    status_header = page.locator(".task-table thead th").filter(has_text="Status").first
    index = status_header.evaluate(
        "node => [...node.parentElement.children].indexOf(node)"
    )
    rendered = row.locator("td").nth(index).inner_text().strip()

    # The two views agree as rendered, casing included, and the word is the
    # task's own state rather than an empty cell.
    assert rendered == card_text
    assert rendered.lower() == no_outcome["status"]


# ── restricted access pending versus granted ──────────────────────────────────


@pytest.mark.parametrize(
    ("access", "badge", "panel", "pending_notice"),
    [
        (
            AccessState.pending_policy(),
            "Access pending",
            "Access requested",
            "Runner access approval is pending review.",
        ),
        (AccessState.granted_policy(), "Access granted", "Access granted", None),
    ],
    ids=["pending", "granted"],
)
def test_restricted_access_state_is_reflected_without_navigation(
    page: Page, access: AccessState, badge: str, panel: str, pending_notice: str | None
) -> None:
    """Pending and granted policies change badge, banner, and Create Task gate in place."""
    scenario = controlled_scenario().with_access(access)
    requests = mount_scenario(page, scenario).requests

    page.goto(f"{ORIGIN}/runners")
    expect(page.locator(".runner-card .badge")).to_have_text(badge)

    page.get_by_role("link", name="View method").click()
    expect(page.locator(".access-banner")).to_contain_text(badge)
    # The sidebar keeps input preparation reachable while the server-owned gate enforces pending access.
    page.goto(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")
    expect(page.locator(".ct-access-panel h2")).to_have_text(panel)
    # No in-place request control is offered once the policy is pending or granted.
    expect(page.get_by_role("button", name="Request access", exact=True)).to_have_count(0)
    run = _run_task(page)
    if pending_notice is not None:
        expect(page.locator(".ct-validation")).to_contain_text(pending_notice)
        expect(run).to_be_disabled()
    else:
        # A granted policy is not an access error: once the input is supplied the
        # run is admitted.
        expect(page.locator(".ct-validation")).not_to_contain_text("access approval")
        _provide_sequence(page)
        expect(run).to_be_enabled()
    expect(page).to_have_url(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")
    assert requests.access_request() == ()


# The cases below assert two kinds of text. A server-owned value (the policy's
# notice, licence, or the 404's message) is asserted exactly as the fixture
# projects it. A frontend-authored string is asserted in the English catalog's
# wording, and the locale is pinned rather than left to the runner's default so
# the assertion cannot silently mean "some default locale". `i18n.test.ts` owns
# catalog parity: a key present in one catalog and not the other fails there.
EN_LOAD_RUNNERS = 'Unable to load runners.'
EN_DETAIL_LOAD_FAILED = 'Unable to load this runner.'
EN_DECLINED_REQUEST = 'A previous access request was declined. You may request access again.'


def _pin_locale(page: Page, locale: str) -> None:
    """Pin the locale before the bundle boots; copy is baked in as the DOM builds."""
    page.add_init_script(f"localStorage.setItem('revocompute-locale', '{locale}')")


# ── restricted Runner policy terms ────────────────────────────────────────────


def test_restricted_runner_detail_publishes_the_owning_policys_terms(page: Page) -> None:
    """The page that announces a restriction also states its published terms.

    The policy's notice and licence are server-projected vocabulary that the
    detail response already carries, so they are rendered verbatim on the same
    page that says access is restricted - never re-authored by the frontend.
    """
    access = AccessState.requestable_policy()
    mount_scenario(page, controlled_scenario().with_access(access))
    _pin_locale(page, "en")

    page.goto(f"{ORIGIN}/runners/sequence_demo")
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()

    expect(page.get_by_text(access.notice_title, exact=True)).to_be_visible()
    expect(page.get_by_text(access.notice_summary, exact=True)).to_be_visible()
    licence = page.get_by_role("link", name=access.license_name, exact=True)
    expect(licence).to_be_visible()
    # The licence resolves to the server-projected URL, opened away from the page.
    expect(licence).to_have_attribute("href", access.license_url)
    expect(licence).to_have_attribute("target", "_blank")


def test_unrestricted_runner_detail_publishes_no_policy_terms(page: Page) -> None:
    """An unrestricted Runner has no restriction terms to publish."""
    mount_scenario(page, controlled_scenario())
    terms = AccessState.requestable_policy()
    _pin_locale(page, "en")

    page.goto(f"{ORIGIN}/runners/sequence_demo")
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()

    assert page.get_by_text(terms.notice_summary).count() == 0
    assert page.get_by_text(terms.notice_title, exact=True).count() == 0
    assert page.locator(f"a[href='{terms.license_url}']").count() == 0


@pytest.mark.parametrize("licence_url", ["javascript:alert(1)", "/local/terms"])
def test_a_licence_url_outside_http_is_not_offered_as_a_destination(page: Page, licence_url: str) -> None:
    """The licence link admits only an absolute http/https destination.

    A server-supplied URL is a destination the page hands the reader, so a scheme
    that executes rather than navigates is dropped, and so is a value that is not
    a destination at all - resolving against the page origin would silently turn
    a relative path into a link on the Runner's own page. The notice text stays.
    """
    access = AccessState.requestable_policy(license_url=licence_url)
    mount_scenario(page, controlled_scenario().with_access(access))
    _pin_locale(page, "en")

    page.goto(f"{ORIGIN}/runners/sequence_demo")
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()

    expect(page.get_by_text(access.notice_title, exact=True)).to_be_visible()
    assert page.get_by_role("link", name=access.license_name, exact=True).count() == 0
    assert page.locator("a[href^='javascript:']").count() == 0
    assert page.locator("a[href$='/local/terms']").count() == 0


# ── a declined access request ─────────────────────────────────────────────────


def _request_control(page: Page):
    return page.get_by_role("button", name="Request access", exact=True)


def test_declined_request_is_acknowledged_before_the_control_is_offered_again(page: Page) -> None:
    """A rejected-but-requestable policy answers the previous request first.

    The reader is told the earlier request was declined before being asked to
    submit another one, and the run stays blocked in the meantime.
    """
    access = AccessState.requestable_policy(request_status="rejected")
    scenario = controlled_scenario().with_access(access)
    requests = mount_scenario(page, scenario).requests
    _pin_locale(page, "en")

    _mount_create_task(page)
    panel = page.locator(".ct-access-panel")
    expect(panel).to_be_visible()

    declined = panel.get_by_text(EN_DECLINED_REQUEST, exact=True)
    request = _request_control(page)
    expect(declined).to_be_visible()
    expect(request).to_be_visible()
    # The acknowledgement is stated before the control that asks for a new one.
    declined_box, request_box = declined.bounding_box(), request.bounding_box()
    assert declined_box is not None and request_box is not None
    assert declined_box["y"] < request_box["y"], "the declined state is stated before the request control"
    # The declined state is never silently permissive: the run stays blocked.
    expect(page.locator(".ct-validation")).to_contain_text("access approval")
    expect(_run_task(page)).to_be_disabled()
    assert requests.access_request() == ()


def test_a_requestable_policy_states_no_decline(page: Page) -> None:
    """Only an answered request carries the declined line."""
    mount_scenario(page, controlled_scenario().with_access(AccessState.requestable_policy()))
    _pin_locale(page, "en")

    _mount_create_task(page)
    expect(_request_control(page)).to_be_visible()
    assert page.get_by_text(EN_DECLINED_REQUEST, exact=True).count() == 0


# ── malformed Runner contracts ────────────────────────────────────────────────

# `_ENGINE_TEXT` is what a browser itself throws when the payload is not the
# contract the page reads; these cases assert its absence from the rendered body,
# alongside the presence of the frontend's own copy.
_ENGINE_TEXT = ("Cannot read propert", "undefined (reading", "is not a function", "TypeError", "[object Object]")


def _assert_no_engine_text(page: Page) -> None:
    body = page.evaluate("() => document.body.innerText")
    leaked = [signature for signature in _ENGINE_TEXT if signature in body]
    assert leaked == [], f"engine-internal text reached the reader: {leaked}"


def test_malformed_detail_contract_renders_frontend_copy(page: Page) -> None:
    """A detail body missing its contract fields is described by frontend copy."""
    errors: list[str] = []
    mount_scenario(page, controlled_scenario())
    _pin_locale(page, "en")
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route(f"{ORIGIN}/compute/api/types/sequence_demo", lambda route: route.fulfill(json={"name": "sequence_demo"}))

    page.goto(f"{ORIGIN}/runners/sequence_demo")
    expect(page.get_by_role("heading", name="Runner unavailable", exact=True)).to_be_visible()
    expect(page.get_by_text(EN_DETAIL_LOAD_FAILED, exact=True)).to_be_visible()
    _assert_no_engine_text(page)
    assert errors == []


def test_unknown_runner_detail_keeps_the_server_authored_message(page: Page) -> None:
    """A 404 is genuinely informative, so its server-authored message survives."""
    mount_scenario(page, controlled_scenario())
    _pin_locale(page, "en")

    page.goto(f"{ORIGIN}/runners/not_a_runner")
    expect(page.get_by_role("heading", name="Runner unavailable", exact=True)).to_be_visible()
    # The reader is told which method was not found, in the server's own words.
    expect(page.get_by_text("not_a_runner", exact=False).first).to_be_visible()
    _assert_no_engine_text(page)


def test_malformed_catalog_contract_renders_frontend_copy(page: Page) -> None:
    """A catalog body missing its contract fields is described by frontend copy."""
    errors: list[str] = []
    mount_scenario(page, controlled_scenario())
    _pin_locale(page, "en")
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route(f"{ORIGIN}/compute/api/types", lambda route: route.fulfill(json={"task_types": []}))

    page.goto(f"{ORIGIN}/runners")
    expect(page.locator(".runner-catalog")).to_contain_text(EN_LOAD_RUNNERS)
    _assert_no_engine_text(page)
    assert errors == []


@pytest.mark.parametrize("width", [320, 375, 768])
def test_catalog_density_switch_sizes_to_its_two_controls(page: Page, width: int) -> None:
    """The catalog's two-control density fieldset reserves no space it cannot use.

    The fieldset shares a layout rule with the Dashboard's three-control view
    switch, so on a stretched toolbar it used to carry a third, empty track. The
    property is measured against the render rather than against the rule: the
    fieldset's content box is compared with the width its two controls actually
    occupy, and both controls must still sit on one row inside it.
    """
    extras = [controlled_runner(name=f"method_{index}", display_name=f"Method {index}") for index in range(1, 6)]
    mount_scenario(page, controlled_scenario().with_catalog(extras))
    page.set_viewport_size({"width": width, "height": 900})

    page.goto(f"{ORIGIN}/runners")
    expect(page.locator(".catalog-count")).to_be_visible()
    switch = page.locator(".runner-toolbar fieldset").first
    expect(switch).to_be_visible()

    measured = page.evaluate(
        """
        () => {
            const field = document.querySelector('.runner-toolbar fieldset');
            const buttons = [...field.querySelectorAll('button')];
            const box = field.getBoundingClientRect();
            const occupancy = buttons.reduce((sum, b) => sum + b.getBoundingClientRect().width, 0)
                - (buttons.length - 1);   /* the controls share a 1px seam */
            const rows = new Set(buttons.map(b => Math.round(b.getBoundingClientRect().top)));
            return {
                free: box.width - occupancy,
                rows: rows.size,
                pageScrolls: document.documentElement.scrollWidth > document.documentElement.clientWidth,
            };
        }
        """
    )
    assert measured["rows"] == 1, "the two density controls share one fieldset row"
    assert measured["free"] < 8, f"the density fieldset reserves {measured['free']}px beyond its controls"
    assert measured["pageScrolls"] is False, "the fieldset fits the viewport"


# ── responsive, content-loaded surfaces ───────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "heading"),
    [
        ("/runners", "Runner catalog"),
        ("/compute/create_task?task_type=sequence_demo", "Sequence demo"),
        ("/compute/dashboard", "Tasks"),
        (f"/compute/results/{TASK_ID}", "sample.fasta"),
    ],
)
def test_narrow_surfaces_keep_their_heading(page: Page, path: str, heading: str) -> None:
    """Catalog, Create Task, Dashboard, and Result Workspace at 320px."""
    mount_scenario(page, controlled_scenario().with_result("minimal_success"))
    page.set_viewport_size({"width": 320, "height": 760})

    page.goto(f"{ORIGIN}{path}")
    expect(page.get_by_role("heading", name=heading, exact=True).first).to_be_visible()


def test_narrow_surfaces_that_fit_do_not_overflow(page: Page) -> None:
    """The 320px surfaces whose rendered content fits stay overflow-free."""
    mount_scenario(page, controlled_scenario().with_result("minimal_success"))
    page.set_viewport_size({"width": 320, "height": 760})

    # ``selector`` is the surface's own fully-rendered content: scroll width is
    # only meaningful once the async content (not just the shell) is on screen.
    for path, selector in (
        ("/runners", ".catalog-count"),
        ("/compute/dashboard", ".task-card"),
    ):
        page.goto(f"{ORIGIN}{path}")
        expect(page.locator(selector)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), path


@pytest.mark.parametrize("width", [320, 390])
@pytest.mark.parametrize(
    ("path", "selector"),
    [
        ("/compute/create_task?task_type=sequence_demo", ".ct-protocol"),
        (f"/compute/results/{TASK_ID}", ".result-header"),
    ],
)
def test_narrow_content_heavy_surfaces_fit_the_viewport(page: Page, path: str, selector: str, width: int) -> None:
    """Create Task and the Result Workspace fit the phone viewport floor.

    Content-heavy surfaces hold the same 320px floor the rest of the app holds,
    and the 390px width a common phone reports; at both, neither the protocol
    column nor the result header actions push the document past the viewport.
    The surface's own content node is awaited first, so the measurement is of
    the settled layout rather than of a partially-rendered shell.
    """
    mount_scenario(page, controlled_scenario().with_result("minimal_success"))
    page.set_viewport_size({"width": width, "height": 760})
    page.goto(f"{ORIGIN}{path}")
    expect(page.locator(selector)).to_be_visible()

    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


@pytest.mark.parametrize("width", [640, 768, 900, 960])
def test_parameter_headings_stay_within_their_cells(page: Page, width: int) -> None:
    """A parameter heading never paints past its own grid cell.

    Two adjacent basic parameters put a label and a Reset button in the same
    heading row. The heading is a space-between flex row, so if the label cannot
    shrink the Reset is pushed into the neighbouring cell and the two sets of
    glyphs overlap even though the document itself never scrolls. Assert the
    visible invariant directly: every element rendered inside a parameter field
    stays within that field's cell box.
    """
    mount_scenario(page, structure_scenario())
    page.set_viewport_size({"width": width, "height": 1000})

    page.goto(f"{ORIGIN}/compute/create_task?task_type=fold_demo")
    expect(page.locator(".ct-workbench")).to_be_visible()
    # The parameter grid is below the fold; measure only after it is on screen.
    page.locator(".ct-parameter-grid").first.scroll_into_view_if_needed()
    expect(page.locator(".ct-parameter-grid .ct-reset").first).to_be_visible()

    offenders = page.evaluate(
        """() => {
        const grid = document.querySelector('.ct-parameter-grid');
        const out = [];
        for (const field of grid.querySelectorAll(':scope > .ct-parameter')) {
            const bound = field.getBoundingClientRect().right;
            const over = [];
            for (const el of field.querySelectorAll('*')) {
                const right = el.getBoundingClientRect().right;
                if (right > bound + 0.5) over.push(el.className);
            }
            if (over.length) out.push({ cell: field.querySelector('.ct-label').textContent, over });
        }
        return out;
    }"""
    )
    assert offenders == [], f"parameter heading paints past its cell at {width}px: {offenders}"


# ── representative real contracts ─────────────────────────────────────────────


def test_gpu_structure_runner_is_exercisable_without_weights_or_inference(page: Page) -> None:
    """A GPU multi-stage Runner renders and submits with only fixture bytes."""
    requests = mount_scenario(page, structure_scenario()).requests

    page.goto(f"{ORIGIN}/runners/fold_demo")
    expect(page.get_by_role("heading", name="Fold demo", exact=True)).to_be_visible()
    expect(page.locator(".runner-facts")).to_contain_text("GPU")
    expect(page.locator(".stage-list li")).to_have_count(3)
    expect(page.locator(".stage-list")).to_contain_text("Structure prediction")
    expect(page.locator(".stage-list")).to_contain_text("Confidence scoring")

    page.get_by_role("link", name="Create task").first.click()
    expect(page.locator(".ct-method-facts")).to_contain_text("GPU method")
    _provide_sequence(page)
    _run_task(page).click()

    expect(page.get_by_role("heading", name="Tasks", exact=True)).to_be_visible()
    assert requests.submit()
