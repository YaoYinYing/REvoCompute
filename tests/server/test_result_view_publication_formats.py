# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Publication-time checks that a trajectory's formats match its artifacts."""

from __future__ import annotations

from types import SimpleNamespace

from revocompute.task_runtime import _validate_scientific_view


def _definition(**mapping: object) -> SimpleNamespace:
    return SimpleNamespace(
        plugin="trajectory",
        title="Ensemble",
        mapping={"association": "single", "coordinate_format": "xtc", **mapping},
    )


def _problems(definition: SimpleNamespace, topology: str, coordinates: str) -> list[str]:
    return _validate_scientific_view(
        definition,
        {"topology": [topology], "coordinates": [coordinates]},
        "unused",
    )


def test_a_declared_topology_format_must_match_the_published_topology() -> None:
    definition = _definition(topology_format="mmcif")
    assert any("topology format" in problem for problem in _problems(definition, "topology.pdb", "samples.xtc"))
    assert _problems(definition, "topology.cif", "samples.xtc") == []


def test_an_absent_topology_format_is_checked_as_pdb() -> None:
    definition = _definition()
    assert any("topology format" in problem for problem in _problems(definition, "topology.cif", "samples.xtc"))
    assert _problems(definition, "topology.pdb", "samples.xtc") == []


def test_a_gzipped_text_topology_keeps_its_underlying_format() -> None:
    definition = _definition(topology_format="mmcif")
    assert _problems(definition, "topology.cif.gz", "samples.xtc") == []


def test_a_gzipped_binary_coordinate_is_rejected_because_the_viewer_does_not_inflate_it() -> None:
    definition = _definition(topology_format="mmcif")
    assert any("coordinate format" in problem for problem in _problems(definition, "topology.cif", "samples.xtc.gz"))


def test_a_gzipped_multi_model_pdb_coordinate_keeps_its_underlying_format() -> None:
    definition = _definition(coordinate_format="pdb")
    assert _problems(definition, "topology.pdb", "frames.pdb.gz") == []
