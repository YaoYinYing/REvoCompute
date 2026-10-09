# Copyright (c) 2026 The REvoDesign Developers.
# SPDX-License-Identifier: GPL-3.0-only
"""Standalone Runner test support, outside the production plugin discovery root."""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def pytest_configure(config):
    for path in (ROOT, Path(__file__).resolve().parent, *sorted((ROOT / "docker/runners").glob("*/tests/fast"))):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    os.environ.setdefault("SERVER_DIR", str(ROOT))
    os.environ.setdefault("RUNNER_UID", "1000")
    os.environ.setdefault("RUNNER_GID", "1000")
