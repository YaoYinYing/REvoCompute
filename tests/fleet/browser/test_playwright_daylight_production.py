# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Production bundle acceptance with authenticated API fixtures and authentic result bytes.

These are browser replays, not live compute execution. Unlike the general fixture
suite these cases use the real Mol* bundle. The separate adapter acceptance checks
exact residue collections; these cases establish rendered integration and reflow.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

import browser_frontend_assets
from frontend_fixtures import ReplayBundle, gremlin_lh_runner, mount_scenario, replay_scenario
from test_playwright_replay_fpocket import fpocket_runner

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[3]
ORIGIN = 'https://revocompute.example'


@pytest.fixture
def production_bundle(monkeypatch):
    monkeypatch.setattr(browser_frontend_assets, '_RESULT_DIST', ROOT / 'frontend/dist')


def capture(page: Page, tmp_path: Path, name: str) -> None:
    page.evaluate('document.fonts.ready')
    for width in (1440, 1024, 390):
        page.set_viewport_size({'width': width, 'height': 1050 if name.startswith('fpocket') else 1080})
        page.evaluate('scrollTo(0, 0)')
        page.screenshot(path=str(tmp_path / f'{name}-{width}-viewport.png'))
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, page.evaluate("[...document.querySelectorAll('body *')].filter(n=>n.getBoundingClientRect().right>innerWidth+1).slice(0,10).map(n=>[n.className,Math.round(n.getBoundingClientRect().right)])"))
        page.screenshot(path=str(tmp_path / f'{name}-{width}.png'), full_page=True)


def test_preparation_and_matrix_use_the_production_bundle(page: Page, production_bundle, tmp_path: Path) -> None:
    replay = ReplayBundle.load(ROOT / 'tests/data/gremlin_lh_replay/2kl8_seed0_944ed43af62e.json')
    mount_scenario(page, replay_scenario(gremlin_lh_runner(), replay))
    page.route(f'{ORIGIN}/compute/api/results/{replay.task_id}/storyboard/**', lambda route: route.fulfill(
        content_type='text/javascript', path=ROOT / 'docker/runners/gremlin_lh/storyboard/index.js'))
    page.set_viewport_size({'width': 1440, 'height': 1080})
    page.goto(f'{ORIGIN}/compute/create_task?task_type=gremlin_lh_fit')
    expect(page.locator('.ct-workbench')).to_be_visible()
    path = replay.logical_artifact_path('alignment', 0)
    assert path
    payload = replay.payload(path)
    assert payload
    page.locator('input[type=file]').first.set_input_files({'name': '2KL8.i90c75_aln.a3m', 'mimeType': 'text/plain', 'buffer': payload[0]})
    expect(page.locator('.ct-file-list')).to_contain_text('2KL8.i90c75_aln.a3m')
    expect(page.locator('.ct-input-preview')).to_contain_text(payload[0].decode().splitlines()[0].lstrip('>'))
    expect(page.locator('.ct-alignment-row')).to_have_count(6)
    page.locator('[data-ct-parameter="iterations"]').fill('99')
    page.get_by_role('button', name='Clear selected files', exact=True).click()
    expect(page.locator('.ct-input-preview')).not_to_be_visible()
    expect(page.locator('[data-ct-parameter="iterations"]')).to_have_value('99')
    page.locator('[data-ct-parameter="iterations"]').fill('400')
    page.locator('input[type=file]').first.set_input_files({'name': '2KL8.i90c75_aln.a3m', 'mimeType': 'text/plain', 'buffer': payload[0]})
    expect(page.locator('.ct-aa-acid').first).to_be_visible()
    expect(page.locator('.ct-preview-foot')).to_contain_text('Original A3M preserved')
    assert page.locator('input[type=file]').first.evaluate("async el => await el.files[0].text()") == payload[0].decode()
    assert page.locator('.ct-aa').first.evaluate("el => parseFloat(getComputedStyle(el).fontSize)") >= 14
    capture(page, tmp_path, 'create')
    page.locator('.ct-advanced > summary').click()
    expect(page.locator('[data-ct-parameter="seed"]')).to_be_visible()
    page.locator('[data-ct-parameter="seed"]').fill('3')
    capture(page, tmp_path, 'create-advanced')
    page.locator('.ct-advanced > summary').click()
    page.goto(f'{ORIGIN}/compute/results/{replay.task_id}')
    expect(page.locator('.glh-bench canvas')).to_be_visible()
    expect(page.locator('.glh-inspector')).to_contain_text('79')
    expect(page.locator('.glh-pair-readout')).to_contain_text('78 ↔ 79')
    page.locator('.glh-pair-preview tbody button').nth(1).click()
    expect(page.locator('.glh-pair-readout')).to_contain_text('19 ↔ 33')
    expect(page.locator('.glh-pair-readout')).to_contain_text('1.5592755')
    page.locator('.glh-pair-preview tbody button').first.click()
    capture(page, tmp_path, 'gremlin-raw')
    page.locator('.glh-landscape [data-view-id="apc_couplings"]').click()
    expect(page.locator('.glh-landscape [data-view-id="apc_couplings"]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.glh-bench canvas')).to_be_visible()
    page.locator('.glh-bench canvas').focus()
    page.keyboard.press('ArrowRight')
    expect(page.locator('.pair-matrix-readout')).not_to_be_empty()
    capture(page, tmp_path, 'gremlin-apc')
    page.locator('.result-view-menu > summary').click()
    page.locator('.result-tab[data-view="ranked_pairs"]').click()
    expect(page.locator('.result-preview table')).to_be_visible()
    capture(page, tmp_path, 'ranked-pairs')
    assert page.evaluate('window.__cspViolations') == []


def test_spatial_pocket_selection_keeps_the_real_protein(page: Page, production_bundle, tmp_path: Path) -> None:
    replay = ReplayBundle.load(ROOT / 'tests/data/fpocket_replay/1suo_2pockets.json')
    mount_scenario(page, replay_scenario(fpocket_runner(), replay))
    page.route(f'{ORIGIN}/compute/api/results/{replay.task_id}/storyboard/**', lambda route: route.fulfill(
        content_type='text/javascript', path=ROOT / 'docker/runners/fpocket/storyboard/index.js'))
    # The replay excludes the large protein payload; supply only the exact
    # repository input whose hash the same run records, never another structure.
    import hashlib
    source = ROOT / 'tests/data/pdb/1SUO.pdb'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == replay.bundle['logical_files']['protein_structure'][0]['sha256']
    for url in [entry['url'] for entry in replay.manifest['result']['files']['protein_structure']]:
        page.route(f'{ORIGIN}{url}', lambda route: route.fulfill(content_type='chemical/x-pdb', path=source))
    page.set_viewport_size({'width': 1440, 'height': 1080})
    page.goto(f'{ORIGIN}/compute/results/{replay.task_id}')
    expect(page.locator('.storyboard-structure-panel[data-ready="true"]')).to_be_visible(timeout=60000)
    expect(page.locator('.storyboard-structure-panel canvas').first).to_be_visible()
    expect(page.locator('.fpl-pocket-row').first).to_have_attribute('aria-current', 'true')
    capture(page, tmp_path, 'fpocket')
    page.locator('.fpl-pocket-row').nth(1).click()
    expect(page.locator('.fpl-stage')).to_contain_text('Pocket 2')
    page.get_by_role('button', name='Focus this pocket', exact=True).click()
    capture(page, tmp_path, 'fpocket-focus')
    page.get_by_role('button', name='Whole structure', exact=True).click()
    page.locator('.fpl-detail summary', has_text='Pocket artifacts').click()
    page.get_by_role('button', name='Inspect alpha-sphere coordinates', exact=True).click()
    expect(page.locator('.storyboard-geometry-panel canvas').first).to_be_visible(timeout=30000)
    expect(page.locator('.storyboard-structure-panel canvas').first).to_be_visible()
    expect(page.locator('.storyboard-geometry-panel')).to_contain_text('fixed display size')
    capture(page, tmp_path, 'fpocket-geometry')
    page.get_by_role('button', name='Close geometry', exact=True).click()
    expect(page.locator('.storyboard-geometry-panel')).to_have_count(0)
    assert page.evaluate('window.__cspViolations') == []


def test_original_approved_fpocket_run_with_real_molecular_stage(page: Page, production_bundle, monkeypatch, tmp_path: Path) -> None:
    """The approved prototype's exact retained run, normalized by production code."""
    from conftest import _load_fleet_module
    from test_playwright_fpocket_result_acceptance import _build_manifest, _projected_manifest, _serve
    module = _load_fleet_module(monkeypatch, tmp_path, extra_env={'RUNNER_UID': '1234', 'RUNNER_GID': '5678'})
    task_id, manifest, root = _build_manifest(module, tmp_path)
    paths = {key: [file['path'] for file in files] for key, files in manifest['result']['files'].items()}
    page.set_viewport_size({'width': 1440, 'height': 1050})
    _serve(page, _projected_manifest(manifest, task_id), root, task_id, paths)
    expect(page.locator('.storyboard-structure-panel[data-ready="true"]')).to_be_visible(timeout=60000)
    expect(page.locator('.fpl-detail')).to_contain_text('0.629')
    expect(page.get_by_role('checkbox', name='Highlight contacts')).to_be_checked()
    capture(page, tmp_path, 'fpocket-approved-run')
    page.set_viewport_size({'width': 1440, 'height': 1050})
    page.get_by_role('checkbox', name='Alpha spheres', exact=True).check()
    expect(page.get_by_role('checkbox', name='Alpha spheres', exact=True)).to_be_checked()
    expect(page.locator('.fpl-scene-bottom')).to_contain_text('recorded alpha spheres shown')
    expect(page.locator('.storyboard-geometry-panel')).to_have_count(0)
    capture(page, tmp_path, 'fpocket-recorded-spheres')
    page.get_by_role('checkbox', name='Alpha spheres', exact=True).uncheck()
    page.get_by_role('checkbox', name='Highlight contacts').uncheck()
    page.locator('.fpl-pocket-row').nth(1).click()
    expect(page.get_by_role('checkbox', name='Highlight contacts')).not_to_be_checked()
    expect(page.locator('.fpl-detail')).to_contain_text('0.301')
    page.get_by_role('checkbox', name='Highlight contacts').check()
    page.get_by_role('button', name='Focus this pocket', exact=True).click()
    page.locator('.fpl-pocket-row').first.click()
    page.get_by_role('button', name='Whole structure', exact=True).click()
    expect(page.locator('.storyboard-structure-panel canvas').first).to_be_visible()


def test_retained_matrix_without_binary_model_uses_the_real_api(page: Page, monkeypatch, tmp_path: Path) -> None:
    """Missing model bytes do not erase authentic retained scientific evidence."""
    import shutil
    import threading
    from conftest import _load_fleet_module, _test_client_auth, _upsert_task_for_user
    from werkzeug.serving import make_server

    module = _load_fleet_module(monkeypatch, tmp_path, extra_env={'RUNNER_UID': '1234', 'RUNNER_GID': '5678'})
    _test_client_auth(module)
    replay = ReplayBundle.load(ROOT / 'tests/data/gremlin_lh_replay/2kl8_seed0_944ed43af62e.json')
    result = tmp_path / 'retained'
    result.mkdir()
    for artifact in replay.manifest['artifacts']:
        payload = replay.payload(artifact['path'])
        if payload is not None:
            path = result / artifact['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload[0])
    _upsert_task_for_user(module, replay.task_id, filename='2KL8.i90c75_aln.a3m',
                          file_path=result / replay.logical_artifact_path('alignment', 0),
                          result_dir=result, username='tester', task_type='gremlin_lh_fit')
    task = module.task_store.get_task(replay.task_id)
    module.task_runtime._finalize_results_manifest(task, execution_state='completed', finished_at=1700000000)
    static = tmp_path / 'static'
    shutil.copytree(ROOT / 'frontend/dist', static / 'app')
    module.app.static_folder = str(static)
    server = make_server('127.0.0.1', 0, module.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        assert page.context.request.post(f'{origin}/compute/api/auth/login', data={'username':'tester','password':'password'}).status == 200
        page.set_viewport_size({'width':1440,'height':1080})
        page.goto(f'{origin}/compute/results/{replay.task_id}')
        expect(page.locator('.glh-bench canvas')).to_be_visible()
        expect(page.locator('.result-status')).to_contain_text('Output check incomplete')
        expect(page.locator('.glh-pair-readout')).to_contain_text('1.5839645')
        expect(page.locator('.glh-inspector')).to_contain_text('79')
        page.locator('.glh-result > details > summary').click()
        expect(page.locator('.glh-artifact-row', has_text='MRF model')).to_contain_text('Not published')
        manifest = page.context.request.get(f'{origin}/compute/api/results/{replay.task_id}').json()
        assert manifest['output_check']['state'] == 'failed'
        assert any('mrf_model' in problem for problem in manifest['output_check']['problems'])
        page.locator('.glh-result > details > summary').click()
        page.screenshot(path=str(tmp_path / 'gremlin-real-api.png'))
    finally:
        server.shutdown()
        thread.join(timeout=5)
