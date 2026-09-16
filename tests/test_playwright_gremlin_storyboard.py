# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser contract for the GREMLIN_LH result storyboard module.

The storyboard is Runner-owned JavaScript executed by the result page. This test
loads the real module, mounts it with the documented context API, and verifies
that it composes inline inspection only for URL-previewable image artifacts and
offers downloads for everything else (nested tables, JSON, and the MRF).
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
STORYBOARD = ROOT / "docker" / "runners" / "gremlin_lh" / "storyboard" / "index.js"

# Mirrors the logical-file record the server returns for a storyboard
# (`revocompute/routes.py`): `preview` is the declared expected-file type and
# `media_type` is the detected transport type.
ARTIFACTS = {
    "alignment": {"id": "alignment", "path": "alignment/filtered_alignment.a3m", "preview": "alignment", "media_type": "text/plain"},
    "alignment_statistics": {"id": "alignment_statistics", "path": "alignment/statistics.json", "preview": "json", "media_type": "application/json"},
    "sequence_weights": {"id": "sequence_weights", "path": "alignment/sequence_weights.tsv", "preview": "table", "media_type": "text/tab-separated-values"},
    "query": {"id": "query", "path": "query.fasta", "preview": "fasta", "media_type": "text/plain"},
    "mrf_model": {"id": "mrf_model", "path": "model/gremlin_mrf.npz", "preview": "model", "media_type": "application/octet-stream"},
    "model_metadata": {"id": "model_metadata", "path": "model/metadata.json", "preview": "json", "media_type": "application/json"},
    "training_history": {"id": "training_history", "path": "model/training_history.csv", "preview": "table", "media_type": "text/csv"},
    "sequence_scores": {"id": "sequence_scores", "path": "model/sequence_scores.tsv", "preview": "table", "media_type": "text/tab-separated-values"},
    "profile": {"id": "profile", "path": "profiles/profile.tsv", "preview": "table", "media_type": "text/tab-separated-values"},
    "pairwise_scores": {"id": "pairwise_scores", "path": "couplings/pairwise_scores.tsv", "preview": "table", "media_type": "text/tab-separated-values"},
    "raw_matrix": {"id": "raw_matrix", "path": "couplings/raw_scores.csv", "preview": "table", "media_type": "text/csv"},
    "apc_matrix": {"id": "apc_matrix", "path": "couplings/apc_scores.csv", "preview": "table", "media_type": "text/csv"},
    "coupling_plot": {"id": "coupling_plot", "path": "plots/coupling_apc.png", "preview": "image", "media_type": "image/png"},
    "summary": {"id": "summary", "path": "summary.json", "preview": "json", "media_type": "application/json"},
}

MOUNT = """
async (payload) => {
  const url = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(url);
  const files = new Map(Object.entries(payload.files).map(([id, artifact]) => [id, Object.assign({
    name: artifact.path.split("/").pop(),
    url: "/compute/api/results/abc/files/" + id + "?index=0",
    size: 1024,
  }, artifact)]));
  const opened = [];
  const context = {
    files: { get: (id) => files.get(id) || null },
    metadata: { taskType: "gremlin_lh_fit" },
    services: { openFile: (artifact) => { opened.push(artifact.id); } },
  };
  const host = document.getElementById("host");
  module.default.mount(host, context);
  const buttons = Array.from(host.querySelectorAll("button"));
  const imageButton = buttons.find((node) => node.textContent.includes("coupling heatmap"));
  if (imageButton) imageButton.click();
  return {
    opened,
    buttons: buttons.map((node) => node.textContent),
    links: Array.from(host.querySelectorAll("a")).map((node) => ({
      text: node.textContent, href: node.getAttribute("href"),
    })),
    unavailable: Array.from(host.querySelectorAll(".storyboard-unavailable")).map((node) => node.textContent),
  };
}
"""


def _mount(page: Page, files: dict[str, dict[str, str]]) -> dict:
    page.set_content("<div id='host'></div>")
    return page.evaluate(MOUNT, {"source": STORYBOARD.read_text(encoding="utf-8"), "files": files})


def test_storyboard_inspects_images_and_downloads_other_artifacts(page: Page) -> None:
    result = _mount(page, ARTIFACTS)

    assert result["unavailable"] == []
    assert len(result["buttons"]) == 1, result["buttons"]
    assert any("coupling heatmap" in label for label in result["buttons"])

    # Only the image is opened inline; the clicked button forwards the logical
    # artifact to the server-owned previewer.
    assert result["opened"] == ["coupling_plot"]

    links = {entry["text"]: entry["href"] for entry in result["links"]}
    assert len(links) == 13, links
    for label in ("GREMLIN MRF model (NPZ)", "filtered alignment (A3M)", "position profile (TSV)", "summary JSON"):
        href = links[f"Download {label}"]
        assert href.endswith("download=1"), href


def test_storyboard_marks_unresolved_logical_files_unavailable(page: Page) -> None:
    files = {key: value for key, value in ARTIFACTS.items() if key != "mrf_model"}
    result = _mount(page, files)
    expect(page.locator(".storyboard-unavailable")).to_have_count(1)
    assert "GREMLIN MRF model (NPZ) unavailable" in result["unavailable"]
