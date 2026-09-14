# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

from revocompute.doctor import diagnose_tools


ROOT = Path(__file__).resolve().parents[3]


def test_tool_doctor_validates_production_contracts_and_images(tmp_path):
    (tmp_path / "bioio.sif").touch()
    (tmp_path / "chemio.sif").touch()

    report = diagnose_tools(
        ROOT / "docker" / "tools",
        enabled={"bioio", "chemio"},
        image_root=tmp_path,
    )

    assert report.ok
    assert "Tool family bioio" in report.checked
    assert "Tool family chemio" in report.checked


def test_tool_doctor_reports_missing_candidate_image(tmp_path):
    report = diagnose_tools(ROOT / "docker" / "tools", enabled={"bioio"}, image_root=tmp_path)

    assert not report.ok
    assert report.diagnostics[0].code == "E5002"
