# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Fleet browser acceptance for the real RFdiffusion input workspace.

The generic browser suite drives the synthetic ``sequence_demo`` Runner; this
file owns the one authentic production workspace contract a browser test needs,
because a generic test must never consume a real Runner identity. It loads the
installed fleet's ``rfdiffusion`` task and its
``placer-rfdiffusion:rfdiffusion-regions`` workspace plugin through the
production projection, serves those bytes to the built frontend, and drives the
Create Task workbench: the RFdiffusion workbench mounts, binder mode asks for a
target and hotspots, the structure selection is collected as a normalized design
plan, and the plan the browser submits is the one the Server would receive.

The assertions are presentation and contract semantics, not science: the
normalization is computed by the production ``normalize_rfdiffusion`` backend and
the submitted workspace echo is read out of the real preflight multipart body.
"""

from __future__ import annotations

import json
import re

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import result_dist
from conftest import _load_fleet_module, _test_client_auth

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
CSP = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
    "script-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:"
)


def _install_app(page: Page) -> list[str]:
    """Serve the built frontend bundle for the Create Task workbench."""
    dist = result_dist()
    entry = json.loads((dist / ".vite" / "manifest.json").read_text(encoding="utf-8"))["index.html"]
    styles = "".join(f'<link rel="stylesheet" href="/static/app/{name}">' for name in entry.get("css", []))
    html = (
        '<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        f'{styles}<script type="module" src="/static/app/{entry["file"]}"></script>'
        '</head><body><div id="app"></div></body></html>'
    )
    headers = {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Security-Policy": CSP,
        "Referrer-Policy": "no-referrer",
    }
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    page.route(f"{ORIGIN}/compute/create_task**", lambda route: route.fulfill(headers=headers, body=html))
    page.route(f"{ORIGIN}/compute/login**", lambda route: route.fulfill(headers=headers, body=html))

    def static(route):
        relative = route.request.url.split("/static/app/", 1)[1].split("?", 1)[0]
        route.fulfill(path=dist / relative)

    page.route(f"{ORIGIN}/static/app/**", static)
    page.route(
        f"{ORIGIN}/compute/api/auth/me",
        lambda route: route.fulfill(json={"id": 1, "username": "tester", "role": "user"}),
    )
    page.route(f"{ORIGIN}/compute/api/auth/token", lambda route: route.fulfill(json={"token": "ephemeral"}))
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": []}))
    return requested


def test_real_rfdiffusion_workspace_normalizes_and_collects_structure_selection(
    page: Page,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    requested = _install_app(page)
    backend = _load_fleet_module(
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
    # Submission is exercised elsewhere; here it stops the single-action flow on a
    # server error so the workbench stays mounted for the post-preflight assertions.
    page.route(f"{ORIGIN}/compute/api/post", lambda route: route.fulfill(status=500, json={"error": "not exercised"}))
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
    # The app ships under `script-src 'self'`, so a string predicate that is not
    # already true on the first evaluation forces Playwright to re-poll via
    # `new Function(...)`, which the CSP blocks with an EvalError. Assert the loaded
    # structure through a retrying locator expectation instead, which polls from
    # Playwright's own injected script and is CSP-safe.
    expect(page.locator(".ct-structure-viewer")).to_have_attribute("data-label", "target.pdb")
    page.evaluate("window.__emitViewerSelection([{chain: 'A', residue: 10}, {chain: 'A', residue: 11}])")
    page.get_by_role("button", name="Use selection as target", exact=True).click()
    expect(page.locator(".rfd-feedback")).to_have_text("Target: A10–11")
    page.get_by_role("button", name="Use selection as hotspots", exact=True).click()
    expect(page.locator(".rfd-status")).to_have_text("Binder: A10-11/0 100-100")

    page.get_by_role("button", name="Run task", exact=True).click()
    # The single action runs validation -> preflight -> submit. The submit route is
    # stubbed to 500, so the settled state is a positive submission failure; asserting
    # it (rather than a negative "not Checking task…", which is already true before the
    # async flow starts) serializes the click and pins the outcome. Retrying locator
    # expectation, not a string predicate, under `script-src 'self'`.
    expect(page.locator(".ct-status")).to_contain_text("Submission failed")
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
