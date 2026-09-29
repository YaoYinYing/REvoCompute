# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for the exact Foundry RF3 seed/sample contract."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import install_scientific_assets

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]

MOUNT = """
async (payload) => {
  const url = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(url);
  const requests = [], opened = [], downloaded = [];
  window.REvoDesignAuth = { authFetch: async (target) => {
    requests.push(target);
    if (payload.delays && payload.delays[target]) await new Promise((resolve) => setTimeout(resolve, payload.delays[target]));
    const value = payload.responses[target];
    return { ok: value !== undefined, json: async () => value, text: async () => String(value) };
  }};
  window.fetch = window.REvoDesignAuth.authFetch;
  const files = new Map(Object.entries(payload.files));
  const instance = await module.default.mount(document.getElementById("host"), {
    files: { get: (id) => files.get(id) || null },
    metadata: { taskType: "foundry_rf3_fold" },
    services: {
      openFile: (artifact) => opened.push(artifact.url),
      downloadFile: (artifact) => downloaded.push(artifact.url),
    },
  });
  window.__rf3Storyboard = { requests, opened, downloaded, instance };
}
"""


def _page(artifact: str, key: str, shape: list[int], data: list[float]) -> tuple[str, dict]:
    url = f"{artifact}?max_elements=1048576&key={key}"
    return url, {
        "kind": "numeric",
        "dtype": "<f8",
        "key": key,
        "shape": shape,
        "total_elements": len(data),
        "data": data,
    }


def test_rf3_ranks_samples_and_loads_exact_matching_confidence(page: Page) -> None:
    files = {
        "structures": [
            {"url": "/model-0", "name": "target_seed-0_sample-0_model.cif"},
            {"url": "/model-1", "name": "target_seed-0_sample-1_model.cif"},
        ],
        "summaries": [
            {"url": "/summary-0", "name": "target_seed-0_sample-0_summary_confidences.json"},
            {"url": "/summary-1", "name": "target_seed-0_sample-1_summary_confidences.json"},
        ],
        "confidences": [
            {"ndarray_url": "/confidence-0", "name": "target_seed-0_sample-0_confidences.json"},
            {"ndarray_url": "/confidence-1", "name": "target_seed-0_sample-1_confidences.json"},
        ],
        "rankings": [{"url": "/ranking", "name": "target_ranking_scores.csv"}],
        "run_record": [{"url": "/run", "name": "foundry-run.json"}],
        "model_assets": [{"url": "/assets", "name": "foundry-model-assets.json"}],
    }
    responses = {
        "/ranking": "seed,sample,ranking_score\n0,0,0.2\n0,1,0.8\n",
        "/summary-1": {
            "overall_plddt": 0.77,
            "overall_pae": 6.6,
            "overall_pde": 2.0,
            "ptm": 0.12,
            "iptm": 0,
            "ranking_score": 0.8,
            "has_clash": False,
        },
    }
    responses.update([_page("/confidence-1", "atom_plddts", [2], [0.7, 0.8])])
    responses.update([_page("/confidence-1", "pae", [2, 2], [1, 2, 2, 1])])
    source = (ROOT / "docker/runners/foundry/storyboard/index.js").read_text(encoding="utf-8")
    page.set_viewport_size({"width": 1200, "height": 1100})
    page.set_content("<div id='host'></div>")
    install_scientific_assets(page)
    page.evaluate(MOUNT, {"source": source, "files": files, "responses": responses, "delays": {"/summary-1": 100}})

    expect(page.locator(".rf3-candidates button").first).to_contain_text("sample 1 · 0.8")
    expect(page.locator(".scalar-grid")).to_contain_text("Overall PDE2 angstrom")
    expect(page.get_by_role("img", name="pLDDT by Atom index")).to_be_visible()
    expect(page.locator(".matrix-readout")).to_contain_text("1.0 angstrom")
    requests = page.evaluate("window.__rf3Storyboard.requests")
    assert "/summary-0" not in requests
    assert "/confidence-0?max_elements=1048576&key=pae" not in requests

    page.locator(".candidate-open").nth(0).click()
    page.locator(".candidate-open").nth(1).click()
    expect(page.locator(".scalar-grid")).to_have_count(0)
    expect(page.get_by_role("img", name="pLDDT by Atom index")).to_have_count(0)
    expect(page.get_by_role("button", name="Open selected structure")).to_have_count(0)
    expect(page.locator(".rf3-figure")).to_be_hidden()
    page.wait_for_timeout(150)
    expect(page.locator(".scalar-grid")).to_have_count(0)


def test_rf3_early_stop_mounts_without_a_structure(page: Page) -> None:
    files = {
        "structures": [],
        "summaries": [],
        "confidences": [],
        "rankings": [{"url": "/ranking", "name": "target_ranking_scores.csv"}],
        "run_record": [{"url": "/run", "name": "foundry-run.json"}],
        "model_assets": [{"url": "/assets", "name": "foundry-model-assets.json"}],
    }
    source = (ROOT / "docker/runners/foundry/storyboard/index.js").read_text(encoding="utf-8")
    page.set_content("<div id='host'></div>")
    install_scientific_assets(page)
    page.evaluate(MOUNT, {"source": source, "files": files, "responses": {"/ranking": "early_stopped\ntrue\n"}})

    expect(page.locator(".preview-message")).to_have_text("RF3 published early-stopping metrics without a structure.")
    expect(page.get_by_role("button", name="Download run record")).to_be_visible()
