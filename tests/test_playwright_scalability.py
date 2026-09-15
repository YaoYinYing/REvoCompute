# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import re
from pathlib import Path

from jinja2 import Environment
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "revocompute" / "static" / "js"
TEMPLATES = ROOT / "revocompute" / "templates"


def _template(name: str) -> str:
    source = (TEMPLATES / name).read_text(encoding="utf-8")
    source = re.sub(r'<script[^>]+src="[^"]+"[^>]*></script>', "", source)
    source = re.sub(r"{{.*?}}", "Example", source, flags=re.DOTALL)
    return re.sub(r"{%.*?%}", "", source, flags=re.DOTALL)


def _runner_catalog_template() -> str:
    methods = [
        {
            "name": "alphafold3",
            "display_name": "AlphaFold 3",
            "category": "structure_prediction",
            "runtime_family": "alphafold3",
            "summary": "Predict biomolecular structures",
            "use_when": "complex structure prediction",
            "input_summary": "FASTA",
            "output_summary": "mmCIF",
            "input_extensions": [".fasta"],
            "gpus": True,
            "access": {"restricted": False},
        },
        {
            "name": "bioemu",
            "display_name": "BioEmu",
            "category": "structure_prediction",
            "runtime_family": "bioemu",
            "summary": "Sample protein conformations",
            "use_when": "conformational ensembles",
            "input_summary": "Sequence",
            "output_summary": "Trajectory",
            "input_extensions": [".fasta"],
            "gpus": True,
            "access": {"restricted": False},
        },
        {
            "name": "gremlin",
            "display_name": "GREMLIN",
            "category": "evolution",
            "runtime_family": "pssm_gremlin",
            "summary": "Infer residue co-evolution",
            "use_when": "fitness analysis",
            "input_summary": "MSA",
            "output_summary": "CSV",
            "input_extensions": [".a3m"],
            "gpus": False,
            "access": {"restricted": False},
        },
    ]
    html = Environment(autoescape=True).from_string(
        (TEMPLATES / "runners.html").read_text(encoding="utf-8")
    ).render(task_types=methods)
    return re.sub(r'<script[^>]+src="[^"]+"[^>]*></script>', "", html)


def test_runner_catalog_search_and_shared_density(page: Page) -> None:
    page.set_viewport_size({"width": 1200, "height": 900})
    page.route(
        "https://runners.revocompute.test/",
        lambda route: route.fulfill(content_type="text/html", body=_runner_catalog_template()),
    )
    page.goto("https://runners.revocompute.test/")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "base.css")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "index.css")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "runners.css")
    page.add_script_tag(path=JS / "ui.js")
    page.add_script_tag(path=JS / "runners.js")
    cards = page.locator(".runner-card")
    expect(cards).to_have_count(3)
    expect(page.locator("#runnerCatalogCount")).to_have_text("3 methods")

    page.locator("#runnerSearch").fill("alphafold")
    expect(page.locator('[data-task-type="alphafold3"]')).to_be_visible()
    expect(page.locator('[data-task-type="bioemu"]')).to_be_hidden()
    expect(page.locator('[data-task-type="gremlin"]')).to_be_hidden()
    expect(page.locator('[data-category="structure_prediction"]')).to_be_visible()
    expect(page.locator('[data-category="evolution"]')).to_be_hidden()
    assert page.locator('[data-task-type="gremlin"]').bounding_box() is None
    assert page.locator('[data-category="evolution"]').bounding_box() is None
    expect(page.locator("#runnerCatalogCount")).to_have_text("1 method")

    page.get_by_role("button", name="Compact").click()
    expect(page.locator("#runnerCatalog")).to_have_attribute("data-density", "compact")
    assert page.evaluate("localStorage.getItem('revocompute.ui.catalog-density.v1')") == "compact"
    expect(page.locator('[data-task-type="gremlin"]')).to_be_hidden()
    page.locator("#runnerCategory").select_option("evolution")
    expect(page.locator("#runnerCatalogEmpty")).to_be_visible()
    expect(page.locator("#runnerCatalogCount")).to_have_text("0 methods")
    page.get_by_role("button", name="Comfortable").click()
    expect(page.locator('[data-task-type="alphafold3"]')).to_be_hidden()

    page.locator("#runnerSearch").fill("")
    expect(page.locator('[data-task-type="gremlin"]')).to_be_visible()
    expect(page.locator('[data-category="structure_prediction"]')).to_be_hidden()
    expect(page.locator("#runnerCatalogCount")).to_have_text("1 method")
    page.locator("#runnerCategory").select_option("")
    expect(cards).to_have_count(3)
    for index in range(3):
        expect(cards.nth(index)).to_be_visible()
    expect(page.locator("#runnerCatalogEmpty")).to_be_hidden()
    expect(page.locator("#runnerCatalogCount")).to_have_text("3 methods")

    for width in (1200, 834, 390):
        page.set_viewport_size({"width": width, "height": 900})
        page.locator("#runnerSearch").fill("alphafold")
        expect(page.locator('[data-task-type="alphafold3"]')).to_be_visible()
        expect(page.locator('[data-task-type="gremlin"]')).to_be_hidden()
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        page.locator("#runnerSearch").fill("")


def test_create_task_catalog_search_and_hidden_reuse(page: Page) -> None:
    html = _template("create_task.html")
    assert "Reuse an artifact" not in html
    task_types = [
        {"name": f"method-{index}", "display_name": f"Method {index} with a long scientific Runner name", "category": "fold", "runtime_family": "family-a", "summary": "Protein structure", "use_when": "prediction", "input_summary": "sequence", "output_summary": "mmCIF" if index == 0 else "CSV", "input_label": "FASTA", "access": {"restricted": index % 2 == 0, "granted": False}}
        for index in range(12)
    ]
    catalog = {"categories": [{"name": "fold", "label": "Folding", "description": "Structure prediction"}], "task_types": task_types}
    page.route("https://create.revocompute.test/**", lambda route: route.fulfill(content_type="text/html", body=html))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("https://create.revocompute.test/")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "base.css")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "create-task.css")
    page.evaluate("""window.__catalog=%s; window.REvoDesignTheme={initToggle:function(){}}; window.REvoDesignAuth={authFetch:function(){}};
      window.REvoComputeInputWorkspace={InputWorkspace:function(){this.destroy=function(){};this.validate=function(){return[]};this.files=function(){return[]};this.sequence=function(){return''}}};
      window.fetch=function(url){return Promise.resolve({ok:true,json:function(){return Promise.resolve(window.__catalog)}})};""" % json.dumps(catalog))
    page.add_script_tag(path=JS / "ui.js")
    page.add_script_tag(path=JS / "create-task.js")
    expect(page.locator(".method-card")).to_have_count(12)
    expect(page.locator(".access-state", has_text="Restricted")).to_have_count(6)
    page.locator("#methodSearch").fill("missing")
    expect(page.get_by_text("No methods match that search.")).to_be_visible()
    page.locator("#methodSearch").fill("Method 0")
    expect(page.locator(".method-card")).to_have_count(1)
    page.get_by_role("button", name="Compact").click()
    expect(page.locator("#methodGroups")).to_have_attribute("data-density", "compact")
    assert page.evaluate("localStorage.getItem('revocompute.ui.catalog-density.v1')") == "compact"
    page.locator("#methodSearch").fill("missing")
    expect(page.get_by_text("No methods match that search.")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_failed_sequence_submission_does_not_leak_generated_file_into_retry(page: Page) -> None:
    html = _template("create_task.html")
    catalog = {
        "categories": [{"name": "fold", "label": "Folding", "description": "Structure prediction"}],
        "task_types": [{
            "name": "sequence_task", "display_name": "Sequence task", "category": "fold",
            "runtime_family": "sequence", "summary": "Predict a structure", "use_when": "testing retries",
            "input_summary": "FASTA", "output_summary": "Structure", "access": {"restricted": False},
        }],
    }
    definition = {
        **catalog["task_types"][0],
        "gpus": False,
        "requires_network": False,
        "considerations": [],
        "parameters_url": "/compute/api/types/sequence_task/parameters",
        "workspace_plugins": [],
        "inputs": [{
            "id": "sequence", "title": "Protein sequence", "type": "protein_sequence",
            "accept": ".fasta", "extensions": [".fasta"], "cardinality": {"min": 1, "max": 1},
        }],
        "max_request_bytes": 16_777_216,
        "input_workspace": {"version": 3, "steps": [
            {"id": "material", "title": "Input", "description": "", "capabilities": [
                {"plugin": "files", "id": "source_files", "title": "Files", "options": {}},
                {"plugin": "sequence", "id": "sequence_editor", "title": "Paste sequence",
                 "options": {"role": "sequence"}},
            ]},
            {"id": "review", "title": "Review", "description": "", "capabilities": [
                {"plugin": "review", "id": "submission_review", "title": "Review", "options": {}},
            ]},
        ]},
    }
    submissions: list[bytes] = []

    def serve(route):
        path = route.request.url.split("?", 1)[0].removeprefix("https://create.revocompute.test")
        if route.request.method == "POST" and path == "/compute/api/post":
            submissions.append(route.request.post_data_buffer or b"")
            route.fulfill(status=503, json={"error": f"retry-{len(submissions)}"})
        elif path == "/compute/api/types":
            route.fulfill(json=catalog)
        elif path == "/compute/api/types/sequence_task":
            route.fulfill(json=definition)
        elif path == "/compute/api/types/sequence_task/parameters":
            route.fulfill(json={"type": "object", "properties": {}})
        elif path == "/compute/api/types/sequence_task/reusable-artifacts":
            route.fulfill(json={"roles": {}})
        else:
            route.fulfill(content_type="text/html", body=html)

    page.route("https://create.revocompute.test/**", serve)
    page.goto("https://create.revocompute.test/?task_type=sequence_task")
    page.evaluate(
        """window.REvoDesignTheme={initToggle:function(){}};
        window.REvoDesignAuth={authFetch:function(url, options){return window.fetch(url, options);}};"""
    )
    page.add_script_tag(path=JS / "ui.js")
    page.add_script_tag(path=JS / "plugin-host.js")
    page.add_script_tag(path=JS / "input-workspace.js")
    page.add_script_tag(path=JS / "create-task.js")

    page.get_by_label("Sequence name").fill("stale")
    page.get_by_label("Protein sequence").fill("ACDE")
    page.get_by_role("button", name="Run Sequence task").click()
    expect(page.locator("#uploadStatus")).to_have_text("retry-1")

    page.get_by_label("Protein sequence").fill("")
    page.set_input_files(
        "[data-input-role=sequence] input[type=file]",
        {"name": "replacement.fasta", "mimeType": "text/plain", "buffer": b">replacement\nWXYZ\n"},
    )
    page.get_by_role("button", name="Run Sequence task").click()
    expect(page.locator("#uploadStatus")).to_have_text("retry-2")

    assert len(submissions) == 2
    assert b'filename="stale.fasta"' in submissions[0]
    assert b'filename="replacement.fasta"' in submissions[1]
    assert b'filename="stale.fasta"' not in submissions[1]


def test_configuration_tasktype_filter(page: Page) -> None:
    page.set_content(_template("configuration.html"))
    page.evaluate("""window.escapeHtml=function(value){return String(value==null?'':value)}; window.REvoDesignTheme={initToggle:function(){}}; window.REvoDesignAuth={logout:function(){},authFetch:function(){return Promise.resolve({ok:true,json:function(){return Promise.resolve({task_types:[{tool:'alpha',display_name:'Alpha',enabled:true,runtime_family:'family-a',is_workflow_stage:false,effective_resources:{cpus:4,memory:'8G',max_runtime_seconds:60}}],resources:{},slurm:{enabled:false,allowed_queues:[]}})}})}};
      window.fetch=function(){return Promise.resolve({ok:true,json:function(){return Promise.resolve({task_types:[{name:'alpha',display_name:'Alpha',category:'fold',input_extension:'.fasta',input_label:'Sequence',stage_markers:{},params:[]}]})}})};""")
    page.add_script_tag(path=JS / "configuration.js")
    expect(page.locator(".type-card-name")).to_contain_text("Alpha")
    page.locator("#taskTypeSearch").fill("family-a")
    expect(page.locator(".type-card")).to_have_count(1)
    page.locator("#taskTypeSearch").fill("docking")
    expect(page.locator("#taskTypeEmpty")).to_be_visible()


def test_configuration_infrastructure_panel_and_refresh(page: Page) -> None:
    payload = {
        "status": "READY",
        "checked_at": "2026-09-15T08:00:00+00:00",
        "stale": True,
        "summary": {
            "infrastructure": {"label": "Infrastructure", "status": "READY", "stale": True},
            "scheduler": {"label": "Scheduler", "status": "READY", "stale": False, "capacity": "BUSY"},
            "gpu": {"label": "GPU", "status": "READY", "stale": False, "capacity": "BUSY"},
            "worker": {"label": "Worker", "status": "READY", "stale": False},
            "storage": {"label": "Storage", "status": "DEGRADED", "stale": False},
        },
        "components": [
            {
                "component": "result_storage",
                "status": "DEGRADED",
                "reason_code": "disk_space_low",
                "message": "Required storage has low free space.",
                "checked_at": "2026-09-15T08:00:00+00:00",
                "duration_ms": 4,
                "failure_count": 1,
                "next_action": "Plan storage cleanup or expansion.",
                "stale": True,
            }
        ],
    }
    page.set_content(_template("configuration.html"))
    page.evaluate(
        """([readiness]) => {
          window.escapeHtml = function(value) { return String(value == null ? '' : value); };
          window.REvoDesignTheme = {initToggle: function() {}};
          window.infrastructureCalls = [];
          window.REvoDesignAuth = {
            logout: function() {},
            authFetch: function(url, options) {
              if (url.indexOf('infrastructure') !== -1) {
                window.infrastructureCalls.push([url, options && options.method]);
                return Promise.resolve({ok: true, json: function() { return Promise.resolve(readiness); }});
              }
              return Promise.resolve({ok: true, json: function() { return Promise.resolve({task_types: [], resources: {}, slurm: {enabled: false, allowed_queues: []}}); }});
            }
          };
          window.fetch = function() { return Promise.resolve({ok: true, json: function() { return Promise.resolve({task_types: []}); }}); };
        }""",
        [payload],
    )
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "base.css")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "configuration.css")
    page.add_script_tag(path=JS / "configuration.js")

    page.get_by_role("button", name="Infrastructure").click()
    expect(page.locator("#tab-infrastructure")).to_be_visible()
    expect(page.locator("#infrastructureSummary")).to_contain_text("GPU")
    expect(page.locator("#infrastructureSummary")).to_contain_text("Capacity BUSY")
    expect(page.locator("#infrastructureBody")).to_contain_text("disk_space_low")
    expect(page.locator("#infrastructureCheckedAt")).to_contain_text("evidence is stale")

    page.get_by_role("button", name="Refresh").click()
    expect(page.locator("#refreshInfrastructureBtn")).to_be_enabled()
    assert page.evaluate("window.infrastructureCalls") == [
        ["/compute/api/infrastructure", None],
        ["/compute/api/auth/admin/infrastructure/refresh", "POST"],
    ]


def test_dashboard_search_regex_sort_and_layout(page: Page) -> None:
    tasks = [
        {
            "md5": "a" * 32, "status": "finished", "fasta_fn": "older-alpha.pdb", "task_type": "alpha",
            "submitted_time": "2026-01-01", "finished_time": "2026-01-03", "submitted_timestamp": 1767225600,
            "finished_timestamp": 1767398400, "walltime": "1m", "sequence": "AAA", "can_delete": True,
            "owner": "u", "structure_input": True, "input_url": "/input/alpha", "structure_format": "pdb",
        },
        {"md5": "b" * 32, "status": "running", "fasta_fn": "new-beta.fasta", "task_type": "beta", "submitted_time": "2026-01-02", "finished_time": "-", "submitted_timestamp": 1767312000, "finished_timestamp": 0, "walltime": "-", "sequence": "BBB", "can_delete": True, "owner": "u"},
        {"md5": "c" * 32, "status": "failed", "fasta_fn": "failed-gamma-with-an-intentionally-long-scientific-task-name-for-phone-layout.fasta", "task_type": "gamma", "submitted_time": "2026-01-02", "finished_time": "2026-01-03", "submitted_timestamp": 1767311000, "finished_timestamp": 1767398300, "walltime": "2m", "sequence": "CCC", "can_delete": True, "owner": "u", "error": "Runner failed after a populated test state."},
    ]
    tasks.extend({"md5": f"{index:032d}", "status": "finished", "fasta_fn": f"bulk-{index}.fasta", "task_type": f"method-{index:03d}", "submitted_timestamp": index, "finished_timestamp": index, "can_delete": False} for index in range(100))
    html = f"""<script id="dashboard-task-data" type="application/json">
      {json.dumps({'tasks': tasks, 'is_admin': False})}</script>
      <span id="totalTasks"></span><span id="inQueue"></span><span id="inRunning"></span>
      <span id="finished"></span><span id="issues"></span><div id="toastWrap"></div><div id="adminTools"></div>
      <input id="taskSearch"><button id="taskRegex"></button><span id="taskSearchError"></span>
      <input id="taskTypeFilter" list="taskTypeOptions"><button id="taskTypeRegex"></button>
      <datalist id="taskTypeOptions"></datalist><span id="taskTypeSearchError"></span>
      <select id="statusFilter"><option value=""></option><option value="running">Running</option>
        <option value="finished">Finished</option></select>
      <input id="submissionFrom" type="date"><input id="submissionTo" type="date">
      <input id="finishFrom" type="date"><input id="finishTo" type="date">
      <select id="taskSort"><option value="submitted">Submission</option>
        <option value="finished">Finish</option></select>
      <div id="taskLayout"><button data-value="detailed">Detailed</button>
        <button data-value="compact">Compact</button><button data-value="table">Table</button></div>
      <button id="refreshBtn"></button><button id="logoutBtn"></button>
      <button id="selectVisibleBtn"></button><button id="clearSelectionBtn"></button>
      <button class="delete-selected" id="deleteSelectedBtn"></button><main class="board" id="taskList"></main>"""
    page.route("https://dashboard.revocompute.test/**", lambda route: route.fulfill(content_type="text/html", body=html))
    page.set_viewport_size({"width": 430, "height": 932})
    page.goto("https://dashboard.revocompute.test/")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "base.css")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "dashboard.css")
    page.evaluate("""window.escapeHtml=function(value){return String(value==null?'':value)};
      window.REvoDesignTheme={initToggle:function(){},getStoredThemeMode:function(){return 'light'}};
      window.__dashboardRequests=[];
      window.setInterval=function(callback){window.__pollStatuses=callback};
      window.REvoDesignAuth={logout:function(){},authFetch:function(url,options){
        window.__dashboardRequests.push({url:url,method:(options&&options.method)||'GET'});
        if(url==='/input/alpha')return Promise.resolve({ok:true,text:function(){return Promise.resolve('ATOM')}});
        if(url.indexOf('/compute/api/running/')===0)return Promise.resolve({ok:true,json:function(){return Promise.resolve({status:'pending'})}});
        if(url.indexOf('/compute/api/cancel/')===0)return Promise.resolve({ok:true,json:function(){return Promise.resolve({status:'cancelled'})}});
        if(url.indexOf('/archive')!==-1)return new Promise(function(){});
        return Promise.resolve({ok:true,json:function(){return Promise.resolve({})}});
      }};
      window.REvoDesignPy2Dmol={renderAlphaTrace:function(box){box.dataset.rendered='true';return Promise.resolve()}};""")
    page.add_script_tag(path=JS / "ui.js")
    page.add_script_tag(path=JS / "dashboard.js")
    page.evaluate("document.dispatchEvent(new Event('DOMContentLoaded'))")
    expect(page.locator("#taskList")).to_have_attribute("data-layout", "detailed")
    expect(page.locator(".task-title").first).to_have_text("new-beta.fasta")
    expect(page.locator('.task-card[data-md5="' + "c" * 32 + '"] .error-indicator')).to_be_visible()
    expect(page.locator("#taskTypeOptions option")).to_have_count(103)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    page.locator("#taskSearch").fill("alpha")
    expect(page.locator(".task-card")).to_have_count(1)
    page.locator("#taskRegex").click(); page.locator("#taskSearch").fill("[")
    expect(page.locator("#taskSearchError")).to_have_text("Invalid regular expression")
    page.locator("#taskSearch").fill("(alpha|beta)")
    expect(page.locator(".task-card")).to_have_count(2)
    page.locator("#taskTypeRegex").click(); page.locator("#taskTypeFilter").fill("[")
    expect(page.locator("#taskTypeSearchError")).to_have_text("Invalid regular expression")
    page.locator("#taskTypeFilter").fill("^(alpha|beta)$")
    expect(page.locator(".task-card")).to_have_count(2)
    page.locator("#taskTypeRegex").click(); page.locator("#taskTypeFilter").fill("alpha")
    page.locator("#statusFilter").select_option("finished")
    page.locator("#finishFrom").fill("2026-01-03")
    expect(page.locator(".task-card")).to_have_count(1)
    page.locator("#taskTypeFilter").fill("")
    page.locator("#statusFilter").select_option("")
    page.locator("#finishFrom").fill("")
    page.locator("#taskSort").select_option("finished")
    expect(page.locator(".task-title").first).to_have_text("new-beta.fasta")
    page.get_by_role("button", name="Compact").click()
    expect(page.locator("#taskList")).to_have_attribute("data-layout", "compact")
    detail_button = page.locator('.task-card[data-md5="' + "a" * 32 + '"] [data-action="details"]')
    assert detail_button.evaluate("node => getComputedStyle(node).display") != "none"
    detail_button.click()
    expect(page.get_by_role("dialog")).to_contain_text("older-alpha.pdb")
    assert page.get_by_role("dialog").evaluate("node => node.getBoundingClientRect().width <= innerWidth && node.getBoundingClientRect().height <= innerHeight")
    page.get_by_role("dialog").get_by_text("Structure Snapshot").click()
    expect(page.get_by_role("dialog").locator(".structure-preview")).to_have_attribute("data-rendered", "true")
    page.get_by_role("button", name="Close dialog").click()
    page.get_by_role("button", name="Table").click()
    expect(page.locator("#taskList")).to_have_attribute("data-layout", "table")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    expect(page.locator("#deleteSelectedBtn")).to_be_disabled()
    assert float(page.locator("#deleteSelectedBtn").evaluate("node => getComputedStyle(node).opacity")) < 0.5
    page.set_viewport_size({"width": 1200, "height": 800})
    finished_row = page.locator(".task-table tr", has_text="older-alpha.pdb")
    expect(finished_row.locator("[data-action='results']")).to_have_class(re.compile("results"))
    expect(finished_row.locator("[data-action='download']")).to_have_class(re.compile("download"))
    expect(finished_row.locator("[data-action='delete']")).to_have_class(re.compile("delete"))
    initial_height = finished_row.evaluate("node => node.getBoundingClientRect().height")
    finished_row.get_by_role("button", name="Download", exact=True).click()
    progress = finished_row.get_by_role("button", name=re.compile("Preparing download"))
    expect(progress).to_have_text("Preparing…")
    expect(progress).to_have_attribute("aria-busy", "true")
    assert abs(finished_row.evaluate("node => node.getBoundingClientRect().height") - initial_height) <= 1
    action_tops = finished_row.locator(".table-actions .task-btn").evaluate_all(
        "nodes => nodes.map(node => Math.round(node.getBoundingClientRect().top))"
    )
    assert len(set(action_tops)) == 1
    running_row = page.locator(".task-table tr", has_text="new-beta.fasta")
    expect(running_row.locator(".status-pill")).to_have_attribute("data-task-status", "running")
    expect(running_row.get_by_role("button", name="Cancel")).to_be_visible()
    expect(running_row.get_by_role("button", name="Delete")).to_be_visible()
    page.evaluate("window.__pollStatuses()")
    page.wait_for_function("window.__dashboardRequests.some(function(item){return item.url.indexOf('/compute/api/running/')===0})")
    expect(running_row.locator(".status-pill")).to_have_attribute("data-task-status", "pending")
    running_row.get_by_role("button", name="Cancel").click()
    page.wait_for_function("window.__dashboardRequests.some(function(item){return item.url.indexOf('/compute/api/cancel/')===0})")
    expect(page.locator(".task-table tr", has_text="new-beta.fasta").locator(".status-pill")).to_contain_text("Cancelled")
    assert page.evaluate("localStorage.getItem('revocompute.ui.task-layout.v1')") == "table"

    page.get_by_role("button", name="Compact").click()
    finished_card = page.locator('#taskList .task-card[data-md5="' + "a" * 32 + '"]')
    compact_actions = finished_card.locator(".actions").first
    for action in ("details", "results", "download"):
        expect(compact_actions.locator('[data-action="' + action + '"]')).to_be_visible()
    expect(compact_actions.locator('[data-action="delete"]')).to_be_hidden()
    initial_card_height = finished_card.evaluate("node => node.getBoundingClientRect().height")
    compact_progress = compact_actions.get_by_role("button", name=re.compile("Preparing download"))
    expect(compact_progress).to_have_text("Preparing…")
    expect(compact_progress).to_be_visible()
    assert abs(finished_card.evaluate("node => node.getBoundingClientRect().height") - initial_card_height) <= 1
    compact_actions.get_by_role("button", name="Results", exact=True).click()
    expect(page).to_have_url(re.compile("/compute/results/" + "a" * 32 + "$"))


def test_dashboard_control_geometry_is_aligned_and_content_driven(page: Page) -> None:
    html = _template("dashboard.html")
    for width in (1366, 1920):
        page.set_viewport_size({"width": width, "height": 900})
        page.set_content(html)
        page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "base.css")
        page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "dashboard.css")
        page.locator("#adminTools").evaluate("node => node.hidden = false")

        first_row = page.locator("#taskSearch, #taskTypeFilter, #statusFilter, #ownerSearch")
        input_tops = first_row.evaluate_all(
            "nodes => nodes.map(node => Math.round(node.getBoundingClientRect().top))"
        )
        label_tops = page.locator(
            ".task-name-filter > span:first-child, .task-type-filter > span:first-child, "
            ".status-filter > span:first-child, .owner-filter > span:first-child"
        ).evaluate_all("nodes => nodes.map(node => Math.round(node.getBoundingClientRect().top))")
        assert max(input_tops) - min(input_tops) <= 1, (width, input_tops)
        assert max(label_tops) - min(label_tops) <= 1, (width, label_tops)

        date_widths = page.locator(".date-filter .text-input").evaluate_all(
            "nodes => nodes.map(node => node.getBoundingClientRect().width)"
        )
        assert max(date_widths) - min(date_widths) <= 1, (width, date_widths)
        assert max(date_widths) <= 180

        layout_width, segmented_width = page.locator(".layout-control").evaluate(
            "node => [node.getBoundingClientRect().width, node.querySelector('.segmented-control').getBoundingClientRect().width]"
        )
        assert layout_width <= segmented_width + 1, (width, layout_width, segmented_width)
        assert page.locator(".controls").evaluate("node => node.scrollWidth <= node.clientWidth + 1")
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_affected_pages_do_not_create_horizontal_document_scroll(page: Page) -> None:
    pages = {
        "index.html": ("index.css",), "runners.html": ("index.css", "runners.css"),
        "create_task.html": ("create-task.css",), "dashboard.html": ("dashboard.css",),
        "profile.html": ("profile.css",), "user_control.html": ("user-control.css",),
        "configuration.html": ("configuration.css",), "terms.html": ("auth-page.css",),
        "task_results.html": ("task-results.css",),
    }
    for width, height in (
        (1920, 1080), (1440, 900), (1366, 768),
        (1024, 1366), (834, 1194), (768, 1024),
        (430, 932), (390, 844), (375, 812),
    ):
        page.set_viewport_size({"width": width, "height": height})
        for template, stylesheets in pages.items():
            page.set_content(_template(template))
            page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "base.css")
            for stylesheet in stylesheets:
                page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / stylesheet)
            overflow = page.evaluate("""() => Array.from(document.querySelectorAll('*')).filter(function (node) {
              var rect = node.getBoundingClientRect(); return rect.right > document.documentElement.clientWidth + 1 || rect.left < -1;
            }).slice(0, 8).map(function (node) { return node.tagName + '.' + node.className + ':' + Math.round(node.getBoundingClientRect().right); })""")
            assert not overflow, (template, width, overflow)


def test_landing_page_visual_chapters_at_acceptance_viewports(page: Page) -> None:
    html = _template("index.html")
    page.route(
        "https://landing.revocompute.test/",
        lambda route: route.fulfill(content_type="text/html", body=html),
    )
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto("https://landing.revocompute.test/", wait_until="domcontentloaded")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "base.css")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "index.css")
    page.evaluate("""Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {
      writeText: function (value) { window.__copiedAgentUrl = value; return Promise.resolve(); }
    }}); window.setTimeout = function () {};""")
    page.add_script_tag(path=JS / "index-agent-guide.js")
    for width, height in (
        (1920, 1080), (1440, 900), (1366, 768), (1024, 1366), (834, 1194), (430, 932), (390, 844),
    ):
        page.set_viewport_size({"width": width, "height": height})
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        tops = page.evaluate("""() => ['.landing-hero','.agent-entry','.approach-section','.workflow-section','.product-section','.closing-section'].map(function (selector) { return document.querySelector(selector).getBoundingClientRect().top + scrollY; })""")
        assert tops == sorted(tops) and len(set(tops)) == len(tops), (width, height, tops)
        expect(page.locator(".hero-cta .btn-primary")).to_be_visible()
        hierarchy = page.evaluate("""() => ['.agent-entry-heading', '.agent-entry-description', '.agent-url-row']
          .map(selector => document.querySelector(selector).getBoundingClientRect().top)""")
        assert hierarchy == sorted(hierarchy) and len(set(hierarchy)) == 3, (width, hierarchy)
        assert page.locator(".agent-url-row").evaluate(
            "node => node.scrollWidth <= node.clientWidth + 1 && node.getBoundingClientRect().right <= innerWidth"
        )
        assert page.locator("#agentSkillsUrl").get_attribute("title") == "https://landing.revocompute.test/skills.md"
        if width >= 1366:
            assert page.locator(".hero-cta").evaluate("node => node.getBoundingClientRect().bottom <= innerHeight"), (width, height)
            assert page.locator(".landing-hero").evaluate(
                "node => node.getBoundingClientRect().bottom <= innerHeight + 1"
            ), (width, height)
            assert page.locator(".agent-entry").evaluate(
                "node => node.getBoundingClientRect().left >= "
                "document.querySelector('.evidence-map').getBoundingClientRect().left"
            )
        else:
            assert page.locator(".agent-entry").evaluate(
                "node => node.getBoundingClientRect().top >= "
                "document.querySelector('.evidence-map').getBoundingClientRect().bottom"
            )
        box_height = page.locator(".agent-entry").evaluate("node => node.getBoundingClientRect().height")
        page.locator("#copyAgentSkillsUrl").click()
        expect(page.locator("#copyAgentSkillsUrl")).to_have_text("Copied")
        assert page.evaluate("window.__copiedAgentUrl") == "https://landing.revocompute.test/skills.md"
        assert abs(page.locator(".agent-entry").evaluate("node => node.getBoundingClientRect().height") - box_height) <= 1


def test_swagger_surfaces_follow_live_light_and_dark_themes(page: Page) -> None:
    page.set_content("""<section id="swagger-ui"><div class="swagger-ui" data-render="stable">
      <section class="models"><h4 class="model-title">Schemas</h4>
        <div class="model-container"><span class="model">Task</span></div></section>
      <div class="opblock opblock-post"><div class="opblock-summary">
        <span class="opblock-summary-description">Submit task</span></div>
        <div class="opblock-section-header"><h4>Parameters</h4></div>
        <div class="opblock-description-wrapper"><p>Task input</p></div>
        <label><span class="parameter__name required">Name</span><input type="text" placeholder="Task name"></label>
        <select aria-label="Task type"><option>Example</option></select><textarea placeholder="Request body"></textarea>
        <button class="btn execute">Execute</button><button class="btn cancel">Cancel</button>
        <table class="responses-table"><thead><tr><th>Status</th><th>Description</th></tr></thead>
          <tbody><tr><td class="response-col_status">200</td>
            <td class="response-col_description">OK<pre>response body</pre></td></tr></tbody></table>
        <div class="highlight-code"><pre class="microlight">curl /compute/api/post</pre></div>
        <div class="request-url">/compute/api/post</div>
      </div><a href="#schemas">Schema link</a></div></section>""")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "base.css")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "api-docs.css")
    root = page.locator("#swagger-ui .swagger-ui")
    field = page.get_by_placeholder("Task name")
    page.evaluate("document.documentElement.dataset.theme = 'light'")
    light = field.evaluate("node => [getComputedStyle(node).color, getComputedStyle(node).backgroundColor]")
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    dark = field.evaluate("node => [getComputedStyle(node).color, getComputedStyle(node).backgroundColor]")
    assert light != dark and dark[0] != dark[1]
    assert root.get_attribute("data-render") == "stable"
    selectors = (
        ".opblock-description-wrapper", ".response-col_description", ".model-title", ".highlight-code",
        ".request-url", ".btn.execute", "a",
    )
    for selector in selectors:
        colors = root.locator(selector).first.evaluate(
            "node => [getComputedStyle(node).color, getComputedStyle(node).backgroundColor]"
        )
        assert colors[0] != colors[1], selector
