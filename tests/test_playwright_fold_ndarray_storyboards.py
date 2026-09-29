# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for ESMFold2, Boltz, and Chai runner storyboards."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
PRIMITIVES = ROOT / "revocompute/static/js/scientific-primitives.js"

MOUNT = """
async (payload) => {
  const url = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(url);
  const requests = [], opened = [];
  window.REvoDesignAuth = { authFetch: async (target) => {
    requests.push(target);
    const value = payload.responses[target];
    return { ok: value !== undefined, json: async () => value, text: async () => String(value) };
  }};
  const files = new Map(Object.entries(payload.files));
  const instance = await module.default.mount(document.getElementById("host"), {
    files: { get: (id) => files.get(id) || null },
    metadata: { taskType: payload.taskType },
    services: { openFile: (artifact) => opened.push(artifact.url), downloadFile: () => {} },
  });
  window.__foldStoryboard = { requests, opened, instance };
}
"""


def _mount(page: Page, family: str, task_type: str, files: dict, responses: dict) -> None:
    source = (ROOT / "docker/runners" / family / "storyboard/index.js").read_text(encoding="utf-8")
    page.set_viewport_size({"width": 1200, "height": 1100})
    page.set_content("<div id='host'></div>")
    page.add_script_tag(content=PRIMITIVES.read_text(encoding="utf-8"))
    page.evaluate(MOUNT, {"source": source, "taskType": task_type, "files": files, "responses": responses})


def test_esmfold2_uses_persisted_scale_and_bounds_json_matrix_fetch(page: Page) -> None:
    files = {
        "structures": [{"url": "/structure", "name": "sample_001.cif"}],
        "summaries": [{"url": "/summary", "name": "sample_001_confidence.json"}],
        "local_confidence": [{"url": "/local", "ndarray_url": "/arrays/local", "name": "sample_001_plddt.csv"}],
        "pae": [{"url": "/pae", "name": "sample_001_pae.json", "size": 3_000_000}],
    }
    responses = {
        "/summary": {"mean_plddt": 0.8, "ptm": 0.7, "iptm": None},
        "/arrays/local?offset=0&limit=16384&key=token_index": {"dtype": "<f8", "key": "token_index", "shape": [2], "total_elements": 2, "offset": 0, "count": 2, "data": [1, 2], "has_more": False},
        "/arrays/local?offset=0&limit=16384&key=plddt": {"dtype": "<f8", "key": "plddt", "shape": [2], "total_elements": 2, "offset": 0, "count": 2, "data": [0.7, 0.9], "has_more": False},
    }
    _mount(page, "esmfold2", "esmfold2_predict", files, responses)

    expect(page.locator(".scalar-grid")).to_contain_text("Mean pLDDT0.8 score")
    expect(page.get_by_role("img", name="pLDDT by Token index")).to_be_visible()
    expect(page.locator(".matrix-readout")).to_contain_text("exceeds the interactive JSON limit")
    assert "/local" not in page.evaluate("window.__foldStoryboard.requests")
    assert "/pae" not in page.evaluate("window.__foldStoryboard.requests")


def test_boltz_reads_named_npz_members_through_bounded_api(page: Page) -> None:
    files = {
        "structures": [{"url": "/structure", "name": "job_model_0.cif"}],
        "summaries": [{"url": "/summary", "name": "confidence_job_model_0.json"}],
        "local_confidence": [{"ndarray_url": "/arrays/plddt", "name": "plddt_job_model_0.npz"}],
        "pae": [{"ndarray_url": "/arrays/pae", "name": "pae_job_model_0.npz"}],
        "pde": [],
    }
    responses = {
        "/summary": {"confidence_score": 0.8, "ptm": 0.7, "iptm": 0.6, "complex_plddt": 0.9, "complex_pde": 1.2},
        "/arrays/plddt?offset=0&limit=16384&key=plddt": {"dtype": "float32", "key": "plddt", "shape": [2], "total_elements": 2, "offset": 0, "count": 2, "data": [0.7, 0.9], "has_more": False},
        "/arrays/pae?offset=0&limit=16384&key=pae": {"dtype": "float32", "key": "pae", "shape": [2, 2], "total_elements": 4, "offset": 0, "count": 4, "data": [1, 2, 2, 1], "has_more": False},
    }
    _mount(page, "boltz", "boltz_predict", files, responses)

    expect(page.locator(".scalar-grid")).to_contain_text("Confidence score0.8 score")
    expect(page.locator(".boltz-figure canvas").first).to_be_visible()
    expect(page.locator(".matrix-readout").first).to_contain_text("1.0 angstrom")
    requests = page.evaluate("window.__foldStoryboard.requests")
    assert requests == [
        "/summary",
        "/arrays/plddt?offset=0&limit=16384&key=plddt",
        "/arrays/pae?offset=0&limit=16384&key=pae",
    ]


def test_chai_rejects_oversized_matrix_projection_without_partial_plot(page: Page) -> None:
    files = {
        "structures": [{"url": "/structure", "name": "rank_0.cif"}],
        "summaries": [{"url": "/summary", "name": "confidence.rank_0.json"}],
        "local_confidence": [{"ndarray_url": "/arrays/plddt", "name": "plddt.rank_0.npy"}],
        "pae": [{"ndarray_url": "/arrays/pae", "name": "pae.rank_0.npy"}],
        "pde": [{"ndarray_url": "/arrays/pde", "name": "pde.rank_0.npy"}],
    }
    responses = {
        "/summary": {"aggregate_score": 0.8, "ptm": 0.7, "iptm": 0.6, "has_inter_chain_clashes": False},
        "/arrays/plddt?offset=0&limit=16384": {"dtype": "float32", "key": None, "shape": [2], "total_elements": 2, "offset": 0, "count": 2, "data": [0.8, 0.9], "has_more": False},
        "/arrays/pae?offset=0&limit=16384": {"dtype": "float32", "key": None, "shape": [1025, 1025], "total_elements": 1_050_625, "offset": 0, "count": 0, "data": [], "has_more": True},
        "/arrays/pde?offset=0&limit=16384": {"dtype": "float32", "key": None, "shape": [2, 2], "total_elements": 4, "offset": 0, "count": 4, "data": [0.1, 0.2, 0.2, 0.1], "has_more": False},
    }
    _mount(page, "chai1", "chai1_predict", files, responses)

    expect(page.locator(".scalar-grid")).to_contain_text("Inter-chain clashesNo")
    expect(page.locator(".matrix-readout").first).to_contain_text("exceeds the bounded interactive limit")
    expect(page.locator(".matrix-readout").nth(1)).to_contain_text("0.1 angstrom")
    assert all(".npy" not in target for target in page.evaluate("window.__foldStoryboard.requests"))


def test_boltz_assembles_a_matrix_larger_than_one_bounded_page(page: Page) -> None:
    side = 129
    total = side * side
    first = [1.0] * 16_384
    second = [2.0] * (total - len(first))
    files = {
        "structures": [{"url": "/structure", "name": "job_model_0.cif"}],
        "summaries": [{"url": "/summary", "name": "confidence_job_model_0.json"}],
        "local_confidence": [{"ndarray_url": "/arrays/plddt", "name": "plddt_job_model_0.npz"}],
        "pae": [{"ndarray_url": "/arrays/pae", "name": "pae_job_model_0.npz"}],
        "pde": [],
    }
    responses = {
        "/summary": {"confidence_score": 0.8},
        "/arrays/plddt?offset=0&limit=16384&key=plddt": {"dtype": "float32", "key": "plddt", "shape": [1], "total_elements": 1, "offset": 0, "count": 1, "data": [0.8], "has_more": False},
        "/arrays/pae?offset=0&limit=16384&key=pae": {"dtype": "float32", "key": "pae", "shape": [side, side], "total_elements": total, "offset": 0, "count": len(first), "data": first, "has_more": True},
        "/arrays/pae?offset=16384&limit=16384&key=pae": {"dtype": "float32", "key": "pae", "shape": [side, side], "total_elements": total, "offset": 16_384, "count": len(second), "data": second, "has_more": False},
    }
    _mount(page, "boltz", "boltz_predict", files, responses)

    expect(page.locator(".matrix-readout").first).to_contain_text("1.0 angstrom")
    requests = page.evaluate("window.__foldStoryboard.requests")
    assert "/arrays/pae?offset=16384&limit=16384&key=pae" in requests
