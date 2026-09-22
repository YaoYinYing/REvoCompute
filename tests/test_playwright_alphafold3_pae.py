# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser contract for the AlphaFold 3 result storyboard module.

The storyboard is Runner-owned JavaScript executed by the result page. This test
loads the real module, mounts it with the documented context API against a
synthetic ``*_confidences.json``, and verifies the PAE plot's observable
behaviour: mapped pixels, axis ticks carrying residue numbers, the colour-scale
legend, the chain-border toggle repainting the canvas, and a residue readout.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page
import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
STORYBOARD = ROOT / "docker" / "runners" / "alphafold3" / "storyboard" / "index.js"

# Two chains, so exactly one chain border is defensible from token_chain_ids.
CHAINS = ["A"] * 6 + ["B"] * 6
RESIDUES = list(range(1, 7)) * 2

# Square PAE: low inside a chain, high across chains, so the colour mapping and
# the chain border both have something to show.
PAE = [[float(abs(row - column) % 7) + (12.0 if (row < 6) != (column < 6) else 1.0) for column in range(12)]
       for row in range(12)]
CONFIDENCES = {
    "pae": PAE,
    "token_chain_ids": CHAINS,
    "token_res_ids": RESIDUES,
    "atom_plddts": [90.0] * 12,
    "atom_chain_ids": CHAINS,
    "contact_probs": [[0.0] * 12] * 12,
}
SUMMARY = {"ptm": 0.88, "iptm": 0.85, "ranking_score": 0.85, "fraction_disordered": 0.0, "has_clash": 0.0}

# Mirrors the logical-file record the server returns for a storyboard
# (`revocompute/routes.py`): `preview` is the declared expected-file type and
# `url` is the authenticated artifact URL.
FILES = {
    "structures": {
        "id": "structures",
        "name": "job_model.cif",
        "path": "modeling/job/job_model.cif",
        "preview": "structure",
        "media_type": "chemical/x-mmcif",
        "url": "/compute/api/results/task/files/structures?index=0",
    },
    "confidences": {
        "id": "confidences",
        "name": "job_confidences.json",
        "path": "modeling/job/job_confidences.json",
        "preview": "json",
        "media_type": "application/json",
        "url": "/compute/api/results/task/files/confidences?index=1",
    },
    "summaries": {
        "id": "summaries",
        "name": "job_summary_confidences.json",
        "path": "modeling/job/job_summary_confidences.json",
        "preview": "json",
        "media_type": "application/json",
        "url": "/compute/api/results/task/files/summaries?index=2",
    },
}

MOUNT = """
async (payload) => {
  const url = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(url);
  const files = new Map(Object.entries(payload.files).map(([id, artifact]) => [id, Object.assign({
    cardinality: "many", role: "primary", size: 2048,
  }, artifact)]));
  const opened = [];
  window.REvoDesignAuth = {
    authFetch: (target) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(/summaries/.test(target) ? payload.summary : payload.confidences),
    }),
  };
  const context = {
    files: { get: (id) => files.get(id) || null },
    metadata: { taskType: "alphafold3" },
    services: { openFile: (artifact) => { opened.push(artifact.id); } },
  };
  const host = document.getElementById("host");
  const instance = await module.default.mount(host, context);
  const canvas = host.querySelector("canvas");
  const context2d = canvas.getContext("2d");
  const probe = (column, row) => {
    // Centre of one matrix cell: the plot geometry is fixed at 500 px square
    // starting at (78, 30) for a 12 x 12 matrix.
    const cell = context2d.getImageData(78 + Math.round(500 * (column + 0.5) / 12),
                                        30 + Math.round(500 * (row + 0.5) / 12), 1, 1).data;
    return [cell[0], cell[1], cell[2], cell[3]];
  };
  window.__af3 = {
    opened,
    probe,
    signature: () => {
      const pixels = context2d.getImageData(0, 0, canvas.width, canvas.height).data;
      let hash = 0;
      for (let index = 0; index < pixels.length; index += 13) hash = (hash * 31 + pixels[index]) >>> 0;
      return hash;
    },
  };
  return {
    opened,
    buttons: Array.from(host.querySelectorAll("button")).map((node) => node.textContent),
    spans: Array.from(host.querySelectorAll(".af3-figure span")).map((node) => node.textContent),
    note: host.querySelector("#af3-pae-note").textContent,
    readout: host.querySelector(".matrix-readout").textContent,
    canvas: {
      width: canvas.width, height: canvas.height, tabIndex: canvas.tabIndex,
      role: canvas.getAttribute("role"), describedBy: canvas.getAttribute("aria-describedby"),
    },
    confidence: Array.from(host.querySelectorAll(".scalar-grid dd")).map((node) => node.textContent),
    destroyable: typeof instance.destroy === "function",
  };
}
"""


def _open(page: Page) -> None:
    page.set_viewport_size({"width": 1280, "height": 1000})
    page.set_content("<div id='host'></div>")


def _mount(page: Page) -> dict:
    return page.evaluate(
        MOUNT,
        {
            "source": STORYBOARD.read_text(encoding="utf-8"),
            "files": FILES,
            "confidences": CONFIDENCES,
            "summary": SUMMARY,
        },
    )


def test_storyboard_draws_the_pae_matrix_with_axes_and_a_legend(page: Page) -> None:
    _open(page)
    result = _mount(page)

    assert result["canvas"]["width"] == 800 and result["canvas"]["role"] == "grid"
    # The colour mapping is real: the low-error diagonal cell and a cross-chain
    # cell are opaque and visually distinct.
    low = page.evaluate("() => window.__af3.probe(0, 0)")
    high = page.evaluate("() => window.__af3.probe(0, 6)")
    assert low[3] == 255 and high[3] == 255
    assert low[:3] != high[:3], (low, high)

    # Axis ticks and titles are DOM text, so the plot has a text alternative.
    texts = result["spans"]
    assert "Aligned residue" in texts and "Scored residue" in texts
    assert any(text.startswith("PAE (Å)") for text in texts)
    residue_ticks = [text for text in texts if text.isdigit()]
    assert len(residue_ticks) == 12, texts  # six aligned + six scored ticks
    assert set(residue_ticks) == {str(value) for value in RESIDUES[:6]}
    assert "12 × 12" in result["note"] and "Å" in result["note"]


def test_chain_border_toggle_is_keyboard_operable_and_repaints(page: Page) -> None:
    _open(page)
    _mount(page)

    toggle = page.get_by_role("button", name="Show chain borders")
    assert toggle.get_attribute("aria-pressed") == "false"
    before = page.evaluate("() => window.__af3.signature()")
    toggle.focus()
    toggle.press("Enter")
    assert toggle.get_attribute("aria-pressed") == "true"
    assert page.evaluate("() => window.__af3.signature()") != before
    toggle.press(" ")
    assert toggle.get_attribute("aria-pressed") == "false"
    assert page.evaluate("() => window.__af3.signature()") == before


def test_readout_reports_residue_numbers_and_a_value(page: Page) -> None:
    _open(page)
    _mount(page)

    # Click a cell in the second half of the matrix: chain B against itself.
    page.locator("#host canvas").click(position={"x": 78 + 450, "y": 30 + 450})
    readout = page.locator(".matrix-readout")
    assert readout.text_content() == "Aligned residue 5 (chain B) · Scored residue 5 (chain B) · 1.0 Å"

    canvas = page.locator("#host canvas")
    canvas.focus()
    canvas.press("ArrowRight")
    assert "Aligned residue 6 (chain B)" in readout.text_content()


def test_storyboard_composes_structures_and_confidence(page: Page) -> None:
    _open(page)
    result = _mount(page)

    # Structures stay reachable: the storyboard hands them to the shared viewer.
    assert result["buttons"][0] == "job_model.cif"
    page.get_by_role("button", name="job_model.cif").click()
    assert page.evaluate("() => window.__af3.opened") == ["structures"]
    assert result["confidence"] == ["0.88 score", "0.85 score", "0.85 score", "0 fraction"]
    assert result["destroyable"] is True
