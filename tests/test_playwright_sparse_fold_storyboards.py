# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for AlphaFold2 and SimpleFold runner storyboards."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from tests.browser_frontend_assets import install_scientific_assets

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]

MOUNT = """
async (payload) => {
  const url = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(url);
  const requests = [], opened = [];
  window.REvoDesignAuth = { authFetch: async (target) => {
    requests.push(target);
    const value = payload.responses[target];
    return { ok: value !== undefined, json: async () => value };
  }};
  const files = new Map(Object.entries(payload.files));
  const instance = await module.default.mount(document.getElementById("host"), {
    files: { get: (id) => files.get(id) || null },
    metadata: { taskType: payload.taskType },
    services: { openFile: (artifact) => opened.push(artifact.url), downloadFile: () => {} },
  });
  window.__sparseStoryboard = { requests, opened, instance };
}
"""


def _mount(page: Page, family: str, task_type: str, files: dict, responses: dict) -> None:
    source = (ROOT / "docker/runners" / family / "storyboard/index.js").read_text(encoding="utf-8")
    page.set_viewport_size({"width": 1200, "height": 1000})
    page.set_content("<div id='host'></div>")
    install_scientific_assets(page)
    page.evaluate(MOUNT, {"source": source, "taskType": task_type, "files": files, "responses": responses})


def test_alphafold2_joins_rank_to_model_identity_before_loading_evidence(page: Page) -> None:
    files = {
        "structures": [{"url": "/ranked-0", "name": "ranked_0.pdb"}],
        "confidences": [
            {"url": "/confidence-1", "name": "confidence_model_1_ptm_pred_0.json"},
            {"url": "/confidence-2", "name": "confidence_model_2_ptm_pred_0.json"},
        ],
        "pae": [{"url": "/pae-2", "name": "pae_model_2_ptm_pred_0.json", "size": 100}],
        "ranking": [{"url": "/ranking", "name": "ranking_debug.json"}],
    }
    responses = {
        "/ranking": {"order": ["model_2_ptm_pred_0", "model_1_ptm_pred_0"]},
        "/confidence-2": {"confidenceScore": [70, 90], "residueNumber": [1, 2]},
        "/pae-2": [{"predicted_aligned_error": [[1, 2], [2, 1]], "max_predicted_aligned_error": 31.75}],
    }
    _mount(page, "alphafold", "alphafold", files, responses)

    expect(page.get_by_role("img", name="pLDDT by Residue position")).to_be_visible()
    expect(page.locator(".matrix-readout")).to_contain_text("1.0 angstrom")
    assert page.evaluate("window.__sparseStoryboard.requests") == ["/ranking", "/confidence-2", "/pae-2"]


def test_simplefold_pairs_optional_confidence_by_sample_stem(page: Page) -> None:
    files = {
        "structures_cif": [
            {"url": "/sample-0", "name": "mini_sampled_0.cif"},
            {"url": "/sample-1", "name": "mini_sampled_1.cif"},
        ],
        "structures_pdb": [],
        "confidences": [{"url": "/confidence-1", "name": "mini_sampled_1.json"}],
    }
    responses = {"/confidence-1": {"confidenceScore": [80, 90], "meanPlddt": 85}}
    _mount(page, "simplefold", "simplefold_predict", files, responses)

    expect(page.locator(".preview-message")).to_have_text("pLDDT was not requested for this run.")
    page.get_by_role("button", name="mini_sampled_1").click()
    expect(page.get_by_role("img", name="pLDDT by Residue position")).to_be_visible()
    assert page.evaluate("window.__sparseStoryboard.requests") == ["/confidence-1"]
