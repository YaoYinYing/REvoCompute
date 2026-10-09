# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance against a REAL GREMLIN_LH scientific-golden ResultManifest.

This test does not fabricate a manifest: it serves the exact ResultManifest and
the exact artifacts a real Slurm+Apptainer run on the 2KL8 scientific golden case
produced (staged under ``/var/tmp/glh-accept2kl8``), projected through the same
serve-time enrichment the Server applies (per-artifact
``url``/``table_url``/``ndarray_url`` and the per-logical-file projection), and
drives the built Result workspace in Chrome.

The 2KL8 case is the scientific golden case (6 rows x 79 columns at the pinned
upstream profile). The tiny 8x8 ``gremlin_lh_tiny.a3m`` is a separate
runtime/smoke case and must not be presented here. This test proves the declared
``matrix`` primitive, the storyboard narrative (including the
``columns_excluded_by_gap_cutoff`` metric), the ranked-pairs table, the alignment
section, and the artifact-role grouping against real data.
"""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import result_dist
from frontend_fixtures import project_manifest_for_serve

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
# The golden case is a real production run, not a fixture: its manifest,
# artifacts, and storyboard are staged by whoever took the receipt. Point
# ``REVOCOMPUTE_GREMLIN_STAGE`` at that directory to run this test; when it is
# absent the case is skipped rather than fabricated, because a synthetic copy
# would no longer prove what this test exists to prove.
STAGE = Path(os.environ.get("REVOCOMPUTE_GREMLIN_STAGE", "/var/tmp/glh-accept2kl8"))
SHOTS = STAGE / "shots"
MANIFEST_PATH = STAGE / "manifest.json"
STORYBOARD_PATH = STAGE / "storyboard-index.js"
TASK_ID = "5cffb82db52978a42508a79794df703f"
ORIGIN = "https://revocompute.example"

if not MANIFEST_PATH.is_file():
    pytest.skip(
        f"no staged GREMLIN_LH golden run at {STAGE} (set REVOCOMPUTE_GREMLIN_STAGE)",
        allow_module_level=True,
    )

# The document CSP the Server emits (revocompute/app.py) governs the whole flow.
CSP = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
    "script-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:"
)

def _projected_manifest() -> dict:
    """The real staged manifest, enriched exactly as the Server serves it.

    Delegates to the one projection implementation the result route itself uses
    (``revocompute.result_projection`` through the shared
    ``project_manifest_for_serve``), so this test cannot drift from the served
    body it exists to drive.
    """
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["task_id"] == TASK_ID, "Staged manifest is not the scientific-golden run"
    inputs = {item["path"] for item in manifest["run"]["inputs"]}
    assert "2KL8.i90c75_aln.a3m" in inputs, f"Golden browser case is not 2KL8: {inputs}"
    assert "gremlin_lh_tiny.a3m" not in inputs, "The tiny smoke case must not back the golden browser test"
    return project_manifest_for_serve(manifest, task_id=TASK_ID)


def _csv_rows(relative_path: str) -> list[list[str]]:
    delimiter = "\t" if relative_path.lower().endswith(".tsv") else ","
    with (STAGE / relative_path).open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.reader(handle, delimiter=delimiter)]


def _status() -> dict:
    return {
        "task_id": TASK_ID,
        "task_type": "gremlin_lh_fit",
        "display_name": "2KL8.i90c75_aln.a3m",
        "status": "finished",
        "terminal": True,
        "result_available": True,
        "status_url": f"/compute/api/running/{TASK_ID}",
        "results_url": f"/compute/api/results/{TASK_ID}",
        "error": None,
    }


def _serve(page: Page, manifest: dict, *, matrix_page: int = 3) -> dict:
    """Serve the built frontend plus the real manifest/artifacts/storyboard."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    staged_files = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["result"]["files"]
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
        lambda route: route.fulfill(
            content_type="text/html", headers={"Content-Security-Policy": CSP}, body=html
        ),
    )
    page.route(f"{ORIGIN}/compute/login**", lambda route: route.fulfill(content_type="text/html", body="<p>Login</p>"))

    def static(route):
        relative = route.request.url.split("/static/app/", 1)[1].split("?", 1)[0]
        route.fulfill(path=dist / relative)

    table_requests: list[dict] = []
    storyboard_requests: list[str] = []

    def tables(route):
        parts = urlsplit(route.request.url)
        relative = unquote(parts.path.split(f"/results/{TASK_ID}/tables/", 1)[1])
        query = parse_qs(parts.query)
        offset = int(query.get("offset", ["0"])[0])
        requested = int(query.get("limit", ["100"])[0])
        is_matrix = query.get("matrix", ["0"])[0] == "1"
        # The Server caps a page at 500 (matrix) / its own bounds; this harness
        # additionally caps matrix pages small so the renderer's paging loop is
        # genuinely exercised instead of satisfied by one short page.
        limit = min(requested, matrix_page) if is_matrix else requested
        rows = _csv_rows(relative)
        table_requests.append({"path": relative, "offset": offset, "limit": requested, "matrix": is_matrix,
                               "columns": len(rows[0]) if rows else 0})
        columns, body = (rows[0], rows[1:]) if rows else ([], [])
        page_rows = body[offset:offset + limit]
        route.fulfill(json={
            "columns": columns,
            "rows": page_rows,
            "offset": offset,
            "limit": len(page_rows),
            "has_more": offset + len(page_rows) < len(body),
        })

    def artifacts(route):
        relative = unquote(urlsplit(route.request.url).path.split(f"/results/{TASK_ID}/artifacts/", 1)[1])
        route.fulfill(path=STAGE / relative)

    staged = staged_files

    def logical(route):
        parts = urlsplit(route.request.url)
        file_id = parts.path.split(f"/results/{TASK_ID}/files/", 1)[1].split("/", 1)[0]
        index = int(parse_qs(parts.query).get("index", ["0"])[0])
        path = staged[file_id][index]["path"]
        route.fulfill(path=STAGE / path)

    def storyboard(route):
        storyboard_requests.append(route.request.url)
        route.fulfill(content_type="application/javascript", body=STORYBOARD_PATH.read_text(encoding="utf-8"))

    page.route(f"{ORIGIN}/static/app/**", static)
    page.route(
        f"{ORIGIN}/compute/api/auth/me",
        lambda route: route.fulfill(json={"id": 1, "username": "owner", "role": "user"}),
    )
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": []}))
    page.route(f"{ORIGIN}/compute/api/running/{TASK_ID}", lambda route: route.fulfill(json=_status()))
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}", lambda route: route.fulfill(json=manifest))
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}/tables/**", tables)
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}/artifacts/**", artifacts)
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}/files/**", logical)
    page.route(f"{ORIGIN}/compute/api/results/{TASK_ID}/storyboard/**", storyboard)
    return {"tables": table_requests, "storyboard": storyboard_requests}


def _collect_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda message: errors.append(f"console.{message.type}: {message.text}")
            if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    return errors


def test_gremlin_lh_golden_result_acceptance(page: Page) -> None:
    manifest = _projected_manifest()
    errors = _collect_errors(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    # Deterministic light theme: the workspace applies storedTheme() at startup.
    page.add_init_script("localStorage.setItem('revocompute-theme', 'light');")
    calls = _serve(page, manifest)
    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")

    # ── 3. THE STORYBOARD LOADS ───────────────────────────────────────────────
    # The manifest declares a storyboard, so it opens the page. It mounts the real
    # storyboard-index.js, reads statistics/metadata over the logical-file URLs,
    # and renders its question-ordered narrative.
    # (The header h1 carries the same method name, so target the storyboard's own h2.)
    expect(page.locator(".glh-result h2")).to_have_text("GREMLIN_LH Potts model")
    for heading in (
        "What alignment was modelled?",
        "How much independent evolutionary information was present?",
        "What model was fit?",
        "What coupling landscape was inferred?",
        "Which residue pairs carry the strongest statistical coupling?",
        "What model and provenance artifacts are available for downstream analysis?",
    ):
        expect(page.get_by_role("heading", name=heading)).to_be_visible()
    assert calls["storyboard"], "Storyboard entrypoint was never imported"

    # The renamed wsA statistic reached the real storyboard narrative.
    expect(page.get_by_text("Columns excluded from weighting", exact=True)).to_be_visible()
    expect(page.get_by_text("3 positions", exact=True)).to_be_visible()
    expect(page.get_by_text("Effective sequence count (Neff)", exact=True)).to_be_visible()
    # Provenance actions resolved against the real logical-file projection.
    expect(page.get_by_role("button", name="Open", exact=True)).to_have_count(5)
    expect(page.get_by_role("button", name="Download", exact=True)).to_have_count(1)
    expect(page.locator(".glh-unavailable")).to_have_count(0)
    expect(page.locator(".result-empty")).to_have_count(0)

    page.screenshot(path=str(SHOTS / "storyboard-light.png"))
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    expect(page.locator(".glh-result h2")).to_have_text("GREMLIN_LH Potts model")
    page.screenshot(path=str(SHOTS / "storyboard-dark.png"))
    page.evaluate("document.documentElement.dataset.theme = 'light'")

    # ── 1. THE MATRIX IS A MATRIX ─────────────────────────────────────────────
    page.get_by_role("button", name="Coupling strength (raw Frobenius)", exact=True).click()
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()
    expect(page.locator(".result-preview table")).to_have_count(0)
    expect(page.locator(".result-empty")).to_have_count(0)
    expect(page.get_by_text("View shown as a plain artifact instead", exact=False)).to_have_count(0)
    expect(page.get_by_role("heading", name="Coupling strength (raw Frobenius)")).to_be_visible()
    # The renderer read the REAL csv through the paged table endpoint.
    raw_calls = [call for call in calls["tables"] if call["path"] == "couplings/raw_scores.csv"]
    assert raw_calls, "The matrix renderer never queried the server table endpoint"
    assert all(call["matrix"] for call in raw_calls), "Matrix pages were not requested with matrix=1"
    assert raw_calls[0]["columns"] == 80, f"Expected 80 columns, saw {raw_calls[0]['columns']}"
    assert len({call["offset"] for call in raw_calls}) >= 2, "The paging loop never advanced past the first page"
    assert raw_calls[-1]["offset"] > 0
    axes = page.locator(".pair-matrix-title").all_inner_texts()
    assert "Alignment position (one-based)" in axes
    assert any("coupling score" in title for title in axes)
    # The raw matrix is a Frobenius norm (every entry >= 0), so its legend must
    # read as a sequential low→high scale, never a signed diverging one.
    assert any("(low → high)" in title for title in axes), axes
    assert not any("(negative → positive)" in title for title in axes), axes

    page.screenshot(path=str(SHOTS / "matrix-light.png"))
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()
    page.screenshot(path=str(SHOTS / "matrix-dark.png"))
    page.evaluate("document.documentElement.dataset.theme = 'light'")

    # ── 2. THE APC MATRIX ALSO RENDERS AS A MATRIX ────────────────────────────
    page.get_by_role("button", name="Coupling strength (average-product corrected)", exact=True).click()
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()
    expect(page.locator(".result-preview table")).to_have_count(0)
    expect(page.get_by_role("heading", name="Coupling strength (average-product corrected)")).to_be_visible()
    apc_calls = [call for call in calls["tables"] if call["path"] == "couplings/apc_scores.csv"]
    assert apc_calls and apc_calls[0]["columns"] == 80
    # APC scores are signed after the correction, so this view keeps a diverging
    # scale centred at zero — the opposite of the raw view's sequential scale.
    expect(page.locator(".pair-matrix-title", has_text="(negative → positive)")).to_be_visible()
    apc_titles = page.locator(".pair-matrix-title").all_inner_texts()
    assert not any("(low → high)" in title for title in apc_titles), apc_titles

    # Narrow viewport screenshot of the matrix view.
    page.set_viewport_size({"width": 420, "height": 820})
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()
    page.screenshot(path=str(SHOTS / "matrix-narrow.png"))
    page.set_viewport_size({"width": 420, "height": 820})
    page.get_by_role("button", name="Scientific result", exact=True).click()
    expect(page.locator(".glh-result h2")).to_have_text("GREMLIN_LH Potts model")
    page.screenshot(path=str(SHOTS / "storyboard-narrow.png"))
    page.set_viewport_size({"width": 1280, "height": 900})

    # ── 4. ARTIFACT ROLES ARE SANE ────────────────────────────────────────────
    # task_finished is the runner's completion sentinel, never a published artifact.
    assert not any(artifact["path"] == "task_finished" for artifact in manifest["artifacts"])
    count = page.get_by_text("task_finished", exact=False).count()
    assert count == 0, "task_finished is rendered in the Files rail"

    # The "Other files" bucket holds only the role=artifact input query, never a
    # scientific output.
    other = page.locator(".result-file-group", has=page.get_by_role("heading", name="Other files", exact=True))
    expect(other).to_be_visible()
    other_files = other.locator(".result-file-open").all_inner_texts()
    assert [name.split("\n")[0] for name in other_files] == ["query.fasta"], other_files

    scientific_outputs = {
        "raw_scores.csv", "apc_scores.csv", "pairwise_scores.tsv", "profile.tsv",
        "statistics.json", "metadata.json", "summary.json", "gremlin_mrf.npz",
        "filtered_alignment.a3m", "sequence_weights.tsv", "sequence_scores.tsv",
        "training_history.csv", "coupling_apc.png",
    }
    other_names = {name.split("\n")[0] for name in other_files}
    assert not (other_names & scientific_outputs), f"Scientific outputs fell into 'Other files': {other_names & scientific_outputs}"

    # The role groups the Server projects are all present for this run.
    group_labels = page.locator(".result-file-group h3").all_inner_texts()
    assert group_labels == ["Results", "Supporting files", "Diagnostics", "Other files"], group_labels
    results_group = page.locator(".result-file-group", has=page.get_by_role("heading", name="Results", exact=True))
    assert "raw_scores.csv" in results_group.locator(".result-file-open").all_inner_texts()[0]

    # ── 5. NO CONSOLE / CSP ERRORS ────────────────────────────────────────────
    assert errors == [], errors
