#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Normalize authentic CAVER 3.0.2 output into the Task's declared result tables.

Every input path below is one of the fixed files the pinned distribution
documents and the packaged guided example actually produces; nothing is
discovered by globbing. CAVER writes compact summary tables, per-axis profile
rows and block-structured residue lists, so this module only reshapes those
numbers into columns with explicit Angstrom units. It never recomputes a
scientific quantity: a value missing from CAVER's output is an error, not a
zero.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
from collections import Counter
from pathlib import Path

SUMMARY_COLUMNS = (
    "ID",
    "No",
    "No_snaps",
    "Avg_BR",
    "SD",
    "Max_BR",
    "Avg_L",
    "SD",
    "Avg_C",
    "SD",
    "Priority",
    "Avg_throughput",
    "SD",
    "Avg_up_E_BR",
    "SD",
    "Max_up_E_BR",
    "Avg_up_E_TR",
    "Max_up_E_TR",
)
CLUSTER_FIELDS = (
    "cluster",
    "tunnel_count",
    "snapshot_count",
    "mean_bottleneck_radius_angstrom",
    "max_bottleneck_radius_angstrom",
    "mean_length_angstrom",
    "mean_curvature",
    "priority",
    "mean_throughput",
)
TUNNEL_FIELDS = (
    "snapshot",
    "tunnel_cluster",
    "tunnel",
    "throughput",
    "cost",
    "bottleneck_radius_angstrom",
    "length_angstrom",
    "curvature",
)
PROFILE_FIELDS = (
    "snapshot",
    "tunnel_cluster",
    "tunnel",
    "point_index",
    "x_angstrom",
    "y_angstrom",
    "z_angstrom",
    "distance_angstrom",
    "length_angstrom",
    "radius_angstrom",
)
BOTTLENECK_FIELDS = (
    "snapshot",
    "tunnel_cluster",
    "tunnel",
    "throughput",
    "cost",
    "bottleneck_x_angstrom",
    "bottleneck_y_angstrom",
    "bottleneck_z_angstrom",
    "bottleneck_radius_angstrom",
    "bottleneck_residues",
)
RESIDUE_FIELDS = (
    "tunnel_cluster",
    "chain",
    "residue_number",
    "insertion_code",
    "residue_name",
    "snapshot_count",
    "sidechain_snapshot_count",
    "lining_atoms",
)


class OutputError(ValueError):
    """A required CAVER output file is missing, malformed, or empty."""


def require_file(path: Path) -> Path:
    if not path.is_file() or path.stat().st_size == 0:
        raise OutputError(f"CAVER did not produce {path.name}")
    return path


def number(text: str, field: str) -> float:
    try:
        value = float(text.strip())
    except ValueError as exc:
        raise OutputError(f"{field} is not a number: {text!r}") from exc
    if not math.isfinite(value):
        raise OutputError(f"{field} is not finite: {text!r}")
    return value


def optional_number(text: str) -> str:
    stripped = text.strip()
    return "" if stripped in ("", "-") else f"{number(stripped, 'value'):.10g}"


def parse_summary(path: Path) -> list[dict[str, object]]:
    """Parse the fixed-width tunnel-cluster summary table."""
    lines = path.read_text(encoding="utf-8").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if tuple(line.split()) == SUMMARY_COLUMNS),
        None,
    )
    if header_index is None:
        raise OutputError("summary.txt has no recognized tunnel-cluster table")
    clusters = []
    for line in lines[header_index + 1 :]:
        if not line.strip():
            break
        fields = line.split()
        if len(fields) != len(SUMMARY_COLUMNS):
            raise OutputError("summary.txt contains a malformed tunnel-cluster row")
        clusters.append(
            {
                "cluster": int(fields[0]),
                "tunnel_count": int(fields[1]),
                "snapshot_count": int(fields[2]),
                "mean_bottleneck_radius_angstrom": optional_number(fields[3]),
                "max_bottleneck_radius_angstrom": optional_number(fields[5]),
                "mean_length_angstrom": optional_number(fields[6]),
                "mean_curvature": optional_number(fields[8]),
                "priority": optional_number(fields[10]),
                "mean_throughput": optional_number(fields[11]),
            }
        )
    if not clusters:
        raise OutputError("summary.txt reports no tunnel clusters")
    return clusters


def _csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [[cell.strip() for cell in row] for row in csv.reader(handle)]
    if not rows:
        raise OutputError(f"{path.name} is empty")
    return rows[0], rows[1:]


def parse_characteristics(path: Path) -> list[dict[str, object]]:
    """Parse the per-tunnel, per-snapshot characteristics table."""
    header, rows = _csv_rows(path)
    required = ("Snapshot", "Tunnel cluster", "Tunnel", "Throughput", "Cost", "Bottleneck radius", "Length", "Curvature")
    missing = [name for name in required if name not in header]
    if missing:
        raise OutputError(f"tunnel_characteristics.csv lacks columns: {', '.join(missing)}")
    index = {name: header.index(name) for name in required}
    tunnels = []
    for row in rows:
        if not row or not any(row):
            continue
        if len(row) < len(header):
            raise OutputError("tunnel_characteristics.csv contains a truncated row")
        tunnels.append(
            {
                "snapshot": row[index["Snapshot"]],
                "tunnel_cluster": int(row[index["Tunnel cluster"]]),
                "tunnel": int(row[index["Tunnel"]]),
                "throughput": f"{number(row[index['Throughput']], 'Throughput'):.10g}",
                "cost": f"{number(row[index['Cost']], 'Cost'):.10g}",
                "bottleneck_radius_angstrom": f"{number(row[index['Bottleneck radius']], 'Bottleneck radius'):.10g}",
                "length_angstrom": f"{number(row[index['Length']], 'Length'):.10g}",
                "curvature": f"{number(row[index['Curvature']], 'Curvature'):.10g}",
            }
        )
    if not tunnels:
        raise OutputError("CAVER reported no tunnels")
    return tunnels


def parse_profiles(path: Path) -> list[dict[str, object]]:
    """Merge CAVER's per-axis profile rows into one row per profile point."""
    header, rows = _csv_rows(path)
    if "Axis" not in header:
        raise OutputError("tunnel_profiles.csv has no Axis column")
    axis_index = header.index("Axis")
    key_names = ("Snapshot", "Tunnel cluster", "Tunnel")
    if any(name not in header for name in key_names):
        raise OutputError("tunnel_profiles.csv lacks snapshot/tunnel key columns")
    key_index = {name: header.index(name) for name in key_names}
    required_axes = ("X", "Y", "Z", "distance", "length", "R")
    grouped: dict[tuple[str, int, int], dict[str, list[float]]] = {}
    seen: set[tuple[str, int, int, str]] = set()
    for row in rows:
        if not row or not any(row):
            continue
        if len(row) <= axis_index:
            raise OutputError("tunnel_profiles.csv contains a truncated row")
        axis = row[axis_index]
        raw_values = row[axis_index + 1 :]
        try:
            values = [number(cell, f"Axis {axis}") for cell in raw_values]
        except OutputError:
            # Optional error axes are written as "-" when compute_errors is
            # off; only the geometric axes are required to be numeric.
            if axis in required_axes:
                raise
            continue
        if not values:
            raise OutputError(f"tunnel_profiles.csv has no values for axis {axis!r}")
        key = (
            row[key_index["Snapshot"]],
            int(row[key_index["Tunnel cluster"]]),
            int(row[key_index["Tunnel"]]),
        )
        if (*key, axis) in seen:
            # CAVER writes one row per axis; a repeated axis would silently
            # replace the earlier values, so the published geometry would
            # depend on row order.
            raise OutputError(f"tunnel_profiles.csv repeats the {axis!r} axis for tunnel {key}")
        seen.add((*key, axis))
        grouped.setdefault(key, {})[axis] = values
    points = []
    for (snapshot, cluster, tunnel), axes in grouped.items():
        lengths = {len(values) for values in axes.values()}
        if len(lengths) != 1:
            raise OutputError(f"profile axes for {snapshot} tunnel {tunnel} have different lengths")
        missing = [axis for axis in required_axes if axis not in axes]
        if missing:
            raise OutputError(f"profile for {snapshot} tunnel {tunnel} lacks axes: {', '.join(missing)}")
        for index in range(len(axes["R"])):
            points.append(
                {
                    "snapshot": snapshot,
                    "tunnel_cluster": cluster,
                    "tunnel": tunnel,
                    "point_index": index,
                    "x_angstrom": f"{axes['X'][index]:.6g}",
                    "y_angstrom": f"{axes['Y'][index]:.6g}",
                    "z_angstrom": f"{axes['Z'][index]:.6g}",
                    "distance_angstrom": f"{axes['distance'][index]:.6g}",
                    "length_angstrom": f"{axes['length'][index]:.6g}",
                    "radius_angstrom": f"{axes['R'][index]:.6g}",
                }
            )
    if not points:
        raise OutputError("tunnel_profiles.csv contains no profile points")
    return points


def parse_bottlenecks(path: Path) -> list[dict[str, object]]:
    """Parse the bottleneck residue table, skipping its explanatory first line."""
    lines = path.read_text(encoding="utf-8").splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.startswith("Snapshot,")), None)
    if header_index is None:
        raise OutputError("bottlenecks.csv has no header row")
    header = next(csv.reader([lines[header_index]]))
    header = [cell.strip() for cell in header]
    if "Bottleneck residues" not in header:
        raise OutputError("bottlenecks.csv has no Bottleneck residues column")
    residues_index = header.index("Bottleneck residues")
    index = {name: header.index(name) for name in header if name != "Bottleneck residues"}
    rows = []
    for cells in csv.reader(lines[header_index + 1 :]):
        cells = [cell.strip() for cell in cells]
        if not cells or not any(cells):
            continue
        if len(cells) < len(header):
            raise OutputError("bottlenecks.csv contains a truncated row")
        rows.append(
            {
                "snapshot": cells[index["Snapshot"]],
                "tunnel_cluster": int(cells[index["Tunnel cluster"]]),
                "tunnel": int(cells[index["Tunnel"]]),
                "throughput": f"{number(cells[index['Throughput']], 'Throughput'):.10g}",
                "cost": f"{number(cells[index['Cost']], 'Cost'):.10g}",
                "bottleneck_x_angstrom": f"{number(cells[index['Bottleneck X']], 'Bottleneck X'):.6g}",
                "bottleneck_y_angstrom": f"{number(cells[index['Bottleneck Y']], 'Bottleneck Y'):.6g}",
                "bottleneck_z_angstrom": f"{number(cells[index['Bottleneck Z']], 'Bottleneck Z'):.6g}",
                "bottleneck_radius_angstrom": f"{number(cells[index['Bottleneck R']], 'Bottleneck R'):.6g}",
                # Every residue column after the last numeric one belongs to
                # the list; a DictReader would drop all but the first.
                "bottleneck_residues": ",".join(cell for cell in cells[residues_index:] if cell),
            }
        )
    if not rows:
        raise OutputError("bottlenecks.csv reports no bottleneck residues")
    return rows


def _split_residue(token: str) -> tuple[int, str]:
    body = token[:-1] if token[-1:].isalpha() else token
    icode = token[-1] if token[-1:].isalpha() else ""
    try:
        return int(body), icode
    except ValueError as exc:
        raise OutputError(f"residue index is not numeric: {token!r}") from exc


#: Fixed columns of a residues.txt data row, verified against real CAVER output:
#: the chain is one character at offset 2 (blank for a structure without chain
#: identifiers), the residue index occupies 3..10 and the amino acid 11..14.
#: Whitespace splitting cannot work here because a blank chain collapses into
#: the residue column.
_RESIDUE_CHAIN = slice(2, 3)
_RESIDUE_INDEX = slice(3, 10)
_RESIDUE_NAME = slice(11, 14)


def parse_residues(path: Path) -> list[dict[str, object]]:
    """Parse the per-cluster tunnel-lining residue blocks."""
    residues = []
    cluster: int | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("==") and "Tunnel cluster" in stripped:
            try:
                cluster = int(stripped.rstrip("=").strip().split()[-1])
            except ValueError as exc:
                raise OutputError("residues.txt has a malformed cluster heading") from exc
            continue
        if stripped.startswith("#"):
            continue
        if cluster is None:
            raise OutputError("residues.txt has residue rows before a cluster heading")
        chain = line[_RESIDUE_CHAIN].strip()
        number, icode = _split_residue(line[_RESIDUE_INDEX].strip())
        name = line[_RESIDUE_NAME].strip()
        fields = line[14:].split()
        if len(fields) < 2 or not name:
            raise OutputError("residues.txt contains a malformed residue row")
        residues.append(
            {
                "tunnel_cluster": cluster,
                "chain": chain,
                "residue_number": number,
                "insertion_code": icode,
                "residue_name": name,
                "snapshot_count": int(fields[0]),
                "sidechain_snapshot_count": int(fields[1]),
                "lining_atoms": ";".join(fields[2:]),
            }
        )
    if not residues:
        raise OutputError("residues.txt reports no tunnel-lining residues")
    return residues


def _snapshot_order(label: str) -> tuple[int, int, str]:
    """Order frame labels numerically, so 10 follows 9 rather than 1."""
    match = re.fullmatch(r"\D*(\d+)(.*)", label)
    if match is None:
        return (1, 0, label)
    return (0, int(match.group(1)), match.group(2))


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def normalize(raw_out: Path, output_dir: Path, provenance: dict[str, object]) -> dict[str, object]:
    """Normalize one CAVER output tree into the Task's declared result files."""
    clusters = parse_summary(require_file(raw_out / "summary.txt"))
    tunnels = parse_characteristics(require_file(raw_out / "analysis/tunnel_characteristics.csv"))
    profiles = parse_profiles(require_file(raw_out / "analysis/tunnel_profiles.csv"))
    bottlenecks = parse_bottlenecks(require_file(raw_out / "analysis/bottlenecks.csv"))
    residues = parse_residues(require_file(raw_out / "analysis/residues.txt"))

    cluster_ids = {int(cluster["cluster"]) for cluster in clusters}
    tunnel_keys = [
        (str(tunnel["snapshot"]), int(tunnel["tunnel_cluster"]), int(tunnel["tunnel"])) for tunnel in tunnels
    ]
    tunnel_key_set = set(tunnel_keys)
    repeated_tunnel = next((key for key, count in Counter(tunnel_keys).items() if count > 1), None)
    if repeated_tunnel is not None:
        raise OutputError(f"tunnel_characteristics.csv repeats tunnel {repeated_tunnel}")
    for tunnel in tunnels:
        if int(tunnel["tunnel_cluster"]) not in cluster_ids:
            raise OutputError(f"tunnel_characteristics.csv names unknown cluster {tunnel['tunnel_cluster']}")
    for row in residues:
        if int(row["tunnel_cluster"]) not in cluster_ids:
            raise OutputError(f"residues.txt names unknown tunnel cluster {row['tunnel_cluster']}")
    for name, rows in (("tunnel_profiles.csv", profiles), ("bottlenecks.csv", bottlenecks)):
        for row in rows:
            key = (str(row["snapshot"]), int(row["tunnel_cluster"]), int(row["tunnel"]))
            if key not in tunnel_key_set:
                raise OutputError(f"{name} names a tunnel absent from tunnel_characteristics.csv: {key}")

    # CAVER's summary counts are the record of how many tunnels and snapshots it
    # analyzed. Every authenticated output satisfies these invariants, and a
    # truncated table still parses, so a partial output would otherwise be
    # published as a complete result.
    cluster_tunnel_sum = sum(int(cluster["tunnel_count"]) for cluster in clusters)
    if cluster_tunnel_sum != len(tunnels):
        raise OutputError(
            f"summary.txt reports {cluster_tunnel_sum} tunnels but tunnel_characteristics.csv lists {len(tunnels)}"
        )
    tunnel_counts = Counter(int(tunnel["tunnel_cluster"]) for tunnel in tunnels)
    for cluster in clusters:
        cluster_id = int(cluster["cluster"])
        if int(cluster["tunnel_count"]) != tunnel_counts[cluster_id]:
            raise OutputError(
                f"summary.txt reports {cluster['tunnel_count']} tunnels in cluster {cluster_id} "
                f"but tunnel_characteristics.csv lists {tunnel_counts[cluster_id]}"
            )
        snapshot_count = len({str(t["snapshot"]) for t in tunnels if int(t["tunnel_cluster"]) == cluster_id})
        if int(cluster["snapshot_count"]) != snapshot_count:
            raise OutputError(
                f"summary.txt reports {cluster['snapshot_count']} snapshots in cluster {cluster_id} "
                f"but tunnel_characteristics.csv lists {snapshot_count}"
            )
    bottleneck_counts = Counter(
        (str(row["snapshot"]), int(row["tunnel_cluster"]), int(row["tunnel"])) for row in bottlenecks
    )
    repeated_bottleneck = next((key for key, count in bottleneck_counts.items() if count > 1), None)
    if repeated_bottleneck is not None:
        raise OutputError(f"bottlenecks.csv repeats tunnel {repeated_bottleneck}")
    profile_keys = {(str(row["snapshot"]), int(row["tunnel_cluster"]), int(row["tunnel"])) for row in profiles}
    residue_counts = Counter(int(row["tunnel_cluster"]) for row in residues)
    for key in tunnel_keys:
        if key not in profile_keys:
            raise OutputError(f"tunnel_profiles.csv has no points for tunnel {key}")
        if bottleneck_counts[key] != 1:
            raise OutputError(f"bottlenecks.csv has no bottleneck row for tunnel {key}")
    for cluster_id in tunnel_counts:
        if residue_counts[cluster_id] == 0:
            raise OutputError(f"residues.txt has no residue rows for tunnel cluster {cluster_id}")

    _write_csv(output_dir / "clusters.csv", CLUSTER_FIELDS, clusters)
    _write_csv(output_dir / "tunnels.csv", TUNNEL_FIELDS, tunnels)
    _write_csv(output_dir / "profiles.csv", PROFILE_FIELDS, profiles)
    _write_csv(output_dir / "bottlenecks.csv", BOTTLENECK_FIELDS, bottlenecks)
    _write_csv(output_dir / "residues.csv", RESIDUE_FIELDS, residues)
    shutil.copyfile(require_file(raw_out / "analysis/atoms.txt"), output_dir / "atoms.txt")
    shutil.copyfile(require_file(raw_out / "log.txt"), output_dir / "log.txt")
    warnings = raw_out / "warnings.txt"
    if warnings.is_file():
        shutil.copyfile(warnings, output_dir / "warnings.txt")

    summary = {
        **provenance,
        "cluster_count": len(clusters),
        "tunnel_count": len(tunnels),
        "profile_point_count": len(profiles),
        "bottleneck_row_count": len(bottlenecks),
        # One residue can line several tunnel clusters, so the residue count is
        # the number of distinct residues, not the number of table rows.
        "lining_residue_count": len(
            {(str(residue["chain"]), int(residue["residue_number"]), str(residue["insertion_code"])) for residue in residues}
        ),
        "lining_residue_row_count": len(residues),
        # Bind the provenance record to the exact published tables: the cluster
        # identifiers CAVER assigned, the snapshot labels it reported, and the
        # bytes of the tunnel table. Counts alone cannot identify a result set.
        "cluster_ids": sorted(int(cluster["cluster"]) for cluster in clusters),
        "snapshot_labels": sorted({str(tunnel["snapshot"]) for tunnel in tunnels}, key=_snapshot_order),
        "cluster_table_sha256": hashlib.sha256((output_dir / "clusters.csv").read_bytes()).hexdigest(),
        "tunnel_table_sha256": hashlib.sha256((output_dir / "tunnels.csv").read_bytes()).hexdigest(),
        "units": {
            "bottleneck_radius": "angstrom",
            "length": "angstrom",
            "curvature": "dimensionless",
            "throughput": "dimensionless",
            "cost": "dimensionless",
            "priority": "dimensionless",
            "profile_distance": "angstrom",
            "profile_radius": "angstrom",
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


