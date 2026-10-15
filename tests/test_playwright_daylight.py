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
    assert page.evaluate("[...document.fonts].some(face => face.family === 'DM Sans' && face.status === 'loaded')")


@pytest.mark.parametrize('width', [1440, 1024, 390])
def test_dashboard_views_filters_and_important_type_remain_usable(page: Page, width: int) -> None:
    page.set_viewport_size({'width': width, 'height': 1080})
    open_tasks(page)
    expect(page.get_by_role('heading', name='Tasks', exact=True)).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    nav = page.locator('.app-nav').bounding_box()
    toggle = page.locator('.app-rail-toggle').bounding_box()
    assert nav and toggle and toggle['y'] + toggle['height'] <= nav['y'] + nav['height'] + 1
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
    toggle = page.get_by_role('button', name='Account & more: Expand navigation', exact=True)
    toggle.focus()
    page.keyboard.press('Enter')
    expect(page.get_by_role('link', name='Security', exact=True)).to_be_visible()
    page.keyboard.press('Tab')
    expect(page.locator('[data-nav-group="account"] a').first).to_be_focused()
    admin = page.locator('.app-nav-group[data-nav-group="admin"]')
    if role == 'admin':
        expect(admin).to_be_visible()
    else:
        expect(admin).to_be_hidden()
    page.keyboard.press('Escape')
    expect(toggle).to_be_focused()
    expect(toggle).to_have_attribute('aria-expanded', 'false')


def test_production_dashboard_with_real_flask_session_and_owned_tasks(page: Page, tmp_path, monkeypatch) -> None:
    """Real routes/auth/Task projection plus the production bundle; no scheduler claim."""
    from pathlib import Path
    import shutil
    import threading
    from conftest import _load_pssm_module, _test_client_auth, _upsert_task_for_user
    from werkzeug.serving import make_server

    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={'RUNNER_UID': '1234', 'RUNNER_GID': '5678'})
    _test_client_auth(module)
    bundle = Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
    static_root = tmp_path / 'browser-static'
    shutil.copytree(bundle, static_root / 'app')
    monkeypatch.setattr(module.app, 'static_folder', str(static_root))
    for index, status in enumerate(('pending', 'running', 'failed', 'cancelled')):
        result = tmp_path / f'result-{index}'
        result.mkdir()
        _upsert_task_for_user(module, f'{index + 1:032x}', filename=f'owned-{status}.fasta',
                              file_path=tmp_path / f'input-{index}.fasta', result_dir=result,
                              username='tester', status=status)
    server = make_server('127.0.0.1', 0, module.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        login = page.context.request.post(f'{origin}/compute/api/auth/login', data={'username': 'tester', 'password': 'password'})
        assert login.status == 200
        response = page.context.request.get(f'{origin}/compute/api/tasks')
        assert response.status == 200 and len(response.json()['tasks']) == 4
        page.goto(f'{origin}/compute/dashboard')
        expect(page.locator('.task-card')).to_have_count(4)
        page.evaluate('document.fonts.ready')
        for width in (1440, 1024, 390):
            page.set_viewport_size({'width': width, 'height': 1080})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path / f'daylight-real-api-{width}.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1080})
        page.screenshot(path=str(tmp_path / 'daylight-real-api.png'), full_page=True)
        page.evaluate("localStorage.setItem('revocompute-theme', 'dark'); localStorage.setItem('revocompute-locale', 'zh-CN')")
        page.reload()
        expect(page.get_by_role('heading', name='任务', exact=True)).to_be_visible()
        page.evaluate('document.fonts.ready')
        for width in (1440, 1024, 390):
            page.set_viewport_size({'width': width, 'height': 1080})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(tmp_path / 'daylight-real-api-zh-dark-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1080})
        page.evaluate("document.documentElement.style.zoom = '2'")
        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_archive_readiness_is_persistent_and_does_not_replace_the_preview(page: Page) -> None:
    scenario = controlled_scenario().with_result('archive_pending').with_lifecycle('finished')
    mount_scenario(page, scenario)
    manifest = scenario.result_manifest()
    assert manifest
    posts = []

    def prepare(route):
        posts.append(route.request.method)
        manifest['archive']['ready'] = True
        manifest['archive']['download_url'] = f'/compute/api/download/{scenario.task_id}'
        route.fulfill(status=202, json={'status': 'building'})

    page.route(f'{ORIGIN}/compute/api/results/{scenario.task_id}', lambda route: route.fulfill(json=manifest))
    page.route(f'{ORIGIN}/compute/api/results/{scenario.task_id}/archive', prepare)
    page.goto(f'{ORIGIN}/compute/results/{scenario.task_id}')
    expect(page.locator('.result-preview pre')).to_be_visible()
    preview = page.locator('.result-preview pre').inner_text()
    page.get_by_role('button', name='Prepare full-result ZIP', exact=True).click()
    expect(page.locator('.result-archive-status')).to_have_text('Full-result ZIP is ready to download.')
    expect(page.get_by_role('button', name='Download ZIP', exact=True)).to_be_enabled()
    expect(page.locator('.result-preview pre')).to_have_text(preview)
    assert posts == ['POST']


def test_archive_failure_stays_visible_and_allows_retry(page: Page) -> None:
    scenario = controlled_scenario().with_result('archive_pending').with_lifecycle('finished')
    mount_scenario(page, scenario)
    page.route(f'{ORIGIN}/compute/api/results/{scenario.task_id}/archive',
               lambda route: route.fulfill(status=503, json={'error': 'Archive worker unavailable'}))
    page.goto(f'{ORIGIN}/compute/results/{scenario.task_id}')
    page.get_by_role('button', name='Prepare full-result ZIP', exact=True).click()
    expect(page.locator('.result-archive-status')).to_contain_text('Archive worker unavailable')
    expect(page.get_by_role('button', name='Prepare full-result ZIP', exact=True)).to_be_enabled()
    expect(page.locator('.result-preview pre')).to_be_visible()
