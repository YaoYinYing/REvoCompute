# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the fpocket Ranked-pockets result workspace.

This does not fabricate scientific values. It runs the production normalizer over
the pinned 1SUO output, publishes the manifest through the real server
(``task_runtime._finalize_results_manifest``), and drives the built Result
workspace in Chrome. The assertions are about *presentation semantics* — the
storyboard mounts and ranks the pockets, selecting one updates the detail, the
primary entity-table still renders the pocket rows it is handed, and no view is a
runner-name special case. Nothing here asserts a pocket score is scientifically
correct: pocket values are what fpocket reported (see INTEGRATION.md).
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
RETAINED_RUN = ROOT / "tests/data/fpocket/1SUO_out"
INPUT_STRUCTURE = ROOT / "tests/data/pdb/1SUO.pdb"
ORIGIN = "https://revocompute.example"
CSP = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
    "script-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:"
)


def _write_retained_run(root: Path, count: int = 2) -> None:
    """Write a self-consistent run tree from the retained evidence set.

    The frozen fixture keeps the global descriptor source plus the per-pocket
    geometry/contact files for the selected pockets only, so the descriptor file
    is truncated to the same pockets; the production normalizer needs a tree whose
    pockets all have their files.
    """
    pockets = root / "work" / "1SUO_out" / "pockets"
    pockets.mkdir(parents=True)
    info = (RETAINED_RUN / "1SUO_info.txt").read_text(encoding="utf-8")
    kept: list[str] = []
    seen = 0
    for line in info.splitlines():
        if line.startswith("Pocket "):
            seen += 1
            if seen > count:
                break
        kept.append(line)
    (pockets.parent / "1SUO_info.txt").write_text("\n".join(kept) + "\n", encoding="utf-8")
    for name in ("pocket1_vert.pqr", "pocket1_atm.pdb", "pocket2_vert.pqr", "pocket2_atm.pdb"):
        shutil.copy(RETAINED_RUN / "pockets" / name, pockets / name)


def _build_manifest(module, tmp_path: Path) -> tuple[str, dict, Path]:
    """Publish a real fpocket manifest from the pinned run and return it."""
    task_id = uuid.uuid4().hex
    result_dir = tmp_path / "result"
    _write_retained_run(result_dir)
    shutil.copy(INPUT_STRUCTURE, result_dir / "1SUO.pdb")
    # The Server captures the submitted structure under debug/inputs/<role>/; the
    # storyboard binds its structure identity to that stable location.
    debug_input = result_dir / "debug" / "inputs" / "structure" / "1SUO.pdb"
    debug_input.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(INPUT_STRUCTURE, debug_input)
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
    """Enrich the stored manifest the way the Server does at serve time.

    Mirrors ``revocompute/routes.py``: artifact URLs, the logical-file projection
    the storyboard binds to, and the storyboard entrypoint URL.  The asset itself
    is served from the runner directory, exactly as the ``storyboard/<asset>``
    route does for a trusted local declaration.
    """
    for artifact in manifest["artifacts"]:
        path = artifact["path"]
        artifact["capability"] = artifact.get("preview") or "download_only"
        artifact["url"] = f"/compute/api/results/{task_id}/artifacts/{path}"
        if artifact["capability"] == "table":
            artifact["table_url"] = f"/compute/api/results/{task_id}/tables/{path}"
    logical_files: dict[str, list[dict]] = {}
    logical_paths: dict[str, list[str]] = {}
    for file_id, files in manifest.get("result", {}).get("files", {}).items():
        logical_paths[file_id] = [entry["path"] for entry in files]
        logical_files[file_id] = [
            {
                "id": file_id,
                "name": Path(entry["path"]).name,
                "media_type": entry["media_type"],
                "size": entry["size"],
                "role": entry["role"],
                "cardinality": entry["cardinality"],
                "viewer": entry.get("preview") or "download",
                "preview": entry.get("preview"),
                "capability": entry.get("preview") or "download_only",
                "url": f"/compute/api/results/{task_id}/files/{file_id}?index={index}",
            }
            for index, entry in enumerate(files)
        ]
    manifest["result"] = {"files": logical_files}
    manifest["_logical_paths"] = logical_paths
    if manifest.get("storyboard"):
        entrypoint = manifest["storyboard"]["entrypoint"]
        manifest["storyboard"]["entrypoint_url"] = f"/runner/storyboard/{entrypoint}"
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
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": []}))
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

    def logical_files(route):
        # /files/<logical_id>?index=<n> — where the storyboard reads the table.
        file_id = route.request.url.split(f"/results/{task_id}/files/", 1)[1].split("?", 1)[0]
        paths = manifest.get("_logical_paths", {}).get(file_id) or []
        if not paths:
            route.fulfill(status=404, body="")
            return
        calls.append({"path": paths[0], "source": "logical"})
        route.fulfill(status=200, content_type="text/csv", body=(root / paths[0]).read_text(encoding="utf-8"))

    page.route(f"{ORIGIN}/compute/api/results/{task_id}/files/**", logical_files)
    page.route(
        f"{ORIGIN}/compute/api/results/{task_id}/artifacts/**",
        lambda route: route.fulfill(status=200, body="artifact"),
    )
    page.route(
        f"{ORIGIN}/runner/storyboard/**",
        lambda route: route.fulfill(content_type="text/javascript", body=(FAMILY / "storyboard" / "index.js").read_text(encoding="utf-8")),
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

    # A storyboard is the primary interpretation: it opens on load and its ranked
    # selector renders the real normalized pockets.csv.
    expect(page.get_by_role("button", name="Scientific result")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("heading", name="fpocket pockets")).to_be_visible()
    table = page.locator("table.fpl-pockets")
    expect(table).to_be_visible()
    assert any(call["path"] == "pockets.csv" for call in calls), calls
    header = table.locator("thead th").all_inner_texts()
    assert "Pocket" in header and "Score" in header and "Druggability" in header, header
    # The rendered rows are the published pockets, in score order, with the pocket
    # identity kept distinct from the rank.
    body = table.locator("tbody tr")
    expect(body).to_have_count(len(expected_rows))
    first_row = body.first.locator("td").all_inner_texts()
    assert first_row[0] == expected_rows[0]["rank"]
    assert first_row[1] == expected_rows[0]["pocket"]

    # Selecting a pocket is the real integration boundary: the protein structure
    # mounts once in the shared panel, the pocket stays active, and the contacted
    # residues reach the molecular adapter as ONE combined selection.
    assert page.evaluate("window.__viewerMounts") is None
    page.locator(".fpl-pocket-row").first.click()
    expect(page.locator('.fpl-pocket-row[aria-current="true"]')).to_have_count(1)
    expect(page.locator(".fpl-detail")).to_contain_text(expected_rows[0]["druggability_score"])
    expect(page.locator("section.storyboard-structure-panel[data-ready='true']")).to_be_visible()
    assert page.evaluate("window.__viewerLoads")[-1] == "1SUO.pdb"
    page.get_by_role("button", name="Select contacted residues").click()
    selects = page.evaluate("window.__viewerSelects")
    assert len(selects) == 1, selects
    assert set(selects[0]["residues"]) == set(expected_rows[0]["residue_ids"].split())

    # The pocket's own geometry files remain reachable from the result: the storyboard
    # hands the contacted-atom artifact to the shared panel, which loads it.
    page.get_by_role("button", name="Open contacted atoms").click()
    page.wait_for_function("() => (window.__viewerLoads || []).includes('pocket1_atm.pdb')")
    assert page.evaluate("window.__viewerLoads")[-1] == "pocket1_atm.pdb"

    # The generic views stay reachable as the audit/fallback path.
    for title in ("Ranked pockets", "Detection summary", "Raw fpocket output"):
        expect(page.get_by_role("button", name=title, exact=True)).to_be_visible()
    page.get_by_role("button", name="Detection summary", exact=True).click()
    expect(page.get_by_role("heading", name="Detection summary")).to_be_visible()
    expect(page.locator(".result-preview-header")).to_contain_text("Detected pocket count")

    assert errors == [], errors
