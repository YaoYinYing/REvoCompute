# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance against a replayed real GREMLIN_LH result.

This drives the built production frontend against the captured real 2KL8 result
bundle (task ``944ed43a...``) served through the PR #38 fixture boundary. It is
the complement of ``test_playwright_gremlin_golden_acceptance.py``: that test
stages the raw run from a local directory the operator supplies, while this one
replays a checked-in, sanitized bundle through the same router the synthetic
scenarios use, so no operator staging directory is required.

The assertions state renderer semantics and file/task identity, not incidental
CSS structure: the declared views mount, the matrices read the real table bytes,
the ranked-pairs table consumes the real table, the storyboard reads the real
statistics, and a download returns the exact captured bytes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from frontend_fixtures import (
    ReplayBundle,
    gremlin_lh_runner,
    mount_scenario,
    replay_scenario,
)
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://revocompute.example"
BUNDLE_PATH = ROOT / "tests" / "data" / "gremlin_lh_replay" / "2kl8_seed0_944ed43af62e.json"

if not BUNDLE_PATH.is_file():
    pytest.skip("the captured GREMLIN_LH replay bundle is not present", allow_module_level=True)

TASK_ID = "944ed43af62ead9f5c9560bae1ccd897"


def _replay() -> ReplayBundle:
    return ReplayBundle.load(BUNDLE_PATH)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mount(page: Page) -> ReplayBundle:
    replay = _replay()
    mount_scenario(page, replay_scenario(gremlin_lh_runner(), replay))
    return replay


def _open(page: Page) -> None:
    page.goto(f"{ORIGIN}/compute/results/{TASK_ID}")
    expect(page.locator(".result-workspace, .glh-result, .result-status").first).to_be_visible()


def test_replayed_result_mounts_every_declared_view(page: Page) -> None:
    _mount(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)

    # The task identity the URL carried is the captured identity, not a fixture id.
    expect(page.locator(".result-meta")).to_contain_text(TASK_ID)
    # The storyboard declares a primary surface, so it opens the page and each
    # declared view keeps its own tab.
    expect(page.locator(".result-tab", has_text="Scientific result")).to_be_visible()
    for title in (
        "Coupling strength (raw Frobenius)",
        "Coupling strength (average-product corrected)",
        "Ranked residue pairs",
        "Filtered alignment",
        "Model fit summary",
    ):
        expect(page.locator(".result-tab", has_text=title)).to_be_visible()


def test_replayed_matrices_read_the_real_table_bytes(page: Page) -> None:
    requests = mount_scenario(page, replay_scenario(gremlin_lh_runner(), _replay())).requests
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)

    page.locator(".result-tab", has_text="Coupling strength (raw Frobenius)").click()
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()
    raw_calls = requests.matching(f"/compute/api/results/{TASK_ID}/tables/couplings/raw_scores.csv")
    assert raw_calls, "the matrix renderer never queried the replayed table route"
    assert all("matrix=1" in record.query for record in raw_calls)

    page.locator(".result-tab", has_text="Coupling strength (average-product corrected)").click()
    expect(page.locator(".pair-matrix-view canvas")).to_be_visible()
    apc_calls = requests.matching(f"/compute/api/results/{TASK_ID}/tables/couplings/apc_scores.csv")
    assert apc_calls, "the APC matrix renderer never queried the replayed table route"
    # APC scores are signed after correction, so this view keeps a diverging scale.
    expect(page.locator(".pair-matrix-title", has_text="(negative → positive)")).to_be_visible()


def test_replayed_ranked_pairs_table_consumes_the_real_table(page: Page) -> None:
    requests = mount_scenario(page, replay_scenario(gremlin_lh_runner(), _replay())).requests
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)

    page.locator(".result-tab", has_text="Ranked residue pairs").click()
    table = page.locator(".result-preview table").first
    expect(table).to_be_visible()
    # The header row comes from the captured TSV, not a fixture.
    expect(table.locator("th", has_text="alignment_i")).to_be_visible()
    assert requests.matching(f"/compute/api/results/{TASK_ID}/tables/couplings/pairwise_scores.tsv"), (
        "the ranked-pairs view never read the replayed table"
    )


def test_replayed_alignment_renders_the_captured_artifact(page: Page) -> None:
    _mount(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)

    page.locator(".result-tab", has_text="Filtered alignment").click()
    preview = page.locator(".result-preview")
    expect(preview).to_contain_text("2KL8")


def test_replayed_storyboard_reads_the_real_statistics(page: Page) -> None:
    _mount(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)

    # The storyboard's own h2 (the header carries the same method name).
    expect(page.locator(".glh-result h2")).to_have_text("GREMLIN_LH Potts model")
    # Values that exist only in the real captured artifacts.
    expect(page.get_by_text("Columns excluded from weighting", exact=True)).to_be_visible()
    expect(page.get_by_text("3 positions", exact=True)).to_be_visible()
    expect(page.get_by_text("Effective sequence count (Neff)", exact=True)).to_be_visible()
    expect(page.locator(".glh-unavailable")).to_have_count(0)


def test_replayed_download_returns_the_exact_captured_bytes(page: Page) -> None:
    replay = _mount(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)

    # Fetch one captured artifact through the served route and compare its bytes
    # to the bundle's own recorded hash, byte for byte.
    path = "couplings/raw_scores.csv"
    expected = replay.bundle["payloads"][path]["sha256"]
    fetched = page.evaluate(
        """async (url) => {
            const response = await fetch(url, { credentials: 'same-origin' });
            const buffer = await response.arrayBuffer();
            const digest = await crypto.subtle.digest('SHA-256', buffer);
            return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('');
        }""",
        f"{ORIGIN}/compute/api/results/{TASK_ID}/artifacts/{path}?download=0",
    )
    assert fetched == expected


def test_replayed_result_raises_no_console_or_csp_error(page: Page) -> None:
    errors: list[str] = []
    page.on("console", lambda message: errors.append(f"console.{message.type}: {message.text}") if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    mount_scenario(page, replay_scenario(gremlin_lh_runner(), _replay()))
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page)
    expect(page.locator(".result-tab", has_text="Scientific result")).to_be_visible()
    violations = page.evaluate("window.__cspViolations || []")
    assert errors == [], errors
    assert violations == [], violations


def test_replayed_task_scope_is_enforced_for_a_mismatched_id(page: Page) -> None:
    """An artifact request for a different task id must not be served."""
    _mount(page)
    # Drive from the page so the request stays same-origin; the router returns the
    # same 404 a real deployment would for an id it does not own.
    status = page.evaluate(
        """async (url) => (await fetch(url, { credentials: 'same-origin' })).status""",
        f"{ORIGIN}/compute/api/results/{'f' * 32}/artifacts/couplings/raw_scores.csv",
    )
    assert status == 404
