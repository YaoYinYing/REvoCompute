# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Server normalization of the CAVER start-point contract.

The owning ``task.yaml`` is the only parameter vocabulary; these cases prove
that the contract accepts the typed selections the picker writes, rejects an
incomplete explicit point, and keeps group mode free of a stale residue number.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from revocompute.schemas import TaskSubmissionRequest
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def caver():
    with isolated_discovery(str(ROOT / "docker" / "runners")):
        yield


def _coerce(caver, params: dict) -> dict:
    submission = TaskSubmissionRequest.model_validate({"task_type": "caver", "params": params})
    return submission.coerce_params()


def test_point_mode_defaults_the_source_and_keeps_typed_coordinates(caver) -> None:
    coerced = _coerce(caver, {"start_point_mode": "point", "start_x": 1.5, "start_y": 2.5, "start_z": 3.5})
    assert coerced["start_point_source"] == "manual"
    assert coerced["start_x"] == 1.5
    assert coerced["start_selected_residues"] == ""


@pytest.mark.parametrize(
    "missing",
    ["start_selected_residues", "start_selected_serials", "start_reference_sha256"],
)
def test_explicit_centroid_requires_its_provenance(caver, missing: str) -> None:
    params = {
        "start_point_mode": "point",
        "start_point_source": "centroid",
        "start_x": 1.0,
        "start_y": 2.0,
        "start_z": 3.0,
        "start_selected_residues": "A:1",
        "start_selected_serials": "1-3",
        "start_reference_sha256": "a" * 64,
    }
    params[missing] = ""
    with pytest.raises(ValidationError, match=missing):
        TaskSubmissionRequest.model_validate({"task_type": "caver", "params": params})


def test_com_conversion_is_accepted_with_the_complete_provenance(caver) -> None:
    coerced = _coerce(
        caver,
        {
            "start_point_mode": "point",
            "start_point_source": "com",
            "start_x": 1.25,
            "start_y": 2.25,
            "start_z": 3.25,
            "start_selected_residues": "A:1,A:2",
            "start_selected_serials": "1-6",
            "start_reference_sha256": "b" * 64,
        },
    )
    assert coerced["start_point_source"] == "com"
    assert coerced["start_selected_residues"] == "A:1,A:2"


def test_com_hydrogen_policy_is_declared_explicitly(caver) -> None:
    base = {
        "start_point_mode": "point",
        "start_point_source": "com",
        "start_x": 1.0,
        "start_y": 2.0,
        "start_z": 3.0,
        "start_selected_residues": "A:1",
        "start_selected_serials": "1-3",
        "start_reference_sha256": "b" * 64,
    }
    assert _coerce(caver, base)["start_com_hydrogen_policy"] == "include"
    assert _coerce(caver, {**base, "start_com_hydrogen_policy": "exclude"})["start_com_hydrogen_policy"] == "exclude"
    with pytest.raises(ValidationError, match="start_com_hydrogen_policy"):
        TaskSubmissionRequest.model_validate(
            {"task_type": "caver", "params": {**base, "start_com_hydrogen_policy": "maybe"}}
        )


def test_group_mode_does_not_require_a_residue_number(caver) -> None:
    coerced = _coerce(caver, {"start_point_mode": "group", "start_group": "A:1-2,B:9"})
    assert coerced["start_group"] == "A:1-2,B:9"
    assert coerced.get("start_residue_number") is None


def test_include_and_exclude_filters_are_both_accepted(caver) -> None:
    coerced = _coerce(
        caver,
        {
            "start_point_mode": "residue",
            "start_chain": "A",
            "start_residue_number": 7,
            "include_residue_names": "ALA GLY",
            "include_atom_numbers": "1-20",
            "exclude_residue_names": "HOH",
        },
    )
    assert coerced["include_residue_names"] == "ALA GLY"
    assert coerced["exclude_residue_names"] == "HOH"


def test_an_invalid_include_token_is_rejected(caver) -> None:
    with pytest.raises(ValidationError, match="include_residue_ids"):
        TaskSubmissionRequest.model_validate(
            {
                "task_type": "caver",
                "params": {
                    "start_point_mode": "point",
                    "start_x": 1,
                    "start_y": 2,
                    "start_z": 3,
                    "include_residue_ids": "A:1; rm -rf /",
                },
            }
        )


def test_seed_is_a_deterministic_32_bit_integer(caver) -> None:
    first = _coerce(caver, {"start_point_mode": "point", "start_x": 1, "start_y": 2, "start_z": 3})
    second = _coerce(caver, {"start_point_mode": "point", "start_x": 1, "start_y": 2, "start_z": 3})
    assert first["seed"] == second["seed"] == 1
    with pytest.raises(ValidationError, match="seed"):
        TaskSubmissionRequest.model_validate(
            {
                "task_type": "caver",
                "params": {"start_point_mode": "point", "start_x": 1, "start_y": 2, "start_z": 3, "seed": 2**31},
            }
        )
