# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for loading a declared example into Create Task.

A demo is a supported input preset the owning Task declares: named input roles
to bind and typed parameters to set. Loading one is a *local form edit* in one
deliberate action - it fills the same controls a reader fills by hand, shows
what it changed, stays editable, and stops there. It never submits, preflights,
reserves credit, or creates a Task, which is the guarantee most of this file
exists to hold: the requests the browser actually made are the evidence, not the
copy on screen.

The catalog and obtain contracts are covered at the server boundary in
``tests/server/test_task_demos.py``; this file drives the built application
through ``tests/frontend_fixtures/`` and asserts only what a reader meets.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import (
    ANONYMOUS_AUTH,
    DemoFileSpec,
    DemoSpec,
    controlled_runner,
    mount_scenario,
    runner_scenario,
    sequence_demo,
)

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"

# The smallest touch target every control in this repository carries.
MIN_TARGET_PX = 44

# One demo whose declared parameter differs from the Task's own default, so a
# load has something to change and something to report.
LOADABLE = sequence_demo(parameters={"iterations": 4})


def _pin_locale(page: Page) -> None:
    """Pin the locale before the bundle boots; copy is baked in as the DOM builds."""
    page.add_init_script("localStorage.setItem('revocompute-locale', 'en')")


def _open_create_task(page: Page, runner=None) -> None:
    page.goto(f"{ORIGIN}/compute/create_task?task_type={(runner or controlled_runner()).name}")
    expect(page.locator(".ct-workbench")).to_be_visible()


def _scenario(demos=(LOADABLE,)):
    return runner_scenario(controlled_runner()).with_demos(tuple(demos))


def _mount(page: Page, scenario):
    """Serve the built bundle against one scenario and return its request capture."""
    return mount_scenario(page, scenario).requests


def _header_demo_button(page: Page):
    # Addressed by the hook the surface publishes, not by its copy: the label is
    # reader-facing text and may be reworded without breaking this contract.
    return page.locator("[data-ct-demo-open]")


def _open_picker(page: Page):
    _header_demo_button(page).click()
    dialog = page.locator(".ct-demo-dialog")
    expect(dialog).to_be_visible()
    return dialog


def _choose(page: Page, dialog, title: str = LOADABLE.title) -> str:
    """Choose one declared example from an open picker and return its card text.

    The card is read while the picker is open, because the picker leaves the
    document as soon as a choice is made; the caller's own next assertion is what
    waits for the form to catch up with the asynchronous load.
    """
    card = dialog.locator(".ct-demo", has_text=title)
    expect(card).to_be_visible()
    text = card.inner_text()
    card.locator("[data-ct-demo-choose]").click()
    expect(dialog).to_have_count(0)
    return text


def _parameter(page: Page, name: str):
    return page.locator(f'[data-ct-parameter="{name}"]')


def test_the_demo_button_fills_the_named_roles_and_parameters_in_one_action(page: Page) -> None:
    """One deliberate action fills the form: files bound, parameters set, nothing run."""
    _pin_locale(page)
    mount = _scenario()
    requests = _mount(page, mount)
    _open_create_task(page)

    # Nothing is bound before the example is loaded, and the Task's own default
    # is what the parameter control holds.
    expect(page.locator(".ct-file-well.has-file")).to_have_count(0)
    expect(_parameter(page, "iterations")).to_have_value("2")

    dialog = _open_picker(page)
    _choose(page, dialog)

    # The declared parameter value is the control's value, and the declared file
    # is bound to the role the demo names - the same role binding an upload makes.
    expect(_parameter(page, "iterations")).to_have_value("4")
    well = page.locator(".ct-file-role", has_text="Protein sequence")
    expect(well.locator(".ct-file-well")).to_have_class("ct-file-well has-file")
    expect(well.locator("strong").first).to_have_text("records.fasta")

    # The reader is told the example was applied and what it filled, and the
    # form stays theirs: the submission control is still the reader's to press.
    expect(page.locator(".ct-status")).to_have_class("ct-status ok")
    expect(page.locator(".ct-status")).to_contain_text(LOADABLE.title)
    applied = page.locator(".ct-demo-applied")
    expect(applied).to_be_visible()
    expect(applied).to_contain_text("Filled 1 of 1 input files")

    # Loading an example is not running the task. The evidence is the traffic.
    assert requests.preflight() == ()
    assert requests.submit() == ()


def test_loading_an_example_leaves_every_field_editable(page: Page) -> None:
    """A loaded example is a starting point the reader can still change."""
    mount = _scenario()
    _mount(page, mount)
    _open_create_task(page)

    _choose(page, _open_picker(page))

    # A parameter the example set is an ordinary control: editing it works, and
    # the file the example bound previews exactly as an uploaded one does.
    _parameter(page, "iterations").fill("3")
    expect(_parameter(page, "iterations")).to_have_value("3")
    expect(page.locator(".ct-input-preview")).to_be_visible()
    expect(page.locator(".ct-input-preview")).to_contain_text("ACDEFGHIKL")


def test_loading_an_example_never_preflights_or_submits(page: Page) -> None:
    """Reading the catalog, obtaining a file, and applying it are all the traffic."""
    mount = _scenario()
    requests = _mount(page, mount)
    _open_create_task(page)

    _choose(page, _open_picker(page))
    expect(page.locator(".ct-status")).to_have_class("ct-status ok")

    catalog = requests.demo_catalog(mount.runner.name)
    files = requests.demo_files(mount.runner.name)
    assert len(catalog) == 1, requests.urls()
    assert len(files) == 1, requests.urls()
    assert requests.preflight() == (), "loading a preset must not preflight"
    assert requests.submit() == (), "loading a preset must not submit"
    assert requests.status_polls() == (), "loading a preset must not create job identity"


def test_an_edited_form_is_only_replaced_after_the_reader_confirms(page: Page) -> None:
    """The destructive path asks first, and the previous state can be restored."""
    mount = _scenario()
    _mount(page, mount)
    _open_create_task(page)

    # The reader has entered their own setting; loading would replace it.
    _parameter(page, "iterations").fill("1")
    _choose(page, _open_picker(page))

    confirm = page.locator("dialog.ct-dialog:not(.ct-demo-dialog)")
    expect(confirm).to_be_visible()
    expect(confirm).to_contain_text("replaces the inputs and settings")
    confirm.get_by_role("button", name="Keep what I entered", exact=True).click()

    # Keeping what they entered is answered state: nothing was replaced.
    expect(confirm).to_have_count(0)
    expect(_parameter(page, "iterations")).to_have_value("1")
    expect(page.locator(".ct-demo-applied")).to_have_count(0)

    # Confirming replaces it, and the state that was replaced can be put back.
    _choose(page, _open_picker(page))
    confirm = page.locator("dialog.ct-dialog:not(.ct-demo-dialog)")
    confirm.get_by_role("button", name="Replace current inputs", exact=True).click()
    expect(_parameter(page, "iterations")).to_have_value("4")

    applied = page.locator(".ct-demo-applied")
    expect(applied).to_contain_text("What changed")
    # The panel names what changed against the state it replaced, in the Task's
    # own parameter vocabulary; the label is the server's, read from the schema.
    expect(applied.locator("li", has_text="1 → 4")).not_to_have_count(0)
    applied.get_by_role("button", name="Put my inputs back", exact=True).click()
    expect(_parameter(page, "iterations")).to_have_value("1")
    expect(page.locator(".ct-status")).to_contain_text("Your previous inputs are back")


def test_the_picker_names_the_source_and_licence_of_every_example(page: Page) -> None:
    """A reader judges a fixture by its provenance, so the picker states it."""
    _pin_locale(page)
    mount = _scenario()
    _mount(page, mount)
    _open_create_task(page)

    card = _choose(page, _open_picker(page))
    assert LOADABLE.purpose in card, card
    assert "Source and licence" in card, card
    assert LOADABLE.source_name in card, card
    assert LOADABLE.license_name in card, card
    # The declared setting is stated before the reader chooses, not only after.
    assert "iterations" in card, card


def test_a_method_without_a_declared_example_says_so(page: Page) -> None:
    """No example is an answer: the picker opens and reports the absence."""
    _pin_locale(page)
    mount = _scenario(demos=())
    _mount(page, mount)
    _open_create_task(page)

    dialog = _open_picker(page)
    expect(dialog.locator("[data-ct-demo-empty]")).to_be_visible()
    expect(dialog.locator(".ct-demo")).to_have_count(0)
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog).to_have_count(0)


def test_the_demo_catalog_is_a_public_read_that_grants_nothing(page: Page) -> None:
    """The catalog is published input: an anonymous caller reads it, and gains nothing.

    The read is issued with the page's own ``fetch`` rather than
    ``page.request.get`` because a Playwright APIRequestContext request is not
    routed through ``page.route``: it resolves the host itself and so can never
    reach the fixture origin. Driving the page's own network stack keeps the
    request covered by the harness, exactly as production would issue it.

    Create Task itself requires a session, so this read runs under the anonymous
    session the harness projects. That is the point: neither the catalog nor the
    fixture it names carries a credential or an entitlement, and reaching either
    authorizes, reserves, and creates nothing at all. Reading the same method as
    a signed-in user is not different behavior - the endpoint has no
    session-dependent branch to reach.
    """
    mount = _scenario()
    _mount(page, mount.with_session(ANONYMOUS_AUTH))
    page.goto(f"{ORIGIN}/compute/login")

    read = page.evaluate(
        """async path => {
            const response = await fetch(path, { credentials: 'same-origin' });
            return { status: response.status, body: await response.json() };
        }""",
        f"/compute/api/types/{mount.runner.name}/demos",
    )
    assert read["status"] == 200, read
    assert read["body"] == mount.demo_catalog(mount.runner.name)

    # The fixture the declaration names is served on the same anonymous terms,
    # byte for byte, and the digest the client verifies is the declared one.
    asset = LOADABLE.files[0]
    obtained = page.evaluate(
        """async path => {
            const response = await fetch(path, { credentials: 'same-origin' });
            return { status: response.status, body: await response.text() };
        }""",
        f"/compute/api/types/{mount.runner.name}/demos/{LOADABLE.id}/files/{asset.path}",
    )
    assert obtained == {"status": 200, "body": asset.body}
    assert read["body"]["demos"][0]["inputs"][asset.role][0]["sha256"] == asset.payload(
        mount.runner.name, LOADABLE.id
    )["sha256"]

    # A path the declaration does not name is not served, and a method that
    # declares no example answers with an empty catalog rather than an error.
    assert mount.with_demos(()).demo_catalog(mount.runner.name) == {
        "version": 1,
        "task_type": mount.runner.name,
        "demos": [],
    }


def test_a_file_the_declaration_cannot_serve_reports_the_failure_and_changes_nothing(page: Page) -> None:
    """An unserved fixture is a reported failure, never a partial application."""
    unavailable = DemoSpec(
        id=LOADABLE.id,
        title=LOADABLE.title,
        purpose=LOADABLE.purpose,
        files=(
            DemoFileSpec(role="sequence", path="files/records.fasta", body=">x\nACDE\n", media_type="text/x-fasta"),
        ),
        parameters={"iterations": 4},
        unavailable_asset="files/records.fasta",
    )
    mount = _scenario((unavailable,))
    requests = _mount(page, mount)
    _open_create_task(page)

    _choose(page, _open_picker(page))
    expect(page.locator(".ct-status")).to_have_class("ct-status error")
    expect(_parameter(page, "iterations")).to_have_value("2")
    expect(page.locator(".ct-file-well.has-file")).to_have_count(0)
    assert requests.preflight() == ()
    assert requests.submit() == ()


def test_the_demo_controls_are_full_targets_and_keep_the_page_within_its_width(page: Page) -> None:
    """The example affordance is operable and does not push the layout sideways."""
    mount = _scenario()
    _mount(page, mount)

    for width in (390, 320):
        page.set_viewport_size({"width": width, "height": 900})
        _open_create_task(page)
        button = _header_demo_button(page)
        box = button.bounding_box()
        assert box is not None and box["height"] >= MIN_TARGET_PX, (width, box)
        button.focus()
        assert button.evaluate("node => node === document.activeElement")

        dialog = _open_picker(page)
        choose = dialog.locator("[data-ct-demo-choose]")
        choose.focus()
        assert choose.evaluate("node => node === document.activeElement")
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), width

