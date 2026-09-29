# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior and bounded-data contract for the OpenDDE storyboard."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from tests.browser_frontend_assets import install_scientific_assets

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
STORYBOARD = ROOT / "docker" / "runners" / "opendde" / "storyboard" / "index.js"

FILES = {
    "structures": [
        {"id": "structures", "name": "job_sample_0.cif", "url": "/structures/0"},
        {"id": "structures", "name": "job_sample_0.cif", "url": "/structures/1"},
    ],
    "summaries": [
        {"id": "summaries", "name": "job_summary_confidence_sample_0.json", "url": "/summaries/0"},
        {"id": "summaries", "name": "job_summary_confidence_sample_0.json", "url": "/summaries/1"},
    ],
    "full_confidences": [
        {"id": "full_confidences", "name": "job_full_data_sample_0.json", "url": "/full/0", "ndarray_url": "/arrays/0"},
        {"id": "full_confidences", "name": "job_full_data_sample_0.json", "url": "/full/1", "ndarray_url": "/arrays/1"},
    ],
}

SUMMARIES = {
    "/summaries/0": {"plddt": 92.2, "ptm": 0.18, "iptm": 0, "gpde": 0.45, "ranking_score": 0.036, "has_clash": False},
    "/summaries/1": {"plddt": 75.1, "ptm": 0.71, "iptm": 0.64, "gpde": 1.2, "ranking_score": 0.59, "has_clash": True},
}

PROJECTIONS = {
    "0": {
        "atom_plddt": [0.95, 0.82, 0.74],
        "token_pair_pae": [[1.0, 2.0], [3.0, 1.0]],
        "token_pair_pde": [[0.5, 1.5], [1.5, 0.5]],
        "contact_probs": [[0.9, 0.2], [0.2, 0.8]],
    },
    "1": {
        "atom_plddt": [0.61, 0.72],
        "token_pair_pae": [[4.0, 8.0], [7.0, 3.0]],
        "token_pair_pde": [[2.0, 3.0], [3.0, 2.0]],
        "contact_probs": [[0.7, 0.4], [0.4, 0.6]],
    },
}

MOUNT = """
async (payload) => {
  const moduleUrl = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(moduleUrl);
  const fetched = [], opened = [], downloaded = [];
  window.REvoDesignAuth = { authFetch: async (url) => {
    fetched.push(url);
    if (url.startsWith('/summaries/')) {
      if (payload.failedSummary === url) {
        if (payload.failureDelay) await new Promise((resolve) => setTimeout(resolve, payload.failureDelay));
        return { ok: false, status: 500, json: async () => ({ error: 'failed' }) };
      }
      return { ok: true, json: async () => payload.summaries[url] };
    }
    const parsed = new URL(url, 'https://example.invalid');
    const sample = parsed.pathname.split('/').pop();
    const key = parsed.searchParams.get('key');
    if (payload.failedKey === key) return { ok: true, status: 200, json: async () => ({
      kind: 'numeric', dtype: '<f8', shape: [1048577], key, total_elements: 1048577, data: [],
    }) };
    const value = (payload.projections[sample] || {})[key];
    if (!value) return { ok: false, status: 400, json: async () => ({error: 'missing'}) };
    const shape = Array.isArray(value[0]) ? [value.length, value[0].length] : [value.length];
    const flat = value.flat();
    return { ok: true, json: async () => ({
      kind: 'numeric', dtype: '<f8', shape, key, total_elements: flat.length, data: flat,
    }) };
  }};
  window.fetch = window.REvoDesignAuth.authFetch;
  const files = new Map(Object.entries(payload.files));
  const instance = await module.default.mount(document.getElementById("host"), {
    files: { get: (id) => files.get(id) || null },
    metadata: { taskType: "opendde" },
    services: { openFile: (artifact) => opened.push(artifact.url), downloadFile: (artifact) => downloaded.push(artifact.url) },
  });
  window.__opendde = { fetched, opened, downloaded, instance };
}
"""


def _mount(page: Page, *, failed_key: str | None = None, failed_summary: str | None = None) -> None:
    page.set_content("<div id='host'></div>")
    install_scientific_assets(page)
    page.evaluate(
        MOUNT,
        {
            "source": STORYBOARD.read_text(encoding="utf-8"),
            "files": FILES,
            "summaries": SUMMARIES,
            "projections": PROJECTIONS,
            "failedKey": failed_key,
            "failedSummary": failed_summary,
            "failureDelay": 100,
        },
    )


def test_opendde_storyboard_pairs_duplicate_sample_names_by_contract_order(page: Page) -> None:
    _mount(page)
    expect(page.locator(".candidate-open")).to_have_count(2)
    expect(page.locator(".scalar-grid")).to_contain_text("pLDDT92.2 score")
    expect(page.locator(".scalar-grid")).to_contain_text("ClashNo")

    page.locator(".candidate-open").nth(1).click()
    expect(page.locator(".scalar-grid")).to_contain_text("pLDDT75.1 score")
    expect(page.locator(".scalar-grid")).to_contain_text("ClashYes")
    fetched = page.evaluate("window.__opendde.fetched")
    assert fetched[0] == "/summaries/0"
    assert "/summaries/1" in fetched
    assert all(url.startswith(("/summaries/", "/arrays/")) for url in fetched)


def test_opendde_full_confidence_is_downloaded_without_browser_fetch(page: Page) -> None:
    _mount(page)
    page.get_by_role("button", name="Download full confidence").click()
    page.get_by_role("button", name="Open selected structure").click()

    assert page.evaluate("window.__opendde.downloaded") == ["/full/0"]
    assert page.evaluate("window.__opendde.opened") == ["/structures/0"]
    assert all(not url.startswith("/full/") for url in page.evaluate("window.__opendde.fetched"))


def test_opendde_renders_bounded_local_and_pairwise_confidence(page: Page) -> None:
    _mount(page)

    expect(page.get_by_role("img", name="Atom pLDDT by Atom index")).to_be_visible()
    expect(page.get_by_label("Pairwise confidence matrix")).to_have_value("0")
    expect(page.locator(".matrix-readout")).to_contain_text("1.0 Å")
    pair_section = page.locator(".opendde-section").filter(has_text="Pairwise confidence")
    expect(pair_section.locator(".scientific-note")).to_contain_text("2 × 2 tokens")

    page.get_by_label("Pairwise confidence matrix").select_option(label="PDE")
    expect(page.locator(".matrix-readout")).to_contain_text("0.5 Å")
    page.get_by_label("Pairwise confidence matrix").select_option(label="Contact probability")
    expect(page.locator(".matrix-readout")).to_contain_text("0.90 probability")

    fetched = page.evaluate("window.__opendde.fetched")
    assert any("key=atom_plddt" in url for url in fetched)
    assert any("key=token_pair_pae" in url for url in fetched)
    assert any("key=token_pair_pde" in url for url in fetched)
    assert any("key=contact_probs" in url for url in fetched)
    assert all(not url.startswith("/full/") for url in fetched)


def test_opendde_isolates_one_oversized_matrix_from_other_confidence(page: Page) -> None:
    _mount(page, failed_key="token_pair_pae")

    expect(page.locator(".scalar-grid")).to_contain_text("pLDDT92.2 score")
    expect(page.get_by_role("img", name="Atom pLDDT by Atom index")).to_be_visible()
    expect(page.locator(".preview-message")).to_contain_text("Some pairwise confidence data could not be displayed")
    expect(page.get_by_label("Pairwise confidence matrix").locator("option")).to_have_count(2)
    expect(page.get_by_label("Pairwise confidence matrix")).to_have_value("0")
    expect(page.locator(".matrix-readout")).to_contain_text("0.5 Å")
    page.get_by_label("Pairwise confidence matrix").select_option(label="Contact probability")
    expect(page.locator(".matrix-readout")).to_contain_text("0.90 probability")


def test_opendde_clears_every_candidate_panel_while_failed_replacement_loads(page: Page) -> None:
    _mount(page, failed_summary="/summaries/1")
    expect(page.locator(".scalar-grid")).to_contain_text("pLDDT92.2 score")

    page.locator(".candidate-open").nth(1).click()
    expect(page.locator(".opendde-actions button")).to_have_count(0)
    expect(page.locator(".scalar-grid")).to_have_count(0)
    expect(page.get_by_role("img", name="Atom pLDDT by Atom index")).to_have_count(0)
    expect(page.locator(".opendde-section").filter(has_text="Pairwise confidence")).to_be_hidden()
    expect(page.get_by_text("The OpenDDE confidence summary could not be loaded.", exact=True)).to_be_visible()
    expect(page.locator(".opendde-actions button")).to_have_count(0)
