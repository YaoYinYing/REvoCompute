# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[1] / "revocompute" / "static"
TEMPLATE = Path(__file__).resolve().parents[1] / "revocompute" / "templates" / "task_results.html"


def _task_results_html() -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("{{ static_version }}", "test")
    html = html.replace("{{ task.task_type }}", "easifa")
    html = html.replace("{{ task.fasta_fn }}", "enzyme.pdb")
    html = html.replace("{{ task.md5 }}", "0123456789abcdef0123456789abcdef")
    html = html.replace(
        "{{ task | tojson }}",
        json.dumps(
            {
                "task_type": "easifa",
                "fasta_fn": "enzyme.pdb",
                "md5": "0123456789abcdef0123456789abcdef",
                "status": "finished",
            }
        ),
    )
    return html


def _manifest(
    *,
    structure_path: str = "enzyme_structure.pdb",
    confidence_encoding: str | None = None,
    artifact_count: int = 0,
    empty_tree: bool = False,
    extra_structures: int = 0,
) -> dict:
    artifacts = [
        {
            "path": "active_sites.csv",
            "size": 96,
            "sha256": "a" * 64,
            "media_type": "text/csv",
            "preview": "table",
            "role": "primary",
            "url": "/compute/api/results/task/artifacts/active_sites.csv",
        },
        {
            "path": structure_path,
            "size": 80,
            "sha256": "b" * 64,
            "media_type": "chemical/x-pdb" if structure_path.endswith(".pdb") else "chemical/x-mmcif",
            "preview": "structure",
            "role": "primary",
            "url": f"/compute/api/results/task/artifacts/{structure_path}",
        },
        {
            "path": "execution/slurm-job.stdout.log",
            "size": 10,
            "sha256": "c" * 64,
            "media_type": "text/plain",
            "preview": "text",
            "role": "diagnostic",
            "url": "/compute/api/results/task/artifacts/execution/slurm-job.stdout.log",
        },
    ]
    manifest = {
        "schema_version": 3,
        "task_id": "0123456789abcdef0123456789abcdef",
        "task_type": "easifa",
        "status": "finished",
        "run": {
            "method": {
                "id": "easifa",
                "name": "EasIFA2 Active Sites",
                "summary": "Active-site annotation.",
                "output_summary": "Residue-level active-site annotations linked to the submitted enzyme structure.",
            },
            "inputs": [{"path": "enzyme.pdb", "sha256": "d" * 64}],
            "parameters": [{"name": "reaction_smiles", "label": "Reaction context", "value": "", "unit": ""}],
            "submitted_at": "2026-08-26T08:00:00+00:00",
            "started_at": "2026-08-26T08:01:00+00:00",
            "finished_at": "2026-08-26T08:02:00+00:00",
            "walltime_seconds": 60,
            "citations": [],
        },
        "output_check": {"state": "passed", "checks": [], "problems": []},
        "limitations": ["Predictions require biochemical interpretation."],
        "views": [
            {
                "id": "active_sites",
                "plugin": "entity-table",
                "role": "primary",
                "title": "Active-site mapping",
                "description": "Predicted active-site residues in the submitted enzyme structure.",
                "sources": {"table": ["active_sites.csv"], "structure": [structure_path]},
                "mapping": {
                    "entity": "residue",
                    "key_columns": ["chain", "residue_index"],
                    "label_column": "site_name",
                    "chain_column": "chain",
                    "residue_column": "residue_index",
                    "numbering": "label_seq_id",
                    "evidence_columns": ["site_class", "probabilities"],
                },
            }
        ],
        "artifacts": artifacts,
        "total_size": sum(item["size"] for item in artifacts),
        "archive": {"ready": False, "request_url": "/archive", "download_url": None},
    }
    if confidence_encoding:
        artifacts[1]["confidence_encoding"] = confidence_encoding
    if empty_tree:
        artifacts = []
    manifest["artifacts"] = artifacts
    for index in range(extra_structures):
        path = f"models/model_{index:02d}.pdb"
        artifacts.append(
            {
                "path": path,
                "size": 80 + index,
                "sha256": ("%064x" % (100 + index)),
                "media_type": "chemical/x-pdb",
                "preview": "structure",
                "role": "evidence",
                "url": f"/compute/api/results/task/artifacts/{path}",
            }
        )
    for index in range(artifact_count):
        directory = "outputs/models" if index % 2 else "outputs/tables"
        artifacts.append(
            {
                "path": f"{directory}/result_item_{index:03d}.dat",
                "size": 32 + index,
                "sha256": ("%064x" % index),
                "media_type": "application/octet-stream",
                "preview": None,
                "role": "evidence",
                "url": f"/compute/api/results/task/artifacts/{directory}/result_item_{index:03d}.dat",
            }
        )
    manifest["total_size"] = sum(item["size"] for item in artifacts)
    return manifest


def _add_protocol_fixtures(manifest: dict) -> None:
    fixtures = [
        ("confidence.json", "application/json", "text", 80),
        ("pae.json", "application/json", "text", 80),
        ("summary.json", "application/json", "text", 80),
        ("input.a3m", "application/octet-stream", "text", 40),
        ("topology.pdb", "chemical/x-pdb", "structure", 80),
        ("samples.xtc", "application/octet-stream", None, 24),
    ]
    for index, (path, media_type, preview, size) in enumerate(fixtures):
        manifest["artifacts"].append(
            {
                "path": path,
                "size": size,
                "sha256": chr(ord("d") + index) * 64,
                "media_type": media_type,
                "preview": preview,
                "role": "evidence",
                "url": f"/compute/api/results/task/artifacts/{path}",
            }
        )
    manifest["views"].extend(
        [
            {
                "id": "confidence",
                "plugin": "metric-series",
                "role": "evidence",
                "title": "Residue confidence",
                "description": "Per-residue confidence.",
                "sources": {"series": ["confidence.json"]},
                "mapping": {
                    "format": "json",
                    "value_path": "values",
                    "x_label": "Residue",
                    "y_label": "pLDDT",
                    "unit": "score",
                    "direction": "higher",
                    "missing": "null",
                    "y_min": 0,
                    "y_max": 100,
                },
            },
            {
                "id": "pae",
                "plugin": "matrix",
                "role": "evidence",
                "title": "Predicted aligned error",
                "description": "Pairwise error.",
                "sources": {"matrices": ["pae.json"]},
                "mapping": {
                    "format": "json",
                    "value_path": "values",
                    "x_label": "Aligned residue",
                    "y_label": "Scored residue",
                    "unit": "Å",
                    "direction": "lower",
                    "scale": "sequential",
                    "scale_min": 0,
                    "scale_max": 30,
                },
            },
            {
                "id": "summary",
                "plugin": "scalar-summary",
                "role": "evidence",
                "title": "Global confidence",
                "description": "Global confidence values.",
                "sources": {"data": ["summary.json"]},
                "mapping": {"fields": [{"path": "ptm", "label": "pTM", "unit": "score", "direction": "higher"}]},
            },
            {
                "id": "alignment",
                "plugin": "alignment",
                "role": "evidence",
                "title": "Input alignment",
                "description": "Aligned sequences.",
                "sources": {"alignment": ["input.a3m"]},
                "mapping": {"format": "a3m", "numbering": "sequence"},
            },
            {
                "id": "ensemble",
                "plugin": "trajectory",
                "role": "evidence",
                "title": "Conformational ensemble",
                "description": "Sampled conformations.",
                "sources": {"topology": ["topology.pdb"], "coordinates": ["samples.xtc"]},
                "mapping": {"coordinate_format": "xtc", "frame_unit": "sample", "timestep": 1, "association": "single"},
            },
        ]
    )
    manifest["total_size"] = sum(item["size"] for item in manifest["artifacts"])


def _open_result_page(
    page: Page,
    delay_second_viewer: bool = False,
    protocols: bool = False,
    *,
    structure_path: str = "enzyme_structure.pdb",
    confidence_encoding: str | None = None,
    artifact_count: int = 0,
    empty_tree: bool = False,
    extra_structures: int = 0,
) -> None:
    page.route("https://fonts.googleapis.com/**", lambda route: route.abort())
    page.route("https://fonts.gstatic.com/**", lambda route: route.abort())
    html = _task_results_html()
    manifest = _manifest(
        structure_path=structure_path,
        confidence_encoding=confidence_encoding,
        artifact_count=artifact_count,
        empty_tree=empty_tree,
        extra_structures=extra_structures,
    )
    if protocols:
        _add_protocol_fixtures(manifest)
    pdb = "ATOM      1  CA  GLY A  28      10.000  10.000  10.000  1.00 20.00           C\nEND\n"
    shell = """<script>
    parent.postMessage({type: 'shell-ready'}, '*');
    window.addEventListener('message', function (event) {
      if (event.data.type === 'structure') parent.postMessage({type: 'ready', requestId: event.data.requestId}, '*');
      if (event.data.type === 'trajectory') {
        parent.postMessage({type: 'trajectory-ready', requestId: event.data.requestId, frame: 0, frameCount: 3}, '*');
      }
      if (event.data.type === 'trajectory-control') {
        var frame = event.data.action === 'set' ? event.data.value : 1;
        parent.postMessage({type: 'trajectory-frame', frame: frame, frameCount: 3}, '*');
      }
      if (event.data.type === 'select-residue') parent.postMessage({type: 'selected', payload: event.data}, '*');
      if (event.data.type === 'dispose') parent.postMessage({type: 'disposed'}, '*');
    });
    </script>"""
    page.route(
        "https://revocompute.example/compute/results/*",
        lambda route: route.fulfill(content_type="text/html", body=html),
    )
    page.route(
        "https://revocompute.example/static/js/*",
        lambda route: route.fulfill(
            content_type="application/javascript",
            body=(STATIC / "js" / route.request.url.split("/static/js/", 1)[1].split("?", 1)[0]).read_text(
                encoding="utf-8"
            ),
        ),
    )
    page.route(
        "https://revocompute.example/static/css/*",
        lambda route: route.fulfill(
            content_type="text/css",
            body=(STATIC / "css" / route.request.url.split("/static/css/", 1)[1].split("?", 1)[0]).read_text(
                encoding="utf-8"
            ),
        ),
    )
    page.route(
        "https://revocompute.example/compute/api/auth/token", lambda route: route.fulfill(json={"token": "test-token"})
    )
    page.route(
        "https://revocompute.example/compute/api/results/*/tables/active_sites.csv*",
        lambda route: route.fulfill(
            json={
                "columns": ["chain", "residue_index", "residue", "site_class", "site_name", "probabilities"],
                "rows": [["A", "28", "G", "active", "Binding site", "[0.1,0.9]"]],
                "offset": 0,
                "limit": 100,
                "has_more": False,
            }
        ),
    )
    page.route(
        f"https://revocompute.example/compute/api/results/task/artifacts/{structure_path}*",
        lambda route: route.fulfill(content_type="chemical/x-pdb", body=pdb),
    )
    structure_downloads: list[str] = []

    def serve_structure(route):
        structure_downloads.append(route.request.url)
        route.fulfill(content_type="chemical/x-pdb", body=pdb)

    page.route(
        "https://revocompute.example/compute/api/results/task/artifacts/models/*",
        serve_structure,
    )
    page.route(
        "https://revocompute.example/compute/api/results/task/artifacts/confidence.json*",
        lambda route: route.fulfill(json={"values": [72, 84, 91]}),
    )
    page.route(
        "https://revocompute.example/compute/api/results/task/artifacts/pae.json*",
        lambda route: route.fulfill(json={"values": [[1, 8], [7, 2]]}),
    )
    page.route(
        "https://revocompute.example/compute/api/results/task/artifacts/summary.json*",
        lambda route: route.fulfill(json={"ptm": 0.82}),
    )
    page.route(
        "https://revocompute.example/compute/api/results/task/artifacts/input.a3m*",
        lambda route: route.fulfill(body=">query\nACDE\n>homolog\nAC-E\n"),
    )
    page.route(
        "https://revocompute.example/compute/api/results/task/artifacts/topology.pdb*",
        lambda route: route.fulfill(content_type="chemical/x-pdb", body=pdb),
    )
    page.route(
        "https://revocompute.example/compute/api/results/task/artifacts/samples.xtc*",
        lambda route: route.fulfill(content_type="application/octet-stream", body=b"mock-xtc"),
    )
    page.route("https://revocompute.example/compute/api/results/*", lambda route: route.fulfill(json=manifest))
    viewer_requests = 0

    def serve_viewer(route):
        nonlocal viewer_requests
        viewer_requests += 1
        body = "<script></script>" if delay_second_viewer and viewer_requests == 2 else shell
        route.fulfill(content_type="text/html", body=body)

    page.route("https://revocompute.example/compute/viewer-shell", serve_viewer)
    page.goto("https://revocompute.example/compute/results/0123456789abcdef0123456789abcdef")
    page.add_style_tag(
        content="*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}"
    )
    page.structure_downloads = structure_downloads


def _workspace_tracks(page: Page) -> list[str]:
    columns = page.locator(".result-workspace").evaluate("node => getComputedStyle(node).gridTemplateColumns")
    return columns.strip().split()


def test_result_page_opens_principal_view_without_shortlist(page: Page) -> None:
    _open_result_page(page)
    expect(page.get_by_text("EasIFA2 Active Sites")).to_be_visible()
    expect(page.get_by_text("Expected outputs found")).to_be_visible()
    expect(page.get_by_role("heading", name="Active-site mapping")).to_be_visible()
    expect(page.get_by_text("Binding site")).to_be_visible()

    expect(page.get_by_text("Review shortlist")).to_have_count(0)
    expect(page.locator(".decision-rail, .candidate-select")).to_have_count(0)
    expect(page.get_by_text("Outcome", exact=True)).to_have_count(0)
    expect(page.get_by_text("Evidence", exact=True)).to_have_count(0)
    expect(page.get_by_text("Selection", exact=True)).to_have_count(0)

    # Desktop result workspace: flexible primary content beside a controlled rail.
    tracks = _workspace_tracks(page)
    assert len(tracks) == 2, tracks
    rail_width = page.locator(".artifact-rail").bounding_box()["width"]
    assert 320 <= rail_width <= 420, rail_width
    assert page.locator(".result-workspace > .preview-workspace").count() == 1
    assert page.locator(".result-workspace > .result-record").count() == 1


def test_result_page_keeps_artifacts_fallback_and_native_space(page: Page) -> None:
    _open_result_page(page)
    files_diagnostics = page.locator("details.artifact-section > summary")
    expect(files_diagnostics).to_contain_text("Files & diagnostics")
    search = page.get_by_label("Filter result artifacts")
    expect(search).to_be_visible()
    search.fill("stdout")
    search.press("Space")
    expect(search).to_have_value("stdout ")
    # Leaves show the basename; the full relative path stays available on the row.
    log_button = page.locator('.artifact-row[title="execution/slurm-job.stdout.log"]')
    expect(log_button).to_be_visible()
    expect(log_button).to_contain_text("Execution log · 10 B")
    log_button.click()
    expect(page.get_by_role("heading", name="execution/slurm-job.stdout.log")).to_be_visible()
    expect(page.get_by_role("link", name="Download file")).to_be_visible()

    search.fill("enzyme_structure")
    page.locator(".artifact-row", has_text="enzyme_structure.pdb").click()
    expect(page.get_by_role("heading", name="enzyme_structure.pdb")).to_be_visible()
    expect(page.locator(".preview-workspace > .artifact-preview-stage")).to_have_count(1)
    expect(page.locator("iframe.artifact-molstar-preview")).to_be_visible()


def test_result_file_tree_uses_basenames_and_collapsible_folders(page: Page) -> None:
    _open_result_page(page)
    tree = page.locator("#artifactList")
    # Folder nodes communicate hierarchy; leaves do not repeat the full path.
    log_leaf = tree.locator(".artifact-row", has_text="slurm-job.stdout.log")
    expect(log_leaf.locator(".artifact-row-name")).to_have_text("slurm-job.stdout.log")
    expect(log_leaf).to_have_attribute("title", "execution/slurm-job.stdout.log")

    folder = tree.locator("details.artifact-folder").first
    expect(folder).to_have_attribute("open", "")
    folder.locator("summary").click()
    expect(folder).not_to_have_attribute("open", "")
    folder.locator("summary").click()
    expect(folder).to_have_attribute("open", "")

    # A flat search still disambiguates duplicate basenames through the directory hint.
    search = page.get_by_label("Filter result artifacts")
    search.fill("slurm-job.stdout")
    row = tree.locator(".artifact-row").first
    expect(row.locator(".artifact-row-dir")).to_have_text("execution/")


def test_result_page_collapses_workspace_at_mobile_width(page: Page) -> None:
    page.set_viewport_size({"width": 430, "height": 932})
    structure_path = "prediction_with_a_very_long_artifact_name_model_001.cif"
    _open_result_page(page, protocols=True, structure_path=structure_path, confidence_encoding="plddt_bfactor")
    tracks = _workspace_tracks(page)
    assert len(tracks) == 1 and tracks[0] != "none", tracks
    expect(page.locator(".decision-rail")).to_have_count(0)
    expect(page.locator(".result-view-tab")).to_have_count(6)
    # Mobile exposes the file rail through a controlled disclosure below the result.
    expect(page.locator("details.artifact-section")).not_to_have_attribute("open", "")
    page.locator("details.artifact-section").evaluate("node => node.open = true")
    page.locator(".artifact-row", has_text=structure_path).click()
    expect(page.locator("iframe.artifact-molstar-preview")).to_be_visible()
    expect(page.locator('button.preset-toggle[data-preset="confidence"]')).to_be_visible()
    assert page.locator(".result-view-tabs").evaluate("node => node.scrollWidth > node.clientWidth")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_result_file_tree_handles_empty_and_large_inventories(page: Page) -> None:
    _open_result_page(page, artifact_count=120)
    tree = page.locator("#artifactList")
    assert tree.locator(".artifact-row").count() == 123
    expect(page.locator("#artifactSummary")).to_contain_text("123 files")
    # The rail bounds its inventory and scrolls in place rather than growing the page.
    rail = page.locator(".artifact-rail")
    assert rail.bounding_box()["height"] <= 720
    tree_scrolls = page.locator("#artifactList").evaluate(
        "node => node.scrollHeight > node.clientHeight && getComputedStyle(node).overflowY === 'auto'"
    )
    assert tree_scrolls
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")

    page.get_by_label("Filter result artifacts").fill("result_item_00")
    assert tree.locator(".artifact-row").count() == 10


def test_result_file_tree_handles_an_empty_inventory(page: Page) -> None:
    _open_result_page(page, empty_tree=True)
    expect(page.locator("#artifactList .artifact-row")).to_have_count(0)
    expect(page.locator("#artifactSummary")).to_contain_text("0 files")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


@pytest.mark.parametrize(
    "width,two_region",
    [(1440, True), (1280, True), (1100, True), (1024, False), (900, False), (768, False), (390, False), (320, False)],
)
def test_result_workspace_regions_follow_viewport_width(page: Page, width: int, two_region: bool) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    _open_result_page(page)
    tracks = _workspace_tracks(page)
    assert (len(tracks) == 2) is two_region, (width, tracks)
    if two_region:
        rail_width = page.locator(".artifact-rail").bounding_box()["width"]
        assert 320 <= rail_width <= 420, (width, rail_width)
        primary = page.locator(".preview-workspace").bounding_box()["width"]
        assert primary >= rail_width, (width, primary, rail_width)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_result_workspace_dom_order_matches_visual_order(page: Page) -> None:
    _open_result_page(page)
    order = page.locator(".result-workspace").evaluate(
        """node => ['.preview-workspace', '.artifact-rail', '.result-record']
          .map(selector => Array.from(node.children).findIndex(child => child.matches(selector)))"""
    )
    assert order == [0, 1, 2], order

    preview = page.locator(".preview-workspace").bounding_box()
    rail = page.locator(".artifact-rail").bounding_box()
    records = page.locator(".result-record").bounding_box()
    assert rail["x"] >= preview["x"] + preview["width"] - 1
    assert records["y"] >= preview["y"] + preview["height"] - 1

    # The file workspace is reachable by keyboard in DOM order.
    page.locator("#artifactSearch").focus()
    assert page.evaluate("document.activeElement && document.activeElement.id") == "artifactSearch"


@pytest.mark.parametrize("structure_path", ["prediction.pdb", "prediction.cif"])
def test_structure_color_exposes_plddt_only_from_declared_confidence(page: Page, structure_path: str) -> None:
    _open_result_page(page, structure_path=structure_path, confidence_encoding="plddt_bfactor")
    page.locator("details.artifact-section").evaluate("node => node.open = true")
    page.locator(".artifact-row", has_text=structure_path).click()
    expect(page.locator('button.preset-toggle[data-preset="confidence"]')).to_have_count(1)
    # A representation preset is offered alongside the color presets.
    expect(page.locator('button.preset-toggle[data-preset="cartoon_ligand"]')).to_be_visible()


def test_structure_color_hides_plddt_without_confidence_metadata(page: Page) -> None:
    _open_result_page(page)
    page.locator("details.artifact-section").evaluate("node => node.open = true")
    page.locator(".artifact-row", has_text="enzyme_structure.pdb").click()
    expect(page.locator('button.preset-toggle[data-preset="confidence"]')).to_have_count(0)
    expect(page.locator('button.preset-toggle[data-preset="chain"]')).to_be_visible()


def test_result_page_cancels_delayed_warm_viewer_on_artifact_switch(page: Page) -> None:
    _open_result_page(page, delay_second_viewer=True)
    expect(page.get_by_role("heading", name="Active-site mapping")).to_be_visible()
    page.locator("details.artifact-section").evaluate("node => node.open = true")
    page.locator(".artifact-row", has_text="enzyme_structure.pdb").evaluate("node => node.click()")
    expect(page.locator("iframe.artifact-molstar-preview")).to_have_count(1)
    page.locator(".artifact-row", has_text="slurm-job.stdout.log").evaluate("node => node.click()")
    expect(page.get_by_role("heading", name="execution/slurm-job.stdout.log")).to_be_visible()
    expect(page.locator("iframe.artifact-molstar-preview")).to_have_count(0, timeout=3000)


def test_scientific_protocol_views_are_interactive_and_accessible(page: Page) -> None:
    _open_result_page(page, protocols=True)

    page.get_by_role("button", name="Residue confidence").click()
    expect(page.get_by_role("img", name="pLDDT by Residue")).to_be_visible()
    expect(page.get_by_text("Higher is favourable")).to_be_visible()

    page.get_by_role("button", name="Predicted aligned error").click()
    matrix = page.get_by_role("grid", name="Predicted aligned error; use arrow keys to inspect cells")
    expect(matrix).to_be_visible()
    matrix.focus()
    matrix.press("ArrowRight")
    expect(page.get_by_role("status").filter(has_text="Aligned residue 2")).to_be_visible()

    page.get_by_role("button", name="Global confidence").click()
    expect(page.get_by_text("0.82 score")).to_be_visible()

    page.get_by_role("button", name="Input alignment").click()
    expect(page.get_by_text("Columns use sequence numbering")).to_be_visible()

    page.get_by_role("button", name="Conformational ensemble").click()
    expect(page.get_by_label("Trajectory frame")).to_have_attribute("max", "2")
    page.get_by_role("button", name="Next").click()
    expect(page.get_by_text("2 / 3 · 1 sample")).to_be_visible()


def _structure_row(page: Page, path: str):
    return page.locator(f'.artifact-row[title="{path}"]')


def _structure_downloads(page: Page, path: str) -> int:
    return sum(1 for url in page.structure_downloads if path in url)


def test_structure_switch_reuses_one_viewer_and_keeps_the_preset(page: Page) -> None:
    _open_result_page(page, extra_structures=2)
    page.locator("details.artifact-section").evaluate("node => node.open = true")
    _structure_row(page, "models/model_00.pdb").click()
    expect(page.locator("iframe.artifact-molstar-preview")).to_have_count(1)
    # Tag the live host: if switching structures recreates the viewer, the tag
    # disappears with the old iframe.
    assert page.evaluate(
        "() => { const f = document.querySelector('iframe.artifact-molstar-preview');"
        " if (!f) return false; f.dataset.hostProbe = 'kept'; return true; }"
    )

    page.get_by_role("button", name="Sticks", exact=True).click()
    expect(page.locator('button.preset-toggle[data-preset="sticks"]')).to_have_attribute("aria-pressed", "true")

    _structure_row(page, "models/model_01.pdb").click()
    expect(page.get_by_role("heading", name="models/model_01.pdb")).to_be_visible()
    expect(page.locator("iframe.artifact-molstar-preview")).to_have_count(1)
    assert page.evaluate(
        "() => (document.querySelector('iframe.artifact-molstar-preview') || {}).dataset?.hostProbe === 'kept'"
    )
    expect(page.locator('button.preset-toggle[data-preset="sticks"]')).to_have_attribute("aria-pressed", "true")


def test_structure_cache_serves_a_revisited_artifact_without_refetching(page: Page) -> None:
    _open_result_page(page, extra_structures=2)
    page.locator("details.artifact-section").evaluate("node => node.open = true")
    _structure_row(page, "models/model_00.pdb").click()
    expect(page.get_by_role("heading", name="models/model_00.pdb")).to_be_visible()
    first = _structure_downloads(page, "model_00.pdb")
    assert first == 1, first

    _structure_row(page, "models/model_01.pdb").click()
    expect(page.get_by_role("heading", name="models/model_01.pdb")).to_be_visible()
    _structure_row(page, "models/model_00.pdb").click()
    expect(page.get_by_role("heading", name="models/model_00.pdb")).to_be_visible()
    assert _structure_downloads(page, "model_00.pdb") == first


def test_prefetch_stays_bounded_to_adjacent_structures(page: Page) -> None:
    _open_result_page(page, extra_structures=6)
    page.locator("details.artifact-section").evaluate("node => node.open = true")
    _structure_row(page, "models/model_00.pdb").click()
    expect(page.get_by_role("heading", name="models/model_00.pdb")).to_be_visible()
    # A seven-structure result must never be downloaded wholesale.
    assert _structure_downloads(page, "model_05.pdb") == 0
    assert _structure_downloads(page, "model_06.pdb") == 0
