# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for the runner-owned ColabFold result storyboard."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import install_scientific_assets
from storyboard_first_screen import assert_first_screen

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
STORYBOARD = ROOT / "docker" / "runners" / "colabfold_af2" / "storyboard" / "index.js"

FILES = {
    "structures": [
        {"id": "structures", "name": "job_unrelaxed_rank_001_model_1_seed_000.pdb", "url": "/rank1-unrelaxed"},
        {"id": "structures", "name": "job_relaxed_rank_001_model_1_seed_000.pdb", "url": "/rank1-relaxed"},
        {"id": "structures", "name": "job_unrelaxed_rank_002_model_2_seed_000.pdb", "url": "/rank2"},
    ],
    "scores": [
        {"id": "scores", "name": "job_scores_rank_001_model_1_seed_000.json", "url": "/scores/1", "ndarray_url": "/arrays/1"},
        {"id": "scores", "name": "job_scores_rank_002_model_2_seed_000.json", "url": "/scores/2", "ndarray_url": "/arrays/2"},
    ],
    "alignment": {"id": "alignment", "name": "job.a3m", "url": "/alignment"},
    "interface_scores": {"id": "interface_scores", "name": "interface_scores.json", "url": "/interface"},
}

RESPONSES = {
    "/scores/1": {"plddt": [90, 80, 70], "ptm": 0.81, "iptm": 0.72, "max_pae": 24.3, "pae": [[1, 2, 3], [2, 1, 2], [3, 2, 1]]},
    "/scores/2": {"plddt": [50, 60, 70], "ptm": 0.61, "iptm": 0.52, "pae": [[4, 5, 6], [5, 4, 5], [6, 5, 4]]},
    "/interface": {"scores_file": "job_scores_rank_001_model_1_seed_000.json", "ipsae": 0.67, "pdockq2": 0.58},
}
# The declared views the storyboard reads its vocabulary from, transcribed from
# task.yaml: the pLDDT series, the PAE matrix, and both scalar summaries.
VIEWS = [
    {
        "id": "residue_confidence",
        "plugin": "metric-series",
        "title": "Per-residue model confidence",
        "sources": {},
        "mapping": {"format": "json", "value_path": "plddt", "x_label": "Residue position", "y_label": "pLDDT",
                    "unit": "score", "direction": "higher", "y_min": 0, "y_max": 100},
    },
    {
        "id": "predicted_aligned_error",
        "plugin": "matrix",
        "title": "Predicted aligned error",
        "sources": {},
        "mapping": {"scale_min": 0, "scale_max": 31.75, "unit": "Å", "x_label": "Aligned residue", "y_label": "Scored residue"},
    },
    {
        "id": "global_confidence",
        "plugin": "scalar-summary",
        "title": "Global model confidence",
        "sources": {},
        "mapping": {"fields": [
            {"path": "ptm", "label": "pTM", "unit": "score", "direction": "higher"},
            {"path": "max_pae", "label": "Maximum PAE", "unit": "Å", "direction": "lower"},
        ]},
    },
    {
        "id": "interface_confidence",
        "plugin": "scalar-summary",
        "title": "Interface confidence",
        "sources": {},
        "mapping": {"fields": [
            {"path": "ipsae", "label": "ipSAE", "unit": "score", "direction": "higher"},
            {"path": "pdockq2", "label": "pDockQ2", "unit": "score", "direction": "higher"},
        ]},
    },
]

MOUNT = """
async (payload) => {
  const moduleUrl = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(moduleUrl);
  const opened = [];
  window.REvoDesignAuth = { authFetch: async (url) => {
    const value = url === "/alignment" ? "#2,1\\t1,2\\n>query\\nACD\\n>hit\\nA-D\\n" : payload.responses[url];
    return { ok: true, text: async () => typeof value === "string" ? value : JSON.stringify(value) };
  }};
  window.fetch = async (target) => {
    const url = new URL(target, "https://example.invalid"), key = url.searchParams.get("key");
    if (payload.delays && payload.delays[url.pathname]) await new Promise((resolve) => setTimeout(resolve, payload.delays[url.pathname]));
    const source = payload.responses[url.pathname.replace("/arrays/", "/scores/")];
    const value = source && source[key];
    if (value === undefined) return { ok: false, status: 400, json: async () => ({}) };
    const shape = Array.isArray(value) ? (Array.isArray(value[0]) ? [value.length, value[0].length] : [value.length]) : [];
    const data = shape.length === 2 ? value.flat() : shape.length === 1 ? value : [value];
    return { ok: true, status: 200, json: async () => ({ kind: "numeric", dtype: "float64", shape, key, total_elements: data.length, data }) };
  };
  const files = new Map(Object.entries(payload.files));
  const instance = await module.default.mount(document.getElementById("host"), {
    files: { get: (id) => files.get(id) || null },
    metadata: { taskType: "colabfold_af2" },
    views: payload.views || [],
    services: { openFile: (artifact) => opened.push(artifact.url), downloadFile: () => {} },
  });
  window.__colabfold = { opened, instance };
}
"""


def _mount(page: Page, *, delays: dict[str, int] | None = None) -> None:
    page.set_viewport_size({"width": 1280, "height": 1000})
    page.set_content("<div id='host'></div>")
    install_scientific_assets(page)
    page.evaluate(MOUNT, {"source": STORYBOARD.read_text(encoding="utf-8"), "files": FILES, "views": VIEWS, "responses": RESPONSES, "delays": delays or {}})


def test_colabfold_storyboard_synchronizes_ranked_confidence_and_pae(page: Page) -> None:
    _mount(page)

    candidates = page.locator(".colabfold-candidates > .candidate-open")
    expect(candidates).to_have_count(2)
    expect(candidates.nth(0)).to_have_attribute("aria-current", "true")
    assert page.locator(".scalar-grid").text_content() == (
        "pTM0.81 scoreHigher is betterMaximum PAE24.3 ÅLower is better"
        "ipSAE0.67 scoreHigher is betterpDockQ20.58 scoreHigher is better"
    )
    expect(page.locator(".colabfold-figure canvas")).to_have_attribute("role", "grid")
    assert "1.0 Å" in page.locator(".matrix-readout").text_content()
    # The header is its own table group; the selectable records are body rows.
    expect(page.locator(".entity-result-table thead tr")).to_have_count(1)
    expect(page.locator(".entity-result-table tbody tr")).to_have_count(2)
    expect(page.locator(".msa-header")).to_have_count(2)
    # The preferred relaxed rank 1 reaches the stage on mount, and the PAE matrix
    # is inside the hero beside it.
    assert page.evaluate("window.__colabfold.opened") == ["/rank1-relaxed"]
    expect(page.locator(".colabfold-stage-label")).to_have_text("job_relaxed_rank_001_model_1_seed_000.pdb")
    assert_first_screen(page, hero=".colabfold-hero", slot=".colabfold-stage", figure=".colabfold-side .colabfold-figure")

    candidates.nth(1).click()
    expect(page.locator(".scalar-grid")).to_contain_text("pTM0.61 score")
    expect(page.locator(".scalar-grid")).not_to_contain_text("ipSAE")
    expect(page.locator(".matrix-readout")).to_contain_text("4.0 Å")
    assert page.evaluate("window.__colabfold.opened") == ["/rank1-relaxed", "/rank2"]


def test_colabfold_storyboard_opens_the_preferred_relaxed_structure(page: Page) -> None:
    _mount(page)
    # The stage mounted the preferred relaxed rank 1; the button re-opens it.
    page.get_by_role("button", name="Open selected structure").click()
    assert page.evaluate("window.__colabfold.opened") == ["/rank1-relaxed", "/rank1-relaxed"]


def test_colabfold_renders_available_evidence_when_optional_fields_are_missing(page: Page) -> None:
    files = {key: value for key, value in FILES.items()}
    responses = {**RESPONSES, "/scores/1": {"plddt": [90, 80, 70], "ptm": 0.81}}
    page.set_viewport_size({"width": 1280, "height": 1000})
    page.set_content("<div id='host'></div>")
    install_scientific_assets(page)
    page.evaluate(MOUNT, {"source": STORYBOARD.read_text(encoding="utf-8"), "files": files, "views": VIEWS, "responses": responses})

    expect(page.locator(".scalar-grid")).to_contain_text("pTM0.81 score")
    expect(page.locator(".scalar-grid")).not_to_contain_text("Maximum PAE")
    expect(page.locator(".colabfold-figure")).to_be_hidden()
    expect(page.get_by_role("button", name="Open selected structure")).to_be_visible()
    # The structure stage is independent of the optional PAE evidence.
    assert page.evaluate("window.__colabfold.opened") == ["/rank1-relaxed"]


def test_colabfold_ignores_a_late_response_from_the_previous_generation(page: Page) -> None:
    _mount(page, delays={"/arrays/1": 120})
    candidates = page.locator(".candidate-open")
    candidates.nth(0).click()
    candidates.nth(1).click()

    expect(page.locator(".scalar-grid")).to_contain_text("pTM0.61 score")
    page.wait_for_timeout(180)
    expect(page.locator(".scalar-grid")).to_contain_text("pTM0.61 score")
    expect(page.locator(".matrix-readout")).to_contain_text("4.0 Å")
