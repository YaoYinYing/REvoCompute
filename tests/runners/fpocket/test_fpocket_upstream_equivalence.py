# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Scientific-equivalence acceptance for the fpocket Runner.

``test_fpocket_results.py`` keeps the raw output tree as a fast protocol contract:
it checks the normalizer's shape and error handling.  This module proves the
*scientific* path instead.  It runs the production normalizer over the pinned
1SUO pocket output and compares every published observable against
``tests/data/fpocket/upstream_reference.json``, which is derived independently by
``tests/data/fpocket/build_reference.py`` (it imports nothing from the
production parser, so a parser error cannot make the reference agree with it).

The reference case is PDB ``1SUO`` (mammalian cytochrome P450 2B4 with bound
4-(4-chlorophenyl)imidazole, 1.9 A), a real structure whose leading detected
pocket contacts the heme cofactor.  That the reference pins a non-zero pocket
count and a cofactor-contacting pocket is deliberate: a case that produced
trivially empty output would prove nothing.  The contact is stated as a
hetero/cofactor contact, not a ligand- or active-site claim — the co-crystallized
inhibitor CPZ is present in the input but contacted by no reported pocket.

Observable classes (tolerances are justified below, not chosen to pass):

* ``exact``    -- values upstream prints and the Runner republishes verbatim:
  pocket count/ids, ranking, every non-Monte-Carlo descriptor, alpha-sphere
  vertex count, contacted-residue set, contacted-atom count, hetero contact.
* ``not-golden`` -- the Monte-Carlo pocket volume.  fpocket seeds its RNG from
  ``time(NULL)``, so the volume varies run to run (measured ~8% on the leading
  pocket) and cannot be a cross-run golden value; the reference records it for
  the frozen run and the comparison skips it, asserting only that it is positive.
* ``tolerant`` -- the pocket centre, re-derived as the mean of the pocket's own
  alpha-sphere centres (``set_pockets_bary`` in fpocket's ``src/pocket.c``).  Both
  sides sum the same float coordinates, so agreement is limited only by the
  normalizer's four-decimal rounding: 2e-4 A.

Fail-closed identity: the reference records the upstream revision, the input
structure hash, and the hash of every raw fpocket file.  The tests refuse if the
input or any raw file differs from what the reference was built from, so a
reference that no longer matches the pinned run cannot silently pass.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Importing the fixture registers it in this module's namespace. It lives in a
# plain module (not a conftest.py) so it cannot shadow the repository-root
# conftest that tests/server/* imports by name.
from fpocket_fixtures import subset_run_dir  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/fpocket"
FIXTURES = ROOT / "tests/data/fpocket"
REFERENCE_PATH = FIXTURES / "upstream_reference.json"
INPUT_STRUCTURE = ROOT / "tests/data/pdb/1SUO.pdb"
#: The complete 40-pocket table a real production run published (task
#: b546f034ffc7fafac871f21176a03c91 on lab309-westlake); the real-Runner
#: evidence behind the full-result layer below.
LIVE_RESULT = FIXTURES / "live" / "pockets.csv"

#: Columns the published pocket table must expose for the declared result view.
#: These are the observables the Runner claims to publish, so they are the
#: contract here rather than an assertion about the task manifest text.
PUBLISHED_COLUMNS = (
    "pocket",
    "rank",
    "score",
    "druggability_score",
    "alpha_spheres",
    "mean_alpha_sphere_radius_angstrom",
    "total_sasa_angstrom2",
    "apolar_sasa_angstrom2",
    "polar_sasa_angstrom2",
    "volume_angstrom3",
    "hydrophobicity_score",
    "volume_score",
    "polarity_score",
    "charge_score",
    "apolar_alpha_sphere_proportion",
    "center_x",
    "center_y",
    "center_z",
    "residue_count",
    "residue_ids",
    "atom_count",
)

#: Centre tolerance: both sides average the same alpha-sphere coordinates, so the
#: only loss is the normalizer's four-decimal rounding (half a unit in the last
#: place is 5e-5 A); a 2e-4 A bound leaves margin without hiding a wrong centre.
CENTER_ATOL_ANGSTROM = 2e-4


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def normalized_run(subset_run_dir: Path, monkeypatch) -> dict:
    """Run the production normalizer over the pinned subset tree and return its output."""
    tmp_path = subset_run_dir
    provenance = tmp_path / "fpocket-run.json"
    provenance.write_text(
        json.dumps(
            {
                "task_type": "fpocket",
                "upstream_revision": "4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066",
                "input_structure": {"name": "1SUO.pdb", "sha256": _sha256(INPUT_STRUCTURE)},
                "parameters": {"volume_monte_carlo_iterations": 300},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        [sys.executable, str(FAMILY / "normalize_results.py"), str(tmp_path), "--provenance", str(provenance)],
        check=True,
        capture_output=True,
        text=True,
    )
    with (tmp_path / "pockets.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    return {"rows": rows, "summary": summary}


def _check(reference: dict, rows: list[dict]) -> None:
    """Assert the published pocket table reproduces the reference, layer by layer.

    Layer 1 (every published pocket): ids, rank, and the deterministic printed
    descriptors, which the global descriptor source proves for all reported
    pockets.  Layer 1 holds for the full 40-pocket live table and for the smaller
    subset table produced from the retained per-pocket files.
    Layers 2-3 (the selected pockets only): the geometry-derived centre and the
    contacted-residue/atom/hetero-contact semantics, whose raw per-pocket files
    are the retained subset.
    """
    expected = reference["expected"]
    row_ids = [row["pocket"] for row in rows]
    # The published pockets are the leading reference pockets; the full live table
    # covers all of them, a subset table covers a prefix.
    assert row_ids == expected["pocket_ids"][: len(row_ids)]

    by_id = {row["pocket"]: row for row in rows}
    run_local = set(reference.get("run_local_descriptors", ()))
    selected = set(expected["selected_pockets"])
    for pocket in expected["pockets"][: len(row_ids)]:
        published = by_id[pocket["pocket"]]
        assert int(published["rank"]) == pocket["rank"]
        for name, value in pocket["descriptors"].items():
            # The Monte-Carlo volume is seeded from the wall clock upstream, so it
            # is deterministic within one run but not across runs; it is recorded
            # for the frozen run and skipped in the cross-run comparison.
            if name in run_local:
                continue
            assert published[name] == value, (pocket["pocket"], name, published[name], value)
        assert float(published["volume_angstrom3"]) > 0.0
        # Geometry/contact observables are only proven for the retained subset; the
        # reference does not carry their expected values for the other pockets.
        if pocket["pocket"] not in selected:
            continue
        assert int(published["alpha_spheres"]) == pocket["alpha_sphere_vertices"]
        assert int(published["residue_count"]) == pocket["residue_count"]
        assert int(published["atom_count"]) == pocket["atom_count"]
        # The contacted-residue identity is the scientific observable, so it is
        # compared as a set; the published order (ascending residue number) is a
        # separate production-presentation property checked elsewhere.
        assert set(published["residue_ids"].split()) == set(pocket["residue_ids"])
        for axis, wanted in (
            ("center_x", pocket["center_x"]),
            ("center_y", pocket["center_y"]),
            ("center_z", pocket["center_z"]),
        ):
            assert abs(float(published[axis]) - wanted) <= CENTER_ATOL_ANGSTROM, (pocket["pocket"], axis)


def test_reference_is_pinned_to_one_upstream_revision(reference: dict) -> None:
    upstream = reference["upstream"]
    assert upstream["repository"] == "https://github.com/Discngine/fpocket"
    assert upstream["revision"] == "4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066"
    assert upstream["revision_label"] == "4.2.3"
    assert upstream["code_license"] == "MIT"
    # Both method publications fpocket's algorithm is grounded in.
    assert upstream["method_publications"] == ["10.1186/1471-2105-10-168", "10.1021/jm100574m"]
    # Every Runner parameter is recorded with the upstream CLI flag it maps to.
    assert reference["parameters"]["min_alpha_sphere_radius"]["flag"] == "-m"
    assert reference["parameters"]["max_alpha_sphere_radius"]["flag"] == "-M"
    assert reference["parameters"]["min_alpha_spheres_per_pocket"]["flag"] == "-i"
    assert reference["parameters"]["clustering_distance"]["flag"] == "-D"
    assert reference["parameters"]["volume_monte_carlo_iterations"]["flag"] == "-v"


def test_reference_input_and_raw_output_identity_fail_closed(reference: dict) -> None:
    case = reference["reference_case"]
    assert case["pdb_id"] == "1SUO"
    assert INPUT_STRUCTURE.name == "1SUO.pdb"
    assert _sha256(INPUT_STRUCTURE) == case["input_sha256"]
    raw = reference["raw_output"]
    run_dir = ROOT / raw["run_dir"]
    observed = {
        str(path.relative_to(run_dir)): _sha256(path)
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    }
    # Only the retained evidence set is present and hashed; omitted per-pocket
    # files are deliberate (recorded in raw_output.omitted_files), not assumed.
    assert observed == raw["retained_files"]
    # The global descriptor source proves every pocket's printed descriptors and is
    # bound by its own hash and digest.
    assert raw["global_source"]["path"] in observed
    assert observed[raw["global_source"]["path"]] == raw["global_source"]["sha256"]
    expected_digest = hashlib.sha256(
        f"{raw['global_source']['path']} {raw['global_source']['sha256']}".encode()
    ).hexdigest()
    assert expected_digest == raw["global_source_digest"]
    # Every selected pocket's geometry and contact files are retained and hashed.
    assert set(raw["per_pocket_files"]) == set(raw["retained_files"]) - {raw["global_source"]["path"]}
    for pocket in raw["selected_pockets"]:
        for suffix in ("_vert.pqr", "_atm.pdb"):
            name = f"pockets/pocket{pocket}{suffix}"
            assert raw["per_pocket_files"][name] == observed[name]
    # The omitted files are exactly the per-pocket files for unselected pockets.
    omitted = set(raw["omitted_files"])
    assert omitted == {
        f"pockets/pocket{index}{suffix}"
        for index in range(1, reference["expected"]["pocket_count"] + 1)
        if index not in raw["selected_pockets"]
        for suffix in ("_vert.pqr", "_atm.pdb")
    }
    assert not (omitted & set(observed)), "an omitted file is still present on disk"


def test_reference_still_reproduces_from_the_pinned_tree(reference: dict) -> None:
    """The checked-in reference must be exactly what the extractor derives now.

    This is what makes a wrong identity fail closed: if the raw tree, the input,
    or the extractor changed, the frozen ``expected`` block would no longer match
    a fresh derivation and this test refuses.
    """
    sys.path.insert(0, str(FIXTURES))
    import build_reference  # noqa: E402

    fresh = build_reference.extract(FIXTURES / "1SUO_out", INPUT_STRUCTURE)
    assert fresh["upstream"] == reference["upstream"]
    assert fresh["parameters"] == reference["parameters"]
    assert fresh["raw_output"] == reference["raw_output"]
    assert fresh["reference_case"] == reference["reference_case"]
    assert fresh["expected"] == reference["expected"]


def test_published_pockets_match_the_independent_reference(reference: dict, normalized_run: dict) -> None:
    _check(reference, normalized_run["rows"])


def test_full_production_result_matches_the_reference(reference: dict) -> None:
    """Layer 4: the complete 40-pocket table a real run published matches the reference.

    ``tests/data/fpocket/live/pockets.csv`` is the normalized output of a real
    Slurm+Apptainer run (task b546f034ffc7fafac871f21176a03c91), not a regenerated
    file, so this proves the whole production result -- all 40 pockets' ids,
    ranking, and deterministic printed descriptors -- agrees with the reference.
    """
    with LIVE_RESULT.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = reference["expected"]
    assert len(rows) == expected["pocket_count"] == 40
    _check(reference, rows)
    # The live leading pocket is the cofactor-contacting pocket the reference records.
    assert rows[0]["pocket"] == "pocket1"
    assert rows[0]["druggability_score"] == expected["pockets"][0]["descriptors"]["druggability_score"]


def test_published_table_exposes_the_declared_observables(reference: dict, normalized_run: dict) -> None:
    rows = normalized_run["rows"]
    assert rows, "the reference case must publish at least one pocket"
    assert set(PUBLISHED_COLUMNS) <= set(rows[0])
    summary = normalized_run["summary"]
    # The subset run publishes the retained pockets; the reference's global source
    # owns the full count.
    assert summary["pocket_count"] == len(rows)
    assert summary["ranking_metric"] == "score"
    assert summary["ranking_order"] == "descending"
    # Provenance flows into the published summary so the displayed pockets can be
    # audited back to the run that produced them.
    assert summary["provenance"]["input_structure"]["sha256"] == reference["reference_case"]["input_sha256"]


def test_reference_case_has_a_real_pocket_not_an_empty_result(reference: dict) -> None:
    expected = reference["expected"]
    assert expected["pocket_count"] >= 1
    # The leading pocket contacts the heme cofactor (a non-polymer HETATM), so the
    # case is a meaningful, non-empty detection rather than an all-zero output.
    # This is a hetero/cofactor contact, NOT a ligand (CPZ) or active-site claim:
    # the co-crystallized inhibitor CPZ is present in the input but contacted by
    # no reported pocket, asserted here so the wording cannot drift back into an
    # unsupported "ligand-binding pocket" claim.
    assert expected["hetero_contacting_pockets"] == ["pocket1"]
    assert expected["pockets"][0]["hetero_residues"] == ["HEM"]
    # The whole retained contact set carries only the HEM cofactor — the CPZ
    # inhibitor is contacted by no reported pocket.
    assert expected["contacted_hetero_residues"] == ["HEM"]
    assert float(expected["pockets"][0]["descriptors"]["druggability_score"]) > 0.5
    # A real fpocket run on this structure yields many sub-threshold pockets, not
    # a single degenerate one; the leading pocket must outscore the rest.
    assert expected["pocket_count"] == 40
    assert expected["pockets"][0]["descriptors"]["score"] != expected["pockets"][-1]["descriptors"]["score"]


def test_ranking_is_descending_and_consistent_with_pocket_ids(reference: dict, normalized_run: dict) -> None:
    rows = normalized_run["rows"]
    scores = [float(row["score"]) for row in rows]
    assert scores == sorted(scores, reverse=True)
    # Ranking is by descending score over the retained subset, and the reference's
    # global ranking begins with the same pockets.
    assert [row["pocket"] for row in rows] == reference["expected"]["ranking"][: len(rows)]
    assert [row["pocket"] for row in rows] == [f"pocket{i}" for i in range(1, len(rows) + 1)]


def test_a_perturbed_published_score_fails_acceptance(reference: dict, normalized_run: dict) -> None:
    rows = [dict(row) for row in normalized_run["rows"]]
    rows[0]["score"] = f"{float(rows[0]['score']) + 0.01:.3f}"
    with pytest.raises(AssertionError):
        _check(reference, rows)


def test_a_swapped_pocket_order_fails_acceptance(reference: dict, normalized_run: dict) -> None:
    rows = [dict(row) for row in normalized_run["rows"]][::-1]
    with pytest.raises(AssertionError):
        _check(reference, rows)


def test_a_perturbed_reference_center_fails_acceptance(reference: dict, normalized_run: dict) -> None:
    perturbed = json.loads(json.dumps(reference))
    perturbed["expected"]["pockets"][0]["center_x"] += 0.5
    with pytest.raises(AssertionError):
        _check(perturbed, normalized_run["rows"])


def test_a_dropped_residue_fails_acceptance(reference: dict, normalized_run: dict) -> None:
    rows = [dict(row) for row in normalized_run["rows"]]
    rows[0]["residue_ids"] = " ".join(rows[0]["residue_ids"].split()[:-1])
    with pytest.raises(AssertionError):
        _check(reference, rows)


def test_a_claimed_ligand_contact_that_fpocket_did_not_report_fails(reference: dict) -> None:
    """The corrected contact definition must not drift back into a ligand claim.

    A pocket whose atoms contact only the heme cofactor is a hetero/cofactor
    contact, not evidence that the pocket binds the co-crystallized inhibitor. If
    someone re-adds CPZ to the expected contact set (the exact over-claim the
    reviewer flagged), this refuses.
    """
    expected = reference["expected"]
    assert expected["hetero_contacting_pockets"] == ["pocket1"]
    assert expected["pockets"][0]["hetero_residues"] == ["HEM"]
    # No retained contact set names the inhibitor, so a CPZ-bearing contact set is
    # a fabricated claim.
    assert expected["contacted_hetero_residues"] == ["HEM"]
    assert "ligand_contacting_pockets" not in expected
    assert "ligand_contact_rule" not in reference["reference_case"]
