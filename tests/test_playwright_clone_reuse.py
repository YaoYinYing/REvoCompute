# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser regressions for Clone & Reuse and the sticky submit rail.

Both surfaces keep the reader's keyboard position when the clone plan cannot be
created, and the focused last parameter stays clear of the sticky rail at the
narrow widths where it overlays the form. These drive the built frontend bundle
against the fixture API, so ``document.activeElement`` and real layout geometry
are the assertions rather than a DOM imitation.
"""

from __future__ import annotations

import copy
import re

from playwright.sync_api import Page, expect
import pytest

from test_playwright_application import ORIGIN, TASK_ID, _detail, _install_app

pytestmark = pytest.mark.browser

CLONE_PLAN = re.compile(rf"{re.escape(ORIGIN)}/compute/api/tasks/{TASK_ID}/clone-plan$")


def _fail_clone_plan(page: Page) -> None:
    """Answer the one write the surfaces issue with a bounded server refusal."""
    page.route(CLONE_PLAN, lambda route: route.fulfill(status=503, json={"error": "clone plan unavailable"}))


def test_dashboard_failed_clone_returns_focus_to_the_clone_control(page: Page) -> None:
    _install_app(page)
    _fail_clone_plan(page)
    page.goto(f"{ORIGIN}/compute/dashboard")
    clone = page.get_by_role("button", name="Clone & reuse", exact=True)
    expect(clone).to_be_visible()
    clone.focus()
    page.keyboard.press("Enter")

    # The localized, polite notice is kept; the control that failed is enabled
    # again and is where the keyboard was before the request.
    expect(page.locator(".app-notices")).to_contain_text("Could not prepare a clone")
    expect(clone).to_be_enabled()
    expect(clone).to_be_focused()


def test_result_failed_clone_returns_focus_to_the_clone_control(page: Page) -> None:
    _install_app(page)
    _fail_clone_plan(page)
    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")
    clone = page.get_by_role("button", name="Clone & reuse", exact=True)
    expect(clone).to_be_visible()
    clone.focus()
    page.keyboard.press("Enter")

    status = page.locator(".result-status")
    expect(status).to_contain_text("Could not prepare a clone")
    expect(clone).to_be_enabled()
    expect(clone).to_be_focused()


def _parameter_detail(count: int, required: int = 0) -> tuple[dict, dict]:
    """Return a workbench contract with ``count`` parameters, the first ``required`` required.

    An empty required field renders a validation row, which grows the sticky
    rail after it mounts: the state the constant reservation missed.
    """
    detail = copy.deepcopy(_detail())
    detail["parameters_url"] = "/compute/api/task-parameters/sequence_demo"
    names = [f"p{index}" for index in range(1, count + 1)]
    properties = {
        name: {"type": "integer", "title": f"Parameter {name[1:]}"}
        for name in names
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": names[:required],
    }
    return detail, schema


@pytest.mark.parametrize(
    ("width", "height", "count", "required"),
    [
        (834, 560, 4, 0),
        (390, 520, 5, 0),
        (1440, 900, 4, 0),
        (834, 560, 5, 1),
        (834, 560, 5, 2),
        (834, 560, 5, 3),
        (390, 520, 5, 2),
    ],
    ids=[
        "834x560-4",
        "390x520-5",
        "1440x900-4",
        "834x560-5-1-required",
        "834x560-5-2-required",
        "834x560-5-3-required",
        "390x520-5-2-required",
    ],
)
def test_focused_last_parameter_is_visible_above_the_sticky_rail(
    page: Page, width: int, height: int, count: int, required: int
) -> None:
    _install_app(page)
    detail, schema = _parameter_detail(count, required)
    page.route(
        f"{ORIGIN}/compute/api/types/sequence_demo",
        lambda route: route.fulfill(json=detail),
    )
    page.route(
        f"{ORIGIN}/compute/api/task-parameters/sequence_demo",
        lambda route: route.fulfill(json=schema),
    )
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{ORIGIN}/compute/create_task?task_type=sequence_demo")
    expect(page.locator(".ct-workbench")).to_be_visible()
    expect(page.locator("[data-ct-parameter]")).to_have_count(count)
    if required:
        # The empty required fields are exactly what makes the rail taller than
        # the old constant reservation: the rows are the fixture's premise. The
        # one extra row is the fixture's own required sequence input.
        expect(page.locator(".ct-validation-row.error")).to_have_count(required + 1)

    # The reservation follows the rail's measured height, so wait for it to
    # catch up with the rows before positioning a field: measuring a stale
    # reservation would test the observation's timing, not the layout.
    page.wait_for_function(
        """() => {
            const rail = document.querySelector('.ct-snapshot-panel');
            const field = document.querySelector('[data-ct-parameter="p1"]');
            return parseFloat(getComputedStyle(field).scrollMarginBottom) >= rail.getBoundingClientRect().height;
        }""",
        timeout=15_000,
    )

    # Put the last field just under the rail's lower edge while it is still fully
    # inside the viewport. This is the state that used to be left un-scrolled:
    # the browser sees a visible field and only moves it when the control itself
    # reserves the rail's height.
    page.evaluate(
        """(count) => {
            const rail = document.querySelector('.ct-snapshot-panel').getBoundingClientRect();
            const field = document.querySelector(`[data-ct-parameter="p${count}"]`);
            scrollTo(0, field.getBoundingClientRect().top + scrollY - (rail.top + 8));
        }""",
        count,
    )
    page.locator(f'[data-ct-parameter="p{count - 1}"]').focus()
    page.keyboard.press("Tab")
    last = page.locator(f'[data-ct-parameter="p{count}"]')
    expect(last).to_be_focused()

    rail = page.locator(".ct-snapshot-panel").bounding_box()
    field = last.bounding_box()
    assert rail is not None and field is not None
    print(
        f"viewport={width}x{height} parameters={count} required={required} "
        f"focused={field['y']:.1f}..{field['y'] + field['height']:.1f} "
        f"rail={rail['y']:.1f}..{rail['y'] + rail['height']:.1f}"
    )
    # The focused field is inside the viewport and entirely above the rail that
    # overlays its lower edge.
    assert field["y"] >= 0
    assert field["y"] + field["height"] <= height
    assert field["y"] + field["height"] <= rail["y"]
