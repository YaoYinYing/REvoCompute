# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""The Fleet's Active image cell renders server-established identity.

A representative 32-family register carries the few lifecycle variants a real
deployment shows: an identified active artifact, a missing artifact, and an
artifact whose identity the server could not establish.  The page must render
those three states from the server's projection, keep the evidence dialog
reachable from the keyboard, and stay within the viewport at phone width.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

import browser_frontend_assets
from test_playwright_application import _current_user, _install_app

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "https://revocompute.example"
FLEET_SIZE = 32


def _row(name: str, variant: str) -> dict:
    evidence = {
        "sif_path": f"/images/{name}.sif",
        "sif_exists": variant != "missing",
        "sif_sha256": None,
        "build_provenance_current": variant in {"active", "stale"},
        "build_provenance_digest": "sha256:build" if variant != "missing" else None,
        "runtime_bundle_sha256": None,
        "receipt_exists": variant in {"active", "stale"},
        "receipt_valid": variant == "active",
        "receipt_tested_at": "2026-01-01T00:00:00Z" if variant in {"active", "stale"} else None,
        "required_smoke_cases": ["smoke"],
        "passed_smoke_cases": ["smoke"] if variant == "active" else [],
        "doctor_ok": variant != "unknown",
    }
    if variant in {"active", "stale"}:
        evidence["sif_sha256"] = f"sha256:{name[-2:]}".ljust(71, "a")
        image = {"state": "ACTIVE", "sha256": evidence["sif_sha256"], "reason_code": None}
    elif variant == "missing":
        image = {"state": "MISSING", "sha256": None, "reason_code": "SIF_MISSING"}
    elif variant == "promotion":
        # A validated candidate: the row reports the candidate's receipt and
        # smoke evidence while the installed identity stays unknown.
        evidence.update(
            build_provenance_current=True,
            runtime_bundle_sha256="sha256:bundle",
            receipt_exists=True,
            receipt_valid=True,
            receipt_tested_at="2026-01-02T00:00:00Z",
            passed_smoke_cases=["smoke"],
        )
        image = {"state": "UNKNOWN", "sha256": None, "reason_code": "STAGED_CANDIDATE_PENDING"}
    else:
        image = {"state": "UNKNOWN", "sha256": None, "reason_code": "ACTIVE_IMAGE_IDENTITY_UNKNOWN"}
    status = {
        "active": "READY",
        "stale": "VALIDATION_STALE",
        "missing": "NOT_BUILT",
        "unknown": "NOT_CONFIGURED",
        "promotion": "BUILD_STALE",
    }[variant]
    return {
        "runner_family": name,
        "readiness": {
            "status": status,
            "reason_code": {
                "active": "READY",
                "stale": "RECEIPT_STALE",
                "missing": "SIF_MISSING",
                "unknown": "DOCTOR_FAILED",
                "promotion": "CANDIDATE_AWAITING_PROMOTION",
            }[variant],
            "message": (
                "A Runner image candidate is staged for promotion; activate it with the deployment-host "
                "promote-sifs step"
                if variant == "promotion"
                else "Evidence for the fleet rendering fixture."
            ),
            "next_action": "none" if variant == "active" else "promote" if variant == "promotion" else "live-test",
            "active_image": image,
            "evidence": evidence,
        },
        "capacity": {"available": True, "reason": "scheduler_available"},
        "access": {"restricted": False, "granted": True, "policy_id": None},
        "in_flight": None,
    }


VARIANTS = ("active", "stale", "missing", "unknown", "promotion")


def _fleet() -> dict:
    runners = [_row(f"family_{index:02d}", VARIANTS[index % len(VARIANTS)]) for index in range(FLEET_SIZE)]
    return {
        "runners": runners,
        "executor": {"available": True, "reason": "operator_executor_available", "unavailable_reason": None},
    }


def _mount_fleet(page: Page, fleet: dict | None = None) -> dict:
    fleet = fleet or _fleet()
    _install_app(page)
    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json=_current_user("admin")))
    page.route(f"{ORIGIN}/compute/api/auth/admin/runners", lambda route: route.fulfill(json=fleet))
    page.route(
        f"{ORIGIN}/compute/api/auth/admin/runners/*/history*",
        lambda route: route.fulfill(json={"history": []}),
    )

    def detail(route) -> None:
        family = route.request.url.rsplit("/", 1)[-1]
        row = next((item for item in fleet["runners"] if item["runner_family"] == family), fleet["runners"][0])
        # Mirror the server's refusal of a futile repair plan for a staged
        # candidate: the action is offered without a plan, so no rebuild CTA.
        actions = []
        if row["readiness"]["reason_code"] == "CANDIDATE_AWAITING_PROMOTION":
            actions = [{
                "id": "runner.repair",
                "tier": "mutate",
                "summary": "Plan and run the shortest remediation for the current invalidation",
                "available": False,
                "unavailable_reason": "no_safe_plan_for_current_state",
            }]
        route.fulfill(json={**row, "actions": actions})

    page.route(f"{ORIGIN}/compute/api/auth/admin/runners/*", detail)
    return fleet


def test_fleet_renders_active_image_identity_over_32_families(page: Page, monkeypatch) -> None:
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", ROOT / "frontend/dist")
    _mount_fleet(page)
    page.goto(f"{ORIGIN}/compute/runner_fleet")

    rows = page.locator(".admin-table tbody tr")
    expect(rows).to_have_count(FLEET_SIZE)

    active = "family_00"
    expect(
        page.get_by_role("button", name=f"{active} · Active image: Active · 00aaaaaaaaaa…")
    ).to_be_visible()
    expect(
        page.get_by_role("button", name="family_02 · Active image: Missing")
    ).to_be_visible()
    expect(
        page.get_by_role("button", name="family_03 · Active image: Unknown")
    ).to_be_visible()
    expect(
        page.get_by_role("button", name="family_04 · Active image: Unknown")
    ).to_be_visible()

    # The dialog is reachable and operable from the keyboard, and closing it
    # restores focus to the control that opened it. (The existing site-wide
    # Fleet test covers the Escape close request on the same dialog.)
    opener = page.get_by_role("button", name=f"{active} · Active image: Active · 00aaaaaaaaaa…")
    opener.focus()
    page.keyboard.press("Enter")
    dialog = page.locator(".fleet-evidence-dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("Active · sha256:")
    expect(dialog).to_contain_text("Ready to accept new submissions.")
    close = dialog.get_by_role("button", name="Close", exact=True)
    close.focus()
    page.keyboard.press("Enter")
    expect(dialog).not_to_be_visible()
    expect(opener).to_be_focused()

    # The responsive table scrolls inside its own container; the page never
    # exceeds the phone viewport.
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 1080})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
    assert page.evaluate("window.__cspViolations") == []


def test_fleet_reports_the_candidate_receipt_without_an_active_claim(page: Page, monkeypatch) -> None:
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", ROOT / "frontend/dist")
    _mount_fleet(
        page,
        {
            "runners": [_row("family_00", "promotion")],
            "executor": {"available": True, "reason": "operator_executor_available", "unavailable_reason": None},
        },
    )
    page.goto(f"{ORIGIN}/compute/runner_fleet")

    row = page.locator(".admin-table tbody tr").first
    expect(row).to_contain_text("Recommended: Activate")
    expect(page.get_by_role("button", name="family_00 · Build: Built")).to_be_visible()
    expect(page.get_by_role("button", name="family_00 · Live test: Validated")).to_be_visible()
    page.get_by_role("button", name="family_00 · Active image: Unknown").click()

    dialog = page.locator(".fleet-evidence-dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text(
        "A Runner image candidate is staged for promotion; activate it with the deployment-host promote-sifs step"
    )

    def fact(label: str):
        return dialog.locator(".fleet-fact", has_text=label).locator("dd")

    expect(fact("Recommended next step")).to_have_text("Activate")
    expect(fact("Active image")).to_have_text("Unknown — a staged candidate is awaiting activation")
    expect(fact("Build provenance")).to_have_text("Current")
    expect(fact("Runtime bundle")).to_have_text("Pinned")
    expect(fact("Live receipt")).to_have_text("Valid")
    expect(fact("Last validated")).not_to_have_text("Never")
    expect(fact("Smoke coverage")).to_have_text("1 of 1 cases")

    # The server refuses a futile build→live_test repair plan for this state, so
    # the action is listed as unavailable and offers no run control.
    expect(dialog).to_contain_text("Not available for the current state")
    expect(dialog.get_by_role("button", name="Review and run")).to_have_count(0)


def test_empty_fleet_says_none_is_enabled_rather_than_implying_readiness(page: Page, monkeypatch) -> None:
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", ROOT / "frontend/dist")
    _mount_fleet(
        page,
        {
            "runners": [],
            "executor": {"available": True, "reason": "operator_executor_available", "unavailable_reason": None},
        },
    )
    page.goto(f"{ORIGIN}/compute/runner_fleet")

    expect(page.locator(".admin-table tbody tr")).to_have_count(1)
    expect(page.get_by_text("No Runner family is enabled on this deployment.").first).to_be_visible()
    expect(page.locator(".fleet-summary")).to_contain_text("No Runner family is enabled")
