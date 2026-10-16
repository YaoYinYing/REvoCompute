# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Instrument operations with the installed catalog and bounded synthetic Task volume."""
from __future__ import annotations

import copy
import shutil
import threading
from pathlib import Path

import pytest
from flask import Response
from playwright.sync_api import Page, expect
from werkzeug.serving import make_server

import browser_frontend_assets
from conftest import _load_fleet_module, _test_client_auth, _upsert_task_for_user
from test_playwright_application import ORIGIN, TASK_ID, _install_app, _task_summary

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def installed_server(page: Page, monkeypatch, tmp_path: Path):
    module = _load_fleet_module(monkeypatch, tmp_path, extra_env={'RUNNER_UID': '1234', 'RUNNER_GID': '5678'})
    _test_client_auth(module)
    source = tmp_path / 'sample.fasta'
    source.write_text('>synthetic\nACDE\n')
    result = tmp_path / 'result'
    result.mkdir()
    _upsert_task_for_user(module, TASK_ID, filename=source.name, file_path=source,
                          result_dir=result, username='tester', task_type='gremlin_lh_fit')
    static = tmp_path / 'static'
    shutil.copytree(ROOT / 'frontend/dist', static / 'app')
    module.app.static_folder = str(static)
    module.app.add_url_rule('/compute/export.zip', 'fixture_export', lambda: Response(
        b'fixture archive', mimetype='application/zip',
        headers={'Content-Disposition': 'attachment; filename="result.zip"'},
    ))
    server = make_server('127.0.0.1', 0, module.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        assert page.context.request.post(f'{origin}/compute/api/auth/login', data={
            'username': 'tester', 'password': 'password',
        }).status == 200
        yield origin
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_compare_installed_methods_preserves_contracts_and_access(page: Page, installed_server, tmp_path: Path) -> None:
    origin = installed_server
    catalog = page.context.request.get(f'{origin}/compute/api/types').json()
    page.set_viewport_size({'width': 1440, 'height': 1080})
    page.goto(f'{origin}/runners')
    expect(page.locator('.runner-card')).to_have_count(len(catalog['task_types']))
    names = ['fpocket', 'gremlin_lh_fit', 'alphafold3', 'autodock_vina']
    search = page.get_by_role('searchbox', name='Search methods')
    for name in names:
        search.fill(name)
        page.locator(f'input[data-compare="{name}"]').check()
    search.fill('')
    expect(page.locator('input[data-compare="diffdock"]')).to_be_disabled()
    page.get_by_role('button', name='Compare methods', exact=True).click()
    dialog = page.get_by_role('dialog', name='Compare methods')
    expect(dialog).to_be_visible()
    expect(dialog.locator('tbody tr')).to_have_count(8)
    for index, name in enumerate(names):
        detail = page.context.request.get(f'{origin}/compute/api/types/{name}').json()
        expect(dialog.locator('thead th').nth(index + 1)).to_have_text(detail['display_name'])
        input_cell = dialog.locator('tbody tr').nth(1).locator('td').nth(index)
        for role in detail['inputs']:
            expect(input_cell).to_contain_text(role['title'])
            expect(input_cell).to_contain_text(', '.join(role['formats']))
        expect(dialog.locator('tbody tr').nth(2).locator('td').nth(index)).to_have_text(detail['output_summary'])
    expect(dialog.locator('tbody tr').last.locator('td').nth(2).get_by_role('link')).to_have_attribute(
        'href', '/compute/account/runner-access',
    )
    page.screenshot(path=str(tmp_path / 'compare-installed-1440.png'))
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    expect(dialog.locator('.method-comparison-scroll')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.get_by_role('button', name='Compare methods', exact=True)).to_be_focused()
    expect(page.locator('input[data-compare="fpocket"]')).to_be_checked()
    page.get_by_role('button', name='Clear selection').click()
    expect(page.locator('input[data-compare="fpocket"]')).not_to_be_checked()
    expect(page.locator('input[data-compare="diffdock"]')).to_be_enabled()
    # A failed detail does not hide the comparison for other selected methods.
    page.route(f'{origin}/compute/api/types/fpocket', lambda route: route.fulfill(status=503, json={}))
    page.locator('input[data-compare="fpocket"]').check()
    page.locator('input[data-compare="gremlin_lh_fit"]').check()
    page.get_by_role('button', name='Compare methods', exact=True).click()
    expect(dialog.locator('tbody tr').first.locator('td').first).to_contain_text('Unable to load this runner')
    expect(dialog.locator('thead')).to_contain_text('GREMLIN_LH Potts model')


def test_dense_task_register_keeps_relevant_operations_direct(page: Page, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(browser_frontend_assets, '_RESULT_DIST', ROOT / 'frontend/dist')
    _install_app(page)
    tasks = []
    for index in range(120):
        task = copy.deepcopy(_task_summary())
        task['task_id'] = f'{index:032x}'
        task['display_name'] = f'model-{index:03d}.fasta'
        task['result']['page_url'] = f"/compute/results/{task['task_id']}"
        task['result']['manifest_url'] = f"/compute/api/results/{task['task_id']}"
        task['result']['archive_request_url'] = f"/compute/api/results/{task['task_id']}/archive"
        for action in ('cancel', 'delete'):
            task['actions'][action]['url'] = f"/compute/api/{action}/{task['task_id']}"
        if index % 3 == 0:
            task.update(status='running', terminal=False, finished_at=None, outcome=None)
            task['result']['available'] = False
            task['actions']['cancel']['allowed'] = True
        elif index % 3 == 1:
            task.update(status='failed', outcome=None, error='Runner exited with code 1')
            task['result']['available'] = False
        tasks.append(task)
    page.route(f'{ORIGIN}/compute/api/tasks', lambda route: route.fulfill(json={'tasks': tasks}))
    page.set_viewport_size({'width': 1440, 'height': 1080})
    page.goto(f'{ORIGIN}/compute/dashboard')
    page.get_by_role('button', name='Compact', exact=True).click()
    expect(page.locator('.task-card')).to_have_count(120)
    expect(page.locator('.task-card').first.get_by_role('button', name='Cancel', exact=True)).to_be_visible()
    failed = page.locator('.task-card').filter(has=page.get_by_role('heading', name='model-001.fasta', exact=True))
    expect(failed.get_by_role('link', name='View details', exact=True)).to_be_visible()
    finished = page.locator('.task-card').filter(has=page.get_by_role('heading', name='model-002.fasta', exact=True))
    expect(finished.get_by_role('button', name='Prepare ZIP', exact=True)).to_be_visible()
    assert failed.bounding_box()['height'] < 150
    expect(failed.locator('.status')).to_have_text('failed')
    page.screenshot(path=str(tmp_path / 'tasks-120-1440.png'))
    search = page.get_by_role('searchbox', name='Search', exact=True)
    search.fill(tasks[1]['task_id'])
    expect(page.locator('.task-card')).to_have_count(1)
    expect(page.locator('.task-card h2')).to_have_text('model-001.fasta')
    search.fill('')
    page.get_by_role('button', name='Table', exact=True).click()
    expect(page.locator('.task-table tbody tr')).to_have_count(120)
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_full_result_export_is_available_without_opening_files(page: Page, installed_server) -> None:
    origin = installed_server
    state = {'ready': False}
    manifest = {
        'schema_version': 3, 'task_id': TASK_ID, 'task_type': 'sequence_demo',
        'created_at': '2026-09-29T00:00:03Z', 'status': 'finished', 'terminal': True,
        'error': None, 'run': {}, 'output_check': {'state': 'passed', 'checks': [], 'problems': []},
        'limitations': [], 'views': [], 'artifacts': [], 'result': {'files': {}},
        'storyboard': None, 'outcome': 'SUCCESS', 'total_size': 0,
    }
    def result(route):
        route.fulfill(json={**manifest, 'archive': {
            'ready': state['ready'], 'request_url': f'/compute/api/results/{TASK_ID}/archive',
            **({'download_url': '/compute/export.zip'} if state['ready'] else {}),
        }})
    def prepare(route):
        state['ready'] = True
        route.fulfill(status=202, json={'status': 'queued'})
    page.route(f'{origin}/compute/api/running/{TASK_ID}', lambda route: route.fulfill(json={
        'task_id': TASK_ID, 'task_type': 'sequence_demo', 'display_name': 'sample.fasta',
        'status': 'finished', 'terminal': True, 'result_available': True,
        'status_url': f'/compute/api/running/{TASK_ID}', 'results_url': f'/compute/api/results/{TASK_ID}',
    }))
    page.route(f'{origin}/compute/api/results/{TASK_ID}', result)
    page.route(f'{origin}/compute/api/results/{TASK_ID}/archive', prepare)
    page.goto(f'{origin}/compute/results/{TASK_ID}')
    expect(page.locator('.result-rail')).not_to_be_visible()

    page.get_by_role('button', name='Prepare full-result ZIP').click()
    with page.expect_download() as download:
        page.get_by_role('button', name='Download ZIP', exact=True).click()
    assert Path(download.value.path()).read_bytes() == b'fixture archive'
    expect(page.locator('.result-rail')).not_to_be_visible()
    page.get_by_role('button', name='Open Files and diagnostics', exact=True).click()
    expect(page.locator('.result-rail').get_by_role('button', name='Download ZIP', exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('.result-header-actions').get_by_role('button', name='Download ZIP', exact=True)).to_be_visible()


def test_slow_infrastructure_does_not_block_localized_method_inspection(page: Page, installed_server) -> None:
    origin = installed_server
    page.add_init_script("localStorage.setItem('revocompute-locale', 'zh-CN')")
    pending = []
    page.route(f'{origin}/compute/api/infrastructure', lambda route: pending.append(route))
    page.goto(f'{origin}/runners')
    expect(page.locator('.runner-card').first).to_be_visible()
    expect(page.get_by_role('button', name='比较方法', exact=True)).to_be_visible()
    search = page.get_by_role('searchbox', name='搜索方法', exact=True)
    search.fill('gremlin_lh_fit')
    expect(page.locator('.runner-card h3')).to_have_text('GREMLIN_LH Potts model')
    page.locator('.runner-card').get_by_role('link', name='查看方法', exact=True).click()
    expect(page.locator('.runner-detail-heading h1')).to_have_text('GREMLIN_LH Potts model')
    expect(page.locator('.readiness-state')).to_have_text('正在检查基础设施')
    for route in pending:
        route.fulfill(status=503, json={})
    expect(page.locator('.readiness-state')).to_contain_text('基础设施状态不可用')
