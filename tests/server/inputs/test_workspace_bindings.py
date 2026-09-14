# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import pytest

from revocompute.task_types import TaskInputRole, _load_input_workspace


def _workspace(role: str | None) -> dict:
    options = {} if role is None else {"role": role}
    return {
        "steps": [
            {
                "id": "material",
                "title": "Material",
                "capabilities": [
                    {"plugin": "sequence", "id": "sequence_editor", "options": options},
                    {"plugin": "review", "id": "review"},
                ],
            }
        ]
    }


def test_sequence_capability_requires_a_compatible_named_role():
    roles = (TaskInputRole("sequence", "Sequence", "protein_sequence", ("fasta",), 1, 1),)

    workspace = _load_input_workspace(_workspace("sequence"), input_roles=roles)
    assert workspace[0].capabilities[0].options == {"role": "sequence"}

    with pytest.raises(ValueError, match="must bind to an input role"):
        _load_input_workspace(_workspace(None), input_roles=roles)
    with pytest.raises(ValueError, match="references unknown role"):
        _load_input_workspace(_workspace("first_input"), input_roles=roles)
