# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Production frontend navigation and captures; API account data is synthetic.

Method descriptions use existing Runner contract fixtures. This verifies the
rendered application and role-gated destinations, not a live deployment.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

import browser_frontend_assets
from frontend_fixtures import controlled_scenario, gremlin_lh_runner, mount_scenario
from test_playwright_replay_fpocket import fpocket_runner
from test_playwright_application import _install_app, _current_user, _fleet_payload

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[3]
ORIGIN = 'https://revocompute.example'


def capture(page: Page, directory: Path, name: str) -> None:
    page.evaluate('document.fonts.ready')
    for width in (1440, 390):
        page.set_viewport_size({'width': width, 'height': 1080})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, page.evaluate("[...document.querySelectorAll('body *')].filter(node => node.getBoundingClientRect().right > innerWidth + 1).slice(0, 12).map(node => [node.tagName, node.className, Math.round(node.getBoundingClientRect().right)])"))
        page.screenshot(path=str(directory / f'{name}-{width}.png'), full_page=name != 'api-reference')
    page.set_viewport_size({'width': 1440, 'height': 1080})


def test_whole_site_navigation_with_the_production_frontend(page: Page, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(browser_frontend_assets, '_RESULT_DIST', ROOT / 'frontend/dist')
    mount_scenario(page, controlled_scenario().with_role('admin').with_catalog([gremlin_lh_runner(), fpocket_runner()]))
    page.goto(f'{ORIGIN}/runners')
    page.evaluate('window.__daylightDocument = 1')
    expect(page.locator('.runner-card')).to_have_count(3)
    capture(page, tmp_path, 'catalog')
    page.locator('.runner-card', has=page.get_by_role('heading', name='GREMLIN_LH Potts model', exact=True)).get_by_role('link', name='View method').click()
    expect(page.locator('.runner-detail-heading h1')).to_have_text('GREMLIN_LH Potts model')
    expect(page.locator('.runner-facts')).to_contain_text('CPU')
    expect(page.locator('.parameter-list article').filter(has=page.get_by_text('lambda_lh', exact=True))).to_contain_text('> 0 · ≤ 10')
    capture(page, tmp_path, 'method')
    page.locator('.runner-detail-heading').get_by_role('link', name='Create task', exact=True).click()
    expect(page.locator('.ct-workbench')).to_be_visible()
    # Reuse the existing bounded operational fixtures; never invent an action.
    _install_app(page)
    page.route(f'{ORIGIN}/compute/api/auth/me', lambda route: route.fulfill(json=_current_user('admin')))
    page.route(f'{ORIGIN}/compute/api/auth/admin/runners', lambda route: route.fulfill(json=_fleet_payload()))
    page.locator('.app-rail-toggle').click()
    page.locator('[data-nav-group="account"] a[href="/compute/profile"]').click()
    expect(page.locator('.account-page h1')).to_have_text('Account')
    capture(page, tmp_path, 'profile')
    for path, name in [('/compute/account/security', 'security'), ('/compute/account/api-key', 'api-key'), ('/compute/account/runner-access', 'runner-access'), ('/compute/account/gpu-credits', 'gpu-credits'), ('/compute/account/metrics', 'metrics'), ('/compute/quota', 'quota')]:
        page.locator(f'.account-navigation a[href="{path}"]').click()
        expect(page.locator('.account-navigation a[aria-current="page"]')).to_have_attribute('href', path)
        expect(page.locator('.account-page h1')).to_be_visible()
        capture(page, tmp_path, name)
        assert page.evaluate('window.__daylightDocument') == 1
    page.locator('.app-rail-toggle').click()
    page.locator('[data-nav-group="admin"] a[href="/compute/runner_fleet"]').click()
    expect(page.locator('.admin-page h1')).to_be_visible()
    capture(page, tmp_path, 'fleet')
    for path, name in [('/compute/user_control', 'users'), ('/compute/configuration', 'configuration'), ('/compute/logs', 'logs')]:
        page.locator(f'.operations-navigation a[href="{path}"]').click()
        expect(page.locator('.admin-page h1')).to_be_visible()
        capture(page, tmp_path, name)
        assert page.evaluate('window.__daylightDocument') == 1
    page.go_back()
    expect(page.locator('.operations-navigation a[aria-current="page"]')).to_have_attribute('href', '/compute/configuration')
    assert page.evaluate('window.__daylightDocument') == 1
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    capture(page, tmp_path, 'configuration-dark')
    assert page.evaluate('window.__cspViolations') == []


def test_public_and_authentication_production_surfaces(page: Page, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(browser_frontend_assets, '_RESULT_DIST', ROOT / 'frontend/dist')
    mount_scenario(page, controlled_scenario().with_role('anonymous'))
    page.route(f'{ORIGIN}/openapi.json', lambda route: route.fulfill(content_type='application/json', path=ROOT / 'revocompute/static/openapi.json'))
    page.route(f'{ORIGIN}/compute/api/auth/registration', lambda route: route.fulfill(json={'enabled': True, 'email_available': True}))
    page.route(f'{ORIGIN}/compute/api/auth/captcha', lambda route: route.fulfill(json={'question': 'What is 4 + 5?', 'token': 'fixture-captcha'}))
    for path, name in [('/', 'home'), ('/compute/login', 'login'), ('/compute/register', 'register'), ('/compute/reset_password', 'password-reset'), ('/compute/terms', 'terms')]:
        page.goto(f'{ORIGIN}{path}')
        expect(page.get_by_role('heading', level=1)).to_be_visible()
        capture(page, tmp_path, name)
        expect(page.locator('[data-nav-group="admin"]')).to_be_hidden()
    page.goto(f'{ORIGIN}/api-docs')
    expect(page.locator('.swagger-ui .opblock').first).to_be_visible()
    capture(page, tmp_path, 'api-reference')
    page.goto(f'{ORIGIN}/compute/user_control')
    expect(page.locator('.auth-panel')).to_be_visible()
    assert page.evaluate('window.__cspViolations') == []
