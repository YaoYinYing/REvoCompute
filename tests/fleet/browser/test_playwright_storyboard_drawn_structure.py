# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for one molecular stage per result page.

A Task Storyboard mounts a published structure in its own
``[data-structure-slot]`` through ``services.openFile`` and then mounts its
declared candidate-collection view, which lists that same artifact. The
workspace has ONE shared StructureController, and mounting a different host
dispossesses the previous one, so the declared view must not re-mount what the
page already draws: the storyboard's own slot keeps its canvas and the view
states where the structure is drawn. Only the real Mol* stage shows this, so
this case drives the built production bundle.

A candidate the page does not draw is a different structure and gets its own
view-owned stage: the page's slot keeps its canvas beside it, and selecting the
artifact the page draws closes only the view's stage.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

import browser_frontend_assets
from frontend_fixtures import DEFAULT_ORIGIN, DEFAULT_TASK_ID, ResultFixture, RunnerDefinition, StoryboardSpec, mount_scenario, runner_scenario
from frontend_fixtures.models import ResultArtifactSpec
from frontend_fixtures.results import PDB_BODY

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
RESULT_DIST = ROOT / "frontend" / "dist"

STORYBOARD = """export default {
  async mount(host, context) {
    const structure = context.files.get("structures");
    const stage = document.createElement("section");
    const slot = document.createElement("div");
    slot.dataset.structureSlot = "true";
    slot.style.height = "420px";
    stage.append(slot);
    const note = document.createElement("p"); note.className = "storyboard-note";
    host.replaceChildren(stage, note);
    await context.services.openFile(structure);
    note.textContent = "The structure above is the run's own model.";
    const view = document.createElement("section"); view.className = "storyboard-view";
    host.append(view);
    await context.services.mountView("models", view, new AbortController().signal);
    return { destroy() {} };
  },
};
"""


def page_with_drawn_structure() -> RunnerDefinition:
    runner = RunnerDefinition(
        name="stage_demo", display_name="Stage demo", category="design",
        category_label="Design", summary="One designed structure.", runtime_family="stage_demo",
    )
    result = ResultFixture(
        name="storyboard_drawn_structure",
        task_type="stage_demo",
        artifacts=(
            ResultArtifactSpec("predictions/model_0.pdb", role="primary", capability="molecular_structure",
                               media_type="chemical/x-pdb", body=PDB_BODY),
        ),
        logical_files=(("structures", ("predictions/model_0.pdb",)),),
        views=(
            (("plugin", "candidate-collection"), ("id", "models"), ("role", "primary"), ("title", "Models"),
             ("sources", {"candidates": ["predictions/model_0.pdb"]}), ("mapping", {})),
        ),
        storyboard=StoryboardSpec(
            identifier="stage-demo", entrypoint="index.js", requires=("structures",), module_body=STORYBOARD,
        ),
    )
    return runner_scenario(runner, result=result)


STORYBOARD_SAME_BASENAME = """export default {
  async mount(host, context) {
    const structure = context.files.get("structures");
    const stage = document.createElement("section");
    const slot = document.createElement("div");
    slot.dataset.structureSlot = "true";
    slot.style.height = "420px";
    stage.append(slot);
    const note = document.createElement("p"); note.className = "storyboard-note";
    host.replaceChildren(stage, note);
    await context.services.openFile(structure);
    note.textContent = "The structure above is the run's own model.";
    const view = document.createElement("section"); view.className = "storyboard-view";
    host.append(view);
    await context.services.mountView("models", view, new AbortController().signal);
    return { destroy() {} };
  },
};
"""


def page_with_same_basename_candidates() -> RunnerDefinition:
    """The page draws ``run2/model_0.cif``; the view lists ``run1`` and ``run2``."""
    runner = RunnerDefinition(
        name="stage_demo", display_name="Stage demo", category="design",
        category_label="Design", summary="Two modeled structures.", runtime_family="stage_demo",
    )
    result = ResultFixture(
        name="storyboard_same_basename",
        task_type="stage_demo",
        artifacts=(
            ResultArtifactSpec("run2/model_0.cif", role="primary", capability="molecular_structure",
                               media_type="chemical/x-cif", body=PDB_BODY),
            ResultArtifactSpec("run1/model_0.cif", role="primary", capability="molecular_structure",
                               media_type="chemical/x-cif", body=PDB_BODY),
        ),
        logical_files=(("structures", ("run2/model_0.cif",)),),
        views=(
            (("plugin", "candidate-collection"), ("id", "models"), ("role", "primary"), ("title", "Models"),
             ("sources", {"candidates": ["run1/model_0.cif", "run2/model_0.cif"]}), ("mapping", {})),
        ),
        storyboard=StoryboardSpec(
            identifier="stage-demo", entrypoint="index.js", requires=("structures",),
            module_body=STORYBOARD_SAME_BASENAME,
        ),
    )
    return runner_scenario(runner, result=result)


def test_the_storyboard_slot_keeps_the_only_stage(page: Page, monkeypatch: pytest.MonkeyPatch) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", RESULT_DIST)
    mount_scenario(page, page_with_drawn_structure())
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{DEFAULT_ORIGIN}/compute/results/{DEFAULT_TASK_ID}")

    # The structure the page opened stays mounted in the storyboard's own slot.
    expect(page.locator("[data-structure-slot] .structure-host canvas").first).to_be_visible(timeout=180_000)
    # The declared view lists the same artifact and states where it is drawn;
    # it neither mounts a second stage nor dispossesses the page's own.
    expect(page.locator(".candidate-stage")).to_have_count(0)
    expect(page.locator(".structure-host")).to_have_count(1)
    expect(page.locator(".candidate-collection-view .result-note")).to_contain_text("drawn in the page’s own structure stage above")
    expect(page.locator(".storyboard-note")).to_contain_text("the run's own model")
    assert errors == [], errors


def test_a_same_basename_candidate_stages_beside_the_page_slot(page: Page, monkeypatch: pytest.MonkeyPatch) -> None:
    """The page draws ``run2/model_0.cif``; a view candidate ``run1/model_0.cif`` is its own stage.

    Two owners, two live canvases: the slot keeps the page's own structure while
    the view draws its candidate. Selecting the artifact the page draws closes
    only the view's stage -- the slot keeps its canvas, so the page's note that
    the structure above is the run's own model stays true.
    """
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", RESULT_DIST)
    mount_scenario(page, page_with_same_basename_candidates())
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{DEFAULT_ORIGIN}/compute/results/{DEFAULT_TASK_ID}")

    slot_canvas = page.locator("[data-structure-slot] .structure-host canvas").first
    expect(slot_canvas).to_be_visible(timeout=180_000)
    expect(page.locator(".candidate-stage .structure-host canvas").first).to_be_visible(timeout=180_000)
    # Both owners keep their own live stage; the page's slot was not dispossessed.
    expect(page.locator("[data-structure-slot] .structure-host canvas")).to_have_count(1)
    expect(page.locator(".candidate-stage .structure-host canvas")).to_have_count(1)
    expect(slot_canvas).to_be_visible()

    candidates = page.locator(".candidate-collection-view .candidate-list button")
    expect(candidates).to_have_count(2)
    expect(candidates.nth(0)).to_have_attribute("aria-current", "true")
    expect(candidates.nth(1)).to_have_attribute("aria-current", "false")

    # Selecting the artifact the page already draws closes only the view's stage.
    candidates.nth(1).click()
    expect(page.locator(".candidate-stage")).to_have_count(0)
    expect(page.locator(".candidate-collection-view .result-note")).to_contain_text(
        "drawn in the page’s own structure stage above"
    )
    expect(page.locator("[data-structure-slot] .structure-host canvas")).to_have_count(1)
    expect(page.locator("[data-structure-slot] .structure-host canvas").first).to_be_visible()
    expect(page.locator(".storyboard-note")).to_contain_text("the run's own model")
    assert errors == [], errors
