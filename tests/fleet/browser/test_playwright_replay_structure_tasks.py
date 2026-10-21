# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance against replayed real results for the structure Tasks.

Each case drives the built production frontend against a bounded replay bundle
of a real production run of that Task, served through the same router the
synthetic scenarios use. The bundle supplies the result surface -- manifest,
artifact bytes, logical files, projections, storyboard source -- and each
Runner's declared catalog identity is transcribed locally so the matrix module
does not depend on a shared scenario helper another PR owns.

The assertions are renderer semantics against the captured bytes: the storyboard
opens on the captured result, the declared views keep their tabs, the values
shown are the ones in the captured artifacts (not fixture guesses), the
confidence primitives read the real projections, and a download returns the
exact captured bytes. Nothing here claims the predictions are scientifically
correct; see each ``tests/data/<family>_replay/README.md`` for what was captured.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from frontend_fixtures import ReplayBundle, mount_scenario, replay_scenario
from frontend_fixtures.models import InputRole, RunnerDefinition
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "https://revocompute.example"

BUNDLES = {
    "alphafold": "tests/data/alphafold_replay/2kl8_production_51d8c875.json",
    "alphafold3": "tests/data/alphafold3_replay/tiny_production_4fed6908.json",
    "colabfold_af2": "tests/data/colabfold_af2_replay/2kl8_production_e3c6c52d.json",
    "esmfold2_predict": "tests/data/esmfold2_replay/minimal_production_9803381e.json",
    "chai1_predict": "tests/data/chai1_replay/minimal_production_018c32b6.json",
    "opendde": "tests/data/opendde_replay/tiny_production_2f16c036.json",
}
_MISSING = [name for name, relative in BUNDLES.items() if not (ROOT / relative).is_file()]
if _MISSING:
    pytest.skip(f"captured structure replay bundles are not present: {_MISSING}", allow_module_level=True)

# The storyboard's own root, and one captured artifact whose bytes a download
# must return unchanged.
ROOTS = {
    "alphafold": ".af2-result",
    "alphafold3": ".af3-result",
    "colabfold_af2": ".colabfold-result",
    "esmfold2_predict": ".esmfold-result",
    "chai1_predict": ".chai-result",
    "opendde": ".opendde-result",
}
DOWNLOAD_PATHS = {
    "alphafold": "2KL8/ranked_0.pdb",
    "alphafold3": "modeling/tiny-protein/tiny-protein_ranking_scores.csv",
    "colabfold_af2": "2KL8.a3m",
    "esmfold2_predict": "mini_protein/sample_001_plddt.csv",
    "chai1_predict": "pae.rank_0.npy",
    "opendde": "tiny/seed_101/predictions/tiny_full_data_sample_0.json",
}

_SETTLE = """async () => {
  await document.fonts.ready;
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}"""


def _structure_runner(name: str, display_name: str, summary: str, role: tuple[str, str, str]) -> RunnerDefinition:
    """One structure Task's declared catalog identity, transcribed from ``task.yaml``.

    Only the catalog/detail surface comes from here; the result surface is the
    captured bundle. Like the fpocket replay module this is kept local so the
    matrix test does not depend on a scenario helper another PR owns.
    """
    role_id, title, logical_type = role
    extensions = (".json",) if logical_type.endswith("_specification") else (".fasta", ".fa", ".faa")
    return RunnerDefinition(
        name=name,
        display_name=display_name,
        category="structure",
        category_label="Structure prediction",
        summary=summary,
        runtime_family=name.split("_predict")[0],
        inputs=(
            InputRole(
                id=role_id,
                title=title,
                logical_type=logical_type,
                formats=tuple(extension.lstrip(".") for extension in extensions),
                extensions=extensions,
            ),
        ),
    )


RUNNERS = {
    "alphafold": _structure_runner(
        "alphafold", "AlphaFold2",
        "DeepMind AlphaFold2 structure prediction (JAX, multimer-capable).",
        ("sequence", "Protein sequence", "protein_sequence"),
    ),
    "alphafold3": _structure_runner(
        "alphafold3", "AlphaFold 3", "AlphaFold 3 biomolecular structure prediction.",
        ("specification", "AlphaFold 3 input", "alphafold3_specification"),
    ),
    "colabfold_af2": _structure_runner(
        "colabfold_af2", "ColabFold (AlphaFold2)",
        "ColabFold AlphaFold2 prediction with online MMseqs2 MSA search and local GPU inference.",
        ("sequence", "Protein sequence", "protein_sequence"),
    ),
    "esmfold2_predict": _structure_runner(
        "esmfold2_predict", "ESMFold 2 structure prediction",
        "Predict all-atom protein structures with ESMFold 2 from sequence and optional MSA context.",
        ("sequence", "Protein sequence", "protein_sequence"),
    ),
    "chai1_predict": _structure_runner(
        "chai1_predict", "Chai-1 structure prediction",
        "Chai-1 all-atom biomolecular complex structure prediction from sequence and chemical inputs.",
        ("entities", "Molecular entities", "chai_entity_specification"),
    ),
    "opendde": _structure_runner(
        "opendde", "OpenDDE", "All-atom structure prediction with MSA and template guidance (OpenDDE).",
        ("specification", "OpenDDE job specification", "opendde_specification"),
    ),
}


def _replay(family: str) -> ReplayBundle:
    return ReplayBundle.load(ROOT / BUNDLES[family])


def _mount(page: Page, family: str) -> ReplayBundle:
    replay = _replay(family)
    mount_scenario(page, replay_scenario(RUNNERS[family], replay))
    return replay


def _open(page: Page, family: str) -> None:
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{ORIGIN}/compute/results/{_replay(family).task_id}")
    # The scientific surface is the one root these tests then exercise, and the
    # only one whose visibility is stable once the manifest arrives.
    expect(page.locator(ROOTS[family])).to_be_visible()
    page.evaluate(_SETTLE)


def _open_tab(page: Page, title: str) -> None:
    """Open one declared view's tab.

    The result menu is a ``details`` element that closes itself after a successful
    tab switch, but stays open when the selected view resolves no artifact, so the
    menu is opened only when it is actually closed.
    """
    if not page.locator(".result-view-menu[open]").count():
        page.locator(".result-view-menu > summary").click()
    page.locator(".result-tab", has_text=title).click()


def _js_number(value: float) -> str:
    """The ECMAScript ``String()`` form of a JSON number (``0.0`` renders as ``0``)."""
    return str(int(value)) if isinstance(value, float) and value.is_integer() else repr(value)


def test_alphafold_pairs_each_rank_with_its_own_confidence_and_pae(page: Page) -> None:
    replay = _mount(page, "alphafold")
    _open(page, "alphafold")

    expect(page.locator(".result-meta")).to_have_attribute("title", f"Task ID {replay.task_id}")
    expect(page.locator(".af2-result h2")).to_have_text("AlphaFold2 prediction")
    # Ranking order comes from the captured ranking_debug.json, and each rank
    # reads the confidence record named by that order -- not the array position.
    ranking = json.loads(replay.payload("2KL8/ranking_debug.json")[0])
    buttons = page.locator(".af2-candidates button")
    expect(buttons).to_have_text([f"Rank {index}" for index in range(len(ranking["order"]))])
    expect(buttons.first).to_have_attribute("aria-current", "true")

    first_confidence = json.loads(replay.payload(f"2KL8/confidence_{ranking['order'][0]}.json")[0])
    expect(page.get_by_role("img", name="pLDDT by Residue position")).to_be_visible()
    assert len(first_confidence["confidenceScore"]) == 79
    # Rank 0's captured PAE [0][0] is 0.2 Å on the persisted scale.
    readout = page.locator(".af2-result .matrix-readout")
    expect(readout).to_have_text("Aligned residue 1 · Scored residue 1 · value 0.2 angstrom")

    buttons.nth(1).click()
    expect(buttons.nth(1)).to_have_attribute("aria-current", "true")
    # The second published identity is model_1_ptm_pred_0 whose captured PAE
    # [0][0] is 0.25 Å, rendered on the declared one-decimal readout.
    expect(readout).to_have_text("Aligned residue 1 · Scored residue 1 · value 0.3 angstrom")
    expect(page.get_by_role("img", name="pLDDT by Residue position")).to_be_visible()


def test_alphafold3_shows_the_captured_confidences_and_pae(page: Page) -> None:
    replay = _mount(page, "alphafold3")
    _open(page, "alphafold3")

    expect(page.locator(".result-meta")).to_have_attribute("title", f"Task ID {replay.task_id}")
    expect(page.locator(".af3-result h2")).to_have_text("AlphaFold 3 prediction")
    summary = json.loads(
        replay.payload("modeling/tiny-protein/seed-1_sample-0/tiny-protein_seed-1_sample-0_summary_confidences.json")[0]
    )
    grid = page.locator(".af3-result .scalar-grid")
    expect(grid).to_contain_text(f"pTM{_js_number(summary['ptm'])} score")
    expect(grid).to_contain_text(f"Ranking score{_js_number(summary['ranking_score'])} score")
    expect(grid).to_contain_text(f"Fraction disordered{_js_number(summary['fraction_disordered'])} fraction")
    # A published null ipTM is not given a score the capture does not contain.
    expect(grid).not_to_contain_text("ipTM")
    expect(page.locator("#af3-pae-note")).to_have_text(
        "PAE (Å): 22 × 22 scored and aligned residues across 1 chains. Lower is better."
    )
    expect(page.locator(".af3-canvas")).to_be_visible()
    expect(page.locator(".af3-result .matrix-readout")).to_have_text(
        "Aligned residue 1 (chain A) · Scored residue 1 (chain A) · 0.8 Å"
    )

    # The declared scalar-summary view keeps every declared field, including the
    # nullable one, through the shared renderer.
    _open_tab(page, "Structure confidence")
    view = page.locator("section.scalar-summary-view dl.scalar-grid")
    expect(view.locator("dt")).to_have_text(
        ["pTM", "ipTM", "Ranking score", "Fraction disordered", "Has clash"]
    )
    expect(view.locator("dd")).to_have_text(
        ["0.21 scoreHigher is better", "N/AHigher is better", "0.71 scoreHigher is better",
         "1 fractionLower is better", "0 flagLower is better"]
    )
    # Two published summary records exist; the view says it shows the first.
    expect(page.locator("section.scalar-summary-view")).to_contain_text(
        "Showing the first of 2 published summary records."
    )


def test_colabfold_reads_the_a3m_header_and_leaves_an_empty_view_honest(page: Page) -> None:
    replay = _mount(page, "colabfold_af2")
    _open(page, "colabfold_af2")

    expect(page.locator(".colabfold-result h2")).to_have_text("ColabFold prediction")
    grid = page.locator(".colabfold-result .scalar-grid")
    expect(grid).to_contain_text("pTM0.6 score")
    expect(page.get_by_role("img", name="pLDDT by Residue position")).to_be_visible()

    a3m = replay.payload("2KL8.a3m")[0].decode("utf-8")
    assert a3m.startswith("#79\t1")
    expect(page.locator("pre.msa-block")).to_be_visible()
    expect(page.locator("table.entity-result-table tr td")).to_have_text(["Entity 1", "79", "1"])
    # The captured PAE [0][0] is 0.25 Å on the declared one-decimal readout.
    expect(page.locator(".colabfold-result .matrix-readout")).to_have_text(
        "Aligned residue 1 · Scored residue 1 · value 0.3 Å"
    )

    _open_tab(page, "Global model confidence")
    global_view = page.locator("section.scalar-summary-view dl.scalar-grid")
    expect(global_view.locator("dt")).to_have_text(["pTM", "Maximum PAE"])
    expect(global_view).to_contain_text("pTM0.6 score")
    expect(global_view).to_contain_text("Maximum PAE24.3125 Å")

    # A single-chain prediction publishes no interface score, so that declared
    # view resolves no source and states it rather than showing a stale panel.
    _open_tab(page, "Interface confidence")
    expect(page.locator(".result-preview .result-empty")).to_have_text("This view has no available artifact.")


def test_esmfold2_shows_confidence_on_its_persisted_scale(page: Page) -> None:
    replay = _mount(page, "esmfold2_predict")
    _open(page, "esmfold2_predict")

    expect(page.locator(".esmfold-result h2")).to_have_text("ESMFold 2 prediction")
    summary = json.loads(replay.payload("mini_protein/sample_001_confidence.json")[0])
    grid = page.locator(".esmfold-result .scalar-grid")
    expect(grid).to_contain_text(f"Mean pLDDT{_js_number(summary['mean_plddt'])} score")
    expect(grid).to_contain_text(f"pTM{_js_number(summary['ptm'])} score")
    # pLDDT is shown on ESMFold 2's persisted 0-1 scale, not multiplied by 100.
    expect(page.get_by_role("img", name="pLDDT by Token index")).to_be_visible()
    expect(page.locator(".esmfold-result p").first).to_contain_text("persisted 0 to 1 scale")
    # The captured PAE [0][0] is 0.2527... Å on the declared one-decimal readout.
    expect(page.locator(".esmfold-result .matrix-readout")).to_have_text(
        "Aligned token 1 · Scored token 1 · value 0.3 angstrom"
    )


def test_chai1_projects_the_captured_npy_arrays(page: Page) -> None:
    replay = _mount(page, "chai1_predict")
    _open(page, "chai1_predict")

    expect(page.locator(".chai-result h2")).to_have_text("Chai-1 prediction")
    summary = json.loads(replay.payload("confidence.rank_0.json")[0])
    grid = page.locator(".chai-result .scalar-grid")
    expect(grid).to_contain_text(f"Aggregate score{_js_number(summary['aggregate_score'])} score")
    expect(grid).to_contain_text(f"pTM{_js_number(summary['ptm'])} score")
    expect(grid).to_contain_text(f"ipTM{_js_number(summary['iptm'])} score")
    expect(grid).to_contain_text("Inter-chain clashesNo")
    # pLDDT, PAE, and PDE arrive as captured NPY arrays through the bounded
    # projection route, so real values are drawn rather than a placeholder.
    expect(page.get_by_role("img", name="pLDDT by Token index")).to_be_visible()
    readouts = page.locator(".chai-result .matrix-readout")
    expect(readouts.nth(0)).to_have_text("Aligned token 1 · Scored token 1 · value 0.3 angstrom")
    expect(readouts.nth(1)).to_have_text("Token 1 · Token 1 · value 0.3 angstrom")


def test_opendde_switches_between_the_captured_pairwise_matrices(page: Page) -> None:
    replay = _mount(page, "opendde")
    _open(page, "opendde")

    expect(page.locator(".opendde-result h2")).to_have_text("OpenDDE prediction")
    expect(page.locator(".opendde-candidates button")).to_have_text(["Candidate 1 - sample 0"])
    summary = json.loads(replay.payload("tiny/seed_101/predictions/tiny_summary_confidence_sample_0.json")[0])
    grid = page.locator(".opendde-result .scalar-grid")
    for label, key in (("pLDDT", "plddt"), ("gPDE", "gpde"), ("pTM", "ptm"), ("ipTM", "iptm"),
                       ("Ranking score", "ranking_score")):
        expect(grid).to_contain_text(f"{label}{_js_number(summary[key])} score")
    expect(grid).to_contain_text("ClashNo")
    expect(page.get_by_role("img", name="Atom pLDDT by Atom index")).to_be_visible()

    select = page.locator('select[aria-label="Pairwise confidence matrix"]')
    expect(select.locator("option")).to_have_text(["PAE", "PDE", "Contact probability"])
    note = page.locator(".opendde-result .scientific-note").last
    readout = page.locator(".opendde-result .matrix-readout")
    # PAE is the first captured matrix: 9 x 9 tokens, [0][0] = 0.77 Å.
    expect(note).to_have_text("Predicted aligned error for 9 × 9 tokens. Lower is better.")
    expect(readout).to_have_text("Aligned token 1 · Scored token 1 · 0.8 Å")

    select.select_option(label="PDE")
    expect(note).to_have_text("Predicted distance error for 9 × 9 tokens. Lower is better.")
    expect(readout).to_have_text("Aligned token 1 · Scored token 1 · 0.4 Å")

    select.select_option(label="Contact probability")
    expect(note).to_have_text("Contact probability for 9 × 9 tokens. Higher is better.")
    expect(readout).to_have_text("Aligned token 1 · Scored token 1 · 1.00 probability")


@pytest.mark.parametrize("family", sorted(BUNDLES))
def test_replayed_result_mounts_every_declared_view(page: Page, family: str) -> None:
    replay = _mount(page, family)
    _open(page, family)

    page.locator(".result-view-menu > summary").click()
    expect(page.locator(".result-tab", has_text="Scientific result")).to_be_visible()
    for title in [view["title"] for view in replay.manifest["views"]]:
        expect(page.locator(".result-tab", has_text=title)).to_be_visible()


@pytest.mark.parametrize("family", sorted(BUNDLES))
def test_replayed_download_returns_the_exact_captured_bytes(page: Page, family: str) -> None:
    replay = _mount(page, family)
    _open(page, family)

    path = DOWNLOAD_PATHS[family]
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


@pytest.mark.parametrize("family", sorted(BUNDLES))
def test_replayed_result_raises_no_console_or_csp_error(page: Page, family: str) -> None:
    errors: list[str] = []
    # A projection the Server refuses is an honest 404 the storyboard catches and
    # states in its panel; the browser still logs every failed response, so a 404
    # on the bounded projection route is the only failure this test excuses.
    refused: set[str] = set()

    def record_console(message: object) -> None:
        if getattr(message, "type", "") != "error":
            return
        url = (getattr(message, "location", None) or {}).get("url", "")
        if "404" in getattr(message, "text", "") and "/ndarrays/" in url and url in refused:
            return
        errors.append(f"console.error: {getattr(message, 'text', '')}")

    page.on("console", record_console)
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    page.on("response", lambda response: refused.add(response.url) if response.status >= 400 else None)
    replay = _mount(page, family)
    _open(page, family)

    # Visit every declared view, so each renderer is exercised on captured bytes.
    for view in replay.manifest["views"]:
        _open_tab(page, view["title"])
        expect(page.locator(".result-preview")).not_to_have_attribute("aria-busy", "true")
    _open_tab(page, "Scientific result")
    expect(page.locator(ROOTS[family])).to_be_visible()
    page.evaluate(_SETTLE)

    violations = page.evaluate("window.__cspViolations || []")
    assert errors == [], errors
    assert violations == [], violations


@pytest.mark.parametrize("family", sorted(BUNDLES))
def test_replayed_task_scope_is_enforced_for_a_mismatched_id(page: Page, family: str) -> None:
    _mount(page, family)
    status = page.evaluate(
        """async (url) => (await fetch(url, { credentials: 'same-origin' })).status""",
        f"{ORIGIN}/compute/api/results/{'f' * 32}/artifacts/{DOWNLOAD_PATHS[family]}",
    )
    assert status == 404
