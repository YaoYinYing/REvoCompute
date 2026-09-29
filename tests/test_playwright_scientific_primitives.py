# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for the shared scientific result primitives."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from browser_frontend_assets import install_scientific_assets

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
def _open(page: Page, body: str) -> None:
    page.set_content(body)
    install_scientific_assets(page)


def test_selection_store_and_candidate_selector_reject_stale_completion(page: Page) -> None:
    _open(page, "<div id='candidates'></div>")
    result = page.evaluate(
        """async () => {
          const changes = [];
          const aborted = [];
          const store = new REvoComputeScientific.ResultSelectionStore();
          store.subscribe((state, source) => changes.push([state.candidate, Boolean(source)]));
          const selector = new REvoComputeScientific.CandidateSelector(
            document.getElementById('candidates'), {
              items: [{id: 'slow', label: 'Slow'}, {id: 'fast', label: 'Fast'}],
              store,
              onSelect: (item, index, request) => new Promise((resolve) => {
                request.signal.addEventListener('abort', () => aborted.push(item.id));
                setTimeout(() => resolve(item.id), index === 0 ? 40 : 1);
              }),
            }
          );
          const slow = selector.select(0);
          const fast = selector.select(1);
          const completed = await Promise.all([slow, fast]);
          const current = Array.from(document.querySelectorAll('button')).map((button) => button.getAttribute('aria-current'));
          return {aborted, changes, completed, current, state: store.get()};
        }"""
    )

    assert result == {
        "aborted": ["slow"],
        "changes": [["fast", True]],
        "completed": [None, "fast"],
        "current": ["false", "true"],
        "state": {"candidate": "fast", "entityA": None, "entityB": None, "token": None},
    }


def test_pair_matrix_resizes_and_keeps_pointer_and_keyboard_mapping(page: Page) -> None:
    _open(
        page,
        """
        <style>:root { --ink: #111; --line: #ccc; }</style>
        <div id="plot" style="width: 400px"><div id="figure"><canvas id="matrix" tabindex="0"></canvas></div></div>
        <p id="readout"></p>
        """,
    )
    page.evaluate(
        """() => {
          window.__selections = [];
          window.__matrix = new REvoComputeScientific.PairMatrix({
            figure: document.getElementById('figure'),
            canvas: document.getElementById('matrix'),
            readout: document.getElementById('readout'),
            observe: document.getElementById('plot'),
            maxElements: 6,
            xTitle: 'Aligned token', yTitle: 'Scored token', unit: 'Å',
            formatReadout: (cell) => cell.xLabel + '/' + cell.yLabel + '=' + cell.value + ' Å',
            onSelect: (cell) => window.__selections.push([cell.x, cell.y]),
          });
          window.__matrix.setData({
            values: [[1, 2, 3], [4, 5, 6]],
            xLabels: ['x1', 'x2', 'x3'], yLabels: ['y1', 'y2'],
            xGroups: ['A', 'A', 'B'], yGroups: ['C', 'D'],
          });
        }"""
    )

    expect(page.locator("#matrix")).not_to_have_attribute("aria-disabled", "true")
    assert page.locator("#matrix").evaluate("node => node.style.width") == "400px"
    page.locator("#matrix").click(position={"x": 247, "y": 203})
    expect(page.locator("#readout")).to_have_text("x3/y2=6 Å")
    page.locator("#matrix").press("ArrowLeft")
    expect(page.locator("#readout")).to_have_text("x2/y2=5 Å")
    page.locator("#matrix").click(position={"x": 10, "y": 10})
    expect(page.locator("#readout")).to_have_text("x2/y2=5 Å")
    assert page.evaluate("() => window.__selections") == [[2, 1], [1, 1]]

    page.locator("#plot").evaluate("node => { node.style.width = '640px'; }")
    expect(page.locator("#matrix")).to_have_js_property("clientWidth", 640)
    expect(page.locator("#readout")).to_have_text("x2/y2=5 Å")
    assert page.evaluate("() => window.__selections") == [[2, 1], [1, 1]]

    error = page.evaluate(
        """() => {
          try { window.__matrix.setData({values: [[1, 2, 3], [4, 5, 6], [7, 8, 9]]}); }
          catch (failure) { return failure.message; }
        }"""
    )
    assert error == "The pair matrix exceeds the element limit."


def test_pair_matrix_fits_below_320_pixels_without_losing_axes(page: Page) -> None:
    _open(page, "<div id='plot' style='width:280px'><div id='figure'><canvas id='matrix' tabindex='0'></canvas></div></div><p id='readout'></p>")
    page.evaluate(
        """() => {
          const matrix = new REvoComputeScientific.PairMatrix({
            figure: document.getElementById('figure'), canvas: document.getElementById('matrix'),
            readout: document.getElementById('readout'), observe: document.getElementById('plot'),
            xTitle: 'Aligned token', yTitle: 'Scored token', legendTitle: 'PAE',
          });
          matrix.setData({values: [[1, 2], [2, 1]]});
        }"""
    )
    assert page.locator("#matrix").evaluate("node => node.clientWidth") == 280
    expect(page.locator(".pair-matrix-title")).to_have_count(3)
    page.locator("#matrix").click(position={"x": 180, "y": 160})
    expect(page.locator("#readout")).to_contain_text("value 1.0")
    boxes = page.locator(".pair-matrix-title").evaluate_all(
        "nodes => nodes.map(node => { const box = node.getBoundingClientRect(); return {left: box.left, right: box.right, top: box.top, bottom: box.bottom}; })"
    )
    assert all(box["left"] >= 0 and box["right"] <= 280 for box in boxes)
    assert all(
        first["right"] <= second["left"] or second["right"] <= first["left"]
        or first["bottom"] <= second["top"] or second["bottom"] <= first["top"]
        for index, first in enumerate(boxes) for second in boxes[index + 1:]
    )


def test_structure_viewport_reuses_and_disposes_one_viewer(page: Page) -> None:
    _open(page, "<div id='host'></div>")
    result = page.evaluate(
        """async () => {
          const calls = [];
          const viewer = {
            mount: (host) => { calls.push('mount'); host.textContent = 'mounted'; },
            loadStructure: (source) => calls.push('load:' + source),
            setRepresentation: (mode) => calls.push('representation:' + mode),
            resize: () => calls.push('resize'),
            dispose: () => calls.push('dispose'),
          };
          const viewport = new REvoComputeScientific.StructureViewport(document.getElementById('host'), {viewer});
          await viewport.ready;
          await viewport.loadStructure('candidate-1');
          await viewport.loadStructure('candidate-2');
          await viewport.setRepresentation('surface');
          viewport.destroy();
          await Promise.resolve();
          return calls.filter((call) => call !== 'resize');
        }"""
    )

    assert result == ["mount", "load:candidate-1", "load:candidate-2", "representation:surface", "dispose"]


def test_numeric_projection_loader_uses_one_bounded_request(page: Page) -> None:
    _open(page, "<div></div>")
    result = page.evaluate(
        """async () => {
          const calls = [];
          window.fetch = async (url) => {
            const parsed = new URL(url, 'https://example.invalid');
            calls.push({maximum: parsed.searchParams.get('max_elements'), key: parsed.searchParams.get('key')});
            return {ok: true, json: async () => ({
              kind: 'numeric', dtype: '<f8', shape: [7], key: 'scores', total_elements: 7,
              data: Array.from({length: 7}, (_, index) => index + 0.5),
            })};
          };
          const loaded = await REvoComputeScientific.loadNumericProjection(
            {ndarray_url: '/projection'}, {key: 'scores'}
          );
          let bounded;
          try {
            await REvoComputeScientific.loadNumericProjection(
              {ndarray_url: '/projection'}, {key: 'scores', maxElements: 6}
            );
          } catch (error) { bounded = error.message; }
          return {calls, loaded, bounded};
        }"""
    )

    assert result["calls"][0] == {"maximum": "1048576", "key": "scores"}
    assert result["loaded"] == {
        "dtype": "<f8",
        "shape": [7],
        "key": "scores",
        "totalElements": 7,
        "values": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5],
    }
    assert result["bounded"] == "The bounded projection is invalid or exceeds browser limits."


def test_numeric_projection_loader_preserves_abort_and_rejects_malformed_data(page: Page) -> None:
    _open(page, "<div></div>")
    result = page.evaluate(
        """async () => {
          const errors = {};
          const controller = new AbortController();
          window.fetch = (_url, init) => new Promise((_resolve, reject) => {
              init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once: true});
            });
          const pending = REvoComputeScientific.loadNumericProjection({ndarray_url: '/projection'}, {signal: controller.signal});
          controller.abort();
          try { await pending; } catch (error) { errors.abort = error.name; }

          window.fetch = async () => ({ok: true, json: async () => ({kind: 'numeric', dtype: '<f8', shape: [4], key: null, total_elements: 4, data: [1, 2]})});
          try {
            await REvoComputeScientific.loadNumericProjection({ndarray_url: '/projection'});
          } catch (error) { errors.malformed = error.message; }
          return errors;
        }"""
    )

    assert result == {
        "abort": "AbortError",
        "malformed": "The bounded projection is invalid or exceeds browser limits.",
    }
