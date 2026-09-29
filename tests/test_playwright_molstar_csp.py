# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Qualify the self-hosted Mol* bundle under the normal Result Page CSP.

Run with a real software-GL display::

    xvfb-run -a --server-args="-screen 0 1400x1000x24" \
      .venv/bin/python -m pytest tests/test_playwright_molstar_csp.py --headed -v
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import urlparse

from playwright.sync_api import Page, expect
import pytest

from conftest import _load_pssm_module, _test_client_auth, _upsert_task_for_user

pytestmark = [pytest.mark.browser, pytest.mark.molstar_csp]

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "revocompute" / "static"
BUNDLE = STATIC / "vendor" / "molstar" / "molstar.js"
PDB = (ROOT / "tests" / "data" / "pdb" / "2KL8.pdb").read_text(encoding="utf-8")
MMCIF = """data_probe
#
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA GLY A 1 1 10.0 10.0 10.0 1.0 80.0 1
#
"""


@pytest.fixture(scope="module", autouse=True)
def _requires_a_display(request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--headed"):
        pytest.skip("Mol* needs a headed browser under a display; run with --headed under xvfb-run")


def _probe_module() -> str:
    return f"""
import {{ MolecularViewer }} from '/static/vendor/molstar/molstar.js';

window.__molstarQualification = {{ state: 'running' }};
(async () => {{
  const host = document.getElementById('molstarQualificationHost');
  const viewer = await MolecularViewer.mount(host, {{selectionEnabled: true, theme: 'light'}});
  const mountedHost = host.firstElementChild;
  await viewer.loadStructure({{data: {json.dumps(PDB)}, format: 'pdb', label: 'probe.pdb'}});
  const cartoonImage = await viewer.captureImage();
  await viewer.setRepresentation('sticks');
  const sticksImage = await viewer.captureImage();
  await viewer.setColor('rainbow');
  const selected = viewer.select({{chain: 'A', residue: 1, numbering: 'auth_seq_id'}});
  const focused = viewer.focus({{chain: 'A', residue: 1, numbering: 'auth_seq_id'}});
  viewer.resetCamera();
  viewer.setTheme('dark');
  viewer.resize();
  const image = await viewer.captureImage();
  await viewer.clear();
  await viewer.loadStructure({{data: {json.dumps(MMCIF)}, format: 'mmcif', label: 'probe.cif'}});
  const canvas = host.querySelector('canvas');
  const canvasReady = Boolean(canvas && canvas.width > 0 && canvas.height > 0);
  const reused = host.firstElementChild === mountedHost;
  viewer.dispose();

  window.__molstarQualification = {{
    state: 'passed', selected, focused, canvasReady, reused,
    image: image.startsWith('data:image/'), representationChanged: cartoonImage !== sticksImage,
    colorChanged: sticksImage !== image,
    disposed: host.childElementCount === 0
  }};
  host.dataset.qualification = 'passed';
}})().catch(error => {{
  window.__molstarQualification = {{ state: 'failed', error: error.stack || String(error) }};
  document.getElementById('molstarQualificationHost').dataset.qualification = 'failed';
}});
"""


def test_direct_molstar_runs_under_the_normal_result_page_csp(
    page: Page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert BUNDLE.is_file(), "run npm ci && npm run build:molstar before the browser contract"

    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    auth_headers = _test_client_auth(module)
    task_id = "1234567890abcdef1234567890abcdef"
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    input_path = tmp_path / "input.pdb"
    input_path.write_text(PDB, encoding="utf-8")
    _upsert_task_for_user(
        module,
        task_id,
        filename=input_path.name,
        file_path=input_path,
        result_dir=result_dir,
        username="tester",
    )
    response = module.app.test_client().get(f"/compute/results/{task_id}", headers=auth_headers)
    assert response.status_code == 200
    csp = response.headers["Content-Security-Policy"]
    script_src = next(part for part in csp.split(";") if part.strip().startswith("script-src"))
    assert "'unsafe-eval'" not in script_src

    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.add_init_script(
        "window.__cspViolations=[]; document.addEventListener('securitypolicyviolation', event => "
        "window.__cspViolations.push({directive:event.effectiveDirective, blockedURI:event.blockedURI}));"
    )
    page.route("https://fonts.googleapis.com/**", lambda route: route.abort())
    page.route("https://fonts.gstatic.com/**", lambda route: route.abort())
    page.route(
        f"https://revocompute.example/compute/results/{task_id}",
        lambda route: route.fulfill(
            status=200,
            headers={"Content-Security-Policy": csp, "Content-Type": "text/html; charset=utf-8"},
            body=response.get_data(as_text=True),
        ),
    )

    def serve_static(route) -> None:
        path = STATIC / urlparse(route.request.url).path.split("/static/", 1)[1]
        if not path.is_file():
            route.abort()
            return
        content_type = "text/css" if path.suffix == ".css" else "application/javascript"
        route.fulfill(content_type=content_type, body=path.read_bytes())

    page.route("https://revocompute.example/static/**", serve_static)
    page.route(
        "https://revocompute.example/compute/api/results/**",
        lambda route: route.fulfill(json={"artifacts": [], "views": [], "archive": {"ready": False}}),
    )
    page.route(
        "https://revocompute.example/compute/api/auth/token",
        lambda route: route.fulfill(json={"token": "test-token"}),
    )
    page.route(
        "https://revocompute.example/molstar-csp-probe.js",
        lambda route: route.fulfill(content_type="application/javascript", body=_probe_module()),
    )

    page.goto(f"https://revocompute.example/compute/results/{task_id}")
    page.evaluate(
        """() => {
          const host = document.createElement('div');
          host.id = 'molstarQualificationHost';
          Object.assign(host.style, { position: 'fixed', inset: '1rem', zIndex: '9999', background: 'white' });
          document.body.appendChild(host);
          const css = document.createElement('link');
          css.rel = 'stylesheet'; css.href = '/static/vendor/molstar/molstar.css';
          document.head.appendChild(css);
          const probe = document.createElement('script');
          probe.type = 'module'; probe.src = '/molstar-csp-probe.js';
          document.head.appendChild(probe);
        }"""
    )
    host = page.locator("#molstarQualificationHost")
    expect(host).to_have_attribute(
        "data-qualification", re.compile("^(passed|failed)$"), timeout=180_000
    )
    result = page.evaluate("() => window.__molstarQualification")
    violations = page.evaluate("() => window.__cspViolations")

    assert result["state"] == "passed", result.get("error")
    assert result["selected"] is True
    assert result["focused"] is True
    assert result["canvasReady"] is True
    assert result["reused"] is True
    assert result["image"] is True
    assert result["representationChanged"] is True
    assert result["colorChanged"] is True
    assert result["disposed"] is True
    assert violations == []
    expect(page.locator("#molstarQualificationHost canvas")).to_have_count(0)
    assert not page_errors, page_errors
