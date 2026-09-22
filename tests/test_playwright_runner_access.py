# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "revocompute" / "templates"
STATIC_JS = ROOT / "revocompute" / "static" / "js"
STATIC_CSS = ROOT / "revocompute" / "static" / "css"
UI_JS = STATIC_JS / "ui.js"


def _template_body(name: str) -> str:
    html = (TEMPLATES / name).read_text(encoding="utf-8")
    html = re.sub(r'<script[^>]+src="[^"]+"[^>]*></script>', "", html)
    html = re.sub(r'<link[^>]+href="https://[^"]+"[^>]*>', "", html)
    return html.replace('{{ {"is_admin": is_admin_user} | tojson }}', '{"is_admin": true}')


def _install_runtime(page: Page, auth_fetch: str) -> None:
    page.add_style_tag(path=STATIC_CSS / "base.css")
    page.add_style_tag(path=STATIC_CSS / "profile.css")
    page.add_style_tag(path=STATIC_CSS / "user-control.css")
    page.add_style_tag(
        content="*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}"
    )
    page.evaluate(
        """
        window.REvoDesignTheme = {initToggle: function () {}};
        window.REvoDesignAuth = {
          authFetch: %s,
          logout: function () {}
        };
        window.escapeHtml = function (value) { return String(value == null ? "" : value).replace(/[&<>"']/g, "_"); };
        """ % auth_fetch
    )
    page.add_script_tag(path=UI_JS)


def _open_section(page: Page, label: str) -> None:
    """Switch the settings surface to one section (desktop sidebar or tab strip)."""
    page.locator("#profileTabs").get_by_role("button", name=label, exact=True).click()


def _assert_no_document_overflow(page: Page) -> None:
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_profile_discovers_and_requests_restricted_runner_access(page: Page) -> None:
    page.set_content(_template_body("profile.html"))
    _install_runtime(
        page,
        """function (url, options) {
          window.__accessState = window.__accessState || "restricted";
          if (url === "/compute/api/access/requests") {
            window.__requestPayload = JSON.parse(options.body);
            window.__accessState = "pending";
            return Promise.resolve({ok: true, json: function () { return Promise.resolve({}); }});
          }
          if (url === "/compute/api/access") {
            var pending = window.__accessState === "pending";
            return Promise.resolve({ok: true, json: function () { return Promise.resolve({policies: [{
              policy_id: "alphafold3_noncommercial", label: "AlphaFold 3 non-commercial use",
              description: "Restricted Runner", granted: false, requestable: true,
              request_status: pending ? "pending" : null,
              license: {name: "AlphaFold 3 Terms of Use", url: "https://example.test/terms"}
            }]}); }});
          }
          if (url === "/compute/api/auth/me") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({username: "researcher", email: "r@example.test", role: "user"});
          }});
          if (url === "/compute/api/auth/me/api-key") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({has_api_key: false});
          }});
          if (url.indexOf("/compute/api/user-metrics") === 0) return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({
              window: "30d", days: 30, period: "2026-09-22", tasks_submitted: 3, tasks_completed: 2,
              tasks_failed: 1, success_rate: 2 / 3, cpu_tasks: 2, gpu_tasks: 1, gpu_minutes: 12.5,
              total_runtime_seconds: 5400, median_runtime_seconds: 900,
              distribution: [{task_type: "gremlin", label: "PSSM-GREMLIN", gpu: false, tasks: 2}],
              activity: [{period: "2026-09-01", count: 1}, {period: "2026-09-02", count: 0}]
            });
          }});
          return Promise.resolve({ok: false, json: function () { return Promise.resolve({}); }});
        }""",
    )
    page.add_script_tag(path=STATIC_JS / "profile.js")

    expect(page.locator("#section-profile")).to_be_visible()
    expect(page.locator("#section-runner-access")).to_be_hidden()
    _open_section(page, "Runner Access")

    expect(page.get_by_role("heading", name="AlphaFold 3 non-commercial use")).to_be_visible()
    expect(page.get_by_text("Requestable", exact=True)).to_be_visible()
    expect(page.get_by_text("AlphaFold 3 Terms of Use", exact=True)).to_be_visible()
    details = page.locator("#runnerAccessList details")
    expect(details).to_have_count(1)
    expect(details.locator("summary")).to_have_text("Details")
    details.locator("summary").click()
    expect(details.get_by_text("Restricted Runner", exact=True)).to_be_visible()
    license_link = page.get_by_role("link", name=re.compile("AlphaFold 3 Terms of Use"))
    expect(license_link).to_have_attribute("href", "https://example.test/terms")
    expect(license_link).to_have_attribute("rel", "noopener noreferrer")
    reason = page.get_by_label("Research use and affiliation")
    expect(reason).to_have_attribute("maxlength", "1000")
    reason.fill("   ")
    page.get_by_role("button", name="Request access").click()
    expect(page.get_by_text("Describe your research use before requesting access.", exact=True)).to_be_visible()
    assert page.evaluate("window.__requestPayload") is None
    reason.fill("Non-commercial structural biology research at Example University")
    page.get_by_role("button", name="Request access").click()
    expect(page.get_by_text("Pending", exact=True)).to_be_visible()
    expect(page.get_by_text("Request submitted — awaiting an administrator decision.", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Request access")).to_have_count(0)
    assert page.evaluate("window.__requestPayload.reason") == (
        "Non-commercial structural biology research at Example University"
    )


def test_profile_renders_self_scoped_gpu_credit_ledger(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.set_content(_template_body("profile.html"))
    _install_runtime(
        page,
        """function (url) {
          if (url === "/compute/api/gpu-credit") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({period: "2026-09", allow_gpu_use: true, monthly_grant_credits: 1000,
              adjustment_credits: 200, usage_credits: 346.8, remaining_credits: 853.2,
              history: [{kind: "usage", gpu_seconds: -120, reason: "Actual Slurm GPU allocation time", created_at: 1788393600},
                {kind: "admin_adjustment", gpu_seconds: 12000, reason: "Approved collaboration run", created_at: 1788307200}]});
          }});
          if (url === "/compute/api/access") return Promise.resolve({ok: true, json: function () { return Promise.resolve({policies: []}); }});
          if (url === "/compute/api/auth/me") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({username: "researcher", email: "r@example.test", role: "user"});
          }});
          if (url === "/compute/api/auth/me/api-key") return Promise.resolve({ok: true, json: function () { return Promise.resolve({has_api_key: false}); }});
          if (url.indexOf("/compute/api/user-metrics") === 0) return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({window: "30d", days: 30, period: "2026-09-22", tasks_submitted: 0,
              tasks_completed: 0, tasks_failed: 0, success_rate: null, cpu_tasks: 0, gpu_tasks: 0,
              gpu_minutes: 0, total_runtime_seconds: 0, median_runtime_seconds: null,
              distribution: [], activity: []});
          }});
          return Promise.resolve({ok: false, json: function () { return Promise.resolve({}); }});
        }""",
    )
    page.add_script_tag(path=STATIC_JS / "profile.js")

    _open_section(page, "GPU Credits")
    expect(page.get_by_role("heading", name="GPU Credits")).to_be_visible()
    expect(page.locator("#gpuCreditPeriod")).to_have_text("September 2026")
    expect(page.locator("#gpuRemaining")).to_have_text("853.2")
    expect(page.get_by_text("Approved collaboration run", exact=True)).to_be_visible()
    _assert_no_document_overflow(page)
    _open_section(page, "API Key")
    expect(page.locator("#apiKeyStatus")).to_contain_text("No API key configured")
    expect(page.get_by_role("button", name="Generate API Key")).to_be_visible()
    _assert_no_document_overflow(page)


def test_profile_metrics_window_selector_updates_displayed_data(page: Page) -> None:
    page.set_content(_template_body("profile.html"))
    _install_runtime(
        page,
        """function (url) {
          if (url.indexOf("/compute/api/user-metrics") === 0) {
            var selected = url.split("window=")[1];
            var payloads = {
              "7d": {tasks_submitted: 1, tasks_completed: 1, tasks_failed: 0, success_rate: 1,
                cpu_tasks: 1, gpu_tasks: 0, gpu_minutes: 0, total_runtime_seconds: 60,
                median_runtime_seconds: 60, distribution: [{task_type: "gremlin", label: "PSSM-GREMLIN", gpu: false, tasks: 1}],
                activity: [{period: "2026-09-22", count: 1}]},
              "30d": {tasks_submitted: 4, tasks_completed: 3, tasks_failed: 1, success_rate: 0.75,
                cpu_tasks: 2, gpu_tasks: 2, gpu_minutes: 42, total_runtime_seconds: 7200,
                median_runtime_seconds: 1800, distribution: [{task_type: "gremlin", label: "PSSM-GREMLIN", gpu: false, tasks: 2},
                  {task_type: "alphafold3", label: "AlphaFold 3", gpu: true, tasks: 2}],
                activity: [{period: "2026-09-10", count: 2}, {period: "2026-09-11", count: 2}]},
              "90d": {tasks_submitted: 9, tasks_completed: 8, tasks_failed: 1, success_rate: 8 / 9,
                cpu_tasks: 4, gpu_tasks: 5, gpu_minutes: 120, total_runtime_seconds: 14400,
                median_runtime_seconds: 3600, distribution: [{task_type: "gremlin", label: "PSSM-GREMLIN", gpu: false, tasks: 9}],
                activity: [{period: "2026-07-01", count: 9}]},
              "quarter": {tasks_submitted: 12, tasks_completed: 11, tasks_failed: 1, success_rate: 11 / 12,
                cpu_tasks: 6, gpu_tasks: 6, gpu_minutes: 240, total_runtime_seconds: 21600,
                median_runtime_seconds: 5400, distribution: [{task_type: "gremlin", label: "PSSM-GREMLIN", gpu: false, tasks: 12}],
                activity: [{period: "2026-06-23", count: 12}]}
            };
            window.__metricsWindows = (window.__metricsWindows || []).concat([selected]);
            var body = payloads[selected] || payloads["30d"];
            body.window = selected;
            body.days = {"7d": 7, "30d": 30, "90d": 90, "quarter": 92}[selected];
            body.period = "2026-09-22";
            return Promise.resolve({ok: true, json: function () { return Promise.resolve(body); }});
          }
          if (url === "/compute/api/access") return Promise.resolve({ok: true, json: function () { return Promise.resolve({policies: []}); }});
          if (url === "/compute/api/auth/me") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({username: "researcher", email: "r@example.test", role: "user"});
          }});
          if (url === "/compute/api/auth/me/api-key") return Promise.resolve({ok: true, json: function () { return Promise.resolve({has_api_key: false}); }});
          if (url === "/compute/api/gpu-credit") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({period: "2026-09", allow_gpu_use: true, monthly_grant_credits: 1000,
              adjustment_credits: 0, usage_credits: 0, remaining_credits: 1000, history: []});
          }});
          return Promise.resolve({ok: false, json: function () { return Promise.resolve({}); }});
        }""",
    )
    page.add_script_tag(path=STATIC_JS / "profile.js")

    _open_section(page, "Metrics")
    expect(page.locator("#section-metrics")).to_be_visible()
    expect(page.locator("#metricsSubmitted")).to_have_text("4")
    expect(page.locator("#metricsSuccessRate")).to_have_text("75%")
    expect(page.locator("#metricsGpuMinutes")).to_have_text("42")
    expect(page.locator("#metricsMedianRuntime")).to_have_text("30m")
    expect(page.locator("#metricsPeriod")).to_contain_text("30d window")
    expect(page.locator("#metricsComposition")).to_contain_text("2 CPU · 2 GPU")
    expect(page.locator("#metricsComposition")).to_contain_text("2.0h total runtime")
    expect(page.locator("#metricsActivity svg")).to_have_count(1)
    expect(page.locator("#metricsDistribution .metrics-bar-row")).to_have_count(2)
    expect(page.locator("#metricsDistribution")).to_contain_text("AlphaFold 3")
    assert page.evaluate("window.__metricsWindows") == ["30d"]

    page.locator("#metricsWindow").get_by_role("button", name="7 days").click()
    expect(page.locator("#metricsSubmitted")).to_have_text("1")
    expect(page.locator("#metricsPeriod")).to_contain_text("7d window")
    expect(page.locator("#metricsDistribution .metrics-bar-row")).to_have_count(1)
    assert page.evaluate("window.__metricsWindows") == ["30d", "7d"]

    page.locator("#metricsWindow").get_by_role("button", name="Quarter").click()
    expect(page.locator("#metricsSubmitted")).to_have_text("12")
    expect(page.locator("#metricsPeriod")).to_contain_text("quarter window")
    assert page.evaluate("window.__metricsWindows") == ["30d", "7d", "quarter"]
    _assert_no_document_overflow(page)


def test_profile_section_navigation_reaches_every_section_by_url_and_keyboard(page: Page) -> None:
    page.set_content(_template_body("profile.html"))
    _install_runtime(
        page,
        """function (url) {
          if (url === "/compute/api/access") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({policies: [
              {policy_id: "granted_policy", label: "Granted Runner", granted: true, requestable: false,
               expires_at: 1790000000, license: {name: "Granted Terms", url: "https://example.test/granted"}},
              {policy_id: "pending_policy", label: "Pending Runner", granted: false, requestable: true,
               request_status: "pending"},
              {policy_id: "rejected_policy", label: "Rejected Runner", granted: false, requestable: true,
               request_status: "rejected"},
              {policy_id: "expired_policy", label: "Expired Runner", granted: false, requestable: true,
               expired: true, request_status: "approved"},
              {policy_id: "restricted_policy", label: "Restricted Runner", granted: false, requestable: false}
            ]});
          }});
          if (url === "/compute/api/auth/me") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({username: "researcher", email: "r@example.test", role: "user",
              full_name: "Example Researcher", affiliation: "Example University", position: "phd_student",
              pi_name: "Professor Example"});
          }});
          if (url === "/compute/api/auth/me/api-key") return Promise.resolve({ok: true, json: function () { return Promise.resolve({has_api_key: false}); }});
          if (url === "/compute/api/gpu-credit") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({period: "2026-09", allow_gpu_use: false, monthly_grant_credits: 1000,
              adjustment_credits: 0, usage_credits: 100, remaining_credits: 900, history: []});
          }});
          if (url.indexOf("/compute/api/user-metrics") === 0) return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({window: "30d", days: 30, period: "2026-09-22", tasks_submitted: 0,
              tasks_completed: 0, tasks_failed: 0, success_rate: null, cpu_tasks: 0, gpu_tasks: 0,
              gpu_minutes: 0, total_runtime_seconds: 0, median_runtime_seconds: null,
              distribution: [], activity: []});
          }});
          return Promise.resolve({ok: false, json: function () { return Promise.resolve({}); }});
        }""",
    )
    page.add_script_tag(path=STATIC_JS / "profile.js")

    tabs = page.locator("#profileTabs")
    expect(tabs).to_be_visible()
    expect(tabs.get_by_role("button", name="Profile", exact=True)).to_be_visible()
    expect(tabs.get_by_role("button", name="Security", exact=True)).to_be_visible()
    expect(tabs.get_by_role("button", name="API Key", exact=True)).to_be_visible()
    expect(tabs.get_by_role("button", name="Runner Access", exact=True)).to_be_visible()
    expect(tabs.get_by_role("button", name="GPU Credits", exact=True)).to_be_visible()
    expect(tabs.get_by_role("button", name="Metrics", exact=True)).to_be_visible()

    # The Profile section owns identity, never credentials.
    expect(page.locator("#profileUsername")).to_have_text("researcher")
    expect(page.locator("#profileEmail")).to_have_text("r@example.test")
    expect(page.locator("#profileRole")).to_have_text("User")
    expect(page.locator("#passwordForm")).to_be_hidden()

    # Every section is reachable by URL hash...
    for section, anchor in (
        ("security", "#passwordForm"),
        ("api-key", "#apiKeyStatus"),
        ("runner-access", "#runnerAccessList"),
        ("gpu-credits", "#gpuRemaining"),
    ):
        page.evaluate("location.hash = '#%s'" % section)
        expect(page.locator("#section-%s" % section)).to_be_visible()
        expect(page.locator(anchor)).to_be_visible()

    # ... and the section switch is a shared layout transition that the
    # reduced-motion rule neutralises.
    assert page.evaluate(
        "getComputedStyle(document.getElementById('section-gpu-credits')).animationName === 'none'"
        " || getComputedStyle(document.getElementById('section-gpu-credits')).animationDuration === '0s'"
    )

    # Keyboard operation: focusing a tab and pressing Enter or Space activates it.
    page.evaluate("location.hash = '#profile'")
    api_key_tab = tabs.get_by_role("button", name="API Key", exact=True)
    api_key_tab.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#section-api-key")).to_be_visible()
    expect(page).to_have_url(re.compile(r"#api-key$"))

    gpu_tab = tabs.get_by_role("button", name="GPU Credits", exact=True)
    gpu_tab.focus()
    page.keyboard.press("Space")
    expect(page.locator("#section-gpu-credits")).to_be_visible()
    expect(page).to_have_url(re.compile(r"#gpu-credits$"))

    # Runner Access states render as state-first rows.
    _open_section(page, "Runner Access")
    rows = page.locator("#runnerAccessList .access-row")
    expect(rows).to_have_count(5)
    for state in ("Granted", "Pending", "Rejected", "Expired", "Restricted"):
        expect(page.locator("#runnerAccessList .access-state", has_text=state)).to_have_count(1)
    granted = rows.nth(0)
    expect(granted.locator(".access-detail")).to_contain_text("Valid until")
    expect(granted.locator(".access-restriction")).to_have_text("Granted Terms")
    expect(page.get_by_role("button", name="Request access")).to_have_count(2)
    expect(rows.nth(1).get_by_role("button", name="Request access")).to_have_count(0)
    expect(rows.nth(2).locator(".access-detail")).to_contain_text("not approved")
    expect(rows.nth(3).locator(".access-detail")).to_contain_text("expired")

    # Dense layout: each policy row stays well under a verbose card height.
    assert rows.nth(0).evaluate("node => node.getBoundingClientRect().height < 120")


def _profile_auth_stub() -> str:
    return """function (url) {
      if (url === "/compute/api/access") return Promise.resolve({ok: true, json: function () {
        return Promise.resolve({policies: [
          {policy_id: "granted_policy", label: "Granted Runner", granted: true, requestable: false,
           expires_at: 1790000000, license: {name: "Granted Terms", url: "https://example.test/granted"},
           description: "Non-commercial research use only."},
          {policy_id: "restricted_policy", label: "Restricted Runner", granted: false, requestable: false,
           description: "Operator verification is required before use."}
        ]});
      }});
      if (url === "/compute/api/auth/me") return Promise.resolve({ok: true, json: function () {
        return Promise.resolve({username: "researcher", email: "r@example.test", role: "user",
          full_name: "Example Researcher", affiliation: "Example University", position: "phd_student"});
      }});
      if (url === "/compute/api/auth/me/api-key") return Promise.resolve({ok: true, json: function () { return Promise.resolve({has_api_key: false}); }});
      if (url === "/compute/api/gpu-credit") return Promise.resolve({ok: true, json: function () {
        return Promise.resolve({period: "2026-09", allow_gpu_use: true, monthly_grant_credits: 1000,
          adjustment_credits: 0, usage_credits: 100, remaining_credits: 900, history: []});
      }});
      if (url.indexOf("/compute/api/user-metrics") === 0) return Promise.resolve({ok: true, json: function () {
        return Promise.resolve({window: "30d", days: 30, period: "2026-09-22", tasks_submitted: 2,
          tasks_completed: 2, tasks_failed: 0, success_rate: 1, cpu_tasks: 2, gpu_tasks: 0,
          gpu_minutes: 0, total_runtime_seconds: 120, median_runtime_seconds: 60,
          distribution: [{task_type: "gremlin", label: "PSSM-GREMLIN", gpu: false, tasks: 2}],
          activity: [{period: "2026-09-21", count: 1}, {period: "2026-09-22", count: 1}]});
      }});
      return Promise.resolve({ok: false, json: function () { return Promise.resolve({}); }});
    }"""


def test_profile_settings_layout_holds_at_every_supported_width(page: Page) -> None:
    for width, height in ((320, 720), (390, 844), (768, 1024), (1440, 900), (2560, 1080)):
        page.set_viewport_size({"width": width, "height": height})
        page.goto("about:blank")
        page.set_content(_template_body("profile.html"))
        _install_runtime(page, _profile_auth_stub())
        page.add_script_tag(path=STATIC_JS / "profile.js")
        expect(page.locator("#profileTabs")).to_be_visible()
        _assert_no_document_overflow(page)

        # Desktop keeps a sticky sidebar column; narrow screens stack it above
        # the panel and keep every tab inside the viewport.
        tabs_box = page.locator("#profileTabs").bounding_box()
        panel_box = page.locator("#section-profile").bounding_box()
        if width >= 1200:
            assert tabs_box["x"] + tabs_box["width"] <= panel_box["x"] + 1, width
            assert panel_box["width"] > tabs_box["width"], width
        else:
            assert tabs_box["y"] + tabs_box["height"] <= panel_box["y"] + 1, width
            assert tabs_box["x"] + tabs_box["width"] <= width + 1, width
            assert panel_box["x"] + panel_box["width"] <= width + 1, width

        for label in ("Profile", "Security", "API Key", "Runner Access", "GPU Credits", "Metrics"):
            tab = page.locator("#profileTabs").get_by_role("button", name=label, exact=True)
            expect(tab).to_be_visible()
            tab.click()
            expect(page.locator("#profileTabs .sub-tab.active")).to_have_text(label)
            _assert_no_document_overflow(page)

        # A prose-heavy section keeps lines readable rather than spanning the shell.
        _open_section(page, "API Key")
        _assert_no_document_overflow(page)
        if width >= 1200:
            assert page.locator("#section-api-key .subline").evaluate(
                "node => node.getBoundingClientRect().width"
            ) < panel_box["width"]


def test_profile_respects_guest_restrictions_for_security_and_api_key(page: Page) -> None:
    page.set_content(_template_body("profile.html"))
    _install_runtime(
        page,
        """function (url) {
          if (url === "/compute/api/auth/me") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({username: "guest", email: "guest@example.test", role: "guest"});
          }});
          if (url === "/compute/api/access") return Promise.resolve({ok: true, json: function () { return Promise.resolve({policies: []}); }});
          if (url === "/compute/api/gpu-credit") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({period: "2026-09", allow_gpu_use: false, monthly_grant_credits: 0,
              adjustment_credits: 0, usage_credits: 0, remaining_credits: 0, history: []});
          }});
          if (url.indexOf("/compute/api/user-metrics") === 0) return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({window: "30d", days: 30, period: "2026-09-22", tasks_submitted: 0,
              tasks_completed: 0, tasks_failed: 0, success_rate: null, cpu_tasks: 0, gpu_tasks: 0,
              gpu_minutes: 0, total_runtime_seconds: 0, median_runtime_seconds: null,
              distribution: [], activity: []});
          }});
          return Promise.resolve({ok: false, json: function () { return Promise.resolve({}); }});
        }""",
    )
    page.add_script_tag(path=STATIC_JS / "profile.js")

    expect(page.locator("#userInfo")).to_contain_text("guest account")
    tabs = page.locator("#profileTabs")
    expect(tabs.get_by_role("button", name="Security", exact=True)).to_have_count(0)
    expect(tabs.get_by_role("button", name="API Key", exact=True)).to_have_count(0)
    expect(page.locator("#section-security")).to_have_count(0)
    expect(page.locator("#section-api-key")).to_have_count(0)

    # A crafted URL hash cannot reach a removed section either.
    page.evaluate("location.hash = '#api-key'")
    page.evaluate("location.hash = '#security'")
    expect(page.locator("#section-profile")).to_be_visible()
    expect(page.locator("#section-security")).to_have_count(0)
    expect(page.locator("#section-api-key")).to_have_count(0)

    # The remaining sections still work, and guest metrics are honestly empty.
    _open_section(page, "Metrics")
    expect(page.locator("#metricsEmpty")).to_be_visible()
    expect(page.locator("#metricsSubmitted")).to_have_text("0")


def test_admin_applies_reasoned_gpu_credit_adjustment(page: Page) -> None:
    page.set_viewport_size({"width": 430, "height": 932})
    page.set_content(_template_body("user_control.html"))
    _install_runtime(
        page,
        """function (url, options) {
          if (url === "/compute/api/auth/me") return Promise.resolve({ok: true, json: function () { return Promise.resolve({username: "admin"}); }});
          if (url === "/compute/api/auth/admin/users") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({users: [{id: 9, username: "researcher", email: "r@example.test", role: "user",
              registration_status: "approved", user_status: "active", allow_gpu_use: true,
              gpu_credit: {remaining_gpu_seconds: 60000}}]});
          }});
          if (url === "/compute/api/auth/admin/users/9/gpu-credit") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({monthly_grant_credits: 1000, adjustment_credits: 0, usage_credits: 0,
              remaining_credits: 1000, history: [{kind: "monthly_grant", gpu_seconds: 60000, reason: "UTC calendar-month allowance"}]});
          }});
          if (url === "/compute/api/auth/admin/users/9/gpu-credit/adjustments") {
            window.__gpuAdjustment = JSON.parse(options.body);
            return Promise.resolve({ok: true, json: function () { return Promise.resolve({}); }});
          }
          return Promise.resolve({ok: true, json: function () { return Promise.resolve({}); }});
        }""",
    )
    page.add_script_tag(path=STATIC_JS / "user-control.js")

    expect(page.get_by_text("1,000 credits", exact=True)).to_be_visible()
    page.get_by_role("button", name="GPU credits").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Adjustment in credits").fill("200")
    dialog.get_by_label("Reason").fill("Approved collaboration run")
    expect(dialog.get_by_text("1,200", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Apply adjustment").click()
    page.wait_for_function("window.__gpuAdjustment")
    assert page.evaluate("window.__gpuAdjustment.gpu_seconds") == 12000
    assert page.evaluate("window.__gpuAdjustment.reason") == "Approved collaboration run"
    expect(page.get_by_role("dialog")).to_contain_text("GPU credit adjustment recorded.")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_admin_sets_per_user_monthly_gpu_allowance(page: Page) -> None:
    page.set_viewport_size({"width": 430, "height": 932})
    page.set_content(_template_body("user_control.html"))
    _install_runtime(
        page,
        """function (url, options) {
          if (url === "/compute/api/auth/me") return Promise.resolve({ok: true, json: function () { return Promise.resolve({username: "admin"}); }});
          if (url === "/compute/api/auth/admin/users") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({users: [{id: 9, username: "researcher", email: "r@example.test", role: "user",
              registration_status: "approved", user_status: "active", allow_gpu_use: true,
              gpu_credit: {remaining_gpu_seconds: 60000}}]});
          }});
          if (url === "/compute/api/auth/admin/users/9/gpu-credit") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({monthly_grant_credits: 1000, adjustment_credits: 0, usage_credits: 0,
              remaining_credits: 1000, history: []});
          }});
          if (url === "/compute/api/auth/admin/users/9/gpu-credit/allowance") {
            window.__gpuAllowance = JSON.parse(options.body);
            return Promise.resolve({ok: true, json: function () { return Promise.resolve({}); }});
          }
          return Promise.resolve({ok: true, json: function () { return Promise.resolve({}); }});
        }""",
    )
    page.add_script_tag(path=STATIC_JS / "user-control.js")

    page.get_by_role("button", name="GPU credits").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Monthly allowance in credits").fill("1200")
    dialog.get_by_role("button", name="Set allowance").click()
    page.wait_for_function("window.__gpuAllowance")
    assert page.evaluate("window.__gpuAllowance.monthly_gpu_seconds") == 72000
    expect(page.get_by_role("dialog")).to_contain_text("Monthly allowance updated.")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_admin_manages_policy_and_clears_suspension(page: Page) -> None:
    page.set_viewport_size({"width": 430, "height": 932})
    page.set_content(_template_body("user_control.html"))
    _install_runtime(
        page,
        """function (url, options) {
          window.__suspensionCleared = window.__suspensionCleared || false;
          if (url === "/compute/api/auth/me") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({username: "admin", role: "admin"});
          }});
          if (url.indexOf("/clear-suspension") !== -1) {
            window.__suspensionCleared = true;
            return Promise.resolve({ok: true, json: function () { return Promise.resolve({}); }});
          }
          if (url === "/compute/api/auth/admin/access/policies") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({policies: [{policy_id: "alphafold3_noncommercial",
              label: "AlphaFold 3 non-commercial access for structural biology research",
              description: "Restricted to non-commercial research", requires: ["alphafold3_noncommercial"],
              notice: {summary: "Institutional eligibility must be verified."},
              license: {name: "AlphaFold 3 Terms", url: "https://example.test/alphafold-terms"},
              authorized_users: 2, pending_requests: window.__decision ? 0 : 1, suspended_users: window.__suspensionCleared ? 0 : 1}]});
          }});
          if (url === "/compute/api/auth/admin/access/policies/alphafold3_noncommercial") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({policy: {policy_id: "alphafold3_noncommercial", label: "AlphaFold 3", description: "Restricted to non-commercial research"},
              authorized_users: [{user_id: 2, username: "allowed", email: "allowed@example.test", basis: "individually_verified", grant_id: 11},
                {user_id: 5, full_name: "Admin Researcher", username: "admin", email: "admin@example.test", basis: "lab_member", grant_id: 12}],
              pending_requests: window.__decision ? [] : [{request_id: 7, user_id: 3, username: "waiting", full_name: "Waiting Researcher", email: "waiting@university.test", affiliation: "Example University", position: "phd_student", pi_name: "Professor Example", entitlement: "alphafold3_noncommercial", reason: "Non-commercial structure prediction"}],
              suspended_users: window.__suspensionCleared ? [] : [{user_id: 4, username: "blocked", retry_after_seconds: 30}]});
          }});
          if (url.indexOf("/compute/api/auth/admin/access/events") === 0) return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({events: [{full_name: "Blocked Researcher", username: "blocked",
              event_type: "runner_access_suspended", policy_id: "alphafold3_noncommercial",
              outcome: "suspended", occurred_at: 1788393600}]});
          }});
          if (url.indexOf("/decision") !== -1) {
            window.__decision = JSON.parse(options.body);
            return Promise.resolve({ok: true, json: function () { return Promise.resolve({}); }});
          }
          if (url === "/compute/api/auth/admin/access/requests") return Promise.resolve({ok: true, json: function () {
            if (window.__decision) return Promise.resolve({requests: []});
            return Promise.resolve({requests: [{id: 7, user_id: 3, username: "waiting", full_name: "Waiting Researcher",
              email: "waiting@university.test", affiliation: "Example University", position: "phd_student",
              pi_name: "Professor Example", registration_status: "approved", entitlement: "alphafold3_noncommercial",
              reason: "Non-commercial structure prediction"}]});
          }});
          if (url.indexOf("/compute/api/auth/admin/users") === 0) return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({users: [], grants: [{entitlement: "alphafold3_noncommercial", basis: "individually_verified", revoked_at: 1, expires_at: null}]});
          }});
          return Promise.resolve({ok: false, json: function () { return Promise.resolve({}); }});
        }""",
    )
    page.add_script_tag(path=STATIC_JS / "user-control.js")

    page.get_by_role("button", name="Runner Access").click()
    policy_label = "AlphaFold 3 non-commercial access for structural biology research"
    expect(page.locator("#accessPolicyOverview").get_by_text(policy_label, exact=True)).to_be_visible()
    expect(page.locator("#accessPolicyOverview .policy-summary")).to_have_count(1)
    counts = page.locator("#accessPolicyOverview .policy-count")
    expect(counts.nth(0)).to_have_text("2Authorized")
    expect(counts.nth(1)).to_have_text("1Pending")
    expect(counts.nth(2)).to_have_text("1Suspended")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    page.set_viewport_size({"width": 1000, "height": 800})
    activity_row = page.locator("#accessActivity .activity-row")
    expect(activity_row).to_have_count(1)
    expect(activity_row.locator("time")).not_to_be_empty()
    expect(activity_row.get_by_text("Blocked Researcher", exact=True)).to_be_visible()
    expect(activity_row.get_by_text(policy_label, exact=True)).to_be_visible()
    expect(activity_row.get_by_text("suspended", exact=True)).to_be_visible()
    assert activity_row.evaluate("node => node.getBoundingClientRect().height < 70")
    manage = page.get_by_role("button", name=re.compile("^Manage AlphaFold 3"))
    assert manage.evaluate(
        "node => node.getBoundingClientRect().width < node.parentElement.getBoundingClientRect().width / 2"
    )
    page.set_viewport_size({"width": 430, "height": 932})
    populated_height = page.locator(".access-priority").evaluate("node => node.getBoundingClientRect().height")

    page.locator("#accessRequestQueue").get_by_role("button", name="Approve").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_text("Waiting Researcher", exact=True)).to_be_visible()
    expect(dialog.get_by_text(re.compile("Example University"))).to_be_visible()
    expect(dialog.get_by_text("Restricted to non-commercial research", exact=True)).to_be_visible()
    expect(dialog.get_by_role("link", name="AlphaFold 3 Terms")).to_have_attribute(
        "href", "https://example.test/alphafold-terms"
    )
    expect(dialog.get_by_text(re.compile("Revoked.*individually verified"))).to_be_visible()
    assert dialog.evaluate("node => node.getBoundingClientRect().width <= innerWidth && node.getBoundingClientRect().height <= innerHeight")
    dialog.get_by_role("button", name="Confirm eligibility").click()
    page.wait_for_function("window.__decision && window.__decision.decision === 'approved'")
    expect(page.get_by_text("No pending access requests.", exact=True)).to_be_visible()
    assert page.locator(".access-priority").evaluate("node => node.getBoundingClientRect().height") < populated_height
    terms_link = page.get_by_role("link", name="Access and licensing terms")
    assert terms_link.evaluate("node => getComputedStyle(node).color !== 'rgb(128, 0, 128)'")

    policy_list_height = page.locator("#accessPolicyOverview").evaluate("node => node.getBoundingClientRect().height")
    activity_top = page.locator("#accessActivityHeading").evaluate("node => node.getBoundingClientRect().top")
    manage.click()
    policy_dialog = page.get_by_role("dialog")
    expect(policy_dialog.get_by_role("heading", name=policy_label)).to_be_visible()
    expect(policy_dialog.get_by_text("alphafold3_noncommercial", exact=True)).to_be_visible()
    expect(policy_dialog.get_by_text("Restricted to non-commercial research", exact=True)).to_be_visible()
    expect(policy_dialog.locator(".policy-user-row")).to_have_count(3)
    expect(policy_dialog.get_by_text("No pending requests.", exact=True)).to_be_visible()
    expect(policy_dialog.get_by_text("allowed", exact=True)).to_be_visible()
    expect(policy_dialog.get_by_text("allowed@example.test", exact=True)).to_be_visible()
    assert page.locator("#accessPolicyOverview").evaluate("node => node.getBoundingClientRect().height") == policy_list_height
    assert page.locator("#accessActivityHeading").evaluate("node => node.getBoundingClientRect().top") == activity_top
    assert page.locator("#accessPolicyDetail").count() == 0
    page.get_by_role("button", name="Close dialog").click()
    expect(manage).to_be_focused()

    manage.click()
    policy_dialog = page.get_by_role("dialog")
    policy_dialog.get_by_role("button", name="Clear suspension").click()
    expect(policy_dialog.get_by_text("blocked", exact=True)).to_have_count(0)
    expect(policy_dialog.get_by_text("No suspended users.", exact=True)).to_be_visible()
    expect(page.locator("#accessPolicyOverview .policy-count").nth(2)).to_have_text("0Suspended")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_user_action_uses_stable_id_when_display_names_are_missing(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.set_content(_template_body("user_control.html"))
    _install_runtime(
        page,
        """function (url) {
          if (url === "/compute/api/auth/me") return Promise.resolve({ok: true, json: function () { return Promise.resolve({username: "admin"}); }});
          if (url === "/compute/api/auth/admin/users") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({users: [
              {id: 9, registration_status: "verified", user_status: "pending", role: "user"},
              {id: 10, full_name: "A Researcher With An Intentionally Long Scientific Display Name", email: "long.researcher@university.example", affiliation: "Institute for Extremely Long Molecular Biology and Protein Engineering Studies", position: "postdoc", pi_name: "Professor Long Name", registration_ip: "192.0.2.9", registration_country: "Example Country", registration_status: "approved", user_status: "active", role: "user"}
            ]});
          }});
          return Promise.resolve({ok: true, json: function () { return Promise.resolve({}); }});
        }""",
    )
    page.add_script_tag(path=STATIC_JS / "user-control.js")
    page.locator("#userTableBody").get_by_role("button", name="Approve").click()
    expect(page.get_by_role("dialog")).to_contain_text("Approve 9?")
    expect(page.get_by_role("dialog")).not_to_contain_text("Undefined user")
    page.get_by_role("dialog").get_by_role("button", name="Cancel").click()
    long_row = page.locator("#userTableBody tr", has_text="A Researcher With An Intentionally Long Scientific Display Name")
    long_row.get_by_role("button", name="Details").click()
    expect(page.get_by_role("dialog")).to_contain_text("Institute for Extremely Long Molecular Biology")
    assert page.get_by_role("dialog").evaluate("node => node.getBoundingClientRect().width <= innerWidth && node.getBoundingClientRect().height <= innerHeight")
    page.get_by_role("button", name="Close dialog").click()
    long_row.get_by_role("button", name="Modify").click()
    expect(page.get_by_role("dialog").get_by_label("Affiliation")).to_have_value("Institute for Extremely Long Molecular Biology and Protein Engineering Studies")
    page.get_by_role("dialog").get_by_role("button", name="Cancel").click()
    page.locator(".user-select").first.check()
    expect(page.locator("#batchCount")).to_have_text("1 selected")
    expect(page.locator("#batchBar")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def _credit_users_payload() -> list[dict]:
    return [
        {
            "id": 9,
            "username": "researcher",
            "email": "r@example.test",
            "role": "user",
            "registration_status": "approved",
            "user_status": "active",
            "allow_gpu_use": True,
            "gpu_credit": {"remaining_gpu_seconds": 51192},
        },
        {
            "id": 10,
            "username": "second",
            "email": "s@example.test",
            "role": "user",
            "registration_status": "approved",
            "user_status": "active",
            "allow_gpu_use": False,
            "gpu_credit": {"remaining_gpu_seconds": 60000},
        },
    ]


def test_admin_resets_one_user_gpu_credits_with_reason(page: Page) -> None:
    page.set_viewport_size({"width": 430, "height": 932})
    page.set_content(_template_body("user_control.html"))
    _install_runtime(
        page,
        """function (url, options) {
          if (url === "/compute/api/auth/me") return Promise.resolve({ok: true, json: function () { return Promise.resolve({username: "admin"}); }});
          if (url === "/compute/api/auth/admin/users") {
            window.__userRefreshes = (window.__userRefreshes || 0) + 1;
            return Promise.resolve({ok: true, json: function () { return Promise.resolve({users: %s}); }});
          }
          if (url === "/compute/api/auth/admin/users/9/gpu-credit") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({monthly_grant_credits: 1000, adjustment_credits: 0, usage_credits: 146.8,
              remaining_credits: 853.2, history: [{kind: "monthly_grant", gpu_seconds: 60000, reason: "UTC calendar-month allowance"}]});
          }});
          if (url === "/compute/api/auth/admin/users/9/gpu-credit/reset") {
            window.__resetPayload = JSON.parse(options.body);
            return Promise.resolve({ok: true, json: function () { return Promise.resolve({user_id: 9, period: "2026-09",
              monthly_allowance_gpu_seconds: 60000, previous_remaining_gpu_seconds: 51192, reset_delta_gpu_seconds: 8808,
              remaining_gpu_seconds: 60000, changed: true, entry_id: 12}); }});
          }
          return Promise.resolve({ok: true, json: function () { return Promise.resolve({}); }});
        }""" % json.dumps(_credit_users_payload()),
    )
    page.add_script_tag(path=STATIC_JS / "user-control.js")

    page.get_by_role("button", name="GPU credits").first.click()
    reset_button = page.get_by_role("button", name="Reset to 1,000 credits")
    expect(reset_button).to_be_visible()
    reset_button.click()

    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Reset GPU credits for researcher?")
    expect(dialog).to_contain_text("853.2 credits")
    expect(dialog).to_contain_text("1,000 credits")
    expect(dialog).to_contain_text("+146.8 credits")
    expect(dialog).to_contain_text("Usage history will not be deleted.")

    dialog.get_by_role("button", name="Reset credits").click()
    expect(page.get_by_role("dialog")).to_contain_text("Enter a reason for the reset.")
    assert page.evaluate("window.__resetPayload") is None
    page.get_by_role("dialog").get_by_role("button", name="Close").click()

    page.get_by_role("button", name="GPU credits").first.click()
    page.get_by_role("button", name="Reset to 1,000 credits").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Reason").fill("Approved new allocation cycle")
    dialog.get_by_role("button", name="Reset credits").click()
    page.wait_for_function("window.__resetPayload")
    assert page.evaluate("window.__resetPayload.reason") == "Approved new allocation cycle"
    assert page.evaluate("window.__resetPayload.idempotency_key")
    expect(page.get_by_role("dialog")).to_contain_text("GPU credits reset to 1,000 credits.")
    expect(page.get_by_role("dialog")).to_contain_text("Adjustment: +146.8 credits.")
    assert page.evaluate("window.__userRefreshes") >= 2
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_admin_global_gpu_credit_reset_requires_typed_confirmation(page: Page) -> None:
    page.set_viewport_size({"width": 430, "height": 932})
    page.set_content(_template_body("user_control.html"))
    _install_runtime(
        page,
        """function (url, options) {
          if (url === "/compute/api/auth/me") return Promise.resolve({ok: true, json: function () { return Promise.resolve({username: "admin"}); }});
          if (url === "/compute/api/auth/admin/users") return Promise.resolve({ok: true, json: function () {
            window.__userRefreshes = (window.__userRefreshes || 0) + 1;
            return Promise.resolve({users: %s});
          }});
          if (url === "/compute/api/auth/admin/gpu-credit/reset") {
            window.__resetAllPayload = JSON.parse(options.body);
            return Promise.resolve({ok: true, json: function () { return Promise.resolve({period: "2026-09",
              batch_id: "reset-batch:global-ui", users_considered: 2, users_changed: 1, users_unchanged: 1,
              total_delta_gpu_seconds: 8808}); }});
          }
          return Promise.resolve({ok: true, json: function () { return Promise.resolve({}); }});
        }""" % json.dumps(_credit_users_payload()),
    )
    page.add_script_tag(path=STATIC_JS / "user-control.js")

    danger = page.locator(".gpu-reset-zone")
    expect(danger.get_by_role("button", name="Reset all users")).to_be_visible()
    danger.get_by_role("button", name="Reset all users").click()

    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Reset GPU credits for all 2 current users?")
    expect(dialog).to_contain_text("Usage history will NOT be deleted.")
    dialog.get_by_label("Reason").fill("Start refreshed allocation cycle")
    dialog.get_by_role("button", name="Reset all users").click()
    expect(page.get_by_role("dialog")).to_contain_text("Type RESET ALL to confirm the global reset.")
    assert page.evaluate("window.__resetAllPayload") is None
    page.get_by_role("dialog").get_by_role("button", name="Close").click()

    danger.get_by_role("button", name="Reset all users").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Reason").fill("Start refreshed allocation cycle")
    dialog.get_by_label("Type RESET ALL to confirm").fill("RESET ALL")
    dialog.get_by_role("button", name="Reset all users").click()
    page.wait_for_function("window.__resetAllPayload")
    assert page.evaluate("window.__resetAllPayload.reason") == "Start refreshed allocation cycle"
    expect(page.get_by_role("dialog")).to_contain_text(
        "Reset completed. 1 users changed; 1 already at their configured allowance."
    )
    assert page.evaluate("window.__userRefreshes") >= 2
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
