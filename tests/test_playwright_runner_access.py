# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "revocompute" / "templates"
STATIC_JS = ROOT / "revocompute" / "static" / "js"


def _template_body(name: str) -> str:
    html = (TEMPLATES / name).read_text(encoding="utf-8")
    html = re.sub(r'<script[^>]+src="[^"]+"[^>]*></script>', "", html)
    return html.replace('{{ {"is_admin": is_admin_user} | tojson }}', '{"is_admin": true}')


def _install_runtime(page: Page, auth_fetch: str) -> None:
    page.evaluate(
        """
        window.REvoDesignTheme = {initToggle: function () {}};
        window.REvoDesignAuth = {
          authFetch: %s,
          logout: function () {}
        };
        """ % auth_fetch
    )


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
          return Promise.resolve({ok: false, json: function () { return Promise.resolve({}); }});
        }""",
    )
    page.add_script_tag(path=STATIC_JS / "profile.js")

    expect(page.get_by_role("heading", name="AlphaFold 3 non-commercial use")).to_be_visible()
    expect(page.get_by_text("Restricted", exact=True)).to_be_visible()
    license_link = page.get_by_role("link", name=re.compile("AlphaFold 3 Terms of Use"))
    expect(license_link).to_have_attribute("href", "https://example.test/terms")
    expect(license_link).to_have_attribute("rel", "noopener noreferrer")
    reason = page.get_by_label("Research use and affiliation")
    expect(reason).to_have_attribute("maxlength", "1000")
    reason.fill("Non-commercial structural biology research at Example University")
    page.get_by_role("button", name="Request access").evaluate("node => node.click()")
    expect(page.get_by_text("Access requested", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Request access")).to_have_count(0)
    assert page.evaluate("window.__requestPayload.reason") == (
        "Non-commercial structural biology research at Example University"
    )


def test_admin_manages_policy_and_clears_suspension(page: Page) -> None:
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
            return Promise.resolve({policies: [{policy_id: "alphafold3_noncommercial", label: "AlphaFold 3",
              authorized_users: 2, pending_requests: 1, suspended_users: window.__suspensionCleared ? 0 : 1}]});
          }});
          if (url === "/compute/api/auth/admin/access/policies/alphafold3_noncommercial") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({policy: {label: "AlphaFold 3"},
              authorized_users: [{user_id: 2, username: "allowed"}], pending_requests: [{user_id: 3, username: "waiting"}],
              suspended_users: window.__suspensionCleared ? [] : [{user_id: 4, username: "blocked", retry_after_seconds: 30}]});
          }});
          if (url.indexOf("/compute/api/auth/admin/access/events") === 0) return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({events: [{username: "blocked", event_type: "runner_access_suspended", policy_id: "alphafold3_noncommercial", created_at: "2026-09-03T00:00:00Z"}]});
          }});
          if (url === "/compute/api/auth/admin/access/requests") return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({requests: []});
          }});
          if (url.indexOf("/compute/api/auth/admin/users") === 0) return Promise.resolve({ok: true, json: function () {
            return Promise.resolve({users: []});
          }});
          return Promise.resolve({ok: false, json: function () { return Promise.resolve({}); }});
        }""",
    )
    page.add_script_tag(path=STATIC_JS / "user-control.js")

    page.get_by_role("button", name="Runner Access").evaluate("node => node.click()")
    expect(page.get_by_text("AlphaFold 3", exact=True).first).to_be_visible()
    counts = page.locator("#accessPolicyOverview .policy-count")
    expect(counts.nth(0)).to_have_text("2Authorized")
    expect(counts.nth(1)).to_have_text("1Pending")
    expect(counts.nth(2)).to_have_text("1Suspended")
    expect(page.locator("#accessActivity").get_by_text("blocked", exact=True)).to_be_visible()

    page.get_by_role("button", name="Manage", exact=True).evaluate("node => node.click()")
    detail = page.locator("#accessPolicyDetail")
    expect(detail.get_by_text("allowed", exact=True)).to_be_visible()
    expect(detail.get_by_text("waiting", exact=True)).to_be_visible()
    expect(detail.get_by_text("blocked", exact=True)).to_be_visible()
    page.get_by_role("button", name="Clear suspension").evaluate("node => node.click()")
    expect(detail.get_by_text("blocked", exact=True)).to_have_count(0)
