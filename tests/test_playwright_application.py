# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the frontend-owned ordinary compute workflow."""

from __future__ import annotations

import json
from pathlib import Path
import re

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import result_dist
from conftest import _load_pssm_module, _test_client_auth

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
TASK_ID = "0123456789abcdef0123456789abcdef"


def _catalog() -> dict:
    access = {"restricted": False, "granted": True, "request_status": None}
    return {
        "version": 3,
        "categories": [{"name": "evolution", "label": "Evolution"}],
        "task_types": [{
            "name": "sequence_demo", "display_name": "Sequence demo", "category": "evolution",
            "summary": "Summarize one protein sequence.", "access": access,
            "detail_url": "/compute/api/types/sequence_demo",
            "parameters_url": "/compute/api/task-parameters/sequence_demo",
        }],
    }


def _detail() -> dict:
    return {
        **_catalog()["task_types"][0],
        "use_when": "Use this for a small sequence summary.",
        "input_summary": "One protein sequence.", "output_summary": "A text summary.",
        "considerations": [], "runtime_family": "example", "gpus": False, "requires_network": False,
        "inputs": [{
            "id": "sequence", "title": "Protein sequence", "type": "protein_sequence",
            "formats": ["fasta"], "extensions": [".fasta", ".fa"], "accept": ".fasta,.fa",
            "cardinality": {"min": 1, "max": 1}, "description": "One FASTA record.",
        }],
        "citations": [], "workflow": [], "max_request_bytes": 1048576,
        "input_workspace": {
            "version": 3, "plugins": [], "steps": [
                {"id": "input", "title": "Provide input", "description": "Choose one source.", "capabilities": [
                    {"plugin": "files", "id": "source_files", "title": "Files", "description": "Upload FASTA.", "options": {}},
                    {"plugin": "sequence", "id": "sequence_editor", "title": "Sequence", "description": "Paste FASTA.", "options": {"role": "sequence"}},
                ]},
                {"id": "settings", "title": "Settings", "description": "Configure the run.", "capabilities": [
                    {"plugin": "parameters", "id": "parameters", "title": "Parameters", "description": "Method controls.", "options": {}},
                ]},
                {"id": "review", "title": "Review", "description": "Check the snapshot.", "capabilities": [
                    {"plugin": "review", "id": "review", "title": "Review", "description": "Submission summary.", "options": {"show_paths": True}},
                ]},
            ],
        },
    }


def _task_summary() -> dict:
    return {
        "task_id": TASK_ID, "task_type": "sequence_demo", "display_name": "sample.fasta",
        "status": "finished", "terminal": True, "submitted_at": "2026-09-29T00:00:00Z",
        "finished_at": "2026-09-29T00:00:03Z", "walltime_seconds": 3, "owner": None,
        "progress": None, "outcome": "SUCCESS", "error": None, "input_preview": None,
        "result": {
            "available": True, "page_url": f"/compute/results/{TASK_ID}",
            "manifest_url": f"/compute/api/results/{TASK_ID}", "archive_ready": False,
            "archive_request_allowed": True, "archive_request_url": f"/compute/api/results/{TASK_ID}/archive",
            "download_url": None,
        },
        "actions": {
            "cancel": {"allowed": False, "url": f"/compute/api/cancel/{TASK_ID}"},
            "delete": {"allowed": True, "url": f"/compute/api/delete/{TASK_ID}"},
        },
    }


def _current_user(role: str = "user") -> dict:
    return {
        "username": "admin" if role == "admin" else "tester",
        "email": f"{role}@example.org",
        "email_verified": True,
        "role": role,
        "full_name": "Admin Scientist" if role == "admin" else "Test Scientist",
        "affiliation": "Example Institute",
        "position": "research_assistant",
        "pi_name": "Dr Example",
    }


def _gpu_credit(user_id: int = 2, adjustment: int = 600) -> dict:
    return {
        "user_id": user_id,
        "period": "2026-09",
        "credit_unit_gpu_seconds": 60,
        "monthly_grant_gpu_seconds": 7200,
        "usage_gpu_seconds": 1800,
        "adjustment_gpu_seconds": adjustment,
        "remaining_gpu_seconds": 6000 + adjustment,
        "monthly_grant_credits": 120,
        "usage_credits": 30,
        "adjustment_credits": adjustment / 60,
        "remaining_credits": 100 + adjustment / 60,
        "allow_gpu_use": True,
        "history": [{
            "id": 1, "period": "2026-09", "kind": "monthly_grant", "gpu_seconds": 7200,
            "reason": "Monthly allocation", "created_at": 1790636400,
        }],
    }


def _admin_user() -> dict:
    return {
        "id": 2,
        **_current_user(),
        "allow_gpu_use": True,
        "registration_status": "approved",
        "user_status": "active",
        "created_at": 1790636400,
        "approved_by": 1,
        "approved_at": 1790636500,
        "registration_ip": "192.0.2.10",
        "registration_country": "TEST",
        "gpu_credit": _gpu_credit(),
    }


def _infrastructure() -> dict:
    return {
        "status": "READY",
        "checked_at": "2026-09-29T00:00:00Z",
        "stale": False,
        "summary": {"compute": {"label": "Compute", "status": "READY", "stale": False, "capacity": "AVAILABLE"}},
        "components": [{
            "component": "celery_worker", "status": "READY", "reason_code": "worker_ready",
            "message": "Worker is accepting tasks.", "checked_at": "2026-09-29T00:00:00Z",
            "duration_ms": 4, "failure_count": 0, "next_action": "None", "capacity": "AVAILABLE", "stale": False,
        }],
    }


def _metrics(window: str = "30d") -> dict:
    return {
        "window": window,
        "days": 30,
        "period": "2026-09-29",
        "tasks_submitted": 5,
        "tasks_completed": 4,
        "tasks_failed": 1,
        "success_rate": 0.8,
        "cpu_tasks": 3,
        "gpu_tasks": 2,
        "gpu_minutes": 30,
        "total_runtime_seconds": 480,
        "median_runtime_seconds": 75,
        "distribution": [{"task_type": "sequence_demo", "label": "Sequence demo", "gpu": False, "tasks": 5}],
        "activity": [{"period": "2026-09-28", "count": 2}, {"period": "2026-09-29", "count": 3}],
    }


def _install_app(page: Page) -> list[str]:
    dist = result_dist()
    entry = json.loads((dist / ".vite" / "manifest.json").read_text(encoding="utf-8"))["index.html"]
    styles = "".join(f'<link rel="stylesheet" href="/static/app/{name}">' for name in entry.get("css", []))
    html = (f'<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="referrer" content="no-referrer">'
            f'{styles}<script type="module" src="/static/app/{entry["file"]}"></script></head><body><div id="app"></div></body></html>')
    requested: list[str] = []
    page.add_init_script("window.__cspViolations = []; document.addEventListener('securitypolicyviolation', event => window.__cspViolations.push(event.violatedDirective + ':' + event.blockedURI));")
    page.on("request", lambda request: requested.append(request.url))
    html_headers = {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:",
        "Referrer-Policy": "no-referrer",
    }
    for pattern in (
        "/", "/api-docs", "/runners", "/runners/*", "/compute/login**", "/compute/register",
        "/compute/reset_password**", "/compute/user_verify**", "/compute/terms", "/compute/profile**",
        "/compute/user_control", "/compute/configuration", "/compute/logs", "/compute/create_task**",
        "/compute/dashboard", "/compute/results/*",
    ):
        page.route(f"{ORIGIN}{pattern}", lambda route: route.fulfill(headers=html_headers, body=html))

    def static(route):
        relative = route.request.url.split("/static/app/", 1)[1].split("?", 1)[0]
        route.fulfill(path=dist / relative)

    page.route(f"{ORIGIN}/static/app/**", static)
    current_user = _current_user()

    def current_user_handler(route) -> None:
        if route.request.method == "PUT":
            payload = route.request.post_data_json
            current_user.update({key: value for key, value in payload.items() if key in {
                "full_name", "affiliation", "position", "pi_name",
            }})
            route.fulfill(json={"message": "Profile updated"})
        else:
            route.fulfill(json=current_user)

    page.route(f"{ORIGIN}/compute/api/auth/me", current_user_handler)
    page.route(f"{ORIGIN}/compute/api/auth/token", lambda route: route.fulfill(json={"token": "ephemeral"}))
    page.route(f"{ORIGIN}/compute/api/auth/login", lambda route: route.fulfill(json={"token": "signed-in", "username": "tester"}))
    page.route(f"{ORIGIN}/compute/api/auth/forgot-password", lambda route: route.fulfill(json={"message": "If the account exists, a reset link has been sent."}))
    page.route(f"{ORIGIN}/compute/api/auth/registration", lambda route: route.fulfill(json={"enabled": True, "email_available": True}))
    page.route(f"{ORIGIN}/compute/api/auth/captcha", lambda route: route.fulfill(json={"question": "What is 4 + 5?", "token": "captcha-token"}))
    page.route(f"{ORIGIN}/compute/api/auth/register", lambda route: route.fulfill(status=201, json={
        "message": "Check your email, then wait for administrator approval.", "username": "newresearcher", "email_sent": True,
    }))
    page.route(f"{ORIGIN}/compute/api/auth/resend-verification", lambda route: route.fulfill(json={"message": "Verification email sent."}))
    page.route(f"{ORIGIN}/compute/api/auth/reset-password", lambda route: route.fulfill(json={"message": "Password updated."}))
    page.route(f"{ORIGIN}/compute/api/auth/verify-email", lambda route: route.fulfill(json={
        "message": "Your email address is verified.", "email": "tester@example.org", "registration_pending": True,
    }))
    page.route(f"{ORIGIN}/compute/api/legal/terms", lambda route: route.fulfill(json={
        "document": "terms", "version": "sha256:test", "markdown": (
            "# Terms of Service\n\n"
            + "\n\n".join(f"## Policy {index}\n\nPolicy detail {index}." for index in range(1, 16))
            + "\n\n## Restricted Runner access {#restricted-runner-access}\n\nAccess decisions are server-owned."
        ),
    }))
    page.route(f"{ORIGIN}/openapi.json", lambda route: route.fulfill(json={
        "openapi": "3.1.0", "info": {"title": "REvoCompute API", "version": "3"},
        "paths": {"/compute/api/types": {"get": {"summary": "List Runner types", "responses": {"200": {"description": "Catalog"}}}}},
    }))
    page.route(f"{ORIGIN}/compute/api/infrastructure", lambda route: route.fulfill(json=_infrastructure()))
    page.route(f"{ORIGIN}/compute/api/types", lambda route: route.fulfill(json=_catalog()))
    page.route(f"{ORIGIN}/compute/api/types/sequence_demo", lambda route: route.fulfill(json=_detail()))
    page.route(f"{ORIGIN}/compute/api/task-parameters/sequence_demo", lambda route: route.fulfill(json={
        "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
        "additionalProperties": False, "properties": {"iterations": {"type": "integer", "default": 2, "minimum": 1, "maximum": 4}},
    }))
    page.route(f"{ORIGIN}/compute/api/preflight/sequence_demo", lambda route: route.fulfill(json={
        "valid": True, "security": {"status": "passed"}, "contract": {"status": "passed"},
        "admission": {"allowed": True, "runner_ready": True, "infrastructure_ready": True, "infrastructure_status": "READY"},
        "normalized_params": {"iterations": 2}, "inputs": [{"role": "sequence", "format": "fasta", "path": "sample.fasta"}],
        "warnings": [], "errors": [],
    }))
    page.route(f"{ORIGIN}/compute/api/post", lambda route: route.fulfill(status=202, json={
        "task_id": TASK_ID, "task_type": "sequence_demo", "display_name": "sample.fasta", "status": "queued",
        "terminal": False, "status_url": f"/compute/api/running/{TASK_ID}", "results_url": f"/compute/api/results/{TASK_ID}", "result_available": False,
    }))
    page.route(f"{ORIGIN}/compute/api/tasks", lambda route: route.fulfill(json={"tasks": [_task_summary()]}))
    page.route(f"{ORIGIN}/compute/api/running/{TASK_ID}", lambda route: route.fulfill(json={
        "task_id": TASK_ID, "task_type": "sequence_demo", "display_name": "sample.fasta", "status": "finished",
        "terminal": True, "status_url": f"/compute/api/running/{TASK_ID}", "results_url": f"/compute/api/results/{TASK_ID}", "result_available": True,
    }))
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}", lambda route: route.fulfill(json={
        "schema_version": 3, "task_id": TASK_ID, "task_type": "sequence_demo", "created_at": "2026-09-29T00:00:03Z",
        "status": "finished", "terminal": True, "error": None, "run": {"method": {"name": "Sequence demo", "output_summary": "A text summary."}},
        "output_check": {"state": "passed", "checks": [], "problems": []}, "limitations": [], "views": [], "artifacts": [],
        "result": {"files": {}}, "storyboard": None, "outcome": "SUCCESS", "total_size": 0,
        "archive": {"ready": False, "request_url": f"/compute/api/results/{TASK_ID}/archive"},
    }))

    api_key = {"active": False}

    def api_key_handler(route) -> None:
        method = route.request.method
        if method == "GET":
            route.fulfill(json={"has_api_key": api_key["active"]})
        elif method == "POST":
            api_key["active"] = True
            route.fulfill(status=201, json={"api_key": "rvk_test_secret_once", "message": "API key generated."})
        else:
            api_key["active"] = False
            route.fulfill(json={"message": "API key revoked."})

    page.route(f"{ORIGIN}/compute/api/auth/me/api-key", api_key_handler)
    page.route(f"{ORIGIN}/compute/api/access", lambda route: route.fulfill(json={"policies": [{
        "policy_id": "academic-only", "label": "Academic models", "description": "Academic eligibility is required.",
        "granted": False, "requestable": True, "request_status": None,
        "notice": {"title": "Academic use only", "summary": "The upstream licence requires verified academic eligibility."},
        "license": {"name": "Upstream terms", "url": "https://example.org/terms"},
    }]}))
    page.route(f"{ORIGIN}/compute/api/access/requests", lambda route: route.fulfill(status=201, json={"status": "pending"}))
    page.route(f"{ORIGIN}/compute/api/gpu-credit", lambda route: route.fulfill(json=_gpu_credit()))
    page.route(f"{ORIGIN}/compute/api/user-metrics?*", lambda route: route.fulfill(json=_metrics()))

    users = [_admin_user()]

    def admin_users(route) -> None:
        if route.request.method == "POST":
            payload = route.request.post_data_json
            users.append({**_admin_user(), **payload, "id": 3, "gpu_credit": _gpu_credit(3, 0)})
            route.fulfill(status=201, json={"message": "User created.", "username": payload["username"]})
        else:
            route.fulfill(json={"users": users})

    def admin_user(route) -> None:
        route.fulfill(json={"message": "User updated."})

    def admin_credit(route) -> None:
        if route.request.method == "POST" and route.request.url.endswith("/adjustments"):
            payload = route.request.post_data_json
            route.fulfill(status=201, json={"entry_id": 2, "gpu_credit": _gpu_credit(2, payload["gpu_seconds"])})
        elif route.request.method == "PUT":
            route.fulfill(json={"entry_id": 2, "gpu_credit": _gpu_credit()})
        else:
            route.fulfill(json=_gpu_credit())

    page.route(f"{ORIGIN}/compute/api/auth/admin/users", admin_users)
    page.route(f"{ORIGIN}/compute/api/auth/admin/users/*/gpu-credit/adjustments", admin_credit)
    page.route(f"{ORIGIN}/compute/api/auth/admin/users/*/gpu-credit/allowance", admin_credit)
    page.route(f"{ORIGIN}/compute/api/auth/admin/users/*/gpu-credit", admin_credit)
    page.route(f"{ORIGIN}/compute/api/auth/admin/users/*", admin_user)
    pending = {"visible": True}

    def access_requests(route) -> None:
        route.fulfill(json={"requests": ([{
            "id": 7, "user_id": 2, "username": "tester", "full_name": "Test Scientist",
            "email": "user@example.org", "affiliation": "Example Institute", "entitlement": "academic-models",
            "reason": "Non-commercial protein design.", "status": "pending", "created_at": 1790636400,
        }] if pending["visible"] else [])})

    def access_decision(route) -> None:
        pending["visible"] = False
        route.fulfill(json={"status": "approved"})

    page.route(f"{ORIGIN}/compute/api/auth/admin/access/requests?*", access_requests)
    page.route(f"{ORIGIN}/compute/api/auth/admin/access/requests/*/decision", access_decision)
    page.route(f"{ORIGIN}/compute/api/auth/admin/access/policies", lambda route: route.fulfill(json={"policies": [{
        "policy_id": "academic-only", "label": "Academic models", "description": "Eligibility required.",
        "requires": ["academic-models"], "authorized_users": 1, "pending_requests": 1, "suspended_users": 0,
    }]}))
    page.route(f"{ORIGIN}/compute/api/auth/admin/access/events?*", lambda route: route.fulfill(json={"events": []}))
    page.route(f"{ORIGIN}/compute/api/auth/admin/gpu-credit/reconciliation", lambda route: route.fulfill(json={"result": None, "allocations": []}))
    config = {
        "task_types": [{
            "tool": "sequence_demo", "display_name": "Sequence demo", "enabled": True, "requires_gpu": False,
            "runtime_family": "example", "is_workflow_stage": False, "category": "evolution", "inputs": [],
            "parameter_count": 1, "stage_count": 0, "effective_resources": {"cpus": 2, "memory": "4G"},
        }],
        "resources": {"cpus": 2, "memory": "4G", "max_runtime_seconds": 3600, "slurm_partition": "cpu"},
        "ignored_resource_keys": [], "slurm": {"enabled": True, "allowed_queues": ["cpu", "gpu"]},
    }
    page.route(f"{ORIGIN}/compute/api/auth/admin/config", lambda route: route.fulfill(
        json={"message": "Configuration updated."} if route.request.method == "PUT" else config,
    ))
    page.route(f"{ORIGIN}/compute/api/auth/admin/infrastructure/refresh", lambda route: route.fulfill(json=_infrastructure()))
    page.route(f"{ORIGIN}/compute/api/auth/admin/logs/*", lambda route: route.fulfill(content_type="text/plain", body="worker ready\ntask accepted\n"))
    page.route(f"{ORIGIN}/compute/api/auth/admin/logs/archives", lambda route: route.fulfill(json={"logs": [{
        "id": "server", "filename": "server.log", "archives": [{"filename": "server.log.1", "size": 2048, "modified_at": 1790636400}],
    }]}))
    return requested


def test_runner_to_result_workflow_is_frontend_owned_and_refreshable(page: Page) -> None:
    requests = _install_app(page)
    page.goto(f"{ORIGIN}/runners")
    expect(page.get_by_role("heading", name="Runner catalog")).to_be_visible()
    page.get_by_role("link", name="View method").click()
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    page.get_by_role("link", name="Create task").first.click()
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    page.locator("textarea[aria-label='Protein sequence']").fill(">sample\nACDEFG")
    page.get_by_role("button", name="Review", exact=True).click()
    expect(page.get_by_role("button", name="Run", exact=True)).to_be_enabled()
    page.get_by_role("button", name="Run", exact=True).click()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    page.get_by_role("link", name="Results").click()
    expect(page.get_by_role("heading", name="sample.fasta")).to_be_visible()
    page.reload()
    expect(page.get_by_role("heading", name="sample.fasta")).to_be_visible()
    assert any("/compute/api/preflight/sequence_demo" in url for url in requests)
    assert any("/compute/api/post" in url for url in requests)
    assert any("/compute/api/tasks" in url for url in requests)


@pytest.mark.parametrize("path", ["/runners", "/runners/sequence_demo", "/compute/create_task", "/compute/dashboard"])
def test_application_routes_refresh_without_overflow(page: Page, path: str) -> None:
    _install_app(page)
    page.set_viewport_size({"width": 320, "height": 760})
    page.goto(f"{ORIGIN}{path}")
    page.reload()
    expect(page.locator(".app-header")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_unknown_runner_and_expired_session_have_frontend_states(page: Page) -> None:
    _install_app(page)
    page.route(f"{ORIGIN}/compute/api/types/missing", lambda route: route.fulfill(status=404, json={"error": "Unknown task type"}))
    page.goto(f"{ORIGIN}/runners/missing")
    expect(page.get_by_role("heading", name="Runner unavailable")).to_be_visible()

    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(status=401, json={"error": "Authentication required"}))
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page).to_have_url(f"{ORIGIN}/compute/login?return_to=%2Fcompute%2Fdashboard")
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()


def test_restricted_runner_access_request_updates_without_navigation(page: Page) -> None:
    _install_app(page)
    detail = _detail()
    detail["access"] = {
        "restricted": True,
        "granted": False,
        "requestable": True,
        "request_status": None,
        "policy_id": "academic-only",
        "description": "Academic research approval is required.",
    }
    requested: list[str] = []
    page.route(f"{ORIGIN}/compute/api/types/sequence_demo", lambda route: route.fulfill(json=detail))
    page.route(
        f"{ORIGIN}/compute/api/access/requests",
        lambda route: (requested.append(route.request.post_data or ""), route.fulfill(status=201, json={"status": "pending"})),
    )

    page.goto(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")
    page.get_by_role("button", name="Request access", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog).not_to_be_visible()
    page.get_by_role("button", name="Request access", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Research use and affiliation").fill("Non-commercial structural biology research")
    dialog.get_by_role("button", name="Request access", exact=True).click()
    expect(page.get_by_role("heading", name="Access requested")).to_be_visible()
    assert requested and "academic-only" in requested[0]


def test_admin_dashboard_batch_action_uses_authorized_api(page: Page) -> None:
    _install_app(page)
    page.route(
        f"{ORIGIN}/compute/api/auth/me",
        lambda route: route.fulfill(json=_current_user("admin")),
    )
    admin_task = _task_summary()
    admin_task["owner"] = "tester"
    page.route(f"{ORIGIN}/compute/api/tasks", lambda route: route.fulfill(json={"tasks": [admin_task]}))
    deleted: list[str] = []
    page.route(
        f"{ORIGIN}/compute/api/delete",
        lambda route: (deleted.append(route.request.post_data or ""), route.fulfill(json={"deleted": [TASK_ID]})),
    )
    page.on("dialog", lambda dialog: dialog.accept())

    page.goto(f"{ORIGIN}/compute/dashboard")
    page.get_by_label("Administration").click()
    expect(page.get_by_role("link", name="Server logs")).to_have_attribute("href", "/compute/logs")
    expect(page.get_by_role("button", name="Delete selected (0)")).to_be_hidden()
    page.get_by_role("checkbox", name="Select", exact=True).check()
    page.get_by_role("button", name="Delete selected (1)").click()
    expect(page.get_by_text("Selected tasks deleted.")).to_be_visible()
    assert deleted and TASK_ID in deleted[0]


def test_mid_session_expiry_redirects_after_mutation(page: Page) -> None:
    _install_app(page)
    page.route(
        f"{ORIGIN}/compute/api/delete/{TASK_ID}",
        lambda route: route.fulfill(status=401, json={"error": "Authentication required"}),
    )
    page.on("dialog", lambda dialog: dialog.accept())

    page.goto(f"{ORIGIN}/compute/dashboard")
    page.get_by_role("button", name="Delete", exact=True).click()

    expect(page).to_have_url(f"{ORIGIN}/compute/login?return_to=%2Fcompute%2Fdashboard")
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()


def test_dark_theme_and_mobile_navigation_clearance(page: Page) -> None:
    _install_app(page)
    page.set_viewport_size({"width": 320, "height": 760})
    page.goto(f"{ORIGIN}/compute/create_task")
    page.get_by_role("button", name="Theme: Auto").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    create_colors = page.locator(".create-task").evaluate(
        "node => { const style = getComputedStyle(node); const control = getComputedStyle(node.querySelector('.ct-method')); "
        "return [style.color, control.backgroundColor, parseFloat(style.paddingBottom), "
        "document.querySelector('.app-nav').getBoundingClientRect().height]; }"
    )
    assert create_colors[0] != create_colors[1]
    assert create_colors[2] >= create_colors[3]

    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    result_colors = page.locator(".result-app").evaluate(
        "node => [getComputedStyle(node).color, getComputedStyle(document.body).backgroundColor]"
    )
    assert result_colors[0] != result_colors[1]


def test_malformed_result_id_stays_in_frontend_not_found_state(page: Page) -> None:
    _install_app(page)
    page.goto(f"{ORIGIN}/compute/results/not-a-task")
    expect(page.get_by_role("heading", name="Page not found")).to_be_visible()


@pytest.mark.parametrize("width", [320, 390, 768, 1280])
def test_public_home_is_immediate_responsive_and_refreshable(page: Page, width: int) -> None:
    requests = _install_app(page)
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(f"{ORIGIN}/")

    expect(page.get_by_role("heading", name="REvoDesign", exact=True)).to_be_visible()
    expect(page.get_by_text("Evidence-guided design")).to_be_visible()
    page.reload()
    expect(page.get_by_role("heading", name="REvoDesign", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert any(url.endswith("/static/app/logo.svg") for url in requests)
    assert not any(url.endswith("/compute/logo.svg") for url in requests)

    if width == 390:
        page.get_by_role("button", name="Theme: Auto").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.reload()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")


@pytest.mark.parametrize(
    ("path", "heading"),
    [("/compute/terms", "Terms of Service"), ("/api-docs", "REvoCompute API")],
)
def test_public_reference_routes_render_from_direct_refresh(page: Page, path: str, heading: str) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _install_app(page)
    page.goto(f"{ORIGIN}{path}")
    expect(page.get_by_role("heading", name=heading, exact=True).first).to_be_visible()
    page.reload()
    expect(page.get_by_role("heading", name=heading, exact=True).first).to_be_visible()
    if path == "/compute/terms":
        expect(page.locator(".legal-document")).to_have_attribute("data-version", "sha256:test")
        expect(page.get_by_role("heading", name="Restricted Runner access")).to_be_visible()
    else:
        expect(page.locator(".swagger-ui")).to_be_visible()
        expect(page.get_by_text("List Runner types", exact=True)).to_be_visible()
        page.get_by_role("button", name="Theme: Auto").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.locator(".opblock-summary").first.click()
        expect(page.locator(".opblock-body").first).to_be_visible()
    assert page.evaluate("window.__cspViolations") == []
    assert errors == []


def test_terms_fragment_scrolls_after_async_document_render(page: Page) -> None:
    _install_app(page)
    page.goto(f"{ORIGIN}/compute/terms#restricted-runner-access")

    target = page.locator("#restricted-runner-access")
    expect(target).to_be_visible()
    expect(target).to_be_in_viewport()


def test_login_forgot_password_and_return_target_validation(page: Page) -> None:
    _install_app(page)
    posted: list[tuple[str, dict]] = []
    page.on("request", lambda request: posted.append((request.url, request.post_data_json)) if request.post_data else None)
    page.goto(f"{ORIGIN}/compute/login?return_to=https%3A%2F%2Fevil.example%2Fsteal")

    page.get_by_role("button", name="Forgot your password?").click()
    page.get_by_label("Email", exact=True).fill("tester@example.org")
    page.get_by_role("button", name="Send reset link").click()
    expect(page.get_by_text("If the account exists, a reset link has been sent.")).to_be_visible()

    page.get_by_label("Username or email").fill("tester")
    page.get_by_label("Password", exact=True).fill("correct horse battery staple")
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/compute/dashboard")
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    assert any(url.endswith("/forgot-password") and body == {"email": "tester@example.org"} for url, body in posted)
    assert any(url.endswith("/login") and body["username"] == "tester" for url, body in posted)


def test_registration_reset_and_verification_post_canonical_contracts(page: Page) -> None:
    _install_app(page)
    posted: list[tuple[str, dict]] = []
    asset_referers: list[str] = []
    page.on("request", lambda request: posted.append((request.url, request.post_data_json)) if request.post_data else None)
    page.on("request", lambda request: asset_referers.append(request.headers.get("referer", "")) if "/static/app/" in request.url else None)
    page.goto(f"{ORIGIN}/compute/register")

    expect(page.get_by_text("What is 4 + 5?")).to_be_visible()
    page.get_by_label("Username", exact=True).fill("newresearcher")
    page.get_by_label("Email", exact=True).fill("new@example.org")
    page.get_by_label("Full name").fill("New Researcher")
    page.get_by_label("Affiliation").fill("Example Institute")
    page.get_by_label("Position").select_option("phd_student")
    page.get_by_label("PI or supervisor").fill("Dr Example")
    page.locator('input[name="password"]').fill("long-enough-password")
    page.get_by_role("checkbox").check()
    page.get_by_label("CAPTCHA answer").fill("9")
    page.get_by_role("button", name="Create account").click()
    expect(page.get_by_text("Check your email, then wait for administrator approval.")).to_be_visible()
    expect(page.get_by_role("button", name="Resend verification email")).to_be_visible()

    page.goto(f"{ORIGIN}/compute/reset_password?token=reset-token")
    expect(page).to_have_url(f"{ORIGIN}/compute/reset_password")
    page.get_by_label("New password").fill("another-long-password")
    page.get_by_role("button", name="Set password").click()
    expect(page.get_by_text("Password updated.")).to_be_visible()

    page.goto(f"{ORIGIN}/compute/user_verify?token=verify-token")
    expect(page).to_have_url(f"{ORIGIN}/compute/user_verify")
    expect(page.get_by_role("heading", name="Email verified")).to_be_visible()
    expect(page.get_by_text("An administrator must approve the account before you can sign in.")).to_be_visible()

    registration = next(body for url, body in posted if url.endswith("/register"))
    assert registration["captcha_token"] == "captcha-token"
    assert registration["terms_agreed"] is True
    assert next(body for url, body in posted if url.endswith("/reset-password")) == {
        "token": "reset-token", "password": "another-long-password",
    }
    assert next(body for url, body in posted if url.endswith("/verify-email")) == {"token": "verify-token"}
    assert all("reset-token" not in referer and "verify-token" not in referer for referer in asset_referers)


def test_profile_server_state_api_key_access_credits_and_metrics(page: Page) -> None:
    _install_app(page)
    posted: list[tuple[str, str, dict | None]] = []
    page.on("request", lambda request: posted.append(
        (request.url, request.method, request.post_data_json if request.post_data else None),
    ))
    page.goto(f"{ORIGIN}/compute/profile")

    expect(page.get_by_role("heading", name="Profile")).to_be_visible()
    expect(page.get_by_label("Full name")).to_have_value("Test Scientist")
    expect(page.get_by_label("Affiliation", exact=True)).to_have_value("Example Institute")
    page.get_by_label("Full name").fill("Updated Scientist")
    page.get_by_label("Affiliation", exact=True).fill("New Institute")
    page.get_by_label("Position").select_option("associate_professor")
    page.get_by_label("PI or supervisor").fill("Professor Example")
    page.get_by_role("button", name="Save profile").click()
    expect(page.get_by_role("alert").filter(has_text="Profile updated.")).to_be_visible()
    page.reload()
    expect(page.get_by_label("Full name")).to_have_value("Updated Scientist")
    expect(page.get_by_label("Affiliation", exact=True)).to_have_value("New Institute")
    account_tab = page.get_by_role("tab", name="Account")
    account_tab.focus(); account_tab.press("ArrowRight")
    expect(page.get_by_role("tab", name="Security")).to_have_attribute("aria-selected", "true")

    page.get_by_role("tab", name="API key").click()
    page.get_by_role("button", name="Generate API key").click()
    expect(page.locator("[data-api-key-value]")).to_have_value("rvk_test_secret_once")
    page.reload()
    expect(page.get_by_text("An active API key is configured.")).to_be_visible()
    page.get_by_role("button", name="Revoke API key").click()
    page.get_by_role("dialog").get_by_role("button", name="Revoke API key").click()
    expect(page.get_by_role("alert").filter(has_text="API key revoked.")).to_be_visible()

    page.get_by_role("tab", name="Runner access").click()
    page.get_by_text("Policy details").click()
    expect(page.get_by_text("Academic use only")).to_be_visible()
    expect(page.get_by_text("The upstream licence requires verified academic eligibility.")).to_be_visible()
    page.get_by_label("Research use and affiliation").fill("Non-commercial work at Example Institute")
    page.get_by_role("button", name="Request access").click()
    expect(page.get_by_text("Access request submitted.")).to_be_visible()

    page.get_by_role("tab", name="GPU credits").click()
    expect(page.get_by_text("September 2026")).to_be_visible()
    expect(page.get_by_text("GPU access granted")).to_be_visible()
    page.get_by_role("tab", name="Metrics").click()
    expect(page.get_by_text("Tasks submitted")).to_be_visible()
    expect(page.get_by_text("80%")).to_be_visible()
    page.get_by_role("button", name="7 days").click()
    expect(page.get_by_text("Sequence demo", exact=True)).to_be_visible()

    assert any(url.endswith("/me/api-key") and method == "POST" for url, method, _ in posted)
    assert any(url.endswith("/me/api-key") and method == "DELETE" for url, method, _ in posted)
    profile_update = next(body for url, method, body in posted if url.endswith("/me") and method == "PUT")
    assert profile_update == {
        "full_name": "Updated Scientist", "affiliation": "New Institute",
        "position": "associate_professor", "pi_name": "Professor Example",
    }
    access = next(body for url, method, body in posted if url.endswith("/access/requests") and method == "POST")
    assert access == {"policy_id": "academic-only", "reason": "Non-commercial work at Example Institute"}
    assert any("window=7d" in url for url, _, _ in posted)


def test_profile_wrong_password_stays_inline_and_guest_profile_is_read_only(page: Page) -> None:
    _install_app(page)

    def reject_password(route) -> None:
        if route.request.method == "PUT":
            route.fulfill(status=400, json={"error": "Current password is incorrect"})
        else:
            route.fulfill(json=_current_user())

    page.route(f"{ORIGIN}/compute/api/auth/me", reject_password)
    page.goto(f"{ORIGIN}/compute/profile#security")
    page.get_by_label("Current password").fill("mistyped")
    page.get_by_label("New password", exact=True).fill("replacement-password")
    page.get_by_label("Confirm new password").fill("replacement-password")
    page.get_by_role("button", name="Update password").click()
    expect(page.get_by_role("alert").filter(has_text="Current password is incorrect")).to_be_visible()
    expect(page).to_have_url(f"{ORIGIN}/compute/profile#security")

    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json=_current_user("guest")))
    page.goto(f"{ORIGIN}/compute/profile")
    expect(page.get_by_text("Guest account", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Save profile")).to_have_count(0)


@pytest.mark.parametrize("width", [320, 390, 768, 1280])
def test_auth_profile_and_admin_views_are_responsive_under_production_csp(page: Page, width: int) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _install_app(page)
    page.set_viewport_size({"width": width, "height": 800})

    page.goto(f"{ORIGIN}/compute/login")
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")

    page.goto(f"{ORIGIN}/compute/profile")
    expect(page.get_by_role("heading", name="Profile")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")

    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json=_current_user("admin")))
    page.goto(f"{ORIGIN}/compute/user_control")
    expect(page.get_by_role("heading", name="User control")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert page.evaluate("window.__cspViolations") == []
    assert errors == []


def test_admin_user_access_and_credit_mutations(page: Page) -> None:
    _install_app(page)
    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json=_current_user("admin")))
    posted: list[tuple[str, str, dict | None]] = []
    page.on("request", lambda request: posted.append(
        (request.url, request.method, request.post_data_json if request.post_data else None),
    ))
    page.goto(f"{ORIGIN}/compute/user_control")

    expect(page.get_by_role("heading", name="User control")).to_be_visible()
    page.get_by_role("button", name="Create user").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Username").fill("created-user")
    dialog.get_by_label("Email").fill("created@example.org")
    dialog.get_by_label("Password").fill("created-password")
    dialog.get_by_label("Full name").fill("Created Researcher")
    dialog.get_by_role("button", name="Create user").click()
    expect(page.get_by_text("Created Researcher", exact=True)).to_be_visible()

    page.get_by_role("tab", name="Runner access").click()
    page.get_by_role("button", name="Approve").click()
    approval = page.get_by_role("dialog")
    approval.get_by_label("Verification basis").select_option("institutional_collaborator")
    approval.get_by_label("Decision note (optional)").fill("Affiliation verified")
    approval.get_by_role("button", name="Confirm eligibility").click()
    expect(page.get_by_text("Runner access approved.")).to_be_visible()
    expect(page.get_by_text("No pending access requests.")).to_be_visible()

    page.get_by_role("tab", name="Users").click()
    user_row = page.get_by_role("row").filter(has_text="Test Scientist")
    user_row.get_by_role("button", name="Credits").click()
    credit_dialog = page.get_by_role("dialog")
    credit_dialog.get_by_label("Adjustment in credits").fill("12")
    credit_dialog.get_by_label("Reason").fill("Approved research allocation")
    credit_dialog.get_by_role("button", name="Apply adjustment").click()
    confirm = page.get_by_role("dialog").last
    confirm.get_by_role("button", name="Apply adjustment").click()
    expect(page.get_by_text("GPU credit adjustment recorded.")).to_be_visible()

    assert any(url.endswith("/admin/users") and method == "POST" and body["username"] == "created-user" for url, method, body in posted)
    decision = next(body for url, method, body in posted if url.endswith("/requests/7/decision") and method == "POST")
    assert decision["decision"] == "approved"
    adjustment = next(body for url, method, body in posted if url.endswith("/gpu-credit/adjustments") and method == "POST")
    assert adjustment["gpu_seconds"] == 720
    assert adjustment["reason"] == "Approved research allocation"


def test_admin_configuration_and_logs_use_live_controls(page: Page) -> None:
    _install_app(page)
    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json=_current_user("admin")))
    posted: list[tuple[str, str, dict | None]] = []
    page.on("request", lambda request: posted.append(
        (request.url, request.method, request.post_data_json if request.post_data else None),
    ))
    page.goto(f"{ORIGIN}/compute/configuration")

    expect(page.get_by_role("heading", name="Runtime configuration")).to_be_visible()
    task_row = page.locator(".config-type-row").filter(has_text="Sequence demo")
    task_row.get_by_text("Sequence demo", exact=True).click()
    expect(task_row.get_by_label("Exclusive")).to_have_value("")
    task_row.get_by_label("CPU cores", exact=True).fill("3")
    task_row.get_by_role("button", name="Save overrides").click()
    expect(page.get_by_text("Sequence demo resource overrides saved.")).to_be_visible()
    task_update = next(body for url, method, body in posted if url.endswith("/admin/config") and method == "PUT")
    assert task_update["task_types"][0]["slurm_exclusive"] is None

    page.get_by_role("tab", name="Resources").click()
    page.get_by_role("button", name="Save resource policy").click()
    expect(page.get_by_text("Resource policy saved.")).to_be_visible()
    update = next(
        body
        for url, method, body in reversed(posted)
        if url.endswith("/admin/config") and method == "PUT" and "slurm" in body
    )
    assert update["slurm"] == {"enabled": True, "allowed_queues": ["cpu", "gpu"]}

    page.goto(f"{ORIGIN}/compute/logs")
    expect(page.get_by_role("heading", name="Server logs")).to_be_visible()
    expect(page.get_by_role("tabpanel", name="Gunicorn access")).to_contain_text("worker ready")
    page.get_by_role("tab", name="Celery worker").click()
    expect(page.get_by_text("Loaded celery-worker:")).to_be_visible()
    page.get_by_text("Rotated log archives").click()
    page.get_by_text("server.log", exact=True).click()
    expect(page.get_by_text("server.log.1", exact=True)).to_be_visible()


def test_real_rfdiffusion_workspace_normalizes_and_collects_structure_selection(
    page: Page,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requested = _install_app(page)
    backend = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    client = backend.app.test_client()
    auth_headers = _test_client_auth(backend)
    catalog_response = client.get("/compute/api/types")
    detail_response = client.get("/compute/api/types/rfdiffusion")
    assert catalog_response.status_code == detail_response.status_code == 200
    catalog = catalog_response.get_json()
    detail = detail_response.get_json()
    parameters_response = client.get(detail["parameters_url"])
    assert parameters_response.status_code == 200
    module_url = detail["input_workspace"]["plugins"][0]["module"]["url"]
    stylesheet_url = detail["input_workspace"]["plugins"][0]["stylesheets"][0]["url"]
    module_response = client.get(module_url, headers=auth_headers)
    stylesheet_response = client.get(stylesheet_url, headers=auth_headers)
    assert module_response.status_code == stylesheet_response.status_code == 200

    page.route(f"{ORIGIN}/compute/api/types", lambda route: route.fulfill(json=catalog))
    page.route(f"{ORIGIN}/compute/api/types/rfdiffusion", lambda route: route.fulfill(json=detail))
    page.route(
        f"{ORIGIN}{detail['parameters_url']}",
        lambda route: route.fulfill(json=parameters_response.get_json()),
    )
    page.route(
        f"{ORIGIN}{module_url}",
        lambda route: route.fulfill(
            content_type="text/javascript",
            body=module_response.get_data(),
        ),
    )
    page.route(
        f"{ORIGIN}{stylesheet_url}",
        lambda route: route.fulfill(
            content_type="text/css",
            body=stylesheet_response.get_data(),
        ),
    )

    normalizations: list[dict] = []

    def normalize(route) -> None:
        payload = route.request.post_data_json
        normalizations.append(payload)
        response = client.post(
            "/compute/api/types/rfdiffusion/workspace/normalize",
            headers=auth_headers,
            json=payload,
        )
        route.fulfill(
            status=response.status_code,
            content_type="application/json",
            body=response.get_data(),
        )

    page.route(f"{ORIGIN}/compute/api/types/rfdiffusion/workspace/normalize", normalize)
    preflight_bodies: list[bytes] = []

    def preflight(route) -> None:
        preflight_bodies.append(route.request.post_data_buffer or b"")
        route.fulfill(json={
            "valid": True,
            "security": {"status": "passed"},
            "contract": {"status": "passed"},
            "admission": {
                "allowed": True,
                "runner_ready": True,
                "infrastructure_ready": True,
                "infrastructure_status": "READY",
            },
            "normalized_params": {},
            "inputs": [{"role": "structure", "format": "pdb", "path": "target.pdb"}],
            "warnings": [],
            "errors": [],
        })

    page.route(f"{ORIGIN}/compute/api/preflight/rfdiffusion", preflight)
    page.goto(f"{ORIGIN}/compute/create_task?task_type=rfdiffusion")

    expect(page.get_by_role("heading", name="RFdiffusion", exact=True)).to_be_visible()
    expect(page.locator('link[data-workspace-plugin="placer-rfdiffusion:rfdiffusion-regions"]')).to_have_count(1)
    page.locator("#rfd_mode").select_option("binder")
    expect(page.locator(".rfd-status")).to_contain_text("needs a target and hotspots")

    page.get_by_label("Optional guiding structure").set_input_files({
        "name": "target.pdb",
        "mimeType": "chemical/x-pdb",
        "buffer": b"ATOM      1  CA  ALA A  10      11.000  12.000  13.000  1.00 20.00           C\n",
    })
    page.wait_for_function("window.__viewerLoads && window.__viewerLoads.includes('target.pdb')")
    page.evaluate("window.__emitViewerSelection([{chain: 'A', residue: 10}, {chain: 'A', residue: 11}])")
    page.get_by_role("button", name="Use selection as target", exact=True).click()
    expect(page.locator(".rfd-feedback")).to_have_text("Target: A10\u201311")
    page.get_by_role("button", name="Use selection as hotspots", exact=True).click()
    expect(page.locator(".rfd-status")).to_have_text("Binder: A10-11/0 100-100")

    page.get_by_role("button", name="Review", exact=True).click()
    expect(page.get_by_role("button", name="Run", exact=True)).to_be_enabled()

    assert normalizations[-1]["capability_id"] == "design_regions"
    expected_value = {
        "version": 1,
        "mode": "binder",
        "segments": [
            {"kind": "fixed", "chain": "A", "start": 10, "end": 11},
            {"kind": "chain_break"},
            {"kind": "generated", "min_length": 100, "max_length": 100},
        ],
        "hotspots": [{"chain": "A", "residue": 10}, {"chain": "A", "residue": 11}],
        "raw_contig": None,
    }
    assert normalizations[-1]["value"] == expected_value
    body = preflight_bodies[0].decode("utf-8", errors="replace")
    workspace_match = re.search(r'name="workspace"\r\n\r\n(.+?)\r\n--', body, flags=re.DOTALL)
    assert workspace_match
    workspace = json.loads(workspace_match.group(1))
    assert workspace["capabilities"]["design_regions"] == expected_value
    assert f"{ORIGIN}{module_url}" in requested
    assert f"{ORIGIN}{stylesheet_url}" in requested

    page.get_by_role("button", name="Change method", exact=True).click()
    expect(page.locator('link[data-workspace-plugin="placer-rfdiffusion:rfdiffusion-regions"]')).to_have_count(0)
    assert page.evaluate("window.__viewerDisposals") == 1
