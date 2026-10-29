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

from normalize_results import (  # noqa: E402
    OutputError,
    normalize,
    parse_bottlenecks,
    parse_characteristics,
    parse_profiles,
    parse_residues,
    parse_summary,
)

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
    # One authentic profile point per tunnel: the fixture is the guided-example
    # profile table sliced to the first point of every axis.
    assert len(profiles) == 83
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
    assert len(bottlenecks) == 83
    assert bottlenecks[0]["bottleneck_x_angstrom"] == "12.1187"
    assert bottlenecks[0]["bottleneck_radius_angstrom"] == "1.01758"
    # Every contacting residue is published, not just the first.
    assert bottlenecks[0]["bottleneck_residues"] == "X:146,X:142,X:173,X:242,X:169,X:138,X:141,X:145"

    residues = read_csv(output / "residues.csv")
    assert len(residues) == 171
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
    assert summary["profile_point_count"] == 83
    assert summary["bottleneck_row_count"] == 83
    # A residue can line several clusters; 44 of the 171 rows repeat a residue.
    assert summary["lining_residue_row_count"] == 171
    assert summary["lining_residue_count"] == 72
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


def test_malformed_utf8_output_is_an_error(tmp_path: Path) -> None:
    parsers = {
        "summary.txt": parse_summary,
        "tunnel_characteristics.csv": parse_characteristics,
        "tunnel_profiles.csv": parse_profiles,
        "bottlenecks.csv": parse_bottlenecks,
        "residues.txt": parse_residues,
    }
    for name, parser in parsers.items():
        path = tmp_path / name
        path.write_bytes((FIXTURES / name).read_bytes() + b"\xff\n")
        with pytest.raises(OutputError, match="is not valid UTF-8 text"):
            parser(path)


def test_non_integer_summary_identity_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "summary.txt"
    lines = (FIXTURES / "summary.txt").read_text(encoding="utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if len(line.split()) == 18 and line.split()[0].isdigit())
    fields = lines[index].split()
    fields[0] = "one"
    lines[index] = "  ".join(fields)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="summary.txt has a non-integer cluster ID"):
        parse_summary(path)


def test_non_integer_characteristic_tunnel_key_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "tunnel_characteristics.csv"
    rows = list(csv.reader((FIXTURES / "tunnel_characteristics.csv").read_text(encoding="utf-8").splitlines()))
    rows[1][[cell.strip() for cell in rows[0]].index("Tunnel cluster")] = "x"
    path.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="tunnel_characteristics.csv has a non-integer Tunnel cluster"):
        parse_characteristics(path)


def test_non_integer_profile_tunnel_key_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "tunnel_profiles.csv"
    rows = list(csv.reader((FIXTURES / "tunnel_profiles.csv").read_text(encoding="utf-8").splitlines()))
    axis_index = [cell.strip() for cell in rows[0]].index("Axis")
    row = next(candidate for candidate in rows[1:] if candidate[axis_index].strip() == "X")
    row[[cell.strip() for cell in rows[0]].index("Tunnel")] = "x"
    path.write_text("\n".join(",".join(candidate) for candidate in rows) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="tunnel_profiles.csv has a non-integer Tunnel"):
        parse_profiles(path)


def test_non_integer_bottleneck_tunnel_key_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "bottlenecks.csv"
    lines = (FIXTURES / "bottlenecks.csv").read_text(encoding="utf-8").splitlines()
    header_index = next(i for i, line in enumerate(lines) if line.startswith("Snapshot,"))
    rows = list(csv.reader(lines[header_index:]))
    rows[1][[cell.strip() for cell in rows[0]].index("Tunnel cluster")] = "x"
    path.write_text("\n".join([*lines[:header_index], *((",".join(row)) for row in rows)]) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="bottlenecks.csv has a non-integer Tunnel cluster"):
        parse_bottlenecks(path)


def test_non_integer_residue_snapshot_count_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "residues.txt"
    lines = (FIXTURES / "residues.txt").read_text(encoding="utf-8").splitlines()
    index = next(
        i
        for i, line in enumerate(lines)
        if line.strip() and not line.lstrip().startswith(("#", "==")) and len(line[14:].split()) >= 2
    )
    fields = lines[index][14:].split()
    fields[0] = "x"
    lines[index] = lines[index][:14] + " ".join(fields)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="residues.txt has a non-integer snapshot count"):
        parse_residues(path)


def test_profile_axis_length_mismatch_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    lines = (raw / "analysis/tunnel_profiles.csv").read_text(encoding="utf-8").splitlines()
    lines[-1] = lines[-1] + ", 1.0"
    (raw / "analysis/tunnel_profiles.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="different lengths"):
        normalize(raw, output, {})


def _blank_axis(raw: Path, axis: str) -> None:
    """Rewrite one profile axis row the way CAVER does when it is not computed."""
    path = raw / "analysis/tunnel_profiles.csv"
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    axis_index = [cell.strip() for cell in rows[0]].index("Axis")
    for row in rows[1:]:
        if row[axis_index].strip() == axis:
            for index in range(axis_index + 1, len(row)):
                row[index] = "-"
    path.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")


def test_uncomputed_error_axis_is_skipped(tmp_path: Path) -> None:
    """compute_errors no writes '-' in the optional error axes; the geometric axes still parse."""
    raw, output = prepare(tmp_path)
    _blank_axis(raw, "Upper limit of R overestimation")
    summary = normalize(raw, output, {})
    assert summary["profile_point_count"] == 83
    assert read_csv(output / "profiles.csv")[0]["radius_angstrom"] == "1.644"


def test_uncomputed_required_axis_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    _blank_axis(raw, "R")
    with pytest.raises(OutputError, match="not a number"):
        normalize(raw, output, {})


def test_bottleneck_row_keeps_every_contacting_residue() -> None:
    rows = parse_bottlenecks(FIXTURES / "bottlenecks_multi.csv")
    assert rows[0]["bottleneck_residues"] == "A:500,A:367,A:600,A:363"


def test_blank_chain_residues_are_parsed_by_column() -> None:
    rows = parse_residues(FIXTURES / "residues_blank_chain.txt")
    assert rows[0]["chain"] == ""
    assert rows[0]["residue_number"] == 98
    assert rows[0]["residue_name"] == "ARG"
    assert rows[0]["lining_atoms"].startswith("1:CD_541")


def test_insertion_coded_residues_are_parsed_by_column() -> None:
    rows = parse_residues(FIXTURES / "residues_insertion_code.txt")
    assert [(row["residue_number"], row["insertion_code"]) for row in rows] == [(100, "A"), (100, "")]


def test_lining_residue_count_counts_distinct_residues() -> None:
    rows = parse_residues(FIXTURES / "residues_duplicates.txt")
    assert len(rows) == 3
    # A:98 lines two clusters, so the distinct count must be smaller than the row count.
    assert {(row["chain"], row["residue_number"]) for row in rows} == {("A", 98), ("A", 101)}


def _summary_lines(raw: Path) -> list[str]:
    return (raw / "summary.txt").read_text(encoding="utf-8").splitlines()


def _rewrite_summary_field(raw: Path, cluster: int, field: int, value: int) -> None:
    """Rewrite one numeric field of one tunnel-cluster summary row."""
    lines = _summary_lines(raw)
    for index, line in enumerate(lines):
        fields = line.split()
        if len(fields) == 18 and fields[0].lstrip("-").isdigit() and int(fields[0]) == cluster:
            fields[field] = str(value)
            lines[index] = "  ".join(fields)
            break
    else:
        raise AssertionError(f"summary row for cluster {cluster} not found")
    (raw / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_missing_bottleneck_row_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    lines = (raw / "analysis/bottlenecks.csv").read_text(encoding="utf-8").splitlines()
    (raw / "analysis/bottlenecks.csv").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="has no bottleneck row for tunnel"):
        normalize(raw, output, {})


def test_duplicate_bottleneck_row_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    path = raw / "analysis/bottlenecks.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([*lines, lines[-1]]) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match=r"bottlenecks\.csv repeats tunnel \('18\.pdb', 5, 2\)"):
        normalize(raw, output, {})


def test_duplicate_profile_axis_row_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    path = raw / "analysis/tunnel_profiles.csv"
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    axis_index = [cell.strip() for cell in rows[0]].index("Axis")
    duplicate = [*next(row for row in rows[1:] if row[axis_index].strip() == "X")]
    duplicate[-1] = "99.0"
    rows.append(duplicate)
    path.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match=r"tunnel_profiles\.csv repeats the 'X' axis for tunnel \('1\.pdb', 1, 1\)"):
        normalize(raw, output, {})


def test_duplicate_characteristic_row_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    path = raw / "analysis/tunnel_characteristics.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([*lines, lines[-1]]) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match=r"tunnel_characteristics\.csv repeats tunnel \('18\.pdb', 5, 2\)"):
        normalize(raw, output, {})


def test_multi_point_profile_and_many_lining_residues_still_pass(tmp_path: Path) -> None:
    """One row per axis may carry many profile points, and a residue block many rows."""
    raw, output = prepare(tmp_path)
    path = raw / "analysis/tunnel_profiles.csv"
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    for row in rows[1:]:
        if [cell.strip() for cell in row[:3]] == ["1.pdb", "1", "1"]:
            row.append("2.5")
    path.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")

    summary = normalize(raw, output, {})
    assert summary["profile_point_count"] == 84
    assert summary["lining_residue_row_count"] == 171
    profiles = read_csv(output / "profiles.csv")
    second_point = [
        profile
        for profile in profiles
        if (profile["snapshot"], profile["tunnel_cluster"], profile["tunnel"], profile["point_index"])
        == ("1.pdb", "1", "1", "1")
    ]
    assert [profile["x_angstrom"] for profile in second_point] == ["2.5"]


def test_missing_profile_rows_are_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    path = raw / "analysis/tunnel_profiles.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [lines[0]]
    for line in lines[1:]:
        cells = [cell.strip() for cell in line.split(",")]
        if cells[0] == "2.pdb" and cells[1] == "1" and cells[2] == "1":
            continue
        kept.append(line)
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="has no points for tunnel"):
        normalize(raw, output, {})


def test_missing_residue_block_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    path = raw / "analysis/residues.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = lines[: lines.index("== Tunnel cluster 5 ==")]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="has no residue rows for tunnel cluster 5"):
        normalize(raw, output, {})


def test_summary_tunnel_count_mismatch_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    _rewrite_summary_field(raw, 1, 1, 49)
    with pytest.raises(OutputError, match="summary.txt reports 82 tunnels"):
        normalize(raw, output, {})


def test_summary_snapshot_count_mismatch_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    _rewrite_summary_field(raw, 2, 2, 27)
    with pytest.raises(OutputError, match="reports 27 snapshots in cluster 2"):
        normalize(raw, output, {})


def test_residues_with_an_unknown_cluster_are_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    text = (raw / "analysis/residues.txt").read_text(encoding="utf-8").replace("Tunnel cluster 1 ==", "Tunnel cluster 99 ==")
    (raw / "analysis/residues.txt").write_text(text, encoding="utf-8")
    with pytest.raises(OutputError, match="unknown tunnel cluster 99"):
        normalize(raw, output, {})


def test_snapshot_labels_are_ordered_numerically(tmp_path: Path) -> None:
    from normalize_results import _snapshot_order

    labels = ["1.pdb", "2.pdb", "10.pdb"]
    assert sorted(reversed(labels), key=_snapshot_order) == labels


def test_tunnel_absent_from_characteristics_is_an_error(tmp_path: Path) -> None:
    raw, output = prepare(tmp_path)
    lines = (raw / "analysis/tunnel_profiles.csv").read_text(encoding="utf-8").splitlines()
    lines = [line.replace("1.pdb, 1, 1,", "1.pdb, 1, 99,", 1) if index else line for index, line in enumerate(lines)]
    (raw / "analysis/tunnel_profiles.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(OutputError, match="absent from tunnel_characteristics.csv"):
        normalize(raw, output, {})
