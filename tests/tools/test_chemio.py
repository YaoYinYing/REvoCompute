# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "docker" / "tools" / "chemio" / "python" / "tool_cli.py"
    spec = importlib.util.spec_from_file_location("chemio_tool_cli", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_neutral_sdf_to_mol2_conversion_preserves_structure(tmp_path):
    module = _module()
    source = Path(__file__).resolve().parents[1] / "data" / "docking" / "ethanol.sdf"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "tool": "ligand_convert",
                "parameters": {"output_format": "mol2"},
                "inputs": {"ligand": [{"path": str(source), "format": "sdf"}]},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    output.mkdir()

    response = module.ligand_convert(request, output)
    converted, failures = module._read_molecules(output / "ligand.mol2", "mol2")

    assert failures == []
    assert len(converted) == 1
    metadata = module._molecule_metadata(converted[0])
    assert metadata["atom_count"] == 9
    assert metadata["formal_charge"] == 0
    assert metadata["partial_charge_present"] is False
    assert metadata["has_3d_coordinates"] is True
    assert response["backend"]["mode"] == "representation_only"


def test_conversion_rejects_missing_3d_coordinates(tmp_path):
    module = _module()
    source = tmp_path / "flat.sdf"
    source.write_text(
        "flat\n  fixture\n\n  1  0  0  0  0  0  0  0  0  0999 V2000\n"
        "    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\nM  END\n$$$$\n",
        encoding="utf-8",
    )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "tool": "ligand_convert",
                "parameters": {"output_format": "mol2"},
                "inputs": {"ligand": [{"path": str(source), "format": "sdf"}]},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    output.mkdir()

    try:
        module.ligand_convert(request, output)
    except module.ToolInputError as exc:
        assert "3D coordinates" in str(exc)
    else:
        raise AssertionError("2D ligand conversion was accepted")
