# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for AlphaFold2 and SimpleFold runner storyboards."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import install_scientific_assets

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]

MOUNT = """
async (payload) => {
  const url = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(url);
  const requests = [], opened = [];
  window.REvoDesignAuth = { authFetch: async (target) => {
    requests.push(target);
    if (payload.delays && payload.delays[target]) await new Promise((resolve) => setTimeout(resolve, payload.delays[target]));
    const value = payload.responses[target];
    return { ok: value !== undefined, json: async () => value };
  }};
  window.fetch = window.REvoDesignAuth.authFetch;
  const files = new Map(Object.entries(payload.files));
  const instance = await module.default.mount(document.getElementById("host"), {
    files: { get: (id) => files.get(id) || null },
    metadata: { taskType: payload.taskType },
    services: { openFile: (artifact) => opened.push(artifact.url), downloadFile: () => {} },
  });
  window.__sparseStoryboard = { requests, opened, instance };
}
"""


def _mount(page: Page, family: str, task_type: str, files: dict, responses: dict, delays: dict | None = None) -> None:
    source = (ROOT / "docker/runners" / family / "storyboard/index.js").read_text(encoding="utf-8")
    page.set_viewport_size({"width": 1200, "height": 1000})
    page.set_content("<div id='host'></div>")
    install_scientific_assets(page)
    page.evaluate(MOUNT, {"source": source, "taskType": task_type, "files": files, "responses": responses, "delays": delays or {}})


def test_alphafold2_joins_rank_to_model_identity_before_loading_evidence(page: Page) -> None:
    files = {
        "structures": [{"url": "/ranked-0", "name": "ranked_0.pdb"}],
        "confidences": [
            {"url": "/confidence-1", "name": "confidence_model_1_ptm_pred_0.json"},
            {"url": "/confidence-2", "name": "confidence_model_2_ptm_pred_0.json"},
        ],
        "pae": [{"url": "/pae-2", "ndarray_url": "/pae-2", "name": "pae_model_2_ptm_pred_0.json", "size": 100}],
        "ranking": [{"url": "/ranking", "name": "ranking_debug.json"}],
    }
    responses = {
        "/ranking": {"order": ["model_2_ptm_pred_0", "model_1_ptm_pred_0"]},
        "/confidence-2": {"confidenceScore": [70, 90], "residueNumber": [1, 2]},
        "/pae-2?max_elements=1048576&key=0.predicted_aligned_error": {"kind": "numeric", "dtype": "<f8", "key": "0.predicted_aligned_error", "shape": [2, 2], "total_elements": 4, "data": [1, 2, 2, 1]},
    }
    _mount(page, "alphafold", "alphafold", files, responses)

    expect(page.get_by_role("img", name="pLDDT by Residue position")).to_be_visible()
    expect(page.locator(".matrix-readout")).to_contain_text("1.0 angstrom")
    assert page.evaluate("window.__sparseStoryboard.requests") == ["/ranking", "/confidence-2", "/pae-2?max_elements=1048576&key=0.predicted_aligned_error"]


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


@pytest.mark.parametrize("family", ["alphafold", "simplefold"])
def test_sparse_storyboards_clear_structure_action_and_confidence_after_failed_replacement(page: Page, family: str) -> None:
    if family == "alphafold":
        files = {
            "structures": [{"url": "/rank-0", "name": "ranked_0.pdb"}, {"url": "/rank-1", "name": "ranked_1.pdb"}],
            "confidences": [{"url": "/confidence-0", "name": "confidence_model_0.json"}, {"url": "/confidence-1", "name": "confidence_model_1.json"}],
            "pae": [], "ranking": [{"url": "/ranking"}],
        }
        responses = {"/ranking": {"order": ["model_0", "model_1"]}, "/confidence-0": {"confidenceScore": [80], "residueNumber": [1]}}
    else:
        files = {
            "structures_cif": [{"url": "/sample-0", "name": "sample_0.cif"}, {"url": "/sample-1", "name": "sample_1.cif"}],
            "structures_pdb": [],
            "confidences": [{"url": "/confidence-0", "name": "sample_0.json"}, {"url": "/confidence-1", "name": "sample_1.json"}],
        }
        responses = {"/confidence-0": {"confidenceScore": [80]}}
    _mount(page, family, family, files, responses, delays={"/confidence-0": 100})
    expect(page.get_by_role("img", name="pLDDT by Residue position")).to_be_visible()

    page.locator(".candidate-open").nth(0).click()
    page.locator(".candidate-open").nth(1).click()
    expect(page.get_by_role("img", name="pLDDT by Residue position")).to_have_count(0)
    expect(page.get_by_role("button", name="Open selected structure")).to_have_count(0)
    page.wait_for_timeout(150)
    expect(page.get_by_role("img", name="pLDDT by Residue position")).to_have_count(0)
