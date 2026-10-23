# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the demo playground: preview only, replay backed.

The built production frontend is served against canonical fixture responses for a
deployment that reports ``execution: preview_only``. Three journeys are checked:
the catalog/detail/form preview that must never offer a runnable control, the
recorded-result replay that renders through the one Result Workspace, and a
submission the Server refuses even when requested directly. The recorded bytes
come from the checked-in replay bundles the deployment loads, so the artifact
and manifest assertions are about the bundle's own identity, not a fixture id.

These are frontend-rendering contracts. They prove nothing about Runner
execution, scientific validity, readiness, or a live deployment.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from frontend_fixtures import controlled_scenario, gremlin_lh_runner, mount_scenario
from playwright.sync_api import Page, expect
from revocompute.demo import load_demo_replays

import browser_frontend_assets

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "https://revocompute.example"
GREMLIN_SCENARIO = "gremlin-lh-couplings"
GREMLIN_TASK_ID = "944ed43af62ead9f5c9560bae1ccd897"
EXCLUDED_LOG = (
    "execution/slurm-unknown-user-gremlin_lh_fit-944ed43af62ead9f5c9560bae1ccd897.stderr.log"
)

DEMO_ENVIRONMENT: dict[str, Any] = {
    "version": 1,
    "demo_mode": True,
    "execution": "preview_only",
    "notice": "Demo environment: preview and replay only. Tasks are not executed.",
}
PRODUCTION_ENVIRONMENT: dict[str, Any] = {"version": 1, "demo_mode": False, "execution": "available"}


@pytest.fixture
def production_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve the worktree's real production build, which carries the demo routes."""
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", ROOT / "frontend" / "dist")


@pytest.fixture
def demo_replays(tmp_path: Path) -> dict[str, Any]:
    """Load the curated replay corpus through the Server's own demo loader.

    The tracked index names checked-in bundles under ``tests/data``. The
    deployment resolves those names into its own state tree, so this fixture
    writes the same resolved index and loads it, rather than constructing a
    scenario the loader would refuse.
    """
    tracked = json.loads((ROOT / "demo" / "replays" / "index.json").read_text(encoding="utf-8"))
    replay_root = tmp_path / "replays"
    replay_root.mkdir()
    resolved: list[dict[str, Any]] = []
    for entry in tracked["scenarios"]:
        source = ROOT / entry["source"]
        if not source.is_file():
            continue
        bundle_name = f"{entry['id']}.json"
        shutil.copy2(source, replay_root / bundle_name)
        resolved.append({key: value for key, value in entry.items() if key != "source"} | {"bundle": bundle_name})
    (replay_root / "index.json").write_text(
        json.dumps({"version": tracked["version"], "scenarios": resolved}), encoding="utf-8"
    )
    return load_demo_replays(replay_root)


def _mount_demo(
    page: Page,
    demo_replays: dict[str, Any],
    *,
    scenario: Any = None,
    environment: dict[str, Any] | None = None,
) -> Any:
    catalog = scenario or controlled_scenario().with_catalog([gremlin_lh_runner()])
    return mount_scenario(
        page, catalog, environment=environment or DEMO_ENVIRONMENT, demo_replays=demo_replays
    )


def _open_replay(page: Page) -> None:
    page.goto(f"{ORIGIN}/compute/demo/replays/{GREMLIN_SCENARIO}")
    expect(page.locator(".demo-replay-banner h1")).to_be_visible()
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()


def _sha256(url: str, page: Page) -> str:
    return page.evaluate(
        """async (url) => {
            const response = await fetch(url, { credentials: 'same-origin' });
            const buffer = await response.arrayBuffer();
            const digest = await crypto.subtle.digest('SHA-256', buffer);
            return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('');
        }""",
        url,
    )


def test_demo_landing_catalog_and_task_detail_lead_to_a_preview_only_form(
    page: Page, production_bundle: None, demo_replays: dict[str, Any]
) -> None:
    """Journey A: the demo chrome, catalog, detail, and the non-runnable form."""
    router = _mount_demo(page, demo_replays)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{ORIGIN}/compute/demo")

    # The deployment profile is stated in the chrome and on the page itself.
    expect(page.locator(".app-demo-badge")).to_be_visible()
    expect(page.locator(".app-demo-badge")).to_have_text("Demo environment")
    expect(page.locator(".demo-page h1")).to_have_text("Demo playground")
    expect(page.locator(".demo-page .demo-notice")).to_contain_text("preview and replay only")

    # The canonical Task catalog and the recorded scenarios are both previewed.
    preview = page.locator(".demo-section", has=page.get_by_role("heading", name="Inspect a Task"))
    expect(preview.locator(".demo-card", has_text="GREMLIN_LH Potts model")).to_be_visible()
    replays = page.locator(".demo-section", has=page.get_by_role("heading", name="Recorded results"))
    expect(replays.locator(".demo-card-replay")).to_have_count(len(demo_replays))
    expect(replays.locator(".demo-card-replay").first.locator(".demo-provenance")).to_contain_text("Recorded result")
    expect(page.locator(".demo-limitations")).to_contain_text("does not run scientific Runners")
    assert router.requests.matching("/compute/api/environment")

    # Runner catalog: canonical contracts, the demo notice, no dead production link.
    page.locator('.app-sidebar a[href="/runners"]').click()
    expect(page.locator(".runner-catalog .runner-card")).to_have_count(2)
    expect(page.locator(".runners-page .demo-notice")).to_contain_text("preview and replay only")
    page.locator(
        ".runner-card", has=page.get_by_role("heading", name="GREMLIN_LH Potts model", exact=True)
    ).get_by_role("link", name="View method").click()
    expect(page.locator(".runner-detail-heading h1")).to_have_text("GREMLIN_LH Potts model")
    expect(page.locator(".runner-detail-page .demo-notice")).to_contain_text("preview and replay only")

    # The form is inspectable, and its only run control states the preview contract.
    page.locator(".runner-detail-heading").get_by_role("link", name="Create task", exact=True).click()
    expect(page.locator(".ct-workbench")).to_be_visible()
    expect(page.locator(".ct-page-header .demo-notice")).to_contain_text("preview and replay only")
    action = page.locator(".ct-actions button.ct-primary")
    expect(action).to_have_text("Preview only — not executable here")
    expect(action).to_be_disabled()
    expect(page.locator(".app-demo-badge")).to_be_visible()


def test_demo_replay_journey_renders_the_recorded_manifest_and_bytes(
    page: Page, production_bundle: None, demo_replays: dict[str, Any]
) -> None:
    """Journey B: landing card to the recorded workspace, views, preview, download."""
    router = _mount_demo(page, demo_replays)
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{ORIGIN}/compute/demo")

    card = page.locator(".demo-card-replay", has=page.get_by_role("heading", name=re.compile("2KL8 alignment")))
    expect(card.locator(".demo-provenance")).to_contain_text("Recorded result")
    card.get_by_role("link", name="Open recorded result").click()
    expect(page).to_have_url(re.compile(rf"/compute/demo/replays/{GREMLIN_SCENARIO}$"))

    # The replay page names the scenario, its provenance, and the captured bundle.
    banner = page.locator(".demo-replay-banner")
    expect(banner.locator(".demo-provenance")).to_contain_text("Recorded result")
    expect(banner.locator(".demo-provenance")).to_contain_text("provenance")
    expect(banner.locator(".demo-card-meta")).to_contain_text("Capture source:")
    expect(banner.locator(".demo-card-meta")).to_contain_text("Bundle digest:")

    # The recorded ResultManifest drives the one Result Workspace, at its own identity.
    expect(page.locator(".result-workspace")).to_be_visible()
    expect(page.locator(".result-meta")).to_have_attribute("title", f"Task ID {GREMLIN_TASK_ID}")
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()
    # The recorded matrix reads the demo-scoped table route; the re-pointed URL
    # never falls back to the production result route the capture was taken from.
    tables = router.requests.matching(
        f"/compute/api/demo/replays/{GREMLIN_SCENARIO}/tables/couplings/raw_scores.csv"
    )
    assert tables and all("matrix=1" in record.query for record in tables)
    assert router.requests.matching(
        f"/compute/api/results/{GREMLIN_TASK_ID}/tables/couplings/raw_scores.csv"
    ) == ()

    # A declared view renders from the recorded logical file.
    page.locator(".result-view-menu > summary").click()
    expect(page.locator(".result-tab", has_text="Filtered alignment")).to_be_visible()
    page.locator(".result-tab", has_text="Filtered alignment").click()
    expect(page.locator(".result-preview")).to_contain_text("2KL8")

    # An artifact row previews the recorded text and offers that exact byte stream.
    page.get_by_role("button", name="Open Files and diagnostics").click()
    page.locator('.result-file-row button[data-artifact-path="citations.bib"]').click()
    expect(page.locator(".result-preview")).to_contain_text("Wang_2024")
    download = page.locator(".result-preview-header a.result-button")
    expect(download).to_have_attribute(
        "href", f"/compute/api/demo/replays/{GREMLIN_SCENARIO}/artifacts/citations.bib?download=1"
    )
    expected = demo_replays[GREMLIN_SCENARIO].bundle.bundle["payloads"]["citations.bib"]["sha256"]
    fetched = _sha256(f"{ORIGIN}/compute/api/demo/replays/{GREMLIN_SCENARIO}/artifacts/citations.bib?download=1", page)
    assert fetched == expected


def test_demo_preview_only_submission_is_refused_by_the_server(
    page: Page, production_bundle: None, demo_replays: dict[str, Any]
) -> None:
    """Journey C: the disabled control and the Server's own independent refusal."""
    _mount_demo(page, demo_replays)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{ORIGIN}/compute/create_task?task_type=gremlin_lh_fit")

    expect(page.locator(".ct-workbench")).to_be_visible()
    action = page.locator(".ct-actions button.ct-primary")
    expect(action).to_have_text("Preview only — not executable here")
    expect(action).to_be_disabled()

    # A crafted client reaching the ordinary API is refused at the same boundary,
    # for both the preflight and the submit path. The preflight carries the
    # Server's projected envelope (the stable code is ``errors[].code`` and
    # admission is denied); the flat submit body names the code at the top level.
    for path in ("/compute/api/preflight/gremlin_lh_fit", "/compute/api/post"):
        result = page.evaluate(
            """async (url) => {
                const response = await fetch(url, {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: 'task_type=gremlin_lh_fit',
                });
                return { status: response.status, body: await response.json() };
            }""",
            f"{ORIGIN}{path}",
        )
        assert result["status"] == 403
        body = result["body"]
        assert body["valid"] is False
        if path.startswith("/compute/api/preflight/"):
            assert [finding["code"] for finding in body["errors"]] == ["demo_read_only"]
            assert body["admission"]["allowed"] is False
        else:
            assert body["code"] == "demo_read_only"

    # No queued or finished state is claimed anywhere, and the form stays put.
    expect(page.locator(".ct-status")).not_to_contain_text("Task queued")
    expect(page).to_have_url(re.compile(r"/compute/create_task\?task_type=gremlin_lh_fit$"))
    expect(page.locator(".result-workspace")).to_have_count(0)


def test_unknown_replay_scenario_reports_unavailable(
    page: Page, production_bundle: None, demo_replays: dict[str, Any]
) -> None:
    """An absent scenario is stated plainly; no workspace or manifest is invented."""
    router = _mount_demo(page, demo_replays)
    page.goto(f"{ORIGIN}/compute/demo/replays/not-installed")

    expect(page.locator(".demo-replay-page h1")).to_have_text("Recorded result unavailable")
    expect(page.locator(".demo-replay-page .empty-state")).to_have_text(
        "This replay scenario is not installed on this deployment."
    )
    expect(page.locator(".result-workspace")).to_have_count(0)
    assert router.requests.matching("/compute/api/demo/replays/not-installed") == ()


def test_a_replay_payload_the_bundle_does_not_retain_fails_visibly(
    page: Page, production_bundle: None, demo_replays: dict[str, Any]
) -> None:
    """A declared artifact with no captured bytes states the failure, not success."""
    _mount_demo(page, demo_replays)
    page.set_viewport_size({"width": 1440, "height": 1000})
    _open_replay(page)

    page.get_by_role("button", name="Open Files and diagnostics").click()
    row = page.locator(f'.result-file-row button[data-artifact-path="{EXCLUDED_LOG}"]')
    expect(row).to_be_visible()
    row.click()

    # The text renderer asked for the excluded route and stated the refusal; the
    # page did not keep an empty preview that would read as a successful load.
    expect(page.locator(".result-preview .result-empty")).to_have_text("Text preview could not be loaded.")
    expect(page.locator(".result-preview pre")).to_have_count(0)
    assert page.evaluate(
        """async (url) => (await fetch(url, { credentials: 'same-origin' })).status""",
        f"{ORIGIN}/compute/api/demo/replays/{GREMLIN_SCENARIO}/artifacts/{EXCLUDED_LOG}",
    ) == 404


def test_demo_landing_and_replay_are_navigable_at_mobile_width(
    page: Page, production_bundle: None, demo_replays: dict[str, Any]
) -> None:
    """The playground reflows at phone width and its card navigation still works."""
    _mount_demo(page, demo_replays)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{ORIGIN}/compute/demo")

    expect(page.locator(".demo-page h1")).to_be_visible()
    expect(page.locator(".demo-card", has_text="GREMLIN_LH Potts model")).to_be_visible()
    card = page.locator(".demo-card-replay", has=page.get_by_role("heading", name=re.compile("2KL8 alignment")))
    expect(card).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    card.get_by_role("link", name="Open recorded result").click()
    expect(page.locator(".demo-replay-banner h1")).to_be_visible()
    expect(page.locator(".demo-replay-banner .demo-provenance")).to_contain_text("Recorded result")
    expect(page.locator(".result-workspace")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_production_profile_offers_no_demo_affordances_or_replays(
    page: Page, production_bundle: None
) -> None:
    """The same bundle states production honestly and exposes no replay content."""
    mount_scenario(page, controlled_scenario().with_catalog([gremlin_lh_runner()]))
    page.goto(f"{ORIGIN}/runners")

    expect(page.locator(".runner-card")).to_have_count(2)
    expect(page.locator(".app-demo-badge")).to_be_hidden()
    expect(page.locator(".demo-notice")).to_have_count(0)
    served = page.evaluate(
        """async (url) => (await fetch(url, { credentials: 'same-origin' })).json()""",
        f"{ORIGIN}/compute/api/environment",
    )
    assert served == PRODUCTION_ENVIRONMENT
    assert page.evaluate(
        """async (url) => (await fetch(url, { credentials: 'same-origin' })).status""",
        f"{ORIGIN}/compute/api/demo/replays",
    ) == 404
