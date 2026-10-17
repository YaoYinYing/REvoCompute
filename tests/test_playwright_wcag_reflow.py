# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for WCAG text-spacing (1.4.12) and text-resize (1.4.4).

Both criteria drive the built production bundle through the deterministic fixture
harness and assert an observable geometry invariant — the document element never
scrolls horizontally, and no element crosses the viewport edge without an
ancestor that scrolls or clips it. A case names class selectors only to locate
the element under test; it asserts no class name, token, pixel literal, or
translated string.

The cases fail for different reasons, which is why they are separate:

* 1.4.12 text spacing applied with the criterion's own metric values, at 320px.
  The rem media queries *do* fire here (the root font is still 16px); an
  unbreakable run inside the hero simply outgrows its column.
* The same property one step narrower, 280px, where the hero column is tighter.
* 1.4.12 text spacing raised on the home's own heading runs. The two cases above
  widen text by the criterion's fixed margins only, so whether they observe an
  unwrapped heading depends on which face the shipped font stack resolves to;
  this one raises the spacing on the runs themselves and asserts that each run
  had to break, which holds on any face.
* 1.4.4 text-only resize to 200% doubles the root font while the layout viewport
  stays 1280px. Every profile.css collapse rule used to live in a
  `@media (max-width: Nrem)` block, and a rem in a *media* query resolves against
  the initial 16px font, so those queries never fired and the multi-column
  profile layout stayed multi-column inside a text-doubled viewport.
"""

from __future__ import annotations

from dataclasses import replace
import json

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import (
    WorkspaceCapability,
    WorkspaceStep,
    controlled_runner,
    controlled_scenario,
    mount_scenario,
    runner_scenario,
)

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"

# The WCAG 1.4.12 text-spacing override: the metric values the criterion names.
TEXT_SPACING = (
    "*{line-height:1.5 !important;letter-spacing:0.12em !important;"
    "word-spacing:0.16em !important;}"
    "p{margin-bottom:2em !important;}"
)
# The criterion's own metric values, applied again with a stronger letter-spacing
# on the home's heading runs. A user may raise text spacing past the criterion's
# minimum, and doing so here makes the run that outgrows its column a property of
# the condition rather than of whichever face the shipped stack resolves to.
WIDER_HEADING_SPACING = "h2,blockquote{letter-spacing:0.5em !important;}"
# 200% text-only resize of a 16px root, with the layout viewport left at 1280px.
TEXT_ZOOM_ROOT_PX = 32


def _install_condition(page: Page, css: str) -> None:
    """Apply a condition stylesheet that survives navigation.

    ``add_style_tag`` only covers the current document, so the rule is also
    registered as an init script that re-injects it into every document the
    page loads.
    """
    page.add_init_script(
        "(function(){var css=%s;function inject(){var s=document.createElement('style');"
        "s.textContent=css;(document.head||document.documentElement).appendChild(s);}"
        "if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',inject,{once:true});}"
        "else{inject();}})();" % json.dumps(css)
    )
    page.add_style_tag(content=css)


def _install_profile_responses(page: Page) -> None:
    """Serve the profile's metrics and credit projections the router does not declare."""
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


# Every element whose right edge crosses the viewport, with the nearest ancestor
# that scrolls or clips it. The property the criteria name: content may only
# leave the viewport when an ancestor scrolls or clips it.
UNCONTAINED_OVERFLOW = """
() => {
  const vw = document.documentElement.clientWidth;
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    if (r.right <= vw + 1) continue;
    let anc = el.parentElement, contained = false;
    while (anc) {
      const a = getComputedStyle(anc);
      if (['hidden', 'auto', 'scroll', 'clip'].includes(a.overflowX)) { contained = true; break; }
      anc = anc.parentElement;
    }
    if (!contained) out.push({
      tag: el.tagName.toLowerCase(),
      cls: typeof el.className === 'string' ? el.className.slice(0, 80) : '',
      right: Math.round(r.right),
    });
  }
  return out;
}
"""


def _horizontal_scroll(page: Page) -> dict[str, int]:
    return page.evaluate(
        "() => { const de = document.documentElement;"
        " return {scrollWidth: de.scrollWidth, clientWidth: de.clientWidth,"
        " delta: de.scrollWidth - de.clientWidth}; }"
    )


def _assert_no_horizontal_page_scroll(page: Page, context: str) -> None:
    """The document element must not exceed its client width, and nothing may
    cross the viewport edge unclipped."""
    geometry = _horizontal_scroll(page)
    uncontained = page.evaluate(UNCONTAINED_OVERFLOW)
    assert geometry["scrollWidth"] <= geometry["clientWidth"], (
        f"{context}: document scrolls horizontally by {geometry['delta']}px "
        f"(scrollWidth={geometry['scrollWidth']}, clientWidth={geometry['clientWidth']}); "
        f"unclipped overflow: {uncontained}"
    )
    assert uncontained == [], f"{context}: content crosses the viewport unclipped: {uncontained}"


# The line count of the element's own text. A wrapped line sits on its own y, so
# counting the distinct y values of the text's client rectangles counts lines;
# counting the rectangles themselves would count the split inline boxes of one
# line, which reads a single line as more than one.
TEXT_LINES = """
el => {
  const range = document.createRange();
  range.selectNodeContents(el);
  return new Set([...range.getClientRects()].map(b => Math.round(b.top))).size;
}
"""


# The natural one-line width of an element's text, against the page width it has
# to fit: the witness a case is not vacuous, because it shows the run really is
# wider than the box the layout gives it. The probe re-applies the computed
# spacing as an *important* inline style, because the condition stylesheets are
# important too and the probe would otherwise measure the criterion's own spacing
# rather than the raised one a case installs.
UNWRAPPED_RUN = """
node => {
  const cs = getComputedStyle(node);
  const span = document.createElement('span');
  span.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;left:-9999px;';
  span.style.setProperty('font', cs.font);
  span.style.setProperty('letter-spacing', cs.letterSpacing, 'important');
  span.style.setProperty('word-spacing', cs.wordSpacing, 'important');
  span.textContent = node.textContent.trim().replace(/\\s+/g, ' ');
  document.body.appendChild(span);
  const unwrapped = span.getBoundingClientRect().width;
  span.remove();
  return {unwrapped: Math.round(unwrapped), page: document.documentElement.clientWidth};
}
"""


def test_home_page_does_not_scroll_horizontally_under_text_spacing(page: Page) -> None:
    """WCAG 1.4.12: at 320px with the text-spacing override the home document must
    not scroll horizontally.

    The root font is 16px here, so the home's rem media queries still apply and
    the layout is the same one 320px users already get — the only new input is
    the user's spacing override widening the hero's unbreakable content.
    """
    page.set_viewport_size({"width": 320, "height": 640})
    mount_scenario(page, controlled_scenario())
    _install_condition(page, TEXT_SPACING)
    page.goto(f"{ORIGIN}/")

    hero = page.locator(".home-hero")
    expect(hero).to_be_visible()
    # Non-vacuous: the hero's own content is on screen, in the column that overflowed.
    expect(page.locator(".home-hero h1")).to_be_visible()
    expect(page.locator(".home-actions a").first).to_be_visible()
    page.evaluate("() => document.fonts.ready")

    _assert_no_horizontal_page_scroll(page, "home @320px with 1.4.12 spacing")


def test_home_page_does_not_scroll_horizontally_under_text_spacing_narrower(page: Page) -> None:
    """The same property one step narrower, where the hero column is tighter still."""
    page.set_viewport_size({"width": 280, "height": 640})
    mount_scenario(page, controlled_scenario())
    _install_condition(page, TEXT_SPACING)
    page.goto(f"{ORIGIN}/")

    expect(page.locator(".home-hero")).to_be_visible()
    expect(page.locator(".home-hero h1")).to_be_visible()
    page.evaluate("() => document.fonts.ready")

    _assert_no_horizontal_page_scroll(page, "home @280px with 1.4.12 spacing")


# Home heading runs that are the widest child of a flex or grid item: an
# unbreakable run inside one is the item's floor, so a heading that may not break
# pushes its whole item past the page.
HOME_HEADING_RUNS = (".home-products h2", ".home-closing blockquote")


def test_home_heading_runs_break_under_widened_text_spacing(page: Page) -> None:
    """WCAG 1.4.12: with the text-spacing override raised on the home's heading
    runs, the home document must not scroll horizontally.

    Each named run is a heading in a flex or grid item it is the widest child of,
    so a run that may not break becomes the item's floor and pushes the page wide.
    The two spacing cases above widen text by the criterion's fixed margins only,
    so whether they see an unwrapped heading depends on which face the shipped
    stack resolves to; raising the spacing on these runs makes that independent of
    the host's fonts.
    """
    page.set_viewport_size({"width": 280, "height": 640})
    mount_scenario(page, controlled_scenario())
    _install_condition(page, TEXT_SPACING + WIDER_HEADING_SPACING)
    page.goto(f"{ORIGIN}/")

    expect(page.locator(".home-products")).to_be_visible()
    page.evaluate("() => document.fonts.ready")

    for selector in HOME_HEADING_RUNS:
        runs = page.locator(selector)
        count = runs.count()
        # Non-vacuous: the run this case names is present on the page.
        assert count > 0, f"home heading run {selector}: the page carries no such run"
        for index in range(count):
            run = runs.nth(index)
            expect(run).to_be_visible()
            measured = run.evaluate(UNWRAPPED_RUN)
            # Non-vacuous: the run does not fit the page on one line, so it must
            # break, and the page can only stay inside the viewport if it does.
            assert measured["unwrapped"] > measured["page"], (
                f"home heading run {selector}[{index}]: {measured['unwrapped']}px unwrapped fits "
                f"the {measured['page']}px page, so this case would pass without any wrap"
            )

    _assert_no_horizontal_page_scroll(page, "home @280px with widened 1.4.12 spacing")


# Account routes whose content is the widest of the page: the account form's two
# columns and the metrics header's segmented control are the two that used to
# widen the document under text-only resize. Each section is its own address.
ACCOUNT_ROUTES = (
    ("account", "/compute/profile"),
    ("security", "/compute/account/security"),
    ("api-key", "/compute/account/api-key"),
    ("runner-access", "/compute/account/runner-access"),
    ("gpu-credits", "/compute/account/gpu-credits"),
    ("metrics", "/compute/account/metrics"),
)


@pytest.mark.parametrize("section,route", ACCOUNT_ROUTES)
def test_account_does_not_scroll_horizontally_under_text_only_resize(page: Page, section: str, route: str) -> None:
    """WCAG 1.4.4: at 200% text-only resize of a 1280px viewport the account
    document must not scroll horizontally on any of its sections."""
    page.set_viewport_size({"width": 1280, "height": 900})
    mount_scenario(page, controlled_scenario())
    _install_profile_responses(page)
    _install_condition(page, f"html{{font-size:{TEXT_ZOOM_ROOT_PX}px !important;}}")
    page.goto(f"{ORIGIN}{route}")

    expect(page.locator(f'[data-section="{section}"]')).to_be_visible()
    page.evaluate("() => document.fonts.ready")

    _assert_no_horizontal_page_scroll(page, f"{route} @200% text-only resize")


def test_profile_account_form_stays_behind_its_own_edge_at_text_only_resize(page: Page) -> None:
    """The account form's two-column grid is the element that most exceeded the
    viewport; at 200% text-only resize it must fit the width the page gives it.

    Asserted against the section that contains it, not a literal width: the
    columns are a behaviour ("the form does not push past its container"), and
    it is the container's own laid-out box the columns must respect.
    """
    page.set_viewport_size({"width": 1280, "height": 900})
    mount_scenario(page, controlled_scenario())
    _install_profile_responses(page)
    _install_condition(page, f"html{{font-size:{TEXT_ZOOM_ROOT_PX}px !important;}}")
    page.goto(f"{ORIGIN}/compute/profile")

    columns = page.locator(".account-form .form-columns")
    expect(columns).to_be_visible()
    page.evaluate("() => document.fonts.ready")
    overhang = columns.evaluate(
        """node => {
             const section = node.closest('.account-section');
             return Math.round(node.getBoundingClientRect().right - section.getBoundingClientRect().right);
           }"""
    )
    assert overhang <= 1, f"the account form columns overhang their section by {overhang}px"


# --- Route mastheads: a roll-up wider than the room the row has left --------

# The runner catalog's readiness badge is one label on the masthead row beside the
# page identity. Under the criterion's own spacing that label is wider than the
# box the row has left for it at 280px, so the run is driven further past the fit
# by widening its tracking, which reproduces the same defect on the dev host's
# narrow face and not only in CI's wider one. The create-task component headings
# are the same class of run under the 1.4.4 case below: a name the layout may not
# widen past the page it was given.
BADGE_RUN_SPACING = TEXT_SPACING + ".readiness-state{letter-spacing:.3em !important;}"
# The 200% text-only resize of the create-task component headings. A root font
# that doubles reaches a manifest-length capability name the way a reader's own
# resize does; the canonical fixture's single-word names are too short for the
# resize alone to overflow a desktop-measure track, so the case below supplies
# names of the length a real task manifest declares.
TITLE_RUN_ZOOM = (
    f"html{{font-size:{TEXT_ZOOM_ROOT_PX}px !important;}}"
    ".ct-component-title{letter-spacing:.4em !important;}"
)


def _manifest_length_names_scenario():
    """The canonical Runner with capability names of the length a manifest declares.

    Real task manifests name capabilities descriptively ("Alignment and
    references", "AlphaFold 3 JSON input"), and the fixture harness projects
    whatever the manifest declares. The 1.4.4 case is about a server-supplied name
    of that length yielding to its column at 200% text-only resize.
    """
    return runner_scenario(replace(controlled_runner(), workspace_steps=(
        WorkspaceStep(
            id="input",
            title="Provide input",
            description="Choose one source.",
            capabilities=(
                WorkspaceCapability("files", "source_files", "Files", "Upload FASTA."),
                WorkspaceCapability(
                    "sequence", "sequence_editor",
                    "Alignment and residue-level sequence validation",
                    "Paste FASTA.",
                    (("role", "sequence"),),
                ),
            ),
        ),
        WorkspaceStep(
            id="settings",
            title="Settings",
            description="Configure the run.",
            capabilities=(WorkspaceCapability("parameters", "parameters", "Parameters", "Method controls."),),
        ),
        WorkspaceStep(
            id="review",
            title="Review",
            description="Check the snapshot.",
            capabilities=(WorkspaceCapability("review", "review", "Review", "Submission summary."),),
        ),
    )))


def test_runner_catalog_masthead_keeps_its_rollup_inside_the_viewport(page: Page) -> None:
    """WCAG 1.4.12: the runner catalog's readiness badge sits beside the page
    identity in the masthead. Under the text-spacing override, with the badge's
    run widened past the room the row has, the label must yield to the box it is
    given rather than carry the document past the viewport.

    The witness is that the label really is too wide for its own box, so the case
    cannot pass merely because the host's face is narrow or the run short.
    """
    page.set_viewport_size({"width": 280, "height": 640})
    mount_scenario(page, controlled_scenario())
    _install_condition(page, BADGE_RUN_SPACING)
    page.goto(f"{ORIGIN}/runners")

    expect(page.locator(".runners-page")).to_be_visible()
    head = page.locator(".page-heading")
    badge = head.locator(".readiness-state")
    expect(badge).to_be_visible()
    page.evaluate("() => document.fonts.ready")

    witness = {
        "badge": badge.evaluate("el => Math.round(el.getBoundingClientRect().width)"),
        "run": badge.evaluate(UNWRAPPED_RUN)["unwrapped"],
        "lines": badge.evaluate(TEXT_LINES),
    }
    assert witness["run"] > witness["badge"], (
        f"not exercised: the badge is already showing its label on one line "
        f"(run={witness['run']}, badge={witness['badge']})"
    )

    _assert_no_horizontal_page_scroll(page, "runner catalog @280px with 1.4.12 spacing")


def test_runner_catalog_masthead_keeps_its_label_on_one_line_when_it_fits(page: Page) -> None:
    """The reading the fix must not change: under the same spacing, with room in
    the row, the readiness label stays on one line on the identity's own row —
    the two words are not broken apart and the roll-up is not sent to its own
    row when it fits beside the identity.

    The witness is the same measurement's other half: here the unwrapped label is
    no wider than the box, so the one-line reading is the expected one. The width
    is the first one at which the shipped masthead row gives the roll-up its full
    label: #88 sets the runner identity in a 38px display face and the roll-up in
    a 14px system face, so the row's remaining measure passes the label's own run
    between 1440px and 1600px. Below that the label wraps, which the sibling case
    above is the one that asserts.
    """
    page.set_viewport_size({"width": 1600, "height": 640})
    mount_scenario(page, controlled_scenario())
    _install_condition(page, BADGE_RUN_SPACING)
    page.goto(f"{ORIGIN}/runners")

    expect(page.locator(".runners-page")).to_be_visible()
    head = page.locator(".page-heading")
    badge = head.locator(".readiness-state")
    expect(badge).to_be_visible()
    page.evaluate("() => document.fonts.ready")

    witness = {
        "badge": badge.evaluate("el => Math.round(el.getBoundingClientRect().width)"),
        "run": badge.evaluate(UNWRAPPED_RUN)["unwrapped"],
    }
    assert witness["run"] <= witness["badge"], (
        f"not exercised: the label does not fit the box at this width "
        f"(run={witness['run']}, badge={witness['badge']})"
    )
    assert badge.evaluate(TEXT_LINES) == 1, (
        "the readiness label no longer reads on one line where it fits "
        f"(run={witness['run']}, badge={witness['badge']})"
    )
    same_row = head.evaluate(
        "el => { const identity = el.firstElementChild, rollup = el.lastElementChild;"
        " return rollup.getBoundingClientRect().top < identity.getBoundingClientRect().bottom; }"
    )
    assert same_row, "the roll-up no longer sits on the identity's row where it fits"


def test_create_task_component_headings_stay_inside_their_step(page: Page) -> None:
    """WCAG 1.4.4: at 200% text-only resize the create-task component headings —
    server-supplied names from the owning Runner's task manifest — must wrap
    within the step column rather than widen it.

    Each heading sits in the step's second track; the witness is that its label
    is wider on one line than the box that box can hold, so what is asserted is
    the heading yielding to its track, not an empty measurement.
    """
    page.set_viewport_size({"width": 320, "height": 900})
    mount_scenario(page, _manifest_length_names_scenario())
    _install_condition(page, TITLE_RUN_ZOOM)
    page.goto(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")

    expect(page.locator(".ct-workbench")).to_be_visible()
    titles = page.locator(".ct-component-title")
    titles.first.wait_for()
    page.evaluate("() => document.fonts.ready")

    measured = []
    for index in range(titles.count()):
        title = titles.nth(index)
        measured.append({
            "box": title.evaluate("el => Math.round(el.getBoundingClientRect().width)"),
            "run": title.evaluate(UNWRAPPED_RUN)["unwrapped"],
            "lines": title.evaluate(TEXT_LINES),
        })
    assert measured, "the sequence_demo workspace declares no component headings"
    assert any(row["run"] > row["box"] for row in measured), (
        f"not exercised: every heading's label fits its track ({measured})"
    )

    _assert_no_horizontal_page_scroll(page, "create task @320px with 200% text-only resize")


def test_create_task_component_headings_keep_their_names_readable(page: Page) -> None:
    """The other half of the 1.4.4 case: at the initial text size the same
    server-supplied component names still read on one line, so the column that
    now yields to its track has not started breaking names that fit.
    """
    page.set_viewport_size({"width": 768, "height": 900})
    mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")

    expect(page.locator(".ct-workbench")).to_be_visible()
    titles = page.locator(".ct-component-title")
    titles.first.wait_for()
    page.evaluate("() => document.fonts.ready")

    measured = []
    for index in range(titles.count()):
        title = titles.nth(index)
        measured.append({
            "box": title.evaluate("el => Math.round(el.getBoundingClientRect().width)"),
            "run": title.evaluate(UNWRAPPED_RUN)["unwrapped"],
            "lines": title.evaluate(TEXT_LINES),
        })
    assert measured, "the sequence_demo workspace declares no component headings"
    assert all(row["run"] <= row["box"] for row in measured), (
        f"not exercised: a heading's label already exceeds its track ({measured})"
    )
    assert all(row["lines"] == 1 for row in measured), (
        f"a component name that fits its track is being broken ({measured})"
    )
