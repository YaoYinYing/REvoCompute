# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the AutoDock Vina result workspace.

This drives the built production frontend against the bytes a real Vina Runner
run published on the target host (``tests/data/autodock_vina/live``), published
through the real server finalization path and projected by the shared server
projection. The storyboard module is served from the Runner deployment tree,
exactly as the deployment serves it.

The assertions are presentation semantics: the ranked table is built from the
run's ``scores.csv``, the ranking sentence and counts come from its
``summary.json``, selecting a row drives the inspector, the input receptor
mounts in the shared structure panel, and the recorded search-box centre is a
focus target. Nothing here claims the docking is scientifically correct: the
values are what Vina reported. A replay bundle with a publication anchor could
not be captured because the live-test task store was not readable from the
capturing account, so this is result acceptance over the same authentic bytes,
not a ``reproduced_real_result`` replay.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from urllib.parse import unquote

import pytest
from playwright.sync_api import Page, expect

from browser_frontend_assets import result_dist
from conftest import _load_fleet_module, _upsert_task_for_user
from frontend_fixtures import project_manifest_for_serve
from frontend_fixtures.router import serve_environment

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
LIVE = ROOT / "tests" / "data" / "autodock_vina" / "live"
STORYBOARD = ROOT / "docker" / "runners" / "autodock_vina" / "tasks" / "autodock_vina" / "storyboard" / "index.js"
ORIGIN = "https://revocompute.example"
CSP = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
    "script-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:; connect-src 'self' blob:"
)


def _publish(module, tmp_path: Path) -> tuple[str, dict, Path]:
    """Publish the authentic live-run tree through the real finalize path."""
    task_id = uuid.uuid4().hex
    result_dir = tmp_path / "result"
    shutil.copytree(LIVE, result_dir)
    (result_dir / ".gitattributes").unlink()
    receptor = result_dir / "debug" / "inputs" / "receptor" / "1abc_A_B.pdb"
    _upsert_task_for_user(
        module,
        task_id,
        filename=receptor.name,
        file_path=receptor,
        result_dir=result_dir,
        username="tester",
        task_type="autodock_vina",
    )
    task = module.task_store.get_task(task_id)
    root = Path(module.app.config["storage_resolver"].get_task_root(task))
    manifest = module.task_runtime._finalize_results_manifest(
        task, execution_state="completed", finished_at=1_700_000_000
    )
    return task_id, manifest, root


def _serve(page: Page, manifest: dict, root: Path, task_id: str, logical_paths: dict[str, list[str]]) -> list[str]:
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

    page.route(f"{ORIGIN}/static/app/**", static)
    page.route(
        f"{ORIGIN}/compute/api/auth/me",
        lambda route: route.fulfill(json={"id": 1, "username": "owner", "role": "user"}),
    )
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": []}))
    serve_environment(page, ORIGIN)
    page.route(
        f"{ORIGIN}/compute/api/running/{task_id}",
        lambda route: route.fulfill(
            json={
                "task_id": task_id,
                "task_type": "autodock_vina",
                "display_name": "1abc_A_B.pdb",
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

    def logical_files(route):
        file_id = route.request.url.split(f"/results/{task_id}/files/", 1)[1].split("?", 1)[0]
        paths = logical_paths.get(file_id) or []
        if not paths:
            route.fulfill(status=404, body="")
            return
        route.fulfill(status=200, body=(root / paths[0]).read_bytes())

    def artifacts(route):
        relative = unquote(route.request.url.split(f"/results/{task_id}/artifacts/", 1)[1].split("?", 1)[0])
        candidate = root / relative
        if not candidate.is_file():
            route.fulfill(status=404, body="")
            return
        route.fulfill(status=200, body=candidate.read_bytes())

    page.route(f"{ORIGIN}/compute/api/results/{task_id}/files/**", logical_files)
    page.route(f"{ORIGIN}/compute/api/results/{task_id}/artifacts/**", artifacts)
    page.route(
        f"{ORIGIN}/compute/api/results/{task_id}/storyboard/**",
        lambda route: route.fulfill(content_type="text/javascript", body=STORYBOARD.read_text(encoding="utf-8")),
    )
    page.goto(f"{ORIGIN}/compute/results/{task_id}")


def _score_rows() -> list[dict[str, str]]:
    lines = (LIVE / "scores.csv").read_text(encoding="utf-8").strip().splitlines()
    header = lines[0].split(",")
    return [dict(zip(header, line.split(","), strict=True)) for line in lines[1:]]


def test_vina_storyboard_is_the_result_surface_over_the_published_bytes(monkeypatch, tmp_path: Path, page: Page) -> None:
    module = _load_fleet_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "autodock_vina"}
    )
    task_id, manifest, root = _publish(module, tmp_path)
    assert manifest["storyboard"]["identifier"] == "autodock-vina-result"
    logical_paths = {file_id: [entry["path"] for entry in entries] for file_id, entries in manifest["result"]["files"].items()}
    manifest = project_manifest_for_serve(manifest, task_id=task_id)

    errors: list[str] = []
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.set_viewport_size({"width": 1280, "height": 900})
    _serve(page, manifest, root, task_id, logical_paths)

    expect(page.locator(".vina-result")).to_be_visible()
    expect(page.locator('[data-vina-caveat="score"]')).to_contain_text("not measured binding free energies")

    expected = _score_rows()
    table = page.locator("table.vina-table")
    expect(table.locator("tbody tr")).to_have_count(len(expected))
    first = table.locator("tbody tr").first.locator("td").all_inner_texts()
    assert first[0] == expected[0]["ligand"]
    assert first[2] == expected[0]["affinity_kcal_mol"]
    summary = json.loads((LIVE / "summary.json").read_text())
    expect(page.locator('[data-vina="ranking"]')).to_have_text(
        f"Ranked by {summary['ranking_metric']}, lowest first, as published by the run."
    )

    # Selecting a row is the real interaction: the inspector reads the published row.
    table.locator("tbody tr").nth(1).click()
    expect(page.locator('.vina-row[aria-current="true"]')).to_have_count(1)
    expect(page.locator(".vina-inspector")).to_contain_text(expected[1]["affinity_kcal_mol"])

    # The immutable receptor snapshot mounts once in the shared structure panel.
    panel = page.locator("section.storyboard-structure-panel")
    expect(panel).to_have_attribute("data-ready", "true")
    assert page.evaluate("window.__viewerLoads")[-1] == "1abc_A_B.pdb"

    # The recorded search-box centre is a spatial fact of the run, not a binding claim.
    record = json.loads((LIVE / "vina-run.json").read_text())
    page.locator('[data-vina-focus="true"]').click()
    focused = page.evaluate("window.__viewerFocuses")
    assert focused[-1]["focusPoint"]["x"] == record["parameters"]["center_x"]
    assert focused[-1]["focusPoint"]["z"] == record["parameters"]["center_z"]

    # The pose the row names is downloadable as published.
    with page.expect_download() as download:
        page.locator('[data-vina-pose-download="true"]').click()
    assert "/files/poses?index=0" in download.value.url
    assert errors == [], errors
