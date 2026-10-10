# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Required Runner acceptance cannot succeed through dependency-driven skips."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("body,expected", [
    ("assert 1 + 1 == 2", 0),
    ("pytest.importorskip('missing_scientific_dependency_for_boundary_test')", 1),
])
def test_required_runner_lane_rejects_skips(tmp_path: Path, body: str, expected: int) -> None:
    (tmp_path / "test_contract.py").write_text("import pytest\ndef test_contract():\n    " + body + "\n")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_contract.py", "--noconftest", "-q",
         "-p", "no:cacheprovider", "-p", "docker.runner_testkit.pytest_plugin"],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    if expected:
        assert "Required Runner tests may not be reported as skips" in result.stdout
