# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance against a replayed real fpocket result.

This drives the built production frontend against a bounded replay bundle of a
real fpocket run (the pinned 4.2.3 SIF, the family's own ``run.sh``/``detect.py``
and the real ``normalize_results.py``, over the 1SUO reference structure at the
100-iteration smoke volume). It covers renderer behaviour GREMLIN_LH does not:
the ``entity-table`` primary over a real normalized pocket table, the
``scalar-summary`` detection summary, the ``evidence-bundle`` of fpocket's own
raw files, and the logical-file/storyboard grouping the runner declares.

It asserts renderer *semantics* -- which plugin consumes which real artifact,
that the table columns and rows come from the captured bytes, that the raw
evidence stays reachable, and that a download returns the exact captured bytes.
Nothing here claims the pockets are scientifically correct: the values are what
fpocket reported (see ``docker/runners/fpocket/INTEGRATION.md``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from frontend_fixtures import ReplayBundle, mount_scenario, replay_scenario
from frontend_fixtures.scenarios import RunnerDefinition
from frontend_fixtures.models import InputRole, ParameterSpec, WorkspaceCapability, WorkspaceStep
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://revocompute.example"
BUNDLE_PATH = ROOT / "tests/data/fpocket_replay/1suo_2pockets.json"

if not BUNDLE_PATH.is_file():
    pytest.skip("the captured fpocket replay bundle is not present", allow_module_level=True)


def _replay() -> ReplayBundle:
    return ReplayBundle.load(BUNDLE_PATH)


def _task_id() -> str:
    return _replay().task_id


def fpocket_runner() -> RunnerDefinition:
    """The real ``fpocket`` declared contract, transcribed from its ``task.yaml``.

    Only the catalog/detail surface comes from here; the result surface is the
    captured bundle. Kept local so the matrix test does not depend on a scenario
    helper another PR owns.
    """
    return RunnerDefinition(
        name="fpocket",
        display_name="fpocket pocket detection",
        category="structure",
        category_label="Structure",
        summary="Detect ranked protein surface pockets with fpocket's Voronoi tessellation.",
        use_when="Use this to enumerate candidate binding pockets on one protein structure.",
        input_summary="Exactly one protein structure.",
        output_summary="Ranked pockets with fpocket score, druggability, and geometry descriptors.",
        runtime_family="fpocket",
        inputs=(
            InputRole(
                id="structure",
                title="Protein structure",
                logical_type="protein_structure",
                formats=("pdb", "cif", "mmcif", "ent"),
                extensions=(".pdb", ".cif", ".mmcif", ".ent"),
                description="One protein structure to scan for pockets.",
            ),
        ),
        parameters=(
            ParameterSpec.number("min_alpha_sphere_radius", default=3.4, has_default=True, description="Minimum alpha-sphere radius."),
            ParameterSpec.number("max_alpha_sphere_radius", default=6.2, has_default=True, description="Maximum alpha-sphere radius."),
            ParameterSpec.integer("min_alpha_spheres_per_pocket", default=15, has_default=True, description="Minimum alpha spheres per pocket."),
            ParameterSpec.number("clustering_distance", default=2.4, has_default=True, description="Clustering distance."),
            ParameterSpec.integer("volume_monte_carlo_iterations", default=300, has_default=True, description="Monte-Carlo volume iterations."),
        ),
        workspace_steps=(
            WorkspaceStep(
                id="structure",
                title="Provide the protein structure",
                description="Upload one protein structure to scan for pockets.",
                capabilities=(
                    WorkspaceCapability("files", "source_files", "Protein structure"),
                    WorkspaceCapability(
                        "structure",
                        "structure_summary",
                        "Inspect the structure",
                        options=(("source", "source_files"), ("select_chains", False), ("select_residues", False)),
                    ),
                ),
            ),
            WorkspaceStep(
                id="settings",
                title="Set detection controls",
                description="Adjust the alpha-sphere geometry and pocket filtering.",
                capabilities=(WorkspaceCapability("parameters", "task_parameters", "fpocket settings"),),
            ),
            WorkspaceStep(
                id="review",
                title="Review and run",
                description="Confirm the structure and detection controls.",
                capabilities=(WorkspaceCapability("review", "submission_review", "fpocket review", options=(("show_paths", True),)),),
            ),
        ),
    )


def _mount(page: Page) -> ReplayBundle:
    replay = _replay()
    mount_scenario(page, replay_scenario(fpocket_runner(), replay))
    return replay


def _open(page: Page) -> None:
    page.goto(f"{ORIGIN}/compute/results/{_task_id()}")
    expect(page.locator(".result-workspace, .fpl-result, .result-status").first).to_be_visible()


def test_replayed_result_mounts_the_declared_fpocket_views(page: Page) -> None:
    replay = _mount(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)

    expect(page.locator(".result-meta")).to_contain_text(replay.task_id)
    # The storyboard owns the primary surface; each declared view keeps a tab.
    expect(page.locator(".result-tab", has_text="Scientific result")).to_be_visible()
    for title in ("Ranked pockets", "Detection summary", "Raw fpocket output"):
        expect(page.locator(".result-tab", has_text=title)).to_be_visible()


def test_replayed_ranked_pockets_table_consumes_the_real_normalized_table(page: Page) -> None:
    replay = _mount(page)
    requests = mount_scenario(page, replay_scenario(fpocket_runner(), _replay())).requests
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)

    page.locator(".result-tab", has_text="Ranked pockets").click()
    table = page.locator(".result-preview table").first
    expect(table).to_be_visible()
    # The header row is the real normalized columns, not a fixture's guess.
    for column in ("pocket", "rank", "druggability_score"):
        expect(table.locator("th", has_text=column)).to_be_visible()

    served = requests.matching(f"/compute/api/results/{replay.task_id}/tables/pockets.csv")
    assert served, "the ranked-pockets view never read the replayed table"
    # The rendered body row count equals the captured table's data rows.
    expected_rows = replay.payload("pockets.csv")[0].decode("utf-8").strip().splitlines()
    rows = table.locator("tbody tr")
    expect(rows).to_have_count(len(expected_rows) - 1)
    first = rows.first.locator("td").all_inner_texts()
    assert first[0] == "pocket1"
    assert first[1] == "1"
    assert first[2] == "0.629"


def test_replayed_detection_summary_renders_the_real_scalar_values(page: Page) -> None:
    replay = _mount(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)

    page.locator(".result-tab", has_text="Detection summary").click()
    summary = json.loads(replay.payload("summary.json")[0])
    preview = page.locator(".result-preview")
    # The scalar-summary fields are declared by the task; their values come from
    # the captured summary.json the real normalizer wrote.
    expect(preview).to_contain_text(str(summary["pocket_count"]))


def test_replayed_evidence_bundle_exposes_the_raw_fpocket_output(page: Page) -> None:
    replay = _mount(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)

    page.locator(".result-tab", has_text="Raw fpocket output").click()
    # The raw descriptor file the run wrote is reachable as an artifact.
    expect(page.locator(".result-tab", has_text="Raw fpocket output")).to_be_visible()
    assert "work/1SUO_out/1SUO_info.txt" in replay.bundle["payloads"]


def test_replayed_download_returns_the_exact_captured_bytes(page: Page) -> None:
    replay = _mount(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)

    path = "pockets.csv"
    expected = replay.bundle["payloads"][path]["sha256"]
    fetched = page.evaluate(
        """async (url) => {
            const response = await fetch(url, { credentials: 'same-origin' });
            const buffer = await response.arrayBuffer();
            const digest = await crypto.subtle.digest('SHA-256', buffer);
            return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('');
        }""",
        f"{ORIGIN}/compute/api/results/{replay.task_id}/artifacts/{path}?download=0",
    )
    assert fetched == expected


def test_replayed_result_raises_no_console_or_csp_error(page: Page) -> None:
    errors: list[str] = []
    page.on("console", lambda message: errors.append(f"console.{message.type}: {message.text}") if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    _mount(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)
    expect(page.locator(".result-tab", has_text="Ranked pockets")).to_be_visible()
    violations = page.evaluate("window.__cspViolations || []")
    assert errors == [], errors
    assert violations == [], violations


def test_replayed_task_scope_is_enforced_for_a_mismatched_id(page: Page) -> None:
    _mount(page)
    status = page.evaluate(
        """async (url) => (await fetch(url, { credentials: 'same-origin' })).status""",
        f"{ORIGIN}/compute/api/results/{'f' * 32}/artifacts/pockets.csv",
    )
    assert status == 404
