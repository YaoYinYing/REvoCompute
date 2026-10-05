# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Parser/integration expectations for the fpocket Runner.

fpocket is a third-party binary: REvoCompute runs it and parses its output, it
does not reimplement fpocket's pocket detection or druggability mathematics
(see ``docker/runners/fpocket/INTEGRATION.md``).  So these tests assert only what
REvoCompute owns -- that the normalizer transforms real fpocket output into the
declared table, and refuses malformed input -- and never that a particular score,
centre, or pocket is "correct".  The values seen here are what fpocket reported
for the frozen run, not a scientific golden.

The fixture is a bounded, self-consistent slice of a real 1SUO run:
``1SUO_info.txt`` (all 40 pockets, the descriptor source) plus the per-pocket
geometry/contact files for ``pocket1`` (contacts the HEM cofactor) and
``pocket2`` (contacts polymer residues only), which exercise both parser
branches.  ``tests/data/fpocket/live/pockets.csv`` is the normalized table a real
production run published and is reused as authentic result data.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

# subset_run_dir is a fixture registered by the import; the helper module is a
# plain module (not conftest.py) so it cannot shadow the repo-root conftest.
from fpocket_fixtures import RETAINED_RUN, build_subset_run, first_pocket_blocks, subset_run_dir  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/fpocket"
FIXTURES = ROOT / "tests/data/fpocket"
INPUT_STRUCTURE = ROOT / "tests/data/pdb/1SUO.pdb"
LIVE_RESULT = FIXTURES / "live" / "pockets.csv"

#: Columns the published pocket table must expose for the declared result view.
#: This is the adapter contract: the Runner claims to publish these fields.
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


@pytest.fixture()
def normalized_run(subset_run_dir: Path, monkeypatch) -> dict:
    """Run the production normalizer over the pinned subset tree and return its output."""
    tmp_path = subset_run_dir
    provenance = tmp_path / "fpocket-run.json"
    provenance.write_text(json.dumps({"task_type": "fpocket", "parameters": {}}), encoding="utf-8")
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
    return {"rows": rows, "summary": summary, "run_dir": tmp_path}


def test_normalizer_maps_every_declared_column_from_real_output(normalized_run: dict) -> None:
    rows = normalized_run["rows"]
    assert rows, "the reference case must publish at least one pocket"
    assert set(PUBLISHED_COLUMNS) <= set(rows[0])
    # Identity and rank are separate fields, so a display never confuses the two.
    assert [row["pocket"] for row in rows] == [f"pocket{index}" for index in range(1, len(rows) + 1)]
    assert [int(row["rank"]) for row in rows] == list(range(1, len(rows) + 1))
    # fpocket reports pockets in descending score order; the adapter preserves it.
    scores = [float(row["score"]) for row in rows]
    assert scores == sorted(scores, reverse=True)
    for row in rows:
        for axis in ("center_x", "center_y", "center_z"):
            float(row[axis])
        assert int(row["residue_count"]) == len(row["residue_ids"].split())
        assert int(row["atom_count"]) > 0


def test_normalizer_reads_the_global_descriptor_file_for_every_pocket(normalized_run: dict) -> None:
    """The global source carries all 40 pockets even though only two are retained.

    The published table is a prefix of the global source's pockets; its count and
    ranking are what ``1SUO_info.txt`` reports, so no pinned per-pocket file is
    needed to prove the descriptor layer.
    """
    declared = first_pocket_blocks((RETAINED_RUN / "1SUO_info.txt").read_text(encoding="utf-8"), 999)
    declared_headers = [line for line in declared.splitlines() if line.startswith("Pocket ")]
    assert len(declared_headers) == 40
    # The real production table carries every one of them.
    with LIVE_RESULT.open(encoding="utf-8", newline="") as handle:
        live = list(csv.DictReader(handle))
    assert len(live) == 40
    assert [row["pocket"] for row in live] == [f"pocket{index}" for index in range(1, 41)]
    # ...and the subset run is its leading prefix, with identical descriptors.
    subset = normalized_run["rows"]
    for produced, published in zip(subset, live):
        assert produced["pocket"] == published["pocket"]
        for name in PUBLISHED_COLUMNS:
            if name in {"volume_angstrom3", "center_x", "center_y", "center_z", "residue_count", "residue_ids", "atom_count"}:
                continue  # run-local or geometry-derived; covered elsewhere
            assert produced[name] == published[name], (produced["pocket"], name)


def test_normalizer_parses_the_two_selected_pockets_and_their_contacts(normalized_run: dict) -> None:
    """The retained geometry/contact files prove the parser's non-descriptor branches.

    ``pocket1`` contacts a non-polymer (hetero) residue; ``pocket2`` contacts only
    polymer residues.  The assertion is that the parser derived a contact set and
    hetero identity from the atom file, not that any particular contact is real.
    """
    rows = {row["pocket"]: row for row in normalized_run["rows"]}
    assert set(rows) == {"pocket1", "pocket2"}
    for row in rows.values():
        assert int(row["alpha_spheres"]) > 0
        assert row["residue_ids"].split()
    pocket1_atoms = (RETAINED_RUN / "pockets/pocket1_atm.pdb").read_text(encoding="utf-8")
    assert "HETATM" in pocket1_atoms  # branch: a pocket that contacts a hetero residue
    pocket2_atoms = (RETAINED_RUN / "pockets/pocket2_atm.pdb").read_text(encoding="utf-8")
    assert "HETATM" not in pocket2_atoms  # branch: a pocket that contacts only polymer residues


def test_summary_reports_the_published_ranking(normalized_run: dict) -> None:
    summary = normalized_run["summary"]
    assert summary["pocket_count"] == len(normalized_run["rows"])
    assert summary["ranking_metric"] == "score"
    assert summary["ranking_order"] == "descending"
    assert summary["units"]["volume_angstrom3"] == "angstrom^3"
    assert summary["provenance"]["task_type"] == "fpocket"


# --- Correct failure handling: REvoCompute-owned behaviour -------------------


def _run_normalizer(output_dir: Path, monkeypatch, provenance: dict | None = None) -> subprocess.CompletedProcess[str]:
    monkeypatch.chdir(output_dir)
    provenance_file = output_dir / "fpocket-run.json"
    provenance_file.write_text(json.dumps(provenance or {"task_type": "fpocket"}), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(FAMILY / "normalize_results.py"), str(output_dir), "--provenance", str(provenance_file)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_normalizer_rejects_a_run_without_pockets(tmp_path: Path, monkeypatch) -> None:
    work = tmp_path / "work"
    (work / "1SUO_out/pockets").mkdir(parents=True)
    (work / "1SUO_out/1SUO_info.txt").write_text("No pockets found\n", encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run_normalizer(tmp_path, monkeypatch)
    assert "no pockets" in failure.value.stderr


def test_normalizer_rejects_a_run_with_no_info_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "work").mkdir()
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run_normalizer(tmp_path, monkeypatch)
    assert "info file" in failure.value.stderr


def test_normalizer_rejects_a_pocket_missing_its_files(tmp_path: Path, monkeypatch) -> None:
    build_subset_run(tmp_path, count=2)
    (tmp_path / "work/1SUO_out/pockets/pocket1_vert.pqr").unlink()
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run_normalizer(tmp_path, monkeypatch)
    assert "missing its vertex or atom file" in failure.value.stderr


def test_normalizer_rejects_a_malformed_descriptor_block(tmp_path: Path, monkeypatch) -> None:
    """A block missing fpocket's declared descriptors is malformed output."""
    build_subset_run(tmp_path, count=2)
    info = tmp_path / "work/1SUO_out/1SUO_info.txt"
    source = info.read_text(encoding="utf-8")
    info.write_text(source.replace("Score", "NotScore", 1), encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run_normalizer(tmp_path, monkeypatch)
    assert "missing descriptors" in failure.value.stderr


def test_normalizer_rejects_an_empty_vertex_file(tmp_path: Path, monkeypatch) -> None:
    build_subset_run(tmp_path, count=2)
    (tmp_path / "work/1SUO_out/pockets/pocket1_vert.pqr").write_text("", encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run_normalizer(tmp_path, monkeypatch)
    assert "alpha-sphere centres" in failure.value.stderr


def test_normalizer_keeps_pdb_insertion_codes_distinct(tmp_path: Path, monkeypatch) -> None:
    """A residue with an insertion code is not the residue with the bare number."""
    build_subset_run(tmp_path, count=2)
    atoms = tmp_path / "work/1SUO_out/pockets/pocket1_atm.pdb"
    line = "ATOM      1  CA  GLY A  42       0.000   0.000   0.000  1.00  0.00           C\n"
    insertion = "ATOM      1  CA  GLY A  42A      0.000   0.000   0.000  1.00  0.00           C\n"
    atoms.write_text(line + insertion + "END\n", encoding="utf-8")
    _run_normalizer(tmp_path, monkeypatch)

    with (tmp_path / "pockets.csv").open(encoding="utf-8", newline="") as handle:
        residues = csv.DictReader(handle).__next__()["residue_ids"].split()
    assert residues == ["A_42", "A_42A"]
