# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Shared navigation behavior, using the production bundle and authorized API fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

import browser_frontend_assets
from test_playwright_application import ORIGIN, TASK_ID, _current_user, _install_app

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def production_bundle(monkeypatch):
    monkeypatch.setattr(browser_frontend_assets, '_RESULT_DIST', ROOT / 'frontend/dist')


@pytest.mark.parametrize('role', ['user', 'admin'])
def test_desktop_navigation_context_preference_and_history(page: Page, role: str, tmp_path: Path) -> None:
    _install_app(page)
    page.route(f'{ORIGIN}/compute/api/auth/me', lambda route: route.fulfill(json=_current_user(role)))
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.goto(f'{ORIGIN}/compute/results/{TASK_ID}')
    nav = page.locator('.app-nav')
    expect(page.locator('.app-shell')).to_have_attribute('data-rail', 'expanded')
    expect(nav.get_by_role('link', name='Dashboard', exact=True)).to_have_attribute('aria-current', 'page')
    expect(page.locator('.app-location')).to_have_text('Dashboard / Results')
    for name in ['Account', 'Security', 'API key', 'Runner access', 'GPU credits', 'Metrics', 'Quota']:
        expect(nav.get_by_role('link', name=name, exact=True)).to_be_visible()
    assert nav.get_by_role('link', name='Server logs', exact=True).is_visible() == (role == 'admin')
    assert page.locator('.app-nav-open').is_visible() is False
    before = page.locator('.app-outlet').bounding_box()['width']
    page.get_by_role('button', name='Collapse navigation', exact=True).click()
    expect(page.locator('.app-shell')).to_have_attribute('data-rail', 'collapsed')
    assert page.locator('.app-outlet').bounding_box()['width'] > before + 150
    for link in nav.locator('a:visible').all():
        assert link.get_attribute('title')
        assert link.locator('svg').count() == 1
    nav.get_by_role('link', name='Security', exact=True).click()
    expect(page.locator('.account-page h1')).to_have_text('Security')
    expect(page.locator('.app-shell')).to_have_attribute('data-rail', 'collapsed')
    page.reload()
    expect(page.locator('.app-shell')).to_have_attribute('data-rail', 'collapsed')
    page.get_by_role('button', name='Expand navigation', exact=True).click()
    page.locator('.account-page h1').click()
    expect(page.locator('.app-shell')).to_have_attribute('data-rail', 'expanded')
    nav.get_by_role('link', name='Runners', exact=True).click()
    page.locator('.runner-card').get_by_role('link', name='View method').click()
    expect(page.locator('.app-location')).to_have_text('Runners / Method')
    expect(nav.get_by_role('link', name='Runners', exact=True)).to_have_attribute('aria-current', 'page')
    page.go_back()
    expect(page.locator('.runner-card')).to_be_visible()
    expect(page.locator('.app-shell')).to_have_attribute('data-rail', 'expanded')
    page.screenshot(path=str(tmp_path / f'spine-{role}-desktop.png'))
    nav.get_by_role('link', name='Account', exact=True).click()
    expect(page.locator('.account-navigation')).to_have_count(0)
    expect(page.locator('.app-nav a[aria-current]')).to_have_count(1)
    page.goto(f'{ORIGIN}/compute/account/account')
    expect(page.locator('.app-nav a[aria-current]')).to_have_attribute('href', '/compute/profile')
    page.goto(f'{ORIGIN}/')
    expect(page.locator('.public-header')).to_be_visible()
    expect(page.locator('.app-sidebar')).to_have_count(0)
    page.goto(f'{ORIGIN}/compute/dashboard')
    expect(page.locator('.app-shell')).to_have_attribute('data-rail', 'expanded')


@pytest.mark.parametrize('width', [320, 390, 768, 1024])
def test_drawer_keyboard_close_route_and_desktop_preference(page: Page, width: int, tmp_path: Path) -> None:
    _install_app(page)
    page.add_init_script("localStorage.setItem('revocompute-rail', 'collapsed')")
    page.route(f'{ORIGIN}/compute/api/auth/me', lambda route: route.fulfill(json=_current_user('admin')))
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(f'{ORIGIN}/compute/dashboard')
    opener = page.get_by_role('button', name='Open navigation', exact=True)
    drawer = page.locator('.app-nav-drawer')
    expect(opener).to_be_visible()
    expect(page.locator('.app-sidebar')).not_to_be_visible()
    assert page.locator('.app-outlet').bounding_box()['x'] == 0
    opener.click()
    expect(drawer).to_be_visible()
    expect(drawer.get_by_role('link', name='Dashboard', exact=True)).to_be_focused()
    last = drawer.get_by_role('link', name='Server logs', exact=True)
    last.focus()
    page.keyboard.press('Tab')
    assert page.evaluate("document.querySelector('.app-nav-drawer').contains(document.activeElement)")
    page.keyboard.press('Shift+Tab')
    expect(last).to_be_focused()
    page.screenshot(path=str(tmp_path / f'drawer-{width}.png'))
    page.keyboard.press('Escape')
    expect(drawer).not_to_be_visible()
    expect(opener).to_be_focused()
    expect(opener).to_have_attribute('aria-expanded', 'false')
    opener.click()
    page.mouse.click(width - 2, 500)
    expect(drawer).not_to_be_visible()
    opener.click()
    drawer.get_by_role('link', name='Security', exact=True).click()
    expect(page.locator('.account-page h1')).to_have_text('Security')
    expect(drawer).not_to_be_visible()
    expect(page.locator('.account-page h1')).to_be_focused()
    assert page.evaluate("localStorage.getItem('revocompute-rail')") == 'collapsed'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    expect(page.locator('.app-sidebar')).to_be_visible()
    expect(page.locator('.app-shell')).to_have_attribute('data-rail', 'collapsed')
    page.get_by_role('button', name='Expand navigation', exact=True).click()
    page.set_viewport_size({'width': width, 'height': 844})
    opener.click()
    expect(drawer.get_by_role('link', name='Security', exact=True)).to_be_visible()
    page.set_viewport_size({'width': 1440, 'height': 1000})
    expect(drawer).not_to_be_visible()
    expect(page.locator('.app-shell')).to_have_attribute('data-rail', 'expanded')
    expect(page.get_by_role('button', name='Collapse navigation', exact=True)).to_be_focused()
