# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the public header under WCAG 1.4.4 text-only resize.

At 200% text-only resize the root font doubles while the layout viewport stays
1280px. The public header is a three-column grid (brand | navigation | actions),
and its compact form used to be selected by a viewport media query in rem. A rem
inside a *media* query resolves against the initial 16px font, not the zoomed
root, so that query needs a 1056px viewport and never fires in a 1280px window:
the inline navigation stays in the middle column, into which the doubled brand
label reaches. The collapse is therefore decided by the header's own inline size
(a container query condition, whose rem resolves against the query container's
own zoomed font) instead of by the viewport.

The cases assert observable geometry and rendered state only - the brand label's
character rects against the navigation links' character rects, the two boxes'
disjointness, where the header's own children land, whether the collapse control
is a real hit target, whether an open navigation panel paints over the page's own
content, and the document's own scroll width. They never assert a class name, a
design token, a pixel literal, or a translated string, and every case carries a
non-vacuity witness: the measured state must actually contain the brand label and
the navigation the criterion names.
"""

from __future__ import annotations

import json

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import controlled_scenario, mount_scenario

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"

# The criterion's viewport and condition: a 1280px layout viewport with the root
# font at 200% of its 16px initial size.
LAYOUT_VIEWPORT = {"width": 1280, "height": 900}
INITIAL_ROOT_PX = 16
TEXT_ZOOM_ROOT_PX = 32

# A viewport at which the header's own inline size is already below the collapse
# threshold while the layout viewport is still above a rem-in-a-media-query
# threshold: the band in which the header's container condition and a viewport
# condition disagree. At the initial text size this is where the header takes its
# compact form, so a dropdown the header does not need is visible over the page.
NARROW_LAYOUT_VIEWPORT = {"width": 1080, "height": 900}


def _install_condition(page: Page, css: str) -> None:
    """Apply a condition stylesheet that survives navigation.

    ``add_style_tag`` only covers the current document, so the rule is also
    registered as an init script that re-injects it into every document the page
    loads.
    """
    page.add_init_script(
        "(function(){var css=%s;function inject(){var s=document.createElement('style');"
        "s.textContent=css;(document.head||document.documentElement).appendChild(s);}"
        "if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',inject,{once:true});}"
        "else{inject();}})();" % json.dumps(css)
    )
    page.add_style_tag(content=css)


# Geometry of the header's brand label and navigation: the character rects of each
# run (a range per non-space character), the two run boxes, and the pairs whose
# characters actually intersect. Element and computed-style names are used to
# *observe* the rendered document, never asserted on.
HEADER_GEOMETRY = """
() => {
  const header = document.querySelector('.public-header');
  const brandLink = document.querySelector('.public-brand');
  const brand = brandLink.querySelector('span');
  const nav = document.querySelector('.public-navigation');
  const navPanel = nav.querySelector('nav');
  const links = [...navPanel.querySelectorAll('a')];
  const isRendered = el => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return style.display !== 'none' && style.visibility === 'visible' && box.width > 0 && box.height > 0;
  };
  const charRects = el => {
    const rects = [];
    for (const node of el.childNodes) {
      if (node.nodeType !== 3 || !node.textContent.trim()) continue;
      const text = node.textContent;
      const range = document.createRange();
      for (let index = 0; index < text.length; index++) {
        if (!text[index].trim()) continue;
        range.setStart(node, index); range.setEnd(node, index + 1);
        const box = range.getBoundingClientRect();
        if (box.width > 0 && box.height > 0) rects.push(box);
      }
    }
    return rects;
  };
  const box = el => { const b = el.getBoundingClientRect();
    return {left: b.left, top: b.top, right: b.right, bottom: b.bottom, width: b.width, height: b.height}; };
  // The page's own content: the first block the shell's outlet lays out. Named by
  // the shell's outlet, not by a page class, so the witness survives a redesign.
  const outlet = document.getElementById('main-content');
  const region = outlet && outlet.firstElementChild;
  const regionBox = region && isRendered(region) ? box(region) : null;
  // The area the navigation panel and the page's own content share, and whether the
  // panel is the thing actually painted at the centre of that shared area. In the
  // compact form the panel is an overlay below the header, so an open one lands on
  // top of the content; the criterion is that nothing is painted over the content
  // until the reader opens the panel.
  const panelBox = box(navPanel);
  let shared = 0, panelPaints = false, sharedPoint = null;
  if (isRendered(navPanel) && regionBox) {
    shared = Math.max(0, Math.min(panelBox.right, regionBox.right) - Math.max(panelBox.left, regionBox.left))
      * Math.max(0, Math.min(panelBox.bottom, regionBox.bottom) - Math.max(panelBox.top, regionBox.top));
    if (shared > 0) {
      const x = (Math.max(panelBox.left, regionBox.left) + Math.min(panelBox.right, regionBox.right)) / 2;
      const y = (Math.max(panelBox.top, regionBox.top) + Math.min(panelBox.bottom, regionBox.bottom)) / 2;
      const el = document.elementFromPoint(x, y);
      panelPaints = el !== null && (el === navPanel || navPanel.contains(el));
      sharedPoint = {x: Math.round(x), y: Math.round(y)};
    }
  }
  const brandChars = charRects(brand);
  const linkChars = {};
  const intersecting = [];
  for (const link of links) {
    const chars = charRects(link);
    linkChars[link.textContent.trim()] = {rendered: isRendered(link), chars: chars.length, box: box(link)};
    if (!isRendered(link)) continue;
    for (const a of brandChars) for (const b of chars) {
      const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (x >= 1 && y >= 1) intersecting.push({
        link: link.textContent.trim(), x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10,
        area: Math.round(x * y),
      });
    }
  }
  const root = getComputedStyle(document.documentElement);
  const headerRect = box(header);
  const headerStyle = getComputedStyle(header);
  const control = nav.querySelector(':scope > summary');
  const controlBox = control ? box(control) : null;
  let controlHit = false;
  if (control && isRendered(control)) {
    const hit = document.elementFromPoint(
      controlBox.left + controlBox.width / 2, controlBox.top + controlBox.height / 2);
    controlHit = hit !== null && (hit === control || control.contains(hit));
  }
  return {
    rootFont: parseFloat(root.fontSize),
    header: {box: headerRect, overflow: headerStyle.overflow, padding: {
      left: parseFloat(headerStyle.paddingLeft), right: parseFloat(headerStyle.paddingRight)}},
    brand: {text: brand.textContent.trim(), chars: brandChars.length, rendered: isRendered(brand), box: box(brand)},
    brandLink: box(brandLink),
    nav: {
      rendered: isRendered(nav),
      panel: isRendered(navPanel),
      panelBox: box(navPanel),
      panelPosition: getComputedStyle(navPanel).position,
      controlRendered: control ? isRendered(control) : false,
      control: controlBox ? {box: controlBox, hit: controlHit} : null,
    },
    links: linkChars,
    intersecting: intersecting,
    region: regionBox,
    shared: shared,
    panelPaints: panelPaints,
    sharedPoint: sharedPoint,
    page: {scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth},
  };
}
"""


def _geometry(page: Page) -> dict:
    return page.evaluate(HEADER_GEOMETRY)


def _assert_brand_is_rendered(geometry: dict, context: str) -> None:
    """Non-vacuity witness: the brand label the criteria name is laid out on screen."""
    assert geometry["brand"]["rendered"], f"{context}: the brand label is not rendered: {geometry['brand']}"
    assert geometry["brand"]["chars"] > 0, f"{context}: the brand label has no laid-out characters"


def _assert_navigation_links_are_rendered(geometry: dict, context: str) -> None:
    """Non-vacuity witness: the navigation links the overprint criterion names are on
    screen. Only the cases whose criterion measures a link against the brand label use
    this; in the compact form the links sit behind the disclosure control."""
    rendered = [name for name, link in geometry["links"].items() if link["rendered"]]
    assert rendered, f"{context}: no navigation link is rendered: {geometry['links']}"
    assert all(link["chars"] > 0 for link in geometry["links"].values() if link["rendered"]), (
        f"{context}: a rendered navigation link has no laid-out characters: {geometry['links']}"
    )


def _assert_no_glyph_intersection(geometry: dict, context: str) -> None:
    """No character of the brand label may intersect any character of a nav link."""
    assert geometry["intersecting"] == [], (
        f"{context}: the brand label overprints the navigation: {geometry['intersecting']}"
    )
    # The character-level property above is the criterion; the run boxes give the
    # same fact a name when it is violated at whole-run granularity.
    brand, nav = geometry["brandLink"], geometry["nav"]["panelBox"]
    if nav["width"] == 0:
        return
    assert brand["right"] <= nav["left"] + 1, (
        f"{context}: the brand label reaches into the navigation's box "
        f"(brand right {round(brand['right'])}px, navigation left {round(nav['left'])}px)"
    )


def _mount_public_home(page: Page, *, root_px: int, viewport: dict = LAYOUT_VIEWPORT) -> None:
    page.set_viewport_size(viewport)
    mount_scenario(page, controlled_scenario())
    _install_condition(page, f"html{{font-size:{root_px}px !important;}}")
    page.goto(f"{ORIGIN}/")
    expect(page.locator(".public-header")).to_be_visible()
    page.evaluate("() => document.fonts.ready")
    # The header is in flow (not a sticky layer), and the criterion defines the
    # measurement at the scroll origin; a reading taken while scrolled is a probe
    # artifact, not a rendered overprint.
    page.evaluate("() => window.scrollTo(0, 0)")


def test_public_header_brand_does_not_overprint_navigation_at_text_only_resize(page: Page) -> None:
    """WCAG 1.4.4 at 200% text-only resize: on the public home page the header
    collapses instead of letting the brand label and the navigation overprint, and
    takes its compact form: it stops sharing its row with the navigation, and the
    collapse control is a real hit target inside the header. The same header at the
    initial text size shares its row, so it is the space the content needs - not a
    viewport width - that selects the form."""
    _mount_public_home(page, root_px=TEXT_ZOOM_ROOT_PX)
    geometry = _geometry(page)
    _assert_brand_is_rendered(geometry, "public header @200% text resize")
    assert geometry["rootFont"] == TEXT_ZOOM_ROOT_PX, (
        f"the condition was not applied: root font is {geometry['rootFont']}px"
    )
    _assert_no_glyph_intersection(geometry, "public header @200% text resize")
    _assert_compact_form(geometry, "public header @200% text resize")


def test_public_header_brand_does_not_overprint_navigation_at_initial_text_size(page: Page) -> None:
    """The same property at the initial text size, where the header is at its
    widest: the navigation is inline and the brand label still clears it. This is
    the discriminating half of the pair - it is the state in which the brand label
    and an inline navigation link are both rendered and closest."""
    _mount_public_home(page, root_px=INITIAL_ROOT_PX)
    geometry = _geometry(page)
    _assert_brand_is_rendered(geometry, "public header @initial text size")
    _assert_navigation_links_are_rendered(geometry, "public header @initial text size")
    assert geometry["rootFont"] == INITIAL_ROOT_PX, (
        f"the condition was not applied: root font is {geometry['rootFont']}px"
    )
    _assert_no_glyph_intersection(geometry, "public header @initial text size")


def _assert_compact_form(geometry: dict, context: str) -> None:
    """The header has collapsed onto its own line: the navigation panel is no longer
    laid out inside the header's row (it is hidden until the reader opens it), and the
    disclosure control that replaces it is rendered inside the header and hit-testable
    at its own centre."""
    header, nav = geometry["header"]["box"], geometry["nav"]
    assert nav["controlRendered"], f"{context}: the header's collapse control is not rendered"
    assert nav["control"] is not None
    assert nav["control"]["hit"], f"{context}: the collapse control is not hit-testable at its centre: {nav['control']}"
    control = nav["control"]["box"]
    assert header["top"] - 1 <= control["top"] and control["bottom"] <= header["bottom"] + 1, (
        f"{context}: the collapse control is outside the header box: {control} vs {header}"
    )
    # An unopened panel is not laid out at all; a panel on screen must be below the
    # header's row, never sharing it with the brand label.
    if nav["panel"]:
        assert nav["panelBox"]["top"] >= header["bottom"] - 1, (
            f"{context}: the navigation is still laid out inside the header's row "
            f"(navigation top {round(nav['panelBox']['top'])}px, header bottom {round(header['bottom'])}px)"
        )


def test_public_header_shares_its_row_at_initial_text_size(page: Page) -> None:
    """The counterexample that keeps the compact-form assertions non-vacuous: at the
    initial text size the header is a single row (the navigation panel is laid out
    inside the header box, and its row is not taller than the header), so a test
    asserting the compact form cannot pass by the header being permanently collapsed."""
    _mount_public_home(page, root_px=INITIAL_ROOT_PX)
    geometry = _geometry(page)
    _assert_brand_is_rendered(geometry, "public header @initial text size")
    _assert_navigation_links_are_rendered(geometry, "public header @initial text size")
    header, nav = geometry["header"]["box"], geometry["nav"]
    assert nav["panel"], f"the navigation panel is not rendered at the initial text size: {nav}"
    assert nav["panelBox"]["top"] <= header["bottom"] - 1, (
        f"the header is not sharing its row at the initial text size: {nav['panelBox']} vs {header}"
    )
    assert not nav["controlRendered"], (
        f"the collapse control is rendered while the navigation is still inline: {nav}"
    )


def _assert_navigation_does_not_paint_over_content(geometry: dict, context: str) -> None:
    """No user interaction: the navigation panel either is not rendered, or - if it
    is - does not paint over the page's own content. The header's container condition
    selects the compact form from the header's own inline size, so a panel that is
    open while the header is narrow is a dropdown the header put on screen without
    being asked: it overlays the content, and that is what this criterion rejects."""
    region = geometry["region"]
    assert region is not None, f"{context}: the page's own content was not located: {geometry}"
    nav = geometry["nav"]
    if not nav["panel"]:
        return
    assert geometry["shared"] == 0, (
        f"{context}: the navigation panel overlaps the page's own content "
        f"(panelBox {nav['panelBox']}, content {region}, shared area {geometry['shared']}px^2)"
    )
    assert not geometry["panelPaints"], (
        f"{context}: the navigation panel paints over the page's own content at {geometry['sharedPoint']}"
    )


def test_public_header_navigation_does_not_cover_content_in_the_narrow_band(page: Page) -> None:
    """At a viewport the header's own inline size collapses in, the navigation takes
    its compact form: the panel is not on screen unless the reader opens it, so
    nothing is painted over the page's own content. An always-open dropdown is the
    regression this guards: the panel would cover the content without interaction."""
    _mount_public_home(page, root_px=INITIAL_ROOT_PX, viewport=NARROW_LAYOUT_VIEWPORT)
    geometry = _geometry(page)
    assert geometry["rootFont"] == INITIAL_ROOT_PX, (
        f"the condition was not applied: root font is {geometry['rootFont']}px"
    )
    assert geometry["brand"]["rendered"], f"the brand label is not rendered: {geometry['brand']}"
    _assert_navigation_does_not_paint_over_content(geometry, "public header @narrow viewport")


def test_public_header_navigation_does_not_cover_content_at_text_only_resize(page: Page) -> None:
    """The same criterion at 200% text-only resize: the layout viewport is wide, but
    the header's own inline size is not - the compact form is the header's, and its
    panel must not cover the content until the reader opens it. At this root font the
    compact form is reached well inside the viewport, so the panel would overlay the
    content here too if it were opened without interaction."""
    _mount_public_home(page, root_px=TEXT_ZOOM_ROOT_PX)
    geometry = _geometry(page)
    assert geometry["rootFont"] == TEXT_ZOOM_ROOT_PX, (
        f"the condition was not applied: root font is {geometry['rootFont']}px"
    )
    assert geometry["brand"]["rendered"], f"the brand label is not rendered: {geometry['brand']}"
    _assert_navigation_does_not_paint_over_content(geometry, "public header @200% text resize")
