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
    cards = "".join(
        f'<article class="runner-card" data-search="method {index} folding"><h2>Method {index} with a long scientific Runner name</h2><span class="badge">Restricted</span></article>'
        for index in range(12)
    )
    html = f'<input id="runnerSearch"><select id="runnerCategory"><option value="">All</option></select><span id="runnerCatalogCount"></span><div id="catalogDensity"><button data-value="comfortable">Comfortable</button><button data-value="compact">Compact</button></div><main id="runnerCatalog"><section class="runner-category" data-category="fold">{cards}</section></main><p id="runnerCatalogEmpty" hidden>No methods match</p>'
    page.route("https://catalog.revocompute.test/**", lambda route: route.fulfill(content_type="text/html", body=html))
    page.set_viewport_size({"width": 430, "height": 932})
    page.goto("https://catalog.revocompute.test/")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "base.css")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "index.css")
    page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "runners.css")
    page.add_script_tag(path=JS / "ui.js")
    page.add_script_tag(path=JS / "runners.js")
    expect(page.locator(".runner-card")).to_have_count(12)
    expect(page.locator(".badge", has_text="Restricted")).to_have_count(12)
    page.locator("#runnerSearch").fill("method 11")
    expect(page.locator(".runner-card:not([hidden])")).to_have_count(1)
    page.get_by_role("button", name="Compact").click()
    expect(page.locator("#runnerCatalog")).to_have_attribute("data-density", "compact")
    assert page.evaluate("localStorage.getItem('revocompute.ui.catalog-density.v1')") == "compact"
    page.locator("#runnerSearch").fill("missing")
    expect(page.locator("#runnerCatalogEmpty")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


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
    page.locator("#methodSearch").fill("mmcif")
    expect(page.locator(".method-card")).to_have_count(1)
    page.get_by_role("button", name="Compact").click()
    expect(page.locator("#methodGroups")).to_have_attribute("data-density", "compact")
    assert page.evaluate("localStorage.getItem('revocompute.ui.catalog-density.v1')") == "compact"
    page.locator("#methodSearch").fill("missing")
    expect(page.get_by_text("No methods match that search.")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


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
        {"md5": "a" * 32, "status": "finished", "fasta_fn": "older-alpha.pdb", "task_type": "alpha", "submitted_time": "2026-01-01", "finished_time": "2026-01-03", "submitted_timestamp": 1767225600, "finished_timestamp": 1767398400, "walltime": "1m", "sequence": "AAA", "can_delete": False, "owner": "u", "structure_input": True, "input_url": "/input/alpha", "structure_format": "pdb"},
        {"md5": "b" * 32, "status": "running", "fasta_fn": "new-beta.fasta", "task_type": "beta", "submitted_time": "2026-01-02", "finished_time": "-", "submitted_timestamp": 1767312000, "finished_timestamp": 0, "walltime": "-", "sequence": "BBB", "can_delete": True, "owner": "u"},
        {"md5": "c" * 32, "status": "failed", "fasta_fn": "failed-gamma-with-an-intentionally-long-scientific-task-name-for-phone-layout.fasta", "task_type": "gamma", "submitted_time": "2026-01-02", "finished_time": "2026-01-03", "submitted_timestamp": 1767311000, "finished_timestamp": 1767398300, "walltime": "2m", "sequence": "CCC", "can_delete": True, "owner": "u", "error": "Runner failed after a populated test state."},
    ]
    tasks.extend({"md5": f"{index:032d}", "status": "finished", "fasta_fn": f"bulk-{index}.fasta", "task_type": f"method-{index:03d}", "submitted_timestamp": index, "finished_timestamp": index, "can_delete": False} for index in range(100))
    html = f"""<script id="dashboard-task-data" type="application/json">{json.dumps({'tasks': tasks, 'is_admin': False})}</script><span id="totalTasks"></span><span id="inQueue"></span><span id="inRunning"></span><span id="finished"></span><span id="issues"></span><div id="toastWrap"></div><div id="adminTools"></div><input id="taskSearch"><button id="taskRegex"></button><span id="taskSearchError"></span><input id="taskTypeFilter" list="taskTypeOptions"><button id="taskTypeRegex"></button><datalist id="taskTypeOptions"></datalist><span id="taskTypeSearchError"></span><select id="statusFilter"><option value=""></option><option value="running">Running</option><option value="finished">Finished</option></select><input id="submissionFrom" type="date"><input id="submissionTo" type="date"><input id="finishFrom" type="date"><input id="finishTo" type="date"><select id="taskSort"><option value="submitted">Submission</option><option value="finished">Finish</option></select><div id="taskLayout"><button data-value="detailed">Detailed</button><button data-value="compact">Compact</button><button data-value="table">Table</button></div><button id="refreshBtn"></button><button id="logoutBtn"></button><button id="selectVisibleBtn"></button><button id="clearSelectionBtn"></button><button id="deleteSelectedBtn"></button><main class="board" id="taskList"></main>"""
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


def test_landing_page_visual_chapters_at_acceptance_viewports(page: Page) -> None:
    for width, height in (
        (1920, 1080), (1440, 900), (1366, 768), (1024, 1366), (834, 1194), (430, 932), (390, 844),
    ):
        page.set_viewport_size({"width": width, "height": height})
        page.set_content(_template("index.html"))
        page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "base.css")
        page.add_style_tag(path=ROOT / "revocompute" / "static" / "css" / "index.css")
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        tops = page.evaluate("""() => ['.landing-hero','.agent-entry','.approach-section','.workflow-section','.product-section','.closing-section'].map(function (selector) { return document.querySelector(selector).getBoundingClientRect().top + scrollY; })""")
        assert tops == sorted(tops) and len(set(tops)) == len(tops), (width, height, tops)
        expect(page.locator(".hero-cta .btn-primary")).to_be_visible()
        if width >= 1366:
            assert page.locator(".hero-cta").evaluate("node => node.getBoundingClientRect().bottom <= innerHeight"), (width, height)
