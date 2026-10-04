# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the fpocket Ranked-pockets result workspace.

This does not fabricate scientific values. It runs the production normalizer over
the pinned 1SUO output, publishes the manifest through the real server
(``task_runtime._finalize_results_manifest``), and drives the built Result
workspace in Chrome. The assertions are about *presentation semantics* — the
primary entity-table renders the pocket rows it is handed, the detection summary
reports the declared scalar, the evidence tabs are present, and no view is a
runner-name special case — not about which pocket scores are correct (the frozen
reference owns that, and the browser is never the source of expected values).
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import result_dist
from conftest import _load_pssm_module, _upsert_task_for_user

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "docker/runners/fpocket"
FIXTURES = ROOT / "tests/data/fpocket"
INPUT_STRUCTURE = ROOT / "tests/data/pdb/1SUO.pdb"
ORIGIN = "https://revocompute.example"
CSP = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
    "script-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:"
)


def _build_manifest(module, tmp_path: Path) -> tuple[str, dict, Path]:
    """Publish a real fpocket manifest from the pinned run and return it."""
    task_id = uuid.uuid4().hex
    result_dir = tmp_path / "result"
    (result_dir / "work" / "1SUO_out").mkdir(parents=True)
    shutil.copytree(FIXTURES / "1SUO_out", result_dir / "work" / "1SUO_out", dirs_exist_ok=True)
    shutil.copy(INPUT_STRUCTURE, result_dir / "1SUO.pdb")
    provenance = result_dir / "fpocket-run.json"
    provenance.write_text(json.dumps({"task_type": "fpocket", "parameters": {}}), encoding="utf-8")
    subprocess.run(
        [sys.executable, str(FAMILY / "normalize_results.py"), str(result_dir), "--provenance", str(provenance)],
        check=True,
        capture_output=True,
        text=True,
    )
    _upsert_task_for_user(
        module,
        task_id,
        filename="1SUO.pdb",
        file_path=result_dir / "1SUO.pdb",
        result_dir=result_dir,
        username="tester",
        task_type="fpocket",
    )
    task = module.task_store.get_task(task_id)
    root = Path(module.app.config["storage_resolver"].get_task_root(task))
    module.task_runtime._finalize_results_manifest(task, execution_state="completed", finished_at=1_700_000_000)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return task_id, manifest, root


def _projected_manifest(manifest: dict, root: Path, task_id: str) -> dict:
    """Enrich the stored manifest the way the Server does at serve time."""
    for artifact in manifest["artifacts"]:
        path = artifact["path"]
        artifact["capability"] = artifact.get("preview") or "download_only"
        artifact["url"] = f"/compute/api/results/{task_id}/artifacts/{path}"
        if artifact["capability"] == "table":
            artifact["table_url"] = f"/compute/api/results/{task_id}/tables/{path}"
    manifest.update(
        {
            "status": "finished",
            "terminal": True,
            "error": None,
            "archive": {"ready": False, "request_url": f"/compute/api/results/{task_id}/archive"},
        }
    )
    return manifest


def _serve(page: Page, manifest: dict, root: Path, task_id: str) -> list[dict]:
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
        relative = route.request.url.split(f"/results/{task_id}/tables/", 1)[1].split("?", 1)[0]
        with (root / relative).open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        calls.append({"path": relative, "columns": len(rows[0]) if rows else 0})
        route.fulfill(json={"columns": rows[0], "rows": rows[1:], "offset": 0, "limit": len(rows) - 1, "has_more": False})

    page.route(f"{ORIGIN}/static/app/**", static)
    page.route(
        f"{ORIGIN}/compute/api/auth/me",
        lambda route: route.fulfill(json={"id": 1, "username": "owner", "role": "user"}),
    )
    page.route(
        f"{ORIGIN}/compute/api/running/{task_id}",
        lambda route: route.fulfill(
            json={
                "task_id": task_id,
                "task_type": "fpocket",
                "display_name": "1SUO.pdb",
                "status": "finished",
                "terminal": True,
                "result_available": True,
                "status_url": f"/compute/api/running/{task_id}",
                "results_url": f"/compute/api/results/{task_id}",
                "error": None,
            }
        ),
    )
    page.route(f"{ORIGIN}/compute/api/results/{task_id}", lambda route: route.fulfill(json=manifest))
    page.route(f"{ORIGIN}/compute/api/results/{task_id}/tables/**", tables)
    page.route(
        f"{ORIGIN}/compute/api/results/{task_id}/artifacts/**",
        lambda route: route.fulfill(status=200, body="artifact"),
    )
    page.goto(f"{ORIGIN}/compute/results/{task_id}")
    return calls


def _errors(page: Page) -> list[str]:
    found: list[str] = []
    page.on("console", lambda m: found.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: found.append(f"pageerror: {e}"))
    return found


def test_fpocket_ranked_pockets_render_as_the_primary_view(monkeypatch, tmp_path: Path, page: Page) -> None:
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    task_id, manifest, root = _build_manifest(module, tmp_path)
    expected_rows = list(csv.DictReader((root / "pockets.csv").open(newline="", encoding="utf-8")))
    manifest = _projected_manifest(manifest, root, task_id)

    errors = _errors(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.add_init_script("localStorage.setItem('revocompute-theme', 'light');")
    calls = _serve(page, manifest, root, task_id)

    # The declared primary view opens the page.
    expect(page.get_by_role("heading", name="Ranked pockets")).to_be_visible()
    table = page.locator(".result-preview table.result-table")
    expect(table).to_be_visible()
    # It read the real pockets.csv through the bounded table endpoint.
    assert any(call["path"] == "pockets.csv" for call in calls), calls
    header = table.locator("thead th").all_inner_texts()
    assert "pocket" in header and "score" in header and "druggability_score" in header, header
    # The rendered rows are the published pockets, in score order, with the pocket
    # identity kept distinct from the rank.
    body = table.locator("tbody tr")
    expect(body).to_have_count(len(expected_rows))
    first_row = body.first.locator("td").all_inner_texts()
    assert first_row[0] == expected_rows[0]["pocket"]
    assert first_row[1] == expected_rows[0]["rank"]

    # The evidence tabs are present and generic (no runner-name special case).
    for title in ("Detection summary", "Raw fpocket output"):
        expect(page.get_by_role("button", name=title, exact=True)).to_be_visible()

    # A declared view opens under its own title and description. `scalar-summary`
    # and `evidence-bundle` have no dedicated browser renderer, so they present
    # through the generic artifact capability path while keeping their declared
    # identity — which is the documented behaviour, not a runner-name branch.
    page.get_by_role("button", name="Detection summary", exact=True).click()
    expect(page.get_by_role("heading", name="Detection summary")).to_be_visible()
    expect(page.locator(".result-preview-header")).to_contain_text("Detected pocket count")

    assert errors == [], errors
