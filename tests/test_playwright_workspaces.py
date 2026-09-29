# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

STATIC_JS = Path(__file__).resolve().parents[1] / "revocompute" / "static" / "js"
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def test_native_browser_mounts_and_collects_rfdiffusion_workspace(page: Page) -> None:
    page.set_content('<div id="root"></div><input id="files" type="file">')
    page.add_script_tag(path=STATIC_JS / "plugin-host.js")
    page.add_script_tag(path=STATIC_JS / "input-workspace.js")
    page.add_script_tag(
        path=STATIC_JS.parents[2] / "docker" / "runners" / "placer-rfdiffusion" / "workspace" / "regions" / "index.js"
    )
    page.evaluate(
        """
        window.fetch = function () { return Promise.resolve({ok: true, json: function () {
          return Promise.resolve({summary: "normalized"});
        }}); };
        window.REvoDesignAuth = { authFetch: function (url, options) { return window.fetch(url, options); } };
        window.workspace = new window.REvoComputeInputWorkspace.InputWorkspace(
          document.getElementById("root"),
          {fileInput: document.getElementById("files"), status: function () {}}
        );
        window.workspace.mount({
          name: "rfdiffusion", display_name: "RFdiffusion", runtime_family: "placer-rfdiffusion",
          inputs: [{id: "structures", title: "Structures", type: "protein_structure", accept: ".pdb",
            extensions: [".pdb"], cardinality: {min: 0, max: 64}}], max_request_bytes: 16777216,
          params: [
            {name: "design_mode", type: "str", default: "unconditional"},
            {name: "contig", type: "str", default: "100-100"},
            {name: "hotspot_res", type: "str", default: ""},
            {name: "diffuser_b_0", type: "float", default: 0.01, minimum: 0}
          ],
          input_workspace: {version: 3, steps: [
            {id: "material", title: "Input", description: "", capabilities: [
              {plugin: "files", id: "source_files", title: "Files", options: {}}
            ]},
            {id: "intent", title: "Intent", description: "", capabilities: [
              {plugin: "rfdiffusion-regions", id: "design_regions", title: "Regions", options: {
                syntax: "rfdiffusion", fields: ["design_mode", "contig", "hotspot_res"],
                modes: ["unconditional", "motif_scaffolding", "binder", "expert"]
              }}
            ]},
            {id: "review", title: "Review", description: "", capabilities: [
              {plugin: "review", id: "submission_review", title: "Review", options: {}}
            ]}
          ]}
        });
        """
    )
    expect(page.locator("[data-capability-id=design_regions] select")).to_be_visible()
    collected = page.evaluate("window.workspace.collect().design_regions")
    assert collected["mode"] == "unconditional"
    assert collected["segments"] == [{"kind": "generated", "min_length": 100, "max_length": 100}]
    # Fractional float defaults must satisfy native constraint validation
    # (a bare step=1 would flag 0.01 as a step mismatch).
    assert page.evaluate("window.workspace.validate()") == []


def test_semantic_steps_group_alternative_inputs_and_review(page: Page) -> None:
    page.set_content('<div id="root"></div><input id="files" type="file">')
    page.add_script_tag(path=STATIC_JS / "plugin-host.js")
    page.add_script_tag(path=STATIC_JS / "input-workspace.js")
    page.evaluate(
        """
        window.workspace = new window.REvoComputeInputWorkspace.InputWorkspace(
          document.getElementById("root"),
          {fileInput: document.getElementById("files"), status: function () {}}
        );
        window.workspace.mount({
          name: "example", display_name: "Example",
          inputs: [{id: "sequence", title: "Protein sequence", type: "protein_sequence", accept: ".fasta",
            extensions: [".fasta"], cardinality: {min: 1, max: 1}}], max_request_bytes: 16777216,
          params: [],
          input_workspace: {version: 3, steps: [
            {id: "material", title: "Provide sequence", description: "", capabilities: [
              {plugin: "files", id: "source_files", title: "Files", options: {}},
              {plugin: "sequence", id: "sequence_editor", title: "Paste sequence", options: {role: "sequence"}}
            ]},
            {id: "review", title: "Review", description: "", capabilities: [
              {plugin: "review", id: "submission_review", title: "Review", options: {}}
            ]}
          ]}
        });
        """
    )
    expect(page.locator(".protocol-step")).to_have_count(2)
    expect(page.locator("#protocol-step-material [data-capability-id=source_files]")).to_be_visible()
    expect(page.locator("#protocol-step-material [data-capability-id=sequence_editor]")).to_be_visible()
    page.get_by_label("Protein sequence").fill(">example\nACDEFG")
    assert page.evaluate("window.workspace.sequence()") == "ACDEFG"
    assert page.evaluate("window.workspace.validate()") == []


def test_large_enum_uses_searchable_combobox_and_rejects_unlisted_values(page: Page) -> None:
    page.set_content('<div id="root"></div><input id="files" type="file">')
    page.add_script_tag(path=STATIC_JS / "plugin-host.js")
    page.add_script_tag(path=STATIC_JS / "input-workspace.js")
    page.evaluate(
        """
        window.workspace = new window.REvoComputeInputWorkspace.InputWorkspace(
          document.getElementById("root"),
          {fileInput: document.getElementById("files"), status: function () {}}
        );
        window.workspace.mount({
          name: "codon_optimize", display_name: "Codon optimization",
          file_input: {extensions: [".fasta"], primary_extensions: [".fasta"], multiple: false, max_files: 1},
          params: [{
            name: "organism", label: "Organism", type: "str", default: "Organism 1",
            choices: Array.from({length: 164}, function (_, index) { return "Organism " + (index + 1); })
          }],
          input_workspace: {version: 3, steps: [{
            id: "settings", title: "Settings", capabilities: [
              {plugin: "parameters", id: "parameters", title: "Parameters", options: {}}
            ]
          }]}
        });
        """
    )
    combo = page.locator("#param_organism")
    expect(combo).to_have_attribute("role", "combobox")
    expect(combo).to_have_attribute("list", "param_organism_choices")
    expect(page.locator("#param_organism_choices option")).to_have_count(164)
    combo.fill("Unlisted organism")
    assert page.evaluate("window.workspace.validate()") == ["Organism: Choose a listed value."]
    combo.fill("Organism 164")
    assert page.evaluate("window.workspace.validate()") == []


def test_seed_control_preserves_optional_zero_and_manual_values(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.set_content('<div id="root"></div><input id="files" type="file">')
    page.add_style_tag(path=STATIC_JS.parent / "css" / "base.css")
    page.add_style_tag(path=STATIC_JS.parent / "css" / "create-task.css")
    page.add_script_tag(path=STATIC_JS / "plugin-host.js")
    page.add_script_tag(path=STATIC_JS / "input-workspace.js")
    page.evaluate(
        """
        window.workspace = new window.REvoComputeInputWorkspace.InputWorkspace(
          document.getElementById("root"),
          {fileInput: document.getElementById("files"), status: function () {}}
        );
        window.workspace.mount({
          name: "seed_contract", display_name: "Seed contract",
          file_input: {extensions: [".fasta"], primary_extensions: [".fasta"], multiple: false, max_files: 1},
          params: [
            {name: "base_seed", label: "Optional seed", type: "int", default: null, required: false, minimum: 0, maximum: 100, ui_control: {kind: "seed", random: {minimum: 0, maximum: 100}}},
            {name: "seed", label: "Upstream seed", type: "int", default: 0, required: true, minimum: 0, maximum: 100, ui_control: {kind: "seed", random: {minimum: 1, maximum: 100}}}
          ],
          input_workspace: {version: 3, steps: [{id: "settings", title: "Settings", capabilities: [
            {plugin: "parameters", id: "parameters", title: "Parameters", options: {}}
          ]}]}
        });
        """
    )
    expect(page.locator("#param_base_seed")).to_have_value("")
    expect(page.locator("#param_seed")).to_have_value("0")
    assert page.locator(".seed-dice").first.evaluate("node => node.getBoundingClientRect().width >= 44 && node.getBoundingClientRect().height >= 44")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    page.locator(".seed-dice").first.click()
    generated = int(page.locator("#param_base_seed").input_value())
    assert 0 <= generated <= 100
    assert page.locator("#param_base_seed").is_editable() is False
    page.locator(".seed-toggle input").first.uncheck()
    expect(page.locator("#param_base_seed")).to_have_value("")
    page.locator(".seed-dice").nth(1).click()
    generated = int(page.locator("#param_seed").input_value())
    assert 1 <= generated <= 100
    assert page.evaluate("window.workspace.paramValues().seed") == str(generated)
    page.locator(".seed-toggle input").nth(1).uncheck()
    expect(page.locator("#param_seed")).to_have_value("0")
    assert page.evaluate("window.workspace.validate()") == []
    page.locator("#param_seed").fill("17")
    page.get_by_role("button", name="Reset Upstream seed to its default").click()
    expect(page.locator("#param_seed")).to_have_value("0")
    assert page.evaluate("window.workspace.paramValues()") == {"seed": "0"}

    page.locator("#param_base_seed").fill("50")
    page.locator(".seed-dice").first.click()
    assert page.locator("#param_base_seed").input_value() != "50"


def test_structure_plugin_keeps_selection_while_direct_viewer_initializes(page: Page) -> None:
    """A file chosen while the direct module initializes is loaded once ready."""
    page.route(
        "https://revocompute.example/",
        lambda route: route.fulfill(
            content_type="text/html", body='<div id="root"></div><input id="files" type="file">'
        ),
    )
    page.route(
        "https://revocompute.example/static/app/assets/molecular-viewer.js",
        lambda route: route.fulfill(
            content_type="application/javascript",
            body="""
              export class MolecularViewer {
                static async mount(host) {
                  await new Promise(resolve => setTimeout(resolve, 800));
                  window.__mounts = (window.__mounts || 0) + 1;
                  return new MolecularViewer(host);
                }
                constructor(host) { this.host = host; }
                async loadStructure(source) { window.__loads.push(source); }
                onSelectionChanged(listener) { this.listener = listener; return () => { this.listener = null; }; }
                async clear() {}
                dispose() { window.__disposals = (window.__disposals || 0) + 1; }
              }
            """,
        ),
    )
    page.goto("https://revocompute.example/")
    page.add_script_tag(path=STATIC_JS / "plugin-host.js")
    page.add_script_tag(path=STATIC_JS / "input-workspace.js")
    page.evaluate(
        """
        window.__loads = []; window.__mounts = 0; window.__disposals = 0;
        window.workspace = new window.REvoComputeInputWorkspace.InputWorkspace(
          document.getElementById("root"),
          {fileInput: document.getElementById("files"), status: function () {}}
        );
        window.workspace.mount({
          name: "rfdiffusion", display_name: "RFdiffusion",
          runtime_family: "placer-rfdiffusion",
          inputs: [{id: "structures", title: "Structures", type: "protein_structure", accept: ".pdb",
            extensions: [".pdb"], cardinality: {min: 1, max: 64}}], max_request_bytes: 16777216,
          params: [],
          input_workspace: {version: 3, steps: [
            {id: "material", title: "Input", description: "", capabilities: [
              {plugin: "files", id: "source_files", title: "Files", options: {primary_role: "structures"}},
              {plugin: "structure", id: "structure_builder", title: "Structure", options: {source: "source_files", role: "structures", select_residues: true}}
            ]},
            {id: "review", title: "Review", description: "", capabilities: [
              {plugin: "review", id: "submission_review", title: "Review", options: {}}
            ]}
          ]}
        });
        """
    )
    page.set_input_files(
        "[data-input-role=structures] input[type=file]",
        [
            {
                "name": "first.pdb",
                "mimeType": "chemical/x-pdb",
                "buffer": b"ATOM      1  CA  GLY A   1      10.000  10.000  10.000  1.00 20.00           C\nEND\n",
            },
            {
                "name": "selected.pdb",
                "mimeType": "chemical/x-pdb",
                "buffer": b"ATOM      1  CA  ALA B   2      12.000  11.000  10.000  1.00 20.00           C\nEND\n",
            },
        ],
    )
    page.locator('input[name="primary_input_structures"]').nth(1).check()
    page.wait_for_timeout(1_000)
    page.wait_for_function("window.__loads.length > 0", timeout=10000)
    assert page.evaluate("window.__mounts") == 1
    assert page.evaluate("window.__loads.at(-1).label") == "selected.pdb"
    assert page.evaluate("window.__loads.at(-1).format") == "pdb"
    assert page.evaluate("window.workspace.inputFiles().map(function (item) { return item.file.name; })") == [
        "selected.pdb",
        "first.pdb",
    ]


def test_real_molstar_sequence_strip_reports_selected_residue(page: Page) -> None:
    """The direct adapter reports sequence-strip selections."""
    assert (FRONTEND_DIST / "assets" / "molecular-viewer.js").is_file(), "run npm ci && npm run build in frontend"
    page.route(
        "https://revocompute.example/static/app/**",
        lambda route: route.fulfill(
            content_type="text/css" if route.request.url.endswith(".css") else "application/javascript",
            body=(FRONTEND_DIST / route.request.url.split("/static/app/", 1)[1]).read_bytes(),
        ),
    )
    page.route(
        "https://revocompute.example/",
        lambda route: route.fulfill(content_type="text/html", body='<div id="viewer" style="width:900px;height:700px"></div>'),
    )
    page.goto("https://revocompute.example/")
    pdb = (Path(__file__).resolve().parents[1] / "tests/data/pdb/2KL8.pdb").read_text(encoding="utf-8")
    page.evaluate(
        """async text => {
          const { MolecularViewer } = await import('/static/app/assets/molecular-viewer.js');
          window.__reports = [];
          window.__viewer = await MolecularViewer.mount(document.getElementById('viewer'), {
            selectionEnabled: true, showControls: true
          });
          window.__viewer.onSelectionChanged(residues => window.__reports.push(residues));
          await window.__viewer.loadStructure({data: text, format: 'pdb', label: 'probe.pdb'});
        }""",
        pdb,
    )

    # Selection mode is enabled by the adapter, so clicking residue 5 updates
    # structure.selection and reports it to the application callback.
    assert "msp-btn-link-toggle-on" in (page.get_by_title("Toggle Selection Mode").get_attribute("class") or "")
    page.locator(".msp-sequence-present").nth(4).click()
    page.wait_for_function(
        "window.__reports.some(function (residues) { return residues.length > 0; })",
        timeout=10_000,
    )
    selection = page.evaluate("window.__reports.filter(function (residues) { return residues.length > 0; }).at(-1)")
    assert selection == [{"chain": "A", "auth_seq_id": 5, "label_seq_id": 5, "residue": 5}]


def test_linked_result_layout_collapses_at_mobile_width(page: Page) -> None:
    css = (STATIC_JS.parent / "css" / "task-results.css").read_text(encoding="utf-8")
    page.set_viewport_size({"width": 560, "height": 800})
    page.set_content(f"<style>{css}</style><div class='linked-result-layout'><div>A</div><div>B</div></div>")
    columns = page.locator(".linked-result-layout").evaluate("node => getComputedStyle(node).gridTemplateColumns")
    assert " " not in columns.strip()
