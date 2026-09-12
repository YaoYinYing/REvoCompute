# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "revocompute" / "static" / "js"
TEMPLATES = ROOT / "revocompute" / "templates"


def _template(name: str) -> str:
    source = (TEMPLATES / name).read_text(encoding="utf-8")
    source = re.sub(r'<script[^>]+src="[^"]+"[^>]*></script>', "", source)
    source = re.sub(r"{{.*?}}", "Example", source, flags=re.DOTALL)
    return re.sub(r"{%.*?%}", "", source, flags=re.DOTALL)


def test_runner_catalog_search_and_shared_density(page: Page) -> None:
    page.route("https://catalog.revocompute.test/**", lambda route: route.fulfill(content_type="text/html", body="""<input id="runnerSearch"><select id="runnerCategory"><option value="">All</option></select><span id="runnerCatalogCount"></span><div id="catalogDensity"><button data-value="comfortable">Comfortable</button><button data-value="compact">Compact</button></div><main id="runnerCatalog"><section class="runner-category" data-category="fold"><article class="runner-card" data-search="alpha fold alphafold3 structure gpu"></article><article class="runner-card" data-search="chai prediction mmcif gpu"></article></section></main><p id="runnerCatalogEmpty" hidden></p>"""))
    page.goto("https://catalog.revocompute.test/")
    page.add_script_tag(path=JS / "ui.js")
    page.add_script_tag(path=JS / "runners.js")
    page.locator("#runnerSearch").fill("mmcif")
    expect(page.locator(".runner-card:not([hidden])")).to_have_count(1)
    page.get_by_role("button", name="Compact").click()
    expect(page.locator("#runnerCatalog")).to_have_attribute("data-density", "compact")
    assert page.evaluate("localStorage.getItem('revocompute.ui.catalog-density.v1')") == "compact"


def test_create_task_catalog_search_and_hidden_reuse(page: Page) -> None:
    html = _template("create_task.html")
    assert "Reuse an artifact" not in html
    page.route("https://create.revocompute.test/**", lambda route: route.fulfill(content_type="text/html", body=html))
    page.goto("https://create.revocompute.test/")
    page.evaluate("""window.REvoDesignTheme={initToggle:function(){}}; window.REvoDesignAuth={authFetch:function(){}};
      window.REvoComputeInputWorkspace={InputWorkspace:function(){this.destroy=function(){};this.validate=function(){return[]};this.files=function(){return[]};this.sequence=function(){return''}}};
      window.fetch=function(url){return Promise.resolve({ok:true,json:function(){return Promise.resolve({categories:[{name:'fold',label:'Folding',description:'Structure prediction'}],task_types:[{name:'alpha',display_name:'Alpha',category:'fold',runtime_family:'family-a',summary:'Protein structure',use_when:'prediction',input_summary:'sequence',output_summary:'mmCIF',input_label:'FASTA',access:{restricted:false}}]})}})};""")
    page.add_script_tag(path=JS / "ui.js")
    page.add_script_tag(path=JS / "create-task.js")
    expect(page.get_by_role("button", name=re.compile("Alpha"))).to_be_visible()
    page.locator("#methodSearch").fill("missing")
    expect(page.get_by_text("No methods match that search.")).to_be_visible()
    page.locator("#methodSearch").fill("mmcif")
    expect(page.get_by_role("button", name=re.compile("Alpha"))).to_be_visible()
    page.get_by_role("button", name="Compact").click()
    expect(page.locator("#methodGroups")).to_have_attribute("data-density", "compact")
    assert page.evaluate("localStorage.getItem('revocompute.ui.catalog-density.v1')") == "compact"


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


def test_dashboard_search_regex_sort_and_layout(page: Page) -> None:
    tasks = [
        {"md5": "a" * 32, "status": "finished", "fasta_fn": "older-alpha.pdb", "task_type": "alpha", "submitted_time": "2026-01-01", "finished_time": "2026-01-03", "submitted_timestamp": 100, "finished_timestamp": 300, "walltime": "1m", "sequence": "AAA", "can_delete": False, "owner": "u", "structure_input": True, "input_url": "/input/alpha", "structure_format": "pdb"},
        {"md5": "b" * 32, "status": "running", "fasta_fn": "new-beta.fasta", "task_type": "beta", "submitted_time": "2026-01-02", "finished_time": "-", "submitted_timestamp": 200, "finished_timestamp": 0, "walltime": "-", "sequence": "BBB", "can_delete": True, "owner": "u"},
    ]
    html = f"""<script id="dashboard-task-data" type="application/json">{json.dumps({'tasks': tasks, 'is_admin': False})}</script><span id="totalTasks"></span><span id="inQueue"></span><span id="inRunning"></span><span id="finished"></span><span id="issues"></span><div id="toastWrap"></div><div id="adminTools"></div><input id="taskSearch"><button id="taskRegex"></button><span id="taskSearchError"></span><select id="taskTypeFilter"><option value=""></option></select><select id="statusFilter"><option value=""></option><option value="running">Running</option><option value="finished">Finished</option></select><input id="submissionFrom"><input id="submissionTo"><input id="finishFrom"><input id="finishTo"><select id="taskSort"><option value="submitted">Submission</option><option value="finished">Finish</option></select><div id="taskLayout"><button data-value="detailed">Detailed</button><button data-value="compact">Compact</button><button data-value="table">Table</button></div><button id="refreshBtn"></button><button id="logoutBtn"></button><button id="selectVisibleBtn"></button><button id="clearSelectionBtn"></button><button id="deleteSelectedBtn"></button><main id="taskList"></main>"""
    page.route("https://dashboard.revocompute.test/**", lambda route: route.fulfill(content_type="text/html", body=html))
    page.goto("https://dashboard.revocompute.test/")
    page.evaluate("""window.escapeHtml=function(value){return String(value==null?'':value)};
      window.REvoDesignTheme={initToggle:function(){},getStoredThemeMode:function(){return 'light'}};
      window.__dashboardRequests=[];
      window.setInterval=function(callback){window.__pollStatuses=callback};
      window.REvoDesignAuth={logout:function(){},authFetch:function(url,options){
        window.__dashboardRequests.push({url:url,method:(options&&options.method)||'GET'});
        if(url==='/input/alpha')return Promise.resolve({ok:true,text:function(){return Promise.resolve('ATOM')}});
        if(url.indexOf('/compute/api/running/')===0)return Promise.resolve({ok:true,json:function(){return Promise.resolve({status:'pending'})}});
        if(url.indexOf('/compute/api/cancel/')===0)return Promise.resolve({ok:true,json:function(){return Promise.resolve({status:'cancelled'})}});
        return Promise.resolve({ok:true,json:function(){return Promise.resolve({})}});
      }};
      window.REvoDesignPy2Dmol={renderAlphaTrace:function(box){box.dataset.rendered='true';return Promise.resolve()}};""")
    page.add_script_tag(path=JS / "ui.js")
    page.add_script_tag(path=JS / "dashboard.js")
    page.evaluate("document.dispatchEvent(new Event('DOMContentLoaded'))")
    expect(page.locator(".task-title").first).to_have_text("new-beta.fasta")
    page.locator("#taskSearch").fill("alpha")
    expect(page.locator(".task-card")).to_have_count(1)
    page.locator("#taskRegex").click(); page.locator("#taskSearch").fill("[")
    expect(page.locator("#taskSearchError")).to_have_text("Invalid regular expression")
    page.locator("#taskSearch").fill("(alpha|beta)")
    expect(page.locator(".task-card")).to_have_count(2)
    page.locator("#taskTypeFilter").select_option("alpha")
    page.locator("#statusFilter").select_option("finished")
    expect(page.locator(".task-card")).to_have_count(1)
    page.locator("#taskTypeFilter").select_option("")
    page.locator("#statusFilter").select_option("")
    page.locator("#taskSort").select_option("finished")
    expect(page.locator(".task-title").first).to_have_text("new-beta.fasta")
    page.get_by_role("button", name="Compact").click()
    page.locator('.task-card[data-md5="' + "a" * 32 + '"] [data-action="details"]').click()
    expect(page.get_by_role("dialog")).to_contain_text("older-alpha.pdb")
    page.get_by_role("dialog").get_by_text("Structure Snapshot").click()
    expect(page.get_by_role("dialog").locator(".structure-preview")).to_have_attribute("data-rendered", "true")
    page.get_by_role("button", name="Close dialog").click()
    page.get_by_role("button", name="Table").click()
    expect(page.locator("#taskList")).to_have_attribute("data-layout", "table")
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
