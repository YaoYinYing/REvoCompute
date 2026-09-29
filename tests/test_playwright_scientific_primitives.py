# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for the shared scientific result primitives."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
PRIMITIVES = ROOT / "revocompute" / "static" / "js" / "scientific-primitives.js"
RESULT_STYLES = ROOT / "revocompute" / "static" / "css" / "task-results.css"


def _open(page: Page, body: str) -> None:
    page.set_content(body)
    page.add_style_tag(path=RESULT_STYLES)
    page.add_script_tag(path=PRIMITIVES)


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


def test_numeric_projection_loader_pages_and_enforces_aggregate_limit(page: Page) -> None:
    _open(page, "<div></div>")
    result = page.evaluate(
        """async () => {
          const calls = [];
          const values = Array.from({length: 7}, (_, index) => index + 0.5);
          const fetch = async (url) => {
            const parsed = new URL(url, 'https://example.invalid');
            const offset = Number(parsed.searchParams.get('offset'));
            const limit = Number(parsed.searchParams.get('limit'));
            calls.push({offset, limit, key: parsed.searchParams.get('key')});
            const data = values.slice(offset, offset + limit);
            return {ok: true, json: async () => ({
              dtype: '<f8', shape: [7], key: 'scores', offset, count: data.length,
              total_elements: 7, has_more: offset + data.length < 7, data,
            })};
          };
          const loaded = await REvoComputeScientific.loadNumericProjection(
            {ndarray_url: '/projection'}, {key: 'scores', sliceSize: 3, fetch}
          );
          let bounded;
          try {
            await REvoComputeScientific.loadNumericProjection(
              {ndarray_url: '/projection'}, {key: 'scores', maxElements: 6, fetch}
            );
          } catch (error) { bounded = error.message; }
          return {calls, loaded, bounded};
        }"""
    )

    assert result["calls"][:3] == [
        {"offset": 0, "limit": 3, "key": "scores"},
        {"offset": 3, "limit": 3, "key": "scores"},
        {"offset": 6, "limit": 3, "key": "scores"},
    ]
    assert result["loaded"] == {
        "dtype": "<f8",
        "shape": [7],
        "key": "scores",
        "totalElements": 7,
        "values": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5],
    }
    assert result["bounded"] == "The numeric projection is invalid or exceeds browser limits."


def test_numeric_projection_loader_preserves_abort_and_rejects_broken_pagination(page: Page) -> None:
    _open(page, "<div></div>")
    result = page.evaluate(
        """async () => {
          const errors = {};
          const controller = new AbortController();
          const pending = REvoComputeScientific.loadNumericProjection(
            {ndarray_url: '/projection'},
            {signal: controller.signal, fetch: (_url, init) => new Promise((_resolve, reject) => {
              init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once: true});
            })}
          );
          controller.abort();
          try { await pending; } catch (error) { errors.abort = error.name; }

          const pages = [
            {dtype: '<f8', shape: [4], key: null, offset: 0, count: 2, total_elements: 4, has_more: true, data: [1, 2]},
            {dtype: '<f4', shape: [4], key: null, offset: 2, count: 2, total_elements: 4, has_more: false, data: [3, 4]},
          ];
          try {
            await REvoComputeScientific.loadNumericProjection(
              {ndarray_url: '/projection'}, {sliceSize: 2, fetch: async () => ({ok: true, json: async () => pages.shift()})}
            );
          } catch (error) { errors.changed = error.message; }

          try {
            await REvoComputeScientific.loadNumericProjection(
              {ndarray_url: '/projection'}, {fetch: async () => ({ok: true, json: async () => ({
                dtype: '<f8', shape: [2], key: null, offset: 0, count: 0,
                total_elements: 2, has_more: true, data: [],
              })})}
            );
          } catch (error) { errors.stalled = error.message; }
          return errors;
        }"""
    )

    assert result == {
        "abort": "AbortError",
        "changed": "The numeric projection changed while loading.",
        "stalled": "The numeric projection pagination is invalid.",
    }
