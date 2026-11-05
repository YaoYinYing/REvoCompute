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

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

import browser_frontend_assets
from frontend_fixtures import (
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
        ParameterSpec("start_group"),
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

    _click_canvas_until(page, lambda: bool(_control(page, "start_residue_number").input_value()))

    picked = int(_control(page, "start_residue_number").input_value())
    assert _control(page, "start_point_mode").input_value() == "residue"
    assert _control(page, "start_chain").input_value() == "A"
    assert _control(page, "start_residue_name").input_value() == _residues(PDB)[picked]

    # Editing the canonical control selects that residue again; the authored
    # identity in the submitted selection follows the edit, not the first pick.
    target = 11 if picked != 11 else 1
    _control(page, "start_residue_number").fill(str(target))
    expect(_control(page, "start_residue_name")).to_have_value(_residues(PDB)[target])

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
    assert params["start_residue_name"] == _residues(PDB)[target]


def test_an_insertion_coded_pick_is_refused_and_writes_nothing(
    page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pick CAVER cannot address leaves the canonical controls untouched."""
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", PRODUCTION_DIST)
    _open_picker(page, _insertion_coded_pdb())
    run = _run(page)
    expect(run).to_be_enabled()

    _click_canvas_until(page, lambda: run.is_disabled())

    assert _control(page, "start_residue_number").input_value() == ""
    assert _control(page, "start_chain").input_value() == ""
    assert run.is_disabled()
