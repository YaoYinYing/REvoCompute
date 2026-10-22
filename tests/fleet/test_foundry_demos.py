# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

from revocompute.task_demos import load_task_demos
from revocompute.task_types import isolated_discovery


ROOT = Path(__file__).resolve().parents[2]


def test_foundry_demos_load_through_the_production_task_contract() -> None:
    expected = {
        "foundry_rfd3_design": ("unconditional_16mer", {"specification"}),
        "foundry_rfd3na_design": ("unconditional_rna_16mer", {"specification"}),
        "foundry_rf3_fold": ("protein_monomer_16mer", {"specification"}),
    }
    with isolated_discovery(str(ROOT / "docker" / "runners"), enabled={"foundry"}) as manager:
        for task_id, (demo_id, roles) in expected.items():
            task = manager.contributions.resolve("tasks", task_id)
            demos = load_task_demos(task)
            assert [demo.id for demo in demos] == [demo_id]
            assert {item.role for item in demos[0].files} == roles
            assert demos[0].parameters == {
                name: definition["default"] for name, definition in task.schema["properties"].items()
            }
