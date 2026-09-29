# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for ESMFold2, Boltz, and Chai runner storyboards."""

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
  const requests = [], opened = [];
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
    metadata: { taskType: payload.taskType },
    services: { openFile: (artifact) => opened.push(artifact.url), downloadFile: () => {} },
  });
  window.__foldStoryboard = { requests, opened, instance };
}
"""


def _mount(page: Page, family: str, task_type: str, files: dict, responses: dict, delays: dict | None = None) -> None:
    source = (ROOT / "docker/runners" / family / "storyboard/index.js").read_text(encoding="utf-8")
    page.set_viewport_size({"width": 1200, "height": 1100})
    page.set_content("<div id='host'></div>")
    install_scientific_assets(page)
    page.evaluate(MOUNT, {"source": source, "taskType": task_type, "files": files, "responses": responses, "delays": delays or {}})


def test_esmfold2_uses_persisted_scale_and_bounded_matrix_projection(page: Page) -> None:
    files = {
        "structures": [{"url": "/structure", "name": "sample_001.cif"}],
        "summaries": [{"url": "/summary", "name": "sample_001_confidence.json"}],
        "local_confidence": [{"url": "/local", "ndarray_url": "/arrays/local", "name": "sample_001_plddt.csv"}],
        "pae": [{"url": "/pae", "ndarray_url": "/arrays/pae", "name": "sample_001_pae.json", "size": 3_000_000}],
    }
    responses = {
        "/summary": {"mean_plddt": 0.8, "ptm": 0.7, "iptm": None},
        "/arrays/local?max_elements=1048576&key=token_index": {"kind": "numeric", "dtype": "<f8", "key": "token_index", "shape": [2], "total_elements": 2, "data": [1, 2]},
        "/arrays/local?max_elements=1048576&key=plddt": {"kind": "numeric", "dtype": "<f8", "key": "plddt", "shape": [2], "total_elements": 2, "data": [0.7, 0.9]},
        "/arrays/pae?max_elements=1048576&key=pae": {"kind": "numeric", "dtype": "<f8", "key": "pae", "shape": [2, 2], "total_elements": 4, "data": [1, 2, 2, 1]},
    }
    _mount(page, "esmfold2", "esmfold2_predict", files, responses)

    expect(page.locator(".scalar-grid")).to_contain_text("Mean pLDDT0.8 score")
    expect(page.get_by_role("img", name="pLDDT by Token index")).to_be_visible()
    expect(page.locator(".matrix-readout")).to_contain_text("1.0 angstrom")
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
        "/arrays/plddt?max_elements=1048576&key=plddt": {"kind": "numeric", "dtype": "float32", "key": "plddt", "shape": [2], "total_elements": 2, "data": [0.7, 0.9]},
        "/arrays/pae?max_elements=1048576&key=pae": {"kind": "numeric", "dtype": "float32", "key": "pae", "shape": [2, 2], "total_elements": 4, "data": [1, 2, 2, 1]},
    }
    _mount(page, "boltz", "boltz_predict", files, responses)

    expect(page.locator(".scalar-grid")).to_contain_text("Confidence score0.8 score")
    expect(page.locator(".boltz-figure canvas").first).to_be_visible()
    expect(page.locator(".matrix-readout").first).to_contain_text("1.0 angstrom")
    requests = page.evaluate("window.__foldStoryboard.requests")
    assert requests == [
        "/summary",
        "/arrays/plddt?max_elements=1048576&key=plddt",
        "/arrays/pae?max_elements=1048576&key=pae",
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
        "/arrays/plddt?max_elements=1048576": {"kind": "numeric", "dtype": "float32", "key": None, "shape": [2], "total_elements": 2, "data": [0.8, 0.9]},
        "/arrays/pde?max_elements=1048576": {"kind": "numeric", "dtype": "float32", "key": None, "shape": [2, 2], "total_elements": 4, "data": [0.1, 0.2, 0.2, 0.1]},
    }
    _mount(page, "chai1", "chai1_predict", files, responses)

    expect(page.locator(".scalar-grid")).to_contain_text("Inter-chain clashesNo")
    expect(page.locator(".matrix-readout").first).to_contain_text("exceeds the bounded interactive limit")
    expect(page.locator(".matrix-readout").nth(1)).to_contain_text("0.1 angstrom")
    assert all(".npy" not in target for target in page.evaluate("window.__foldStoryboard.requests"))


def test_boltz_loads_a_matrix_larger_than_the_legacy_page_size_once(page: Page) -> None:
    side = 129
    total = side * side
    matrix = [1.0] * 16_384 + [2.0] * (total - 16_384)
    files = {
        "structures": [{"url": "/structure", "name": "job_model_0.cif"}],
        "summaries": [{"url": "/summary", "name": "confidence_job_model_0.json"}],
        "local_confidence": [{"ndarray_url": "/arrays/plddt", "name": "plddt_job_model_0.npz"}],
        "pae": [{"ndarray_url": "/arrays/pae", "name": "pae_job_model_0.npz"}],
        "pde": [],
    }
    responses = {
        "/summary": {"confidence_score": 0.8},
        "/arrays/plddt?max_elements=1048576&key=plddt": {"kind": "numeric", "dtype": "float32", "key": "plddt", "shape": [1], "total_elements": 1, "data": [0.8]},
        "/arrays/pae?max_elements=1048576&key=pae": {"kind": "numeric", "dtype": "float32", "key": "pae", "shape": [side, side], "total_elements": total, "data": matrix},
    }
    _mount(page, "boltz", "boltz_predict", files, responses)

    expect(page.locator(".matrix-readout").first).to_contain_text("1.0 angstrom")
    requests = page.evaluate("window.__foldStoryboard.requests")
    assert requests.count("/arrays/pae?max_elements=1048576&key=pae") == 1


@pytest.mark.parametrize("family", ["esmfold2", "boltz", "chai1"])
def test_fold_storyboards_clear_all_candidate_views_after_failed_replacement(page: Page, family: str) -> None:
    structures = [{"url": "/structure-0", "name": "candidate-0.cif"}, {"url": "/structure-1", "name": "candidate-1.cif"}]
    files = {"structures": structures, "summaries": [{"url": "/summary-0"}, {"url": "/summary-1"}]}
    responses = {"/summary-0": {"mean_plddt": 0.8, "confidence_score": 0.8, "aggregate_score": 0.8}}
    if family == "esmfold2":
        files.update({
            "local_confidence": [{"ndarray_url": "/local-0"}, {"ndarray_url": "/local-1"}],
            "pae": [{"ndarray_url": "/pae-0"}, {"ndarray_url": "/pae-1"}],
        })
        for artifact in ("local-0",):
            responses[f"/{artifact}?max_elements=1048576&key=token_index"] = {"kind": "numeric", "dtype": "<f8", "key": "token_index", "shape": [1], "total_elements": 1, "data": [1]}
            responses[f"/{artifact}?max_elements=1048576&key=plddt"] = {"kind": "numeric", "dtype": "<f8", "key": "plddt", "shape": [1], "total_elements": 1, "data": [0.8]}
        responses["/pae-0?max_elements=1048576&key=pae"] = {"kind": "numeric", "dtype": "<f8", "key": "pae", "shape": [1, 1], "total_elements": 1, "data": [1]}
    elif family == "boltz":
        files.update({"local_confidence": [{"ndarray_url": "/local-0"}, {"ndarray_url": "/local-1"}], "pae": [], "pde": []})
        responses["/local-0?max_elements=1048576&key=plddt"] = {"kind": "numeric", "dtype": "<f8", "key": "plddt", "shape": [1], "total_elements": 1, "data": [0.8]}
    else:
        files.update({
            "local_confidence": [{"ndarray_url": "/local-0"}, {"ndarray_url": "/local-1"}],
            "pae": [{"ndarray_url": "/pae-0"}, {"ndarray_url": "/pae-1"}],
            "pde": [{"ndarray_url": "/pde-0"}, {"ndarray_url": "/pde-1"}],
        })
        for artifact, shape, data in (("local-0", [1], [0.8]), ("pae-0", [1, 1], [1]), ("pde-0", [1, 1], [1])):
            responses[f"/{artifact}?max_elements=1048576"] = {"kind": "numeric", "dtype": "<f8", "key": None, "shape": shape, "total_elements": len(data), "data": data}
    _mount(page, family, family, files, responses, delays={"/summary-0": 100})
    expect(page.locator(".scalar-grid")).to_have_count(1)

    page.locator(".candidate-open").nth(0).click()
    page.locator(".candidate-open").nth(1).click()
    expect(page.locator(".scalar-grid")).to_have_count(0)
    expect(page.get_by_role("button", name="Open selected structure")).to_have_count(0)
    expect(page.locator("canvas:visible")).to_have_count(0)
    page.wait_for_timeout(150)
    expect(page.locator(".scalar-grid")).to_have_count(0)
