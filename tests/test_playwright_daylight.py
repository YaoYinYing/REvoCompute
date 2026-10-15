# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Daylight presentation preserves the production Dashboard's interactive contract.

The fixture API is synthetic; all assertions run the built production components.
Scientific data and the backend execution lifecycle are outside this UI slice.
"""
from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import build_task_summary, controlled_runner, controlled_scenario, mount_scenario

pytestmark = pytest.mark.browser
ORIGIN = 'https://revocompute.example'


def open_tasks(page: Page, *, role: str = 'session') -> None:
    runner = controlled_runner()
    tasks = [build_task_summary(f'{index + 1:032x}', runner, status=status, result_available=status == 'finished')
             for index, status in enumerate(('pending', 'running', 'failed', 'finished'))]
    mount_scenario(page, controlled_scenario().with_role(role).with_task_summaries(tasks))
    page.goto(f'{ORIGIN}/compute/dashboard')
    expect(page.locator('.task-card')).to_have_count(4)
    page.evaluate('document.fonts.ready')


@pytest.mark.parametrize('width', [1440, 1024, 390])
def test_dashboard_views_filters_and_important_type_remain_usable(page: Page, width: int) -> None:
    page.set_viewport_size({'width': width, 'height': 1080})
    open_tasks(page)
    expect(page.get_by_role('heading', name='Tasks', exact=True)).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.evaluate("document.fonts.check('400 14px \"DM Sans\"') && document.fonts.check('500 40px \"Instrument Sans\"')")
    for layout in ('compact', 'table', 'detailed'):
        page.locator(f'[data-layout="{layout}"]').first.click()
        expect(page.locator('.task-list')).to_have_attribute('data-layout', layout)
        expect(page.locator('.task-actions [data-action="cancel"]')).to_have_count(2)
        expect(page.locator('.task-actions [data-action="delete"]')).to_have_count(4)
        expect(page.get_by_role('link', name='Results', exact=True)).to_have_count(1)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if width < 896:
        page.locator('.dashboard-filters > summary').click()
    page.locator('[data-filter="status"]').select_option('running')
    expect(page.locator('.task-card')).to_have_count(1)
    expect(page.locator('.status')).to_have_text('running')
    page.locator('[data-filter="status"]').select_option('')
    page.locator('[data-filter="search"]').fill('no matching task')
    expect(page.locator('.empty-state')).to_be_visible()
    assert page.locator('.dashboard-page .primary-button').evaluate('(node) => parseFloat(getComputedStyle(node).fontSize)') >= 14


@pytest.mark.parametrize('role', ['session', 'admin'])
def test_secondary_navigation_keeps_authorized_destinations_and_escape(page: Page, role: str) -> None:
    page.set_viewport_size({'width': 390, 'height': 844})
    open_tasks(page, role=role)
    toggle = page.get_by_role('button', name='Expand navigation', exact=True)
    toggle.click()
    expect(page.get_by_role('link', name='Security', exact=True)).to_be_visible()
    admin = page.locator('.app-nav-group[data-nav-group="admin"]')
    if role == 'admin':
        expect(admin).to_be_visible()
    else:
        expect(admin).to_be_hidden()
    page.keyboard.press('Escape')
    expect(toggle).to_be_focused()
    expect(toggle).to_have_attribute('aria-expanded', 'false')
