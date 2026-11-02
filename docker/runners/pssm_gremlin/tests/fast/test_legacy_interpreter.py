# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""The GREMLIN environment is pinned to Python 3.6, so its scripts must stay 3.6-compatible."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

FAMILY = Path(__file__).resolve().parents[2]
LEGACY_SCRIPTS = (
    "scripts/GREMLIN_TFv1.py",
    "scripts/fasta_lower_char_rm.py",
    "scripts/gremlin_labels.py",
    "scripts/make_paired_MSA_simple.py",
)
# Every ``__future__`` feature importable by Python 3.6. ``annotations`` is the
# first one 3.6 lacks, and ``ast.parse`` accepts its grammar, so the grammar
# check alone cannot protect the legacy interpreter.
PYTHON_36_FUTURES = frozenset({
    "nested_scopes",
    "generators",
    "division",
    "absolute_import",
    "with_statement",
    "print_function",
    "unicode_literals",
    "barry_as_FLUFL",
    "generator_stop",
})


@pytest.mark.parametrize("relative", LEGACY_SCRIPTS)
def test_scripts_run_by_the_gremlin_environment_parse_as_python_36(relative: str) -> None:
    tree = ast.parse((FAMILY / relative).read_text(encoding="utf-8"), filename=relative, feature_version=(3, 6))
    future_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        for alias in node.names
    }
    assert future_imports <= PYTHON_36_FUTURES, (
        f"{relative} imports __future__ features unavailable in Python 3.6: {future_imports - PYTHON_36_FUTURES}"
    )
