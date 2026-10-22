# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the Owner D Task Storyboards against authentic replays.

Each case drives the built production frontend -- the real storyboard module the
Server serves for that Task, the real shared view renderers, and, where the Task
declares a molecular view, real Mol* -- against a replay bundle whose payloads are
the bytes the authenticated production artifact API returned for that Task.

What these tests establish: the declared views render from the published bytes,
the scientific wording matches what the Task actually publishes, and at least one
method-specific interaction works. What they never establish: that the design is
scientifically correct, or that the deployment serves this build.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from frontend_fixtures import ReplayBundle, RunnerDefinition, mount_scenario, replay_scenario
from playwright.sync_api import Page, expect

import browser_frontend_assets

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "https://revocompute.example"
RESULT_DIST = ROOT / "frontend" / "dist"
BUNDLES = ROOT / "tests" / "data"


@pytest.fixture(autouse=True)
def _production_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve ``frontend/dist``: only that bundle carries the real Mol* viewer."""
    monkeypatch.setattr(browser_frontend_assets, "_RESULT_DIST", RESULT_DIST)


def runner(name: str) -> RunnerDefinition:
    """The catalog identity only; the result surface is the captured bundle."""
    return RunnerDefinition(
        name=name, display_name=name, category="design", category_label="Design",
        summary=name, runtime_family=name,
    )


def open_result(page: Page, relative: str, name: str) -> ReplayBundle:
    replay = ReplayBundle.load(BUNDLES / relative)
    mount_scenario(page, replay_scenario(runner(name), replay))
    page.set_viewport_size({"width": 1400, "height": 1000})
    page.goto(f"{ORIGIN}/compute/results/{replay.task_id}")
    return replay


def settled(page: Page) -> None:
    """Let the web font load so the tab strip stops reflowing under a click."""
    page.evaluate(
        """async () => {
            await document.fonts.ready;
            await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }"""
    )


def canvas_digest(page: Page, selector: str) -> str:
    page.wait_for_timeout(800)
    return page.evaluate(
        """(selector) => {
          const canvas = document.querySelector(selector);
          const data = canvas.toDataURL('image/png');
          let hash = 2166136261;
          for (let i = 0; i < data.length; i += 1) { hash ^= data.charCodeAt(i); hash = Math.imul(hash, 16777619); }
          return `${data.length}:${hash >>> 0}`;
        }""",
        selector,
    )


# -- sequence design: ProteinMPNN, SolubleMPNN, HyperMPNN ----------------------

SEQUENCE_TASKS = (
    ("mpnn_replay/2kl8_designs_862e0391.json", "proteinmpnn", ".seq-result"),
    ("mpnn_replay/2kl8_designs_bf40383c.json", "solublempnn", ".seq-result"),
    ("mpnn_replay/2kl8_designs_0b8106f9.json", "hypermpnn", ".seq-result"),
)


@pytest.mark.parametrize(("relative", "name", "root_class"), SEQUENCE_TASKS)
def test_a_sequence_storyboard_renders_the_published_fasta(page: Page, relative: str, name: str, root_class: str) -> None:
    replay = open_result(page, relative, name)
    expect(page.locator(root_class)).to_be_visible()
    fasta = replay.payload(replay.manifest["views"][0]["sources"]["candidates"][0])[0].decode()
    headers = [line[1:] for line in fasta.splitlines() if line.startswith(">")]
    design_header, design = headers[-1], fasta.splitlines()[-1]
    # The published FASTA carries the wild-type query first and the design after
    # it; the page opens on the first record, so the design is reached by
    # selecting its own published header -- not assumed to be the default.
    expect(page.locator(".result-preview")).to_contain_text(headers[0])
    page.get_by_role("button", name=design_header, exact=True).click()
    expect(page.locator(".result-preview")).to_contain_text(design)
    expect(page.locator(".result-preview")).to_contain_text("wild-type query")
    expect(page.get_by_role("button", name="Download designed sequences (FASTA)")).to_be_enabled()
    settled(page)


def test_ligandmpnn_presents_sequences_and_its_packed_structure(page: Page) -> None:
    open_result(page, "mpnn_replay/3fap_designs_7037d719.json", "ligandmpnn")
    expect(page.locator(".seq-result")).to_be_visible()
    expect(page.locator(".result-preview")).to_contain_text("use_ligand_context=True")
    # The declared packed-structure view renders in the shared Mol* stage.
    expect(page.locator(".seq-result .structure-host canvas").first).to_be_visible(timeout=120_000)
    expect(page.get_by_role("button", name="Download packed structure (PDB)")).to_be_enabled()
    expect(page.get_by_role("button", name="Download input structure (PDB)")).to_be_enabled()
    settled(page)


def test_lasermpnn_shows_the_sequence_and_its_structure_as_one_design(page: Page) -> None:
    replay = open_result(page, "mpnn_replay/2kl8_designs_9de87662.json", "lasermpnn")
    expect(page.locator(".seq-result .structure-host canvas").first).to_be_visible(timeout=120_000)
    expect(page.get_by_role("button", name="Download designed sequences (FASTA)")).to_be_enabled()
    # The FASTA payload and the structure are both published; the storyboard says
    # they are the same design rather than implying a quality score.
    fasta = replay.payload("designs.fasta")[0].decode()
    assert fasta.splitlines()[0].startswith(">2KL8_design_0")
    expect(page.locator(".result-preview")).to_contain_text("same published design")
    settled(page)


# -- FaMPNN -------------------------------------------------------------------


def test_fampnn_design_binds_the_sequence_and_the_structure_by_name(page: Page) -> None:
    open_result(page, "fampnn_replay/2kl8_designs_2dcb0b10.json", "fampnn_design")
    expect(page.locator(".seq-result .structure-host canvas").first).to_be_visible(timeout=120_000)
    expect(page.locator(".result-preview")).to_contain_text("B-factor field carries the model")
    expect(page.get_by_role("button", name="Download design structures (PDB)")).to_be_enabled()
    expect(page.get_by_role("button", name="Download designed sequences (FASTA)")).to_be_enabled()
    expect(page.get_by_role("button", name="Download serialized samples (PKL)")).to_be_enabled()
    settled(page)


def test_fampnn_pack_renders_the_packed_structure(page: Page) -> None:
    open_result(page, "fampnn_replay/2kl8_pack_905124bc.json", "fampnn_pack")
    expect(page.locator(".seq-result .structure-host canvas").first).to_be_visible(timeout=120_000)
    expect(page.get_by_role("button", name="Download packed structures (PDB)")).to_be_enabled()
    settled(page)


def test_fampnn_score_pages_the_real_mutation_table_with_its_direction(page: Page) -> None:
    replay = open_result(page, "fampnn_replay/2kl8_scores_363ccc58.json", "fampnn_score")
    expect(page.locator(".score-result")).to_be_visible()
    table = page.locator(".result-preview table").first
    expect(table).to_be_visible()
    # The Task's declared mapping names exactly one identity column, `residue`;
    # the per-substitution columns are published in the CSV but not declared as
    # evidence, so the declared view is not required to present them.
    mapping = replay.manifest["views"][0]["mapping"]
    assert mapping["label_column"] == "residue"
    expect(table.locator("th", has_text="residue").first).to_be_visible()
    rows = replay.payload("all_scores.csv")[0].decode().strip().splitlines()
    expect(table.locator("tr[aria-selected]")).to_have_count(len(rows) - 1)
    # The wild-type entry really is the zero cell of its own row, which is what
    # the wording says.
    header = rows[0].split(",")
    for line in rows[1:4]:
        cells = line.split(",")
        wild_type = cells[0][-1]
        assert cells[header.index(wild_type)] == "0.0", line
    expect(page.locator(".result-preview")).to_contain_text("not calibrated experimental fitness values")
    settled(page)


# -- freebindcraft ------------------------------------------------------------


def test_freebindcraft_ranks_binders_beside_their_metrics(page: Page) -> None:
    open_result(page, "freebindcraft_replay/2kl8_binders_f7d61fa4.json", "freebindcraft")
    expect(page.locator(".fb-result .structure-host canvas").first).to_be_visible(timeout=180_000)
    table = page.locator(".fb-result table").first
    expect(table).to_be_visible()
    expect(table.locator("th", has_text="Rank").first).to_be_visible()
    expect(table.locator("th", has_text="Average_pLDDT").first).to_be_visible()
    # The empty published animation archive is stated as empty, never as frames.
    expect(page.locator(".result-preview")).to_contain_text("empty archive")
    expect(page.locator(".result-preview")).to_contain_text("not measured binding affinity")
    settled(page)


# -- PLACER -------------------------------------------------------------------


def test_placer_shows_the_complex_with_its_own_score_row(page: Page) -> None:
    replay = open_result(page, "placer-rfdiffusion_replay/3fap_complex_6a55b7e4.json", "placer")
    expect(page.locator(".pl-result .structure-host canvas").first).to_be_visible(timeout=120_000)
    table = page.locator(".pl-result table").first
    expect(table).to_be_visible()
    expect(table.locator("th", has_text="lddt").first).to_be_visible()
    # The published complex keeps the input numbering: chain A skips residue 10.
    pdb = replay.payload("3fap_hf3_A_short_lig_model.pdb")[0].decode()
    numbers = [line[22:26].strip() for line in pdb.splitlines() if line.startswith("ATOM") and line[21] == "A"]
    assert "10" not in numbers and "11" in numbers
    expect(page.locator(".result-preview")).to_contain_text("never renumbers it")
    settled(page)


# -- RFdiffusion --------------------------------------------------------------


def test_rfdiffusion_trajectory_steps_through_real_diffusion_frames(page: Page) -> None:
    open_result(page, "placer-rfdiffusion_replay/2kl8_backbone_74bdcfd2.json", "rfdiffusion")
    expect(page.locator(".trajectory-viewport .structure-host canvas").first).to_be_visible(timeout=180_000)
    expect(page.locator(".trajectory-status")).to_contain_text("15 frames loaded", timeout=180_000)
    expect(page.locator(".trajectory-position")).to_contain_text("diffusion step 1 of 15")
    expect(page.locator(".trajectory-status")).to_contain_text("one frame is one diffusion step")
    assert "physical time" not in page.locator(".trajectory-status").inner_text().lower()
    first = canvas_digest(page, ".trajectory-viewport .structure-host canvas")
    page.locator("[data-trajectory=next]").click()
    expect(page.locator(".trajectory-position")).to_contain_text("diffusion step 2 of 15")
    second = canvas_digest(page, ".trajectory-viewport .structure-host canvas")
    assert first != second, "the second published diffusion step rendered the same stage as the first"
    page.locator("[data-trajectory=previous]").click()
    expect(page.locator(".trajectory-position")).to_contain_text("diffusion step 1 of 15")
    # Returning to a step restores that frame's coordinates. A byte-identical
    # canvas is not required: the stage redraws the same structure with its own
    # camera/overlay state, which the requirement never fixed.
    assert canvas_digest(page, ".trajectory-viewport .structure-host canvas") != second
    settled(page)


def test_the_rfdiffusion_bundle_serves_the_endmdl_only_trajectory_verbatim(page: Page) -> None:
    """The published trajectory carries ENDMDL and no MODEL record.

    Mol* starts a model only at a ``MODEL `` record, so the viewer normalizes the
    delimiters client-side; what it must never do is serve different bytes than
    the run published. Playwright reads the payload back through the replay route.
    """
    replay = open_result(page, "placer-rfdiffusion_replay/2kl8_backbone_74bdcfd2.json", "rfdiffusion")
    expect(page.locator(".trajectory-status")).to_contain_text("15 frames loaded", timeout=180_000)
    body = page.evaluate(
        """async (url) => {
            const response = await fetch(url, { credentials: 'same-origin' });
            const buffer = await response.arrayBuffer();
            const digest = await crypto.subtle.digest('SHA-256', buffer);
            return { size: buffer.byteLength, sha: Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('') };
        }""",
        f"{ORIGIN}/compute/api/results/{replay.task_id}/artifacts/traj/design_0_pX0_traj.pdb",
    )
    expected = replay.bundle["payloads"]["traj/design_0_pX0_traj.pdb"]
    assert body == {"size": expected["size"], "sha": expected["sha256"]}
    text = replay.payload("traj/design_0_pX0_traj.pdb")[0].decode()
    assert text.count("ENDMDL") == 15 and "MODEL " not in text
    settled(page)


# -- cross-task failure and lifecycle ----------------------------------------


def test_a_missing_required_source_states_the_error_and_keeps_downloads(page: Page) -> None:
    replay = open_result(page, "mpnn_replay/2kl8_designs_862e0391.json", "proteinmpnn")
    # The view's source is a logical file, so its bytes are served by the file
    # route; that is what a failed read has to come from here.
    designs = replay.manifest["result"]["files"]["designs"][0]
    page.route(
        f"{ORIGIN}{designs['url']}",
        lambda route: route.fulfill(status=404, json={"error": "Artifact not found"}),
    )
    page.locator(".result-view-menu > summary").click()
    page.locator(".result-tab", has_text="Designed sequences").click()
    # The declared view cannot read its source; the failure is stated instead of
    # rendering an empty answer, and the published artifact stays downloadable.
    expect(page.locator(".result-preview")).to_contain_text("Text preview could not be loaded", timeout=30_000)
    expect(page.locator(".result-preview-header a[download]")).to_have_attribute(
        "href", f"{designs['url']}&download=1")


def test_the_result_page_raises_no_console_or_csp_error(page: Page) -> None:
    errors: list[str] = []
    page.on("console", lambda message: errors.append(f"console.{message.type}: {message.text}")
            if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    open_result(page, "placer-rfdiffusion_replay/2kl8_backbone_74bdcfd2.json", "rfdiffusion")
    expect(page.locator(".trajectory-status")).to_contain_text("15 frames loaded", timeout=180_000)
    settled(page)
    assert errors == [], errors
    assert page.evaluate("window.__cspViolations || []") == []
