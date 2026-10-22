# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for a declared candidate-collection view of structures.

The structure fixture declares its primary view as ``candidate-collection`` over
three published structure candidates. A reader opening that view gets the first
candidate in the shared molecular stage and selects another beside it, so this
case reads the real production bundle: the stage's own canvas and toolbar, and
the candidate bytes the browser fetched for each selection. A stand-in
``openFile`` can observe neither.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

import browser_frontend_assets
import frontend_fixtures

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
RESULT_DIST = ROOT / "frontend" / "dist"


def test_a_structure_candidate_mounts_the_shared_stage_and_follows_the_selection(
    page: Page, monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", RESULT_DIST)
    router = frontend_fixtures.mount_scenario(page, frontend_fixtures.structure_scenario())
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{frontend_fixtures.DEFAULT_ORIGIN}/compute/results/{frontend_fixtures.DEFAULT_TASK_ID}")

    # The declared candidates render one by one into the workspace's own
    # molecular stage: Mol*'s canvas and the structure toolbar, in one host.
    expect(page.locator(".candidate-collection-view .structure-host canvas").first).to_be_visible(timeout=180_000)
    expect(page.locator(".candidate-collection-view .structure-toolbar")).to_be_visible()
    candidates = page.locator(".candidate-collection-view .candidate-list button")
    expect(candidates).to_have_count(3)
    expect(candidates.first).to_have_attribute("aria-current", "true")
    expect(candidates.first).to_have_text("predictions/model_0.cif")
    artifacts = f"/compute/api/results/{frontend_fixtures.DEFAULT_TASK_ID}/artifacts/predictions"
    assert router.requests.matching(f"{artifacts}/model_0.cif"), router.requests.urls()

    # Selecting another candidate hands the same stage the other published
    # structure, while the selector stays beside it rather than replacing it.
    candidates.nth(1).click()
    expect(candidates.nth(1)).to_have_attribute("aria-current", "true")
    expect(candidates.first).to_have_attribute("aria-current", "false")
    page.wait_for_function(
        f"""() => performance.getEntriesByType('resource')
            .some((entry) => entry.name.endsWith('{artifacts}/model_1.cif'))""",
        timeout=180_000,
    )
    expect(page.locator(".candidate-collection-view .structure-host")).to_have_count(1)
    expect(page.locator(".candidate-collection-view .structure-host canvas").first).to_be_visible(timeout=180_000)
    assert errors == [], errors
