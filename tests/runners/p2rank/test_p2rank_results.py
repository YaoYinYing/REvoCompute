# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/p2rank"
FIXTURES = ROOT / "tests/data/p2rank"


def _normalize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> subprocess.CompletedProcess[str]:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "1SUO.pdb_predictions.csv").write_text(
        (FIXTURES / "1SUO.pdb_predictions.csv").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "1SUO.pdb_residues.csv").write_text(
        (FIXTURES / "1SUO.pdb_residues.csv").read_text(encoding="utf-8"), encoding="utf-8"
    )
    provenance = tmp_path / "run.json"
    provenance.write_text(json.dumps({"task_type": "p2rank"}), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(FAMILY / "normalize_results.py"), str(tmp_path), "--provenance", str(provenance)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_normalizer_converts_real_p2rank_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _normalize(tmp_path, monkeypatch)

    with (tmp_path / "pockets.csv").open(encoding="utf-8", newline="") as handle:
        pockets = list(csv.DictReader(handle))
    assert [row["pocket"] for row in pockets] == ["pocket1", "pocket2", "pocket3", "pocket4"]
    assert [int(row["rank"]) for row in pockets] == [1, 2, 3, 4]
    assert pockets[0]["center_x"] == "-21.0419"
    assert int(pockets[0]["residue_count"]) == 36
    assert int(pockets[0]["surface_atom_count"]) == 77
    scores = [float(row["score"]) for row in pockets]
    assert scores == sorted(scores, reverse=True)

    with (tmp_path / "residue_scores.csv").open(encoding="utf-8", newline="") as handle:
        residues = list(csv.DictReader(handle))
    assert len(residues) == 465
    assert set(residues[0]) == {"chain", "residue_label", "residue_name", "score", "zscore", "probability", "pocket"}

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["ranking_order"] == "descending"
    assert summary["pocket_count"] == 4
    assert summary["residue_count"] == 465
    assert summary["units"] == {"center_x": "angstrom", "center_y": "angstrom", "center_z": "angstrom"}


@pytest.mark.parametrize(
    ("prediction_rows", "residues", "message"),
    [
        ([], "chain, residue_label, residue_name, score, zscore, probability, pocket\n", "no pockets"),
    ],
)
def test_normalizer_rejects_empty_prediction_table(
    tmp_path: Path, prediction_rows: list[str], residues: str, message: str
) -> None:
    header = "name     ,  rank,   score, probability, sas_points, surf_atoms,   center_x,   center_y,   center_z, residue_ids, surf_atom_ids\n"
    (tmp_path / "1abc.pdb_predictions.csv").write_text(header + "".join(prediction_rows), encoding="utf-8")
    (tmp_path / "1abc.pdb_residues.csv").write_text(residues, encoding="utf-8")
    provenance = tmp_path / "run.json"
    provenance.write_text("{}", encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        subprocess.run(
            [sys.executable, str(FAMILY / "normalize_results.py"), str(tmp_path), "--provenance", str(provenance)],
            check=True,
            capture_output=True,
            text=True,
        )
    assert message in failure.value.stderr
