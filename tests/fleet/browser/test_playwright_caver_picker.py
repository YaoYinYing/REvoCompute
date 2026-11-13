# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for the CAVER start-point picker.

The picker is the boundary where an authored molecular identity becomes the
owning Task's canonical ``start_point_*`` parameters. These cases drive the
built application with the real Mol* viewer: a residue picked on the canvas
writes the authored chain, residue number and residue name; editing the
canonical control selects that residue again; and a selection CAVER cannot
address writes nothing and blocks submission.

The fixture contract is the CAVER declaration's start-point controls: the
picker must speak that vocabulary and never invent its own.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

import browser_frontend_assets
from frontend_fixtures import (
    DemoFileSpec,
    DemoSpec,
    InputRole,
    ParameterSpec,
    RunnerDefinition,
    WorkspaceCapability,
    WorkspaceStep,
    mount_scenario,
    runner_scenario,
)

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
ROOT = Path(__file__).resolve().parents[3]
# The fixture harness otherwise builds the app with the result-viewer double;
# the picker is a viewer behavior and must run against the shipped Mol* bundle.
PRODUCTION_DIST = ROOT / "frontend" / "dist"
PDB = (ROOT / "tests" / "data" / "3fap_hf3_A_short.pdb").read_text(encoding="utf-8")

CAVER_PICKER = RunnerDefinition(
    name="caver_picker",
    display_name="CAVER picker",
    category="structure",
    category_label="Structure analysis",
    summary="Find transport tunnels from a chosen start point.",
    use_when="Use to exercise the start-point picker.",
    input_summary="One reference PDB structure.",
    output_summary="Tunnel geometry.",
    runtime_family="caver",
    inputs=(
        InputRole(
            "structure", "Reference structure", "protein_structure",
            formats=("pdb",), extensions=(".pdb",), minimum=1, maximum=1,
        ),
    ),
    parameters=(
        ParameterSpec.enumeration(
            "start_point_mode", ("point", "atom", "residue", "group", "ligand"), required=True,
        ),
        ParameterSpec.integer("start_residue_number"),
        ParameterSpec("start_residue_name"),
        ParameterSpec("start_chain"),
        ParameterSpec("start_atom_name"),
        ParameterSpec("start_altloc"),
        ParameterSpec("start_group"),
        ParameterSpec.enumeration(
            "start_point_source", ("manual", "viewer-crosshair", "centroid", "com"),
            default="manual", has_default=True,
        ),
        ParameterSpec("start_reference_sha256", default="", has_default=True),
        ParameterSpec("start_selected_residues", default="", has_default=True),
        ParameterSpec("start_selected_serials", default="", has_default=True),
        ParameterSpec.enumeration(
            "start_com_hydrogen_policy", ("include", "exclude"), default="include", has_default=True,
        ),
        ParameterSpec.number("start_x"),
        ParameterSpec.number("start_y"),
        ParameterSpec.number("start_z"),
    ),
    workspace_steps=(
        WorkspaceStep(
            id="material",
            title="Provide the structure",
            capabilities=(
                WorkspaceCapability("files", "source_files", "Structures", options=(("primary_role", "structure"),)),
                WorkspaceCapability(
                    "structure", "structure_summary", "Inspect the reference structure",
                    options=(("source", "source_files"), ("role", "structure"), ("select_residues", True)),
                ),
            ),
        ),
        WorkspaceStep(
            id="settings",
            title="Choose the start point",
            capabilities=(WorkspaceCapability("parameters", "task_parameters", "CAVER settings"),),
        ),
        WorkspaceStep(
            id="review",
            title="Review and run",
            capabilities=(WorkspaceCapability("review", "submission_review", "CAVER review"),),
        ),
    ),
)


def _residues(pdb: str) -> dict[int, str]:
    found: dict[int, str] = {}
    for line in pdb.splitlines():
        if line.startswith("ATOM"):
            found[int(line[22:26])] = line[17:20].strip()
    return found


def _insertion_coded_pdb() -> str:
    """The valid fixture with an insertion code on every authored residue."""
    lines = []
    for line in PDB.splitlines():
        if line.startswith(("ATOM", "HETATM")):
            line = line[:26] + "A" + line[27:]
        lines.append(line)
    return "\n".join(lines) + "\n"


def _ion_pdb() -> str:
    """The valid fixture plus one single-atom ion residue."""
    lines = [line for line in PDB.splitlines() if line not in {"TER", "END"}]
    lines.append("HETATM  600 ZN    ZN A 101     -16.745   2.179  13.690  1.00 20.00          ZN")
    lines.extend(("TER", "END"))
    return "\n".join(lines) + "\n"


def _control(page: Page, name: str):
    return page.locator(f'[data-ct-parameter="{name}"]')


def _run(page: Page):
    return page.get_by_role("button", name="Run task", exact=True)


def _open_picker(page: Page, pdb: str):
    """Open the real picker, bind one structure, and wait for Mol* to load it."""
    requests = mount_scenario(page, runner_scenario(CAVER_PICKER)).requests
    page.goto(f"{ORIGIN}/compute/create_task?task_type={CAVER_PICKER.name}")
    expect(page.locator(".ct-workbench")).to_be_visible()
    page.locator(".ct-file-role input[type=file]").first.set_input_files(
        {"name": "reference.pdb", "mimeType": "chemical/x-pdb", "buffer": pdb.encode("utf-8")}
    )
    page.get_by_text("select residues").wait_for(timeout=180_000)
    page.wait_for_timeout(1500)
    return requests


def _choose_atom(page: Page, name: str) -> None:
    """Choose one named atom from the picker's candidate control."""
    select = page.locator(".ct-caver-actions select")
    options = select.locator("option")
    value = next(
        options.nth(index).get_attribute("value")
        for index, label in enumerate(options.all_inner_texts())
        if label.startswith(f"{name} · ")
    )
    assert value is not None
    select.select_option(value=value)


def _atom_option_serials(page: Page) -> list[int]:
    """The source serials of the picker's current candidate residue."""
    return [
        int(label.rsplit(" · ", 1)[1])
        for label in page.locator(".ct-caver-actions select option").all_inner_texts()
        if " · " in label
    ]


def _residue_of_serial(pdb: str, serial: int) -> tuple[str, int]:
    """The authored chain and residue number of one ATOM record."""
    for line in pdb.splitlines():
        if line.startswith("ATOM") and int(line[6:11]) == serial:
            return line[21], int(line[22:26])
    raise AssertionError(f"serial {serial} is not an ATOM record")


def _click_canvas_until_other_residue(page: Page, current: list[int]) -> None:
    """Click the structure until the viewer selection moves to another residue."""
    viewer = page.locator(".ct-structure-viewer")
    viewer.scroll_into_view_if_needed()
    box = page.locator(".ct-structure-viewer canvas").first.bounding_box()
    assert box is not None
    positions = (
        (0.5, 0.5), (0.5, 0.4), (0.5, 0.6), (0.4, 0.5), (0.6, 0.5),
        (0.35, 0.45), (0.65, 0.55), (0.3, 0.5), (0.7, 0.5), (0.45, 0.35), (0.55, 0.65),
    )
    for dx, dy in positions:
        page.mouse.click(box["x"] + box["width"] * dx, box["y"] + box["height"] * dy)
        for _ in range(8):
            page.wait_for_timeout(250)
            serials = _atom_option_serials(page)
            if serials and serials[0] != current[0]:
                return
    pytest.fail("the structure canvas did not switch to another residue")


def _click_canvas_until(page: Page, condition) -> None:
    """Click the structure until the picker reaches the state under test."""
    viewer = page.locator(".ct-structure-viewer")
    viewer.scroll_into_view_if_needed()
    box = page.locator(".ct-structure-viewer canvas").first.bounding_box()
    assert box is not None
    for dx, dy in ((0.5, 0.5), (0.5, 0.4), (0.5, 0.6), (0.4, 0.5), (0.6, 0.5), (0.35, 0.45), (0.65, 0.55)):
        page.mouse.click(box["x"] + box["width"] * dx, box["y"] + box["height"] * dy)
        page.wait_for_timeout(500)
        if condition():
            return
    pytest.fail("the structure canvas did not reach the state under test")


def test_a_residue_pick_writes_the_owning_tasks_canonical_parameters(page: Page, monkeypatch: pytest.MonkeyPatch) -> None:
    """A canvas pick becomes CAVER parameters, and a control edit re-places it."""
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", PRODUCTION_DIST)
    requests = _open_picker(page, PDB)
    # The mode is explicit in the contract; a residue pick is tested in residue
    # mode rather than relying on the first option of a required select.
    _control(page, "start_point_mode").select_option("residue")

    _click_canvas_until(page, lambda: bool(_control(page, "start_residue_number").input_value()))

    picked = int(_control(page, "start_residue_number").input_value())
    assert _control(page, "start_point_mode").input_value() == "residue"
    assert _control(page, "start_chain").input_value() == "A"
    # A native residue selection is addressed by chain and number only; the
    # residue name is provenance the Runner reads from the structure.
    assert _control(page, "start_residue_name").input_value() == ""

    # Editing the canonical control selects that residue again; the authored
    # identity in the submitted selection follows the edit, not the first pick.
    target = 11 if picked != 11 else 1
    _control(page, "start_residue_number").fill(str(target))
    expect(_control(page, "start_chain")).to_have_value("A")

    _run(page).click()
    page.wait_for_url(f"{ORIGIN}/compute/dashboard**", timeout=30_000)
    submit = requests.submit()[0]
    capabilities = submit.workspace_capabilities()
    assert capabilities["structure_summary"]["selected_residues"] == [
        {"auth_chain": "A", "auth_seq_id": target, "residue_name": _residues(PDB)[target], "hetero": False}
    ]
    params = capabilities["submission_review"]["params"]
    assert params["start_point_mode"] == "residue"
    assert params["start_chain"] == "A"
    assert params["start_residue_number"] == str(target)
    assert "start_residue_name" not in params


def test_an_insertion_coded_pick_is_refused_and_writes_nothing(
    page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pick CAVER cannot address leaves the canonical controls untouched."""
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", PRODUCTION_DIST)
    _open_picker(page, _insertion_coded_pdb())
    _control(page, "start_point_mode").select_option("residue")
    run = _run(page)
    expect(run).to_be_enabled()

    _click_canvas_until(page, lambda: run.is_disabled())

    assert _control(page, "start_residue_number").input_value() == ""
    assert _control(page, "start_chain").input_value() == ""
    assert run.is_disabled()


def _start_point_preset() -> DemoSpec:
    """One complete preset: a reference file plus the start point it defines."""
    return DemoSpec(
        id="configured_start_point",
        title="Configured centroid start point",
        purpose="Bind the reference structure together with an explicit centroid.",
        files=(
            DemoFileSpec(role="structure", path="reference.pdb", body=PDB, media_type="chemical/x-pdb"),
        ),
        parameters={
            "start_point_mode": "point",
            "start_point_source": "centroid",
            "start_x": "12.5",
            "start_y": "8.25",
            "start_z": "4.75",
            "start_selected_residues": "A:7",
            "start_selected_serials": "1-4",
            "start_reference_sha256": hashlib.sha256(PDB.encode("utf-8")).hexdigest(),
        },
    )


def _atom_start_point_preset() -> DemoSpec:
    """One complete preset whose start point is an atom in residue A:2."""
    return DemoSpec(
        id="configured_atom_start_point",
        title="Configured atom start point",
        purpose="Bind the reference structure together with an explicit atom.",
        files=(
            DemoFileSpec(role="structure", path="reference.pdb", body=PDB, media_type="chemical/x-pdb"),
        ),
        parameters={
            "start_point_mode": "atom",
            "start_chain": "A",
            "start_residue_number": "2",
            "start_atom_name": "CA",
            "start_altloc": "",
        },
    )


def _chainless_atom_start_point_preset() -> DemoSpec:
    """The atom preset with the optional chain left to the Runner."""
    preset = _atom_start_point_preset()
    parameters = dict(preset.parameters)
    parameters.pop("start_chain")
    return DemoSpec(
        id="configured_chainless_atom_start_point",
        title="Configured chainless atom start point",
        purpose="Bind the reference structure together with a chainless atom address.",
        files=preset.files,
        parameters=parameters,
    )


def test_a_preset_reinstates_its_start_point_and_undo_restores_the_previous_one(
    page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file and its parameters are one state, not a file edit plus a reset."""
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", PRODUCTION_DIST)
    mount_scenario(page, runner_scenario(CAVER_PICKER).with_demos([_start_point_preset()]))
    page.goto(f"{ORIGIN}/compute/create_task?task_type={CAVER_PICKER.name}")
    expect(page.locator(".ct-workbench")).to_be_visible()

    # The state the preset replaces: a different reference and a residue point.
    page.locator(".ct-file-role input[type=file]").first.set_input_files(
        {"name": "manual.pdb", "mimeType": "chemical/x-pdb", "buffer": PDB.encode("utf-8")}
    )
    page.get_by_text("select residues").wait_for(timeout=180_000)
    _control(page, "start_point_mode").select_option("residue")
    _control(page, "start_chain").fill("A")
    _control(page, "start_residue_number").fill("7")

    page.locator("[data-ct-demo-open]").click()
    expect(page.locator("dialog.ct-demo-dialog")).to_be_visible()
    page.locator("[data-ct-demo-choose]").click()
    page.get_by_role("button", name="Replace current inputs").click()
    expect(page.locator(".ct-demo-applied")).to_be_visible()

    # Loading the file must not erase the parameters that arrived with it.
    expect(page.locator(".ct-file-well")).to_contain_text("reference.pdb")
    expect(_control(page, "start_point_mode")).to_have_value("point")
    expect(_control(page, "start_point_source")).to_have_value("centroid")
    expect(_control(page, "start_x")).to_have_value("12.5")
    expect(_control(page, "start_y")).to_have_value("8.25")
    expect(_control(page, "start_z")).to_have_value("4.75")
    expect(_control(page, "start_selected_serials")).to_have_value("1-4")
    expect(_control(page, "start_reference_sha256")).to_have_value(
        hashlib.sha256(PDB.encode("utf-8")).hexdigest()
    )

    # Undo is another whole preset: the swapped reference and its residue point.
    page.get_by_role("button", name="Put my inputs back").click()
    expect(page.locator(".ct-file-well")).to_contain_text("manual.pdb")
    expect(_control(page, "start_point_mode")).to_have_value("residue")
    expect(_control(page, "start_chain")).to_have_value("A")
    expect(_control(page, "start_residue_number")).to_have_value("7")
    expect(_control(page, "start_x")).to_have_value("")


def test_the_displayed_atom_can_be_committed_explicitly(
    page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unset atom mode shows a placeholder, so the first candidate is choosable."""
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", PRODUCTION_DIST)
    _open_picker(page, PDB)
    _control(page, "start_point_mode").select_option("residue")
    _click_canvas_until(page, lambda: bool(_control(page, "start_residue_number").input_value()))

    _control(page, "start_point_mode").select_option("atom")
    atoms = page.locator(".ct-caver-actions select")
    expect(atoms).to_be_visible()
    # The canonical atom is empty, so the control must display that, not its
    # first candidate: choosing an already-displayed option fires no change.
    expect(atoms).to_have_value("")
    assert _control(page, "start_atom_name").input_value() == ""

    atoms.select_option(index=1)
    expect(_control(page, "start_atom_name")).not_to_have_value("")
    expect(_control(page, "start_chain")).to_have_value("A")


def test_an_atom_committed_for_one_residue_is_not_selected_in_another(
    page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same atom name in another residue is a different committed atom."""
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", PRODUCTION_DIST)
    _open_picker(page, PDB)
    _control(page, "start_point_mode").select_option("residue")
    _click_canvas_until(page, lambda: bool(_control(page, "start_residue_number").input_value()))
    first = int(_control(page, "start_residue_number").input_value())

    _control(page, "start_point_mode").select_option("atom")
    atoms = page.locator(".ct-caver-actions select")
    expect(atoms).to_be_visible()
    _choose_atom(page, "CA")
    expect(_control(page, "start_atom_name")).to_have_value("CA")
    expect(_control(page, "start_residue_number")).to_have_value(str(first))
    first_atoms = _atom_option_serials(page)

    # Pick another residue in the viewer. Its CA has the same name as A's, so a
    # name-only match would display it as if it were the committed atom.
    _click_canvas_until_other_residue(page, first_atoms)
    other_serials = _atom_option_serials(page)
    assert other_serials and other_serials[0] != first_atoms[0]

    # Selecting B leaves the canonical atom uncommitted: the residue fields still
    # name A, and nothing may present B's CA as the committed atom.
    expect(atoms).to_have_value("")
    expect(_control(page, "start_atom_name")).to_have_value("")
    expect(_control(page, "start_residue_number")).to_have_value(str(first))

    # Only an explicit choice commits B, and then every field names B.
    ca_serial = next(
        int(label.rsplit(" · ", 1)[1])
        for label in page.locator(".ct-caver-actions select option").all_inner_texts()
        if label.startswith("CA · ")
    )
    chain, second = _residue_of_serial(PDB, ca_serial)
    _choose_atom(page, "CA")
    expect(_control(page, "start_chain")).to_have_value(chain)
    expect(_control(page, "start_residue_number")).to_have_value(str(second))
    expect(_control(page, "start_atom_name")).to_have_value("CA")
    expect(_control(page, "start_altloc")).to_have_value("")


def test_a_single_atom_ion_is_chosen_explicitly(
    page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A one-atom residue still needs the explicit choice that commits it."""
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", PRODUCTION_DIST)
    _open_picker(page, _ion_pdb())
    _control(page, "start_point_mode").select_option("residue")
    _control(page, "start_chain").fill("A")
    _control(page, "start_residue_number").fill("101")

    _control(page, "start_point_mode").select_option("atom")
    atoms = page.locator(".ct-caver-actions select")
    expect(atoms).to_be_visible()
    expect(atoms).to_have_value("")
    assert _control(page, "start_atom_name").input_value() == ""

    _choose_atom(page, "ZN")
    expect(_control(page, "start_chain")).to_have_value("A")
    expect(_control(page, "start_residue_number")).to_have_value("101")
    expect(_control(page, "start_atom_name")).to_have_value("ZN")
    expect(_control(page, "start_altloc")).to_have_value("")


def test_an_atom_preset_keeps_its_atom_and_undo_keeps_the_earlier_point(
    page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restoring a file and its atom start point must not clear the atom."""
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", PRODUCTION_DIST)
    mount_scenario(page, runner_scenario(CAVER_PICKER).with_demos([_atom_start_point_preset()]))
    page.goto(f"{ORIGIN}/compute/create_task?task_type={CAVER_PICKER.name}")
    expect(page.locator(".ct-workbench")).to_be_visible()

    page.locator(".ct-file-role input[type=file]").first.set_input_files(
        {"name": "manual.pdb", "mimeType": "chemical/x-pdb", "buffer": PDB.encode("utf-8")}
    )
    page.get_by_text("select residues").wait_for(timeout=180_000)
    _control(page, "start_point_mode").select_option("residue")
    _control(page, "start_chain").fill("A")
    _control(page, "start_residue_number").fill("7")

    page.locator("[data-ct-demo-open]").click()
    expect(page.locator("dialog.ct-demo-dialog")).to_be_visible()
    page.locator("[data-ct-demo-choose]").click()
    page.get_by_role("button", name="Replace current inputs").click()
    expect(page.locator(".ct-demo-applied")).to_be_visible()
    page.get_by_text("reference.pdb; select residues").wait_for(timeout=180_000)

    # The atom committed by the preset survives the topology reload.
    expect(page.locator(".ct-file-well")).to_contain_text("reference.pdb")
    expect(_control(page, "start_point_mode")).to_have_value("atom")
    expect(_control(page, "start_chain")).to_have_value("A")
    expect(_control(page, "start_residue_number")).to_have_value("2")
    expect(_control(page, "start_atom_name")).to_have_value("CA")
    atoms = page.locator(".ct-caver-actions select")
    expect(atoms).to_be_visible()
    expect(atoms).not_to_have_value("")
    assert atoms.locator("option:checked").inner_text().startswith("CA · ")

    page.get_by_role("button", name="Put my inputs back").click()
    expect(page.locator(".ct-file-well")).to_contain_text("manual.pdb")
    expect(_control(page, "start_point_mode")).to_have_value("residue")
    expect(_control(page, "start_chain")).to_have_value("A")
    expect(_control(page, "start_residue_number")).to_have_value("7")
    expect(_control(page, "start_atom_name")).to_have_value("")


def test_a_chainless_atom_preset_keeps_its_atom_after_the_topology_loads(
    page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An optional chain must not invalidate the atom address the preset carries."""
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", PRODUCTION_DIST)
    mount_scenario(
        page, runner_scenario(CAVER_PICKER).with_demos([_chainless_atom_start_point_preset()])
    )
    page.goto(f"{ORIGIN}/compute/create_task?task_type={CAVER_PICKER.name}")
    expect(page.locator(".ct-workbench")).to_be_visible()

    page.locator(".ct-file-role input[type=file]").first.set_input_files(
        {"name": "manual.pdb", "mimeType": "chemical/x-pdb", "buffer": PDB.encode("utf-8")}
    )
    page.get_by_text("select residues").wait_for(timeout=180_000)

    page.locator("[data-ct-demo-open]").click()
    expect(page.locator("dialog.ct-demo-dialog")).to_be_visible()
    page.locator("[data-ct-demo-choose]").click()
    page.get_by_role("button", name="Replace current inputs").click()
    expect(page.locator(".ct-demo-applied")).to_be_visible()
    page.get_by_text("reference.pdb; select residues").wait_for(timeout=180_000)

    # The chainless address is a Task-valid atom mode state. Restoring must keep
    # its canonical atom and residue once the deferred topology load completes.
    expect(page.locator(".ct-file-well")).to_contain_text("reference.pdb")
    expect(_control(page, "start_point_mode")).to_have_value("atom")
    expect(_control(page, "start_chain")).to_have_value("")
    expect(_control(page, "start_residue_number")).to_have_value("2")
    expect(_control(page, "start_atom_name")).to_have_value("CA")
    atoms = page.locator(".ct-caver-actions select")
    expect(atoms).to_be_visible()
    expect(atoms).not_to_have_value("")
    assert atoms.locator("option:checked").inner_text().startswith("CA · ")
