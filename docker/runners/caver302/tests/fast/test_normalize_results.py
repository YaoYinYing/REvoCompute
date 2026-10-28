# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Normalization of authentic CAVER 3.0.2 output.

The fixtures are bounded slices of the guided-example output shipped inside the
pinned distribution, not values this project produced or recomputed. The tests
therefore assert the declared table shape and a handful of exact upstream
numbers, plus every refusal path: a missing, empty, malformed or internally
inconsistent output is an error rather than a partial success.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / "docker/runners/caver302"
FIXTURES = Path(__file__).resolve().parent / "fixtures/caver"
sys.path.insert(0, str(FAMILY))

from normalize_results import OutputError, normalize  # noqa: E402

RAW_FILES = {
    "summary.txt": FIXTURES / "summary.txt",
    "analysis/tunnel_characteristics.csv": FIXTURES / "tunnel_characteristics.csv",
    "analysis/tunnel_profiles.csv": FIXTURES / "tunnel_profiles.csv",
    "analysis/bottlenecks.csv": FIXTURES / "bottlenecks.csv",
    "analysis/residues.txt": FIXTURES / "residues.txt",
    "analysis/atoms.txt": FIXTURES / "atoms.txt",
    "log.txt": FIXTURES / "log.txt",
}


def prepare(tmp_path: Path) -> tuple[Path, Path]:
    raw = tmp_path / "caver_out"
    output = tmp_path / "published"
    output.mkdir()
    for relative, source in RAW_FILES.items():
        target = raw / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    return raw, output


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_normalizes_authentic_output_into_declared_tables(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    summary = normalize(raw, output, {"task_type": "caver", "start_point": {"mode": "ligand"}})

    clusters = read_csv(output / "clusters.csv")
    assert len(clusters) == 5
    assert clusters[0] == {
        "cluster": "1",
        "tunnel_count": "50",
        "snapshot_count": "50",
        "mean_bottleneck_radius_angstrom": "1.413",
        "max_bottleneck_radius_angstrom": "2.33",
        "mean_length_angstrom": "13.943",
        "mean_curvature": "1.304",
        "priority": "0.61847",
        "mean_throughput": "0.61847",
    }

    tunnels = read_csv(output / "tunnels.csv")
    assert len(tunnels) == 83
    assert tunnels[0]["snapshot"] == "1.pdb"
    assert tunnels[0]["tunnel_cluster"] == "1"
    assert tunnels[0]["bottleneck_radius_angstrom"] == "1.017582313"
    assert tunnels[0]["length_angstrom"] == "16.47202939"
    assert tunnels[0]["curvature"] == "1.349512442"

    profiles = read_csv(output / "profiles.csv")
    assert len(profiles) == 35
    assert profiles[0] == {
        "snapshot": "1.pdb",
        "tunnel_cluster": "1",
        "tunnel": "1",
        "point_index": "0",
        "x_angstrom": "8.52287",
        "y_angstrom": "-0.0760703",
        "z_angstrom": "0.224005",
        "distance_angstrom": "0.726004",
        "length_angstrom": "0.726004",
        "radius_angstrom": "1.644",
    }

    bottlenecks = read_csv(output / "bottlenecks.csv")
    assert len(bottlenecks) == 9
    assert bottlenecks[0]["bottleneck_x_angstrom"] == "12.1187"
    assert bottlenecks[0]["bottleneck_radius_angstrom"] == "1.01758"
    assert bottlenecks[0]["bottleneck_residues"].startswith("X:146")

    residues = read_csv(output / "residues.csv")
    assert len(residues) == 39
    assert residues[0]["chain"] == "X"
    assert residues[0]["residue_number"] == "38"
    assert residues[0]["residue_name"] == "ASN"
    assert residues[0]["snapshot_count"] == "50"
    assert residues[0]["lining_atoms"].startswith("50:H_570")

    assert (output / "atoms.txt").read_text(encoding="utf-8").startswith("#")
    assert (output / "log.txt").read_text(encoding="utf-8").startswith("Caver computation started.")
    assert not (output / "warnings.txt").exists()

    assert summary["cluster_count"] == 5
    assert summary["tunnel_count"] == 83
    assert summary["profile_point_count"] == 35
    assert summary["bottleneck_row_count"] == 9
    assert summary["lining_residue_count"] == 39
    assert summary["cluster_ids"] == [1, 2, 3, 4, 5]
    assert len(summary["snapshot_labels"]) == 50
    assert len(summary["cluster_table_sha256"]) == 64
    assert len(summary["tunnel_table_sha256"]) == 64
    assert summary["start_point"] == {"mode": "ligand"}
    assert json.loads((output / "summary.json").read_text(encoding="utf-8")) == summary


def test_missing_required_output_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    (raw / "summary.txt").unlink()
    with pytest.raises(OutputError, match="summary.txt"):
        normalize(raw, output, {})


def test_empty_summary_table_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    text = (raw / "summary.txt").read_text(encoding="utf-8")
    header = next(line for line in text.splitlines() if line.split()[:2] == ["ID", "No"])
    (raw / "summary.txt").write_text(header + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="no tunnel clusters"):
        normalize(raw, output, {})


def test_non_finite_or_non_numeric_value_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    lines = (raw / "analysis/tunnel_characteristics.csv").read_text(encoding="utf-8").splitlines()
    fields = lines[1].split(", ")
    fields[3] = "nan"
    lines[1] = ", ".join(fields)
    (raw / "analysis/tunnel_characteristics.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="not finite"):
        normalize(raw, output, {})


def test_profile_axis_length_mismatch_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    lines = (raw / "analysis/tunnel_profiles.csv").read_text(encoding="utf-8").splitlines()
    lines[-1] = lines[-1] + ", 1.0"
    (raw / "analysis/tunnel_profiles.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="different lengths"):
        normalize(raw, output, {})


def test_tunnel_absent_from_characteristics_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    lines = (raw / "analysis/tunnel_profiles.csv").read_text(encoding="utf-8").splitlines()
    lines = [line.replace("1.pdb, 1, 1,", "1.pdb, 1, 99,", 1) if index else line for index, line in enumerate(lines)]
    (raw / "analysis/tunnel_profiles.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="absent from tunnel_characteristics.csv"):
        normalize(raw, output, {})
