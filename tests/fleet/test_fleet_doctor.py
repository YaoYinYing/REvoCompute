# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations
import json
from pathlib import Path
import yaml
from revocompute.doctor import diagnose, main
ROOT = Path(__file__).resolve().parents[2]


def test_doctor_task_scope_validates_all_mpnn_family_smoke_cases():
    root = Path(__file__).resolve().parents[2] / "docker" / "runners"

    for task in ("proteinmpnn", "ligandmpnn"):
        report = diagnose(root, runner="mpnn", task=task)
        assert report.ok, [(item.code, item.message) for item in report.diagnostics]
