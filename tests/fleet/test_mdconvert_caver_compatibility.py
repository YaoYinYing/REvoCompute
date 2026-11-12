# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Replay converted snapshots through the CAVER Runner's own PDB contract."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("MDAnalysis", reason="mdconvert Tool CLI dependencies live in its SIF runtime")

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "data" / "mdconvert"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_converted_snapshots_replay_through_the_caver_snapshot_contract(tmp_path):
    tool = _load(
        "mdconvert_tool_cli",
        REPO_ROOT / "docker" / "tools" / "mdconvert" / "python" / "tool_cli.py",
    )
    selection = _load(
        "caver_pdb_selection",
        next(iter(sorted((REPO_ROOT / "docker" / "runners").glob("*/pdb_selection.py")))),
    )

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in ("tiny.gro", "tiny.xtc"):
        (inputs / name).write_bytes((FIXTURES / name).read_bytes())
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "tool": "md_trajectory_convert",
                "parameters": {"output_adapter": "caver_pdb_snapshots", "start": 0, "stop": 3, "stride": 1},
                "inputs": {
                    "topology": [{"path": str(inputs / "tiny.gro"), "format": "gro"}],
                    "trajectory": [{"path": str(inputs / "tiny.xtc"), "format": "xtc"}],
                },
                "limits": {
                    "request_bytes": 108_000_000,
                    "input_bytes": {"topology": 8_000_000, "trajectory": 100_000_000},
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    output.mkdir()

    response = tool.md_trajectory_convert(request, output)

    reference = selection.parse_pdb(output / "reference.pdb")
    assert [(atom.name, atom.resname, atom.resseq) for atom in reference] == [
        ("N", "ALA", 1),
        ("CA", "ALA", 1),
        ("C", "GLY", 2),
        ("O", "GLY", 2),
    ]
    for declaration in response["outputs"]["snapshots"]:
        name = declaration["path"]
        selection.assert_snapshot_matches(reference, selection.parse_pdb(output / name), name)
