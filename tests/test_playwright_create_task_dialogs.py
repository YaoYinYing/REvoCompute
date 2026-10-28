# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Create Task dialogs are opaque, contained, and dismissible on every surface.

The example picker, the access-request form, and the replace confirmation are
top-layer dialogs appended beside the view, so they inherit nothing from the
create-task page. This file asserts what a reader meets on all three: an opaque
and legible surface over the page, keyboard containment and Escape dismissal,
a narrow-screen layout that stays inside the viewport, and the same original
behavior the dialogs already state (loading an example edits the form only;
requesting access sends exactly one server-owned ``policy_id``).
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import (
    DemoFileSpec,
    controlled_runner,
    controlled_scenario,
    mount_scenario,
    sequence_demo,
)
from frontend_fixtures.models import AccessState

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
RUNNER = controlled_runner().name


def _pin_theme(page: Page, theme: str) -> None:
    page.add_init_script(f"localStorage.setItem('revocompute-theme', {theme!r})")


def _evidence(page: Page, name: str) -> None:
    """Save a screenshot only when a caller names an evidence directory."""
    directory = os.environ.get("REVOCOMPUTE_UI_EVIDENCE_DIR")
    if not directory:
        return
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=target / f"{name}.png")


def _open_demo(page: Page) -> None:
    page.goto(f"{ORIGIN}/compute/create_task?task_type={RUNNER}")
    expect(page.locator(".ct-workbench")).to_be_visible()
    page.locator("[data-ct-demo-open]").click()
    expect(page.locator("dialog.ct-demo-dialog")).to_be_visible()


def _rgba(value: str) -> tuple[float, float, float, float]:
    """Read a computed CSS colour as channels in 0..1 with its alpha."""
    numbers = [float(part) for part in value[value.index("(") + 1 : value.index(")")].replace("/", " ").replace(",", " ").split()]
    red, green, blue = numbers[:3]
    alpha = numbers[3] if len(numbers) > 3 else 1.0
    return red / 255, green / 255, blue / 255, alpha


def _relative_luminance(red: float, green: float, blue: float) -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def _contrast(foreground: str, background: str) -> float:
    fg = _rgba(foreground)
    bg = _rgba(background)
    lighter, darker = sorted((_relative_luminance(*fg[:3]), _relative_luminance(*bg[:3])), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _dialog_style(page: Page, selector: str) -> dict[str, str]:
    return page.eval_on_selector(
        selector,
        """element => {
            const style = getComputedStyle(element);
            return {
                background: style.backgroundColor,
                color: style.color,
                border: style.borderTopWidth,
                radius: style.borderTopLeftRadius,
                shadow: style.boxShadow,
                maxHeight: style.maxHeight,
                overflow: style.overflowY,
            };
        }""",
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_example_picker_is_opaque_legible_and_focus_contained(page: Page, theme: str) -> None:
    """The picker inherits the create-task palette even beside the page."""
    _pin_theme(page, theme)
    mount_scenario(page, controlled_scenario().with_demos([sequence_demo()]))
    _open_demo(page)

    dialog = page.locator("dialog.ct-demo-dialog")
    style = _dialog_style(page, "dialog.ct-demo-dialog")
    background = _rgba(style["background"])
    assert background[3] == pytest.approx(1.0), f"dialog surface is not opaque: {style['background']}"
    assert _contrast(style["color"], style["background"]) >= 4.5, style
    assert float(style["border"].removesuffix("px")) >= 1, style
    assert float(style["radius"].removesuffix("px")) > 0, style
    assert style["shadow"] != "none", style
    assert style["overflow"] in {"auto", "scroll"}, style

    # The dialog is the top layer over the page it was opened from.
    rect = dialog.bounding_box()
    assert rect is not None
    assert rect["width"] > 300 and rect["height"] > 100
    top = page.evaluate(
        """selector => {
            const dialog = document.querySelector(selector);
            const box = dialog.getBoundingClientRect();
            return dialog.contains(document.elementFromPoint(box.left + box.width / 2, box.top + 10));
        }""",
        "dialog.ct-demo-dialog",
    )
    assert top is True
    _evidence(page, f"demo-picker-{theme}")

    # Keyboard focus reaches no control outside the modal. Chromium parks focus
    # on the document body for one step when the cycle wraps, then re-enters, so
    # the assertion is that no interactive element outside the dialog is reached.
    for _ in range(16):
        page.keyboard.press("Tab")
        assert page.evaluate(
            """() => {
                const active = document.activeElement;
                if (!active) return false;
                const interactive = active.matches('button, a, input, select, textarea, [tabindex]');
                return !interactive || active.closest('dialog.ct-demo-dialog') !== null;
            }"""
        ), "keyboard focus escaped the modal dialog to a page control"
    page.keyboard.press("Escape")
    expect(page.locator("dialog.ct-demo-dialog")).to_have_count(0)
    assert page.evaluate(
        "document.activeElement && document.activeElement.hasAttribute('data-ct-demo-open')"
    ), "Escape did not return focus to the control that opened the dialog"


def test_the_example_picker_fits_and_closes_on_a_narrow_screen(page: Page) -> None:
    """A phone viewport keeps the picker inside the screen and dismissible."""
    page.set_viewport_size({"width": 390, "height": 844})
    mount_scenario(page, controlled_scenario().with_demos([sequence_demo()]))
    _open_demo(page)

    dialog = page.locator("dialog.ct-demo-dialog")
    box = dialog.bounding_box()
    assert box is not None
    assert box["x"] >= 0 and box["x"] + box["width"] <= 390
    assert box["y"] >= 0 and box["y"] + box["height"] <= 844
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    expect(dialog.locator("[data-ct-demo-choose]")).to_be_visible()
    _evidence(page, "demo-picker-mobile")

    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    # The same control opens a fresh picker after the dismissal.
    page.locator("[data-ct-demo-open]").click()
    expect(page.locator("dialog.ct-demo-dialog")).to_be_visible()
    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(page.locator("dialog.ct-demo-dialog")).to_have_count(0)


def test_closing_a_picker_while_its_catalog_is_in_flight_cancels_it(page: Page) -> None:
    """A dismissed picker cannot surface a late catalog response."""
    router = mount_scenario(page, controlled_scenario().with_demos([sequence_demo()]))
    page.goto(f"{ORIGIN}/compute/create_task?task_type={RUNNER}")
    expect(page.locator(".ct-workbench")).to_be_visible()

    url = f"{ORIGIN}/compute/api/types/{RUNNER}/demos"
    held: list = []

    def hold_catalog(route) -> None:
        # Leave the request hanging so the picker can be dismissed first.
        held.append(route)

    page.route(url, hold_catalog)
    page.locator("[data-ct-demo-open]").click()
    expect(page.locator("dialog.ct-demo-dialog")).to_be_visible()
    # Keep the dismissed dialog reachable so a late response mutating detached
    # DOM is observable; a page locator cannot see nodes that left the document.
    page.evaluate("() => { window.__closedPicker = document.querySelector('dialog.ct-demo-dialog'); }")
    page.keyboard.press("Escape")
    expect(page.locator("dialog.ct-demo-dialog")).to_have_count(0)
    assert len(held) == 1, "the catalog request must still be in flight"
    assert page.evaluate("window.__closedPicker.querySelectorAll('.ct-demo').length") == 0

    # Deliver the late answer only after the dialog is gone: neither the demo
    # cards nor an error may be written into the detached dialog.
    held[0].fulfill(json=router.scenario.demo_catalog(RUNNER))
    page.wait_for_timeout(400)
    assert page.evaluate("window.__closedPicker.querySelectorAll('.ct-demo').length") == 0
    assert page.evaluate("window.__closedPicker.querySelector('.ct-status').textContent") == ""

    # The late response did not poison the next open either.
    page.unroute(url, hold_catalog)
    page.locator("[data-ct-demo-open]").click()
    expect(page.locator("dialog.ct-demo-dialog .ct-demo")).to_have_count(1)
    page.get_by_role("button", name="Cancel", exact=True).click()


def test_a_late_catalog_failure_is_not_written_into_a_dismissed_picker(page: Page) -> None:
    """The failure path respects the dismissal as the success path does."""
    mount_scenario(page, controlled_scenario().with_demos([sequence_demo()]))
    page.goto(f"{ORIGIN}/compute/create_task?task_type={RUNNER}")
    expect(page.locator(".ct-workbench")).to_be_visible()

    held: list = []
    page.route(f"{ORIGIN}/compute/api/types/{RUNNER}/demos", lambda route: held.append(route))
    page.locator("[data-ct-demo-open]").click()
    expect(page.locator("dialog.ct-demo-dialog")).to_be_visible()
    page.evaluate("() => { window.__closedPicker = document.querySelector('dialog.ct-demo-dialog'); }")
    page.keyboard.press("Escape")
    expect(page.locator("dialog.ct-demo-dialog")).to_have_count(0)

    assert len(held) == 1
    held[0].fulfill(status=503, content_type="application/json", body='{"error": "catalog unavailable"}')
    page.wait_for_timeout(400)
    assert page.evaluate("window.__closedPicker.querySelector('.ct-status').textContent") == ""
    expect(page.locator("dialog.ct-demo-dialog")).to_have_count(0)


def test_a_failed_example_catalog_is_reported_inside_the_picker(page: Page) -> None:
    """A catalog that cannot be read leaves the reader in a closable dialog."""
    mount_scenario(page, controlled_scenario().with_demos([sequence_demo()]))
    page.goto(f"{ORIGIN}/compute/create_task?task_type={RUNNER}")
    expect(page.locator(".ct-workbench")).to_be_visible()
    page.route(
        f"{ORIGIN}/compute/api/types/{RUNNER}/demos",
        lambda route: route.fulfill(status=503, content_type="application/json", body='{"error": "catalog unavailable"}'),
    )
    page.locator("[data-ct-demo-open]").click()
    dialog = page.locator("dialog.ct-demo-dialog")
    expect(dialog).to_be_visible()
    expect(dialog.locator(".ct-status")).to_have_class("ct-status error")
    expect(dialog.locator(".ct-status")).to_contain_text("503")
    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog).to_have_count(0)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_access_request_dialog_is_labelled_keyboard_safe_and_sends_one_policy(page: Page, theme: str) -> None:
    """Requesting access is a modal form that emits exactly the policy's id."""
    _pin_theme(page, theme)
    runner = replace(controlled_runner(), access=AccessState.requestable_policy())
    mount_scenario(page, controlled_scenario(runner=runner))
    posted: list[tuple[str, dict | None]] = []
    page.on("request", lambda request: posted.append((urlsplit(request.url).path, request.post_data_json)))
    page.goto(f"{ORIGIN}/compute/create_task?task_type={RUNNER}")
    expect(page.locator(".ct-access-panel")).to_be_visible()
    page.locator(".ct-access-panel").get_by_role("button", name="Request access", exact=True).click()
    dialog = page.locator("dialog.ct-dialog")
    expect(dialog).to_be_visible()

    style = _dialog_style(page, "dialog.ct-dialog")
    assert _rgba(style["background"])[3] == pytest.approx(1.0), style
    assert _contrast(style["color"], style["background"]) >= 4.5, style
    assert float(style["border"].removesuffix("px")) >= 1, style
    assert style["shadow"] != "none", style
    labelled = page.evaluate(
        """() => {
            const dialog = document.querySelector('dialog.ct-dialog');
            const id = dialog.getAttribute('aria-labelledby');
            return id ? document.getElementById(id)?.textContent : null;
        }"""
    )
    assert labelled == "Request Runner access", labelled
    _evidence(page, f"access-request-dialog-{theme}")

    # A modal dialog takes focus and Escape cancels without sending.
    assert page.evaluate("document.activeElement && document.activeElement.closest('dialog.ct-dialog') !== null")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    assert not [body for path, body in posted if path.endswith("/access/requests")]

    # Submitting sends the server-owned policy id and shows the answered state.
    page.locator(".ct-access-panel").get_by_role("button", name="Request access", exact=True).click()
    page.get_by_label("Research use and affiliation").fill("Non-commercial work at Example Institute")
    dialog = page.locator("dialog.ct-dialog")
    dialog.get_by_role("button", name="Request access", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(page.locator(".ct-access-panel")).to_contain_text("Access requested")
    requests = [body for path, body in posted if path.endswith("/access/requests")]
    assert requests == [{"policy_id": "academic-only", "reason": "Non-commercial work at Example Institute"}]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_replace_confirmation_is_a_labelled_opaque_dialog(page: Page, theme: str) -> None:
    """Replacing an edited form is confirmed in the same dialog family."""
    _pin_theme(page, theme)
    mount_scenario(page, controlled_scenario().with_demos([sequence_demo()]))
    page.goto(f"{ORIGIN}/compute/create_task?task_type={RUNNER}")
    expect(page.locator(".ct-workbench")).to_be_visible()
    page.locator('[data-ct-parameter="iterations"]').fill("1")
    page.locator("[data-ct-demo-open]").click()
    page.locator("[data-ct-demo-choose]").click()
    dialog = page.locator("dialog.ct-dialog:not(.ct-demo-dialog)")
    expect(dialog).to_be_visible()

    style = _dialog_style(page, "dialog.ct-dialog:not(.ct-demo-dialog)")
    assert _rgba(style["background"])[3] == pytest.approx(1.0), style
    assert _contrast(style["color"], style["background"]) >= 4.5, style
    labelled = page.evaluate(
        """() => {
            const dialog = document.querySelector('dialog.ct-dialog:not(.ct-demo-dialog)');
            const id = dialog.getAttribute('aria-labelledby');
            return id ? document.getElementById(id)?.textContent : null;
        }"""
    )
    # The accessible name is the question the reader answers, not the button's
    # imperative label, and it is the heading the dialog actually shows.
    heading = dialog.locator("h2").inner_text()
    assert labelled == heading and heading, labelled
    assert re.fullmatch(
        r"Loading the .+ replaces the inputs and settings you have already entered\.", heading
    ), heading
    assert heading != "Replace current inputs"
    _evidence(page, f"replace-confirmation-{theme}")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(page.locator('[data-ct-parameter="iterations"]')).to_have_value("1")
    expect(page.locator(".ct-demo-applied")).to_have_count(0)


def test_a_partial_example_is_offered_with_its_declared_file_and_nothing_else(page: Page) -> None:
    """The picker's declared file remains the only one the preset binds."""
    demo = sequence_demo()
    assert isinstance(demo.files[0], DemoFileSpec)
    mount_scenario(page, controlled_scenario().with_demos([demo]))
    _open_demo(page)
    dialog = page.locator("dialog.ct-demo-dialog")
    expect(dialog.locator(".ct-demo", has_text=demo.title)).to_be_visible()
    expect(dialog).to_contain_text(demo.files[0].path)
    expect(dialog).to_contain_text(demo.source_name)
    expect(dialog).to_contain_text(demo.license_name)


def test_demo_provenance_never_renders_an_unsafe_link(page: Page) -> None:
    """A declared source or licence URL becomes a link only when it is http(s)."""
    demo = sequence_demo(source_url="javascript:alert(1)", license_url="javascript:alert(1)")
    mount_scenario(page, controlled_scenario().with_demos([demo]))
    _open_demo(page)
    provenance = page.locator("dialog.ct-demo-dialog .ct-demo-provenance")
    expect(provenance.locator("a")).to_have_count(0)
    expect(provenance).to_contain_text(demo.source_name)
    expect(provenance).to_contain_text(demo.license_name)
    assert page.evaluate(
        "[...document.querySelectorAll('a[href]')].every(anchor => !anchor.getAttribute('href').startsWith('javascript:'))"
    )
