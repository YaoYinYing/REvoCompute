# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import pytest

from revocompute.job import ExecutionPlan


def test_execution_plan_accepts_generic_container_contract():
    plan = ExecutionPlan(
        image="registry.example/runner:1",
        command=("/opt/runner",),
        arguments=("--input", "inputs/input.json"),
        environment={"OMP_NUM_THREADS": "2"},
        mounts=({"source": "inputs", "target": "/workspace/inputs", "mode": "ro"},),
        outputs=("outputs/result.json",),
        workspace_paths=("inputs/input.json", "outputs/result.json"),
    )

    assert plan.image == "registry.example/runner:1"
    assert plan.command + plan.arguments == ("/opt/runner", "--input", "inputs/input.json")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"image": "", "command": ("run",)},
        {"image": "runner", "command": ()},
        {"image": "runner", "command": ("run",), "environment": {"": "bad"}},
        {"image": "runner", "command": ("run",), "mounts": ({"source": "x", "target": "/x", "mode": "rx"},)},
    ],
)
def test_execution_plan_rejects_invalid_contract(kwargs):
    with pytest.raises(ValueError):
        ExecutionPlan(**kwargs)


@pytest.mark.parametrize("path", ["../secret.txt", "/etc/passwd", "", "a/../b"])
def test_execution_plan_rejects_unsafe_workspace_paths(path):
    with pytest.raises(ValueError):
        ExecutionPlan(image="runner", command=("run",), outputs=(path,))
