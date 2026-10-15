# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser contract for the Mol* advanced-controls disclosure in the Result viewer.

Two halves of one contract, both read from a browser driving the shipped bundle:

* On the real Result route, driven through the canonical Runner fixture, the
  structure viewport is mounted by ``StructureController`` exactly as a reader's
  page mounts it. Mol* renders its own native panel; the observable is the
  reader's affordance -- closed behind a named, on-screen button that opens the
  panel by pointer *and* by keyboard and closes it again without covering the
  workspace, at every width and in fullscreen.
* A mode that deliberately offers no native panel must not offer a disclosure
  either. That is the "intended-hidden, not broken" half, read from the real
  viewer mounted on the contract's own page with and without native panels, so
  the absence is asserted as intent rather than inferred from the Result page.

The browser fixtures launch Chromium with `--use-angle=swiftshader`, so the
Mol* viewer mounts without a display and the contract runs in the default
browser job. Locally, run under a display for a visible session::

    xvfb-run -a --server-args="-screen 0 1400x1000x24" \
      .venv/bin/python -m pytest tests/test_playwright_structure_controls.py --headed -v
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

import browser_frontend_assets
import frontend_fixtures

pytestmark = [pytest.mark.browser]

ROOT = Path(__file__).resolve().parents[1]
RESULT_DIST = ROOT / "frontend" / "dist"
PDB = (ROOT / "tests" / "data" / "pdb" / "2KL8.pdb").read_text(encoding="utf-8")

# Mol*'s own viewport-overlay button is the disclosure. It names itself only in
# a `title` (Mol*'s `IconButton` renders no ARIA), so the title is what the
# reader and the accessibility tree both get from Mol*.
_DISCLOSURE = "button[title='Toggle Controls Panel']"
# The panel Mol* renders into the right region: `ControlsWrapper`'s scroll
# container is what a reader scrolls through the native structure tools.
_PANEL = ".msp-layout-right .msp-scrollable-container"
# The right region Mol* reserves for the native panel: `overflow: hidden` on the
# region means a region outside the structure host is geometry the reader can
# never reach.
_REGION = ".msp-layout-region.msp-layout-right"


def _open_result(page: Page, monkeypatch: pytest.MonkeyPatch, *, width: int, height: int) -> list[str]:
    """Serve the production bundle against the canonical structure fixture.

    The bundle is the built ``frontend/dist``: the advanced controls are Mol*
    chunk markup, so the fixture-viewer double used by the unit suite cannot lay
    them out at all. Loading ``dist`` is the same source ``browser_frontend_assets``
    already uses for the other Mol* cases.
    """
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": width, "height": height})
    # The dist the harness serves is process-global, so it is installed through
    # `monkeypatch`: a bare assignment would leak the production bundle into every
    # later browser case in the same session, whatever bundle that case meant to
    # exercise.
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", RESULT_DIST)
    frontend_fixtures.mount_scenario(page, frontend_fixtures.structure_scenario())
    page.goto(f"{frontend_fixtures.DEFAULT_ORIGIN}/compute/results/{frontend_fixtures.DEFAULT_TASK_ID}")
    expect(page.locator(f".structure-host canvas, .structure-host {_DISCLOSURE}").first).to_be_visible(timeout=180_000)
    expect(page.locator(_DISCLOSURE).first).to_be_visible(timeout=180_000)
    page.wait_for_timeout(1000)
    return errors


def _reading(page: Page) -> dict:
    """What the reader's browser lays out: is the native panel on screen, is it
    inside the structure host, and does the page still fit the window?

    A reading is taken from the DOM a reader meets, never from a layout flag, so
    a panel hidden by CSS while the state says otherwise is reported as closed.
    """
    return page.evaluate(
        """(selectors) => {
          const disclosure = document.querySelector(selectors.disclosure);
          const host = document.querySelector('.structure-host');
          const panel = document.querySelector(selectors.panel);
          const region = document.querySelector(selectors.region);
          const box = (node) => { if (!node) return null; const b = node.getBoundingClientRect();
            return { x: Math.round(b.x), y: Math.round(b.y), width: Math.round(b.width), height: Math.round(b.height) }; };
          const hostBox = host ? host.getBoundingClientRect() : null;
          const inside = (node) => { if (!node || !hostBox) return false; const b = node.getBoundingClientRect();
            return b.left >= hostBox.left - 1 && b.right <= hostBox.right + 1 && b.top >= hostBox.top - 1 && b.bottom <= hostBox.bottom + 1; };
          const opaque = (node) => { if (!node) return false; const style = getComputedStyle(node); const b = node.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && b.width > 0 && b.height > 0; };
          const centre = disclosure ? document.elementFromPoint(
            disclosure.getBoundingClientRect().x + disclosure.getBoundingClientRect().width / 2,
            disclosure.getBoundingClientRect().y + disclosure.getBoundingClientRect().height / 2) : null;
          return {
            disclosure: { box: box(disclosure), label: disclosure ? disclosure.getAttribute('aria-label') : null,
                          title: disclosure ? disclosure.getAttribute('title') : null,
                          inside: inside(disclosure), disabled: disclosure ? disclosure.disabled : null,
                          on: disclosure ? disclosure.className.includes('msp-btn-link-toggle-on') : null,
                          hittable: centre ? disclosure.contains(centre) : false },
            panel: { present: Boolean(panel), visible: opaque(panel), box: box(panel), inside: inside(panel),
                     controls: panel ? panel.querySelectorAll('button, input, select, [role]').length : 0 },
            region: { box: box(region), inside: inside(region) },
            host: box(host),
            toolbar: box(document.querySelector('.structure-toolbar')),
            fullscreen: Boolean(document.fullscreenElement && document.fullscreenElement.classList.contains('structure-viewport')),
            documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          };
        }""",
        {"disclosure": _DISCLOSURE, "panel": _PANEL, "region": _REGION},
    )


def _click_disclosure(page: Page) -> dict:
    page.locator(_DISCLOSURE).first.click()
    page.wait_for_timeout(600)
    return _reading(page)


def test_advanced_controls_toggle_is_discoverable_and_operable(page: Page, monkeypatch: pytest.MonkeyPatch) -> None:
    """At 1440x900 the disclosure is on screen, named, and opens the native panel."""
    errors = _open_result(page, monkeypatch, width=1440, height=900)
    closed = _reading(page)

    # At rest the science owns the stage: the native panel is genuinely closed.
    assert closed["panel"]["visible"] is False, closed
    assert closed["disclosure"]["title"] == "Toggle Controls Panel", closed
    assert closed["disclosure"]["disabled"] is False, closed
    # The affordance is inside the structure host, on screen, and receives the
    # pointer: a button the canvas intercepts is a control a reader cannot use.
    assert closed["disclosure"]["inside"], closed
    assert closed["disclosure"]["hittable"], closed
    assert closed["disclosure"]["box"]["width"] >= 40 and closed["disclosure"]["box"]["height"] >= 40, closed

    # A real pointer click opens the panel, and the panel is on screen.
    opened = _click_disclosure(page)
    assert opened["disclosure"]["on"] is True, opened
    assert opened["panel"]["visible"] is True, "the advanced controls panel did not open"
    assert opened["panel"]["controls"] > 0, "the advanced controls panel rendered no controls"
    assert opened["panel"]["inside"], opened
    assert opened["region"]["inside"], opened
    # The opened layout is the one that must keep the controls reachable: the
    # panel takes a column, so this is where the disclosure could be pushed out.
    assert opened["disclosure"]["inside"] and opened["disclosure"]["hittable"], opened
    # Opening the panel must not push the toolbar or the page off the reader.
    assert opened["toolbar"] is not None and opened["toolbar"]["width"] > 0, opened
    assert opened["documentOverflow"] <= 0, opened

    # A second pointer click puts it back: the disclosure has a close path.
    reclined = _click_disclosure(page)
    assert reclined["disclosure"]["on"] is False, reclined
    assert reclined["panel"]["visible"] is False, "the advanced controls panel did not close"

    # The disclosure is a real button, so it is keyboard operable: focus it the
    # way a keyboard user does and activate it with Enter.
    page.locator(_DISCLOSURE).first.focus()
    assert page.evaluate("(sel) => document.activeElement.matches(sel)", _DISCLOSURE), "the disclosure is not focusable"
    page.keyboard.press("Enter")
    page.wait_for_timeout(600)
    pressed = _reading(page)
    assert pressed["disclosure"]["on"] is True, pressed
    assert pressed["panel"]["visible"] is True, "the panel did not open from the keyboard"
    assert pressed["disclosure"]["hittable"] and pressed["region"]["inside"], pressed
    page.keyboard.press("Enter")
    page.wait_for_timeout(600)
    assert _reading(page)["panel"]["visible"] is False, "the panel did not close from the keyboard"

    # The workspace toolbar owns fullscreen, and the disclosure must survive it.
    # The toolbar's own label flip is the product's signal that fullscreen took;
    # the geometry is then read from the fullscreen layout.
    page.get_by_role("button", name="Enter fullscreen", exact=True).click()
    expect(page.get_by_role("button", name="Exit fullscreen", exact=True)).to_be_visible()
    fullscreen = _reading(page)
    assert fullscreen["fullscreen"] is True, fullscreen
    assert fullscreen["disclosure"]["inside"], fullscreen
    assert fullscreen["disclosure"]["hittable"], fullscreen
    in_fullscreen = _click_disclosure(page)
    assert in_fullscreen["panel"]["visible"] is True, "the panel did not open in fullscreen"
    assert in_fullscreen["disclosure"]["hittable"], in_fullscreen
    assert in_fullscreen["region"]["inside"], in_fullscreen

    assert errors == [], errors
    # Leaving fullscreen is teardown, not part of the contract: the page is
    # discarded with the test, so this is best-effort only.
    page.evaluate("() => { try { document.exitFullscreen(); } catch (error) {} }")


@pytest.mark.parametrize(("width", "height"), [(768, 900), (320, 900)])
def test_advanced_controls_reach_every_reader_at_narrow_widths(page: Page, monkeypatch: pytest.MonkeyPatch, width: int, height: int) -> None:
    """No width strands the disclosure, covers the science, or traps a scroll."""
    errors = _open_result(page, monkeypatch, width=width, height=height)
    # The complete molecular toolbar can place the stage below the initial
    # viewport on a phone. Measure reachability after ordinary page scrolling.
    page.locator(_DISCLOSURE).first.scroll_into_view_if_needed()
    closed = _reading(page)
    assert closed["disclosure"]["inside"], closed
    assert closed["disclosure"]["hittable"], closed
    assert closed["documentOverflow"] <= 0, closed

    opened = _click_disclosure(page)
    assert opened["panel"]["visible"] is True, f"the panel did not open at {width}px"
    assert opened["panel"]["inside"], f"the panel escaped the structure host at {width}px: {opened}"
    assert opened["region"]["inside"], f"the native region escaped the structure host at {width}px: {opened}"
    # The panel overlays the stage; it must not become a second page-wide scroll.
    assert opened["documentOverflow"] <= 0, opened
    assert errors == [], errors


@pytest.mark.parametrize(("options", "expected"), [
    ({}, 1),
    ({"showControls": False}, 0),
])
def test_native_panel_presence_follows_the_mode(page: Page, options: dict, expected: int) -> None:
    """A mode that offers no native panel must not offer its disclosure either.

    This is the "intended-hidden, not broken" half of the contract: the viewer is
    mounted on the contract's own page, with and without native panels, so the
    absence of the affordance is asserted as intent rather than inferred from the
    Result page. A reader never meets a control that cannot act on anything.

    The page loads the viewer's *own* build of the real module. The shipped
    ``frontend/dist`` chunk cannot stand alone -- it shares the application chunk,
    whose bootstrap requires the app root -- so ``dist`` is the wrong source for
    a page that mounts the viewer and nothing else. The entry and config live in
    ``frontend/tests`` next to the other browser-contract harnesses.
    """
    import os
    import subprocess
    import tempfile

    build = Path(tempfile.mkdtemp(prefix="revocompute-structure-browser-build-"))
    output = Path(tempfile.mkdtemp(prefix="revocompute-structure-browser-dist-"))
    environment = {**os.environ}
    for name in ("NODE_ENV", "BROWSER", "REVOCOMPUTE_STRUCTURE_TEST_BUILD", "REVOCOMPUTE_STRUCTURE_TEST_DIST"):
        environment.pop(name, None)
    completed = subprocess.run(
        ["npm", "exec", "vite", "--", "build", "--config", "tests/structure-viewer.vite.config.ts"],
        cwd=ROOT / "frontend",
        env={**environment, "REVOCOMPUTE_STRUCTURE_TEST_BUILD": str(build), "REVOCOMPUTE_STRUCTURE_TEST_DIST": str(output)},
        capture_output=True, text=True, timeout=300,
    )
    if completed.returncode:
        raise RuntimeError(f"Structure viewer browser build failed:\n{completed.stdout}\n{completed.stderr}")
    script = output / "structure-viewer.js"
    stylesheet = next(path for path in output.glob("structure-viewer.css") if path.stat().st_size)

    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(f"console.{message.type}: {message.text}") if message.type == "error" else None)
    page.set_viewport_size({"width": 1440, "height": 900})

    def serve(route) -> None:
        url = route.request.url.split("?", 1)[0]
        if url.endswith("structure-viewer.js"):
            route.fulfill(content_type="application/javascript", body=script.read_bytes())
        elif url.endswith(".css"):
            route.fulfill(content_type="text/css", body=stylesheet.read_bytes())
        else:
            route.fulfill(content_type="text/html", body="<!doctype html><html><body></body></html>")

    page.route("https://viewer.example/**", serve)
    page.goto("https://viewer.example/")
    page.evaluate(
        """bundle => {
          const host = document.createElement('div');
          host.id = 'structureEntryHost';
          Object.assign(host.style, { position: 'fixed', inset: '0', background: 'white' });
          document.body.replaceChildren(host);
          Object.assign(window, {
            __structureData: { data: bundle.data, format: 'pdb', label: 'probe.pdb' },
            __structureOptions: bundle.options,
          });
          const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = '/structure-viewer.css';
          document.head.appendChild(link);
          const script = document.createElement('script'); script.type = 'module'; script.src = '/structure-viewer.js';
          document.head.appendChild(script);
        }""",
        {"data": PDB, "options": options},
    )
    try:
        expect(page.locator("html")).to_have_attribute("data-structure-ready", "true", timeout=180_000)
    except AssertionError:
        raise AssertionError(
            f"viewer never became ready for options={options}: {page.evaluate('() => document.documentElement.dataset.structureError')!r}; {errors}"
        ) from None
    page.wait_for_timeout(800)
    assert page.locator("#structureEntryHost canvas").count() == 1, "the structure canvas did not mount"
    assert page.locator(_DISCLOSURE).count() == expected
    assert errors == [], errors
