# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Shared helpers for the fpocket tests.

The bounded raw fixture lives in ``docker/runners/fpocket/tests/fast/fixtures/1SUO_out``: the global
descriptor source (``1SUO_info.txt``, with all reported pockets) plus the
per-pocket geometry/contact files for two selected pockets only.  The production
normalizer expects a self-consistent tree, so the tests build a small tree from
those files rather than checking a second copy of the descriptor file into the
repository.

This is a plain module, not a ``conftest.py``: a conftest inside
``docker/runners/fpocket/tests/fast`` would shadow the repository-root conftest that
``tests/server/*`` imports by name.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
RETAINED_RUN = FIXTURES / "1SUO_out"


def first_pocket_blocks(info_text: str, count: int) -> str:
    """Return the info file truncated to its first ``count`` pocket blocks."""
    kept: list[str] = []
    seen = 0
    for line in info_text.splitlines():
        if line.startswith("Pocket "):
            seen += 1
            if seen > count:
                break
        kept.append(line)
    return "\n".join(kept) + "\n"


def build_subset_run(tmp_path: Path, count: int = 2) -> Path:
    """Build a complete fpocket run tree for the retained pockets under ``tmp_path``.

    Contains the retained ``1SUO_info.txt`` truncated to its first ``count`` pocket
    blocks and the retained ``pocket1``/``pocket2`` geometry and contact files, so
    the production normalizer runs end to end on real fpocket output.
    """
    run_dir = tmp_path / "work" / "1SUO_out"
    pockets = run_dir / "pockets"
    pockets.mkdir(parents=True)
    info = (RETAINED_RUN / "1SUO_info.txt").read_text(encoding="utf-8")
    (run_dir / "1SUO_info.txt").write_text(first_pocket_blocks(info, count), encoding="utf-8")
    for name in ("pocket1_vert.pqr", "pocket1_atm.pdb", "pocket2_vert.pqr", "pocket2_atm.pdb"):
        shutil.copy(RETAINED_RUN / "pockets" / name, pockets / name)
    return tmp_path


@pytest.fixture()
def subset_run_dir(tmp_path: Path) -> Path:
    return build_subset_run(tmp_path)
