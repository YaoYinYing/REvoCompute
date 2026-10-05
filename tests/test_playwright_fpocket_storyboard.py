# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser contract for the fpocket result storyboard module.

The storyboard is Runner-owned JavaScript executed by the result page. This test
loads the real module and mounts it with the documented context API, then checks
that it composes the structure-aware pocket result: a compact ranked selector,
a per-pocket descriptor readout, contacted-residue highlighting, and the
structure-focus integration boundary. It does not assert pocket values are
scientifically correct — they are what fpocket reported (see INTEGRATION.md).
"""

from __future__ import annotations

import csv
from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import install_scientific_assets

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
STORYBOARD = ROOT / "docker" / "runners" / "fpocket" / "storyboard" / "index.js"
LIVE_POCKETS = ROOT / "tests/data/fpocket/live/pockets.csv"

# The logical files the storyboard binds to, shaped as the server returns them.
FILES = {
    "protein_structure": {"id": "protein_structure", "name": "1SUO.pdb", "path": "work/1SUO.pdb",
                          "preview": "structure", "capability": "molecular_structure", "url": "/files/structure"},
    "pockets": {"id": "pockets", "name": "pockets.csv", "path": "pockets.csv", "preview": "table",
                "capability": "table", "url": "/files/pockets"},
    "detection_summary": {"id": "detection_summary", "name": "summary.json", "path": "summary.json",
                          "preview": "json", "capability": "text", "url": "/files/summary"},
    "pocket_contacts": [
        {"id": "pocket_contacts", "name": "pocket1_atm.pdb", "path": "work/1SUO_out/pockets/pocket1_atm.pdb",
         "preview": "structure", "capability": "molecular_structure", "url": "/files/pocket1_atm"},
        {"id": "pocket_contacts", "name": "pocket2_atm.pdb", "path": "work/1SUO_out/pockets/pocket2_atm.pdb",
         "preview": "structure", "capability": "molecular_structure", "url": "/files/pocket2_atm"},
    ],
    "pocket_alpha_spheres": [
        {"id": "pocket_alpha_spheres", "name": "pocket1_vert.pqr", "path": "work/1SUO_out/pockets/pocket1_vert.pqr",
         "preview": "pqr", "capability": "text", "url": "/files/pocket1_vert"},
    ],
}

# The task's own declared views; the storyboard may only navigate to these.
VIEWS = [
    {"id": "ranked_pockets", "plugin": "entity-table", "role": "primary", "title": "Ranked pockets",
     "sources": {"table": [{"path": "pockets.csv"}]}},
    {"id": "detection_summary", "plugin": "scalar-summary", "role": "evidence", "title": "Detection summary",
     "sources": {"data": [{"path": "summary.json"}]}},
    {"id": "raw_fpocket_output", "plugin": "evidence-bundle", "role": "evidence", "title": "Raw fpocket output",
     "sources": {"items": []}},
]

MOUNT = """
async (payload) => {
  const url = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(url);
  const files = new Map();
  for (const [id, value] of Object.entries(payload.files)) {
    if (Array.isArray(value)) files.set(id, value.map((item) => Object.assign({}, item)));
    else files.set(id, Object.assign({}, value));
  }
  if (payload.dropGeometry) { files.set("pocket_contacts", []); files.set("pocket_alpha_spheres", []); }
  const csv = files.get("pockets");
  if (payload.breakTable) csv.url = "/missing/pockets.csv";
  else csv.url = "data:text/csv;charset=utf-8," + encodeURIComponent(payload.pocketsCsv);
  window.REvoDesignAuth = { authFetch: async (target) => {
    if (String(target).startsWith("data:")) {
      const text = decodeURIComponent(String(target).split(",").slice(1).join(","));
      return { ok: true, text: async () => text, json: async () => JSON.parse(text) };
    }
    return { ok: false, status: 404, text: async () => "", json: async () => ({}) };
  }};
  window.fetch = window.REvoDesignAuth.authFetch;
  const opened = [], downloaded = [], focused = [], selected = [], viewed = [];
  const context = {
    files: { get: (id) => (files.has(id) ? files.get(id) : null) },
    metadata: { taskType: "fpocket" },
    views: payload.views,
    selection: { set: (state) => selected.push(state) },
    services: {
      openFile: (artifact) => opened.push(artifact.url || artifact.name),
      downloadFile: (artifact) => downloaded.push(artifact.url || artifact.name),
      openView: async (viewId) => viewed.push(viewId),
      focusStructure: (selection) => { focused.push(selection); return true; },
      selectStructure: (selection) => { selected.push({ structure: selection }); return true; },
    },
  };
  const host = document.getElementById("host");
  const instance = await module.default.mount(host, context);
  window.__fpl = { host, instance, opened, downloaded, focused, selected, viewed };
}
"""


def _pocket_rows() -> list[dict[str, str]]:
    with LIVE_POCKETS.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _mount(page: Page, *, drop_geometry: bool = False, break_table: bool = False) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.set_content("<div id='host'></div>")
    install_scientific_assets(page)
    page.evaluate(
        MOUNT,
        {
            "source": STORYBOARD.read_text(encoding="utf-8"),
            "files": FILES,
            "views": VIEWS,
            "pocketsCsv": LIVE_POCKETS.read_text(encoding="utf-8"),
            "dropGeometry": drop_geometry,
            "breakTable": break_table,
        },
    )
    return errors


def test_storyboard_renders_the_ranked_selector_from_the_real_table(page: Page) -> None:
    expected = _pocket_rows()
    assert len(expected) == 40
    _mount(page)

    expect(page.get_by_role("heading", name="fpocket pockets")).to_be_visible()
    table = page.locator("table.fpl-pockets")
    expect(table.locator("tbody tr")).to_have_count(40)
    headers = table.locator("thead th").all_inner_texts()
    for label in ("Rank", "Pocket", "Score", "Druggability", "Alpha spheres", "Volume (A^3)", "SASA (A^2)"):
        assert label in headers, headers
    first = table.locator("tbody tr").first.locator("td").all_inner_texts()
    assert first[0] == expected[0]["rank"] == "1"
    assert first[1] == expected[0]["pocket"] == "pocket1"
    assert first[2] == expected[0]["score"]


def test_storyboard_selection_updates_the_detail_without_reloading(page: Page) -> None:
    expected = _pocket_rows()
    _mount(page)

    # Nothing is selected until a pocket is chosen.
    expect(page.get_by_text("Select a pocket", exact=False)).to_be_visible()
    page.locator(".fpl-pocket-row").nth(1).click()

    readout = page.locator(".fpl-detail")
    expect(readout).to_contain_text("Druggability score")
    expect(readout).to_contain_text(expected[1]["druggability_score"])
    expect(readout).to_contain_text(expected[1]["center_x"])
    # The selected row is marked and the contacted residues are listed.
    expect(page.locator('.fpl-pocket-row[aria-current="true"]')).to_have_count(1)
    expect(page.locator('.fpl-pocket-row[aria-current="true"] td').first).to_have_text("2")
    residues = page.locator(".fpl-chip").all_inner_texts()
    assert residues and set(residues) == set(expected[1]["residue_ids"].split())

    # Switching pockets updates in place: the same table and readout, new pocket.
    page.locator(".fpl-pocket-row").nth(4).click()
    expect(readout).to_contain_text(expected[4]["score"])
    expect(page.locator('.fpl-pocket-row[aria-current="true"] td').first).to_have_text("5")


def test_storyboard_selection_drives_the_structure_focus_boundary(page: Page) -> None:
    _mount(page)
    page.locator(".fpl-pocket-row").first.click()

    # Selecting a pocket publishes the choice to the shared selection store.
    selected = page.evaluate("window.__fpl.selected")
    assert any(entry.get("candidate") == "pocket1" for entry in selected), selected

    # The explicit focus action crosses the structure-view boundary with a residue
    # selection the viewer can resolve, derived from the pocket's contacted atoms.
    page.get_by_role("button", name="Focus this pocket").click()
    focused = page.evaluate("window.__fpl.focused")
    assert focused, "selecting a pocket must request a structure focus"
    assert focused[0].get("numbering") == "label_seq_id"
    assert focused[0].get("chain") == "A"
    assert isinstance(focused[0].get("residue"), int)

    page.get_by_role("button", name="Select contacted residues").click()
    structure_selections = [entry["structure"] for entry in page.evaluate("window.__fpl.selected") if "structure" in entry]
    assert structure_selections and all(entry.get("numbering") == "label_seq_id" for entry in structure_selections)


def test_storyboard_mounts_the_structure_when_a_pocket_is_selected(page: Page) -> None:
    _mount(page)
    assert page.evaluate("window.__fpl.opened") == []
    page.locator(".fpl-pocket-row").first.click()
    opened = page.evaluate("window.__fpl.opened")
    # Selecting a pocket pulls the protein structure into the shared panel once.
    assert opened == ["/files/structure"], opened
    page.locator(".fpl-pocket-row").nth(1).click()
    assert page.evaluate("window.__fpl.opened") == ["/files/structure"]


def test_storyboard_opens_the_pocket_geometry_files(page: Page) -> None:
    _mount(page)
    page.locator(".fpl-pocket-row").first.click()
    page.get_by_role("button", name="Open contacted atoms").click()
    page.get_by_role("button", name="Open alpha spheres").click()
    opened = page.evaluate("window.__fpl.opened")
    assert "/files/pocket1_atm" in opened
    assert "/files/pocket1_vert" in opened


def test_storyboard_keeps_the_ranked_table_usable_without_geometry(page: Page) -> None:
    """One missing optional geometry file must not break the whole result."""
    _mount(page, drop_geometry=True)
    table = page.locator("table.fpl-pockets")
    expect(table.locator("tbody tr")).to_have_count(40)
    page.locator(".fpl-pocket-row").nth(2).click()
    expect(page.locator(".fpl-detail")).to_contain_text("Druggability score")
    expect(page.get_by_role("button", name="Open contacted atoms")).to_have_count(0)
    expect(page.get_by_text("Pocket geometry files were not published", exact=False)).to_be_visible()


def test_storyboard_states_a_malformed_table_instead_of_crashing(page: Page) -> None:
    _mount(page, break_table=True)
    expect(page.locator("table.fpl-pockets")).to_have_count(0)
    expect(page.locator(".fpl-unavailable")).to_be_visible()


def test_storyboard_keeps_the_generic_views_reachable(page: Page) -> None:
    errors = _mount(page)
    for title in ("Open Ranked pockets", "Open Detection summary", "Open Raw fpocket output"):
        expect(page.get_by_role("button", name=title, exact=True)).to_be_visible()
    page.get_by_role("button", name="Open Detection summary", exact=True).click()
    assert page.evaluate("window.__fpl.viewed") == ["detection_summary"]
    assert errors == [], errors
