# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the BioEmu2 equilibrium storyboard on a real replay.

Drives the built production frontend -- the real ResultWorkspace, the real
storyboard host, the real trajectory view renderer, the real Mol* viewer and XTC
reader -- against the captured production result ``4d77ffcc...``. The capture's
manifest predates the Task's Storyboard declaration, so the test serves the
replayed manifest with the declaration read by the Server's own
``storyboard_declaration`` and the logical files resolved by the Server's own
``resolve_expected_files`` from the capture's published artifacts. Every other
byte -- views, artifact paths, payloads -- is the capture's.

Expected values are read from the bundle (``ReplayBundle``), not retyped: sample
count, physicality verdicts, file URLs and served bytes all come from the
captured manifest and payloads. Only the storyboard's own published wording is
a literal.

Download note: under Playwright, Chromium cancels a download whose response is
fulfilled by same-origin request interception. Measured against this fixture
router: the ``download`` event fires with the right URL, but
``Download.path()`` reports ``canceled``; real HTTP downloads, cross-origin
intercepted downloads, and blob downloads save normally. The repository's
other intercepted-fixture download tests therefore assert the event URL. This
test does the same and additionally hashes the bytes the same URL serves with
SHA-256, fetched in-page, against the captured payload hash.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from frontend_fixtures import ReplayBundle, RunnerDefinition, mount_scenario, replay_scenario
from frontend_fixtures.replay_bundle import project_manifest_for_serve
from playwright.sync_api import Page, expect

import browser_frontend_assets
from revocompute.result_storyboard import load_expected_file_tree, resolve_expected_files, storyboard_declaration

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "https://revocompute.example"
BUNDLE_PATH = ROOT / "tests" / "data" / "bioemu2_replay" / "2kl8_production_4d77ffcc.json"
RESULT_DIST = ROOT / "frontend" / "dist"
FAMILY = ROOT / "docker" / "runners" / "bioemu2"
CONTRACT = FAMILY / "tasks" / "bioemu2_equilibrium"
STORYBOARD = CONTRACT / "storyboard" / "index.js"

if not BUNDLE_PATH.is_file():
    pytest.skip("the captured BioEmu2 replay bundle is not present", allow_module_level=True)

UNPARSEABLE = "The physicality report could not be parsed as JSON."

SHA256_JS = """async (url) => {
  const response = await fetch(url, { credentials: 'same-origin' });
  const buffer = await response.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', buffer);
  return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('');
}"""


@pytest.fixture(autouse=True)
def _production_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve ``frontend/dist``: only that bundle carries the real Mol* viewer."""
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", RESULT_DIST)


def _replay() -> ReplayBundle:
    return ReplayBundle.load(BUNDLE_PATH)


def _runner() -> RunnerDefinition:
    """The catalog identity only; the result surface is the captured bundle."""
    return RunnerDefinition(
        name="bioemu2_equilibrium", display_name="BioEmu2 equilibrium ensemble",
        category="structure", category_label="Structure prediction",
        summary="Sample a protein equilibrium conformational ensemble with BioEmu2.",
        runtime_family="bioemu2",
    )


def _served_manifest(replay: ReplayBundle) -> dict:
    """The replayed manifest with the Task's Storyboard and logical files served.

    The capture carries its resolved logical files, but the Server's serving
    projection rebuilds ``result.files`` from the published artifact list and
    the Task's ``expected_files.yaml``. The test goes through that same
    projection (``resolve_expected_files`` then ``project_manifest_for_serve``)
    with the capture's own artifacts, and adds the Storyboard declaration read
    by the Server's own ``storyboard_declaration``. Every other byte -- views,
    artifact paths, payloads -- is the capture's.
    """
    declaration = storyboard_declaration(
        SimpleNamespace(runtime=SimpleNamespace(root=str(FAMILY), definition=""), task_dir="tasks/bioemu2_equilibrium"),
        str(ROOT), set(load_expected_file_tree(CONTRACT / "expected_files.yaml")),
    )
    assert declaration is not None
    tree = load_expected_file_tree(CONTRACT / "expected_files.yaml")
    resolved, _checks, problems = resolve_expected_files(tree, replay.manifest["artifacts"])
    assert not problems
    published = json.loads(json.dumps(replay.manifest))
    published["result"] = {"files": resolved}
    published["storyboard"] = declaration
    return project_manifest_for_serve(published)


def _open(page: Page, overrides: list[tuple[str, bytes]] | None = None) -> tuple[object, ReplayBundle]:
    """Open the real result page with the storyboard declared over the replay."""
    replay = _replay()
    router = mount_scenario(page, replay_scenario(_runner(), replay))
    served = _served_manifest(replay)
    # Registered after the router: Playwright matches routes in reverse order.
    page.route(
        f"{ORIGIN}/compute/api/results/{replay.task_id}",
        lambda route: route.fulfill(json=served),
    )
    page.route(
        f"{ORIGIN}{served['storyboard']['entrypoint_url']}",
        lambda route: route.fulfill(content_type="text/javascript", body=STORYBOARD.read_text(encoding="utf-8")),
    )
    # Same precedence rule: a negative override must outrank the router too.
    for url, body in overrides or []:
        def override(route: object, _request: object, payload: bytes = body) -> None:
            route.fulfill(status=200, content_type="application/json", body=payload)

        page.route(f"{ORIGIN}{url}", override)
    page.set_viewport_size({"width": 1280, "height": 1000})
    page.goto(f"{ORIGIN}/compute/results/{replay.task_id}")
    expect(page.locator(".be2-result")).to_be_visible(timeout=180_000)
    return router, replay


def _settled_canvas_digest(page: Page) -> str:
    """A digest of the rendered stage once two readings agree.

    Mol* commits frames asynchronously: a reading taken right after a step can
    capture a partially rendered stage. Poll until the digest stops moving.
    """
    previous = _canvas_digest(page)
    for _ in range(20):
        current = _canvas_digest(page)
        if current == previous:
            return current
        previous = current
    raise AssertionError("the Mol* stage never settled")


def _canvas_digest(page: Page) -> str:
    """A stable reading of the rendered stage, after Mol* has committed a frame."""
    page.wait_for_timeout(800)
    return page.evaluate(
        """() => {
          const canvas = document.querySelector('.be2-stage .structure-host canvas');
          const data = canvas.toDataURL('image/png');
          let hash = 2166136261;
          for (let i = 0; i < data.length; i += 1) { hash ^= data.charCodeAt(i); hash = Math.imul(hash, 16777619); }
          return `${data.length}:${hash >>> 0}`;
        }"""
    )


def _sample_count(replay: ReplayBundle) -> int:
    """Published samples: one physicality entry per sample upstream emitted."""
    return len(json.loads(replay.payload("physicality.json")[0]))


def test_the_hero_stage_mounts_the_declared_trajectory_view(page: Page) -> None:
    router, replay = _open(page)
    (view,) = replay.manifest["views"]
    assert (view["id"], view["plugin"], view["role"]) == ("conformational_ensemble", "trajectory", "primary")

    # The stage is the declared view mounted through the workspace's own
    # ``mountView``: with a single declared view, the trajectory renderer that
    # produced ``.trajectory-viewport`` inside ``.be2-stage`` can only have been
    # resolved from that view id by the real service.
    expect(page.locator(".be2-stage .trajectory-viewport")).to_have_count(1)
    expect(page.locator(".be2-stage .structure-host canvas").first).to_be_visible(timeout=180_000)
    expect(page.locator(".be2-stage .trajectory-status")).to_contain_text(
        f"{_sample_count(replay)} frames loaded", timeout=180_000
    )
    # Every declared source came from the replay artifact routes.
    for path in view["sources"]["topology"] + view["sources"]["coordinates"]:
        assert router.requests.matching(f"/compute/api/results/{replay.task_id}/artifacts/{path}"), path


def test_stepping_to_the_second_sample_changes_the_stage(page: Page) -> None:
    _, replay = _open(page)
    total = _sample_count(replay)
    assert total == 2
    expect(page.locator(".be2-stage .structure-host canvas").first).to_be_visible(timeout=180_000)
    expect(page.locator(".be2-stage .trajectory-status")).to_contain_text(f"{total} frames loaded", timeout=180_000)
    expect(page.locator(".be2-stage .trajectory-position")).to_contain_text(f"Sample index 1 of {total}")
    first = _settled_canvas_digest(page)

    page.locator(".be2-stage [data-trajectory=next]").click()
    expect(page.locator(".be2-stage .trajectory-position")).to_contain_text(f"Sample index 2 of {total}")
    second = _settled_canvas_digest(page)
    assert first != second, "the second published sample rendered the same stage as the first"

    page.locator(".be2-stage [data-trajectory=previous]").click()
    expect(page.locator(".be2-stage .trajectory-position")).to_contain_text(f"Sample index 1 of {total}")
    assert _settled_canvas_digest(page) == first, "stepping back did not restore the earlier sample"

    # Playback is reachable in the product: the control is enabled once the frames
    # are loaded, advances to the last declared sample, and stops there rather than
    # wrapping or claiming a physical time.
    play = page.locator(".be2-stage [data-trajectory=play]")
    expect(play).to_be_enabled()
    play.click()
    expect(page.locator(".be2-stage .trajectory-position")).to_contain_text(f"Sample index {total} of {total}", timeout=30_000)
    expect(play).to_have_text("Play")


def test_the_table_and_verdict_state_what_upstream_reported(page: Page) -> None:
    _, replay = _open(page)
    report = json.loads(replay.payload("physicality.json")[0])
    rows = page.locator(".be2-table tbody tr")
    expect(rows).to_have_count(len(report))
    for index, entry in enumerate(report):
        row = rows.nth(index)
        expect(row.locator("td").nth(0)).to_have_text(str(entry["frame"]))
        expect(row.locator("td").nth(1)).to_have_text(entry["status"])
        expect(row.locator("td").nth(2)).to_have_text(entry["reason"])
        expect(row.locator(".be2-state")).to_have_attribute("data-status", entry["status"])
    accepted = sum(1 for entry in report if entry["status"] == "passed")
    expect(page.locator("[data-bioemu2=physicality] dd")).to_have_text(f"{accepted} of {len(report)} accepted")


def test_the_hero_stage_and_the_verdict_table_share_the_first_screen(page: Page) -> None:
    _open(page)
    # At 1280 wide the navigation rail leaves a 969px content column, under the
    # storyboard's 980px container breakpoint, so the declared two-column hero
    # only exists with the rail collapsed. That user preference is exercised
    # here so the claim is about the storyboard's layout, not the shell's.
    page.get_by_role("button", name="Collapse navigation").click()
    page.wait_for_timeout(500)
    stage = page.locator(".be2-stage")
    table = page.locator(".be2-table")
    expect(stage).to_be_visible()
    expect(table).to_be_visible()
    assert page.evaluate("window.scrollY") == 0
    height = page.viewport_size["height"]
    # The hero row is ~837px tall, so a 1000px first screen with the ~476px of
    # page chrome above it cannot contain the whole stage: the claim is that
    # the stage is on screen and the per-sample verdict table is fully on
    # screen, which is what the storyboard's own comment declares.
    stage_box = stage.bounding_box()
    table_box = table.bounding_box()
    assert stage_box is not None and table_box is not None
    assert 0 <= stage_box["y"] < height, stage_box
    assert 0 <= table_box["y"] and table_box["y"] + table_box["height"] <= height, (table_box, height)
    assert table_box["y"] < stage_box["y"] + stage_box["height"], "the table is not beside the stage"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_the_six_downloads_serve_the_captured_bytes(page: Page) -> None:
    _, replay = _open(page)
    files = replay.manifest["result"]["files"]
    buttons = page.locator(".be2-downloads button")
    expect(buttons).to_have_count(6)
    assert set(files) == {
        button.get_attribute("data-download") for button in buttons.all()
    }
    for file_id, (file,) in files.items():
        button = page.locator(f".be2-downloads button[data-download={file_id}]")
        expect(button).to_be_enabled()
        with page.expect_download() as download:
            button.click()
        assert download.value.url == f"{ORIGIN}{file['url']}", file_id
        path = replay.logical_artifact_path(file_id, 0)
        assert path is not None, file_id
        expected = hashlib.sha256(replay.payload(path)[0]).hexdigest()
        served = page.evaluate(SHA256_JS, file["url"])
        assert served == expected, file_id


def test_the_page_raises_no_unhandled_or_console_error(page: Page) -> None:
    page_errors: list[str] = []
    console_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    _open(page)
    page.locator(".be2-stage [data-trajectory=next]").click()
    expect(page.locator(".be2-stage .trajectory-position")).to_contain_text("Sample index 2 of 2")
    page.wait_for_timeout(1500)
    assert page_errors == []
    assert console_errors == []


def test_an_unparseable_physicality_report_names_the_problem_and_keeps_the_ensemble(page: Page) -> None:
    replay = _replay()
    served = _served_manifest(replay)
    file_url = served["result"]["files"]["physicality"][0]["url"]
    _open(page, overrides=[(file_url, b"not json")])

    expect(page.locator(".be2-table-wrap .be2-empty")).to_have_text(UNPARSEABLE)
    expect(page.locator(".be2-stage .structure-host canvas").first).to_be_visible(timeout=180_000)
    expect(page.locator(".be2-downloads button[data-download=coordinates]")).to_be_enabled()
