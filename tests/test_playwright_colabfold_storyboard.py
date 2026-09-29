# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for the runner-owned ColabFold result storyboard."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
STORYBOARD = ROOT / "docker" / "runners" / "colabfold_af2" / "storyboard" / "index.js"
PRIMITIVES = ROOT / "revocompute" / "static" / "js" / "scientific-primitives.js"

FILES = {
    "structures": [
        {"id": "structures", "name": "job_unrelaxed_rank_001_model_1_seed_000.pdb", "url": "/rank1-unrelaxed"},
        {"id": "structures", "name": "job_relaxed_rank_001_model_1_seed_000.pdb", "url": "/rank1-relaxed"},
        {"id": "structures", "name": "job_unrelaxed_rank_002_model_2_seed_000.pdb", "url": "/rank2"},
    ],
    "scores": [
        {"id": "scores", "name": "job_scores_rank_001_model_1_seed_000.json", "url": "/scores/1"},
        {"id": "scores", "name": "job_scores_rank_002_model_2_seed_000.json", "url": "/scores/2"},
    ],
    "alignment": {"id": "alignment", "name": "job.a3m", "url": "/alignment"},
    "interface_scores": {"id": "interface_scores", "name": "interface_scores.json", "url": "/interface"},
}

RESPONSES = {
    "/scores/1": {"plddt": [90, 80, 70], "ptm": 0.81, "iptm": 0.72, "ranking_confidence": 0.74, "pae": [[1, 2, 3], [2, 1, 2], [3, 2, 1]]},
    "/scores/2": {"plddt": [50, 60, 70], "ptm": 0.61, "iptm": 0.52, "ranking_confidence": 0.54, "pae": [[4, 5, 6], [5, 4, 5], [6, 5, 4]]},
    "/interface": {"scores_file": "job_scores_rank_001_model_1_seed_000.json", "ipsae": 0.67, "pdockq2": 0.58},
}

MOUNT = """
async (payload) => {
  const moduleUrl = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(moduleUrl);
  const opened = [];
  window.REvoDesignAuth = { authFetch: async (url) => {
    const value = url === "/alignment" ? "#2,1\\t1,2\\n>query\\nACD\\n>hit\\nA-D\\n" : payload.responses[url];
    return { ok: true, text: async () => typeof value === "string" ? value : JSON.stringify(value) };
  }};
  const files = new Map(Object.entries(payload.files));
  const instance = await module.default.mount(document.getElementById("host"), {
    files: { get: (id) => files.get(id) || null },
    metadata: { taskType: "colabfold_af2" },
    services: { openFile: (artifact) => opened.push(artifact.url), downloadFile: () => {} },
  });
  window.__colabfold = { opened, instance };
}
"""


def _mount(page: Page) -> None:
    page.set_viewport_size({"width": 1200, "height": 1000})
    page.set_content("<div id='host'></div>")
    page.add_script_tag(content=PRIMITIVES.read_text(encoding="utf-8"))
    page.evaluate(MOUNT, {"source": STORYBOARD.read_text(encoding="utf-8"), "files": FILES, "responses": RESPONSES})


def test_colabfold_storyboard_synchronizes_ranked_confidence_and_pae(page: Page) -> None:
    _mount(page)

    candidates = page.locator(".colabfold-candidates > .candidate-open")
    expect(candidates).to_have_count(2)
    expect(candidates.nth(0)).to_have_attribute("aria-current", "true")
    assert page.locator(".scalar-grid").text_content() == (
        "Mean pLDDT80.0 scoreHigher is betterpTM0.81 scoreHigher is better"
        "ipTM0.72 scoreHigher is betterRanking confidence0.74 scoreHigher is better"
        "ipSAE0.67 scoreHigher is betterpDockQ20.58 scoreHigher is better"
    )
    expect(page.locator(".colabfold-figure canvas")).to_have_attribute("role", "grid")
    assert "1.0 Å" in page.locator(".matrix-readout").text_content()
    expect(page.locator(".entity-result-table tr")).to_have_count(3)
    expect(page.locator(".msa-header")).to_have_count(2)

    candidates.nth(1).click()
    expect(page.locator(".scalar-grid")).to_contain_text("Mean pLDDT60.0 score")
    expect(page.locator(".scalar-grid")).not_to_contain_text("ipSAE")
    expect(page.locator(".matrix-readout")).to_contain_text("4.0 Å")


def test_colabfold_storyboard_opens_the_preferred_relaxed_structure(page: Page) -> None:
    _mount(page)
    page.get_by_role("button", name="Open rank 1 structure").click()
    assert page.evaluate("window.__colabfold.opened") == ["/rank1-relaxed"]

