# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""End-to-end browser behavior for the Vite Result workspace."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Page, expect
import pytest

import browser_frontend_assets
import frontend_fixtures
from browser_frontend_assets import result_dist

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "0123456789abcdef0123456789abcdef"
ORIGIN = "https://revocompute.example"

# Read a focus indicator the way a keyboard user meets it: the computed outline
# of whatever already holds focus, plus the colour it is actually drawn against.
# The ring sits outside the border box, so its neighbour is the nearest painted
# ancestor background, not the element's own fill. Focus is driven by real Tab
# presses (``_tab_to`` / ``_tab_walk``), because ``:focus-visible`` is only
# defined for keyboard-initiated focus; nothing here freezes a token or a class.
_FOCUS_JS = """
() => {
  const numbers = (value) => (value.match(/[0-9.]+/g) || []).map(Number);
  const luminance = (rgb) => {
    const channel = (c) => { c = c / 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
  };
  const contrast = (a, b) => { const la = luminance(a), lb = luminance(b); return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05); };
  const backdrop = (el) => {
    const stack = []; let node = el.parentElement;
    while (node) {
      const parts = numbers(getComputedStyle(node).backgroundColor);
      const alpha = parts.length > 3 ? parts[3] : 1;
      if (alpha > 0) { stack.push([parts.slice(0, 3), alpha]); if (alpha >= 0.999) break; }
      node = node.parentElement;
    }
    const base = numbers(getComputedStyle(document.body).backgroundColor).slice(0, 3);
    let merged = base.length === 3 ? base : [255, 255, 255];
    for (let i = stack.length - 1; i >= 0; i -= 1) {
      const [colour, alpha] = stack[i];
      merged = merged.map((value, k) => Math.round(colour[k] * alpha + value * (1 - alpha)));
    }
    return merged;
  };
  const describe = (el) => {
    if (!el) return null;
    const style = getComputedStyle(el);
    const rgb = numbers(style.outlineColor).slice(0, 3);
    const solid = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0;
    const behind = backdrop(el);
    return { tag: el.tagName, cls: String(el.className),
             outline_style: style.outlineStyle, outline_width: style.outlineWidth,
             outline_colour: style.outlineColor, solid: solid,
             focus_visible: el.matches(':focus-visible'), backdrop: behind,
             contrast: solid ? Math.round(contrast(rgb, behind) * 100) / 100 : null };
  };
  return { active: describe(document.activeElement), controls: describe };
}
"""

# The Mol* selection-controls row is fixed-width inside a clipping host. Report
# each control's reachability as the browser lays it out, and whether the row
# can be scrolled to anything the host still clips.
_CONTAINMENT_JS = """
() => {
  const host = document.querySelector('.structure-host');
  const controls = document.querySelector('.msp-selection-viewport-controls');
  if (!host || !controls) return null;
  const hostBox = host.getBoundingClientRect();
  const reachable = (el) => {
    const box = el.getBoundingClientRect();
    if (box.left >= hostBox.left - 1 && box.right <= hostBox.right + 1) return true;
    const row = el.parentElement;
    return Boolean(row && row.scrollWidth > row.clientWidth + 1 && getComputedStyle(row).overflowX === 'auto');
  };
  const controlsBox = controls.getBoundingClientRect();
  return {
    host_width: Math.round(hostBox.width),
    controls_width: Math.round(controlsBox.width),
    overhang: Math.round(controlsBox.right - hostBox.right),
    children: Array.from(controls.querySelectorAll('.msp-flex-row > *'))
      .map((el) => ({ cls: String(el.className).slice(0, 60), reachable: reachable(el) })),
    document_overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
}
"""


def _tab_to(page: Page, selector: str, *, limit: int = 25) -> None:
    """Focus ``selector`` the way a keyboard user does, with real Tab presses.

    ``:focus-visible`` only matches keyboard-initiated focus, and a programmatic
    ``el.focus()`` on a plain button does not set it, so the walk is the only
    faithful way to reach the ring the user actually sees.
    """
    for _ in range(limit):
        page.keyboard.press("Tab")
        if page.evaluate("(sel) => Boolean(document.activeElement && document.activeElement.matches(sel))", selector):
            return
    raise AssertionError(f"{selector} was not reachable by Tab")


def _tab_walk(page: Page, *, limit: int = 60) -> list[dict]:
    """Every focus indicator reached by pressing Tab until the cycle closes."""
    walk, seen = [], set()
    for _ in range(limit):
        page.keyboard.press("Tab")
        reading = page.evaluate(_FOCUS_JS)["active"]
        if reading["tag"] == "BODY":
            break
        walk.append(reading)
        token = (reading["tag"], reading["cls"], reading["outline_colour"])
        if token in seen:
            break
        seen.add(token)
    return walk


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


# A synthetic table-capable matrix artifact with the mapping vocabulary a declared
# `matrix` view carries: a label column, position axes, a unit, and a diverging scale.
MATRIX_COLUMNS = ["position", "1", "2", "3"]
MATRIX_ROWS = [["1", "0", "1.25", "-2.5"], ["2", "1.25", "0", "3.75"], ["3", "-2.5", "3.75", "0"]]


def _matrix_artifact(path: str = "couplings/scores.csv", *, role: str = "primary") -> dict:
    artifact = _artifact(path, role=role, capability="table")
    artifact.update(media_type="text/csv", preview="table",
                    table_url=f"{ORIGIN}/compute/api/results/{TASK_ID}/tables/{path}")
    return artifact


def _matrix_view(artifact: dict) -> dict:
    return {
        "id": "scores", "plugin": "matrix", "role": "primary", "title": "Coupling strengths",
        "description": "Frobenius norms of residue-pair couplings.",
        "sources": {"matrices": [artifact["path"]]},
        "mapping": {"format": "csv", "row_labels_column": "position", "x_label": "Alignment position",
                    "y_label": "Alignment position", "unit": "coupling score", "direction": "higher",
                    "scale": "diverging", "center": 0},
    }


def _manifest(*, artifacts: list[dict] | None = None, status: str = "finished", outcome: str = "SUCCESS", **overrides) -> dict:
    return {
        "schema_version": 3,
        "task_id": TASK_ID,
        "task_type": "demo",
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
        "task_type": "demo",
        "display_name": "safe result name.fasta",
        "status": status,
        "terminal": terminal,
        "result_available": available,
        "status_url": f"/compute/api/running/{TASK_ID}",
        "results_url": f"/compute/api/results/{TASK_ID}",
        "error": "Runner stopped before publishing outputs" if terminal and not available else None,
    }


def _serve_app(page: Page, *, status: dict | None = None, manifest: dict | None = None, authenticated: bool = True,
               failed_artifacts: set[str] | None = None, failed_static: set[str] | None = None,
               table_page: int | None = None, table_columns: list[str] | None = None,
               table_rows: list[list[str]] | None = None, tables_enabled: bool = False) -> None:
    dist = result_dist()
    entry = json.loads((dist / ".vite" / "manifest.json").read_text(encoding="utf-8"))["index.html"]
    styles = "".join(f'<link rel="stylesheet" href="/static/app/{name}">' for name in entry.get("css", []))
    html = f'<!doctype html><html><head>{styles}<script type="module" src="/static/app/{entry["file"]}"></script></head><body><div id="app"></div></body></html>'
    page.route(f"{ORIGIN}/compute/results/*", lambda route: route.fulfill(content_type="text/html", body=html))
    page.route(f"{ORIGIN}/compute/login**", lambda route: route.fulfill(content_type="text/html", body="<p>Login</p>"))
    # The same bundle at a non-result route: the shell is identical, so a control's
    # focus indicator can be read there as the reference the result route must match.
    page.route(f"{ORIGIN}/compute/dashboard", lambda route: route.fulfill(content_type="text/html", body=html))

    def static(route):
        relative = route.request.url.split("/static/app/", 1)[1].split("?", 1)[0]
        if relative in (failed_static or set()):
            route.fulfill(status=503, body="unavailable")
            return
        target = dist / relative
        route.fulfill(path=target)

    # `tables_enabled` serves the bounded table endpoint; when the fixture supplies no
    # rows it answers an empty page, which is the "no table data" path the view falls back on.
    def tables(route):
        if not tables_enabled or table_rows is None:
            route.fulfill(status=404, json={"error": "Table artifact not found"})
            return
        query = parse_qs(urlsplit(route.request.url).query)
        offset, requested = int(query.get("offset", ["0"])[0]), int(query.get("limit", ["500"])[0])
        limit = min(requested, table_page) if table_page else requested
        rows = table_rows[offset:offset + limit]
        route.fulfill(json={"columns": table_columns, "rows": rows, "offset": offset, "limit": limit,
                            "has_more": offset + len(rows) < len(table_rows)})

    page.route(f"{ORIGIN}/static/app/**", static)
    page.route(
        f"{ORIGIN}/compute/api/auth/me",
        lambda route: route.fulfill(status=200 if authenticated else 401, json={"id": 1, "username": "owner"} if authenticated else {"error": "Authentication required"}),
    )
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": []}))
    page.route(f"{ORIGIN}/compute/api/running/{TASK_ID}", lambda route: route.fulfill(json=status or _status()))
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}", lambda route: route.fulfill(json=manifest or _manifest()))
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}/tables/**", tables)
    page.route(
        f"{ORIGIN}/compute/api/results/{TASK_ID}/artifacts/**",
        lambda route: route.fulfill(status=500, json={"error": "broken"})
        if any(path in route.request.url for path in failed_artifacts or set())
        else route.fulfill(body="artifact contents"),
    )
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


def test_declared_matrix_view_renders_a_diverging_pair_matrix_with_paging_and_fallback(page: Page) -> None:
    matrix = _matrix_artifact()
    other = _artifact("summary.txt", role="evidence")
    manifest = _manifest(artifacts=[matrix, other], views=[_matrix_view(matrix)])
    _serve_app(page, manifest=manifest, tables_enabled=True, table_page=2, table_columns=MATRIX_COLUMNS, table_rows=MATRIX_ROWS)
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()
    expect(page.locator(".result-preview table")).to_have_count(0)
    expect(page.get_by_role("heading", name="Coupling strengths")).to_be_visible()
    titles = page.locator(".pair-matrix-title").all_inner_texts()
    assert "Alignment position" in titles
    assert any("coupling score" in title for title in titles)
    legend = page.locator(".pair-matrix-label").all_inner_texts()
    assert "-3.75" in legend and "3.75" in legend and "0.00" in legend
    canvas = page.locator(".pair-matrix-view canvas")
    canvas.press("ArrowRight")
    expect(page.locator(".pair-matrix-readout")).to_contain_text("1.25")
    canvas.press("ArrowRight")
    expect(page.locator(".pair-matrix-readout")).to_contain_text("-2.50")
    expect(page.locator(".pair-matrix-readout")).to_contain_text("coupling score")
    # The ramp is resolved per draw, and the theme observer repaints the matrix. Prove
    # a repaint actually happened: the canvas pixels must change once the dark ramp is
    # in effect. Visibility alone is theme-independent and would assert nothing.
    sign = "() => document.querySelector('.pair-matrix-view canvas').toDataURL()"
    light_pixels = page.evaluate(sign)
    page.evaluate("() => { document.documentElement.dataset.theme = 'dark'; }")
    deadline = time.monotonic() + 5
    dark_pixels = light_pixels
    while time.monotonic() < deadline and dark_pixels == light_pixels:
        page.wait_for_timeout(50)
        dark_pixels = page.evaluate(sign)
    assert dark_pixels != light_pixels, "matrix did not repaint for the dark theme"
    expect(page.locator(".pair-matrix-readout")).to_contain_text("-2.50")
    page.evaluate("() => { document.documentElement.dataset.theme = 'light'; }")
    download = page.locator(".result-preview-header").get_by_role("link", name="Download scores.csv")
    expect(download).to_be_visible()
    expect(download).to_have_attribute("href", matrix["url"] + "?download=1")

    # Without any server table page the same view falls back to the generic table
    # renderer with the reason stated: the declared view keeps its own title, and the
    # artifact stays downloadable.
    second_manifest = _manifest(artifacts=[matrix], views=[_matrix_view(matrix)])
    _serve_app(page, manifest=second_manifest, tables_enabled=True, table_columns=MATRIX_COLUMNS, table_rows=[])
    expect(page.locator(".result-preview table")).to_be_visible()
    expect(page.locator(".pair-matrix-view")).to_have_count(0)
    expect(page.get_by_text("View shown as a plain artifact instead:", exact=False)).to_be_visible()
    expect(page.get_by_role("heading", name="Coupling strengths")).to_be_visible()
    expect(page.locator(".result-preview-header")).to_contain_text("Frobenius norms of residue-pair couplings.")
    expect(page.locator(".pair-matrix-view canvas")).to_have_count(0)
    expect(page.locator(".result-preview-header").get_by_role("link", name="Download scores.csv")).to_be_visible()


def test_unregistered_view_plugin_keeps_its_declared_title_and_tears_down_the_matrix(page: Page) -> None:
    matrix = _matrix_artifact()
    entity = {"id": "pairs", "plugin": "entity-table", "role": "evidence", "title": "Ranked pairs",
              "description": "Pairs ordered by coupling strength.",
              "sources": {"table": [matrix["path"]]}, "mapping": {"key_columns": ["position"]}}
    manifest = _manifest(artifacts=[matrix], views=[_matrix_view(matrix), entity])
    _serve_app(page, manifest=manifest, tables_enabled=True, table_columns=MATRIX_COLUMNS, table_rows=MATRIX_ROWS)
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()
    page.get_by_role("button", name="Ranked pairs", exact=True).click()
    expect(page.get_by_role("heading", name="Ranked pairs")).to_be_visible()
    # The previous matrix renderer is torn down, so it no longer repaints on a theme change.
    expect(page.locator(".pair-matrix-view")).to_have_count(0)
    page.evaluate("() => { document.documentElement.dataset.theme = 'dark'; }")
    expect(page.locator(".pair-matrix-view")).to_have_count(0)


def test_tabs_switch_between_declared_views_and_unavailable_sources_are_isolated(page: Page) -> None:
    matrix = _matrix_artifact()
    table = _artifact("pairs.tsv", role="evidence", capability="table")
    table.update(media_type="text/tab-separated-values", preview="table")
    entity = {"id": "pairs", "plugin": "entity-table", "role": "evidence", "title": "Ranked pairs",
              "description": "Residue pairs ordered by coupling strength.",
              "sources": {"table": [table["path"]]}, "mapping": {"key_columns": ["i", "j"]}}
    manifest = _manifest(artifacts=[matrix, table], views=[_matrix_view(matrix), entity])
    _serve_app(page, manifest=manifest, tables_enabled=True, table_columns=MATRIX_COLUMNS, table_rows=MATRIX_ROWS)
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()
    page.get_by_role("button", name="Ranked pairs", exact=True).click()
    expect(page.locator(".result-preview table")).to_be_visible()
    expect(page.locator(".pair-matrix-view")).to_have_count(0)
    expect(page.get_by_role("heading", name="Ranked pairs")).to_be_visible()
    expect(page.locator(".result-preview-header")).to_contain_text("Residue pairs ordered by coupling strength.")
    page.get_by_role("button", name="Coupling strengths", exact=True).click()
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()


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


def test_storyboard_context_exposes_declared_views_and_navigates_through_openView(page: Page) -> None:
    matrix = _matrix_artifact()
    view = _matrix_view(matrix)
    storyboard = {"identifier": "probe", "entrypoint": "index.js",
                  "entrypoint_url": f"/compute/api/results/{TASK_ID}/storyboard/index.js",
                  "requires": [], "optional": []}
    manifest = _manifest(artifacts=[matrix], views=[view], storyboard=storyboard)
    page.route(f"{ORIGIN}{storyboard['entrypoint_url']}", lambda route: route.fulfill(
        content_type="application/javascript",
        body=("export default { mount(host, context) { const root=document.createElement('div'); root.className='probe-storyboard';"
              "const ids = context.views.map((view) => view.id).join(',');"
              "const button=document.createElement('button'); button.textContent='Open '+ids;"
              "button.onclick=()=>context.services.openView(context.views[0].id);"
              "root.append(button); host.replaceChildren(root); return {destroy(){root.remove();}} } };"),
    ))
    _serve_app(page, manifest=manifest, tables_enabled=True, table_columns=MATRIX_COLUMNS, table_rows=MATRIX_ROWS)
    expect(page.locator(".probe-storyboard")).to_be_visible()
    page.get_by_role("button", name="Open scores", exact=True).click()
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()
    expect(page.locator(".probe-storyboard")).to_have_count(0)


def test_preview_failure_does_not_break_other_files_or_archive(page: Page) -> None:
    broken, good = _artifact("broken.txt", role="primary"), _artifact("good.txt", role="evidence")
    archive_requests: list[str] = []
    page.route(f"{ORIGIN}/compute/api/auth/token", lambda route: route.fulfill(json={"token": "ephemeral"}))
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}/archive", lambda route: (archive_requests.append(route.request.headers.get("authorization", "")), route.fulfill(json={"ready": False})))
    _serve_app(page, manifest=_manifest(artifacts=[broken, good]), failed_artifacts={"broken.txt"})
    expect(page.get_by_text("Text preview could not be loaded.")).to_be_visible()
    page.locator(".result-file-open", has_text="good.txt").click()
    expect(page.locator(".result-preview pre")).to_have_text("artifact contents")
    with page.expect_response(f"{ORIGIN}/compute/api/results/{TASK_ID}/archive"):
        page.get_by_role("button", name="Prepare full-result ZIP", exact=True).click()
    expect(page.get_by_text("Preparing full-result ZIP…", exact=True).first).to_be_visible()
    assert archive_requests == ["Bearer ephemeral"]


def _ring(reading: dict) -> tuple:
    """The observable ring: what the browser paints, not a token or class."""
    return (reading["outline_style"], reading["outline_width"], reading["outline_colour"])


def test_shell_focus_ring_survives_a_result_route_and_every_indicator_meets_contrast(page: Page) -> None:
    """The result sheet must not replace the shell's focus ring, and every focus
    indicator on a result route must reach WCAG 1.4.11's 3:1 non-text contrast.

    Focus is driven by real Tab presses, so each reading is the ring the browser
    shows a keyboard user rather than the result of a script-initiated focus.
    The same shell control's ring on a non-result route is the reference the
    result route must match: the defect is a cascade collision, and a frozen
    token or class name could not tell a collision from a missing style.
    """
    _serve_app(page, manifest=_manifest(artifacts=[_artifact("summary.txt", role="primary")]))
    expect(page.locator(".result-app")).to_be_visible()

    for theme in ("light", "dark"):
        page.evaluate("theme => { document.documentElement.dataset.theme = theme; }", theme)
        _tab_to(page, ".app-brand")
        on_result = page.evaluate(_FOCUS_JS)["active"]
        page.goto(f"{ORIGIN}/compute/dashboard")
        expect(page.locator(".app-brand")).to_be_visible()
        page.evaluate("theme => { document.documentElement.dataset.theme = theme; }", theme)
        _tab_to(page, ".app-brand")
        off_result = page.evaluate(_FOCUS_JS)["active"]
        # The non-result route is the reference: a keyboard ring that is really shown.
        assert off_result["focus_visible"] and off_result["solid"], off_result
        assert (on_result["focus_visible"], _ring(on_result)) == (
            off_result["focus_visible"], _ring(off_result),
        ), f"a shell control lost its ring on a result route ({theme}): {on_result} vs {off_result}"

        page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")
        expect(page.locator(".result-app")).to_be_visible()
        page.evaluate("theme => { document.documentElement.dataset.theme = theme; }", theme)
        walk = _tab_walk(page)
        assert len(walk) >= 5, walk
        assert any(reading["cls"].startswith("app-brand") for reading in walk), walk
        for indicator in walk:
            assert indicator["focus_visible"], indicator
            assert indicator["solid"] and float(indicator["outline_width"].rstrip("px")) > 0, indicator
            assert indicator["contrast"] is not None and indicator["contrast"] >= 3.0, indicator


def test_molstar_selection_controls_stay_reachable_at_mobile_width(page: Page, monkeypatch) -> None:
    """The Mol* selection-controls row must not be clipped unreachably at 320px.

    Read from the browser: every control in the row is inside the structure
    host's box, or the row overflows it as a scrollable region that can reach
    it; and the document still does not scroll sideways.

    This case needs the real production bundle, because the Mol* selection
    controls are chunk markup the fixture-viewer double cannot lay out at all.
    The stand-in is installed through ``monkeypatch`` so it is undone when the
    case ends: a process-global left pinned would serve every later browser case
    whatever bundle was last built on disk, which is not the bundle under test.
    """
    for width, height in ((320, 900), (768, 900), (1280, 900)):
        page.set_viewport_size({"width": width, "height": height})
        # The real production bundle: the Mol* selection controls are chunk
        # markup, so the fixture-viewer double cannot lay them out at all.
        monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", ROOT / "frontend" / "dist")
        frontend_fixtures.mount_scenario(page, frontend_fixtures.structure_scenario())
        page.goto(f"{frontend_fixtures.DEFAULT_ORIGIN}/compute/results/{frontend_fixtures.DEFAULT_TASK_ID}")
        page.locator(".msp-selection-viewport-controls").first.wait_for(timeout=90_000)
        page.wait_for_timeout(1500)
        reading = page.evaluate(_CONTAINMENT_JS)
        assert reading is not None, f"no selection controls were rendered at {width}px"
        assert reading["children"], reading
        assert all(child["reachable"] for child in reading["children"]), reading
        assert reading["overhang"] <= 0 or reading["controls_width"] <= reading["host_width"] + 1, reading
        assert reading["document_overflow"] <= 0, reading
