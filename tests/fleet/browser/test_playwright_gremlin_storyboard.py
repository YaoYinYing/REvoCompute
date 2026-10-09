# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser contract for the GREMLIN_LH result storyboard module.

The storyboard is Runner-owned JavaScript executed by the result page. This test
loads the real module, mounts it with the documented context API, and verifies
that it composes a question-ordered scientific narrative: alignment metrics,
effective-information metrics, model identity, and navigation to the task's own
declared result views rather than a re-implemented matrix renderer.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import install_scientific_assets

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
STORYBOARD = ROOT / "docker" / "runners" / "gremlin_lh" / "storyboard" / "index.js"

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

# The small JSON evidence files the narrative reads directly. Their `url` is
# replaced with a data URL so the module can fetch them in the browser test.
STATISTICS = {
    "sequence_count": 8,
    "alignment_length": 8,
    "query_length": 8,
    "columns_excluded_by_gap_cutoff": 8,
    "mean_gap_fraction": 0.05,
    "effective_sequence_count": 6.5,
    "identity_cutoff": 0.8,
    "gap_cutoff": 0.5,
}
METADATA = {
    "positions": 8,
    "states": 21,
    "regularization": "LH",
    "arrays": {"couplings": {"shape": [8, 21, 8, 21]}},
    "parameters": {"use_bias": True},
}

# The views this task declares in its own task.yaml; the storyboard may only
# navigate to these, never render them itself. The raw Frobenius matrix is the
# declared primary (contact-oriented) view; APC is the comparison.
MATRIX_VIEWS = [
    {
        "id": "raw_couplings", "plugin": "matrix", "role": "primary", "title": "Raw coupling strengths",
        "sources": {"matrices": [{"path": "couplings/raw_scores.csv"}]},
    },
    {
        "id": "apc_couplings", "plugin": "matrix", "role": "evidence", "title": "APC-corrected coupling strengths",
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
# A workspace that declared no matrix view at all, so the coupling section has to
# fall back to the generic artifact preview for both matrices.
VIEWS_WITHOUT_MATRIX = OTHER_VIEWS

MOUNT = """
async (payload) => {
  const url = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(url);
  const files = new Map(Object.entries(payload.files).map(([id, artifact]) => [id, Object.assign({
    name: artifact.path.split("/").pop(),
    url: "/compute/api/results/abc/files/" + id + "?index=0",
    size: 1024,
  }, artifact)]));
  const asDataUrl = (value) => "data:application/json," + encodeURIComponent(JSON.stringify(value));
  files.set("alignment_statistics", Object.assign({}, files.get("alignment_statistics"), { url: asDataUrl(payload.statistics) }));
  files.set("model_metadata", Object.assign({}, files.get("model_metadata"), { url: asDataUrl(payload.metadata) }));
  const opened = [];
  const downloaded = [];
  const viewed = [];
  const context = {
    files: { get: (id) => files.get(id) || null },
    metadata: { taskType: "gremlin_lh_fit" },
    views: payload.views,
    services: {
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
  const clickFile = (fileId, prefix) => {
    const node = Array.from(host.querySelectorAll("button[data-file-id]")).find(
      (item) => item.dataset.fileId === fileId && (!prefix || item.textContent.startsWith(prefix)),
    );
    if (node) node.click();
    return Boolean(node);
  };
  const metrics = Array.from(host.querySelectorAll(".scalar-grid")).map((grid) => {
    const values = {};
    grid.querySelectorAll("dt").forEach((term) => {
      values[term.textContent] = term.nextElementSibling ? term.nextElementSibling.textContent : null;
    });
    return values;
  });
  const clicked = {
    rawMatrix: clickFile("raw_matrix", "Open"),
    mrfModel: clickFile("mrf_model", "Download"),
    modelMetadata: clickFile("model_metadata", "Open"),
  };
  clickView("apc_couplings");
  clickView("ranked_pairs");
  await new Promise((resolve) => setTimeout(resolve, 0));
  return {
    clicked, opened, downloaded, viewed, metrics,
    sections: Array.from(host.querySelectorAll(".glh-section h3")).map((node) => node.textContent),
    buttons: Array.from(host.querySelectorAll("button")).map((node) => node.textContent),
    viewButtons: Array.from(host.querySelectorAll("button[data-view-id]")).map((node) => node.dataset.viewId),
    unavailable: Array.from(host.querySelectorAll(".glh-unavailable")).map((node) => node.textContent),
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
        "statistics": STATISTICS,
        "metadata": METADATA,
    })


def test_storyboard_presents_the_scientific_narrative_in_order(page: Page) -> None:
    result = _mount(page, dict(ARTIFACTS))

    assert result["sections"] == [
        "What alignment was modelled?",
        "How much independent evolutionary information was present?",
        "What model was fit?",
        "What coupling landscape was inferred?",
        "Which residue pairs carry the strongest statistical coupling?",
        "What model and provenance artifacts are available for downstream analysis?",
    ]
    assert result["unavailable"] == []

    # Alignment and effective-information metrics come from the declared statistics file.
    alignment = result["metrics"][0]
    assert alignment["Modelled sequences"] == "8 rows"
    assert alignment["Alignment width"] == "8 positions"
    information = result["metrics"][1]
    assert information["Effective sequence count (Neff)"] == "6.5 sequences"
    assert information["Identity cutoff for weighting"] == "0.8"

    # Model identity comes from the declared metadata file.
    model = result["metrics"][2]
    assert model["Regularization"] == "LH"
    assert model["Coupling tensor"] == "8 x 21 x 8 x 21"
    assert model["One-site fields"] == "fitted"


def test_storyboard_navigates_to_declared_views_instead_of_rendering_couplings(page: Page) -> None:
    result = _mount(page, dict(ARTIFACTS), views=VIEWS_WITHOUT_MATRIX)

    # The declared entity-table view is offered by title; the task's own renderer
    # opens it, so no second table or matrix renderer is implemented here.
    assert "Open Ranked residue pairs" in result["buttons"]
    assert "ranked_pairs" in result["viewed"]

    # With no declared matrix view, both coupling matrices fall back to the
    # generic artifact preview the server already owns.
    assert result["clicked"]["rawMatrix"] is True
    assert "raw_matrix" in result["opened"]
    assert "Open coupling matrix (raw)" in result["buttons"]
    assert "Open coupling matrix (APC)" in result["buttons"]

    # Provenance entries route the durable model to download and metadata to preview.
    assert result["clicked"]["mrfModel"] is True
    assert result["clicked"]["modelMetadata"] is True
    assert "mrf_model" in result["downloaded"]
    assert "model_metadata" in result["opened"]


def test_storyboard_offers_the_declared_primary_matrix_view(page: Page) -> None:
    result = _mount(page, dict(ARTIFACTS), views=VIEWS)

    # The raw matrix is the declared primary view, so the narrative offers it by
    # title and opens it through the server's own renderer instead of the
    # generic preview. APC remains the explicit comparison beside it.
    assert "Open Raw coupling strengths" in result["buttons"]
    assert "Open APC-corrected coupling strengths" in result["buttons"]
    assert "Open raw coupling matrix" not in result["buttons"]
    assert "raw_couplings" in result["viewButtons"]
    assert "apc_couplings" in result["viewButtons"]


def test_storyboard_marks_unresolved_logical_files_unavailable(page: Page) -> None:
    files = {key: value for key, value in ARTIFACTS.items() if key != "mrf_model"}
    result = _mount(page, files, views=[])

    expect(page.locator(".glh-unavailable")).to_have_count(1)
    assert "Durable MRF model (NPZ) unavailable" in result["unavailable"]

    # Without declared views the coupling section still names the raw matrix it can open.
    assert "Open coupling matrix (raw)" in result["buttons"]
