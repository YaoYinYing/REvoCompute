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

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/fpocket"
FIXTURES = ROOT / "tests/data/fpocket"
REFERENCE_PATH = FIXTURES / "upstream_reference.json"
INPUT_STRUCTURE = ROOT / "tests/data/pdb/1SUO.pdb"

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
def normalized_run(tmp_path: Path, monkeypatch) -> dict:
    """Run the production normalizer over the pinned tree and return its output."""
    work = tmp_path / "work"
    (work / "1SUO_out").mkdir(parents=True)
    shutil.copytree(FIXTURES / "1SUO_out", work / "1SUO_out", dirs_exist_ok=True)
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
    """Assert the published pocket table reproduces the reference exactly."""
    expected = reference["expected"]
    assert [row["pocket"] for row in rows] == expected["pocket_ids"]
    assert [int(row["rank"]) for row in rows] == [row["rank"] for row in expected["pockets"]]

    by_id = {row["pocket"]: row for row in rows}
    run_local = set(reference.get("run_local_descriptors", ()))
    for pocket in expected["pockets"]:
        published = by_id[pocket["pocket"]]
        for name, value in pocket["descriptors"].items():
            # The Monte-Carlo volume is seeded from the wall clock upstream, so it
            # is deterministic within one run but not across runs; it is recorded
            # for the frozen run and skipped in the cross-run comparison.
            if name in run_local:
                continue
            assert published[name] == value, (pocket["pocket"], name, published[name], value)
        assert float(published["volume_angstrom3"]) > 0.0
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
    run_dir = ROOT / reference["raw_output"]["run_dir"]
    observed = {
        str(path.relative_to(run_dir)): _sha256(path)
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    }
    assert observed == reference["raw_output"]["files"]
    joined = "\n".join(f"{name} {digest}" for name, digest in sorted(observed.items())).encode("utf-8")
    assert hashlib.sha256(joined).hexdigest() == reference["raw_output"]["tree_digest"]


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


def test_published_table_exposes_the_declared_observables(reference: dict, normalized_run: dict) -> None:
    rows = normalized_run["rows"]
    assert rows, "the reference case must publish at least one pocket"
    assert set(PUBLISHED_COLUMNS) <= set(rows[0])
    summary = normalized_run["summary"]
    assert summary["pocket_count"] == reference["expected"]["pocket_count"]
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
    assert all("CPZ" not in pocket["hetero_residues"] for pocket in expected["pockets"])
    assert float(expected["pockets"][0]["descriptors"]["druggability_score"]) > 0.5
    # A real fpocket run on this structure yields many sub-threshold pockets, not
    # a single degenerate one; the leading pocket must outscore the rest.
    assert expected["pocket_count"] == 40
    assert expected["pockets"][0]["descriptors"]["score"] != expected["pockets"][-1]["descriptors"]["score"]


def test_ranking_is_descending_and_consistent_with_pocket_ids(reference: dict, normalized_run: dict) -> None:
    rows = normalized_run["rows"]
    scores = [float(row["score"]) for row in rows]
    assert scores == sorted(scores, reverse=True)
    # Ranking is by descending score; it must reproduce the reference order and
    # never be confused with the pocket id.
    assert [row["pocket"] for row in rows] == reference["expected"]["ranking"]
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
    # No reported pocket contacts the inhibitor, so a CPZ-bearing contact set is a
    # fabricated claim.
    assert all("CPZ" not in pocket["hetero_residues"] for pocket in expected["pockets"])
    assert "ligand_contacting_pockets" not in expected
    assert "ligand_contact_rule" not in reference["reference_case"]
