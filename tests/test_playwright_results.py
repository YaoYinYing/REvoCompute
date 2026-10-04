# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""End-to-end browser behavior for the Vite Result workspace."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import result_dist

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "0123456789abcdef0123456789abcdef"
ORIGIN = "https://revocompute.example"


def _artifact(path: str, *, role: str = "artifact", capability: str = "text", size: int = 12) -> dict:
    return {
        "path": path,
        "size": size,
        "sha256": "a" * 64,
        "url": f"/compute/api/results/{TASK_ID}/artifacts/{path}",
        "media_type": "text/plain",
        "preview": "text",
        "capability": capability,
        "role": role,
    }


def _structure(path: str, *, role: str = "primary") -> dict:
    artifact = _artifact(path, role=role, capability="molecular_structure")
    artifact.update(media_type="chemical/x-pdb", preview="structure")
    return artifact


def _manifest(*, artifacts: list[dict] | None = None, status: str = "finished", outcome: str = "SUCCESS", **overrides) -> dict:
    return {
        "schema_version": 3,
        "task_id": TASK_ID,
        "task_type": "example",
        "created_at": "2026-09-29T00:00:00Z",
        "status": status,
        "terminal": True,
        "error": "Published partial evidence only" if status == "failed" else None,
        "run": {"method": {"name": "Example method", "output_summary": "Published scientific outputs"}},
        "output_check": {"state": "passed", "checks": [], "problems": []},
        "limitations": [],
        "views": [],
        "artifacts": artifacts or [],
        "result": {"files": {}},
        "storyboard": None,
        "outcome": outcome,
        "total_size": sum(item["size"] for item in artifacts or []),
        "archive": {"ready": False, "request_url": f"/compute/api/results/{TASK_ID}/archive"},
        **overrides,
    }


def _status(*, available: bool = True, terminal: bool = True, status: str = "finished") -> dict:
    return {
        "task_id": TASK_ID,
        "task_type": "example",
        "display_name": "safe result name.fasta",
        "status": status,
        "terminal": terminal,
        "result_available": available,
        "status_url": f"/compute/api/running/{TASK_ID}",
        "results_url": f"/compute/api/results/{TASK_ID}",
        "error": "Runner stopped before publishing outputs" if terminal and not available else None,
    }


def _serve_app(page: Page, *, status: dict | None = None, manifest: dict | None = None, authenticated: bool = True,
               failed_artifacts: set[str] | None = None, failed_static: set[str] | None = None) -> None:
    dist = result_dist()
    entry = json.loads((dist / ".vite" / "manifest.json").read_text(encoding="utf-8"))["index.html"]
    styles = "".join(f'<link rel="stylesheet" href="/static/app/{name}">' for name in entry.get("css", []))
    html = f'<!doctype html><html><head>{styles}<script type="module" src="/static/app/{entry["file"]}"></script></head><body><div id="app"></div></body></html>'
    page.route(f"{ORIGIN}/compute/results/*", lambda route: route.fulfill(content_type="text/html", body=html))
    page.route(f"{ORIGIN}/compute/login**", lambda route: route.fulfill(content_type="text/html", body="<p>Login</p>"))

    def static(route):
        relative = route.request.url.split("/static/app/", 1)[1].split("?", 1)[0]
        if relative in (failed_static or set()):
            route.fulfill(status=503, body="unavailable")
            return
        target = dist / relative
        route.fulfill(path=target)

    page.route(f"{ORIGIN}/static/app/**", static)
    page.route(
        f"{ORIGIN}/compute/api/auth/me",
        lambda route: route.fulfill(status=200 if authenticated else 401, json={"id": 1, "username": "owner"} if authenticated else {"error": "Authentication required"}),
    )
    page.route(f"{ORIGIN}/compute/api/running/{TASK_ID}", lambda route: route.fulfill(json=status or _status()))
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}", lambda route: route.fulfill(json=manifest or _manifest()))
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}/artifacts/**", lambda route: route.fulfill(
        status=500, json={"error": "broken"}
    ) if any(path in route.request.url for path in failed_artifacts or set()) else route.fulfill(body="artifact contents"))
    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")


def test_direct_url_refresh_reconstructs_files_and_preserves_direct_downloads(page: Page) -> None:
    files = [_artifact("models/result.txt", role="primary"), _artifact("execution/slurm.stdout", role="diagnostic")]
    _serve_app(page, manifest=_manifest(artifacts=files))
    expect(page.get_by_role("heading", name="Example method")).to_be_visible()
    expect(page.locator(".result-file-open", has_text="result.txt")).to_be_visible()
    search = page.get_by_label("Filter result artifacts")
    search.fill("stdout")
    expect(page.locator(".result-file-open", has_text="slurm.stdout")).to_be_visible()
    expect(page.locator(".result-file-open", has_text="result.txt")).to_have_count(0)
    download = page.get_by_label("Download execution/slurm.stdout")
    expect(download).to_have_attribute("href", f"/compute/api/results/{TASK_ID}/artifacts/execution/slurm.stdout?download=1")
    search.fill("")
    models = page.locator(".result-directory", has=page.get_by_text("models", exact=True))
    # The workspace remembers directory expansion from the `toggle` event, which the
    # browser dispatches asynchronously. Observe that event before re-filtering, or
    # the re-render can read the map before the collapse is recorded.
    page.evaluate("""() => {
        window.__directoryToggled = false;
        document.querySelector('.result-directory').addEventListener(
            'toggle', () => { window.__directoryToggled = true; }, { once: true });
    }""")
    models.locator("summary").click()
    page.wait_for_function("window.__directoryToggled === true")
    search.fill("stdout")
    search.fill("")
    expect(models).not_to_have_attribute("open", "")
    expect(page.locator(".result-file-open", has_text="result.txt")).to_have_attribute("aria-current", "true")
    page.reload()
    expect(page.get_by_role("heading", name="Example method")).to_be_visible()


def test_declared_zero_byte_artifact_stays_visible_and_counted(page: Page) -> None:
    files = [
        _artifact("models/result.txt", role="primary"),
        _artifact("execution/task_finished", role="diagnostic", size=0),
    ]
    _serve_app(page, manifest=_manifest(artifacts=files))
    expect(page.locator(".result-file-open", has_text="result.txt")).to_be_visible()
    marker = page.locator(".result-file-open", has_text="task_finished")
    expect(marker).to_be_visible()
    expect(marker).to_contain_text("0 B")
    summary = page.locator(".result-files > summary")
    expect(summary).to_contain_text("2 files")
    search = page.get_by_label("Filter result artifacts")
    search.fill("task_finished")
    expect(marker).to_be_visible()
    expect(page.locator(".result-file-open", has_text="result.txt")).to_have_count(0)
    expect(summary).to_contain_text("1 of 2 files")


def test_expired_session_redirects_without_requesting_concealed_result(page: Page) -> None:
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    _serve_app(page, authenticated=False)
    expect(page).to_have_url(f"{ORIGIN}/compute/login?return_to=%2Fcompute%2Fresults%2F{TASK_ID}")
    assert not any(f"/compute/api/running/{TASK_ID}" in url for url in requested)


def test_molecular_viewer_chunk_is_lazy_and_failure_isolated(page: Page) -> None:
    dist = result_dist()
    build_manifest = json.loads((dist / ".vite" / "manifest.json").read_text(encoding="utf-8"))
    result_entry = build_manifest["src/features/results/index.ts"]
    viewer_key = next(key for key in result_entry["dynamicImports"] if key.endswith("fake-molecular-viewer.ts"))
    viewer_file = build_manifest[viewer_key]["file"]
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    text, structure = _artifact("summary.txt", role="primary"), _structure("model.pdb", role="evidence")
    _serve_app(page, manifest=_manifest(artifacts=[text, structure]), failed_static={viewer_file})

    expect(page.locator(".result-preview pre")).to_have_text("artifact contents")
    assert not any(url.endswith(viewer_file) for url in requested)
    page.locator(".result-file-open", has_text="model.pdb").click()
    expect(page.locator(".result-preview .result-empty")).to_be_visible()
    expect(page.locator(".result-file-open", has_text="summary.txt")).to_be_visible()
    expect(page.get_by_label("Download model.pdb")).to_be_visible()
    assert any(url.endswith(viewer_file) for url in requested)


@pytest.mark.parametrize(
    ("task_status", "manifest", "expected"),
    [
        (_status(available=False, terminal=False, status="running"), None, "Waiting for result artifacts."),
        (_status(available=False, terminal=True, status="failed"), None, "No result artifacts were published."),
        (_status(), _manifest(), "No previewable artifact was published."),
        (_status(), _manifest(artifacts=[_artifact("partial.log", role="diagnostic")], status="failed", outcome="PARTIAL_SUCCESS"), "Published partial evidence only"),
    ],
)
def test_running_failed_empty_and_partial_states(page: Page, task_status: dict, manifest: dict | None, expected: str) -> None:
    _serve_app(page, status=task_status, manifest=manifest)
    expect(page.get_by_text(expected, exact=False)).to_be_visible()
    if task_status["terminal"] and not task_status["result_available"]:
        expect(page.get_by_text("Runner stopped before publishing outputs", exact=True)).to_be_visible()


def test_polling_stops_when_a_running_task_becomes_terminal(page: Page) -> None:
    task_status = _status(available=False, terminal=False, status="running")
    page.add_init_script("""
      window.__pollCallback = null;
      window.__clearedPolls = 0;
      window.setInterval = callback => { window.__pollCallback = callback; return 73; };
      window.clearInterval = () => { window.__clearedPolls += 1; };
    """)
    _serve_app(page, status=task_status)
    expect(page.get_by_text("Waiting for result artifacts.", exact=True)).to_be_visible()
    task_status.update(_status(available=False, terminal=True, status="failed"))
    page.evaluate("window.__pollCallback()")
    expect(page.get_by_text("Runner stopped before publishing outputs", exact=True)).to_be_visible()
    page.wait_for_function("window.__clearedPolls === 1")


def test_rail_is_non_obscuring_on_mobile_and_collapsible_on_desktop(page: Page) -> None:
    files = [_artifact("result.txt", role="primary")]
    page.set_viewport_size({"width": 1280, "height": 800})
    _serve_app(page, manifest=_manifest(artifacts=files))
    expanded = page.locator(".result-main").bounding_box()
    page.locator(".result-files > summary").click()
    expect(page.locator(".result-app")).to_have_class("result-app is-rail-collapsed")
    collapsed = page.locator(".result-main").bounding_box()
    assert expanded and collapsed and collapsed["width"] >= expanded["width"] + 200
    page.get_by_label("Open Files and diagnostics").click()
    restored = page.locator(".result-main").bounding_box()
    assert restored and abs(restored["width"] - expanded["width"]) <= 2
    page.set_viewport_size({"width": 300, "height": 700})
    expect(page.locator(".result-workspace")).to_be_visible()
    boxes = [page.locator(".result-main").bounding_box(), page.locator(".result-rail").bounding_box()]
    assert boxes[0] and boxes[1] and boxes[1]["y"] >= boxes[0]["y"] + boxes[0]["height"] - 1


def test_pagehide_preserves_bfcache_state_but_disposes_on_true_unload(page: Page) -> None:
    _serve_app(page, manifest=_manifest(artifacts=[_structure("model.pdb")]))
    expect(page.locator(".structure-host")).to_be_visible()
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }))")
    expect(page.locator(".result-app")).to_be_visible()
    assert page.evaluate("window.__viewerDisposals || 0") == 0
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))")
    expect(page.locator(".result-file-open", has_text="model.pdb")).to_be_visible()
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false }))")
    expect(page.locator(".app-outlet")).to_be_empty()
    expect(page.locator(".app-header")).to_be_visible()
    assert page.evaluate("window.__viewerDisposals") == 1


def test_structure_switch_reuses_viewer_and_latest_success_finishes_last(page: Page) -> None:
    first, second = _structure("models/first.pdb"), _structure("models/second.pdb", role="evidence")
    page.add_init_script("window.__holdStructure = 'models/first.pdb';")
    _serve_app(page, manifest=_manifest(artifacts=[first, second]))
    expect(page.locator(".structure-host")).to_be_visible()
    page.get_by_role("group", name="Structure representation").get_by_role(
        "button", name="Sticks", exact=True
    ).click()
    page.get_by_role("group", name="Structure colour").get_by_role(
        "button", name="Sequence", exact=True
    ).click()
    page.get_by_role("button", name="Dark canvas", exact=True).click()
    expect(page.locator(".structure-host")).to_have_attribute("data-theme", "dark")
    second_row = page.locator(".result-file-open", has_text="second.pdb")
    expect(second_row).to_be_visible()
    second_row.click()
    page.wait_for_function("window.__viewerLoads.includes('models/first.pdb')")
    page.evaluate("window.__releaseStructure()")
    expect(page.locator(".structure-host")).to_have_attribute("data-label", "models/second.pdb")
    expect(page.get_by_role("button", name="Sticks", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("button", name="Sequence", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("button", name="Light canvas", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.locator(".structure-host")).to_have_attribute("data-theme", "dark")
    page.set_viewport_size({"width": 300, "height": 700})
    assert page.get_by_role("group", name="Structure representation").evaluate(
        "node => node.getBoundingClientRect().right <= document.documentElement.clientWidth"
    )
    assert page.evaluate("window.__viewerMounts") == 1
    assert page.evaluate("window.__viewerLoads") == ["models/first.pdb", "models/second.pdb"]


def test_structure_controls_fullscreen_png_source_and_storyboard_reopen(page: Page) -> None:
    structure = _structure("models/model.pdb")
    logical = {"id": "structures", "name": "model.pdb", "size": 12, "media_type": "chemical/x-pdb", "role": "primary",
               "cardinality": "one", "viewer": "structure", "preview": "structure", "capability": "molecular_structure",
               "confidence_encoding": "plddt_bfactor", "url": structure["url"]}
    storyboard = {"identifier": "probe", "entrypoint": "index.js", "entrypoint_url": f"/compute/api/results/{TASK_ID}/storyboard/index.js", "requires": ["structures"], "optional": []}
    manifest = _manifest(artifacts=[structure], views=[{"id": "structure", "plugin": "structure", "title": "Structure", "role": "primary", "sources": {"structure": [structure["path"]]}}],
                         storyboard=storyboard, result={"files": {"structures": [logical]}})
    page.route(
        f"{ORIGIN}{storyboard['entrypoint_url']}",
        lambda route: route.fulfill(content_type="application/javascript", body=(
            "export default { mount(host, context) { const root=document.createElement('div'); root.className='probe-storyboard';"
            "const open=document.createElement('button'); open.textContent='Open structure'; open.onclick=()=>context.services.openFile(context.files.get('structures'));"
            "root.append(open); host.replaceChildren(root); return {destroy(){window.__storyboardDestroyed=(window.__storyboardDestroyed||0)+1;root.remove();}} } };"
        )),
    )
    _serve_app(page, manifest=manifest)
    expect(page.locator(".probe-storyboard")).to_be_visible()
    page.get_by_role("button", name="Structure", exact=True).click()
    expect(page.locator(".structure-host")).to_be_visible()
    assert page.evaluate("window.__storyboardDestroyed") == 1
    fullscreen = page.get_by_label("Enter fullscreen")
    fullscreen.click()
    page.wait_for_function("document.fullscreenElement && document.fullscreenElement.classList.contains('structure-viewport')")
    expect(page.get_by_label("Exit fullscreen")).to_be_visible()
    page.evaluate("document.exitFullscreen()")
    expect(page.get_by_label("Enter fullscreen")).to_be_visible()
    page.get_by_label("Enter fullscreen").click()
    expect(page.get_by_label("Exit fullscreen")).to_be_visible()
    page.get_by_label("Exit fullscreen").click()
    expect(page.get_by_label("Enter fullscreen")).to_be_visible()
    page.get_by_role("button", name="Save PNG", exact=True).click()
    page.wait_for_function("window.__viewerCaptures === 1")
    with page.expect_download() as source_download:
        page.get_by_role("button", name="Download", exact=True).click()
    assert source_download.value.suggested_filename
    page.get_by_role("button", name="Scientific result", exact=True).click()
    expect(page.locator(".probe-storyboard")).to_be_visible()
    assert page.evaluate("window.__viewerDisposals") == 1
    page.get_by_role("button", name="Open structure", exact=True).click()
    expect(page.locator(".structure-host")).to_be_visible()
    expect(page.get_by_role("group", name="Structure colour").get_by_role("button", name="Confidence", exact=True)).to_be_visible()
    assert page.evaluate("window.__viewerMounts") == 2


def test_preview_failure_does_not_break_other_files_or_archive(page: Page) -> None:
    broken, good = _artifact("broken.txt", role="primary"), _artifact("good.txt", role="evidence")
    archive_requests: list[str] = []
    page.route(f"{ORIGIN}/compute/api/auth/token", lambda route: route.fulfill(json={"token": "ephemeral"}))
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}/archive", lambda route: (archive_requests.append(route.request.headers.get("authorization", "")), route.fulfill(json={"ready": False})))
    _serve_app(page, manifest=_manifest(artifacts=[broken, good]), failed_artifacts={"broken.txt"})
    expect(page.get_by_text("Text preview could not be loaded.")).to_be_visible()
    page.locator(".result-file-open", has_text="good.txt").click()
    expect(page.locator(".result-preview pre")).to_have_text("artifact contents")
    page.get_by_role("button", name="Create ZIP", exact=True).click()
    expect(page.get_by_text("Archive generation requested.", exact=True)).to_be_visible()
    assert archive_requests == ["Bearer ephemeral"]
