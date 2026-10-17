# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser contract for the GREMLIN_LH result storyboard module.

The storyboard is Runner-owned JavaScript executed by the result page. This test
loads the real module, mounts it with the documented context API, and verifies
that it composes the approved coupling landscape: the fitted model's own
statistics beside the matrix it declares, the ranked residue pairs read from the
real normalized table, and navigation to the task's own declared result views
rather than a re-implemented matrix renderer.

The fit facts and the ranked pairs are read from the pinned replay bundle
(``tests/data/gremlin_lh_replay``), so the narrative is asserted against the
bytes a real GREMLIN_LH run published rather than against hand-written numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import install_scientific_assets

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
STORYBOARD = ROOT / "docker" / "runners" / "gremlin_lh" / "storyboard" / "index.js"
REPLAY_BUNDLE = ROOT / "tests" / "data" / "gremlin_lh_replay" / "2kl8_seed0_944ed43af62e.json"

if not REPLAY_BUNDLE.is_file():
    pytest.skip("the captured GREMLIN_LH replay bundle is not present", allow_module_level=True)

# Mirrors the logical-file record the server returns for a storyboard
# (`revocompute/routes.py`): `preview` is the declared expected-file type and
# `media_type` is the detected transport type.
ARTIFACTS = {
    "alignment": {"id": "alignment", "path": "alignment/filtered_alignment.a3m", "preview": "alignment", "media_type": "text/plain"},
    "query": {"id": "query", "path": "query.fasta", "preview": "fasta", "media_type": "text/plain"},
    "sequence_weights": {"id": "sequence_weights", "path": "alignment/sequence_weights.tsv", "preview": "table", "media_type": "text/tab-separated-values"},
    "mrf_model": {"id": "mrf_model", "path": "model/gremlin_mrf.npz", "preview": "model", "media_type": "application/octet-stream"},
    "training_history": {"id": "training_history", "path": "model/training_history.csv", "preview": "table", "media_type": "text/csv"},
    "sequence_scores": {"id": "sequence_scores", "path": "model/sequence_scores.tsv", "preview": "table", "media_type": "text/tab-separated-values"},
    "profile": {"id": "profile", "path": "profiles/profile.tsv", "preview": "table", "media_type": "text/tab-separated-values"},
    "pairwise_scores": {"id": "pairwise_scores", "path": "couplings/pairwise_scores.tsv", "preview": "table", "media_type": "text/tab-separated-values"},
    "raw_matrix": {"id": "raw_matrix", "path": "couplings/raw_scores.csv", "preview": "table", "media_type": "text/csv"},
    "apc_matrix": {"id": "apc_matrix", "path": "couplings/apc_scores.csv", "preview": "table", "media_type": "text/csv"},
    "coupling_plot": {"id": "coupling_plot", "path": "plots/coupling_apc.png", "preview": "image", "media_type": "image/png"},
    "alignment_statistics": {"id": "alignment_statistics", "path": "alignment/statistics.json", "preview": "json", "media_type": "application/json"},
    "model_metadata": {"id": "model_metadata", "path": "model/metadata.json", "preview": "json", "media_type": "application/json"},
    "summary": {"id": "summary", "path": "summary.json", "preview": "json", "media_type": "application/json"},
}

# The label the provenance list gives each durable scientific object.
OBJECT_LABELS = {
    "mrf_model": "MRF model (NPZ)",
    "model_metadata": "Model metadata",
    "profile": "Position profile",
    "pairwise_scores": "Ranked residue pairs",
}


def recorded(name: str) -> str:
    """One payload exactly as the pinned real GREMLIN_LH run published it."""
    return json.loads(REPLAY_BUNDLE.read_text(encoding="utf-8"))["payloads"][name]["payload"]


SUMMARY = json.loads(recorded("summary.json"))
PAIRS_TSV = recorded("couplings/pairwise_scores.tsv")

# The views this task declares in its own task.yaml; the storyboard may only
# navigate to these, never render them itself. The raw Frobenius matrix is the
# declared primary (contact-oriented) view; APC is the comparison.
MATRIX_VIEWS = [
    {
        "id": "raw_couplings", "plugin": "matrix", "role": "primary", "title": "Coupling strength (raw Frobenius)",
        "sources": {"matrices": [{"path": "couplings/raw_scores.csv"}]},
    },
    {
        "id": "apc_couplings", "plugin": "matrix", "role": "evidence", "title": "Coupling strength (average-product corrected)",
        "sources": {"matrices": [{"path": "couplings/apc_scores.csv"}]},
    },
]
OTHER_VIEWS = [
    {
        "id": "ranked_pairs", "plugin": "entity-table", "role": "evidence", "title": "Ranked residue pairs",
        "sources": {"table": [{"path": "couplings/pairwise_scores.tsv"}]},
    },
    {
        "id": "filtered_alignment", "plugin": "alignment", "role": "evidence", "title": "Filtered alignment",
        "sources": {"alignment": [{"path": "alignment/filtered_alignment.a3m"}]},
    },
    {"id": "model_artifacts", "plugin": "evidence-bundle", "role": "evidence", "title": "Model artifacts", "sources": {"items": []}},
    {"id": "fit_summary", "plugin": "scalar-summary", "role": "evidence", "title": "Model fit summary", "sources": {"data": [{"path": "summary.json"}]}},
]
VIEWS = MATRIX_VIEWS + OTHER_VIEWS
# A workspace that declared no matrix view at all, so the landscape has no
# declared matrix to render and must not substitute one of its own.
VIEWS_WITHOUT_MATRIX = OTHER_VIEWS

# The tab label each declared view is offered under. A matrix keeps its declared
# id as the label only when the workspace declares a title the panel cannot
# shorten; the two coupling views name the correction instead.
TAB_LABELS = {"raw_couplings": "Raw couplings", "apc_couplings": "APC corrected", "filtered_alignment": "Alignment"}

MOUNT = """
async (payload) => {
  const url = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(url);
  const files = new Map(Object.entries(payload.files).map(([id, artifact]) => [id, Object.assign({
    name: artifact.path.split("/").pop(),
    url: "/compute/api/results/abc/files/" + id + "?index=0",
    size: 1024,
  }, artifact)]));
  // The two artifacts the narrative reads directly are served as the bytes the
  // pinned real run published, so a wrong label or a fixture value cannot pass.
  files.set("summary", Object.assign({}, files.get("summary"),
    { url: "data:application/json," + encodeURIComponent(payload.summary) }));
  files.set("pairwise_scores", Object.assign({}, files.get("pairwise_scores"),
    { url: "data:text/plain," + encodeURIComponent(payload.pairs) }));
  const mounted = [];
  const opened = [];
  const downloaded = [];
  const viewed = [];
  const context = {
    files: { get: (id) => files.get(id) || null },
    metadata: { taskType: "gremlin_lh_fit" },
    views: payload.views,
    services: {
      // The task's own renderer mounts a declared view into the host it is given.
      mountView: async (viewId, host) => { mounted.push(viewId); host.replaceChildren(); return { destroy() {} }; },
      openFile: (artifact) => { opened.push(artifact.id || artifact.path); },
      downloadFile: (artifact) => { downloaded.push(artifact.id || artifact.path); },
      openView: async (viewId) => { viewed.push(viewId); },
    },
  };
  const host = document.getElementById("host");
  await module.default.mount(host, context);
  const clickView = (viewId) => {
    const node = host.querySelector('button[data-view-id="' + viewId + '"]');
    if (node) node.click();
    return Boolean(node);
  };
  // The provenance list names each durable object by its own label; its action
  // is the row's button, so the row is located by label and then by its verb.
  const clickObject = (label, verb) => {
    const row = Array.from(host.querySelectorAll(".glh-artifact-row")).find(
      (item) => item.firstElementChild && item.firstElementChild.textContent === label);
    const node = row && Array.from(row.querySelectorAll("button")).find(
      (item) => !verb || item.textContent.startsWith(verb));
    if (node) node.click();
    return Boolean(node);
  };
  const facts = {};
  host.querySelectorAll(".glh-fit-facts div").forEach((row) => {
    const term = row.querySelector("dt"), value = row.querySelector("dd");
    if (term && value) facts[term.textContent] = value.textContent;
  });
  const clicked = {
    rawMatrix: clickObject(payload.labels.mrf_model, "Download"),
    modelMetadata: clickObject(payload.labels.model_metadata, "Open"),
  };
  clickView("apc_couplings");
  await new Promise((resolve) => setTimeout(resolve, 0));
  // Kept live so a test can click another declared view and assert the result.
  window.__glh = {
    mounted, opened, downloaded, viewed,
    pressed: () => Array.from(host.querySelectorAll(".glh-actions button[aria-pressed=true]")).map((node) => node.dataset.viewId),
  };
  const table = host.querySelector(".glh-pair-preview table");
  return {
    clicked, opened, downloaded, viewed, mounted, facts,
    order: Array.from(host.querySelector(".glh-result").children).map((node) => node.tagName + "." + node.className),
    headings: Array.from(host.querySelectorAll(".glh-result h2, .glh-result h3, .glh-result h4")).map((node) => node.textContent),
    kickers: Array.from(host.querySelectorAll(".glh-kicker")).map((node) => node.textContent),
    tabs: Array.from(host.querySelectorAll(".glh-actions button")).map((node) => node.textContent),
    viewButtons: Array.from(host.querySelectorAll("button[data-view-id]")).map((node) => node.dataset.viewId),
    pressed: Array.from(host.querySelectorAll(".glh-actions button[aria-pressed=true]")).map((node) => node.dataset.viewId),
    tableHead: table ? Array.from(table.querySelectorAll("th")).map((node) => node.textContent) : [],
    firstRow: table ? Array.from(table.querySelectorAll("tbody tr:first-child td")).map((node) => node.textContent) : [],
    rowCount: table ? table.querySelectorAll("tbody tr").length : 0,
    foot: (host.querySelector(".glh-table-foot span") || {}).textContent || null,
    readout: (host.querySelector(".glh-pair-readout") || {}).textContent || null,
    provenance: Array.from(host.querySelectorAll(".glh-artifact-row")).map((node) => node.textContent),
    unavailable: Array.from(host.querySelectorAll(".glh-unavailable")).map((node) => node.textContent),
    canvas: host.querySelectorAll(".glh-matrix canvas").length,
    groupLabels: Array.from(host.querySelectorAll("[role=group]")).map((node) => node.getAttribute("aria-label")),
  };
}
"""


def _mount(page: Page, files: dict[str, dict[str, str]], *, views: list | None = None) -> dict:
    page.set_content("<div id='host'></div>")
    install_scientific_assets(page)
    return page.evaluate(MOUNT, {
        "source": STORYBOARD.read_text(encoding="utf-8"),
        "files": files,
        "views": VIEWS if views is None else views,
        "summary": json.dumps(SUMMARY),
        "pairs": PAIRS_TSV,
        "labels": OBJECT_LABELS,
    })


def test_storyboard_presents_the_fitted_statistics_beside_the_landscape(page: Page) -> None:
    result = _mount(page, dict(ARTIFACTS))

    # The bench is the primary surface: the declared matrix landscape beside the
    # model's own fitted statistics, then the ranked-pair evidence, then the
    # durable artifacts.
    assert result["order"] == ["STYLE.", "SECTION.glh-bench", "SECTION.", "DETAILS."]
    assert result["headings"] == ["Fit statistics", "Ranked residue pairs"]
    assert result["kickers"] == ["Model fit", "Comparison evidence"]
    assert result["groupLabels"] == ["Scientific view"]

    # The fit facts are the real captured values, converted by the module's own
    # number formatting, not the fixture's guesses.
    alignment = SUMMARY["alignment"]
    assert result["facts"] == {
        "MSA rows": str(alignment["sequence_count"]),
        "Alignment width": str(alignment["alignment_length"]),
        "Effective rows": "2.8666666",
        "Regularization": SUMMARY["model"]["regularization"],
        "Optimization updates": str(SUMMARY["optimization"]["iterations"]),
        "Final loss": "42.961807",
    }
    assert result["unavailable"] == []


def test_storyboard_pairs_table_carries_the_real_normalized_table(page: Page) -> None:
    result = _mount(page, dict(ARTIFACTS))

    header = PAIRS_TSV.strip().splitlines()[0].split("\t")
    first = PAIRS_TSV.strip().splitlines()[1].split("\t")
    row = dict(zip(header, first))

    # The table's columns are the storyboard's declared reading order, and its
    # first row is the first data row of the published TSV -- identity, query
    # residues and both score columns, not a fixture's values.
    assert result["tableHead"] == ["Rank", "Alignment pair", "Query residues", "Raw score", "APC score ↓", "Separation"]
    assert result["firstRow"] == [
        row["rank"],
        f'{row["alignment_i"]} ↔ {row["alignment_j"]}',
        f'{row["query_residue_i"]} / {row["query_residue_j"]}',
        row["raw_score"],
        row["apc_score"],
        row["sequence_separation"],
    ]
    # The upper-triangle pair the fit ranks first opens in the readout.
    assert result["readout"].endswith(f'Raw  {row["raw_score"]}APC  {row["apc_score"]}')
    # The table is bounded, and the foot states the real published pair count.
    published = len(PAIRS_TSV.strip().splitlines()) - 1
    assert result["rowCount"] == 20
    assert result["foot"] == f"20 of {published} pairs · ordered by APC score"


def test_storyboard_navigates_to_declared_views_instead_of_rendering_couplings(page: Page) -> None:
    result = _mount(page, dict(ARTIFACTS), views=VIEWS_WITHOUT_MATRIX)

    # The workspace declared no matrix view, so the landscape offers no coupling
    # tab and renders no matrix of its own: it does not substitute a renderer for
    # a view the task never declared.
    assert result["viewButtons"] == ["filtered_alignment"]
    assert result["canvas"] == 0

    # The alignment view is the declared one, and navigating opens that view id
    # through the task's own renderer.
    assert TAB_LABELS["filtered_alignment"] in result["tabs"]
    page.locator('.glh-landscape [data-view-id="filtered_alignment"]').click()
    assert page.evaluate("window.__glh.mounted") == ["filtered_alignment"]
    assert page.evaluate("window.__glh.pressed()") == ["filtered_alignment"]

    # A durable object routes to download and a metadata object to preview.
    assert result["downloaded"] == ["mrf_model"]
    assert result["opened"] == ["model_metadata"]


def test_storyboard_offers_the_declared_primary_matrix_view(page: Page) -> None:
    result = _mount(page, dict(ARTIFACTS), views=VIEWS)

    # The raw Frobenius matrix is the declared primary view, so the landscape
    # opens it through the server's own renderer; APC keeps its tab beside it.
    assert result["viewButtons"] == ["raw_couplings", "apc_couplings", "filtered_alignment"]
    assert result["tabs"] == ["Raw couplings", "APC corrected", "Alignment"]
    # The declared primary opens the landscape on mount; the comparison is a click.
    assert result["mounted"] == ["raw_couplings", "apc_couplings"]
    # Clicking the comparison tab mounts that declared view and marks it pressed.
    assert result["pressed"] == ["apc_couplings"]
    assert "ranked_pairs" not in result["viewButtons"]


def test_storyboard_marks_an_unpublished_object_instead_of_offering_it(page: Page) -> None:
    files = {key: value for key, value in ARTIFACTS.items() if key != "mrf_model"}
    result = _mount(page, files, views=[])

    # An object the run did not publish is stated as such and offers no action,
    # while the published ones keep theirs.
    assert any(item == "MRF model (NPZ)Not published" for item in result["provenance"]), result["provenance"]
    assert "Model metadataOpen" in result["provenance"]
    assert result["clicked"]["rawMatrix"] is False
    assert result["unavailable"] == []
    # With no declared views the landscape offers no view tab at all.
    assert result["tabs"] == []
