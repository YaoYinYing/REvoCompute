"""Real-bundle verification of structure presentation.

This drives the shell against the **pinned Mol* bundle itself** and asserts what
Mol* actually drew, by pixel-diffing the rendered canvas. It is the counterpart
to `tests/js/test_viewer_shell.js`, which asserts the exact manager/builder
calls against a stub: a call can be shaped perfectly and still be a no-op, which
is precisely the bug this file exists to catch. Neither test alone is
sufficient.

Run:
  xvfb-run -a --server-args="-screen 0 1400x1000x24" \
    /repo/REvoCompute/.venv/bin/python -m pytest tests/test_playwright_real_molstar.py \
      -p no:randomly -v --headed

Why the flags: Mol* requests a GL context with `failIfMajorPerformanceCaveat:
true`, so it refuses a software rasterizer unless Chrome is told to allow one.
Headless Chromium on this host cannot create any GL context, so the browser must
be headed under a display, and `--use-angle=swiftshader` is what makes a context
available at all.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
SHELL_JS = (ROOT / "revocompute" / "static" / "js" / "viewer-shell.js").read_text(encoding="utf-8")
PDB = (ROOT / "tests" / "data" / "pdb" / "2KL8.pdb").read_text(encoding="utf-8")
SHELL_HTML = """<!doctype html><html><body>
  <div id="shellState">Waiting</div><div id="viewerHost" hidden></div>
  <script src="/static/js/viewer-shell.js"></script>
</body></html>"""

# The shell keeps its Viewer in a module closure, so the test serves the real
# module with one added line that exposes it. Everything else - the preset
# vocabulary, the builders path, the colour logic, the presentation chain - is
# the production code verbatim; only the assertion hook is injected.
PROBE_JS = SHELL_JS.replace(
    "    viewer.plugin.canvas3d.setProps({ renderer: { backgroundColor: MOLSTAR_CANVAS_COLORS[activeTheme] } });",
    "    viewer.plugin.canvas3d.setProps({ renderer: { backgroundColor: MOLSTAR_CANVAS_COLORS[activeTheme] } });\n"
    "    window.__probeViewer = viewer;",
    1,
)
assert PROBE_JS != SHELL_JS, "the probe hook no longer matches the shell; update it deliberately"

# Reads the representation type and colour theme Mol* actually stored, which is
# what the user sees, rather than what the shell intended to send.
REPRESENTATION_STATE = """() => {
  const viewer = window.__probeViewer;
  if (!viewer || !viewer.plugin) return null;
  const groups = viewer.plugin.managers.structure.hierarchy.currentComponentGroups;
  return [].concat.apply([], groups).map(component => component.representations.map(ref => {
    const params = (ref.cell && ref.cell.transform && ref.cell.transform.params) || {};
    return (params.type && params.type.name) + '|' + (params.colorTheme && params.colorTheme.name);
  }).join(','));
}"""


@pytest.fixture(scope="module", autouse=True)
def _requires_a_display(request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--headed"):
        pytest.skip("Mol* needs a headed browser under a display; run with --headed under xvfb-run")


def _open_shell(page: Page) -> None:
    page.set_viewport_size({"width": 1280, "height": 960})
    page.route(
        "https://revocompute.example/static/js/viewer-shell.js*",
        lambda route: route.fulfill(content_type="application/javascript", body=PROBE_JS),
    )
    page.route(
        "https://revocompute.example/compute/viewer-shell*",
        lambda route: route.fulfill(content_type="text/html", body=SHELL_HTML),
    )
    page.goto("https://revocompute.example/compute/viewer-shell")
    page.evaluate(
        "window.__reports=[]; window.addEventListener('message', function (event) {"
        " if (event.data && typeof event.data === 'object') window.__reports.push(event.data); });"
    )
    page.evaluate(
        """(text) => window.postMessage({type:'structure', requestId:'probe', text, format:'pdb',
            label:'probe.pdb', theme:'light', preset:'cartoon', colorMode:'chain'}, '*')""",
        PDB,
    )
    page.wait_for_function("window.__reports.some(r => r.type === 'ready')", timeout=180_000)
    # Mol* paints its first frame asynchronously after the ready report.
    page.wait_for_timeout(3000)
    expect(page.locator("canvas").first).to_be_visible()


def _send(page: Page, payload: dict) -> None:
    page.evaluate("(message) => window.postMessage(message, '*')", payload)
    page.wait_for_timeout(1800)


def _state(page: Page) -> list[str]:
    return page.evaluate(REPRESENTATION_STATE)


def _signature(page: Page) -> str:
    """A digest of what the renderer actually painted."""
    return hashlib.sha256(page.locator("canvas").first.screenshot()).hexdigest()


def test_real_preset_changes_the_representation_and_the_render(page: Page) -> None:
    _open_shell(page)
    assert _state(page) == ["cartoon|chain-id"]
    default = _signature(page)

    _send(page, {"type": "preset", "preset": "sticks"})
    assert _state(page) == ["ball-and-stick|chain-id"], _state(page)
    sticks = _signature(page)
    assert sticks != default, "the Sticks preset did not change what Mol* drew"

    _send(page, {"type": "preset", "preset": "surface_ligand"})
    assert _state(page) == ["molecular-surface|chain-id"], _state(page)
    assert _signature(page) not in (default, sticks), "the Surface preset did not change the render"

    _send(page, {"type": "preset", "preset": "cartoon"})
    assert _state(page) == ["cartoon|chain-id"], _state(page)


def test_real_colour_survives_a_representation_swap(page: Page) -> None:
    """The reported bug: a swap reset Mol*'s theme to element-symbol."""
    _open_shell(page)

    _send(page, {"type": "color", "mode": "rainbow"})
    assert _state(page) == ["cartoon|sequence-id"], _state(page)

    _send(page, {"type": "preset", "preset": "sticks"})
    assert _state(page) == ["ball-and-stick|sequence-id"], (
        "the active colour was lost when the representation was swapped"
    )

    _send(page, {"type": "color", "mode": "confidence"})
    assert _state(page) == ["ball-and-stick|plddt-confidence"], _state(page)


def test_real_presentation_reapplies_to_the_next_structure(page: Page) -> None:
    _open_shell(page)
    _send(page, {"type": "color", "mode": "rainbow"})
    _send(page, {"type": "preset", "preset": "sticks"})
    assert _state(page) == ["ball-and-stick|sequence-id"]

    page.evaluate(
        """(text) => window.postMessage({type:'structure', requestId:'probe2', text, format:'pdb',
            label:'probe2.pdb', theme:'light', preset:'sticks', colorMode:'rainbow'}, '*')""",
        PDB,
    )
    page.wait_for_function(
        "window.__reports.some(r => r.type === 'ready' && r.requestId === 'probe2')", timeout=60_000
    )
    page.wait_for_timeout(2500)
    assert _state(page) == ["ball-and-stick|sequence-id"], (
        "the second structure did not keep the requested presentation"
    )
