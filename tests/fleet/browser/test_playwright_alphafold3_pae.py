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

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import install_scientific_assets

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
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
        "ndarray_url": "/projection/confidence",
    },
    "summaries": {
        "id": "summaries",
        "name": "job_summary_confidences.json",
        "path": "modeling/job/job_summary_confidences.json",
        "preview": "json",
        "media_type": "application/json",
        "url": "/compute/api/results/task/files/summaries?index=2",
        "ndarray_url": "/projection/summary",
    },
}

MOUNT = """
async (payload) => {
  const url = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(url);
  const normalize = (artifact) => Object.assign({ cardinality: "many", role: "primary", size: 2048 }, artifact);
  const files = new Map(Object.entries(payload.files).map(([id, value]) => [
    id, Array.isArray(value) ? value.map(normalize) : normalize(value),
  ]));
  const opened = [];
  window.fetch = async (target) => {
    const url = new URL(target, "https://example.invalid"), key = url.searchParams.get("key");
    if (payload.delays && payload.delays[url.pathname]) await new Promise((resolve) => setTimeout(resolve, payload.delays[url.pathname]));
    const source = payload.projections && payload.projections[url.pathname] || (url.pathname.includes("summary") ? payload.summary : payload.confidences);
    const value = source[key];
    if (value === undefined) return { ok: false, status: 400, json: async () => ({}) };
    const shape = Array.isArray(value) ? (Array.isArray(value[0]) ? [value.length, value[0].length] : [value.length]) : [];
    const data = shape.length === 2 ? value.flat() : shape.length === 1 ? value : [value];
    const kind = url.searchParams.get("kind") || "numeric";
    return { ok: true, status: 200, json: async () => ({ kind, dtype: kind === "categorical" ? "string" : "float64", shape, key, total_elements: data.length, data }) };
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
  const geometry = () => {
    const cssWidth = canvas.getBoundingClientRect().width;
    const scale = cssWidth / 800;
    const backing = canvas.width / cssWidth;
    return { cssWidth, scale, backing, left: 78 * scale, top: 30 * scale, size: 500 * scale };
  };
  const probe = (column, row) => {
    const current = geometry();
    const x = (current.left + current.size * (column + 0.5) / 12) * current.backing;
    const y = (current.top + current.size * (row + 0.5) / 12) * current.backing;
    const cell = context2d.getImageData(Math.round(x), Math.round(y), 1, 1).data;
    return [cell[0], cell[1], cell[2], cell[3]];
  };
  window.__af3 = {
    opened,
    probe,
    // The darkest pixel in a one-pixel column inside the matrix, three columns
    // wide. The chain border is drawn exactly on a column boundary, so this is
    // ink while borders are shown and a ramp colour while they are not.
    borderColumn: (x) => {
      const current = geometry();
      const centre = (current.left + current.size * x / 12) * current.backing;
      let darkest = null;
      for (let column = Math.round(centre) - 1; column <= Math.round(centre) + 1; column += 1) {
        for (let row = Math.round((current.top + 10 * current.scale) * current.backing);
             row < Math.round((current.top + current.size - 10 * current.scale) * current.backing); row += 1) {
          const cell = context2d.getImageData(column, row, 1, 1).data;
          const value = cell[0] + cell[1] + cell[2];
          if (darkest === null || value < darkest) darkest = value;
        }
      }
      return darkest;
    },
    cellPosition: (column, row) => {
      const current = geometry();
      return { x: current.left + current.size * (column + 0.5) / 12,
               y: current.top + current.size * (row + 0.5) / 12 };
    },
  };
  return {
    opened,
    buttons: Array.from(host.querySelectorAll("button")).map((node) => node.textContent),
    spans: Array.from(host.querySelectorAll(".af3-figure span")).map((node) => node.textContent),
    note: host.querySelector("#af3-pae-note").textContent,
    readout: host.querySelector(".matrix-readout").textContent,
    canvas: {
      width: canvas.width, height: canvas.height, cssWidth: canvas.getBoundingClientRect().width, tabIndex: canvas.tabIndex,
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
    install_scientific_assets(page)


def _mount(page: Page, files: dict = FILES, *, summary: dict = SUMMARY, projections: dict | None = None,
           delays: dict[str, int] | None = None) -> dict:
    return page.evaluate(
        MOUNT,
        {
            "source": STORYBOARD.read_text(encoding="utf-8"),
            "files": files,
            "confidences": CONFIDENCES,
            "summary": summary,
            "projections": projections or {},
            "delays": delays or {},
        },
    )


def test_storyboard_draws_the_pae_matrix_with_axes_and_a_legend(page: Page) -> None:
    _open(page)
    result = _mount(page)

    assert result["canvas"]["cssWidth"] == 800 and result["canvas"]["role"] == "grid"
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
    """The chain border follows the toggle, by keyboard.

    The assertion is on the border itself — the darkest pixel in the column
    where the two chains meet — not on a canvas hash. Repainting identical
    state does not reproduce identical bytes in this environment: the same
    borderless state has produced two different digests within one run, and the
    diff between them includes half-transparent pixels, i.e. pixels the redraw
    did not paint. A hash equality across repaints would be testing the
    rasterizer rather than the toggle.
    """
    _open(page)
    _mount(page)

    toggle = page.get_by_role("button", name="Show chain borders")
    assert toggle.get_attribute("aria-pressed") == "false"
    borderless = page.evaluate("() => window.__af3.borderColumn(6)")

    # Keyboard only, from here: the toggle must be operable without a pointer.
    toggle.focus()
    toggle.press("Enter")
    expect(toggle).to_have_attribute("aria-pressed", "true")
    bordered = page.evaluate("() => window.__af3.borderColumn(6)")
    assert bordered < borderless, "no chain border is drawn at the chain transition"

    toggle.press(" ")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    assert page.evaluate("() => window.__af3.borderColumn(6)") == borderless, (
        "disabling the borders did not remove them"
    )


def test_readout_reports_residue_numbers_and_a_value(page: Page) -> None:
    _open(page)
    _mount(page)

    # Click a cell in the second half of the matrix: chain B against itself.
    position = page.evaluate("() => window.__af3.cellPosition(10, 10)")
    page.locator("#host canvas").click(position=position)
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
    assert result["buttons"][0] == "job"
    page.get_by_role("button", name="Open selected structure").click()
    assert page.evaluate("() => window.__af3.opened") == ["structures"]
    assert result["confidence"] == [
        "0.88 scoreHigher is better",
        "0.85 scoreHigher is better",
        "0.85 scoreHigher is better",
        "0 fractionLower is better",
    ]
    assert result["destroyable"] is True


def test_storyboard_rejects_near_match_instead_of_pairing_by_array_order(page: Page) -> None:
    _open(page)
    files = {**FILES, "structures": {**FILES["structures"], "name": "job_model.cif.bak"}}
    _mount(page, files)

    expect(page.locator(".af3-actions button")).to_have_count(0)
    expect(page.locator("#af3-pae-note")).to_have_text("No exact confidence record matches this structure candidate.")


def test_storyboard_keeps_required_evidence_when_one_optional_scalar_is_absent(page: Page) -> None:
    _open(page)
    _mount(page, summary={key: value for key, value in SUMMARY.items() if key != "iptm"})

    expect(page.locator(".scalar-grid")).to_contain_text("pTM0.88 score")
    expect(page.locator(".scalar-grid")).not_to_contain_text("ipTM")
    expect(page.locator("#af3-pae-note")).to_contain_text("12 × 12")


def test_storyboard_matches_reordered_files_by_name_and_rejects_late_generation(page: Page) -> None:
    _open(page)
    next_summary = {**SUMMARY, "ptm": 0.42}
    next_confidence = {**CONFIDENCES, "pae": [[value + 10 for value in row] for row in PAE]}
    files = {
        "structures": [FILES["structures"], {**FILES["structures"], "id": "next-structure", "name": "next_model.cif"}],
        "summaries": [{**FILES["summaries"], "id": "next-summary", "name": "next_summary_confidences.json", "ndarray_url": "/projection/next-summary"}, FILES["summaries"]],
        "confidences": [{**FILES["confidences"], "id": "next-confidence", "name": "next_confidences.json", "ndarray_url": "/projection/next-confidence"}, FILES["confidences"]],
    }
    _mount(page, files, projections={
        "/projection/summary": SUMMARY,
        "/projection/confidence": CONFIDENCES,
        "/projection/next-summary": next_summary,
        "/projection/next-confidence": next_confidence,
    }, delays={"/projection/summary": 120, "/projection/confidence": 120})
    candidates = page.locator(".candidate-open")
    candidates.nth(0).click()
    candidates.nth(1).click()

    expect(page.locator(".scalar-grid")).to_contain_text("pTM0.42 score")
    page.wait_for_timeout(180)
    expect(page.locator(".scalar-grid")).to_contain_text("pTM0.42 score")
    page.get_by_role("button", name="Open selected structure").click()
    assert page.evaluate("window.__af3.opened") == ["next-structure"]
