# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for the Create Task seed field and its inline dice.

A parameter whose owning schema declares the seed ``x-ui-control`` renders as one
field: an editable value with a dice button inside the field's own edge, a Reset
at the label edge, and the task's own help below. Drawing a seed is an ordinary
edit of that value - the dice writes one integer across the task's declared
generation domain and reports it through the control's own ``input`` event, so
validation, the Task Snapshot, and submission all see the same single edit.

The value distribution is a pure function and is covered directly at
``frontend/tests/create-task-contract.test.ts``. This file drives the built
application through ``tests/frontend_fixtures/`` and asserts the behavior a
reader meets.
"""

from __future__ import annotations

from dataclasses import replace
import re

from playwright.sync_api import Locator, Page, expect
import pytest

from frontend_fixtures import ParameterSpec, controlled_runner, mount_scenario, runner_scenario

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"

# Two seed-declaring parameters, one bounded and one open, plus a plain numeric
# parameter that proves the dice is a seed affordance rather than a decoration on
# every number field. ``seed`` mirrors a shipped declaration: an integer with a
# declared default and an inclusive generation range.
SEED_RUNNER = replace(
    controlled_runner(),
    parameters=(
        ParameterSpec.integer(
            "seed", default=3, has_default=True, minimum=1, maximum=6,
            ui_control=(("kind", "seed"),), description="Random seed controlling mini-batch sampling.",
        ),
        ParameterSpec.integer(
            "sampling_seed", minimum=0, ui_control=(("kind", "seed"),),
            description="Random seed for the sampler; the task declares no default.",
        ),
        ParameterSpec.integer("iterations", default=2, has_default=True, minimum=1, maximum=4),
    ),
)

# The minimum touch target every control in this repository carries.
MIN_TARGET_PX = 44


def _pin_locale(page: Page) -> None:
    """Pin the locale before the bundle boots; copy is baked in as the DOM builds."""
    page.add_init_script("localStorage.setItem('revocompute-locale', 'en')")


def _open_create_task(page: Page) -> None:
    page.goto(f"{ORIGIN}/compute/create_task?task_type={SEED_RUNNER.name}")
    expect(page.locator(".ct-workbench")).to_be_visible()


def _control(page: Page, name: str) -> Locator:
    return page.locator(f'[data-ct-parameter="{name}"]')


def _field(page: Page, name: str) -> Locator:
    """The one parameter field a named parameter owns."""
    return page.locator(".ct-parameter", has=_control(page, name))


def _dice(page: Page, name: str) -> Locator:
    return _field(page, name).locator(".ct-seed")


def _drawn(page: Page, name: str) -> int:
    """The integer the named seed field currently holds."""
    return int(_control(page, name).input_value())


def test_a_seed_parameter_renders_one_field_with_the_dice_inside_it(page: Page) -> None:
    """The dice is part of the value's own control, not a control beside it."""
    _pin_locale(page)
    mount_scenario(page, runner_scenario(SEED_RUNNER))
    _open_create_task(page)

    control, dice = _control(page, "seed"), _dice(page, "seed")
    expect(control).to_have_attribute("type", "number")
    expect(dice).to_be_visible()

    # The dice paints inside the field's own box rather than laying out next to
    # it, which is what makes drawing a seed read as an edit of that value.
    control_box, dice_box = control.bounding_box(), dice.bounding_box()
    assert control_box is not None and dice_box is not None
    assert dice_box["x"] >= control_box["x"] and dice_box["x"] + dice_box["width"] <= control_box["x"] + control_box["width"]
    assert dice_box["y"] >= control_box["y"] and dice_box["y"] + dice_box["height"] <= control_box["y"] + control_box["height"]

    # It is a full touch target and it names the parameter it edits, so the
    # affordance reaches a reader who is not reading the glyph. The parameter is
    # named by the server's own vocabulary; the frame around it is frontend copy.
    assert dice_box["width"] >= MIN_TARGET_PX and dice_box["height"] >= MIN_TARGET_PX, dice_box
    label = dice.get_attribute("aria-label") or ""
    assert "Seed" in label and re.search(r"\S \S", label), label

    # Only the seed-declaring parameters get the affordance.
    expect(page.locator(".ct-seed")).to_have_count(2)
    assert _dice(page, "iterations").count() == 0


def test_the_dice_draws_one_integer_inside_the_declared_generation_domain(page: Page) -> None:
    """Every draw is an edit of the field, and every draw lands inside the range."""
    mount_scenario(page, runner_scenario(SEED_RUNNER))
    _open_create_task(page)

    control, dice = _control(page, "seed"), _dice(page, "seed")
    # A declared range is also the control's own native range, so the drawn value
    # and the hint the spinner projects describe the same domain.
    expect(control).to_have_attribute("min", "1")
    expect(control).to_have_attribute("max", "6")

    drawn: set[int] = set()
    for _ in range(24):
        dice.click()
        value = _drawn(page, "seed")
        assert 1 <= value <= 6, value
        drawn.add(value)
    # One draw does not answer the same value every time, so the field is
    # exercised across its declared domain rather than pinned.
    assert len(drawn) > 1, drawn

    # An open seed draws inside the schema's own valid range, never below it.
    for _ in range(8):
        _dice(page, "sampling_seed").click()
        assert _drawn(page, "sampling_seed") >= 0


def test_a_drawn_seed_is_the_value_the_workbench_submits(page: Page) -> None:
    """Drawing a seed is the edit that reaches the submission."""
    requests = mount_scenario(page, runner_scenario(SEED_RUNNER)).requests
    page.route(f"{ORIGIN}/compute/api/post", lambda route: route.fulfill(status=500, json={"error": "not exercised"}))
    _open_create_task(page)

    page.locator("textarea[aria-label='Protein sequence']").fill(">sample\nACDEFG")
    _dice(page, "seed").click()
    value = _control(page, "seed").input_value()

    page.get_by_role("button", name="Run task", exact=True).click()
    expect(page.locator(".ct-status")).to_contain_text("Submission failed")

    preflight = requests.preflight(SEED_RUNNER.name)[0]
    assert preflight.form_fields()["params[seed]"] == value
    assert str(preflight.workspace_capabilities()["parameters"]["seed"]) == value


def test_reset_restores_the_declared_default_and_is_absent_without_one(page: Page) -> None:
    """Reset returns the value to the task's own default; no default offers none."""
    mount_scenario(page, runner_scenario(SEED_RUNNER))
    _open_create_task(page)

    field = _field(page, "seed")
    expect(field.locator(".ct-control")).to_have_value("3")
    _dice(page, "seed").click()
    reset = field.locator(".ct-reset")
    expect(reset).to_be_visible()
    reset.click()
    expect(field.locator(".ct-control")).to_have_value("3")
    # The help the task owns still reaches the reader below the field.
    expect(field.locator(".ct-help")).to_have_count(1)

    # A parameter the task declares no default for offers no Reset to restore.
    expect(_field(page, "sampling_seed").locator(".ct-reset")).to_have_count(0)


def test_the_dice_is_keyboard_operable_and_keeps_the_field_within_its_cell(page: Page) -> None:
    """A focused dice draws on Enter, and the field fits its cell at every width."""
    mount_scenario(page, runner_scenario(SEED_RUNNER))

    for width in (320, 280):
        page.set_viewport_size({"width": width, "height": 900})
        _open_create_task(page)

        dice = _dice(page, "seed")
        dice.focus()
        assert dice.evaluate("node => node === document.activeElement")
        dice.press("Enter")
        assert 1 <= _drawn(page, "seed") <= 6

        # The dice never leaves the field's own column and the field itself never
        # outgrows it, so the affordance costs no horizontal room beside the value.
        offenders = page.evaluate(
            """() => {
            const grid = document.querySelector('.ct-parameter-grid');
            const out = [];
            for (const field of grid.querySelectorAll(':scope > .ct-parameter')) {
                const cell = field.getBoundingClientRect();
                const control = field.querySelector('.ct-control');
                for (const el of [control, field.querySelector('.ct-seed')]) {
                    if (!el) continue;
                    const box = el.getBoundingClientRect();
                    if (box.left < cell.left - 0.5 || box.right > cell.right + 0.5) out.push(el.className);
                }
            }
            return out;
        }"""
        )
        assert offenders == [], f"a seed field paints past its cell at {width}px: {offenders}"
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
