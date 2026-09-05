# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

import pytest
from revocompute.plugins import PluginManager
from revocompute.workspace_contracts import (
    WorkspaceValidationError,
    normalize_capability,
    validate_capability,
)


def _rfdiffusion_backend():
    root = Path(__file__).resolve().parents[1] / "docker" / "runners"
    manager = PluginManager()
    manager.discover(root, enabled={"placer-rfdiffusion"})
    backend = manager.workspace_backend("rfdiffusion-regions", owner="placer-rfdiffusion")
    assert backend is not None
    return backend


def test_binder_normalization_is_canonical():
    normalizer, _validator = _rfdiffusion_backend()
    result = normalize_capability(
        normalizer,
        {
            "mode": "binder",
            "segments": [
                {"kind": "fixed", "chain": "A", "start": 1, "end": 50},
                {"kind": "chain_break"},
                {"kind": "generated", "min_length": 70, "max_length": 100},
            ],
            "hotspots": [{"chain": "A", "residue": 10}],
        }
    )
    assert result["params"] == {
        "design_mode": "binder",
        "contig": "A1-50/0 70-100",
        "hotspot_res": "[A10]",
    }


def test_fixed_segment_range_is_bounded():
    normalizer, _validator = _rfdiffusion_backend()
    with pytest.raises(WorkspaceValidationError, match="10000"):
        normalize_capability(normalizer,
            {
                "mode": "motif_scaffolding",
                "segments": [{"kind": "fixed", "chain": "A", "start": 1, "end": 20000}],
                "hotspots": [],
            }
        )


def test_numeric_chain_is_rejected():
    normalizer, _validator = _rfdiffusion_backend()
    with pytest.raises(WorkspaceValidationError, match="chain"):
        normalize_capability(normalizer,
            {
                "mode": "motif_scaffolding",
                "segments": [{"kind": "fixed", "chain": "1", "start": 2, "end": 20}],
                "hotspots": [],
            }
        )


def test_unconditional_rejects_hotspots():
    normalizer, _validator = _rfdiffusion_backend()
    with pytest.raises(WorkspaceValidationError, match="Hotspots"):
        normalize_capability(normalizer,
            {
                "mode": "unconditional",
                "segments": [{"kind": "generated", "min_length": 40, "max_length": 40}],
                "hotspots": [{"chain": "A", "residue": 10}],
            }
        )


def test_binder_requires_hotspots():
    normalizer, _validator = _rfdiffusion_backend()
    with pytest.raises(WorkspaceValidationError, match="hotspots"):
        normalize_capability(normalizer,
            {
                "mode": "binder",
                "segments": [
                    {"kind": "fixed", "chain": "A", "start": 1, "end": 10},
                    {"kind": "chain_break"},
                    {"kind": "generated", "min_length": 20, "max_length": 30},
                ],
                "hotspots": [],
            }
        )


def test_structure_cross_validation_rejects_absent_residue(tmp_path):
    normalizer, validator = _rfdiffusion_backend()
    assert validator is not None
    path = tmp_path / "input.pdb"
    path.write_text(
        "ATOM      1  CA  GLY A   1      10.000  10.000  10.000  1.00 20.00           C\nEND\n",
        encoding="utf-8",
    )
    normalized = normalize_capability(normalizer,
        {
            "mode": "motif_scaffolding",
            "segments": [{"kind": "fixed", "chain": "A", "start": 2, "end": 2}],
            "hotspots": [],
        }
    )
    with pytest.raises(WorkspaceValidationError, match="A2"):
        validate_capability(validator, normalized, str(path))
