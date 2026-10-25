# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""The Local Result Workspace reads a real directory the reader chooses.

This contract selects an on-disk folder through the page's own
``input[webkitdirectory]`` with Playwright's real directory upload, so the
browser produces ``webkitRelativePath`` exactly as it does for a reader. The
existing unit tests hand ``openLocalResult`` synthetic ``File`` objects with a
stubbed relative path; only a browser can prove the chooser, the relative-path
shapes, and the ``connect-src blob:`` CSP under which local bytes are read.

The page is served with the Server's own CSP header, read from the application
rather than restated here, and the contract asserts the declared matrix and
entity-table views render from the folder's bytes with no request to
``/compute/api/results``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, expect
import pytest

import browser_frontend_assets
from browser_frontend_assets import result_dist
from conftest import _load_pssm_module, _test_client_auth

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://revocompute.example"
STATIC = ROOT / "revocompute" / "static"

MATRIX_PATH = "couplings/scores.csv"
ENTITY_PATH = "evidence/pairs.csv"
MATRIX_TEXT = "position,1,2,3\n1,0,1.25,-2.5\n2,1.25,0,3.75\n3,-2.5,3.75,0\n"
ENTITY_TEXT = "pair,score\nA:1-B:2,4.5\nA:2-B:3,2.25\n"

_CURRENT_USER = {
    "username": "tester",
    "email": "tester@example.org",
    "email_verified": True,
    "role": "user",
    "full_name": "Test Scientist",
    "affiliation": "Example Institute",
    "position": "research_assistant",
    "pi_name": "Dr Example",
}

_CSP_LISTENER = (
    "window.__cspViolations = [];"
    "document.addEventListener('securitypolicyviolation', event => "
    "window.__cspViolations.push(event.effectiveDirective + ':' + event.blockedURI));"
)

_CONTENT_TYPES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ttf": "font/ttf",
    ".woff2": "font/woff2",
}


def _artifact(path: str, text: str, *, role: str) -> dict:
    data = text.encode("utf-8")
    return {
        "path": path,
        "role": role,
        "media_type": "text/csv",
        "preview": "table",
        "capability": "table",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _manifest(artifacts: list[dict]) -> dict:
    return {
        "schema_version": 3,
        "task_id": "0123456789abcdef0123456789abcdef",
        "task_type": "demo",
        "created_at": "2026-10-25T00:00:00Z",
        "run": {"method": {"name": "Local fixture method", "output_summary": "Two declared tables"}},
        "limitations": [],
        "output_check": {"state": "passed", "checks": [], "problems": []},
        "outcome": "SUCCESS",
        "storyboard": None,
        "artifacts": artifacts,
        "views": [
            {
                "id": "scores",
                "plugin": "matrix",
                "role": "primary",
                "title": "Coupling strengths",
                "description": "Frobenius norms of residue-pair couplings.",
                "sources": {"matrices": [MATRIX_PATH]},
                "mapping": {
                    "format": "csv",
                    "row_labels_column": "position",
                    "x_label": "Alignment position",
                    "y_label": "Alignment position",
                    "unit": "coupling score",
                    "direction": "higher",
                    "scale": "diverging",
                    "center": 0,
                },
            },
            {
                "id": "pairs",
                "plugin": "entity-table",
                "role": "evidence",
                "title": "Ranked pairs",
                "description": "Residue pairs ordered by coupling strength.",
                "sources": {"table": [ENTITY_PATH]},
                "mapping": {"label_column": "pair", "evidence_columns": ["score"]},
            },
        ],
        "result": {"files": {}},
        "total_size": sum(artifact["size"] for artifact in artifacts),
    }


def _write_result(parent: Path) -> Path:
    """Write the smallest valid result folder a reader could have extracted."""
    result = parent / "local-result"
    for path, text in ((MATRIX_PATH, MATRIX_TEXT), (ENTITY_PATH, ENTITY_TEXT)):
        target = result / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    artifacts = [
        _artifact(MATRIX_PATH, MATRIX_TEXT, role="primary"),
        _artifact(ENTITY_PATH, ENTITY_TEXT, role="evidence"),
    ]
    (result / "manifest.json").write_text(json.dumps(_manifest(artifacts), sort_keys=True), encoding="utf-8")
    return result


def _serve_page(page: Page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """Serve the real page and its production CSP; return the requested URLs."""
    dist = result_dist()
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "app").symlink_to(dist, target_is_directory=True)
    module.app.static_folder = str(static_root)
    response = module.app.test_client().get("/compute/local_results", headers=_test_client_auth(module))
    assert response.status_code == 200
    csp = response.headers["Content-Security-Policy"]
    # The production policy, not a test copy: a local file is fetchable because
    # the Server already allows blob: connections for the shared renderers.
    assert "connect-src 'self' blob:" in csp

    requested: list[str] = []
    page.add_init_script(_CSP_LISTENER)
    page.on("request", lambda request: requested.append(request.url))
    page.route(
        f"{ORIGIN}/compute/local_results",
        lambda route: route.fulfill(
            status=200,
            headers={
                "Content-Security-Policy": csp,
                "Content-Type": "text/html; charset=utf-8",
                "Referrer-Policy": "no-referrer",
            },
            body=response.get_data(as_text=True),
        ),
    )

    def serve_static(route) -> None:
        relative = urlparse(route.request.url).path.split("/static/", 1)[1]
        path = dist / relative.removeprefix("app/") if relative.startswith("app/") else STATIC / relative
        if not path.is_file():
            route.abort()
            return
        route.fulfill(
            content_type=_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"),
            body=path.read_bytes(),
        )

    page.route(f"{ORIGIN}/static/**", serve_static)
    page.route(f"{ORIGIN}/compute/api/auth/me", lambda route: route.fulfill(json=_CURRENT_USER))
    page.route(f"{ORIGIN}/compute/api/auth/token", lambda route: route.fulfill(json={"token": "local-test"}))
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": []}))
    page.route(
        f"{ORIGIN}/compute/api/environment",
        lambda route: route.fulfill(json={"version": 1, "demo_mode": False, "execution": "available"}),
    )
    page.goto(f"{ORIGIN}/compute/local_results")
    expect(page.get_by_role("button", name="Open local result folder")).to_be_visible()
    return requested


def _assert_no_result_requests(requested: list[str]) -> None:
    assert any("/static/app/" in url for url in requested), "the frontend bundle never loaded"
    assert not [url for url in requested if "/compute/api/results" in url], requested


def test_real_directory_renders_declared_views_under_production_csp(
    page: Page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    requested = _serve_page(page, monkeypatch, tmp_path)
    result = _write_result(tmp_path / "fixture")

    # Playwright uploads the directory itself, so the browser, not the test,
    # produces each file's webkitRelativePath.
    page.locator("input[webkitdirectory]").set_input_files(str(result))

    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()
    expect(page.get_by_role("heading", name="Coupling strengths")).to_be_visible()
    assert "-3.75" in page.locator(".pair-matrix-label").all_inner_texts()
    matrix = page.locator(".pair-matrix-view canvas")
    matrix.press("ArrowRight")
    expect(page.locator(".pair-matrix-readout")).to_contain_text("1.25")

    # The verification line reports the files whose bytes and hashes were checked.
    expect(page.locator(".result-archive-status")).to_contain_text(
        "2 files match the sizes and SHA-256 hashes their manifest declares."
    )

    page.locator(".result-view-menu > summary").click()
    page.get_by_role("button", name="Ranked pairs", exact=True).click()
    expect(page.get_by_role("heading", name="Ranked pairs")).to_be_visible()
    # Read the rendered rows, not the fixture text: the table is the proof the
    # local CSV reached the shared renderer.
    rows = page.locator(".entity-table-view table tr").all_inner_texts()
    assert any("A:1-B:2" in row and "4.5" in row for row in rows), rows
    assert any("A:2-B:3" in row and "2.25" in row for row in rows), rows

    # The declared production policy permits reading a local handle, and the
    # page never substituted a Server route for the folder.
    assert page.evaluate(
        """async () => {
          const url = URL.createObjectURL(new Blob(['csp-probe'], {type: 'text/plain'}));
          try { return await (await fetch(url)).text(); } finally { URL.revokeObjectURL(url); }
        }"""
    ) == "csp-probe"
    assert page.evaluate("() => window.__cspViolations") == []
    _assert_no_result_requests(requested)


def test_parent_directory_selection_is_refused_without_server_fallback(
    page: Page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Choosing one level above the result cannot be mistaken for the result."""
    requested = _serve_page(page, monkeypatch, tmp_path)
    parent = tmp_path / "fixture"
    _write_result(parent)

    page.locator("input[webkitdirectory]").set_input_files(str(parent))

    report = page.locator(".local-result-open [role=status]")
    expect(report).to_have_attribute("data-error", "true")
    expect(report).to_contain_text("Files the manifest declares are missing from this folder:")
    expect(page.locator(".pair-matrix-view")).to_have_count(0)
    expect(page.locator(".entity-table-view")).to_have_count(0)
    assert page.evaluate("() => window.__cspViolations") == []
    _assert_no_result_requests(requested)
