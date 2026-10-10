# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Fleet browser acceptance for the real ``gremlin_lh_fit`` Runner contract.

The generic browser suite drives the synthetic ``sequence_demo`` Runner; this
file owns the one authentic production contract a browser test needs, because a
generic test must never consume a real Runner identity. The Runner definition
comes from :func:`frontend_fixtures.pssm_gremlin_scenario`, whose identity is
``gremlin_lh_fit`` and whose five declared result views mirror the shipped
``task.yaml``: ``raw_couplings`` is the primary matrix, ``apc_couplings`` is
evidence, and the remaining views are evidence. The artifact bytes are fixtures,
so this exercises rendering and makes no scientific claim.
"""

from __future__ import annotations

from typing import Sequence

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import mount_scenario, pssm_gremlin_scenario

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
TASK_ID = "0123456789abcdef0123456789abcdef"


def _open_result_after_lifecycle(page: Page, pending: Sequence[str], terminal_text: str) -> None:
    """Load the Result Workspace and drive its poll-counted lifecycle to the end.

    The router advances one lifecycle step per status poll and the workspace
    polls on mount, so each ``reload`` is exactly one deterministic step. Once a
    terminal state also reports ``result_available`` the manifest renders in the
    same load, so the terminal *manifest* state - not a final pending status - is
    what the last reload shows.
    """
    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")
    expect(page.locator(".result-status")).to_contain_text(pending[0])
    for status in pending[1:]:
        page.reload()
        expect(page.locator(".result-status")).to_contain_text(status)
    page.reload()
    expect(page.locator(".result-status")).to_contain_text(terminal_text)


def test_gremlin_lh_runner_contract_projects_into_catalog_create_task_and_result(page: Page) -> None:
    """The real GREMLIN_LH scenario renders its views from fixture bytes."""
    mount_scenario(page, pssm_gremlin_scenario())

    page.goto(f"{ORIGIN}/runners/gremlin_lh_fit")
    expect(page.get_by_role("heading", name="GREMLIN_LH Potts model", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Protein multiple-sequence alignment")).to_be_visible()

    page.get_by_role("link", name="Create task").first.click()
    expect(page.get_by_role("heading", name="GREMLIN_LH Potts model", exact=True)).to_be_visible()

    _open_result_after_lifecycle(page, ("queued", "running"), "finished")
    expect(page.get_by_role("heading", name="GREMLIN_LH Potts model", exact=True)).to_be_visible()
    expect(page.locator(".result-tab")).to_have_count(5)
    expect(page.locator(".result-tab", has_text="Coupling strength (raw Frobenius)")).to_be_visible()
    expect(page.locator(".result-tab", has_text="Coupling strength (average-product corrected)")).to_be_visible()
    expect(page.locator(".result-file-group", has_text="Diagnostics")).to_be_visible()
