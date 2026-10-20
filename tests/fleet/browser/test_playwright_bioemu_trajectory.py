# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for a replayed real BioEmu ensemble result.

Drives the built production frontend (real Mol*, a real XTC reader and a real
WebGL stage) against the captured production result ``115a4a8a...``. The
declared primary ``trajectory`` view must render from both of its sources, label
the frame axis as a sample index, and actually change the rendered structure
between two published samples. The checked-in storyboard is mounted separately
against the same authentic artifacts, because the production manifest predates
the storyboard declaration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from frontend_fixtures import ReplayBundle, bioemu_runner, mount_scenario, replay_scenario
from frontend_fixtures.replay_bundle import project_manifest_for_serve
from playwright.sync_api import Page, expect

import browser_frontend_assets
from revocompute.result_storyboard import load_expected_file_tree, resolve_expected_files

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "https://revocompute.example"
BUNDLE_PATH = ROOT / "tests" / "data" / "bioemu_replay" / "2kl8_production_115a4a8a.json"
RESULT_DIST = ROOT / "frontend" / "dist"
STORYBOARD = ROOT / "docker" / "runners" / "bioemu" / "tasks" / "bioemu" / "storyboard" / "index.js"

if not BUNDLE_PATH.is_file():
    pytest.skip("the captured BioEmu replay bundle is not present", allow_module_level=True)

TASK_ID = "115a4a8af225b37c002f1c1a88e9d82c"
# mdtraj reads the published XTC as 23 frames; the 24 requested samples lost one
# to BioEmu's physical-validity filter.
FRAME_COUNT = 23


@pytest.fixture(autouse=True)
def _production_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve ``frontend/dist``, the only bundle with the real Mol* viewer.

    The harness's dist is process-global, so it is installed through
    ``monkeypatch``; a bare assignment would leak the production bundle into
    every later browser case in the session.
    """
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", RESULT_DIST)


def _replay() -> ReplayBundle:
    return ReplayBundle.load(BUNDLE_PATH)


def _open(page: Page) -> None:
    mount_scenario(page, replay_scenario(bioemu_runner(), _replay()))
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")
    # The primary view opens the page; the real Mol* canvas mounts asynchronously.
    expect(page.locator(".trajectory-viewport .structure-host canvas").first).to_be_visible(timeout=180_000)
    expect(page.locator(".trajectory-status")).to_contain_text(f"{FRAME_COUNT} frames", timeout=180_000)


def _canvas_digest(page: Page) -> str:
    """A stable reading of the rendered stage, after Mol* has committed a frame."""
    page.wait_for_timeout(800)
    return page.evaluate(
        """() => {
          const canvas = document.querySelector('.trajectory-viewport .structure-host canvas');
          const data = canvas.toDataURL('image/png');
          let hash = 2166136261;
          for (let i = 0; i < data.length; i += 1) { hash ^= data.charCodeAt(i); hash = Math.imul(hash, 16777619); }
          return `${data.length}:${hash >>> 0}`;
        }"""
    )


def test_the_declared_trajectory_view_renders_both_sources(page: Page) -> None:
    requests = mount_scenario(page, replay_scenario(bioemu_runner(), _replay())).requests
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")

    expect(page.locator(".trajectory-viewport .structure-host canvas").first).to_be_visible(timeout=180_000)
    expect(page.locator(".trajectory-status")).to_contain_text(f"{FRAME_COUNT} frames", timeout=180_000)
    # The frame axis is the mapping's own ``frame_unit: sample``: a sample index
    # with no physical time anywhere in the label.
    position = page.locator(".trajectory-position")
    expect(position).to_contain_text("Sample index 1 of 23")
    scrubber = page.locator(".trajectory-scrubber")
    expect(scrubber).to_have_attribute("aria-label", "Sample index")
    expect(scrubber).to_have_attribute("max", str(FRAME_COUNT))
    expect(page.locator(".trajectory-status")).to_contain_text("Sample order is not physical time")
    # Both declared sources were fetched from the replay routes, not one of them.
    for path in ("topology.pdb", "samples.xtc"):
        assert requests.matching(f"/compute/api/results/{TASK_ID}/artifacts/{path}"), path


def test_two_samples_render_different_coordinates(page: Page) -> None:
    _open(page)
    first = _canvas_digest(page)

    page.locator("[data-trajectory=next]").click()
    expect(page.locator(".trajectory-position")).to_contain_text("Sample index 2 of 23")
    second = _canvas_digest(page)
    assert first != second, "the second published sample rendered the same stage as the first"

    page.locator("[data-trajectory=next]").click()
    expect(page.locator(".trajectory-position")).to_contain_text("Sample index 3 of 23")
    third = _canvas_digest(page)
    assert third != second, "the third published sample rendered the same stage as the second"

    page.locator("[data-trajectory=previous]").click()
    expect(page.locator(".trajectory-position")).to_contain_text("Sample index 2 of 23")
    assert _canvas_digest(page) == second, "stepping back did not restore the earlier frame"


def test_the_scrubber_sets_a_sample_directly(page: Page) -> None:
    _open(page)
    scrubber = page.locator(".trajectory-scrubber")
    scrubber.fill("12")
    expect(page.locator(".trajectory-position")).to_contain_text("Sample index 12 of 23")
    scrubber.fill("1")
    expect(page.locator(".trajectory-position")).to_contain_text("Sample index 1 of 23")


def test_both_sources_remain_downloadable(page: Page) -> None:
    _open(page)
    download = page.locator(".result-preview-header").get_by_role("link", name="Download samples.xtc")
    expect(download).to_have_attribute("href", f"/compute/api/results/{TASK_ID}/artifacts/samples.xtc?download=1")
    # The topology is not the header's primary artifact; it stays reachable from
    # the Files list and serves its exact captured bytes.
    page.get_by_role("button", name="Open Files and diagnostics", exact=True).click()
    expect(page.get_by_label("Download topology.pdb")).to_be_visible()
    status = page.evaluate(
        """async (url) => {
          const response = await fetch(url, { credentials: 'same-origin' });
          const bytes = new Uint8Array(await response.arrayBuffer());
          const digest = await crypto.subtle.digest('SHA-256', bytes);
          return { status: response.status, size: bytes.length,
                   sha: Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('') };
        }""",
        f"{ORIGIN}/compute/api/results/{TASK_ID}/artifacts/topology.pdb",
    )
    assert status == {
        "status": 200,
        "size": 31702,
        "sha": "45b172920650c482cd06cbfd6a5d5f93a7228dd46da7070e8169b8914946f9e1",
    }


def test_a_missing_topology_states_the_error_and_keeps_the_download(page: Page) -> None:
    _open(page)
    page.route(
        f"{ORIGIN}/compute/api/results/{TASK_ID}/artifacts/topology.pdb",
        lambda route: route.fulfill(status=404, json={"error": "Artifact not found"}),
    )
    # Re-open the primary view so the renderer fetches both sources again.
    page.locator(".result-view-menu > summary").click()
    page.locator(".result-tab", has_text="Sampled conformational ensemble").click()

    expect(page.locator(".result-note", has_text="Topology download failed (HTTP 404).")).to_be_visible(timeout=180_000)
    expect(page.locator(".result-preview-header").get_by_role("link", name="Download samples.xtc")).to_be_visible()


def test_a_corrupted_xtc_states_the_error_and_keeps_the_download(page: Page) -> None:
    _open(page)
    page.route(
        f"{ORIGIN}/compute/api/results/{TASK_ID}/artifacts/samples.xtc",
        lambda route: route.fulfill(status=200, content_type="application/octet-stream", body=b"not an xtc"),
    )
    page.locator(".result-view-menu > summary").click()
    page.locator(".result-tab", has_text="Sampled conformational ensemble").click()

    # Mol* refuses the coordinate stream; the workspace states its explicit
    # fallback and the downloads stay reachable.
    expect(page.locator(".result-note", has_text="View shown as a plain artifact instead:")).to_be_visible(timeout=180_000)
    expect(page.locator(".result-preview-header").get_by_role("link", name="Download samples.xtc")).to_be_visible()


def test_teardown_removes_the_stage_when_another_artifact_opens(page: Page) -> None:
    _open(page)
    expect(page.locator(".trajectory-viewport")).to_have_count(1)
    page.get_by_role("button", name="Open Files and diagnostics", exact=True).click()
    page.locator(".result-file-open", has_text="topology.pdb").click()
    expect(page.locator(".trajectory-viewport")).to_have_count(0)


def test_the_storyboard_composes_the_shared_trajectory_view(page: Page) -> None:
    """The checked-in storyboard module, mounted against the authentic bundle.

    The production manifest predates the storyboard, so ``result.files`` is
    empty in the capture. The logical files are therefore resolved by the
    Server's own contract resolver from the checked-in ``expected_files.yaml``
    and projected by the same route implementation the API uses; only the
    manifest's inability to name them is synthetic. ``mountView`` is a recording
    stand-in: the storyboard must delegate the trajectory to the declared view
    instead of mounting its own stage.
    """
    replay = _replay()
    manifest = replay.manifest
    tree = load_expected_file_tree(STORYBOARD.parents[1] / "expected_files.yaml")
    resolved, _checks, problems = resolve_expected_files(tree, manifest["artifacts"])
    assert not problems
    published = json.loads(json.dumps(manifest))
    published["result"] = {"files": resolved}
    served = project_manifest_for_serve(published, task_id=TASK_ID)
    mount_scenario(page, replay_scenario(bioemu_runner(), replay))
    page.set_content("<div id='host'></div>")
    source = STORYBOARD.read_text(encoding="utf-8")
    page.evaluate(
        """async (payload) => {
          const url = URL.createObjectURL(new Blob([payload.source], { type: 'text/javascript' }));
          const module = await import(url);
          const files = new Map(Object.entries(payload.files));
          window.__mounted = [];
          window.__downloads = [];
          await module.default.mount(document.getElementById('host'), {
            files: { get: (id) => files.get(id) || null },
            metadata: { taskType: payload.taskType },
            views: payload.views,
            services: {
              mountView: async (viewId, host, signal) => {
                window.__mounted.push(viewId);
                const notice = document.createElement('p');
                notice.className = 'trajectory-status';
                notice.textContent = '23 frames loaded.';
                host.append(notice);
                return { frameCount: 23, destroy() { host.replaceChildren(); } };
              },
              downloadFile: (file) => window.__downloads.push(file.url),
            },
          });
        }""",
        {"source": source, "views": served["views"], "files": served["result"]["files"], "taskType": served["task_type"]},
    )
    expect(page.locator(".be-result")).to_be_visible()
    assert page.evaluate("window.__mounted") == ["conformational_ensemble"]
    # The storyboard states the published sample count, the scientific caution,
    # and the fact that the validity filter removed samples.
    expect(page.locator("[data-bioemu=published-samples]")).to_contain_text("23 samples")
    expect(page.get_by_text("not measured kinetics or calibrated thermodynamic populations", exact=False)).to_be_visible()
    expect(page.get_by_text("physical-validity filter", exact=False)).to_be_visible()
    # Full downloads for the XTC and the topology stay reachable even though the
    # inline view is composed from the shared renderer.
    page.get_by_role("button", name="Download sampled frames (XTC)").click()
    page.get_by_role("button", name="Download topology (PDB)").click()
    assert len(page.evaluate("window.__downloads")) == 2


