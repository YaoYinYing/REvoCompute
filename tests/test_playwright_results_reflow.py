# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the Result workspace under text-only 200% resize.

WCAG 1.4.4 (Resize text) is about a reader who enlarges text without enlarging
the window. The layout viewport stays wide, so the workspace still has plenty of
inline size in absolute terms, but every text-bearing box inside it needs twice
as much room. A workspace whose column count is pinned by a ``rem`` media query
cannot see that: ``rem`` in a media query resolves against the initial 16px font
size, so doubling the document's font size moves neither the query nor the
window. The file rail keeps a full-width column while the preview column is left
far below the width its own table needs.

These contracts state the observable end of that failure. A table cell and a
file-rail element must never share a band, and the preview must be wide enough
to show the table it is presenting. Both are measured on the geometry the
browser actually resolves - element rectangles, per-character rectangles, and
the preview's own scroll box - so they hold for whatever mechanism keeps the two
apart, without naming a style, a rule, or a breakpoint.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import DEFAULT_ORIGIN, DEFAULT_TASK_ID, controlled_scenario, mount_scenario

pytestmark = pytest.mark.browser

# `!important` because the shell owns the document's font size through a
# `:root` rule, which outranks a type selector on `html`. This mirrors a reader
# font preference: it enlarges text without touching the layout viewport.
TEXT_ONLY_RESIZE = "html { font-size: 32px !important; }"
PREVIEW_CELLS = ".result-preview th, .result-preview td"
RESULT_ROUTE = f"{DEFAULT_ORIGIN}/compute/results/{DEFAULT_TASK_ID}"

# Everything the invariant is stated over, resolved once from the live layout:
# the two working boxes, every intersection between a preview table cell and a
# file-rail text element, and the per-character rectangles of both.
_GEOMETRY = r"""
() => {
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return {left: +r.left.toFixed(2), top: +r.top.toFixed(2),
            right: +r.right.toFixed(2), bottom: +r.bottom.toFixed(2)};
  };
  const intersection = (a, b) => [
    Math.min(a.right, b.right) - Math.max(a.left, b.left),
    Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top),
  ];
  // One rectangle per painted character of an element's direct text, taken from
  // the browser's own text layout rather than from a font metric guess.
  const charRects = (el) => {
    const out = [];
    for (const node of el.childNodes) {
      if (node.nodeType !== 3 || node.textContent.trim() === '') continue;
      const text = node.textContent;
      const range = document.createRange();
      for (let i = 0; i < text.length; i++) {
        if (text[i].trim() === '') continue;
        range.setStart(node, i);
        range.setEnd(node, i + 1);
        const r = range.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) out.push({rect: rect(range), char: text[i]});
      }
    }
    return out;
  };

  const cells = [...document.querySelectorAll('.result-preview th, .result-preview td')];
  const railElements = [...document.querySelectorAll('.result-rail *')]
    .filter((el) => !el.children.length && el.textContent.trim() !== '');

  const boxCollisions = [];
  for (const cell of cells) {
    const c = rect(cell);
    for (const node of railElements) {
      const [x, y] = intersection(c, rect(node));
      if (x >= 1 && y >= 1) {
        boxCollisions.push({cell: cell.textContent.trim(), rail: node.textContent.trim(),
                            overlapX: +x.toFixed(1), overlapY: +y.toFixed(1),
                            cellBox: c, railBox: rect(node)});
      }
    }
  }

  const cellChars = cells.flatMap(charRects);
  const railChars = railElements.flatMap(charRects);
  let glyphX = 0, glyphY = 0, glyphPairs = 0, glyphSample = null;
  for (const a of cellChars) for (const b of railChars) {
    const [x, y] = intersection(a.rect, b.rect);
    if (x >= 1 && y >= 1) {
      glyphPairs++;
      if (x > glyphX) glyphX = x;
      if (y > glyphY) glyphY = y;
      if (glyphSample === null) {
        glyphSample = {cellChar: a.char, railChar: b.char, cellBox: a.rect, railBox: b.rect};
      }
    }
  }

  const preview = document.querySelector('.result-preview');
  const rail = document.querySelector('.result-rail');
  const [previewRailX, previewRailY] = intersection(rect(preview), rect(rail));
  return {
    rootFontSize: getComputedStyle(document.documentElement).fontSize,
    cells: cells.length,
    railElements: railElements.length,
    preview: rect(preview),
    rail: rect(rail),
    // The two boxes share a band only if they intersect as 2-D regions.
    previewRailSharesBand: previewRailX >= 1 && previewRailY >= 1,
    previewRailOverlap: {x: +previewRailX.toFixed(2), y: +previewRailY.toFixed(2)},
    previewScrollWidth: preview.scrollWidth,
    previewClientWidth: preview.clientWidth,
    boxCollisions: boxCollisions,
    glyphPairs: glyphPairs,
    glyphMaxSingle: {x: +glyphX.toFixed(1), y: +glyphY.toFixed(1)},
    glyphSample: glyphSample,
  };
}
"""


def _open_finished_result(page: Page) -> None:
    """Open the Result workspace and advance its poll-counted lifecycle to the end.

    The router advances one lifecycle step per status poll and the workspace
    polls on mount, so each ``reload`` is exactly one deterministic step. Once a
    terminal state also reports ``result_available`` the manifest renders in the
    same load, so the terminal *manifest* state - not a final pending status - is
    what the last reload shows.
    """
    page.goto(RESULT_ROUTE)
    expect(page.locator(".result-status")).to_contain_text("queued")
    for status in ("running", "finished"):
        page.reload()
        expect(page.locator(".result-status")).to_contain_text(status)


def _mount_text_only_200(page: Page) -> dict:
    """Show the tabular preview at 1280px with a text-only 200% enlargement applied.

    Returns the resolved geometry. The enlargement is a font preference, not a
    browser zoom: a zoom shrinks the viewport in CSS pixels and fires every width
    media query, which is precisely the case this contract excludes.
    """
    scenario = controlled_scenario().with_lifecycle("queued", "running", "finished").with_result("table")
    mount_scenario(page, scenario)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open_finished_result(page)
    page.locator(".result-workspace").scroll_into_view_if_needed()
    page.add_style_tag(content=TEXT_ONLY_RESIZE)
    expect(page.locator(PREVIEW_CELLS).first).to_be_visible()
    measured = page.evaluate(_GEOMETRY)
    # The enlargement must be in force, or the geometry below proves nothing.
    assert measured["rootFontSize"] == "32px", f"the text-only resize did not apply: {measured['rootFontSize']}"
    assert measured["cells"] > 0, "the tabular preview rendered no cells to measure"
    assert measured["railElements"] > 0, "the file rail rendered no text elements to measure"
    return measured


def test_preview_never_shares_a_band_with_the_file_rail_at_200_percent_text(page: Page) -> None:
    """At 200% text-only resize the preview table and the file rail stay apart.

    Three readings of the one requirement, from loosest to tightest: the preview
    region and the rail must not share a band, no rectangle of a preview table
    cell may intersect any rectangle of a file-rail text element, and no painted
    preview character may sit on a painted file-rail character. The region-level
    reading is the weakest of the three - it was already true before the fix,
    because the preview is a scroll container that clips what overflows it - so
    the cell-level readings after it are the ones that carry the defect.
    """
    measured = _mount_text_only_200(page)
    assert not measured["previewRailSharesBand"], (
        "at 200% text-only resize the preview region and the file rail share a band "
        f"({measured['previewRailOverlap']} px of 2-D overlap): "
        f"preview={measured['preview']} rail={measured['rail']}"
    )
    detail = "; ".join(
        f"{item['cell']!r} and {item['rail']!r} share a {item['overlapX']}x{item['overlapY']}px band "
        f"(cell {item['cellBox']}, rail {item['railBox']})"
        for item in measured["boxCollisions"][:4]
    )
    assert measured["boxCollisions"] == [], (
        f"at 200% text-only resize the file rail occupies the same band as the preview table: {detail}"
    )
    assert measured["glyphPairs"] == 0, (
        f"at 200% text-only resize {measured['glyphPairs']} preview glyph(s) intersect file-rail glyphs, "
        f"worst by {measured['glyphMaxSingle']['x']}x{measured['glyphMaxSingle']['y']}px "
        f"({measured['glyphSample']})"
    )


def test_preview_shows_its_table_without_scrolling_at_200_percent_text(page: Page) -> None:
    """The working surface must be wide enough for the table it is presenting.

    This is the defect seen from the preview's side rather than the rail's: the
    preview column is left so narrow that its own table is reachable only through
    a scroll window a fraction of the table's width.
    """
    measured = _mount_text_only_200(page)
    assert measured["previewScrollWidth"] <= measured["previewClientWidth"] + 1, (
        "at 200% text-only resize the preview region is narrower than its own content, so its table "
        f"is reachable only through a {measured['previewClientWidth']}px scroll window: "
        f"scrollWidth={measured['previewScrollWidth']} preview={measured['preview']}"
    )
