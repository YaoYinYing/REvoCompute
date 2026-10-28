# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the frontend-owned ordinary compute workflow."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import result_dist
from frontend_fixtures import builders
from frontend_fixtures.router import serve_environment

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
TASK_ID = "0123456789abcdef0123456789abcdef"


def _open_navigation(page: Page) -> None:
    opener = page.get_by_role('button', name='Open navigation', exact=True)
    if opener.is_visible():
        opener.click()


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
        "considerations": [], "runtime_family": "demo", "gpus": False, "requires_network": False,
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
            "available": True, "publication": "available", "page_url": f"/compute/results/{TASK_ID}",
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


def _metrics(window: str = "daily") -> dict:
    return {
        "window": window,
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


def _resource_entitlement(subject_id: int = 2) -> dict:
    """The account's own canonical envelope: one gated unit and one ungated unit."""
    return {
        "subject_type": "user", "subject_id": subject_id, "period": "2026-09",
        "compute": [
            {
                "unit": "gpu_second", "resource_class": "a100", "enforced": True, "allowance": 180000,
                "used": 74250, "reserved": 6000, "unsettled_allocations": 1, "unsettled_quantity": 6000,
                "remaining": 99750, "usage_complete": False, "evidence_sources": ["slurm_accounting"],
            },
            {
                "unit": "cpu_core_second", "resource_class": "", "enforced": False, "allowance": None,
                "used": 12000, "reserved": 0, "unsettled_allocations": 0, "unsettled_quantity": 0,
                "remaining": None, "usage_complete": True, "evidence_sources": [],
            },
        ],
        "storage": {
            "logical_owned_bytes": 10737418240, "soft_limit_bytes": 21474836480,
            "remaining_bytes": 10737418240, "over_soft_limit": False,
        },
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
        "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:; connect-src 'self' blob:",
        "Referrer-Policy": "no-referrer",
    }
    for pattern in (
        "/", "/api-docs", "/runners", "/runners/*", "/compute/login**", "/compute/register",
        "/compute/reset_password**", "/compute/user_verify**", "/compute/terms", "/compute/profile**", "/compute/account/*",
        "/compute/quota",
        "/compute/runner_fleet", "/compute/user_control", "/compute/configuration", "/compute/logs", "/compute/create_task**",
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
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": []}))
    page.route(f"{ORIGIN}/openapi.json", lambda route: route.fulfill(json={
        "openapi": "3.1.0", "info": {"title": "REvoCompute API", "version": "3"},
        "paths": {"/compute/api/types": {"get": {"summary": "List Runner types", "responses": {"200": {"description": "Catalog"}}}}},
    }))
    page.route(f"{ORIGIN}/compute/api/infrastructure", lambda route: route.fulfill(json=_infrastructure()))
    serve_environment(page, ORIGIN)
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
    page.route(f"{ORIGIN}/compute/api/access/requests", lambda route: route.fulfill(status=201, json={"policy_id": "academic-only", "requests": [{"entitlement": "academic-models", "status": "pending"}]}))
    page.route(f"{ORIGIN}/compute/api/gpu-credit", lambda route: route.fulfill(json=_gpu_credit()))
    page.route(f"{ORIGIN}/compute/api/user-metrics?*", lambda route: route.fulfill(json=_metrics(parse_qs(urlsplit(route.request.url).query).get("window", ["daily"])[0])))
    subject_id = 2
    page.route(f"{ORIGIN}/compute/api/resource-entitlement", lambda route: route.fulfill(json=_resource_entitlement(subject_id)))
    page.route(
        f"{ORIGIN}/compute/api/resource-ledger**",
        lambda route: route.fulfill(json=builders.build_resource_ledger(subject_id)),
    )

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

    def admin_report_resources(route) -> None:
        query = parse_qs(urlsplit(route.request.url).query)
        subject = int(query.get("subject", [subject_id])[0])
        route.fulfill(json=builders.build_admin_resource_report(subject))

    page.route(f"{ORIGIN}/compute/api/auth/admin/users", admin_users)
    page.route(f"{ORIGIN}/compute/api/auth/admin/reports/resources?*", admin_report_resources)
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
            "runtime_family": "demo", "is_workflow_stage": False, "category": "evolution", "inputs": [],
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


def _record_request_order(page: Page) -> list[str]:
    """Record the ordered preflight/submit calls the single-action flow makes."""
    order: list[str] = []

    def record(request) -> None:
        if "/compute/api/preflight/" in request.url:
            order.append("preflight")
        elif request.url.endswith("/compute/api/post"):
            order.append("submit")

    page.on("request", record)
    return order


def _open_sequence_create(page: Page) -> None:
    page.goto(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    expect(page.locator(".ct-status")).not_to_contain_text("Loading experiment protocol")
    page.locator("textarea[aria-label='Protein sequence']").fill(">sample\nACDEFG")


def test_single_run_task_action_preflights_then_submits_without_a_second_click(page: Page) -> None:
    _install_app(page)
    order = _record_request_order(page)
    page.route(f"{ORIGIN}/compute/api/preflight/sequence_demo", lambda route: route.fulfill(json={
        "valid": True, "security": {"status": "passed"}, "contract": {"status": "passed"},
        "admission": {"allowed": True, "runner_ready": True, "infrastructure_ready": True, "infrastructure_status": "READY"},
        "normalized_params": {"iterations": 2}, "inputs": [],
        "warnings": [{"message": "This run may take several minutes."}], "errors": [],
    }))
    _open_sequence_create(page)
    page.get_by_role("button", name="Run task", exact=True).click()
    expect(page.get_by_role("heading", name="Tasks", exact=True)).to_be_visible()
    assert "preflight" in order and "submit" in order
    assert order.index("preflight") < order.index("submit")


def test_run_task_is_disabled_until_local_validation_passes(page: Page) -> None:
    _install_app(page)
    order = _record_request_order(page)
    page.goto(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    run = page.get_by_role("button", name="Run task", exact=True)
    expect(run).to_be_disabled()
    page.locator("textarea[aria-label='Protein sequence']").fill(">sample\nACDEFG")
    expect(run).to_be_enabled()
    run.click()
    expect(page.get_by_role("heading", name="Tasks", exact=True)).to_be_visible()
    assert "preflight" in order


def test_terminal_review_step_is_contract_only_not_a_protocol_column(page: Page) -> None:
    _install_app(page)
    workspace_bodies: list[str] = []

    def capture(route) -> None:
        workspace_bodies.append(route.request.post_data_buffer or b"")
        route.fulfill(json={
            "valid": True, "security": {"status": "passed"}, "contract": {"status": "passed"},
            "admission": {"allowed": True, "runner_ready": True, "infrastructure_ready": True, "infrastructure_status": "READY"},
            "normalized_params": {}, "inputs": [], "warnings": [], "errors": [],
        })

    # Stop the run after preflight so the workbench stays mounted for inspection.
    page.route(f"{ORIGIN}/compute/api/preflight/sequence_demo", capture)
    page.route(f"{ORIGIN}/compute/api/post", lambda route: route.fulfill(status=500, json={"error": "not exercised"}))
    _open_sequence_create(page)
    # The manifest's terminal Review step is not rendered as a protocol column.
    assert page.locator(".ct-protocol-step[data-step-id='review']").count() == 0
    expect(page.locator("[data-capability-id='review']")).to_have_count(0)
    page.get_by_role("button", name="Run task", exact=True).click()
    expect(page.locator(".ct-status")).to_contain_text("Submission failed")
    # ...but its capability still contributes the terminal payload to submission.
    body = workspace_bodies[0].decode("utf-8", errors="replace")
    workspace = json.loads(re.search(r'name="workspace"\r\n\r\n(.+?)\r\n--', body, flags=re.DOTALL).group(1))
    terminal = workspace["capabilities"]["review"]
    assert terminal["task_type"] == "sequence_demo"
    assert "inputs" in terminal and "params" in terminal
    for key in ("files", "input_roles", "task_type", "workspace", "params[iterations]"):
        assert f'name="{key}"' in body


def test_failed_preflight_blocks_submission_and_restores_the_form(page: Page) -> None:
    _install_app(page)
    order = _record_request_order(page)
    page.route(f"{ORIGIN}/compute/api/post", lambda route: route.fulfill(status=202, json={"task_id": TASK_ID}))
    page.route(f"{ORIGIN}/compute/api/preflight/sequence_demo", lambda route: route.fulfill(json={
        "valid": False, "security": {"status": "passed"}, "contract": {"status": "failed"},
        "admission": {"allowed": True, "runner_ready": True, "infrastructure_ready": True, "infrastructure_status": "READY"},
        "normalized_params": {}, "inputs": [], "warnings": [],
        "errors": [{"message": "Sequence is too short."}],
    }))
    _open_sequence_create(page)
    run = page.get_by_role("button", name="Run task", exact=True)
    run.click()
    expect(page.locator(".ct-validation-row.error")).to_contain_text("Sequence is too short.")
    assert page.get_by_role("heading", name="Tasks", exact=True).count() == 0
    expect(run).to_be_enabled()
    assert "submit" not in order


def test_repeated_run_task_clicks_submit_once(page: Page) -> None:
    _install_app(page)
    submits: list[str] = []
    page.route(
        f"{ORIGIN}/compute/api/post",
        lambda route: (submits.append(route.request.url), route.fulfill(status=202, json={"task_id": TASK_ID}))[1],
    )
    _open_sequence_create(page)
    page.evaluate("""() => {
        const button = [...document.querySelectorAll('button')].find(item => item.textContent.trim() === 'Run task');
        button.click(); button.click(); button.click();
    }""")
    expect(page.get_by_role("heading", name="Tasks", exact=True)).to_be_visible()
    assert len(submits) == 1


def test_the_check_window_locks_the_method_and_rejects_changed_inputs(page: Page) -> None:
    _install_app(page)
    order = _record_request_order(page)
    submits: list[str] = []
    held: list = []

    page.route(f"{ORIGIN}/compute/api/preflight/sequence_demo", lambda route: held.append(route))
    page.route(
        f"{ORIGIN}/compute/api/post",
        lambda route: (submits.append(route.request.url), route.fulfill(status=202, json={"task_id": TASK_ID}))[1],
    )
    _open_sequence_create(page)
    run = page.get_by_role("button", name="Run task", exact=True)
    # The preflight fetch is dispatched asynchronously after the click, so wait for
    # the interception callback to capture it. Resolving an empty hold list would
    # leave the check pending forever and the edit below would never be observed.
    with page.expect_request(f"{ORIGIN}/compute/api/preflight/sequence_demo"):
        run.click()
    expect(page.locator(".ct-status")).to_contain_text("Checking task…")
    # The single action owns the run for its duration: neither the method switch nor a
    # second Run can start a competing submission while the check is in flight.
    expect(page.get_by_role("button", name="Change method", exact=True)).to_be_disabled()
    expect(run).to_be_disabled()
    assert held, "the in-flight preflight request was not intercepted"
    # An edit inside the check window invalidates the pending check instead of silently
    # submitting the pre-edit inputs.
    page.locator("textarea[aria-label='Protein sequence']").fill(">sample\nACDEFGHIKL")
    for route in held:
        route.fulfill(json={
            "valid": True, "security": {"status": "passed"}, "contract": {"status": "passed"},
            "admission": {"allowed": True, "runner_ready": True, "infrastructure_ready": True, "infrastructure_status": "READY"},
            "normalized_params": {}, "inputs": [], "warnings": [], "errors": [],
        })
    expect(page.locator(".ct-status")).to_contain_text("Inputs changed during the check")
    expect(run).to_be_enabled()
    assert submits == []
    assert "submit" not in order


def test_runner_to_result_workflow_is_frontend_owned_and_refreshable(page: Page) -> None:
    requests = _install_app(page)
    page.goto(f"{ORIGIN}/runners")
    expect(page.get_by_role("heading", name="Runner catalog")).to_be_visible()
    page.get_by_role("link", name="View method").click()
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    page.get_by_role("link", name="Create task").first.click()
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    page.locator("textarea[aria-label='Protein sequence']").fill(">sample\nACDEFG")
    page.get_by_role("button", name="Run task", exact=True).click()
    expect(page.get_by_role("heading", name="Tasks", exact=True)).to_be_visible()
    page.get_by_role("link", name="Results").click()
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    assert any("/compute/api/preflight/sequence_demo" in url for url in requests)
    assert any("/compute/api/post" in url for url in requests)
    assert any("/compute/api/tasks" in url for url in requests)


def test_create_task_keeps_workspace_mount_errors_visible(page: Page) -> None:
    _install_app(page)
    detail = _detail()
    detail["input_workspace"]["steps"][0]["capabilities"][0]["plugin"] = "unavailable_fixture_plugin"
    page.route(f"{ORIGIN}/compute/api/types/sequence_demo", lambda route: route.fulfill(json=detail))
    page.goto(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")
    expect(page.locator("textarea[aria-label='Protein sequence']")).to_be_visible()
    expect(page.locator(".ct-status.error")).to_contain_text("unsupported component")
    expect(page.get_by_role("button", name="Run task", exact=True)).to_be_disabled()


@pytest.mark.parametrize("path", ["/runners", "/runners/sequence_demo", "/compute/create_task", "/compute/dashboard"])
def test_application_routes_refresh_without_overflow(page: Page, path: str) -> None:
    _install_app(page)
    page.set_viewport_size({"width": 320, "height": 760})
    page.goto(f"{ORIGIN}{path}")
    page.reload()
    expect(page.locator(".app-header")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


@pytest.mark.parametrize("method_count", [1, 3, 12])
def test_runner_catalog_cardinality_layout_is_usable(page: Page, method_count: int) -> None:
    _install_app(page)
    access = {"restricted": False, "granted": True, "request_status": None}
    task_types = [{
        "name": f"method_{index:02d}", "display_name": f"Method {index:02d}", "category": "evolution",
        "summary": f"Synthetic method {index:02d} exercised for catalog layout coverage.", "access": access,
        "detail_url": f"/compute/api/types/method_{index:02d}",
        "parameters_url": f"/compute/api/task-parameters/method_{index:02d}",
    } for index in range(method_count)]
    catalog = {"version": 3, "categories": [{"name": "evolution", "label": "Evolution"}], "task_types": task_types}
    page.route(f"{ORIGIN}/compute/api/types", lambda route: route.fulfill(json=catalog))
    for task in task_types:
        page.route(f"{ORIGIN}{task['detail_url']}", lambda route, task=task: route.fulfill(json={**_detail(), **task}))

    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{ORIGIN}/runners")
    expect(page.get_by_role("heading", name="Runner catalog")).to_be_visible()

    def assert_cards_usable() -> None:
        cards = page.locator(".runner-card")
        expect(cards).to_have_count(method_count)
        viewport_width = page.viewport_size["width"]
        for index in range(method_count):
            card = cards.nth(index)
            expect(card).to_be_visible()
            assert card.locator("h3").inner_text().strip()
            box = card.bounding_box()
            assert box is not None
            assert box["width"] <= viewport_width + 1
            assert box["x"] + box["width"] <= viewport_width + 1
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")

    def assert_multi_column_layout() -> None:
        # A desktop grid should place at least two cards on the same row unless it
        # legitimately collapses to a single column that fills the grid width.
        boxes = []
        for index in range(method_count):
            box = page.locator(".runner-card").nth(index).bounding_box()
            assert box is not None
            boxes.append(box)
        card_width = max(box["width"] for box in boxes)
        grid_width = page.locator(".runner-grid").first.bounding_box()["width"]
        if card_width >= grid_width - 2:
            return
        assert any(
            abs(left["y"] - right["y"]) <= 2 and right["x"] - left["x"] >= 40
            for left in boxes for right in boxes
        ), "expected a row containing two cards side by side"

    assert_cards_usable()

    # The group heading counts the register; the unfiltered aggregate does not
    # restate it.
    expect(page.locator(".catalog-count")).to_be_empty()
    expect(page.locator(".runner-group").first).to_contain_text(
        f"{method_count} {'method' if method_count == 1 else 'methods'}"
    )

    switch = page.locator(".layout-switch")
    if method_count <= 3:
        expect(switch).to_be_hidden()
    else:
        expect(switch).to_be_visible()

    if method_count > 1:
        assert_multi_column_layout()

    if method_count > 3:
        page.get_by_role("button", name="Compact", exact=True).click()
        expect(page.locator(".runner-catalog")).to_have_attribute("data-density", "compact")
        assert_cards_usable()
        assert_multi_column_layout()
        page.get_by_role("button", name="Comfortable", exact=True).click()
        expect(page.locator(".runner-catalog")).to_have_attribute("data-density", "comfortable")


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
        lambda route: (requested.append(route.request.post_data or ""), route.fulfill(status=201, json={"policy_id": "academic-only", "requests": [{"entitlement": "academic-models", "status": "pending"}]})),
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
    # Administration retains its authorized destinations in the shared navigation.
    _open_navigation(page)
    expect(page.locator("[data-nav-group='admin']").get_by_role("link", name="Server logs")).to_have_attribute("href", "/compute/logs")
    assert page.locator(".app-header").get_by_label("Administration").count() == 0
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Delete selected (0)")).to_be_hidden()
    page.get_by_role("checkbox", name="Select sample.fasta", exact=True).check()
    page.get_by_role("button", name="Delete selected (1)").click()
    # The confirmation is the application's own dialog, so the destructive request
    # is issued only after the reader confirms.
    dialog = page.locator("#app-dialog")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Delete selected").click()
    expect(page.get_by_text("Selected tasks deleted.")).to_be_visible()
    assert deleted and TASK_ID in deleted[0]


@pytest.mark.parametrize("width", [320, 1280])
def test_anonymous_shell_offers_no_forbidden_administration_links(page: Page, width: int) -> None:
    _install_app(page)
    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(status=401, json={"error": "Authentication required"}))
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(f"{ORIGIN}/runners")
    expect(page.get_by_role("heading", name="Runner catalog", exact=True)).to_be_visible()
    # Anonymous navigation carries no Administration destinations at any width, and
    # there is no second hidden Administration launcher in the top bar.
    expect(page.locator("[data-nav-group='admin']")).to_be_hidden()
    assert page.get_by_role("link", name="User control").count() == 0
    assert page.get_by_role("link", name="Server logs").count() == 0
    assert page.get_by_role("link", name="Configuration").count() == 0
    assert page.locator(".app-header").get_by_label("Administration").count() == 0
    # Account is the only other region, and it is a sign-in affordance: the
    # region's own links are hidden behind the one visible sign-in destination.
    _open_navigation(page)
    expect(page.locator("[data-nav-group='account']")).to_be_visible()
    account = page.locator("[data-nav-group='account'] a:visible")
    expect(account).to_have_count(1)
    expect(account.first).to_have_attribute("href", "/compute/login?return_to=%2Frunners")


def test_mid_session_expiry_redirects_after_mutation(page: Page) -> None:
    _install_app(page)
    page.route(
        f"{ORIGIN}/compute/api/delete/{TASK_ID}",
        lambda route: route.fulfill(status=401, json={"error": "Authentication required"}),
    )

    page.goto(f"{ORIGIN}/compute/dashboard")
    page.locator(".task-overflow > summary").first.click()
    page.get_by_role("button", name="Delete", exact=True).click()
    # Confirming the application dialog issues the mutation; the expired session
    # then redirects to sign in with the dashboard as its return target.
    page.locator("#app-dialog").get_by_role("button", name="Delete").click()

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
    assert page.locator(".app-nav").evaluate("node => getComputedStyle(node).position") != "fixed"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    result_colors = page.locator(".result-app").evaluate(
        "node => [getComputedStyle(node).color, getComputedStyle(document.body).backgroundColor]"
    )
    assert result_colors[0] != result_colors[1]


@pytest.mark.parametrize(("width", "theme"), [(390, "light"), (1440, "light"), (1440, "dark")])
def test_page_kickers_keep_their_role_inside_page_headings(page: Page, width: int, theme: str) -> None:
    page.set_viewport_size({"width": width, "height": 780})
    page.emulate_media(color_scheme=theme)
    _install_app(page)
    paint = """node => {
        const style = getComputedStyle(node);
        return Object.fromEntries(['color', 'fontSize', 'fontWeight', 'marginTop', 'marginBottom']
            .map(property => [property, style[property]]));
    }"""
    page.goto(f"{ORIGIN}/runners/sequence_demo")
    reference = page.locator(".runner-detail-heading .page-kicker")
    expect(reference).to_be_visible()
    page.evaluate("() => document.fonts.ready")
    kicker_paint = reference.evaluate(paint)
    page.goto(f"{ORIGIN}/compute/dashboard")
    kicker = page.locator(".page-heading .page-kicker")
    expect(kicker).to_be_visible()
    page.evaluate("() => document.fonts.ready")
    # Daylight keeps the context label readable and subordinate to its page title;
    # the method reference composition is migrated in a later visual slice.
    dashboard_kicker = kicker.evaluate(paint)
    title_size = page.locator(".page-heading h1").evaluate("node => parseFloat(getComputedStyle(node).fontSize)")
    assert 10 <= float(dashboard_kicker["fontSize"].removesuffix("px")) < title_size
    assert page.locator(".page-heading p:not(.page-kicker)").evaluate("el => parseFloat(getComputedStyle(el).fontSize)") >= 14
    # Account's heading is the section's own identity, not a context label over
    # one, so the page contrasts its heading with its introductory prose instead.
    page.goto(f"{ORIGIN}/compute/profile")
    introduction = page.locator("[data-account-summary]")
    expect(introduction).to_be_visible()
    body_paint = introduction.evaluate(paint)
    assert float(body_paint["fontSize"].removesuffix("px")) > float(kicker_paint["fontSize"].removesuffix("px"))
    assert body_paint["color"] != kicker_paint["color"]
    assert float(body_paint["marginTop"].removesuffix("px")) > float(kicker_paint["marginTop"].removesuffix("px"))


def test_malformed_result_id_stays_in_frontend_not_found_state(page: Page) -> None:
    _install_app(page)
    page.goto(f"{ORIGIN}/compute/results/not-a-task")
    expect(page.get_by_role("heading", name="Page not found")).to_be_visible()


@pytest.mark.parametrize("width", [320, 390, 768, 1280])
def test_public_home_is_immediate_responsive_and_refreshable(page: Page, width: int) -> None:
    requests = _install_app(page)
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(f"{ORIGIN}/")

    expect(page.get_by_role("heading", name="REvoCompute", exact=True).first).to_be_visible()
    expect(page.get_by_text("Scientific computation, managed")).to_be_visible()
    page.reload()
    expect(page.get_by_role("heading", name="REvoCompute", exact=True).first).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    expect(page.locator(".public-brand .bench-mark svg")).to_be_visible()
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
    expect(page.get_by_role("heading", name="Tasks", exact=True)).to_be_visible()
    assert any(url.endswith("/forgot-password") and body == {"email": "tester@example.org"} for url, body in posted)
    assert any(url.endswith("/login") and body["username"] == "tester" for url, body in posted)


@pytest.mark.parametrize("width", [320, 1280])
def test_public_sign_in_failure_feedback_stays_in_the_viewport(page: Page, width: int) -> None:
    _install_app(page)
    page.set_viewport_size({"width": width, "height": 780})
    page.route(
        f"{ORIGIN}/compute/api/auth/login",
        lambda route: route.fulfill(status=401, json={"error": "Invalid credentials"}),
    )
    page.goto(f"{ORIGIN}/compute/login")
    # Keep the live region exposed before inserting feedback, so AT observes updates.
    expect(page.locator(".app-notices")).to_have_attribute("aria-live", "polite")
    expect(page.locator(".app-notices")).not_to_have_css("display", "none")
    page.get_by_label("Username or email").fill("tester")
    page.get_by_label("Password", exact=True).fill("wrong password")
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.locator(".app-notice")).to_have_text("Sign in failed.")
    toast = page.locator(".app-notice").bounding_box()
    assert toast is not None
    assert 56 <= toast["y"] < toast["y"] + toast["height"] < 780, toast
    assert toast["x"] >= 0 and toast["x"] + toast["width"] <= width, toast


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

    expect(page.get_by_role("heading", name="Account", exact=True)).to_be_visible()
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

    # Every Account section is a direct destination in the shell's Account region.
    _open_navigation(page)
    account_nav = page.locator("[data-nav-group='account']")
    expect(account_nav.get_by_role("link", name="Security", exact=True)).to_have_attribute(
        "href", "/compute/account/security")
    expect(account_nav.get_by_role("link", name="API key", exact=True)).to_have_attribute(
        "href", "/compute/account/api-key")
    expect(account_nav.get_by_role("link", name="Runner access", exact=True)).to_have_attribute(
        "href", "/compute/account/runner-access")
    expect(account_nav.get_by_role("link", name="GPU credits", exact=True)).to_have_attribute(
        "href", "/compute/account/gpu-credits")
    expect(account_nav.get_by_role("link", name="Metrics", exact=True)).to_have_attribute(
        "href", "/compute/account/metrics")

    # The Quota page is the account's own resource position: a destination of the
    # Account region with its own protected address, reached from the sidebar.
    expect(account_nav.get_by_role("link", name="Quota", exact=True)).to_have_attribute(
        "href", "/compute/quota")

    page.goto(f"{ORIGIN}/compute/account/api-key")
    expect(page.get_by_role("heading", name="API key")).to_be_visible()
    page.get_by_role("button", name="Generate API key").click()
    expect(page.locator("[data-api-key-value]")).to_have_value("rvk_test_secret_once")
    page.reload()
    expect(page.get_by_text("An active API key is configured.")).to_be_visible()
    page.get_by_role("button", name="Revoke API key").click()
    page.get_by_role("dialog").get_by_role("button", name="Revoke API key").click()
    expect(page.get_by_role("alert").filter(has_text="API key revoked.")).to_be_visible()

    page.goto(f"{ORIGIN}/compute/account/runner-access")
    expect(page.get_by_role("heading", name="Runner access")).to_be_visible()
    page.get_by_text("Policy details").click()
    expect(page.get_by_text("Academic use only")).to_be_visible()
    expect(page.get_by_text("The upstream licence requires verified academic eligibility.")).to_be_visible()
    page.get_by_label("Research use and affiliation").fill("Non-commercial work at Example Institute")
    page.get_by_role("button", name="Request access").click()
    expect(page.get_by_text("Access request submitted.")).to_be_visible()

    page.goto(f"{ORIGIN}/compute/account/gpu-credits")
    expect(page.get_by_role("heading", name="GPU credits")).to_be_visible()
    expect(page.get_by_text("September 2026")).to_be_visible()
    expect(page.get_by_text("GPU access granted")).to_be_visible()

    page.goto(f"{ORIGIN}/compute/account/metrics")
    expect(page.get_by_role("heading", name="Metrics")).to_be_visible()
    expect(page.get_by_text("Tasks submitted")).to_be_visible()
    expect(page.get_by_text("80%")).to_be_visible()
    # The compute-history chart has a labelled count axis: major ticks with a
    # minor tick midway between each, and period ticks along the x-axis.
    chart = page.locator(".activity-chart")
    expect(chart).to_have_count(1)
    assert chart.locator(".activity-axis-y .activity-tick-major").all_inner_texts() == ["0", "5", "10"]
    expect(chart.locator(".activity-axis-y .activity-tick-minor")).to_have_count(0)
    expect(chart.locator(".activity-axis-x .activity-tick-major").filter(has_text=re.compile(r"\d"))).not_to_have_count(0)
    # The axis and plot are grid areas of `.activity-chart`. If the grid is not
    # established on that element the areas resolve to nothing, the y-axis (an
    # empty box whose ticks are absolutely positioned) collapses to zero height,
    # and the plot and x-axis stack. Counting the tick nodes alone passes in that
    # state, so require the y-axis to occupy a real box.
    expect(chart.locator(".activity-axis-y")).to_be_visible()
    page.get_by_role("button", name="Weekly").click()
    expect(page.get_by_role("button", name="Weekly")).to_have_attribute("aria-pressed", "true")
    assert any("window=weekly" in url for url, _, _ in posted)

    assert any(url.endswith("/me/api-key") and method == "POST" for url, method, _ in posted)
    assert any(url.endswith("/me/api-key") and method == "DELETE" for url, method, _ in posted)
    profile_update = next(body for url, method, body in posted if url.endswith("/me") and method == "PUT")
    assert profile_update == {
        "full_name": "Updated Scientist", "affiliation": "New Institute",
        "position": "associate_professor", "pi_name": "Professor Example",
    }
    access = next(body for url, method, body in posted if url.endswith("/access/requests") and method == "POST")
    assert access == {"policy_id": "academic-only", "reason": "Non-commercial work at Example Institute"}
    assert any("window=weekly" in url for url, _, _ in posted)


def test_profile_wrong_password_stays_inline_and_guest_profile_is_read_only(page: Page) -> None:
    _install_app(page)

    def reject_password(route) -> None:
        if route.request.method == "PUT":
            route.fulfill(status=400, json={"error": "Current password is incorrect"})
        else:
            route.fulfill(json=_current_user())

    page.route(f"{ORIGIN}/compute/api/auth/me", reject_password)
    page.goto(f"{ORIGIN}/compute/account/security")
    expect(page.get_by_role("heading", name="Security")).to_be_visible()
    page.get_by_label("Current password").fill("mistyped")
    page.get_by_label("New password", exact=True).fill("replacement-password")
    page.get_by_label("Confirm new password").fill("replacement-password")
    page.get_by_role("button", name="Update password").click()
    expect(page.get_by_role("alert").filter(has_text="Current password is incorrect")).to_be_visible()
    expect(page).to_have_url(f"{ORIGIN}/compute/account/security")

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
    expect(page.get_by_role("heading", name="Account", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    # The Account sections are the shell's own Account region, one page each: there
    # is no nested tab strip inside the page, so the section controls are the
    # navigation and never appear twice.
    _open_navigation(page)
    expect(page.locator("[data-nav-group='account']").get_by_role("link", name="GPU credits", exact=True)).to_be_visible()
    expect(page.get_by_role("tab")).to_have_count(0)

    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json=_current_user("admin")))
    page.goto(f"{ORIGIN}/compute/user_control")
    expect(page.get_by_role("heading", name="User control")).to_be_visible()
    expect(page.locator("[data-nav-group='admin'] a[aria-current='page']")).to_have_attribute("href", "/compute/user_control")
    assert page.locator("[data-nav-group='compute'] a[aria-current='page']").count() == 0
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

    # The operator's drill-in renders the canonical waterfall and the raw ledger
    # window that the waterfall links to, not just the credit totals.
    expect(credit_dialog.get_by_role("heading", name="GPU credit waterfall")).to_be_visible()
    expect(credit_dialog.get_by_role("heading", name="Ledger - 2026-10")).to_be_visible()
    expect(credit_dialog).to_contain_text("UTC calendar-month allowance")
    expect(credit_dialog.locator("#ledger")).to_be_visible()

    assert any(url.endswith("/admin/users") and method == "POST" and body["username"] == "created-user" for url, method, body in posted)
    decision = next(body for url, method, body in posted if url.endswith("/requests/7/decision") and method == "POST")
    assert decision["decision"] == "approved"
    adjustment = next(body for url, method, body in posted if url.endswith("/gpu-credit/adjustments") and method == "POST")
    assert adjustment["gpu_seconds"] == 720
    assert adjustment["reason"] == "Approved research allocation"


def _open_admin_credit_dialog(page: Page) -> None:
    page.goto(f"{ORIGIN}/compute/user_control")
    expect(page.get_by_role("heading", name="User control")).to_be_visible()
    page.get_by_role("tab", name="Users").click()
    page.get_by_role("row").filter(has_text="Test Scientist").get_by_role("button", name="Credits").click()


def _ledger_unavailable(route) -> None:
    route.fulfill(status=503, json={
        "error": "The resource ledger is unavailable.", "unavailable_reason": "ledger_unavailable",
    })


def test_admin_credit_controls_survive_a_ledger_outage(page: Page) -> None:
    """A ledger outage hides the waterfall, never the audited policy controls."""
    _install_app(page)
    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json=_current_user("admin")))
    page.route(f"{ORIGIN}/compute/api/auth/admin/reports/resources?*", _ledger_unavailable)
    _open_admin_credit_dialog(page)
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Adjustment in credits")).to_be_visible()
    expect(dialog).to_contain_text("The GPU credit ledger window is currently unavailable")
    dialog.get_by_label("Adjustment in credits").fill("3")
    dialog.get_by_label("Reason").fill("Outage-safe adjustment")
    dialog.get_by_role("button", name="Apply adjustment").click()
    page.get_by_role("dialog").last.get_by_role("button", name="Apply adjustment").click()
    expect(page.get_by_text("GPU credit adjustment recorded.")).to_be_visible()


def test_admin_credit_mutation_success_survives_a_failed_refresh(page: Page) -> None:
    """A recorded mutation is reported even when the reads after it fail."""
    _install_app(page)
    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json=_current_user("admin")))
    state = {"mutated": False}

    def credit(route) -> None:
        if route.request.method == "POST" and route.request.url.endswith("/adjustments"):
            state["mutated"] = True
            route.fulfill(status=201, json={"entry_id": 2, "gpu_credit": _gpu_credit(2, 720)})
        elif state["mutated"]:
            _ledger_unavailable(route)
        else:
            route.fulfill(json=_gpu_credit())

    def report(route) -> None:
        if state["mutated"]:
            _ledger_unavailable(route)
        else:
            route.fulfill(json=builders.build_admin_resource_report(2))

    page.route(f"{ORIGIN}/compute/api/auth/admin/users/*/gpu-credit/adjustments", credit)
    page.route(f"{ORIGIN}/compute/api/auth/admin/users/*/gpu-credit", credit)
    page.route(f"{ORIGIN}/compute/api/auth/admin/reports/resources?*", report)
    _open_admin_credit_dialog(page)
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("heading", name="GPU credit waterfall")).to_be_visible()
    dialog.get_by_label("Adjustment in credits").fill("12")
    dialog.get_by_label("Reason").fill("Refresh failure check")
    dialog.get_by_role("button", name="Apply adjustment").click()
    page.get_by_role("dialog").last.get_by_role("button", name="Apply adjustment").click()
    expect(page.get_by_text("GPU credit adjustment recorded.")).to_be_visible()
    expect(dialog.get_by_label("Adjustment in credits")).to_be_visible()
    expect(dialog).to_contain_text("The GPU credit ledger window is currently unavailable")
    expect(dialog).to_contain_text("The GPU credit summary is currently unavailable")


def _fleet_payload() -> dict:
    return {
        "runners": [
            {
                "runner_family": "stale_runner",
                "readiness": {
                    "status": "VALIDATION_STALE",
                    "reason_code": "RUNTIME_BUNDLE_CHANGED",
                    "message": "Runtime bundle changed",
                    "next_action": "live-test",
                    "active_image": {"state": "ACTIVE", "sha256": "sha256:sif", "reason_code": None},
                    "evidence": {
                        "sif_path": "/images/stale_runner.sif", "sif_exists": True, "sif_sha256": "sha256:sif",
                        "build_provenance_current": True, "build_provenance_digest": "sha256:build",
                        "runtime_bundle_sha256": "sha256:bundle", "receipt_exists": True, "receipt_valid": False,
                        "receipt_tested_at": "2026-01-01T00:00:00Z",
                        "required_smoke_cases": ["smoke"], "passed_smoke_cases": [], "doctor_ok": True,
                    },
                },
                "capacity": {"available": True, "reason": "scheduler_available"},
                "access": {"restricted": False, "granted": True, "policy_id": None},
                "in_flight": None,
            },
            {
                "runner_family": "healthy_runner",
                "readiness": {
                    "status": "READY", "reason_code": "READY", "message": "ok", "next_action": "none",
                    "active_image": {"state": "ACTIVE", "sha256": "sha256:sif", "reason_code": None},
                    "evidence": {
                        "sif_path": "/images/healthy_runner.sif", "sif_exists": True, "sif_sha256": "sha256:sif",
                        "build_provenance_current": True, "build_provenance_digest": "sha256:build",
                        "runtime_bundle_sha256": None, "receipt_exists": True, "receipt_valid": True,
                        "receipt_tested_at": "2026-02-02T00:00:00Z",
                        "required_smoke_cases": ["smoke"], "passed_smoke_cases": ["smoke"], "doctor_ok": True,
                    },
                },
                "capacity": {"available": True, "reason": "scheduler_available"},
                "access": {"restricted": False, "granted": True, "policy_id": None},
                "in_flight": None,
            },
        ],
        "executor": {"available": True, "reason": "operator_executor_available"},
    }


def _plan_payload(family: str) -> dict:
    return {
        "action": "runner.live_test", "tier": "mutate", "runner_family": family,
        "requested_intent": "runner.live_test", "current_state": "VALIDATION_STALE",
        "reason_code": "RUNTIME_BUNDLE_CHANGED", "evidence_digest": "sha256:" + "e" * 16,
        "effective_actions": ["live_test"], "expected_effects": ["Run bounded smoke acceptance and write a receipt on success"],
        "not_required": [{"operation": "build_sif", "label": "Build a new Runner SIF"}],
        "lease_scope": "runner/" + family, "requires_confirmation": False,
        "next_state_effect": "receipt written", "cli_reference": "restart.sh live-test --runner " + family,
        "plan_digest": "sha256:" + "a" * 16, "evaluated_at": 1.0,
    }


def test_admin_runner_management_plans_revalidates_and_runs_typed_actions(page: Page) -> None:
    """The Runner Management surface reads real readiness and runs a planned action."""
    _install_app(page)
    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json=_current_user("admin")))
    posted: list[tuple[str, str, dict | None]] = []
    page.on("request", lambda request: posted.append(
        (request.url, request.method, request.post_data_json if request.post_data else None),
    ))
    page.route(f"{ORIGIN}/compute/api/auth/admin/runners", lambda route: route.fulfill(json=_fleet_payload()))
    page.route(
        f"{ORIGIN}/compute/api/auth/admin/runners/*",
        lambda route: route.fulfill(json={
            "runner_family": "stale_runner",
            "readiness": _fleet_payload()["runners"][0]["readiness"],
            "capacity": {"available": True, "reason": "scheduler_available"},
            "access": {"restricted": False, "granted": True, "policy_id": None},
            "actions": [{
                "id": "runner.live_test", "tier": "mutate", "lease_scope": "runner/stale_runner",
                "summary": "Run bounded smoke acceptance", "requires_confirmation": False,
                "next_state_effect": "receipt written", "parameters": [{"name": "runner_family", "kind": "family", "required": True, "maximum_length": 64}],
                "available": True, "plan": _plan_payload("stale_runner"),
            }],
        }),
    )
    page.route(f"{ORIGIN}/compute/api/auth/admin/runners/*/history?*", lambda route: route.fulfill(json={"history": []}))
    page.route(f"{ORIGIN}/compute/api/auth/admin/runners/*/actions", lambda route: route.fulfill(status=202, json={
        "job": {"job_id": "opjob_1", "action": "runner.live_test", "runner_family": "stale_runner", "status": "RUNNING"},
        "plan": _plan_payload("stale_runner"), "accepted": True,
    }))

    page.goto(f"{ORIGIN}/compute/runner_fleet")
    expect(page.get_by_role("heading", name="Runner Management", level=1)).to_be_visible()
    expect(page.get_by_role("heading", name="Runner Management", exact=True)).to_have_count(1)
    with page.expect_response(f"{ORIGIN}/compute/api/auth/admin/runners"):
        page.get_by_role("button", name="Refresh", exact=True).click()
    # Readiness and capacity are separate columns; the machine reason is human copy.
    stale_row = page.locator("tr[data-family='stale_runner']")
    expect(stale_row).to_contain_text("Validation stale")
    expect(stale_row).to_contain_text("Receipt stale")
    ready_row = page.locator("tr[data-family='healthy_runner']")
    expect(ready_row).to_contain_text("Ready")
    # The register is summarized by the server's own verdicts as counts, and the
    # host executor is reported once as a capability rather than per family.
    summary = page.locator(".fleet-summary")
    expect(summary).to_contain_text("Runner families")
    expect(summary).to_contain_text("1 of 2 enabled Runner famil")
    expect(page.locator(".fleet-executor")).to_contain_text("Host executor available")

    stale_row.get_by_role("button", name="stale_runner", exact=True).click()
    expect(page.get_by_role("heading", name="stale_runner", level=2)).to_be_visible()
    expect(page.get_by_text("This plan will not")).to_have_count(0)
    page.get_by_role("button", name="Review and run").click()
    expect(page.get_by_text("This plan will not")).to_be_visible()
    expect(page.get_by_text("Build a new Runner SIF")).to_be_visible()
    page.get_by_label("Reason").fill("Revalidate after the runtime bundle change.")
    with page.expect_response(lambda response: response.url.endswith("/actions") and response.request.method == "POST"):
        page.get_by_role("button", name="Run", exact=True).click()
    page.wait_for_load_state("networkidle")

    run = next(body for url, method, body in posted if url.endswith("/actions") and method == "POST")
    assert run == {"action": "runner.live_test", "plan_digest": "sha256:" + "a" * 16, "idempotency_key": run["idempotency_key"]}
    assert run["idempotency_key"]
    assert page.evaluate("window.__cspViolations") == []


@pytest.mark.parametrize("width", [320, 834, 1280])
def test_save_feedback_and_system_notices_clear_each_other_and_navigation(page: Page, width: int) -> None:
    _install_app(page)
    # Hold the transient lifetime: this case measures simultaneous geometry,
    # independent of the speed of a traced browser on a shared host.
    page.clock.install(time="2026-10-08T00:00:00Z")
    page.clock.pause_at("2026-10-08T01:00:00Z")
    page.set_viewport_size({"width": width, "height": 780})
    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json=_current_user("admin")))
    notices = [
        {"id": f"maintenance-{index}", "level": "warning", "title": f"Maintenance {index}",
         "body": "Storage maintenance details. " * 80}
        for index in range(3)
    ]
    page.add_init_script(
        "localStorage.setItem('revocompute-notices-hidden', "
        "JSON.stringify(['maintenance-0', 'maintenance-1', 'maintenance-2']))"
    )
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": notices}))
    page.goto(f"{ORIGIN}/compute/configuration")
    page.get_by_role("tab", name="Resources", exact=True).click()
    page.get_by_role("button", name="Save resource policy", exact=True).click()
    expect(page.locator(".app-notice")).to_have_text("Resource policy saved.")
    page.get_by_role("button", name="System notices").click()
    expect(page.locator(".sys-notice")).to_have_count(3)
    for body in page.locator(".sys-notice-body").all():
        expect(body).to_be_visible()
    stack = page.locator(".sys-notices").bounding_box()
    feedback = page.locator(".app-notices").bounding_box()
    assert stack is not None and feedback is not None and feedback["height"] > 0
    assert stack["y"] >= 56, stack
    assert stack["y"] + stack["height"] < feedback["y"], (stack, feedback)
    header = page.locator(".app-header").bounding_box()
    assert header is not None and stack["y"] >= header["y"] + header["height"]
    sidebar = page.locator(".app-sidebar").bounding_box()
    if sidebar:
        assert stack["x"] >= sidebar["x"] + sidebar["width"]
    assert feedback["y"] + feedback["height"] <= page.viewport_size["height"]


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


# ── Create Task accessibility properties ──────────────────────────────────────


def _rgb(value: str) -> tuple[float, float, float, float]:
    """Parse a painted colour into 0-255 channels plus its alpha.

    Accepts the legacy ``rgb()``/``rgba()`` form and the modern ``color(srgb …)``
    form a resolved ``color-mix()`` computes to, so a tinted ring is measured as
    the colour the browser reports rather than failing to parse.
    """
    if value.startswith("color("):
        inner = value[value.find("(") + 1:value.rfind(")")].replace("/", " ")
        parts = [part for part in inner.split() if part]
        assert parts[0] == "srgb", value
        channels = [float(part) * 255 for part in parts[1:4]]
        alpha = float(parts[4]) if len(parts) > 4 else 1.0
        return channels[0], channels[1], channels[2], alpha
    inner = value[value.find("(") + 1:value.rfind(")")].replace(",", " ").replace("/", " ")
    parts = [part for part in inner.split() if part]
    channels = [float(part[:-1]) * 2.55 if part.endswith("%") else float(part) for part in parts[:3]]
    alpha = float(parts[3]) if len(parts) > 3 else 1.0
    return channels[0], channels[1], channels[2], alpha


def _relative_luminance(value: str) -> float:
    def linear(channel: float) -> float:
        scaled = channel / 255
        return scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4

    red, green, blue, _ = _rgb(value)
    return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)


def _contrast_ratio(foreground: str, background: str) -> float:
    """Non-text contrast of what is actually painted.

    A translucent ring is not seen as its own colour: it is composited over the
    surface behind it, and that composite is what must separate from the surface.
    """
    red, green, blue, alpha = _rgb(foreground)
    if alpha < 1:
        base_red, base_green, base_blue, _ = _rgb(background)
        foreground = "rgb(%f %f %f)" % (
            alpha * red + (1 - alpha) * base_red,
            alpha * green + (1 - alpha) * base_green,
            alpha * blue + (1 - alpha) * base_blue,
        )
    lighter, darker = sorted((_relative_luminance(foreground), _relative_luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# Read the *painted* ring and the surface it sits on. An outline is drawn outside
# the border box and, with an offset, lands on whatever the nearest ancestor
# paints, so the adjacent background is that ancestor's fill - not the focused
# control's own. The probe measures the real render rather than a frozen literal.
_FOCUS_RING_PROBE = """() => {
    const node = document.activeElement;
    if (!node || node === document.body || !node.closest('.create-task')) return null;
    const ring = getComputedStyle(node).outlineColor;
    let host = node.parentElement;
    while (host) {
        const fill = getComputedStyle(host).backgroundColor;
        const match = fill.match(/rgba?\\(([^)]+)\\)/);
        const alpha = match ? (match[1].split('/')[1] ?? match[1].split(',')[3] ?? '1') : '1';
        if (!/transparent/.test(fill) && parseFloat(alpha) > 0) return { ring, surface: fill };
        host = host.parentElement;
    }
    return null;
}"""


def _visible_level_one_headings(page: Page) -> list[str]:
    return page.evaluate(
        """() => [...document.querySelectorAll('h1')]
            .filter(h => h.getClientRects().length > 0)
            .map(h => h.textContent.trim())"""
    )


def test_create_task_renders_one_visible_level_one_heading_per_state(page: Page) -> None:
    _install_app(page)

    # The chooser state: the page title is the only level-1 heading on screen.
    page.goto(f"{ORIGIN}/compute/create_task")
    expect(page.get_by_role("heading", name="Choose a compute method", exact=True)).to_be_visible()
    assert _visible_level_one_headings(page) == ["Create task"]

    # The workbench state: the method's display name replaces the page title, so
    # the two headings are never visible at the same time.
    page.get_by_role("button", name="Sequence demo").first.click()
    expect(page.get_by_role("heading", name="Sequence demo", exact=True)).to_be_visible()
    expect(page.locator(".ct-workbench textarea")).to_be_visible()
    assert _visible_level_one_headings(page) == ["Sequence demo"]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_create_task_focus_indicators_reach_non_text_contrast(page: Page, theme: str) -> None:
    page.emulate_media(color_scheme=theme)
    _install_app(page)
    page.goto(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")
    expect(page.locator(".ct-workbench textarea")).to_be_visible()

    # Walk the workspace's own focusable controls rather than one chosen element:
    # a focus style is a workspace property, and the raised snapshot panel is the
    # surface the previous translucent ring failed against.
    samples = page.locator(".ct-workbench button, .ct-workbench input, .ct-workbench textarea, .ct-workbench summary")
    assert samples.count() > 0
    measured = 0
    for index in range(samples.count()):
        control = samples.nth(index)
        control.focus()
        probe = page.evaluate(_FOCUS_RING_PROBE)
        assert probe, f"control {index} did not take focus inside the workspace"
        if "0, 0, 0, 0" in probe["ring"] or "transparent" in probe["ring"]:
            continue
        ratio = _contrast_ratio(probe["ring"], probe["surface"])
        assert ratio >= 3.0, f"{theme}: focus ring {probe['ring']} on {probe['surface']} is {ratio:.2f}:1"
        measured += 1
    assert measured > 0, f"{theme}: no focus indicator was measured"


def test_create_task_validation_changes_land_in_a_live_region(page: Page) -> None:
    _install_app(page)
    page.route(f"{ORIGIN}/compute/api/preflight/sequence_demo", lambda route: route.fulfill(json={
        "valid": False, "security": {"status": "passed"}, "contract": {"status": "failed"},
        "admission": {"allowed": True, "runner_ready": True, "infrastructure_ready": True, "infrastructure_status": "READY"},
        "normalized_params": {}, "inputs": [], "warnings": [],
        "errors": [{"message": "Sequence is too short."}],
    }))
    _open_sequence_create(page)

    # The region that carries validation exists from mount, before any change: a
    # polite live region added only once validation fires is never announced.
    region = page.locator('[aria-live="polite"]').filter(has=page.locator(".ct-validation"))
    expect(region).to_have_count(1)
    region.evaluate("node => node.dataset.mounted = 'before'")

    page.get_by_role("button", name="Run task", exact=True).click()
    expect(page.locator(".ct-validation-row.error")).to_contain_text("Sequence is too short.")
    # The same mounted node absorbed the change, so the update is announced rather
    # than inserted into a region a screen reader had never been told about.
    expect(region).to_have_count(1)
    assert region.evaluate("node => node.dataset.mounted") == "before"


def test_create_task_status_error_is_announced_assertively(page: Page) -> None:
    _install_app(page)
    page.route(f"{ORIGIN}/compute/api/post", lambda route: route.fulfill(status=500, json={"error": "not exercised"}))
    _open_sequence_create(page)

    status = page.locator(".ct-status")
    expect(status).not_to_have_attribute("role", "alert")
    page.get_by_role("button", name="Run task", exact=True).click()
    expect(page.locator(".ct-status.error")).to_contain_text("Submission failed")
    expect(status).to_have_attribute("role", "alert")
