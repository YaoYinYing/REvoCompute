# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Loading a declared example states the next step this deployment actually has.

The example picker fills the live form from the Task's own declaration: the
files bind to their named roles and the parameters take the declared values.
In a demo deployment nothing can be submitted, so the form must not follow that
success with a "run the task" instruction or a ready row that promises a
submission; a production deployment keeps its ordinary copy. The same bundle is
driven in both profiles so the difference is the deployment fact, not the form.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import controlled_scenario, mount_scenario, sequence_demo

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
TASK_TYPE = "sequence_demo"
DEMO_ENVIRONMENT = {
    "version": 1,
    "demo_mode": True,
    "execution": "preview_only",
    "notice": "Demo environment: preview and replay only. Tasks are not executed.",
}


def _open_form(page: Page) -> None:
    page.goto(f"{ORIGIN}/compute/create_task?task_type={TASK_TYPE}")
    expect(page.locator(".ct-workbench")).to_be_visible()


def _load_example(page: Page) -> None:
    page.locator("[data-ct-demo-open]").click()
    expect(page.locator("dialog.ct-demo-dialog")).to_be_visible()
    page.locator("[data-ct-demo-choose]").click()
    expect(page.locator(".ct-file-well.has-file")).to_have_count(1)


def test_a_demo_deployment_loads_the_example_without_promising_a_run(page: Page) -> None:
    """The preset fills the form and the stated next step is inspection only."""
    mount_scenario(
        page,
        controlled_scenario().with_demos([sequence_demo()]),
        environment=DEMO_ENVIRONMENT,
    )
    _open_form(page)
    _load_example(page)

    # The declaration reached the live form: the file is bound to its role and
    # the declared parameter replaced the control's own default.
    expect(page.locator(".ct-file-well")).to_contain_text("records.fasta")
    expect(page.locator('[data-ct-parameter="iterations"]')).to_have_value("3")

    status = page.locator(".ct-status")
    expect(page.locator(".ct-demo-applied")).to_contain_text("Filled 1 of 1 input files")
    expect(status).not_to_contain_text("run the task")
    ready = page.locator(".ct-validation-row.info")
    expect(ready).to_contain_text("does not execute")
    expect(ready).not_to_contain_text("before submission")

    action = page.locator(".ct-actions button.ct-primary")
    expect(action).to_have_text("Preview only — not executable here")
    expect(action).to_be_disabled()


def test_production_keeps_its_own_next_step_after_loading_the_same_example(page: Page) -> None:
    """The production copy is unchanged by the preview-only statement."""
    mount_scenario(page, controlled_scenario().with_demos([sequence_demo()]))
    _open_form(page)
    _load_example(page)

    expect(page.locator('[data-ct-parameter="iterations"]')).to_have_value("3")
    expect(page.locator(".ct-status")).to_contain_text("run the task yourself")
    expect(page.locator(".ct-validation-row.info")).to_contain_text("before submission")
