# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Scroll and gesture acceptance for the shell's sticky layers and scrollers.

Every case here drives a real scroll - ``page.mouse.wheel`` or a dispatched touch
drag - records the scroll state it measured in, and asserts observable geometry:
bounding rectangles, ``elementFromPoint`` hit-testability, and scroll offsets. No
case asserts a class name as a value, a token, a pixel literal, or a translated
string, and every case carries a non-vacuity witness, because a case that passes
on a page that never scrolled proves nothing.

The sticky geometry these cases drive, read from the product sources:

* ``.app-header`` pins at the viewport top and paints a translucent blurred bar.
* The runner detail's sticky method index pins under that bar and slides beneath
  it. That overlap is *intended* - the bar is translucent, so content passing
  under it still reads, and measuring "does it overlap" while scrolled says
  nothing by itself. The contract asserted here is therefore *reachability*:
  nothing inside the pinned layer may be left completely behind the bar, and
  every control in it must answer ``elementFromPoint`` at its own centre.
* The create-task snapshot panel pins at a viewport-relative offset with no
  knowledge of the shell header above it, so the two layers compete for the same
  band whenever the panel actually pins. Its guard is a viewport-width media
  query, which a text-only resize never trips.
* Below the rail breakpoint the shell floats the navigation over the outlet and
  pays for it with bottom clearance on the outlet, so a scroller's last row is
  reachable - but only once the page itself has moved. A case that hit-tests the
  last row without settling the page measures the floating chrome rather than the
  scroller, and reports an occlusion the reader never meets.

This file also asserts the *absence* of the false positive it must not produce: a
sticky surface that overlaps scrolled content while its own content is still
hit-testable at its centre is reported as reachable, not as occlusion.

Cells driven (viewport / root font / theme / locale):

* runner detail method index: 1280x900 @16px light en, 1280x900 @32px light en,
  1280x900 @16px dark zh-CN; plus a narrow 380x780 cell where it must not pin,
  the witness that the wide cells exercise a layer that really moves.
* runner detail anchor landing (clicking the on-page section index):
  1280x900 @16px light en, @32px light en, and @16px dark zh-CN.
* account deep links: 1280x900 and 1280x500 @16px, in every section; plus a
  wheel-driven scroll that keeps the persistent rail reachable at 1280x500.
* notice scroll memory: 1280x900 @16px.
* dense-table horizontal scroller: 320x800 @16px, driven by wheel and by a
  dispatched touch drag.
* create-task snapshot panel: 1280x900 @16px, 1280x900 @32px, and 1280x400
  @16px - the last two are the cells this round found failing.

The cases, in order:

* ``test_pinned_sticky_layer_keeps_its_content_reachable`` - the runner detail's
  method index, wide, at 200% text-only resize, and in dark mode with zh-CN.
* ``test_account_section_deep_link_lands_below_the_sticky_header`` - each Account
  section as its own route, marked current, landing clear of the bar.
* ``test_sticky_index_is_static_at_a_narrow_viewport`` - the same surface at a
  narrow viewport, where it must scroll away instead of pinning.
* ``test_runner_detail_anchor_lands_below_the_sticky_header`` - clicking each
  on-page section anchor and hit-testing the heading it asked for.
* ``test_account_section_deep_link_lands_below_the_sticky_header`` - each Account
  section as a direct destination, landing clear, full-height and short.
* ``test_persistent_rail_stays_reachable_while_the_page_scrolls`` - the rail,
  scrolled against with real wheel input.
* ``test_notice_keeps_its_remembered_scroll_when_the_surface_is_rebuilt`` - the
  scroll memory in ``system-notices.ts``.
* ``test_dense_table_overflow_reaches_its_last_cell_by_wheel`` - the horizontal
  scroller under the dense-table dashboard layout, driven by wheel.
* ``test_touch_drag_reaches_the_end_of_the_dense_table`` - the same scroller,
  driven by a dispatched touch drag.
* ``test_pinned_create_task_panel_keeps_its_content_reachable`` - the case this
  round found **failing**; see its own docstring.

What is *not* driven here: a cold-load fragment landing (the fragment is
processed before the app mounts, so it neither scrolls nor selects, and that is
the page contract, not a scroll defect); the notice container's own scroll offset
across a rebuild (the product documents no such intent and the container is reset
by design); and every surface, viewport, locale, and theme combination the shell
has - this file drives the sticky and scrolling surfaces the campaign named.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from playwright.sync_api import CDPSession, Page, expect
import pytest

from frontend_fixtures import (
    ADMIN_AUTH,
    CONTROLLED_RUNNER_NAME,
    SEQUENCE_ROLE,
    Citation,
    ParameterSpec,
    RunnerDefinition,
    RunnerScenario,
    controlled_scenario,
    mount_scenario,
)

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"

# WCAG 1.4.4 text-only resize: double the root font and leave the layout
# viewport alone. Sticky offsets are rem-sized, so this is the axis on which
# they move.
TEXT_ZOOM_ROOT_PX = 32
INITIAL_ROOT_PX = 16

# The synthetic method reference the sticky-index cases scroll. The name is a
# harness-local stand-in, never a production Runner identity.
DEEP_RUNNER_NAME = "landscape_demo"

# A notice body long enough to overflow its own bounded scroll region. The copy
# is fixture data, never asserted as product vocabulary.
NOTICE_BODY_SENTENCE = "Operational detail that overflows the bounded region. "


# ── fixtures and helpers ──────────────────────────────────────────────────────


def deep_runner() -> RunnerDefinition:
    """A synthetic method with enough depth that its page really scrolls.

    The depth comes from the parameter list and the citation list; without them
    the detail page is shorter than the viewport and nothing ever pins.
    """
    parameters = tuple(
        ParameterSpec.number(
            f"control_{index:02d}",
            default=index + 0.5,
            has_default=True,
            minimum=0.0,
            maximum=100.0,
            description=f"Control {index} governing one adaptive step of the fit. " * 3,
        )
        for index in range(16)
    )
    return RunnerDefinition(
        name=DEEP_RUNNER_NAME,
        display_name="Landscape demo",
        category="evolution",
        category_label="Evolution",
        summary="Fit a long parameterised landscape so the method reference has depth.",
        use_when="Use when a deep method reference is required for interaction work. " * 4,
        input_summary="One protein sequence. " * 8,
        output_summary="A fitted landscape summary. " * 8,
        considerations=tuple(f"Consideration {index} about the fit. " * 6 for index in range(4)),
        inputs=(SEQUENCE_ROLE,),
        parameters=parameters,
        citations=tuple(
            Citation(num=index + 1, doi=f"10.1000/interaction.{index}", title=f"Reference {index}",
                     url=f"https://example.invalid/ref/{index}")
            for index in range(6)
        ),
    )


def deep_scenario() -> RunnerScenario:
    return controlled_scenario(session=ADMIN_AUTH).with_catalog([deep_runner()])


def quiet_notices(page: Page) -> None:
    """Serve the empty notice projection the router declares only implicitly."""
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": []}))


def notices(page: Page, payload: list[dict]) -> None:
    """Serve an explicit notice projection."""
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": payload}))


def install_text_resize(page: Page, root_px: int) -> None:
    """Double the root font in every document, leaving the layout viewport alone.

    ``add_style_tag`` covers only the current document, so the rule is also
    registered as an init script that re-injects it on each navigation.
    """
    css = f"html{{font-size:{root_px}px !important;}}"
    page.add_init_script(
        "(function(){var css=%s;function inject(){var s=document.createElement('style');"
        "s.textContent=css;(document.head||document.documentElement).appendChild(s);}"
        "if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',inject,{once:true});}"
        "else{inject();}})();" % json.dumps(css)
    )
    page.add_style_tag(content=css)


def open_page(context, viewport: dict, *, root_px: int = INITIAL_ROOT_PX, theme: str | None = None,
              locale: str | None = None) -> Page:
    """A fresh page for one cell.

    A fresh page is required, not tidy: the root-font rule and the stored
    preferences are document-scoped, so one page reused across cells would leak
    a text resize, a theme, or a locale into the next cell.
    """
    fresh = context.new_page()
    fresh.set_viewport_size(viewport)
    if root_px != INITIAL_ROOT_PX:
        install_text_resize(fresh, root_px)
    stored = "".join(
        f"localStorage.setItem({json.dumps(key)}, {json.dumps(value)});"
        for key, value in (("revocompute-theme", theme), ("revocompute-locale", locale))
        if value is not None
    )
    if stored:
        fresh.add_init_script(stored)
    return fresh


def scroll_to(page: Page, target: float) -> int:
    """Scroll the document to ``target`` and return the offset actually reached."""
    return int(
        page.evaluate(
            "target => { window.scrollTo(0, target); return Math.round(window.scrollY); }",
            target,
        )
    )


def wheel_scroll(page: Page, x: float, y: float, delta_y: float, steps: int) -> int:
    """Drive vertical scroll with real wheel input and return the offset reached."""
    page.mouse.move(x, y)
    for _ in range(steps):
        page.mouse.wheel(0, delta_y)
        page.wait_for_timeout(40)
    return int(page.evaluate("Math.round(window.scrollY)"))


def open_profile(page: Page) -> None:
    """Mount the profile with the metrics and credit projections it eagerly loads."""
    mount_scenario(page, controlled_scenario(session=ADMIN_AUTH))
    quiet_notices(page)
    page.route(
        f"{ORIGIN}/compute/api/user-metrics**",
        lambda route: route.fulfill(json={
            "window": "daily", "period": "2026-10-11", "tasks_submitted": 12, "tasks_completed": 10,
            "tasks_failed": 2, "success_rate": 0.8333333, "cpu_tasks": 7, "gpu_tasks": 5,
            "gpu_minutes": 1237.5, "total_runtime_seconds": 98200, "median_runtime_seconds": 4210,
            "distribution": [{"task_type": "sequence_demo", "label": "Sequence demo", "gpu": False, "tasks": 7}],
            "activity": [{"period": f"2026-09-{day:02d}", "count": (day * 7) % 13} for day in range(1, 31)],
        }),
    )
    page.route(
        f"{ORIGIN}/compute/api/gpu-credit",
        lambda route: route.fulfill(json={
            "user_id": 1, "period": "2026-10", "credit_unit_gpu_seconds": 60,
            "monthly_grant_gpu_seconds": 180000, "usage_gpu_seconds": 74250, "adjustment_gpu_seconds": 3600,
            "remaining_gpu_seconds": 109350, "monthly_grant_credits": 3000, "usage_credits": 1237.5,
            "adjustment_credits": 60, "remaining_credits": 1822.5, "allow_gpu_use": True, "history": [],
        }),
    )


def open_dashboard(page: Page) -> None:
    """Open the dashboard in its dense-table layout at a narrow viewport."""
    mount_scenario(page, controlled_scenario(session=ADMIN_AUTH))
    quiet_notices(page)
    page.goto(f"{ORIGIN}/compute/dashboard")
    page.wait_for_timeout(900)
    page.locator("[data-layout='table']").click()
    page.wait_for_timeout(300)


# ── the shared measurement ────────────────────────────────────────────────────

# One probe used by every sticky-layering case. It reports where the header and
# the pinned element land, how much of the pinned element's own content the
# header paints over, and whether that content still answers a hit test at its
# own vertical centre. "Reachable" means the probe point resolves to the pinned
# element, one of its descendants, or one of its ancestors: the point is not
# standing on some other surface. A sticky surface painting over scrolled content
# is intended; content that becomes permanently unreachable is not.
STICKY_PROBE = """
(selector) => {
    const box = (r) => ({top: +r.top.toFixed(1), bottom: +r.bottom.toFixed(1),
                         left: +r.left.toFixed(1), right: +r.right.toFixed(1)});
    const bar = document.querySelector('.app-header').getBoundingClientRect();
    const pinned = document.querySelector(selector);
    if (!pinned) return {missing: selector};
    const rect = pinned.getBoundingClientRect();
    const style = getComputedStyle(pinned);
    const owns = (node) => {
        for (let walk = node; walk; walk = walk.parentElement) { if (walk === pinned) return true; }
        return false;
    };
    const reach = (node) => {
        const r = node.getBoundingClientRect();
        const hit = document.elementFromPoint(r.left + Math.min(2, r.width / 2), r.top + r.height / 2);
        const covered = Math.min(r.bottom, bar.bottom) - Math.max(r.top, bar.top);
        return {tag: node.tagName, text: (node.textContent || '').trim().slice(0, 24),
                top: +r.top.toFixed(1), height: +r.height.toFixed(1),
                coveredPx: +Math.max(0, covered).toFixed(1), reachable: owns(hit)};
    };
    const shown = (node) => { const r = node.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const controls = [...pinned.querySelectorAll('a,button,input,select,textarea,summary')]
        .filter(shown).map(reach);
    const text = [...pinned.querySelectorAll('*')]
        .filter((node) => !node.children.length && (node.textContent || '').trim()).map(reach);
    return {scrollY: Math.round(window.scrollY),
            scrollable: document.documentElement.scrollHeight - window.innerHeight,
            header: box(bar), headerBottom: +bar.bottom.toFixed(1),
            pinned: box(rect), position: style.position, offsetTop: style.top,
            pinnedAtOffset: Math.abs(rect.top - parseFloat(style.top)) < 1.5,
            innerScroll: Math.round(pinned.scrollTop), controls, text};
}
"""


def reachable_controls(sample: Mapping[str, object]) -> list[Mapping[str, object]]:
    """The controls in a sticky sample, as reported by STICKY_PROBE."""
    return list(sample["controls"])  # type: ignore[arg-type]


def unreachable_content(sample: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Content the sticky header paints over in full *and* leaves unreachable.

    Partial coverage is intended: the bar is translucent, and a sticky layer is
    meant to slide beneath it. Only content that is entirely behind the bar and
    cannot be hit-tested at its own centre is a defect.
    """
    offenders = []
    for node in [*reachable_controls(sample), *sample["text"]]:  # type: ignore[arg-type]
        if node["coveredPx"] >= node["height"] and not node["reachable"]:
            offenders.append(node)
    return offenders


# ── sticky layering ───────────────────────────────────────────────────────────


def test_pinned_sticky_layer_keeps_its_content_reachable(page: Page) -> None:
    """The runner detail's method index pins under the header without burying content.

    Driven at a wide viewport, at a 200% text-only resize, and in dark mode with
    the zh-CN locale. The index is *meant* to slide under the translucent bar, so
    the contract is reachability: it must pin at its own sticky offset, it must
    reach the bar (otherwise the case proves nothing), and every link it holds
    must answer ``elementFromPoint`` at its own centre.
    """
    cells = (
        ("wide/16px/light/en", {"width": 1280, "height": 900}, INITIAL_ROOT_PX, None, None),
        ("wide/32px/light/en", {"width": 1280, "height": 900}, TEXT_ZOOM_ROOT_PX, None, None),
        ("wide/16px/dark/zh-CN", {"width": 1280, "height": 900}, INITIAL_ROOT_PX, "dark", "zh-CN"),
    )
    failures: list[str] = []
    for name, viewport, root_px, theme, locale in cells:
        fresh = open_page(page.context, viewport, root_px=root_px, theme=theme, locale=locale)
        try:
            mount_scenario(fresh, deep_scenario())
            quiet_notices(fresh)
            fresh.goto(f"{ORIGIN}/runners/{DEEP_RUNNER_NAME}")
            fresh.wait_for_timeout(900)
            reached = scroll_to(fresh, 10_000)
            sample = fresh.evaluate(STICKY_PROBE, ".method-index")
        finally:
            fresh.close()
        if sample.get("missing"):
            failures.append(f"{name}: no method index on the runner detail")
            continue

        # Non-vacuity witness: the page really scrolled, and the index really
        # pinned at its own offset inside the header band.
        assert sample["scrollable"] > 0 and reached > 0, (
            f"{name}: nothing scrolled, so pinning was never exercised; "
            f"scrollY={sample['scrollY']}, scrollable={sample['scrollable']}"
        )
        assert sample["pinnedAtOffset"], (
            f"{name}: the method index is not pinned at its sticky offset; scrollY={sample['scrollY']}, "
            f"position={sample['position']}, top={sample['pinned']['top']}, offsetTop={sample['offsetTop']}"
        )
        assert sample["pinned"]["top"] >= sample["headerBottom"], (
            f"{name}: the pinned index is hidden by the header band; reachability was "
            f"never exercised; scrollY={sample['scrollY']}, pinnedTop={sample['pinned']['top']}, "
            f"headerBottom={sample['headerBottom']}"
        )

        controls = reachable_controls(sample)
        assert controls, f"{name}: the pinned index holds no controls, so the reachability contract is empty"
        unreachable = [node for node in controls if not node["reachable"]]
        assert not unreachable, (
            f"{name}: {len(unreachable)} control(s) in the pinned index do not answer elementFromPoint at "
            f"their own centre; scrollY={sample['scrollY']}, headerBottom={sample['headerBottom']}, "
            f"pinnedTop={sample['pinned']['top']}; controls={unreachable}"
        )
        offenders = unreachable_content(sample)
        if offenders:
            failures.append(
                f"{name}: scrollY={sample['scrollY']}, headerBottom={sample['headerBottom']}, "
                f"pinnedTop={sample['pinned']['top']}, fully-occluded={offenders}"
            )
    assert not failures, "the pinned layer buried its own content:\n" + "\n".join(failures)


def test_sticky_index_is_static_at_a_narrow_viewport(page: Page) -> None:
    """At a narrow viewport the method index is not sticky and scrolls away.

    The complement of the case above: this cell must *not* pin, which is the
    non-vacuity witness that the reachability case measures a real pinning
    surface rather than a layer that never moves.
    """
    fresh = open_page(page.context, {"width": 380, "height": 780})
    try:
        mount_scenario(fresh, deep_scenario())
        quiet_notices(fresh)
        fresh.goto(f"{ORIGIN}/runners/{DEEP_RUNNER_NAME}")
        fresh.wait_for_timeout(900)
        at_rest = fresh.evaluate(STICKY_PROBE, ".method-index")
        assert not at_rest.get("missing"), "no method index on the runner detail"
        assert at_rest["pinned"]["top"] >= at_rest["headerBottom"] - 1.5, (
            f"the narrow index starts behind the header; scrollY={at_rest['scrollY']}, "
            f"top={at_rest['pinned']['top']}, headerBottom={at_rest['headerBottom']}"
        )
        assert at_rest["position"] != "sticky" or at_rest["pinned"]["top"] > at_rest["headerBottom"], (
            f"the narrow index pins at its offset, which contradicts the narrow layout; "
            f"scrollY={at_rest['scrollY']}, position={at_rest['position']}"
        )
        reached = wheel_scroll(fresh, 190, 400, 220, 20)
        moved = fresh.evaluate(STICKY_PROBE, ".method-index")
    finally:
        fresh.close()
        assert reached > 0, f"the narrow detail never scrolled; scrollY={moved['scrollY']}"
        # A static index leaves with the document; past its own height it is gone
        # from the viewport, which is the witness that the wide cells' pinning
        # surface is real and this cell is its complement.
        assert moved["pinned"]["bottom"] <= 0, (
            f"the narrow index did not scroll away with the document, so it is still occupying the "
            f"viewport; scrollY={moved['scrollY']}, indexBottom={moved['pinned']['bottom']}"
        )


# ── deep-link landing ─────────────────────────────────────────────────────────

# The landing probe hit-tests a heading at the point a reader would click, and
# reports the scroll state it measured in.
LANDING_PROBE = """
(id) => {
    const section = document.getElementById(id);
    if (!section) return {missing: id};
    const heading = section.querySelector('h2, h3');
    if (!heading) return {missing: 'heading'};
    const rect = heading.getBoundingClientRect();
    const bar = document.querySelector('.app-header').getBoundingClientRect();
    const hit = document.elementFromPoint(rect.left + 4, rect.top + rect.height / 2);
    return {scrollY: Math.round(window.scrollY),
            scrollable: document.documentElement.scrollHeight - window.innerHeight,
            top: +rect.top.toFixed(1), bottom: +rect.bottom.toFixed(1),
            headerBottom: +bar.bottom.toFixed(1),
            theme: document.documentElement.dataset.theme,
            lang: document.documentElement.lang,
            owned: Boolean(hit && (heading === hit || heading.contains(hit) || hit.contains(heading)))};
}
"""




def assert_landing_clear(sample: Mapping[str, object], where: str) -> None:
    assert sample["owned"], (
        f"{where}: the heading is not hit-testable clear of the sticky header; "
        f"scrollY={sample['scrollY']}, headingTop={sample['top']}, headingBottom={sample['bottom']}, "
        f"headerBottom={sample['headerBottom']}"
    )
    assert sample["top"] >= sample["headerBottom"] - 0.5, (
        f"{where}: the heading landed behind the header band; "
        f"scrollY={sample['scrollY']}, headingTop={sample['top']}, headerBottom={sample['headerBottom']}"
    )


def test_runner_detail_anchor_lands_below_the_sticky_header(page: Page) -> None:
    """An anchor landing on the runner detail must not sit under the sticky header.

    The section index on the page *is* the reader-facing anchor surface, so the
    case clicks each of its links - a same-document fragment navigation, exactly
    what a reader does - and then hit-tests the heading it asked for. Five cells:
    the 768px and 1024px widths around the shell's rail breakpoint, a wide
    viewport, a 200% text-only resize, and dark mode with the zh-CN locale; the
    last asserts the preference it carried really reached the document, so it
    cannot pass as a silent duplicate of the first.

    The section carries a scroll margin in the product, so this asserts the
    contract the markup states rather than a measured pixel.
    """
    cells = (
        ("tablet/16px", {"width": 768, "height": 900}, INITIAL_ROOT_PX, None, None),
        ("rail-breakpoint/16px", {"width": 1024, "height": 900}, INITIAL_ROOT_PX, None, None),
        ("wide/16px", {"width": 1280, "height": 900}, INITIAL_ROOT_PX, None, None),
        ("wide/32px", {"width": 1280, "height": 900}, TEXT_ZOOM_ROOT_PX, None, None),
        ("wide/16px/dark/zh-CN", {"width": 1280, "height": 900}, INITIAL_ROOT_PX, "dark", "zh-CN"),
    )
    for name, viewport, root_px, theme, locale in cells:
        fresh = open_page(page.context, viewport, root_px=root_px, theme=theme, locale=locale)
        try:
            mount_scenario(fresh, deep_scenario())
            quiet_notices(fresh)
            fresh.goto(f"{ORIGIN}/runners/{DEEP_RUNNER_NAME}")
            fresh.wait_for_timeout(1000)
            links = fresh.locator(".method-index a")
            count = links.count()
            assert count > 0, f"the {name} cell exposes no section anchors"
            for index in range(count):
                link = links.nth(index)
                target = (link.get_attribute("href") or "").lstrip("#")
                link.click()
                fresh.wait_for_timeout(500)
                sample = fresh.evaluate(LANDING_PROBE, target)
                where = f"runner anchor {target} in the {name} cell"
                assert not sample.get("missing"), f"{where}: the anchor target is not in the document"
                if theme is not None:
                    assert sample["theme"] == theme, (
                        f"{where}: the stored theme preference did not reach the document; theme={sample['theme']}"
                    )
                if locale is not None:
                    assert sample["lang"] == locale, (
                        f"{where}: the stored locale preference did not reach the document; lang={sample['lang']}"
                    )
                assert sample["scrollable"] > 0, (
                    f"{where}: the page cannot scroll, so a landing offset is not a landing"
                )
                assert_landing_clear(sample, where)
        finally:
            fresh.close()


# An Account section is its own route: the section heading is the page's identity.
# This probe reports that heading's geometry, whether it owns the point at its own
# centre clear of the sticky header, and the destination the shell marks current.
SECTION_PROBE = """
(section) => {
    const root = document.querySelector('[data-section="' + section + '"]');
    if (!root) return {missing: section};
    const heading = root.querySelector('h1, h2, h3');
    if (!heading) return {missing: 'heading'};
    const rect = heading.getBoundingClientRect();
    const bar = document.querySelector('.app-header').getBoundingClientRect();
    const hit = document.elementFromPoint(rect.left + 4, rect.top + rect.height / 2);
    const current = document.querySelector('.app-nav a[aria-current="page"]');
    return {scrollY: Math.round(window.scrollY),
            scrollable: document.documentElement.scrollHeight - window.innerHeight,
            top: +rect.top.toFixed(1), bottom: +rect.bottom.toFixed(1),
            headerBottom: +bar.bottom.toFixed(1),
            current: current ? current.getAttribute('href') : null,
            owned: Boolean(hit && (heading === hit || heading.contains(hit) || hit.contains(heading)))};
}
"""


def test_account_section_deep_link_lands_below_the_sticky_header(page: Page) -> None:
    """An Account section is a direct destination: its deep link lands clear.

    Each section is its own route with its own address, so a deep link, a refresh,
    and a shared URL all resolve to a real page. The section's own heading must be
    the page identity: hit-testable at its own centre and clear of the sticky bar,
    with the shell marking that exact destination current in the navigation.

    Driven at a full-height viewport and at a short one.
    """
    sections = (
        ("account", "/compute/profile"),
        ("security", "/compute/account/security"),
        ("api-key", "/compute/account/api-key"),
        ("runner-access", "/compute/account/runner-access"),
        ("gpu-credits", "/compute/account/gpu-credits"),
        ("metrics", "/compute/account/metrics"),
    )
    for viewport in ({"width": 1280, "height": 900}, {"width": 1280, "height": 500}):
        fresh = open_page(page.context, viewport)
        try:
            open_profile(fresh)
            for section, route in sections:
                fresh.goto(f"{ORIGIN}{route}")
                fresh.wait_for_timeout(700)
                sample = fresh.evaluate(SECTION_PROBE, section)
                where = f"account {route} at {viewport['width']}x{viewport['height']}"
                assert not sample.get("missing"), f"{where}: no account section for that route"
                assert sample["top"] >= sample["headerBottom"] - 0.5, (
                    f"{where}: the section heading landed behind the header band; "
                    f"scrollY={sample['scrollY']}, headingTop={sample['top']}, headerBottom={sample['headerBottom']}"
                )
                assert sample["owned"], (
                    f"{where}: the section heading is not hit-testable at its own centre; "
                    f"scrollY={sample['scrollY']}, headingTop={sample['top']}"
                )
                assert sample["current"] == route, (
                    f"{where}: the shell did not mark the section's own destination current; "
                    f"current={sample['current']}, expected={route}"
                )
        finally:
            fresh.close()


def test_persistent_rail_stays_reachable_while_the_page_scrolls(page: Page) -> None:
    """The rail persists while the page scrolls, and scrolls inside itself.

    The rail is chrome that outlives the route: it stays in place while a long
    page moves under it, so its destinations are reachable at the end of a scroll
    exactly as at the start. The scroll is driven with real wheel input, and the
    case is only non-vacuous once the page has actually moved.
    """
    fresh_viewport_height = 500
    fresh = open_page(page.context, {"width": 1280, "height": fresh_viewport_height})
    try:
        open_profile(fresh)
        fresh.goto(f"{ORIGIN}/compute/account/metrics")
        fresh.wait_for_timeout(700)
        before = fresh.evaluate(
            "() => { const r = document.querySelector('.app-sidebar').getBoundingClientRect();"
            " return {top: r.top, height: r.height, position: getComputedStyle(document.querySelector('.app-sidebar')).position}; }"
        )
        assert before["position"] == "sticky", before
        reached = wheel_scroll(fresh, 640, 400, 400, 12)
        sample = fresh.evaluate(STICKY_PROBE, ".app-sidebar")
    finally:
        fresh.close()
    assert reached > 0 and sample["scrollY"] > 0, (
        f"the account page never scrolled, so persistence was not exercised; reached={reached}, "
        f"scrollY={sample['scrollY']}"
    )
    assert sample["pinnedAtOffset"], (
        f"the rail is not at its sticky offset after scrolling; scrollY={sample['scrollY']}, "
        f"top={sample['pinned']['top']}, offsetTop={sample['offsetTop']}"
    )
    # The bar is a band in its own grid column; the rail is the column beside it.
    # "Not painted over" means the two rectangles do not intersect: the rail is
    # either below the bar's bottom edge or clear of its left edge.
    bar = sample["header"]
    rail = sample["pinned"]
    assert rail["top"] >= bar["bottom"] - 1.5 or rail["right"] <= bar["left"] + 1.5, (
        f"the rail overlaps the top bar; scrollY={sample['scrollY']}, "
        f"rail={rail}, bar={bar}"
    )
    rail = sample["pinned"]
    assert rail["bottom"] <= fresh_viewport_height + 1.5, (
        f"the rail grew past the viewport instead of scrolling inside itself; "
        f"rail={rail}, viewportHeight={fresh_viewport_height}"
    )
    assert sample["innerScroll"] == 0, (
        f"scrolling the page also scrolled the rail; innerScroll={sample['innerScroll']}"
    )
    controls = reachable_controls(sample)
    assert controls, "the rail holds no destinations"
    onscreen = [
        node
        for node in controls
        if node["top"] >= rail["top"] - 0.5 and node["top"] + node["height"] <= rail["bottom"] + 0.5
    ]
    assert onscreen, f"the rail shows none of its own destinations; rail={rail}"
    unreachable = [node for node in onscreen if not node["reachable"]]
    assert not unreachable, (
        f"{len(unreachable)} rail destination(s) inside the rail's box do not answer "
        f"elementFromPoint at their own centre; scrollY={sample['scrollY']}, offenders={unreachable}"
    )


# ── notice scroll memory ──────────────────────────────────────────────────────

NOTICE_SAMPLE = """
() => {
    const card = document.querySelector('[data-notice-id="beta"]');
    const body = card.querySelector('.sys-notice-body');
    return {scrollY: Math.round(window.scrollY),
            scrollTop: Math.round(body.scrollTop),
            scrollHeight: body.scrollHeight, clientHeight: body.clientHeight,
            open: card.querySelector('details').open,
            present: true};
}
"""


def test_notice_keeps_its_remembered_scroll_when_the_surface_is_rebuilt(page: Page) -> None:
    """A notice body's scroll position survives hiding a sibling notice.

    ``system-notices.ts`` remembers each notice's own scroll offset and restores
    it whenever it rebuilds the surface. Driving the surface rebuild (hide a
    sibling, then reopen from the global affordance) must not lose the reader's
    place in an unrelated notice's body.
    """
    query = {
        "id": "beta", "level": "critical", "title": "Action required",
        "body": NOTICE_BODY_SENTENCE * 140,
    }
    sibling = {
        "id": "alpha", "level": "warning", "title": "Scheduled maintenance",
        "body": NOTICE_BODY_SENTENCE * 140,
    }
    mount_scenario(page, controlled_scenario(session=ADMIN_AUTH))
    notices(page, [sibling, query])
    page.goto(f"{ORIGIN}/compute/dashboard")
    page.wait_for_timeout(900)

    def sample() -> dict:
        return page.evaluate(NOTICE_SAMPLE)

    start = sample()
    # Non-vacuity witness: the body must really be its own scroller with room to
    # scroll, and the notice must really be open for a reader to have scrolled it.
    assert start["present"] and start["open"], f"the notice is not open, so its body cannot be scrolled: {start}"
    assert start["scrollHeight"] > start["clientHeight"], (
        f"the notice body does not overflow, so scroll memory has nothing to remember: {start}"
    )

    body = page.locator("[data-notice-id='beta'] .sys-notice-body")
    body.evaluate("node => { node.scrollTop = Math.round((node.scrollHeight - node.clientHeight) * 0.6); }")
    page.wait_for_timeout(250)
    remembered = sample()
    assert remembered["scrollTop"] > 0, (
        f"the notice body did not scroll, so nothing was remembered; scrollY={remembered['scrollY']}, "
        f"scrollTop={remembered['scrollTop']}, measurement={remembered}"
    )

    page.locator("[data-notice-id='alpha'] .sys-notice-tools button").last.click()
    page.wait_for_timeout(300)
    assert page.locator("[data-notice-id='alpha']").count() == 0, "hiding a notice did not remove it"
    after_hide = sample()
    assert after_hide["scrollTop"] == remembered["scrollTop"], (
        f"hiding a sibling notice reset this notice's remembered scroll position; "
        f"scrollY={after_hide['scrollY']}, before={remembered['scrollTop']}, after={after_hide['scrollTop']}, "
        f"measurement={after_hide}"
    )

    # The global affordance rewrites every notice's disclosure state and
    # re-renders; the body's own offset must survive that rebuild too.
    affordance = page.locator(".app-notice-button")
    affordance.click()
    page.wait_for_timeout(300)
    affordance.click()
    page.wait_for_timeout(300)
    after_reopen = sample()
    assert after_reopen["scrollTop"] == remembered["scrollTop"], (
        f"reopening the notices reset this notice's remembered scroll position; "
        f"scrollY={after_reopen['scrollY']}, before={remembered['scrollTop']}, after={after_reopen['scrollTop']}, "
        f"measurement={after_reopen}"
    )


# ── horizontal overflow ───────────────────────────────────────────────────────

# The dense-table scroller: the last cell's own rectangle against the scroller's
# box, and whether that cell answers a hit test at its centre. The scroll state
# is always reported.
TABLE_PROBE = """
() => {
    const list = document.querySelector(".task-list[data-layout='table']");
    if (!list) return {missing: 'table layout'};
    const cells = [...list.querySelectorAll('th, td')];
    const last = cells[cells.length - 1];
    const box = list.getBoundingClientRect();
    const cell = last.getBoundingClientRect();
    const hit = document.elementFromPoint(cell.left + cell.width / 2, cell.top + cell.height / 2);
    const chain = [];
    let node = hit;
    while (node && chain.length < 5) {
        chain.push(node.tagName.toLowerCase() + '.' + (typeof node.className === 'string' ? node.className.slice(0, 24) : ''));
        node = node.parentElement;
    }
    return {scrollLeft: Math.round(list.scrollLeft),
            maxScroll: list.scrollWidth - list.clientWidth,
            lastLeft: +cell.left.toFixed(1), lastRight: +cell.right.toFixed(1),
            boxLeft: +box.left.toFixed(1), boxRight: +box.right.toFixed(1),
            fullyVisible: cell.right <= box.right + 0.5 && cell.left >= box.left - 0.5,
            hitChain: chain,
            centreOwned: Boolean(hit && (hit === last || last.contains(hit) || hit.contains(last)))};
}
"""

TABLE_SCROLLER = ".task-list[data-layout='table']"


def settle_page_at_its_end(page: Page) -> None:
    """Wheel the page to its end, with real input.

    The shell fixes navigation chrome over the outlet at a narrow width and pays
    for it with bottom clearance on the outlet, so a scroller's last row is
    reachable - but only once the page itself has moved. One wheel past the end
    is the same bounded action in every cell: it saturates at the document's own
    end, so it cannot seek a passing state, and the hit test that follows stays
    falsifiable.
    """
    page.mouse.wheel(0, 2000)
    page.wait_for_timeout(200)


def assert_table_reaches_its_last_cell(sample: Mapping[str, object], where: str) -> None:
    assert sample["maxScroll"] > 0, (
        f"{where}: the table does not overflow horizontally, so its scroller has nothing to reach; "
        f"measurement={sample}"
    )
    assert sample["scrollLeft"] >= sample["maxScroll"] - 1, (
        f"{where}: the scroller did not reach its end; scrollLeft={sample['scrollLeft']}, "
        f"maxScroll={sample['maxScroll']}"
    )
    assert sample["fullyVisible"], (
        f"{where}: the last cell is still clipped by the scroller box; scrollLeft={sample['scrollLeft']}, "
        f"cell=[{sample['lastLeft']}, {sample['lastRight']}], box=[{sample['boxLeft']}, {sample['boxRight']}]"
    )
    assert sample["centreOwned"], (
        f"{where}: the last cell does not answer elementFromPoint at its own centre; "
        f"scrollLeft={sample['scrollLeft']}, cell=[{sample['lastLeft']}, {sample['lastRight']}], "
        f"hit={sample.get('hitChain')}"
    )


def test_dense_table_overflow_reaches_its_last_cell_by_wheel(page: Page) -> None:
    """The dense-table horizontal scroller reaches its last cell with real wheel input.

    At a 320px viewport the table overflows; a reader scrolls it horizontally. The
    case drives ``page.mouse.wheel`` with a horizontal delta over the scroller and
    asserts the last cell becomes fully visible and hit-testable at its centre.
    """
    fresh = open_page(page.context, {"width": 320, "height": 800})
    try:
        open_dashboard(fresh)
        start = fresh.evaluate(TABLE_PROBE)
        assert not start.get("missing"), "the dashboard did not render the table layout"
        assert start["maxScroll"] > 0, (
            f"the dense table does not overflow at this width, so the case proves nothing; measurement={start}"
        )
        assert start["scrollLeft"] == 0, (
            f"the scroller did not start at its origin; scrollLeft={start['scrollLeft']}"
        )
        fresh.locator(TABLE_SCROLLER).scroll_into_view_if_needed()
        box = fresh.locator(TABLE_SCROLLER).bounding_box()
        fresh.mouse.move(box["x"] + 60, box["y"] + 20)
        for _ in range(8):
            fresh.mouse.wheel(300, 0)
            fresh.wait_for_timeout(60)
        settle_page_at_its_end(fresh)
        reached = fresh.evaluate(TABLE_PROBE)
    finally:
        fresh.close()
    assert reached["scrollLeft"] > start["scrollLeft"], (
        f"wheel input did not move the horizontal scroller; before={start['scrollLeft']}, "
        f"after={reached['scrollLeft']}"
    )
    assert_table_reaches_its_last_cell(reached, "dense table by wheel at 320px")


def test_touch_drag_reaches_the_end_of_the_dense_table(page: Page) -> None:
    """A touch drag reaches the end of the dense-table horizontal scroller.

    Playwright's mouse API does not scroll a touch-style overflow container, so
    the case dispatches real touch gestures through CDP, with touch emulation
    enabled first. It asserts the same observable contract as the wheel case.

    A swipe is bounded by the viewport it starts in, so no single swipe can be
    dispatched to any distance the reader likes; and a synthesized gesture is
    consumed by the compositor, which under load takes fewer of the dispatched
    moves than it is offered. The gesture is therefore the one a reader actually
    makes: swipe, then swipe again to carry on. Each swipe re-anchors at the
    scroller's own current right edge and ends past its left edge, so the case
    is bounded by the scroller's geometry rather than by a step count or a step
    size, and cannot fail on how far the dispatcher happened to get. That it
    really moved is still witnessed, by comparing the two ends.
    """
    fresh = open_page(page.context, {"width": 320, "height": 800})
    try:
        open_dashboard(fresh)
        start = fresh.evaluate(TABLE_PROBE)
        assert not start.get("missing"), "the dashboard did not render the table layout"
        assert start["maxScroll"] > 0, (
            f"the dense table does not overflow at this width, so the case proves nothing; measurement={start}"
        )
        fresh.locator(TABLE_SCROLLER).evaluate("node => { node.scrollLeft = 0; }")
        fresh.wait_for_timeout(200)
        origin = fresh.evaluate(TABLE_PROBE)
        assert origin["scrollLeft"] == 0, f"the scroller did not return to its origin; {origin}"

        fresh.locator(TABLE_SCROLLER).scroll_into_view_if_needed()
        box = fresh.locator(TABLE_SCROLLER).bounding_box()
        cdp: CDPSession = fresh.context.new_cdp_session(fresh)
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})

        def swipe() -> None:
            start_x, start_y = box["x"] + box["width"] - 10, box["y"] + 20
            end_x = box["x"] - 10
            cdp.send("Input.dispatchTouchEvent", {
                "type": "touchStart", "touchPoints": [{"x": start_x, "y": start_y}],
            })
            steps = 20
            for step in range(1, steps + 1):
                cdp.send("Input.dispatchTouchEvent", {
                    "type": "touchMove",
                    "touchPoints": [{"x": start_x - (start_x - end_x) * step / steps, "y": start_y}],
                })
                fresh.wait_for_timeout(10)
            cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            fresh.wait_for_timeout(300)

        swipe()
        swipe()
        fresh.wait_for_timeout(300)
        settle_page_at_its_end(fresh)
        reached = fresh.evaluate(TABLE_PROBE)
    finally:
        fresh.close()
    assert reached["scrollLeft"] > origin["scrollLeft"], (
        f"the touch drag did not move the horizontal scroller; before={origin['scrollLeft']}, "
        f"after={reached['scrollLeft']}"
    )
    assert_table_reaches_its_last_cell(reached, "dense table by touch drag at 320px")


# ── the create-task snapshot panel ────────────────────────────────────────────


def test_pinned_create_task_panel_keeps_its_content_reachable(page: Page) -> None:
    """The create-task snapshot panel must not be buried under the shell header.

    The panel pins at its own viewport-relative offset - one rem, the same
    reference point as the shell header's own padding - and unlike a sticky
    surface that is *meant* to slide under the translucent bar, it is a form
    surface a reader has to read. Under a 200% text-only resize and at a
    short-but-wide viewport the two layers overlap and the panel's own label is
    painted over completely and is no longer hit-testable. Its guard is a
    viewport-width media query, which fires in neither condition.

    Every cell records the scroll state it measured in. A cell whose page is too
    short to reach the panel's sticky offset proves nothing and says so; a cell
    where the panel pins asserts that each control and each run of its own text
    still answers ``elementFromPoint`` at its own centre, or reports exactly
    where it was measured.
    """
    cells = (
        ("1280x900 at root 16px", {"width": 1280, "height": 900}, INITIAL_ROOT_PX),
        ("1280x900 at root 32px", {"width": 1280, "height": 900}, TEXT_ZOOM_ROOT_PX),
        ("1280x400 at root 16px", {"width": 1280, "height": 400}, INITIAL_ROOT_PX),
    )
    failures: list[str] = []
    for name, viewport, root_px in cells:
        fresh = open_page(page.context, viewport, root_px=root_px)
        try:
            mount_scenario(fresh, controlled_scenario(session=ADMIN_AUTH))
            quiet_notices(fresh)
            fresh.goto(f"{ORIGIN}/compute/create_task?task_type={CONTROLLED_RUNNER_NAME}")
            fresh.wait_for_timeout(1200)
            reached = wheel_scroll(fresh, 640, 300, 400, 30)
            sample = fresh.evaluate(STICKY_PROBE, ".ct-snapshot-panel")
        finally:
            fresh.close()
        assert not sample.get("missing"), f"{name}: the create-task page rendered no snapshot panel"
        assert sample["scrollable"] > 0 and reached > 0, (
            f"{name}: nothing scrolled, so the pinning state was never reached; "
            f"scrollY={sample['scrollY']}, scrollable={sample['scrollable']}"
        )
        if not sample["pinnedAtOffset"]:
            # The page is too short for the panel to reach its own sticky offset,
            # so the two layers never compete. This is the honest witness for the
            # cell, not a pass.
            continue
        controls = reachable_controls(sample)
        assert controls, f"{name}: the pinned panel holds no controls"
        unreachable = [node for node in controls if not node["reachable"]]
        offenders = [*unreachable, *unreachable_content(sample)]
        if offenders:
            failures.append(
                f"{name}: scrollY={sample['scrollY']}, headerBottom={sample['headerBottom']}, "
                f"pinnedTop={sample['pinned']['top']}, occluded={offenders}"
            )
    assert not failures, (
        "the pinned create-task snapshot panel is buried under the shell header; each cell below "
        "reports the scroll position it measured in:\n" + "\n".join(failures)
    )
