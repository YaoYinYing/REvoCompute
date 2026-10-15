# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the job-oriented guided tours and the Home agent entry.

There are three tours, not one welcome carousel, and each belongs to a job: the
create path from the register, the result tour from a result that really exists,
and the read-only administration walk. These cases drive the real bundle and
assert what a reader can actually observe:

* each flow owns its own progress keys, so a completion in one is not a
  completion in another and a result tour cannot go stale against a different
  result;
* a flow is offered only where its job is — a first-time reader with no finished
  result is never offered the result tour, and no tour ever invents a task id;
* no step submits, cancels, deletes, or mutates anything, and the administration
  walk issues no mutation even where a mutation is one click away;
* the public Home entry states the deployment's own MCP capability rather than
  the repository's, so it stays documentation-only unless the server says it
  answers.
"""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import (
    ADMIN_AUTH,
    DEFAULT_TASK_ID,
    Session,
    controlled_scenario,
    mount_scenario,
)

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"

#: The create flow's keys. Every other flow must leave these untouched.
CREATE_DONE, CREATE_STEP = "revocompute-tour-done", "revocompute-tour-step"
#: The result flow's keys.
RESULT_DONE, RESULT_STEP = "revocompute-tour-results-done", "revocompute-tour-results-step"
#: The administration flow's keys.
ADMIN_DONE, ADMIN_STEP = "revocompute-tour-admin-done", "revocompute-tour-admin-step"

RESULT_URL = f"/compute/results/{DEFAULT_TASK_ID}"

#: Every request that would change server state. A tour is a reading aid: no
#: flow may reach one of these, however close the flow's own surface puts it.
MUTATIONS = (
    "/compute/api/post",
    "/compute/api/delete",
    "/compute/api/cancel",
    "/compute/api/access/requests",
)


class _Traffic:
    """Every request the browser made, so a case can state what it must *not* do."""

    def __init__(self, page: Page) -> None:
        self.records: list[tuple[str, str]] = []
        page.on("request", lambda request: self.records.append((request.method, request.url)))

    def paths(self, method: str | None = None) -> list[str]:
        return [url.split(ORIGIN, 1)[-1] for http, url in self.records if method is None or http == method]

    def mutating(self) -> list[tuple[str, str]]:
        return [
            (method, url) for method, url in self.records
            if method != "GET" and any(marker in url for marker in MUTATIONS)
        ]

    def admin_writes(self) -> list[tuple[str, str]]:
        return [
            (method, url) for method, url in self.records
            if method != "GET" and "/compute/api/auth/admin/" in url
        ]


def _stored(page: Page, key: str) -> str | None:
    return page.evaluate("(key) => localStorage.getItem(key)", key)


def _admin_api(page: Page) -> None:
    """Serve the Administration APIs the four read-only surfaces project.

    Declared at the case rather than in the shared fixture router: these are
    administrator-only projections with no canonical scenario of their own, and
    a non-administrator case must be able to assert that none of them is ever
    requested. It is registered *after* the scenario router, because Playwright
    consults the most recently registered matching route first and the scenario
    router owns a catch-all.
    """
    fleet = {
        "runners": [{
            "runner_family": "sequence_demo",
            "readiness": {
                "status": "READY", "reason_code": "READY", "message": "Ready", "next_action": "none",
                "evidence": {
                    "sif_path": "/images/sequence_demo.sif", "sif_exists": True, "sif_sha256": "sha256:sif",
                    "build_provenance_current": True, "build_provenance_digest": "sha256:build",
                    "runtime_bundle_sha256": None, "receipt_exists": True, "receipt_valid": True,
                    "receipt_tested_at": "2026-01-01T00:00:00Z", "required_smoke_cases": ["smoke"],
                    "passed_smoke_cases": ["smoke"], "doctor_ok": True,
                },
            },
            "capacity": {"available": True, "reason": "scheduler_available"},
            "access": {"restricted": False, "granted": True, "policy_id": None},
            "in_flight": None,
        }],
        "executor": {"available": True, "reason": "operator_executor_available"},
    }
    credit = {
        "user_id": 2, "period": "2026-10", "credit_unit_gpu_seconds": 60, "monthly_grant_gpu_seconds": 7200,
        "usage_gpu_seconds": 1800, "adjustment_gpu_seconds": 0, "remaining_gpu_seconds": 5400,
        "monthly_grant_credits": 120, "usage_credits": 30, "adjustment_credits": 0, "remaining_credits": 90,
        "allow_gpu_use": True, "history": [],
    }
    config = {
        "task_types": [{
            "tool": "sequence_demo", "display_name": "Sequence demo", "enabled": True, "requires_gpu": False,
            "runtime_family": "generic", "is_workflow_stage": False, "category": "evolution", "inputs": [],
            "parameter_count": 1, "stage_count": 0, "effective_resources": {"cpus": 2, "memory": "4G"},
        }],
        "resources": {"cpus": 2, "memory": "4G", "max_runtime_seconds": 3600, "slurm_partition": "cpu"},
        "ignored_resource_keys": [], "slurm": {"enabled": True, "allowed_queues": ["cpu", "gpu"]},
    }
    fulfill = lambda payload: (lambda route: route.fulfill(json=payload))  # noqa: E731 - a route handler per payload

    page.route(f"{ORIGIN}/compute/api/auth/admin/**", fulfill({}))
    page.route(f"{ORIGIN}/compute/api/auth/admin/runners", fulfill(fleet))
    page.route(f"{ORIGIN}/compute/api/auth/admin/runners/*/history?*", fulfill({"history": []}))
    page.route(f"{ORIGIN}/compute/api/auth/admin/runners/*", fulfill(fleet["runners"][0]))
    page.route(f"{ORIGIN}/compute/api/auth/admin/users", fulfill({"users": []}))
    page.route(f"{ORIGIN}/compute/api/auth/admin/users/*/gpu-credit", fulfill(credit))
    page.route(f"{ORIGIN}/compute/api/auth/admin/access/requests?*", fulfill({"requests": []}))
    page.route(f"{ORIGIN}/compute/api/auth/admin/access/policies", fulfill({"policies": []}))
    page.route(f"{ORIGIN}/compute/api/auth/admin/access/events?*", fulfill({"events": []}))
    page.route(f"{ORIGIN}/compute/api/auth/admin/gpu-credit/reconciliation", fulfill({"result": None, "allocations": []}))
    page.route(f"{ORIGIN}/compute/api/auth/admin/config", fulfill(config))
    page.route(f"{ORIGIN}/compute/api/auth/admin/logs/archives", fulfill({"logs": []}))
    page.route(
        f"{ORIGIN}/compute/api/auth/admin/logs/*",
        lambda route: route.fulfill(content_type="text/plain", body="worker ready\ntask accepted\n"),
    )


# ── create flow: the register owns it, and it never submits ───────────────────


def test_create_tour_is_offered_on_the_register_and_never_submits_a_task(page: Page) -> None:
    traffic = _Traffic(page)
    router = mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()

    page.get_by_role("button", name="Guided tour").click()
    callout = page.locator(".tour-callout")
    expect(callout).to_contain_text("Step 1 of 5")
    # Every step announces itself as a position in this flow, not in a shared one.
    assert _stored(page, CREATE_STEP) == "0"
    assert _stored(page, RESULT_STEP) is None and _stored(page, ADMIN_STEP) is None

    callout.get_by_role("button", name="Next").click()
    expect(callout).to_contain_text("Step 2 of 5")
    callout.get_by_role("button", name="Next").click()
    expect(page).to_have_url(f"{ORIGIN}/runners")
    callout.get_by_role("button", name="Next").click()
    expect(page).to_have_url(f"{ORIGIN}/compute/create_task")
    callout.get_by_role("button", name="Next").click()
    expect(callout).to_have_count(0)

    # Walking the whole path submits nothing: the reader still has to run the task.
    assert traffic.mutating() == []
    assert router.requests.submit() == ()
    # Nor did it pursue a result route it has no id for.
    assert [path for path in traffic.paths() if path.startswith("/compute/results")] == []


def test_skipping_the_create_tour_leaves_the_register_entry_for_next_time(page: Page) -> None:
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    page.get_by_role("button", name="Guided tour").click()
    page.locator(".tour-callout").get_by_role("button", name="Skip").click()
    expect(page.locator(".tour-callout")).to_have_count(0)

    # Leaving early is not a completion: the entry stays, and it is still a start.
    assert _stored(page, CREATE_DONE) is None
    launcher = page.locator(".tour-launcher")
    expect(launcher).to_be_visible()
    launcher.click()
    expect(page.locator(".tour-callout")).to_contain_text("Step 1 of 5")
    # Abandoning the create flow leaves the other flows' state alone.
    assert _stored(page, RESULT_STEP) is None and _stored(page, ADMIN_STEP) is None
    assert _stored(page, RESULT_DONE) is None and _stored(page, ADMIN_DONE) is None


def test_a_reader_navigation_ends_the_flow_and_back_leaves_no_orphan(page: Page) -> None:
    # The persistent shell changes the route without reloading the document, so the
    # tour cannot rely on `pagehide` alone: an in-document navigation must also tear
    # the overlay down, or it decorates a page the reader has left. The tour ends the
    # *flow* on that navigation - the reader left the job the flow was walking them
    # through - and leaves no progress dangling, so coming back does not resume a
    # step the reader never finished.
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    page.get_by_role("button", name="Guided tour").click()
    expect(page.locator(".tour-callout")).to_contain_text("Step 1 of 5")
    assert _stored(page, CREATE_STEP) == "0"

    # A real in-app link: intercepted by the shell, rendered in-document, no pagehide.
    page.locator("[data-nav-group='account']").get_by_role("link", name="Account", exact=True).click()
    expect(page.get_by_role("heading", name="Account", exact=True)).to_be_visible()
    expect(page.locator(".tour-callout")).to_have_count(0)
    expect(page.locator(".tour-anchor")).to_have_count(0)
    # The reader left the flow, so its progress is cleared rather than left to
    # resume from a page they walked away from. It was not a completion either.
    assert _stored(page, CREATE_STEP) is None
    assert _stored(page, "revocompute-tour-flow") is None
    assert _stored(page, CREATE_DONE) is None

    # Back is the reader's own traversal, not the tour's: the overlay does not
    # reappear and nothing was left orphaned on the page it returns to.
    page.go_back()
    expect(page.locator(".task-card").first).to_be_visible()
    page.wait_for_timeout(300)
    expect(page.locator(".tour-callout")).to_have_count(0)
    expect(page.locator(".tour-anchor")).to_have_count(0)
    assert _stored(page, CREATE_STEP) is None


def test_the_abort_signal_fires_on_a_route_change_and_not_on_a_first_render(page: Page) -> None:
    # The signal is the navigation layer's contract with whatever the leaving page
    # put in the document. It must fire on a real in-document route change and never
    # on a document's first render - a first render is a page *arriving*, with
    # nothing behind it to tear down - or a tour would end the moment it opened.
    mount_scenario(page, controlled_scenario())
    page.add_init_script(
        "window.__tourAborts = 0;"
        "document.addEventListener('revocompute:tour-abort', () => { window.__tourAborts += 1; });"
    )
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    assert page.evaluate("window.__tourAborts") == 0

    # An in-page fragment scroll is not a route change and must not announce one.
    page.evaluate("() => history.pushState(null, '', location.pathname + '#fragment-not-a-route')")
    page.evaluate("() => window.dispatchEvent(new PopStateEvent('popstate'))")
    page.wait_for_timeout(150)
    assert page.evaluate("window.__tourAborts") == 0

    # A real in-document route change announces it exactly once.
    page.locator("[data-nav-group='account']").get_by_role("link", name="Account", exact=True).click()
    expect(page.get_by_role("heading", name="Account", exact=True)).to_be_visible()
    assert page.evaluate("window.__tourAborts") == 1


def test_a_tour_survives_a_reader_leg_into_the_second_route_that_owns_an_overlay(page: Page) -> None:
    # Two Account destinations now render their own overlays: Account (the tour
    # anchor) and Quota (the resource position). A Quota page that put an overlay
    # in the document must not be mistaken for the reader abandoning a flow: the
    # flow is ended by a navigation the reader made, which the abort signal states
    # exactly once, so the leg's own tear-down fires once and the flow's progress
    # is cleared rather than left to resume on a page it never walked to.
    mount_scenario(page, controlled_scenario())
    page.add_init_script(
        "window.__tourAborts = 0;"
        "document.addEventListener('revocompute:tour-abort', () => { window.__tourAborts += 1; });"
    )
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    page.get_by_role("button", name="Guided tour").click()
    expect(page.locator(".tour-callout")).to_contain_text("Step 1 of 5")
    assert _stored(page, CREATE_STEP) == "0"

    # The reader takes the Account region's own Quota destination: an in-document
    # navigation into the second overlay-owning route.
    page.locator("[data-nav-group='account']").get_by_role("link", name="Quota", exact=True).click()
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/quota"

    # The tour's overlay is gone from the Quota page, the abort fired exactly once
    # for the one navigation, and the flow's progress is cleared - the reader left
    # the job the flow was walking them through, it was not a completion.
    expect(page.locator(".tour-callout")).to_have_count(0)
    expect(page.locator(".tour-anchor")).to_have_count(0)
    assert page.evaluate("window.__tourAborts") == 1
    assert _stored(page, CREATE_STEP) is None
    assert _stored(page, "revocompute-tour-flow") is None
    assert _stored(page, CREATE_DONE) is None


def test_a_tour_step_across_routes_resumes_with_its_progress_intact(page: Page) -> None:
    # A step whose surface is another route advances by navigating, and that
    # navigation is the tour walking its reader forward - not the reader leaving -
    # so the flow must resume on the far side with its step, its flow, and its
    # unfinished status intact.
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    page.get_by_role("button", name="Guided tour").click()
    callout = page.locator(".tour-callout")
    expect(callout).to_contain_text("Step 1 of 5")
    callout.get_by_role("button", name="Next").click()
    expect(callout).to_contain_text("Step 2 of 5")

    # Step 3 lives on the Runner catalog: advancing navigates there and resumes.
    callout.get_by_role("button", name="Next").click()
    expect(page).to_have_url(f"{ORIGIN}/runners")
    expect(page.locator(".tour-callout")).to_contain_text("Step 3 of 5")
    assert _stored(page, CREATE_STEP) == "2"
    assert _stored(page, "revocompute-tour-flow") == "create"
    assert _stored(page, CREATE_DONE) is None


# ── result flow: conditional on a result that really exists ───────────────────


def test_no_finished_result_means_no_result_tour_and_no_fabricated_id(page: Page) -> None:
    # A first-time reader: the account holds no finished result at all.
    traffic = _Traffic(page)
    router = mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()

    # The create entry is the only tour the register offers.
    expect(page.locator(".tour-launcher")).to_have_count(1)
    expect(page.get_by_role("button", name="Tour this result")).to_have_count(0)
    assert _stored(page, "revocompute-tour-result") is None

    # No step of the create flow can land on a result route without an id.
    page.get_by_role("button", name="Guided tour").click()
    for _ in range(4):
        page.locator(".tour-callout").get_by_role("button", name="Next").click()
    expect(page).to_have_url(f"{ORIGIN}/compute/create_task")
    expect(page.locator(".tour-callout")).to_have_count(0)
    assert [path for path in traffic.paths() if path.startswith("/compute/results")] == []
    assert traffic.mutating() == []
    assert router.requests.result_manifest() == ()


def test_result_tour_is_offered_only_on_the_real_result_and_keeps_its_own_progress(page: Page) -> None:
    traffic = _Traffic(page)
    mount_scenario(page, controlled_scenario().with_result("minimal_success"))
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    # The register records the concrete result the flow may visit; it is never invented.
    assert _stored(page, "revocompute-tour-result") == RESULT_URL
    # The result flow belongs to the result page, not to the register.
    expect(page.get_by_role("button", name="Tour this result")).to_have_count(0)

    page.goto(f"{ORIGIN}{RESULT_URL}")
    expect(page.locator(".result-record")).to_be_visible()
    page.get_by_role("button", name="Tour this result").click()
    callout = page.locator(".tour-callout")
    expect(callout).to_contain_text("Step 1 of 3")
    # Three steps, its own keys, and nothing shared with the create flow.
    assert _stored(page, RESULT_STEP) == "0"
    assert _stored(page, CREATE_STEP) is None and _stored(page, ADMIN_STEP) is None

    for index, anchor in ((1, ".result-preview"), (2, ".result-record")):
        callout.get_by_role("button", name="Next").click()
        expect(callout).to_contain_text(f"Step {index + 1} of 3")
        expect(page.locator(anchor)).to_have_class(re.compile(r".*\btour-anchor\b.*"))

    callout.get_by_role("button", name="Finish").click()
    expect(page.locator(".tour-callout")).to_have_count(0)
    # Finishing the result tour completes *that* flow, bound to this result.
    assert _stored(page, RESULT_DONE) == DEFAULT_TASK_ID
    assert _stored(page, CREATE_DONE) is None

    # Reading the result never mutated anything and never looped on a route.
    assert traffic.mutating() == []
    navigations = [path for path in traffic.paths() if path.startswith("/compute/") and "/api/" not in path]
    assert navigations.count(RESULT_URL) == 1, navigations


def test_a_different_result_is_not_treated_as_already_seen(page: Page) -> None:
    mount_scenario(page, controlled_scenario().with_result("minimal_success"))
    other = "f" * 32
    page.goto(f"{ORIGIN}{RESULT_URL}")
    expect(page.locator(".result-record")).to_be_visible()
    # A completion recorded for another result must not mark this one finished.
    page.evaluate("(id) => localStorage.setItem('revocompute-tour-results-done', id)", other)
    page.reload()
    expect(page.locator(".result-record")).to_be_visible()
    page.get_by_role("button", name="Tour this result").click()
    expect(page.locator(".tour-callout")).to_contain_text("Step 1 of 3")


# ── administration flow: read-only, and only for an administrator ─────────────


def test_admin_tour_walks_the_read_only_surfaces_without_a_single_mutation(page: Page) -> None:
    traffic = _Traffic(page)
    mount_scenario(page, controlled_scenario(session=ADMIN_AUTH))
    _admin_api(page)
    page.goto(f"{ORIGIN}/compute/runner_fleet")
    expect(page.locator(".admin-table-scroll")).to_be_visible()
    page.get_by_role("button", name="Tour the admin console").click()
    callout = page.locator(".tour-callout")
    expect(callout).to_contain_text("Step 1 of 4")
    assert _stored(page, ADMIN_STEP) == "0"
    assert _stored(page, CREATE_STEP) is None and _stored(page, RESULT_STEP) is None

    # Readiness first: the fleet step names the derived state it is looking at.
    expect(callout).to_contain_text("derived readiness")

    for step, (route, anchor) in enumerate(
        (
            ("/compute/user_control", ".user-admin-table"),
            ("/compute/configuration", ".config-type-list"),
            ("/compute/logs", ".admin-log-output"),
        ),
        start=2,
    ):
        callout.get_by_role("button", name="Next").click()
        expect(page).to_have_url(f"{ORIGIN}{route}")
        expect(callout).to_contain_text(f"Step {step} of 4")
        expect(page.locator(anchor)).to_have_class(re.compile(r".*\btour-anchor\b.*"))

    callout.get_by_role("button", name="Finish").click()
    expect(page.locator(".tour-callout")).to_have_count(0)
    assert _stored(page, ADMIN_DONE) == "true"
    # The administration walk completes only the administration flow.
    assert _stored(page, CREATE_DONE) is None and _stored(page, RESULT_DONE) is None

    # A read-only walk issues no mutation and no privileged host action, even
    # though every one of these surfaces puts a mutation within a click.
    assert traffic.admin_writes() == []
    assert traffic.mutating() == []
    # Each surface was opened once: resuming the flow is not a navigation loop.
    visited = [path for path in traffic.paths() if path.startswith("/compute/") and "/api/" not in path]
    for route in ("/compute/runner_fleet", "/compute/user_control", "/compute/configuration", "/compute/logs"):
        assert visited.count(route) == 1, (route, visited)


@pytest.mark.parametrize("role", ["guest", "session"], ids=["guest", "ordinary-user"])
def test_a_non_administrator_gets_no_admin_tour_and_no_admin_api_call(page: Page, role: str) -> None:
    traffic = _Traffic(page)
    mount_scenario(page, controlled_scenario(session=Session(role=role)))
    _admin_api(page)
    page.goto(f"{ORIGIN}/compute/runner_fleet")
    # Authorization, not visual hiding: the surface never mounts for this reader.
    expect(page.get_by_role("heading", name="Access denied")).to_be_visible()
    expect(page.locator(".admin-page")).to_have_count(0)
    expect(page.locator(".tour-launcher")).to_have_count(0)
    expect(page.locator(".tour-callout")).to_have_count(0)
    # No administration projection was even requested, and no flow state was written.
    assert [path for path in traffic.paths() if "/compute/api/auth/admin/" in path] == []
    assert _stored(page, ADMIN_STEP) is None and _stored(page, ADMIN_DONE) is None
    assert traffic.mutating() == []


def test_the_admin_tour_is_not_offered_on_an_ordinary_readers_own_surfaces(page: Page) -> None:
    mount_scenario(page, controlled_scenario(session=ADMIN_AUTH))
    # An administrator reading their own dashboard and result gets no admin entry:
    # the administration flow belongs to the administration surfaces.
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    expect(page.get_by_role("button", name="Guided tour")).to_be_visible()
    expect(page.get_by_role("button", name="Tour the admin console")).to_have_count(0)


# ── the public Home entry states the deployment, not the repository ───────────


def test_home_agent_entry_stays_documentation_only_on_a_deployment_without_mcp(page: Page) -> None:
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/")
    aside = page.locator(".agent-guide")
    expect(aside).to_be_visible()
    expect(aside.get_by_role("heading", name="Connect an AI agent")).to_be_visible()
    # The always-available agent guide is the only thing offered.
    expect(aside.locator("[data-agent-url]")).to_have_attribute("href", "/skills.md")
    expect(aside).not_to_have_attribute("data-mcp-state", "enabled")
    expect(aside.locator(".agent-guide-endpoint")).to_have_count(0)
    expect(aside).to_contain_text("stable guide")


def test_home_agent_entry_offers_the_endpoint_only_when_the_deployment_reports_it(page: Page) -> None:
    mount_scenario(page, controlled_scenario().with_mcp_endpoint("/k/mcp"))
    page.goto(f"{ORIGIN}/")
    aside = page.locator(".agent-guide")
    expect(aside).to_have_attribute("data-mcp-state", "enabled")
    # The guide stays: a deployment that speaks MCP still serves /skills.md.
    expect(aside.locator("[data-agent-url]")).to_have_attribute("href", "/skills.md")
    endpoint = aside.locator(".agent-guide-endpoint")
    expect(endpoint).to_have_attribute("href", "/k/mcp")
    expect(endpoint).to_have_attribute("aria-label", f"MCP endpoint: {ORIGIN}/k/mcp")
    expect(aside).to_contain_text("over MCP")


def test_home_agent_entry_copy_is_localized(page: Page) -> None:
    mount_scenario(page, controlled_scenario().with_mcp_endpoint("/k/mcp"))
    page.goto(f"{ORIGIN}/")
    page.locator(".lang-menu > summary").click()
    page.locator('[data-locale="zh-CN"]').click()
    expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
    aside = page.locator(".agent-guide")
    expect(aside.get_by_role("heading", name="连接 AI 智能体")).to_be_visible()
    expect(aside.locator(".agent-guide-endpoint")).to_have_attribute("aria-label", f"MCP 端点：{ORIGIN}/k/mcp")
