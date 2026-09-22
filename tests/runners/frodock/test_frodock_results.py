# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import csv
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker/runners/frodock"


def _write_clustered(path: Path, records: list[tuple[float, ...]], declared: int | None = None) -> None:
    payload = struct.pack("<i", declared if declared is not None else len(records))
    payload += struct.pack("<3f", 0.0, 0.0, 0.0)
    for record in records:
        payload += struct.pack("<7f", *record)
    path.write_bytes(payload)


def _record(correlation: float, index: int = 1) -> tuple[float, ...]:
    return (float(index), float(index), float(index), 1.5, -2.5, 3.5, correlation)


def _prepare(tmp_path: Path, records: list[tuple[float, ...]], poses: list[dict[str, object]] | None = None) -> None:
    _write_clustered(tmp_path / "clustered_solutions.dat", records)
    for index in range(1, len(records) + 1):
        (tmp_path / f"lig_kinase_{index}.pdb").write_text("ATOM      1  CA  ALA A   1       0.0   0.0   0.0\nEND\n", encoding="ascii")
    pose_rows = poses if poses is not None else [
        {
            "posed_file": f"lig_kinase_{index}.pdb",
            "rank": index,
            "correlation_score": round(record[6], 4),
            "euler_z_deg": round(record[0], 4),
            "euler_y_deg": round(record[1], 4),
            "euler_z2_deg": round(record[2], 4),
            "translation_x_angstrom": round(record[3], 4),
            "translation_y_angstrom": round(record[4], 4),
            "translation_z_angstrom": round(record[5], 4),
        }
        for index, record in enumerate(records, start=1)
    ]
    (tmp_path / "poses.json").write_text(
        json.dumps({"raw_solution_count": len(records), "ranking_metric": "correlation_score", "poses": pose_rows}),
        encoding="utf-8",
    )
    (tmp_path / "frodock-run.json").write_text(json.dumps({"task_type": "frodock"}), encoding="utf-8")


def _normalize(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FAMILY / "normalize_results.py"), str(tmp_path),
         "--provenance", str(tmp_path / "frodock-run.json")],
        check=True,
        capture_output=True,
        text=True,
    )


def test_normalizer_writes_ranked_poses_with_scores_and_transforms(tmp_path: Path) -> None:
    _prepare(tmp_path, [_record(215.5285), _record(194.987, index=2), _record(162.786, index=3)])
    _normalize(tmp_path)

    with (tmp_path / "poses.csv").open(encoding="utf-8", newline="") as handle:
        poses = list(csv.DictReader(handle))
    assert [int(row["rank"]) for row in poses] == [1, 2, 3]
    assert [row["pose_file"] for row in poses] == ["lig_kinase_1.pdb", "lig_kinase_2.pdb", "lig_kinase_3.pdb"]
    assert poses[0]["correlation_score"] == "215.5285"
    assert poses[0]["translation_z_angstrom"] == "3.5"

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["ranking_order"] == "descending"
    assert summary["pose_count"] == 3
    assert summary["raw_solution_count"] == 3
    assert summary["provenance"]["pose_count"] == 3


def test_normalizer_rejects_a_solution_file_shorter_than_its_declared_count(tmp_path: Path) -> None:
    _prepare(tmp_path, [_record(215.5)])
    _write_clustered(tmp_path / "clustered_solutions.dat", [_record(215.5)], declared=5)
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _normalize(tmp_path)
    assert "does not match its declared" in failure.value.stderr


def test_normalizer_rejects_a_pose_without_coordinates(tmp_path: Path) -> None:
    _prepare(tmp_path, [_record(215.5)])
    (tmp_path / "lig_kinase_1.pdb").write_text("", encoding="ascii")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _normalize(tmp_path)
    assert "missing or empty" in failure.value.stderr


def test_normalizer_rejects_scores_that_are_not_ranked_descending(tmp_path: Path) -> None:
    _prepare(tmp_path, [_record(100.0), _record(200.0, index=2)])
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _normalize(tmp_path)
    assert "descending correlation order" in failure.value.stderr


def test_normalizer_rejects_a_pose_record_that_disagrees_with_the_solution_file(tmp_path: Path) -> None:
    _prepare(tmp_path, [_record(215.5)])
    payload = json.loads((tmp_path / "poses.json").read_text(encoding="utf-8"))
    payload["raw_solution_count"] = 9
    (tmp_path / "poses.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _normalize(tmp_path)
    assert "disagrees with the clustered solution file" in failure.value.stderr
