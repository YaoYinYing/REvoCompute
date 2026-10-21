# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser contract for the AutoDock Vina result storyboard module.

The storyboard is Runner-owned JavaScript executed by the result page. This test
loads the real module and mounts it with the documented context API, over the
bytes a real Vina run published in a target-host live test (``tests/data/
autodock_vina/live``). It asserts the interaction the scientific question needs:
the ranked pose table is built from the run's own ``scores.csv``, the ranking
direction and counts come from ``summary.json``, selecting a row drives the
inspector and the shared selection store, the search box can be focused as a
spatial target, and the score caveat is always stated. It does not claim the
docking is scientifically correct: the values are what Vina reported.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from browser_frontend_assets import install_scientific_assets

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
STORYBOARD = ROOT / "docker" / "runners" / "autodock_vina" / "tasks" / "autodock_vina" / "storyboard" / "index.js"
LIVE = ROOT / "tests" / "data" / "autodock_vina" / "live"
SCORES = LIVE / "scores.csv"
SUMMARY = LIVE / "summary.json"
RUN_RECORD = LIVE / "vina-run.json"
POSE = LIVE / "vina_1.pdbqt"
LOG = LIVE / "vina_1.log"

# The logical files the storyboard binds to, shaped as the server returns them.
FILES = {
    "scores": {"id": "scores", "name": "scores.csv", "media_type": "text/csv", "size": SCORES.stat().st_size,
               "role": "evidence", "cardinality": "one", "viewer": "table", "preview": "table",
               "capability": "table", "url": "/files/scores?index=0"},
    "summary": {"id": "summary", "name": "summary.json", "media_type": "application/json", "size": SUMMARY.stat().st_size,
                "role": "evidence", "cardinality": "one", "viewer": "json", "preview": "json",
                "capability": "text", "url": "/files/summary?index=0"},
    "run_record": {"id": "run_record", "name": "vina-run.json", "media_type": "application/json",
                   "size": RUN_RECORD.stat().st_size, "role": "provenance", "cardinality": "one",
                   "viewer": "json", "preview": "json", "capability": "text", "url": "/files/run_record?index=0"},
    "poses": [{"id": "poses", "name": "vina_1.pdbqt", "media_type": "application/octet-stream",
               "size": POSE.stat().st_size, "role": "artifact", "cardinality": "many", "viewer": "download",
               "preview": None, "capability": "download_only", "url": "/files/pose?index=0"}],
    "pose_logs": [{"id": "pose_logs", "name": "vina_1.log", "media_type": "application/octet-stream",
                   "size": LOG.stat().st_size, "role": "artifact", "cardinality": "many", "viewer": "text",
                   "preview": "text", "capability": "text", "url": "/files/log?index=0"}],
    "prepared": [{"id": "prepared", "name": "receptor.pdbqt", "path": "prepared/receptor.pdbqt",
                  "size": 10, "role": "artifact", "cardinality": "many", "capability": "download_only",
                  "url": "/files/prepared?index=0"}],
    "receptor": {"id": "receptor", "name": "1abc_A_B.pdb", "path": "debug/inputs/receptor/1abc_A_B.pdb",
                 "size": 10, "role": "provenance", "cardinality": "one", "viewer": "structure",
                 "preview": "structure", "capability": "molecular_structure", "url": "/files/receptor?index=0"},
    "ligands": [{"id": "ligands", "name": "ethanol.sdf", "path": "debug/inputs/ligands/ethanol.sdf",
                 "size": 10, "role": "provenance", "cardinality": "many", "capability": "download_only",
                 "url": "/files/ligands?index=0"}],
    "citations": {"id": "citations", "name": "citations.bib", "size": 10, "role": "provenance",
                  "cardinality": "one", "capability": "text", "url": "/files/citations?index=0"},
}

VIEWS = [
    {"id": "docked_poses", "plugin": "candidate-collection", "role": "primary", "title": "Docked poses",
     "sources": {"candidates": ["vina_1.pdbqt"], "supporting": ["scores.csv"]}},
    {"id": "docking_run", "plugin": "evidence-bundle", "role": "evidence", "title": "Run record",
     "sources": {"items": ["vina-run.json", "summary.json"]}},
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
  if (payload.dropReceptor) files.set("receptor", null);
    const bodies = payload.bodies || {};
  window.REvoDesignAuth = { authFetch: async (target) => {
    const key = String(target).split("?")[0].replace("/files/", "");
    if (key in bodies) return { ok: true, text: async () => bodies[key], json: async () => JSON.parse(bodies[key]) };
    return { ok: false, status: 404, text: async () => "", json: async () => ({}) };
  }};
  window.fetch = window.REvoDesignAuth.authFetch;
  const opened = [], downloaded = [], focused = [], selected = [], viewed = [], annotated = [];
  const context = {
    files: { get: (id) => (files.has(id) ? files.get(id) : null) },
    metadata: { taskType: "autodock_vina" },
    views: payload.views,
    selection: { set: (state) => selected.push(state) },
    services: {
      openFile: (artifact) => { opened.push(artifact.url || artifact.name); return Promise.resolve(); },
      downloadFile: (artifact) => downloaded.push(artifact.url || artifact.name),
      openView: async (viewId) => viewed.push(viewId),
      focusStructure: (selection) => { focused.push(selection); return true; },
      resetStructure: () => viewed.push("reset"),
      annotateStructure: (annotation) => annotated.push(annotation),
    },
  };
  const host = document.getElementById("host");
  const instance = await module.default.mount(host, context);
  window.__vina = { host, instance, opened, downloaded, focused, selected, viewed, annotated };
}
"""


def _bodies(*, break_scores: bool = False) -> dict[str, str]:
    return {
        "scores": "" if break_scores else SCORES.read_text(encoding="utf-8"),
        "summary": SUMMARY.read_text(encoding="utf-8"),
        "run_record": RUN_RECORD.read_text(encoding="utf-8"),
    }


def _mount(page: Page, *, drop_receptor: bool = False, break_scores: bool = False) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.set_content("<div id='host'></div>")
    install_scientific_assets(page)
    # The storyboard receives the logical file's URL; point scores.csv at the
    # run's own bytes when it must resolve, or at an unresolvable path for the
    # failure state.
    files = json.loads(json.dumps(FILES))
    # Point scores.csv at an unresolvable path when the failure state is under
    # test; everything else is served from the run's own bytes.
    if break_scores:
        files["scores"]["url"] = "/missing/scores.csv"
    page.evaluate(
        MOUNT,
        {
            "source": STORYBOARD.read_text(encoding="utf-8"),
            "files": files,
            "views": VIEWS,
            "bodies": _bodies(break_scores=break_scores),
            "dropReceptor": drop_receptor,
        },
    )
    return errors


def _score_rows() -> list[dict[str, str]]:
    lines = SCORES.read_text(encoding="utf-8").strip().splitlines()
    header = lines[0].split(",")
    return [dict(zip(header, line.split(","), strict=True)) for line in lines[1:]]


def test_storyboard_renders_the_ranked_table_from_the_run_scores(page: Page) -> None:
    expected = _score_rows()
    assert len(expected) == 2
    _mount(page)

    expect(page.get_by_role("heading", name="AutoDock Vina ranked poses")).to_be_visible()
    table = page.locator("table.vina-table")
    expect(table.locator("tbody tr")).to_have_count(len(expected))
    first = table.locator("tbody tr").first.locator("td").all_inner_texts()
    assert first[0] == expected[0]["ligand"]
    assert first[1] == expected[0]["pose_rank"]
    assert first[2] == expected[0]["affinity_kcal_mol"]
    assert first[3] == expected[0]["rmsd_lb_angstrom"]
    assert first[4] == expected[0]["rmsd_ub_angstrom"]
    assert first[5] == expected[0]["pose_file"]
    # The ranking sentence is read from summary.json, not assumed.
    summary = json.loads(SUMMARY.read_text())
    expect(page.locator('[data-vina="ranking"]')).to_have_text(
        f"Ranked by {summary['ranking_metric']}, lowest first, as published by the run."
    )


def test_storyboard_states_the_score_is_not_an_affinity_measurement(page: Page) -> None:
    _mount(page)
    caveat = page.locator('[data-vina-caveat="score"]')
    expect(caveat).to_be_visible()
    expect(caveat).to_contain_text("not measured binding free energies or experimental affinities")


def test_storyboard_selection_drives_the_inspector_and_the_selection_store(page: Page) -> None:
    expected = _score_rows()
    _mount(page)

    expect(page.locator('.vina-row[aria-current="true"]')).to_have_count(1)
    expect(page.locator(".vina-inspector")).to_contain_text(expected[0]["affinity_kcal_mol"])
    page.locator(".vina-row").nth(1).click()

    inspector = page.locator(".vina-inspector")
    expect(inspector).to_contain_text(expected[1]["affinity_kcal_mol"])
    expect(inspector).to_contain_text(expected[1]["pose_file"])
    expect(page.locator('.vina-row[aria-current="true"]')).to_have_count(1)
    assert page.evaluate("window.__vina.selected.at(-1).candidate") == expected[1]["pose_file"]
    # The row's named pose file is the published one, downloaded on demand.
    page.locator('[data-vina-pose-download="true"]').click()
    assert page.evaluate("window.__vina.downloaded") == ["/files/pose?index=0"]


def test_storyboard_reports_the_run_record_from_the_published_file(page: Page) -> None:
    record = json.loads(RUN_RECORD.read_text())
    _mount(page)
    run = page.locator('section[aria-label="Run record"]')
    expect(run).to_contain_text(record["inputs"]["receptor"][0]["original_name"])
    expect(run).to_contain_text("center_x")
    # The record prints the value as the number it is; the JSON spells it 5.0.
    expect(run).to_contain_text(f"{float(record['parameters']['center_x']):g}")


def test_storyboard_focuses_the_recorded_search_box_as_a_spatial_target(page: Page) -> None:
    record = json.loads(RUN_RECORD.read_text())
    _mount(page)
    # The receptor snapshot is mounted once, from the logical file.
    assert page.evaluate("window.__vina.opened") == ["/files/receptor?index=0"]
    page.locator('[data-vina-focus="true"]').click()

    focused = page.evaluate("window.__vina.focused")
    assert focused, "focusing the search box must request a structure focus"
    point = focused[0]["focusPoint"]
    assert point["x"] == record["parameters"]["center_x"]
    assert point["y"] == record["parameters"]["center_y"]
    assert point["z"] == record["parameters"]["center_z"]
    assert point["radius"] == record["parameters"]["size_x"] / 2
    annotations = page.evaluate("window.__vina.annotated")
    assert annotations[-1]["label"] == "Vina search box centre"
    page.locator('[data-vina-reset="true"]').click()
    assert page.evaluate("window.__vina.viewed.at(-1)") == "reset"
    assert page.evaluate("window.__vina.annotated.at(-1)") is None


def test_storyboard_keeps_the_table_and_downloads_without_a_receptor_snapshot(page: Page) -> None:
    _mount(page, drop_receptor=True)
    expect(page.locator("table.vina-table")).to_be_visible()
    assert page.evaluate("window.__vina.opened") == []
    expect(page.locator('[data-vina-focus="true"]')).to_have_count(0)
    # The downloads shelf is collapsed by default; open it before reading it.
    page.locator(".vina-artifacts > summary").click()
    expect(page.get_by_role("button", name="Download scores (CSV)")).to_be_visible()


def test_storyboard_states_a_missing_table_instead_of_crashing(page: Page) -> None:
    errors = _mount(page, break_scores=True)
    expect(page.locator("table.vina-table")).to_have_count(0)
    expect(page.locator(".vina-empty")).to_be_visible()
    expect(page.locator(".vina-note", has_text="downloadable")).to_be_visible()
    assert errors == [], errors


def test_storyboard_keeps_the_declared_views_reachable(page: Page) -> None:
    errors = _mount(page)
    page.locator(".vina-artifacts > summary").click()
    for title in ("Open Docked poses", "Open Run record"):
        expect(page.get_by_role("button", name=title, exact=True)).to_be_visible()
    page.get_by_role("button", name="Open Run record", exact=True).click()
    assert page.evaluate("window.__vina.viewed") == ["docking_run"]
    assert errors == [], errors
