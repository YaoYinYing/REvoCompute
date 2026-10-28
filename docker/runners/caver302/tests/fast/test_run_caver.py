# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""End-to-end orchestration of the CAVER Runner with a contract stand-in.

The pinned CAVER JAR is never executed in this lane. The stand-in implements the
CLI contract the pinned distribution documents (``-Xmx`` plus ``-home``, ``-pdb``,
``-conf`` and ``-out`` are mandatory) and publishes the authentic guided-example
output files copied from the distribution. That exercises the real path — start
point resolution, frame staging, config rendering, argv construction, provenance
and normalization — while the actual JAR runs only in the target-host window.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
FAMILY = ROOT / "docker/runners/caver302"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
RAW_FILES = {
    "summary.txt": FIXTURES / "caver/summary.txt",
    "analysis/tunnel_characteristics.csv": FIXTURES / "caver/tunnel_characteristics.csv",
    "analysis/tunnel_profiles.csv": FIXTURES / "caver/tunnel_profiles.csv",
    "analysis/bottlenecks.csv": FIXTURES / "caver/bottlenecks.csv",
    "analysis/residues.txt": FIXTURES / "caver/residues.txt",
    "analysis/atoms.txt": FIXTURES / "caver/atoms.txt",
    "log.txt": FIXTURES / "caver/log.txt",
}
MANIFEST_PARAMS = {
    "start_point_mode": "ligand",
    "start_residue_name": "HEM",
    "start_chain": "A",
    "start_residue_number": 500,
}

sys.path.insert(0, str(Path(__file__).resolve().parent))
from caver_params import BASE_PARAMS  # noqa: E402


def fake_distribution(tmp_path: Path) -> Path:
    home = tmp_path / "dist" / "caver"
    (home / "lib").mkdir(parents=True)
    (home / "bin").mkdir()
    (home / "caver.jar").write_bytes(b"caver-jar")
    (home / "lib" / "kd.jar").write_bytes(b"kd")
    (home / "bin" / "atom_radii.csv").write_bytes(b"C 1.7\n")
    return home


def raw_output_tree(tmp_path: Path) -> Path:
    raw = tmp_path / "stub-output"
    for relative, source in RAW_FILES.items():
        target = raw / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    return raw


def stub_java(tmp_path: Path, *, exit_code: int = 0, publish: bool = True) -> Path:
    script = tmp_path / "java"
    script.write_text(
        "\n".join(
            (
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "home= pdb= conf= out= heap=",
                'while [[ $# -gt 0 ]]; do case "$1" in',
                '  -Xmx*) heap=$1;;',
                '  -home) home=$2; shift;;',
                '  -pdb) pdb=$2; shift;;',
                '  -conf) conf=$2; shift;;',
                '  -out) out=$2; shift;;',
                "esac; shift; done",
                '[[ -n "$heap" && -n "$home" && -n "$pdb" && -n "$conf" && -n "$out" ]] || exit 2',
                f"exit_code={exit_code}",
                '[[ "$exit_code" -eq 0 ]] || exit "$exit_code"',
                '[[ -d "$pdb" && -f "$conf" ]] || exit 4',
            )
            + (
                ('mkdir -p "$out"', 'cp -r "$CAVER_STUB_OUTPUT"/. "$out"/')
                if publish
                else ()
            )
            + ("",)
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def task_manifest(tmp_path: Path, snapshot: Path | None = None) -> Path:
    inputs = {"structure": [{"path": str(ROOT / "tests/data/pdb/1SUO.pdb")}]}
    if snapshot is not None:
        inputs["snapshots"] = [{"path": str(snapshot)}]
    manifest = {
        "task_type": "caver",
        "params": {**BASE_PARAMS, **MANIFEST_PARAMS},
        "inputs": inputs,
    }
    path = tmp_path / "task.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def invoke(tmp_path: Path, manifest: Path, java: Path, home: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(FAMILY / "run_caver.py"),
            "--task",
            str(manifest),
            "--output-dir",
            str(output),
            "--distribution",
            str(home),
            "--java",
            str(java),
            "--upstream",
            str(FAMILY / "upstream.json"),
        ],
        capture_output=True,
        text=True,
    )


def test_orchestrates_selection_config_execution_and_normalization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAVER_STUB_OUTPUT", str(raw_output_tree(tmp_path)))
    snapshot = tmp_path / "second_frame.pdb"
    shutil.copyfile(ROOT / "tests/data/pdb/1SUO.pdb", snapshot)
    output = tmp_path / "published"

    completed = invoke(tmp_path, task_manifest(tmp_path, snapshot), stub_java(tmp_path), fake_distribution(tmp_path), output)
    assert completed.returncode == 0, completed.stderr
    assert "REVODESIGN_STAGE:compute_tunnels" in completed.stdout

    config = (output / "caver_config.txt").read_text(encoding="utf-8")
    assert "starting_point_residue A:500" in config
    assert "probe_radius 0.9" in config
    assert (output / "work/pdbs/frame_0001.pdb").is_file()
    assert (output / "work/pdbs/frame_0002.pdb").is_file()

    provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["start_point"]["mode"] == "ligand"
    assert provenance["start_point"]["chain"] == "A"
    assert provenance["start_point"]["residue_number"] == 500
    # Centroid of the 43 HEM atoms in 1SUO, computed independently from the structure.
    assert provenance["start_point"]["point_angstrom"] == pytest.approx([-22.31088, 90.26135, 8.80723], abs=1e-4)
    assert [frame["frame"] for frame in provenance["frames"]] == ["frame_0001.pdb", "frame_0002.pdb"]
    assert [frame["source_name"] for frame in provenance["frames"]] == ["1SUO.pdb", "second_frame.pdb"]
    assert provenance["distribution"]["jar_sha256"] == hashlib.sha256(b"caver-jar").hexdigest()
    assert provenance["runtime_network"] is False
    assert provenance["upstream"]["release"] == "3.0.2"

    for artifact in ("tunnels.csv", "clusters.csv", "bottlenecks.csv", "profiles.csv", "residues.csv", "summary.json"):
        assert (output / artifact).stat().st_size > 0


def test_nonzero_tool_exit_is_a_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAVER_STUB_OUTPUT", str(raw_output_tree(tmp_path)))
    completed = invoke(
        tmp_path,
        task_manifest(tmp_path),
        stub_java(tmp_path, exit_code=3),
        fake_distribution(tmp_path),
        tmp_path / "published",
    )
    assert completed.returncode != 0
    assert "exited with status 3" in completed.stderr


def test_incomplete_output_is_a_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAVER_STUB_OUTPUT", str(raw_output_tree(tmp_path)))
    completed = invoke(
        tmp_path,
        task_manifest(tmp_path),
        stub_java(tmp_path, publish=False),
        fake_distribution(tmp_path),
        tmp_path / "published",
    )
    assert completed.returncode != 0
    assert "did not produce summary.txt" in completed.stderr
