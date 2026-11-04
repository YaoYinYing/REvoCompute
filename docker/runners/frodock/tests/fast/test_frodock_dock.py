# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / "docker/runners/frodock"

_GRID = """#!/usr/bin/env bash
set -eu
out=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o) out=$2; shift 2 ;;
        *) shift ;;
    esac
done
printf 'map\\n' > "$out"
"""

_SEARCH = """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> dock_calls.txt
printf 'solutions\\n' > solutions.dat
"""

_CLUSTER = """#!/usr/bin/env bash
set -eu
nc=10
while [[ $# -gt 0 ]]; do
    case "$1" in
        --nc) nc=$2; shift 2 ;;
        *) shift ;;
    esac
done
python3 - "$nc" <<'PY'
import struct
import sys

count = int(sys.argv[1])
payload = struct.pack("<i", count) + struct.pack("<3f", 0.0, 0.0, 0.0)
for index in range(1, count + 1):
    payload += struct.pack("<7f", float(index), float(index), float(index), 1.5, -2.5, 3.5, 1000.0 - index)
open("clustered_solutions.dat", "wb").write(payload)
PY
"""

_VIEW = """#!/usr/bin/env bash
set -eu
range="1-1"
while [[ $# -gt 0 ]]; do
    case "$1" in
        -r) range=$2; shift 2 ;;
        *) shift ;;
    esac
done
count=${range#1-}
for ((index = 1; index <= count; index++)); do
    printf 'ATOM      1  CA  ALA A   1       0.0   0.0   0.0\\nEND\\n' > "ligand_$index.pdb"
done
"""


def _install_fakes(tmp_path: Path) -> Path:
    install = tmp_path / "install"
    binaries = install / "bin"
    binaries.mkdir(parents=True)
    for name, body in (
        ("frodockgrid_gcc", _GRID),
        ("frodock_gcc", _SEARCH),
        ("frodockcluster_gcc", _CLUSTER),
        ("frodockview_gcc", _VIEW),
    ):
        path = binaries / name
        path.write_text(body, encoding="ascii")
        path.chmod(0o755)
    (binaries / "soap.bin").write_bytes(b"soap")
    return install


def _run(tmp_path: Path, params: dict[str, object], pose_count: int = 2) -> subprocess.CompletedProcess[str]:
    install = _install_fakes(tmp_path)
    receptor = tmp_path / "receptor.pdb"
    ligand = tmp_path / "ligand.pdb"
    receptor.write_text("ATOM      1  CA  ALA A   1       0.0   0.0   0.0\nEND\n", encoding="ascii")
    ligand.write_text("ATOM      1  CA  ALA A   1       0.0   0.0   0.0\nEND\n", encoding="ascii")
    manifest = tmp_path / "task.json"
    manifest.write_text(json.dumps({"params": {"pose_count": pose_count, **params}}), encoding="utf-8")
    (tmp_path / "out").mkdir()
    return subprocess.run(
        [
            sys.executable, str(FAMILY / "dock.py"),
            "--receptor", str(receptor),
            "--ligand", str(ligand),
            "--workspace", str(tmp_path / "work"),
            "--output-dir", str(tmp_path / "out"),
            "--ligand-name", "lig",
            "--install-dir", str(install),
            "--manifest", str(manifest),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _search_arguments(tmp_path: Path) -> list[str]:
    return (tmp_path / "work" / "dock_calls.txt").read_text(encoding="utf-8").split()


def test_default_bandwidth_is_forwarded_to_the_search(tmp_path: Path) -> None:
    completed = _run(tmp_path, {})

    assert completed.returncode == 0, completed.stderr
    arguments = _search_arguments(tmp_path)
    assert arguments[arguments.index("--bw") + 1] == "32"
    provenance = json.loads((tmp_path / "out" / "frodock-run.json").read_text(encoding="utf-8"))
    assert provenance["parameters"]["bandwidth"] == 32


def test_explicit_bandwidth_is_forwarded_to_the_search(tmp_path: Path) -> None:
    completed = _run(tmp_path, {"bandwidth": 64})

    assert completed.returncode == 0, completed.stderr
    arguments = _search_arguments(tmp_path)
    assert arguments[arguments.index("--bw") + 1] == "64"
    provenance = json.loads((tmp_path / "out" / "frodock-run.json").read_text(encoding="utf-8"))
    assert provenance["parameters"]["bandwidth"] == 64


@pytest.mark.parametrize("bandwidth", [3, 129, 32.0, "32", True, None])
def test_invalid_bandwidth_is_rejected_before_any_binary_runs(tmp_path: Path, bandwidth: object) -> None:
    completed = _run(tmp_path, {"bandwidth": bandwidth})

    assert completed.returncode != 0
    assert "bandwidth must be an integer between 4 and 128" in completed.stderr
    assert not (tmp_path / "work" / "dock_calls.txt").exists()
