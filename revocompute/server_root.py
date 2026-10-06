# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Server-root locator shared by the control plane and the deployment CLI."""

from __future__ import annotations

from pathlib import Path

#: The server checkout root (``revocompute/`` is directly under it).  The
#: deployment control package and the shared control core both resolve Runner
#: build definitions and fixtures relative to this directory.
SERVER_ROOT = Path(__file__).resolve().parents[1]

__all__ = ["SERVER_ROOT"]
