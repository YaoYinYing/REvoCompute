# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser contracts for server-rendered pages outside the application cutover."""

from __future__ import annotations

from pathlib import Path
import re

from playwright.sync_api import Page, expect
import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "revocompute" / "static" / "css"
JS = ROOT / "revocompute" / "static" / "js"
TEMPLATES = ROOT / "revocompute" / "templates"


def _template(name: str) -> str:
    source = (TEMPLATES / name).read_text(encoding="utf-8")
    source = re.sub(r'<script[^>]+src="[^"]+"[^>]*></script>', "", source)
    source = re.sub(r"{{.*?}}", "Example", source, flags=re.DOTALL)
    return re.sub(r"{%-?.*?-?%}", "", source, flags=re.DOTALL)


def _add_styles(page: Page, *names: str) -> None:
    page.add_style_tag(path=CSS / "base.css")
    for name in names:
        page.add_style_tag(path=CSS / name)


def _assert_no_document_overflow(page: Page) -> None:
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def _assert_contained(page: Page, selector: str, width: int) -> None:
    for left, right in page.locator(selector).evaluate_all(
        "nodes => nodes.map(node => { const box = node.getBoundingClientRect(); return [box.left, box.right]; })"
    ):
        assert left >= -1, (selector, left, right)
        assert right <= width + 1, (selector, left, right)


@pytest.mark.parametrize("width", [320, 390, 768, 1024])
def test_public_navigation_stays_discoverable_at_narrow_widths(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(_template("index.html"))
    _add_styles(page, "index.css")

    toggle = page.locator(".nav-menu-toggle")
    checkbox = page.get_by_role("checkbox", name="More navigation")
    expect(toggle).to_be_visible()
    expect(checkbox).to_be_visible()
    expect(checkbox).not_to_be_checked()
    expect(page.locator(".nav-links")).to_be_hidden()

    toggle.click()
    expect(checkbox).to_be_checked()
    expect(page.locator(".nav-menu .nav-links")).to_be_visible()
    expect(page.locator(".nav-links").get_by_role("link").first).to_be_visible()
    _assert_contained(page, ".nav-menu .nav-links", width)
    _assert_contained(page, ".nav-menu .nav-links a", width)
    _assert_no_document_overflow(page)


def test_public_navigation_is_keyboard_operable(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 900})
    page.set_content(_template("index.html"))
    _add_styles(page, "index.css")

    checkbox = page.get_by_role("checkbox", name="More navigation")
    checkbox.focus()
    page.keyboard.press("Space")
    expect(checkbox).to_be_checked()
    expect(page.locator(".nav-menu .nav-links")).to_be_visible()
    assert page.locator(".nav-menu-toggle").evaluate("node => getComputedStyle(node).outlineStyle") != "none"


def test_configuration_tasktype_filter(page: Page) -> None:
    page.set_content(_template("configuration.html"))
    page.evaluate(
        """() => {
          window.escapeHtml = value => String(value == null ? '' : value);
          window.REvoDesignTheme = {initToggle() {}};
          window.REvoDesignAuth = {
            logout() {},
            authFetch() { return Promise.resolve({ok: true, json() { return Promise.resolve({
              task_types: [{tool: 'alpha', display_name: 'Alpha', enabled: true,
                runtime_family: 'family-a', is_workflow_stage: false,
                effective_resources: {cpus: 4, memory: '8G', max_runtime_seconds: 60}}],
              resources: {}, slurm: {enabled: false, allowed_queues: []}
            }); }}); }
          };
          window.fetch = () => Promise.resolve({ok: true, json() { return Promise.resolve({
            task_types: [{name: 'alpha', display_name: 'Alpha', category: 'fold',
              input_extension: '.fasta', input_label: 'Sequence', stage_markers: {}, params: []}]
          }); }});
        }"""
    )
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
        "components": [{
            "component": "result_storage",
            "status": "DEGRADED",
            "reason_code": "disk_space_low",
            "message": "Required storage has low free space.",
            "checked_at": "2026-09-15T08:00:00+00:00",
            "duration_ms": 4,
            "failure_count": 1,
            "next_action": "Plan storage cleanup or expansion.",
            "stale": True,
        }],
    }
    page.set_content(_template("configuration.html"))
    page.evaluate(
        """readiness => {
          window.escapeHtml = value => String(value == null ? '' : value);
          window.REvoDesignTheme = {initToggle() {}};
          window.infrastructureCalls = [];
          window.REvoDesignAuth = {
            logout() {},
            authFetch(url, options) {
              if (url.includes('infrastructure')) {
                window.infrastructureCalls.push([url, options && options.method]);
                return Promise.resolve({ok: true, json() { return Promise.resolve(readiness); }});
              }
              return Promise.resolve({ok: true, json() { return Promise.resolve({
                task_types: [], resources: {}, slurm: {enabled: false, allowed_queues: []}
              }); }});
            }
          };
          window.fetch = () => Promise.resolve({ok: true, json() { return Promise.resolve({task_types: []}); }});
        }""",
        payload,
    )
    _add_styles(page, "configuration.css")
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


def test_landing_page_visual_chapters_at_acceptance_viewports(page: Page) -> None:
    origin = "https://landing.revocompute.test"
    page.route(f"{origin}/", lambda route: route.fulfill(content_type="text/html", body=_template("index.html")))
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(f"{origin}/", wait_until="domcontentloaded")
    _add_styles(page, "index.css")
    page.evaluate(
        """() => {
          Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {
            writeText(value) { window.__copiedAgentUrl = value; return Promise.resolve(); }
          }});
          window.setTimeout = () => {};
        }"""
    )
    page.add_script_tag(path=JS / "index-agent-guide.js")

    for width, height in (
        (1920, 1080), (1440, 900), (1366, 768), (1024, 1366), (834, 1194), (430, 932), (390, 844),
    ):
        page.set_viewport_size({"width": width, "height": height})
        _assert_no_document_overflow(page)
        tops = page.evaluate(
            """() => ['.landing-hero', '.agent-entry', '.approach-section', '.workflow-section',
              '.product-section', '.closing-section'].map(selector =>
                document.querySelector(selector).getBoundingClientRect().top + scrollY)"""
        )
        assert tops == sorted(tops) and len(set(tops)) == len(tops), (width, height, tops)
        expect(page.locator(".hero-cta .btn-primary")).to_be_visible()
        hierarchy = page.evaluate(
            """() => ['.agent-entry-heading', '.agent-entry-description', '.agent-url-row']
              .map(selector => document.querySelector(selector).getBoundingClientRect().top)"""
        )
        assert hierarchy == sorted(hierarchy) and len(set(hierarchy)) == 3, (width, hierarchy)
        assert page.locator(".agent-url-row").evaluate(
            "node => node.scrollWidth <= node.clientWidth + 1 && node.getBoundingClientRect().right <= innerWidth"
        )
        assert page.locator("#agentSkillsUrl").get_attribute("title") == f"{origin}/skills.md"
        if width >= 1366:
            assert page.locator(".hero-cta").evaluate("node => node.getBoundingClientRect().bottom <= innerHeight")
            assert page.locator(".landing-hero").evaluate(
                "node => node.getBoundingClientRect().bottom <= innerHeight + 1"
            )
        box_height = page.locator(".agent-entry").evaluate("node => node.getBoundingClientRect().height")
        page.locator("#copyAgentSkillsUrl").click()
        expect(page.locator("#copyAgentSkillsUrl")).to_have_text("Copied")
        assert page.evaluate("window.__copiedAgentUrl") == f"{origin}/skills.md"
        resized_height = page.locator(".agent-entry").evaluate("node => node.getBoundingClientRect().height")
        assert abs(resized_height - box_height) <= 1


def _contrast_ratio(page: Page, foreground: str, background: str) -> float:
    return page.evaluate(
        """([foreground, background]) => {
          const rgb = value => {
            const values = text => text.match(/[\\d.]+/g).map(Number);
            const comma = value.match(/rgba?\\(([^)]+)\\)/);
            if (comma) return values(comma[1]);
            const srgb = value.match(/color\\(srgb\\s+([^)]+)\\)/);
            if (srgb) return values(srgb[1]).map(channel => channel * 255);
            throw new Error('Unsupported color syntax: ' + value);
          };
          const luminance = channels => channels.slice(0, 3).reduce((total, channel, index) => {
            const value = channel / 255;
            const linear = value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
            return total + linear * [0.2126, 0.7152, 0.0722][index];
          }, 0);
          const [high, low] = [luminance(rgb(foreground)), luminance(rgb(background))].sort((a, b) => b - a);
          return (high + 0.05) / (low + 0.05);
        }""",
        [foreground, background],
    )


def test_landing_agent_card_follows_light_and_dark_theme_tokens(page: Page) -> None:
    origin = "https://landing.revocompute.test"
    page.route(f"{origin}/", lambda route: route.fulfill(content_type="text/html", body=_template("index.html")))
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{origin}/", wait_until="domcontentloaded")
    _add_styles(page, "index.css")
    page.add_script_tag(path=JS / "theme.js")

    card = page.locator(".agent-entry")
    samples = {}
    for theme in ("light", "dark"):
        page.evaluate("theme => window.REvoDesignTheme.applyTheme(theme)", theme)
        samples[theme] = card.evaluate(
            """node => {
              const resolved = (element, property) => getComputedStyle(element)[property];
              return {
                background: resolved(node, 'backgroundColor'),
                heading: resolved(node.querySelector('.agent-entry-heading h2'), 'color'),
                description: resolved(node.querySelector('.agent-entry-description'), 'color'),
                url: resolved(node.querySelector('#agentSkillsUrl'), 'color')
              };
            }"""
        )

    assert samples["light"]["background"] != samples["dark"]["background"]
    for theme in ("light", "dark"):
        for role in ("heading", "description", "url"):
            ratio = _contrast_ratio(page, samples[theme][role], samples[theme]["background"])
            assert ratio >= 4.5, (theme, role, ratio, samples[theme])


def test_swagger_surfaces_follow_live_light_and_dark_themes(page: Page) -> None:
    page.set_content("""<section id="swagger-ui"><div class="swagger-ui" data-render="stable">
      <section class="models"><h4 class="model-title">Schemas</h4>
        <div class="model-container"><span class="model">Task</span></div></section>
      <div class="opblock opblock-post"><div class="opblock-summary">
        <span class="opblock-summary-description">Submit task</span></div>
        <div class="opblock-section-header"><h4>Parameters</h4></div>
        <div class="opblock-description-wrapper"><p>Task input</p></div>
        <label><span class="parameter__name required">Name</span>
          <input type="text" placeholder="Task name"></label>
        <select aria-label="Task type"><option>Example</option></select>
        <textarea placeholder="Request body"></textarea>
        <button class="btn execute">Execute</button><button class="btn cancel">Cancel</button>
        <table class="responses-table"><thead><tr><th>Status</th><th>Description</th></tr></thead>
          <tbody><tr><td class="response-col_status">200</td>
            <td class="response-col_description">OK<pre>response body</pre></td></tr></tbody></table>
        <div class="highlight-code"><pre class="microlight">curl /compute/api/post</pre></div>
        <div class="request-url">/compute/api/post</div>
      </div><a href="#schemas">Schema link</a></div></section>""")
    _add_styles(page, "api-docs.css")

    root = page.locator("#swagger-ui .swagger-ui")
    field = page.get_by_placeholder("Task name")
    page.evaluate("document.documentElement.dataset.theme = 'light'")
    light = field.evaluate("node => [getComputedStyle(node).color, getComputedStyle(node).backgroundColor]")
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    dark = field.evaluate("node => [getComputedStyle(node).color, getComputedStyle(node).backgroundColor]")
    assert light != dark and dark[0] != dark[1]
    assert root.get_attribute("data-render") == "stable"
    for selector in (
        ".opblock-description-wrapper", ".response-col_description", ".model-title", ".highlight-code",
        ".request-url", ".btn.execute", "a",
    ):
        colors = root.locator(selector).first.evaluate(
            "node => [getComputedStyle(node).color, getComputedStyle(node).backgroundColor]"
        )
        assert colors[0] != colors[1], selector


def _search_metrics(page: Page) -> dict:
    return page.locator(".ui-search input.search-input").first.evaluate(
        """node => {
          const style = getComputedStyle(node); const box = node.getBoundingClientRect();
          return {height: Math.round(box.height), minHeight: style.minHeight, radius: style.borderRadius,
            paddingLeft: style.paddingLeft, paddingRight: style.paddingRight, fontSize: style.fontSize,
            fontFamily: style.fontFamily, backgroundImage: style.backgroundImage, borderWidth: style.borderWidth};
        }"""
    )


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_user_control_search_is_responsive_and_keyboard_visible(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(_template("user_control.html"))
    _add_styles(page, "user-control.css")

    control = page.locator(".ui-search").first
    expect(control).to_be_visible()
    _assert_contained(page, ".ui-search", width)
    _assert_no_document_overflow(page)

    metrics = _search_metrics(page)
    assert metrics["radius"] == "12px", metrics
    assert metrics["minHeight"] == "37.6px", metrics
    assert 34 <= metrics["height"] <= 44, metrics
    assert float(metrics["paddingLeft"][:-2]) > float(metrics["paddingRight"][:-2]), metrics
    assert "svg" in metrics["backgroundImage"], metrics

    field = page.locator(".ui-search input.search-input").first
    field.focus()
    assert field.evaluate("node => getComputedStyle(node).boxShadow") not in ("", "none")


def test_user_control_and_configuration_search_controls_match(page: Page) -> None:
    page.set_viewport_size({"width": 1280, "height": 900})
    page.set_content(_template("user_control.html"))
    _add_styles(page, "user-control.css")
    user_metrics = _search_metrics(page)
    user_metrics.pop("height")

    page.set_content(_template("configuration.html"))
    _add_styles(page, "configuration.css")
    configuration_metrics = _search_metrics(page)
    configuration_metrics.pop("height")

    assert user_metrics == configuration_metrics, (user_metrics, configuration_metrics)
