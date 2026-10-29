# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the per-stage ``[Stage] [Status]`` projection.

The status endpoint reports each workflow stage's scheduler status and its
independent dependency state. This file drives the production Result Workspace
through the fixture harness: a running workflow shows its completed, ready and
blocked stages as text, while a single-stage Task (which also has one implicit
stage record) shows no stage section at all.
"""

from __future__ import annotations

from dataclasses import replace

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import (
    LifecycleSpec,
    WorkflowStage,
    controlled_runner,
    controlled_scenario,
    mount_scenario,
)

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"
TASK_ID = "0123456789abcdef0123456789abcdef"


def _workflow_runner():
    """The controlled Runner, declaring four scientific stages."""
    return replace(
        controlled_runner(),
        name="workflow_demo",
        display_name="Workflow demo",
        workflow=(
            WorkflowStage("prepare", "Prepare inputs"),
            WorkflowStage("model", "Model"),
            WorkflowStage("validate", "Validate"),
            WorkflowStage("report", "Report"),
        ),
    )


def _running_workflow():
    """A workflow whose states cover completed, ready and blocked stages."""
    stages = (
        {"name": "prepare", "display_name": "Prepare inputs", "status": "COMPLETED", "dependency": "completed"},
        # No attempt record yet: NOT_STARTED with available inputs.
        {"name": "model", "display_name": "Model", "status": "NOT_STARTED", "dependency": "ready"},
        {"name": "validate", "display_name": "Validate", "status": "FAILED", "dependency": "blocked"},
        # Blocked by the failed stage, and never started.
        {"name": "report", "display_name": "Report", "status": "NOT_STARTED", "dependency": "blocked"},
    )
    return controlled_scenario(
        runner=_workflow_runner(),
        lifecycle=LifecycleSpec(statuses=("running",)),
        stages=stages,
    )


def _open_status(page: Page, scenario) -> None:
    mount_scenario(page, scenario)
    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")
    expect(page.locator(".result-status")).to_contain_text("running")


def test_workflow_stages_show_scheduler_status_and_dependency_separately(page: Page) -> None:
    """Each row names the stage, its scheduler status, and its dependency state."""
    _open_status(page, _running_workflow())

    list_node = page.locator("ol.result-stage-list")
    expect(list_node).to_have_count(1)
    expect(page.locator(".result-stage")).to_have_count(4)

    prepare = page.locator('.result-stage[data-stage="prepare"]')
    expect(prepare).to_contain_text("Prepare inputs")
    expect(prepare.locator(".status")).to_have_text("Completed")
    expect(prepare.locator(".result-stage-dependency")).to_have_text("Dependencies: Completed")

    model = page.locator('.result-stage[data-stage="model"]')
    expect(model.locator(".status")).to_have_text("Not started")
    expect(model.locator(".result-stage-dependency")).to_have_text("Dependencies: Ready")

    validate = page.locator('.result-stage[data-stage="validate"]')
    expect(validate.locator(".status")).to_have_text("Failed")
    expect(validate.locator(".result-stage-dependency")).to_have_text("Dependencies: Blocked")

    # A blocked stage with no attempt says both facts: it never started, and it
    # is blocked. "Blocked" is text in the row, not a tone that colour carries.
    report = page.locator('.result-stage[data-stage="report"]')
    expect(report.locator(".status")).to_have_text("Not started")
    expect(report.locator(".result-stage-dependency")).to_have_text("Dependencies: Blocked")
    expect(report).to_contain_text("Blocked")
    assert "Blocked" in report.inner_text()


def test_stage_without_dependency_shows_scheduler_status_only(page: Page) -> None:
    """A status projection without dependency never invents one.

    The field is server-owned and currently required, but a reader that receives
    an older projection must still state the scheduler status and stay silent
    about the dependency rather than copying a neighbouring stage's state.
    """
    scenario = controlled_scenario(
        runner=_workflow_runner(),
        lifecycle=LifecycleSpec(statuses=("running",)),
        stages=(
            {"name": "prepare", "display_name": "Prepare inputs", "status": "COMPLETED", "dependency": "completed"},
        ),
        stages_omit_dependency=True,
    )
    _open_status(page, scenario)

    row = page.locator('.result-stage[data-stage="prepare"]')
    expect(row.locator(".status")).to_have_text("Completed")
    expect(row.locator(".result-stage-dependency")).to_have_count(0)
    expect(row).not_to_contain_text("Dependencies:")


def test_single_stage_task_shows_no_stage_section(page: Page) -> None:
    """A non-workflow Task keeps its status surface unchanged.

    A single-stage Task also records one implicit stage, so the frontend must
    read the Task Type's workflow declaration rather than the stage count.
    """
    scenario = controlled_scenario().with_lifecycle("running").with_stages((
        # The Server's implicit single stage: the Task type itself.
        {"name": "sequence_demo", "display_name": "Sequence demo", "status": "RUNNING", "dependency": "ready"},
    ))
    _open_status(page, scenario)

    expect(page.locator(".result-stages")).to_be_hidden()
    expect(page.locator(".result-stage")).to_have_count(0)
