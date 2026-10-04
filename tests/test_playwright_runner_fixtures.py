# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the Runner-facing states the fixture harness exposes.

``test_playwright_application.py`` owns the ordinary navigation → create →
submit → finished journey. This file covers the states around it that a real
Runner deployment produces and that the harness now makes cheap: a preflight
rejection and a preflight warning, infrastructure readiness, catalog
cardinality, a failed lifecycle with diagnostics, restricted-Runner access
pending versus granted, narrow-screen rendering of a loaded workspace, and two
representative real contract shapes (a GPU structure Runner and PSSM-GREMLIN).

Every case drives the production bundle through
``tests/frontend_fixtures/`` and states the behavior the frontend actually
exhibits today.
"""

from __future__ import annotations

from typing import Sequence

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import (
    AccessState,
    controlled_runner,
    controlled_scenario,
    mount_scenario,
    pssm_gremlin_scenario,
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
    page.get_by_role("button", name="Review", exact=True).click()

    expect(page.locator(".ct-validation")).to_contain_text("Parameter 'iterations' must be at least 1.")
    expect(page.locator(".ct-validation")).to_contain_text("1 check failed")
    expect(page.get_by_role("button", name="Review again", exact=True)).to_be_enabled()
    expect(page).to_have_url(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")
    assert requests.preflight("sequence_demo")
    assert requests.submit() == ()


@pytest.mark.parametrize("outcome", ["warning", "capacity_busy"])
def test_preflight_warning_is_inline_and_keeps_one_submit_action(page: Page, outcome: str) -> None:
    """A non-blocking finding is reported inline with no extra confirmation stage."""
    scenario = controlled_scenario().with_preflight(outcome)
    requests = mount_scenario(page, scenario).requests

    _mount_create_task(page)
    _provide_sequence(page)
    page.get_by_role("button", name="Review", exact=True).click()

    expect(page.locator(".ct-validation")).to_contain_text("All checks passed")
    expect(page.locator(".ct-validation")).to_contain_text(
        "Inputs will be re-numbered from 1." if outcome == "warning" else "The scheduler is busy; the task will queue."
    )
    # The warning does not introduce a dialog or a second gate: the same action
    # control advances from review to run and submits.
    assert page.get_by_role("dialog").count() == 0
    page.get_by_role("button", name="Run", exact=True).click()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    assert requests.submit()


def test_runner_not_ready_preflight_blocks_with_a_distinct_message(page: Page) -> None:
    """An unavailable Runner is an admission error, and the method stays addressable."""
    scenario = controlled_scenario().with_preflight("runner_not_ready")
    requests = mount_scenario(page, scenario).requests

    _mount_create_task(page)
    _provide_sequence(page)
    page.get_by_role("button", name="Review", exact=True).click()

    expect(page.locator(".ct-validation")).to_contain_text("Runner unavailable")
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
    expect(readiness).to_have_text(banner)
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
    page.get_by_role("button", name="Review", exact=True).click()

    expect(page.locator(".ct-validation")).to_contain_text("Infrastructure unavailable")
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
    expect(page.locator(".catalog-count")).to_have_text(f"{count} {'method' if count == 1 else 'methods'}")
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
    page.get_by_text("Execution error").click()
    expect(page.get_by_text("Runner stopped before publishing a model")).to_be_visible()

    _open_result_after_lifecycle(page, ("queued", "running"), "Runner stopped before publishing a model")
    expect(page.locator(".result-status")).to_contain_text("Runner stopped before publishing a model")
    expect(page.get_by_role("heading", name="Diagnostics")).to_be_visible()
    expect(page.locator(".result-file-list, .result-files").get_by_text("task_failed.txt", exact=True)).to_be_visible()
    assert requests.status_polls()
    assert requests.result_manifest()


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
    expect(page.get_by_role("link", name="Create task").first).to_be_visible()

    page.get_by_role("link", name="Create task").first.click()
    expect(page.locator(".ct-access-panel h2")).to_have_text(panel)
    # No in-place request control is offered once the policy is pending or granted.
    expect(page.get_by_role("button", name="Request access", exact=True)).to_have_count(0)
    if pending_notice is not None:
        expect(page.locator(".ct-validation")).to_contain_text(pending_notice)
        expect(page.get_by_role("button", name="Review", exact=True)).to_be_disabled()
    else:
        expect(page.locator(".ct-validation")).not_to_contain_text("access approval")
    expect(page).to_have_url(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")
    assert requests.access_request() == ()


# ── responsive, content-loaded surfaces ───────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "heading"),
    [
        ("/runners", "Runner catalog"),
        ("/compute/create_task?task_type=sequence_demo", "Sequence demo"),
        ("/compute/dashboard", "Dashboard"),
        (f"/compute/results/{TASK_ID}", "Sequence demo"),
    ],
)
def test_narrow_surfaces_keep_their_heading(page: Page, path: str, heading: str) -> None:
    """Catalog, Create Task, Dashboard, and Result Workspace at 320px."""
    mount_scenario(page, controlled_scenario().with_result("minimal_success"))
    page.set_viewport_size({"width": 320, "height": 760})

    page.goto(f"{ORIGIN}{path}")
    expect(page.get_by_role("heading", name=heading, exact=True).first).to_be_visible()


def test_narrow_surfaces_that_fit_do_not_overflow(page: Page) -> None:
    """The 320px surfaces whose content currently fits stay overflow-free."""
    mount_scenario(page, controlled_scenario().with_result("minimal_success"))
    page.set_viewport_size({"width": 320, "height": 760})

    for path in ("/runners", "/compute/create_task?task_type=sequence_demo", "/compute/dashboard"):
        page.goto(f"{ORIGIN}{path}")
        expect(page.locator(".app-header")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), path


@pytest.mark.xfail(reason="Result Workspace overflows a 320px viewport", strict=False)
def test_narrow_result_workspace_fits_the_viewport(page: Page) -> None:
    """The Result Workspace should not overflow a 320px viewport.

    Known defect: the result header's content (identity plus the wrapped action
    row) currently exceeds 320px, so this assertion is expected to fail. It is
    marked non-strict, so fixing the layout flips the case to XPASS rather than
    to a failure; the requirement is stated positively rather than pinning the
    current overflow as desired behavior.
    """
    mount_scenario(page, controlled_scenario().with_result("minimal_success"))
    page.set_viewport_size({"width": 320, "height": 760})
    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")
    expect(page.get_by_role("heading", name="Sequence demo", exact=True).first).to_be_visible()

    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


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
    page.get_by_role("button", name="Review", exact=True).click()
    expect(page.get_by_role("button", name="Run", exact=True)).to_be_enabled()
    page.get_by_role("button", name="Run", exact=True).click()

    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    assert requests.submit()


def test_pssm_gremlin_contract_projects_into_catalog_create_task_and_result(page: Page) -> None:
    """The realistic PSSM-GREMLIN scenario renders its views from fixture bytes."""
    mount_scenario(page, pssm_gremlin_scenario())

    page.goto(f"{ORIGIN}/runners/gremlin_lh_fit")
    expect(page.get_by_role("heading", name="GREMLIN_LH Potts model", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Protein multiple-sequence alignment")).to_be_visible()

    page.get_by_role("link", name="Create task").first.click()
    expect(page.get_by_role("heading", name="GREMLIN_LH Potts model", exact=True)).to_be_visible()

    _open_result_after_lifecycle(page, ("queued", "running"), "finished")
    expect(page.get_by_role("heading", name="GREMLIN_LH Potts model", exact=True)).to_be_visible()
    expect(page.locator(".result-tab")).to_have_count(5)
    expect(page.locator(".result-tab", has_text="APC-corrected coupling strengths")).to_be_visible()
    expect(page.locator(".result-file-group", has_text="Diagnostics")).to_be_visible()
