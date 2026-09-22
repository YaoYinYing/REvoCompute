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
FAMILY = ROOT / "docker/runners/fpocket"
FIXTURES = ROOT / "tests/data/fpocket"


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


def _copy_run(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "1SUO_out").mkdir(parents=True)
    shutil.copytree(FIXTURES / "1SUO_out", work / "1SUO_out", dirs_exist_ok=True)


def test_normalizer_reads_real_fpocket_output_tree(tmp_path: Path, monkeypatch) -> None:
    _copy_run(tmp_path)
    _run_normalizer(tmp_path, monkeypatch, {"parameters": {"volume_monte_carlo_iterations": 100}})

    with (tmp_path / "pockets.csv").open(encoding="utf-8", newline="") as handle:
        pockets = list(csv.DictReader(handle))
    assert [row["pocket"] for row in pockets] == [f"pocket{index}" for index in range(1, len(pockets) + 1)]
    assert [int(row["rank"]) for row in pockets] == list(range(1, len(pockets) + 1))
    scores = [float(row["score"]) for row in pockets]
    assert scores == sorted(scores, reverse=True)
    first = pockets[0]
    assert first["druggability_score"]
    assert first["volume_angstrom3"]
    for axis in ("center_x", "center_y", "center_z"):
        float(first[axis])
    assert int(first["residue_count"]) == len(first["residue_ids"].split())
    assert int(first["atom_count"]) > 0

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["ranking_order"] == "descending"
    assert summary["pocket_count"] == len(pockets)
    assert summary["units"]["volume_angstrom3"] == "angstrom^3"
    assert summary["provenance"]["parameters"]["volume_monte_carlo_iterations"] == 100


def test_normalizer_rejects_a_run_without_pockets(tmp_path: Path, monkeypatch) -> None:
    work = tmp_path / "work"
    (work / "1SUO_out/pockets").mkdir(parents=True)
    (work / "1SUO_out/1SUO_info.txt").write_text("No pockets found\n", encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run_normalizer(tmp_path, monkeypatch)
    assert "no pockets" in failure.value.stderr


def test_normalizer_rejects_a_pocket_missing_its_vertex_file(tmp_path: Path, monkeypatch) -> None:
    _copy_run(tmp_path)
    (tmp_path / "work/1SUO_out/pockets/pocket1_vert.pqr").unlink()
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run_normalizer(tmp_path, monkeypatch)
    assert "missing its vertex or atom file" in failure.value.stderr


def test_normalizer_keeps_pdb_insertion_codes_distinct(tmp_path: Path, monkeypatch) -> None:
    """A residue with an insertion code is not the residue with the bare number."""
    _copy_run(tmp_path)
    atoms = tmp_path / "work/1SUO_out/pockets/pocket1_atm.pdb"
    line = "ATOM      1  CA  GLY A  42       0.000   0.000   0.000  1.00  0.00           C\n"
    insertion = "ATOM      1  CA  GLY A  42A      0.000   0.000   0.000  1.00  0.00           C\n"
    atoms.write_text(line + insertion + "END\n", encoding="utf-8")
    _run_normalizer(tmp_path, monkeypatch)

    with (tmp_path / "pockets.csv").open(encoding="utf-8", newline="") as handle:
        residues = csv.DictReader(handle).__next__()["residue_ids"].split()
    assert residues == ["A_42", "A_42A"]
