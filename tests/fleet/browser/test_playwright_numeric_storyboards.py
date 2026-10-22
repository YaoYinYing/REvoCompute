# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the Task Storyboards of the numeric-sequence families.

Each case publishes the bytes a real production Runner run wrote
(``tests/data/storyboards/<task>``, captured from the deploy the evidence packets
describe) through the real server finalization path
(``task_runtime._finalize_results_manifest``), serves the projected manifest and
the Runner's own Storyboard module through the same routes the deployment uses,
and drives the built Result workspace in Chrome.

The assertions are presentation semantics: the Storyboard opens as the
scientific surface, every declared view keeps a tab, the primary view renders the
published rows where it has a table, and no console/CSP error is raised. The tab
set is read from the manifest the server produced, so this test cannot pin a
title the Runner is free to change. Nothing here claims a prediction is
scientifically correct -- the values are what the Runner published.
"""

from __future__ import annotations

import csv
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

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "data" / "storyboards"
ORIGIN = "https://revocompute.example"
CSP = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
    "script-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:"
)
# Every Task this Owner declared a Storyboard for, with the table column the
# primary entity-table view must render from the published artifact.
CASES = [
    ("esm", "esm_1v", "mean_score"),
    ("esm", "esm_msa", None),
    ("esm", "esm_extract", None),
    ("esm", "esm_if1", None),
    ("prime", "prime", "ogt"),
    ("prime", "prime_dms", "predict_score"),
    ("ppiformer", "ppiformer_ddg", "predicted_ddg_kcal_mol"),
    ("ppiformer", "ppiformer_embed", "embedding_norm"),
    ("esmdynamic", "esmdynamic", None),
    ("evosplit", "evosplit_cluster", "unsupervised_cluster"),
    ("easifa", "easifa", "site_class"),
    ("codontransformer", "codon_optimize", None),
    ("dynamicmpnn", "dynamicmpnn", None),
    ("frustrampnn", "frustrampnn", "frustration_pred"),
]
FILE_NAMES = {
    "esm_1v": "2KL8.fasta",
    "esm_msa": "2KL8.i90c75_aln.a3m",
    "esm_extract": "2KL8.fasta",
    "esm_if1": "2KL8.pdb",
    "prime": "2KL8.fasta",
    "prime_dms": "2KL8.fasta",
    "ppiformer_ddg": "complex.pdb",
    "ppiformer_embed": "complex.pdb",
    "esmdynamic": "2KL8.fasta",
    "evosplit_cluster": "minimal.a3m",
    "easifa": "2KL8.pdb",
    "codon_optimize": "minimal.fasta",
    "dynamicmpnn": "2KL8.pdb",
    "frustrampnn": "2KL8.pdb",
}


def _module(monkeypatch, tmp_path: Path, family: str):
    return _load_fleet_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": family}
    )


def _publish(module, tmp_path: Path, task: str) -> tuple[str, dict, Path]:
    """Publish the authentic captured tree through the real finalize path."""
    task_id = uuid.uuid4().hex
    result_dir = tmp_path / "result"
    shutil.copytree(FIXTURES / task, result_dir)
    # The finalized Task row names one submitted file; the Server's own copy of
    # it lives under debug/inputs/<role> and is what the manifest records.
    submitted = next((result_dir / "debug" / "inputs").rglob("*"))
    while submitted.is_dir():
        submitted = next(submitted.iterdir())
    _upsert_task_for_user(
        module,
        task_id,
        filename=submitted.name,
        file_path=submitted,
        result_dir=result_dir,
        username="tester",
        task_type=task,
    )
    task_row = module.task_store.get_task(task_id)
    root = Path(module.app.config["storage_resolver"].get_task_root(task_row))
    manifest = module.task_runtime._finalize_results_manifest(task_row, execution_state="completed", finished_at=1_700_000_000)
    return task_id, manifest, root


def _serve(page: Page, manifest: dict, root: Path, task_id: str, logical_paths: dict[str, list[str]], task: str, family: str) -> None:
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
    page.route(
        f"{ORIGIN}/compute/api/running/{task_id}",
        lambda route: route.fulfill(
            json={
                "task_id": task_id,
                "task_type": task,
                "display_name": FILE_NAMES[task],
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

    def tables(route):
        relative = unquote(route.request.url.split(f"/results/{task_id}/tables/", 1)[1].split("?", 1)[0])
        offset = int(route.request.url.split("offset=", 1)[1].split("&", 1)[0]) if "offset=" in route.request.url else 0
        limit = int(route.request.url.split("limit=", 1)[1].split("&", 1)[0]) if "limit=" in route.request.url else 100
        with (root / relative).open(newline='', encoding='utf-8') as handle:
            rows = list(csv.reader(handle))
        window = rows[1 + offset:1 + offset + limit]
        route.fulfill(json={'columns': rows[0], 'rows': window, 'offset': offset, 'limit': limit,
                            'has_more': 1 + offset + limit < len(rows)})

    def logical_files(route):
        file_id = route.request.url.split(f"/results/{task_id}/files/", 1)[1].split("?", 1)[0]
        index = int(route.request.url.split("index=", 1)[1].split("&", 1)[0]) if "index=" in route.request.url else 0
        paths = logical_paths.get(file_id) or []
        if index >= len(paths):
            route.fulfill(status=404, body="")
            return
        route.fulfill(status=200, body=(root / paths[index]).read_bytes())

    def artifacts(route):
        relative = unquote(route.request.url.split(f"/results/{task_id}/artifacts/", 1)[1].split("?", 1)[0])
        candidate = root / relative
        if not candidate.is_file():
            route.fulfill(status=404, body="")
            return
        route.fulfill(status=200, body=candidate.read_bytes())

    storyboard = ROOT / "docker" / "runners" / family / "tasks" / task / "storyboard" / "index.js"
    page.route(f"{ORIGIN}/compute/api/results/{task_id}/files/**", logical_files)
    page.route(f"{ORIGIN}/compute/api/results/{task_id}/artifacts/**", artifacts)
    page.route(f"{ORIGIN}/compute/api/results/{task_id}/tables/**", tables)
    page.route(
        f"{ORIGIN}/compute/api/results/{task_id}/storyboard/**",
        lambda route: route.fulfill(content_type="text/javascript", body=storyboard.read_text(encoding="utf-8")),
    )
    page.goto(f"{ORIGIN}/compute/results/{task_id}")


@pytest.mark.parametrize(("family", "task", "column"), CASES, ids=[case[1] for case in CASES])
def test_storyboard_is_the_scientific_surface_over_published_bytes(monkeypatch, tmp_path: Path, page: Page, family: str, task: str, column: str) -> None:
    module = _module(monkeypatch, tmp_path, family)
    task_id, manifest, root = _publish(module, tmp_path, task)
    # The finalized manifest is the Runner's own declaration, resolved against
    # the published artifacts: a missing tree or unlisted view fails here.
    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]["problems"]
    assert manifest["storyboard"] is not None, "the Task declared no Storyboard"
    logical_paths = {file_id: [entry["path"] for entry in entries] for file_id, entries in manifest["result"]["files"].items()}
    served = project_manifest_for_serve(manifest, task_id=task_id)

    errors: list[str] = []
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.set_viewport_size({"width": 1280, "height": 900})
    _serve(page, served, root, task_id, logical_paths, task, family)

    expect(page.locator(".sl-result")).to_be_visible(timeout=60_000)
    # Let the web font load before touching the tabs: the tab strip reflows
    # while it loads and the menu's click target can move under the pointer.
    page.evaluate(
        """async () => {
            await document.fonts.ready;
            await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }"""
    )
    # The Storyboard owns the primary surface; every declared view keeps a tab.
    # The tab strip lives in a collapsed menu (its buttons are not visible while
    # the menu is closed), so the declared set is read from the DOM rather than
    # through a menu click whose open state a re-render can toggle.
    tabs = page.locator(".result-view-menu .result-tab")
    expect(tabs).to_have_count(len(manifest["views"]) + 1)
    titles = tabs.evaluate_all("(nodes) => nodes.map((node) => node.textContent)")
    assert titles[0] == "Scientific result", titles
    assert titles[1:] == [view["title"] for view in manifest["views"]], titles

    if column:
        # The Storyboard opened the page, so its primary view is the mounted
        # one; the header cell comes from the published artifact, not a fixture.
        expect(page.locator(".entity-table-view table")).to_be_visible(timeout=60_000)
        expect(page.locator(".entity-table-view table th", has_text=column).first).to_be_visible()
    assert errors == [], errors
    assert page.evaluate("window.__cspViolations || []") == []
