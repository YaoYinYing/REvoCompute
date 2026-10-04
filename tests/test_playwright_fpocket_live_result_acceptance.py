# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance against the LIVE fpocket 1SUO ResultManifest.

Unlike ``test_playwright_fpocket_result_acceptance.py`` (a self-contained run of
the production normalizer), this serves the exact manifest and artifacts a real
Slurm+Apptainer fpocket run published for the scientific case, staged under
``REVOCOMPUTE_FPOCKET_STAGE`` (default ``/var/tmp/pr45-accept``). It proves the
browser renders the *production* pocket result through the declared generic views.

The scientific expected values are pinned by the frozen reference, not by this
test; the browser only proves presentation. When the stage is absent the case is
skipped rather than fabricated, because a synthetic copy would not prove what
this test exists to prove.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import result_dist

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
STAGE = Path(os.environ.get("REVOCOMPUTE_FPOCKET_STAGE", "/var/tmp/pr45-accept"))
MANIFEST_PATH = STAGE / "manifest.json"
TASK_ID = "b546f034ffc7fafac871f21176a03c91"
ORIGIN = "https://revocompute.example"
CSP = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
    "script-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:"
)

if not MANIFEST_PATH.is_file():
    pytest.skip(f"no staged fpocket live run at {STAGE} (set REVOCOMPUTE_FPOCKET_STAGE)", allow_module_level=True)


def _projected_manifest() -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["task_id"] == TASK_ID, "staged manifest is not the fpocket scientific run"
    assert manifest["task_type"] == "fpocket"
    for artifact in manifest["artifacts"]:
        path = artifact["path"]
        artifact.setdefault("capability", artifact.get("preview") or "download_only")
        artifact["url"] = f"/compute/api/results/{TASK_ID}/artifacts/{path}"
        if artifact["capability"] == "table":
            artifact["table_url"] = f"/compute/api/results/{TASK_ID}/tables/{path}"
    manifest.update(
        {
            "status": "finished",
            "terminal": True,
            "error": None,
            "archive": {"ready": False, "request_url": f"/compute/api/results/{TASK_ID}/archive"},
        }
    )
    return manifest


def _serve(page: Page, manifest: dict) -> list[dict]:
    dist = result_dist()
    entry = json.loads((dist / ".vite" / "manifest.json").read_text(encoding="utf-8"))["index.html"]
    styles = "".join(f'<link rel="stylesheet" href="/static/app/{name}">' for name in entry.get("css", []))
    html = (
        f'<!doctype html><html><head>{styles}'
        f'<script type="module" src="/static/app/{entry["file"]}"></script></head>'
        f'<body><div id="app"></div></body></html>'
    )
    page.route(
        f"{ORIGIN}/compute/results/*",
        lambda route: route.fulfill(content_type="text/html", headers={"Content-Security-Policy": CSP}, body=html),
    )
    page.route(f"{ORIGIN}/compute/login**", lambda route: route.fulfill(content_type="text/html", body="<p>Login</p>"))

    def static(route):
        relative = route.request.url.split("/static/app/", 1)[1].split("?", 1)[0]
        route.fulfill(path=dist / relative)

    calls: list[dict] = []

    def tables(route):
        relative = route.request.url.split(f"/results/{TASK_ID}/tables/", 1)[1].split("?", 1)[0]
        with (STAGE / relative).open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        calls.append({"path": relative, "rows": len(rows) - 1})
        route.fulfill(json={"columns": rows[0], "rows": rows[1:], "offset": 0, "limit": len(rows) - 1, "has_more": False})

    page.route(f"{ORIGIN}/static/app/**", static)
    page.route(
        f"{ORIGIN}/compute/api/auth/me",
        lambda route: route.fulfill(json={"id": 1, "username": "owner", "role": "user"}),
    )
    page.route(
        f"{ORIGIN}/compute/api/running/{TASK_ID}",
        lambda route: route.fulfill(
            json={
                "task_id": TASK_ID,
                "task_type": "fpocket",
                "display_name": "1SUO.pdb",
                "status": "finished",
                "terminal": True,
                "result_available": True,
                "status_url": f"/compute/api/running/{TASK_ID}",
                "results_url": f"/compute/api/results/{TASK_ID}",
                "error": None,
            }
        ),
    )
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}", lambda route: route.fulfill(json=manifest))
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}/tables/**", tables)
    page.route(
        f"{ORIGIN}/compute/api/results/{TASK_ID}/artifacts/**",
        lambda route: route.fulfill(status=200, body="artifact"),
    )
    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")
    return calls


def _errors(page: Page) -> list[str]:
    found: list[str] = []
    page.on("console", lambda m: found.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: found.append(f"pageerror: {e}"))
    return found


def test_live_fpocket_ranked_pockets_render(page: Page) -> None:
    manifest = _projected_manifest()
    expected = list(csv.DictReader((STAGE / "pockets.csv").open(newline="", encoding="utf-8")))
    assert len(expected) == 40, f"staged live run published {len(expected)} pockets, expected 40"

    errors = _errors(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.add_init_script("localStorage.setItem('revocompute-theme', 'light');")
    calls = _serve(page, manifest)

    # The declared primary view opens the page and reads the real pockets.csv.
    expect(page.get_by_role("heading", name="Ranked pockets")).to_be_visible()
    table = page.locator(".result-preview table.result-table")
    expect(table).to_be_visible()
    assert any(call["path"] == "pockets.csv" and call["rows"] == 40 for call in calls), calls
    header = table.locator("thead th").all_inner_texts()
    assert "pocket" in header and "score" in header and "druggability_score" in header, header
    body = table.locator("tbody tr")
    expect(body).to_have_count(40)
    first = body.first.locator("td").all_inner_texts()
    assert first[0] == expected[0]["pocket"] == "pocket1"
    assert first[1] == expected[0]["rank"] == "1"

    # The evidence tabs are present under their declared titles (generic plugins).
    for title in ("Detection summary", "Raw fpocket output"):
        expect(page.get_by_role("button", name=title, exact=True)).to_be_visible()

    assert errors == [], errors
