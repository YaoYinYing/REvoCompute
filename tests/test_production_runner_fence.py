# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Behavioral contract for the generic Server test fence around the Runner tree.

``tests/conftest.py`` installs an autouse fence: a generic Server test must fail
when it reads or lists the installed Runner tree under ``docker/runners``, while
every unrelated path stays untouched. These counterexamples plant those accesses
from inside an ordinary test and assert the fence raises, so dropping a guarded
syscall entry point or widening the ``tests/fleet`` opt-out fails a real test
instead of shipping silently.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "docker" / "runners"
DENIED = "production Runner root"


def test_fence_denies_every_read_and_list_entry_point():
    marker = PRODUCTION / "README.md"
    accesses = {
        "builtins.open": lambda: open(marker).close(),
        "io.open": lambda: io.open(str(marker)).close(),
        "Path.open": lambda: marker.open().close(),
        "Path.read_text": lambda: marker.read_text(),
        "os.open": lambda: os.close(os.open(marker, os.O_RDONLY)),
        "os.listdir": lambda: os.listdir(PRODUCTION),
        "os.scandir": lambda: list(os.scandir(PRODUCTION)),
        "Path.iterdir": lambda: list(PRODUCTION.iterdir()),
        "os.walk": lambda: list(os.walk(PRODUCTION)),
    }
    for name, access in accesses.items():
        with pytest.raises(AssertionError, match=DENIED):
            access()
            pytest.fail(f"{name} reached the production Runner tree")  # pragma: no cover


def test_fence_leaves_unrelated_paths_untouched(tmp_path):
    assert (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    scratch = tmp_path / "scratch.txt"
    scratch.write_text("untouched", encoding="utf-8")
    assert scratch.read_text(encoding="utf-8") == "untouched"
    with io.open(scratch, encoding="utf-8") as handle:
        assert handle.read() == "untouched"
    assert "fixtures" in os.listdir(ROOT / "tests")
    assert list(os.walk(ROOT / "tests" / "fixtures"))
    assert list((ROOT / "tests").iterdir())
