# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Stand-in for the pinned ``esm.models.esmfold2.config`` module."""

from __future__ import annotations


class EsmFold2Config:
    def __init__(self) -> None:
        self.esmc_id = ""

    @classmethod
    def from_pretrained(cls, local_dir, **overrides):
        del overrides
        return cls()


def default_module_flags(local_dir):
    del local_dir
    return {}
