# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

def normalize(value):
    return {"params": {}, "state": value, "summary": "Synthetic workspace"}

def validate(value, paths):
    return None


def normalize_capability(value):
    return {"params": {}, "state": value, "summary": "Alternate synthetic workspace"}
