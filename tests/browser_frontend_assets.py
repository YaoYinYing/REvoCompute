# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Build browser-only frontend entry points used by Playwright behavior tests."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
_BUILD = tempfile.TemporaryDirectory(prefix="revocompute-frontend-browser-")
_ASSETS: tuple[Path, Path] | None = None
_RESULT_DIST: Path | None = None


def scientific_assets() -> tuple[Path, Path]:
    global _ASSETS
    if _ASSETS is not None:
        return _ASSETS
    output = Path(_BUILD.name) / "scientific"
    environment = {**os.environ, "REVOCOMPUTE_SCIENTIFIC_TEST_DIST": str(output)}
    completed = subprocess.run(
        ["npm", "exec", "vite", "--", "build", "--config", "tests/scientific.vite.config.ts"],
        cwd=ROOT / "frontend",
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode:
        raise RuntimeError(f"Scientific browser build failed:\n{completed.stdout}\n{completed.stderr}")
    _ASSETS = output / "scientific.js", output / "scientific.css"
    if not all(path.is_file() for path in _ASSETS):
        raise RuntimeError(f"Scientific browser build did not produce {_ASSETS}")
    return _ASSETS


def install_scientific_assets(page) -> None:
    script, stylesheet = scientific_assets()
    page.add_style_tag(path=stylesheet)
    page.add_script_tag(path=script)


def result_dist() -> Path:
    global _RESULT_DIST
    if _RESULT_DIST is not None:
        return _RESULT_DIST
    output = Path(_BUILD.name) / "result"
    environment = {**os.environ, "REVOCOMPUTE_RESULT_TEST_DIST": str(output)}
    completed = subprocess.run(
        ["npm", "exec", "vite", "--", "build", "--config", "tests/result-browser.vite.config.ts"],
        cwd=ROOT / "frontend", env=environment, capture_output=True, text=True, timeout=120,
    )
    if completed.returncode:
        raise RuntimeError(f"Result browser build failed:\n{completed.stdout}\n{completed.stderr}")
    _RESULT_DIST = output
    return output
