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


def _install_app(page: Page) -> list[str]:
    dist = result_dist()
    entry = json.loads((dist / ".vite" / "manifest.json").read_text(encoding="utf-8"))["index.html"]
    styles = "".join(f'<link rel="stylesheet" href="/static/app/{name}">' for name in entry.get("css", []))
    html = f'<!doctype html><html><head>{styles}<script type="module" src="/static/app/{entry["file"]}"></script></head><body><div id="app"></div></body></html>'
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    for pattern in ("/runners", "/runners/*", "/compute/create_task**", "/compute/dashboard", "/compute/results/*"):
        page.route(f"{ORIGIN}{pattern}", lambda route: route.fulfill(content_type="text/html", body=html))

    def static(route):
        relative = route.request.url.split("/static/app/", 1)[1].split("?", 1)[0]
        route.fulfill(path=dist / relative)

    page.route(f"{ORIGIN}/static/app/**", static)
    page.route(
        f"{ORIGIN}/compute/logo.svg",
        lambda route: route.fulfill(content_type="image/svg+xml", body="<svg xmlns='http://www.w3.org/2000/svg'/>")
    )
    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json={"id": 1, "username": "tester", "full_name": "Test Scientist", "role": "user"}))
    page.route(f"{ORIGIN}/compute/api/auth/token", lambda route: route.fulfill(json={"token": "ephemeral"}))
    page.route(f"{ORIGIN}/compute/api/infrastructure", lambda route: route.fulfill(json={"status": "READY", "ready": True, "stale": False, "checks": []}))
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
    page.get_by_role("button", name="Review Sequence demo").click()
    expect(page.get_by_text("Preflight passed. Review the checks, then run the experiment.")).to_be_visible()
    page.get_by_role("button", name="Run Sequence demo").click()
    expect(page.get_by_role("heading", name="Task dashboard")).to_be_visible()
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
    page.route(f"{ORIGIN}/compute/login**", lambda route: route.fulfill(content_type="text/html", body="<p>Login</p>"))
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page).to_have_url(f"{ORIGIN}/compute/login?return_to=%2Fcompute%2Fdashboard")


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
        lambda route: route.fulfill(json={"id": 1, "username": "admin", "full_name": "Admin Scientist", "role": "admin"}),
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
    page.route(f"{ORIGIN}/compute/login**", lambda route: route.fulfill(content_type="text/html", body="<p>Login</p>"))
    page.on("dialog", lambda dialog: dialog.accept())

    page.goto(f"{ORIGIN}/compute/dashboard")
    page.get_by_role("button", name="Delete", exact=True).click()

    expect(page).to_have_url(f"{ORIGIN}/compute/login?return_to=%2Fcompute%2Fdashboard")


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
    page.route(f"{ORIGIN}/compute/results/not-a-task", lambda route: route.fulfill(
        content_type="text/html",
        body=(f'<script type="module" src="/static/app/'
              f'{json.loads((result_dist() / ".vite" / "manifest.json").read_text())["index.html"]["file"]}"></script>'
              '<main id="app"></main>'),
    ))
    page.goto(f"{ORIGIN}/compute/results/not-a-task")
    expect(page.get_by_role("heading", name="Page not found")).to_be_visible()


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

    page.get_by_role("button", name="Review RFdiffusion", exact=True).click()
    expect(page.get_by_text("Preflight passed. Review the checks, then run the experiment.")).to_be_visible()

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
