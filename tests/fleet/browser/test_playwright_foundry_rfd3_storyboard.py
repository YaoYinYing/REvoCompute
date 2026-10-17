# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for the RFD3/RFD3NA compressed-design contract.

The two design TaskTypes share one runtime family with the RF3 folding Task, so
this suite's job is that the design Storyboard presents exactly the design tree
its own Task declares -- `<example_id>_model_<index>.cif.gz` structures and the
optional per-design `.json` -- and that it never reaches for the fold spelling
the family-level module used.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]

MOUNT = """
async (payload) => {
  const url = URL.createObjectURL(new Blob([payload.source], { type: "text/javascript" }));
  const module = await import(url);
  const opened = [], downloaded = [];
  const files = new Map(Object.entries(payload.files));
  const instance = await module.default.mount(document.getElementById("host"), {
    files: { get: (id) => files.get(id) || null },
    metadata: { taskType: payload.taskType },
    services: {
      openFile: (artifact) => opened.push(artifact.url),
      downloadFile: (artifact) => downloaded.push(artifact.url),
    },
  });
  window.__designStoryboard = { opened, downloaded, instance };
}
"""


def _source(task: str) -> str:
    return (ROOT / "docker" / "runners" / "foundry" / "tasks" / task / "storyboard" / "index.js").read_text(
        encoding="utf-8"
    )


_DESIGNS = [
    {"url": "/design-0", "name": "binder_0_model_0.cif.gz"},
    {"url": "/design-1", "name": "binder_0_model_1.cif.gz"},
]
_RUN_RECORD = {"url": "/run", "name": "foundry-run.json"}
_MODEL_ASSETS = {"url": "/assets", "name": "foundry-model-assets.json"}


@pytest.mark.parametrize("task", ["foundry_rfd3_design", "foundry_rfd3na_design"])
def test_design_storyboard_labels_and_opens_compressed_designs(page: Page, task: str) -> None:
    """A design is named by its published identity and opened by its own URL."""
    files = {
        "designs": _DESIGNS,
        "model_metadata": [{"url": "/meta-0", "name": "binder_0_model_0.json"}],
        "run_record": [_RUN_RECORD],
        "model_assets": [_MODEL_ASSETS],
    }
    page.set_content("<div id='host'></div>")
    page.evaluate(MOUNT, {"source": _source(task), "files": files, "taskType": task, "responses": {}})

    # The label is read back from the published name, so the specification key
    # and the model index stay explicit rather than being renumbered by position.
    expect(page.locator(".rfd3-designs button").first).to_contain_text("binder_0 · model 0")
    expect(page.locator(".rfd3-designs button").nth(1)).to_contain_text("binder_0 · model 1")
    expect(page.locator(".rfd3-designs button").first).to_have_attribute("aria-current", "true")

    # Only the selected design's own metadata is offered: the second design has
    # none, so selecting it withdraws the metadata action.
    expect(page.get_by_role("button", name="Download design metadata")).to_be_visible()
    page.locator(".rfd3-designs button").nth(1).click()
    expect(page.get_by_role("button", name="Download design metadata")).to_have_count(0)
    expect(page.locator(".rfd3-designs button").nth(1)).to_have_attribute("aria-current", "true")

    page.get_by_role("button", name="Open selected structure").click()
    assert page.evaluate("window.__designStoryboard.opened") == ["/design-1"]

    # The run record and model identity are always downloadable provenance.
    page.get_by_role("button", name="Download run record").click()
    page.get_by_role("button", name="Download model identity").click()
    assert page.evaluate("window.__designStoryboard.downloaded") == ["/run", "/assets"]

    # The design module never offers an RF3 seed/sample affordance.
    expect(page.get_by_role("button", name="Download selected sample")).to_have_count(0)
    expect(page.locator(".rf3-candidates")).to_have_count(0)


@pytest.mark.parametrize("task", ["foundry_rfd3_design", "foundry_rfd3na_design"])
def test_design_storyboard_mounts_without_a_published_design(page: Page, task: str) -> None:
    """A run that published no design states it once and still offers provenance."""
    files = {
        "designs": [],
        "model_metadata": [],
        "run_record": [_RUN_RECORD],
        "model_assets": [_MODEL_ASSETS],
    }
    page.set_content("<div id='host'></div>")
    page.evaluate(MOUNT, {"source": _source(task), "files": files, "taskType": task, "responses": {}})

    expect(page.locator(".preview-message")).to_have_text("No design structure was published.")
    expect(page.get_by_role("button", name="Download run record")).to_be_visible()
    expect(page.get_by_role("button", name="Open selected structure")).to_have_count(0)


def test_design_storyboard_destroys_its_own_host(page: Page) -> None:
    """The module disposes the tree it mounted, leaving no stale evidence."""
    files = {
        "designs": _DESIGNS,
        "model_metadata": [],
        "run_record": [_RUN_RECORD],
        "model_assets": [_MODEL_ASSETS],
    }
    page.set_content("<div id='host'></div>")
    page.evaluate(MOUNT, {"source": _source("foundry_rfd3_design"), "files": files, "taskType": "foundry_rfd3_design", "responses": {}})
    expect(page.locator(".rfd3-result")).to_have_count(1)

    page.evaluate("window.__designStoryboard.instance.destroy()")
    expect(page.locator(".rfd3-result")).to_have_count(0)
    expect(page.locator("#host")).to_be_empty()
