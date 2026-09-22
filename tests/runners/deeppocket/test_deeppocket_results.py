# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/deeppocket"
FIXTURES = ROOT / "tests/data/deeppocket"


def _run_normalizer(output_dir: Path, monkeypatch, provenance: dict | None = None) -> subprocess.CompletedProcess[str]:
    monkeypatch.chdir(output_dir)
    provenance_file = output_dir / "deeppocket-run.json"
    provenance_file.write_text(json.dumps(provenance or {"task_type": "deeppocket"}), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(FAMILY / "normalize_results.py"), str(output_dir), "--provenance", str(provenance_file)],
        check=True,
        capture_output=True,
        text=True,
    )


def _copy_run(tmp_path: Path) -> None:
    for source in FIXTURES.rglob("*"):
        if source.is_file():
            target = tmp_path / source.relative_to(FIXTURES)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def test_normalizer_joins_ranking_with_candidate_centres(tmp_path: Path, monkeypatch) -> None:
    _copy_run(tmp_path)
    _run_normalizer(tmp_path, monkeypatch, {"parameters": {"top_pockets": 2}})

    with (tmp_path / "pockets.csv").open(encoding="utf-8", newline="") as handle:
        pockets = list(csv.DictReader(handle))
    # Rank order comes from the classifier, so candidate 2 leads candidate 3.
    assert [row["pocket"] for row in pockets] == ["2", "3", "1"]
    assert [int(row["rank"]) for row in pockets] == [1, 2, 3]
    confidences = [float(row["confidence"]) for row in pockets]
    assert confidences == sorted(confidences, reverse=True)
    # Centres are joined from fpocket's barycenters, not copied from the ranking file.
    assert float(pockets[0]["center_x"]) == pytest.approx(10.0)
    assert float(pockets[0]["center_y"]) == pytest.approx(-5.25)
    assert float(pockets[0]["center_z"]) == pytest.approx(12.75)
    # Only the top `top_pockets` were segmented; the third candidate has no mask.
    assert [row["segmented"] for row in pockets] == ["True", "True", "False"]
    assert [int(row["residue_count"]) for row in pockets] == [2, 1, 0]

    with (tmp_path / "residues.csv").open(encoding="utf-8", newline="") as handle:
        residues = list(csv.DictReader(handle))
    assert [(row["pocket"], row["chain"], row["resseq"], row["resname"]) for row in residues] == [
        ("2", "A", "28", "GLY"),
        ("2", "A", "31", "SER"),
        ("3", "B", "104", "LEU"),
    ]

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["candidate_count"] == 3
    assert summary["segmented_pocket_count"] == 2
    assert summary["segmented_residue_count"] == 3
    assert summary["ranking_order"] == "descending"
    assert summary["provenance"]["parameters"]["top_pockets"] == 2


def test_normalizer_rejects_a_ranking_without_confidence_scores(tmp_path: Path, monkeypatch) -> None:
    _copy_run(tmp_path)
    (tmp_path / "pocket_confidence.txt").unlink()
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run_normalizer(tmp_path, monkeypatch)
    assert "no classifier confidence file" in failure.value.stderr


def test_normalizer_rejects_a_score_count_that_disagrees_with_the_ranking(tmp_path: Path, monkeypatch) -> None:
    _copy_run(tmp_path)
    (tmp_path / "pocket_confidence.txt").write_text("0.9\n0.8\n", encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run_normalizer(tmp_path, monkeypatch)
    assert "ranked candidates" in failure.value.stderr


def test_normalizer_accepts_a_run_whose_masks_contact_no_residue(tmp_path: Path, monkeypatch) -> None:
    """Segmentation can legitimately reduce every mask to zero residues."""
    _copy_run(tmp_path)
    for pocket_pdb in tmp_path.glob("*_pocket*.pdb"):
        pocket_pdb.unlink()
    _run_normalizer(tmp_path, monkeypatch)

    with (tmp_path / "pockets.csv").open(encoding="utf-8", newline="") as handle:
        pockets = list(csv.DictReader(handle))
    assert [row["segmented"] for row in pockets] == ["False"] * len(pockets)
    with (tmp_path / "residues.csv").open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle)) == []
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["segmented_pocket_count"] == 0
    assert summary["segmented_residue_count"] == 0


def test_normalizer_reports_candidates_whose_masks_contact_nothing(tmp_path: Path, monkeypatch) -> None:
    """A run can rank pockets and segment none of them into residues."""
    _copy_run(tmp_path)
    for pocket_pdb in tmp_path.glob("*_pocket*.pdb"):
        pocket_pdb.unlink()
    (tmp_path / "1SUO_pocket1.pdb").write_text(
        "ATOM      1  CA  ALA B 104       0.000   0.000   0.000  1.00  0.00           C\nEND\n", encoding="utf-8"
    )
    _run_normalizer(tmp_path, monkeypatch)

    with (tmp_path / "pockets.csv").open(encoding="utf-8", newline="") as handle:
        pockets = list(csv.DictReader(handle))
    assert [row["segmented"] for row in pockets] == ["True", "False", "False"]
    with (tmp_path / "residues.csv").open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle))
