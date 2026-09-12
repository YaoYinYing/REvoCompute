# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_resolver():
    spec = importlib.util.spec_from_file_location("resolve_citations", ROOT / "tools/resolve_citations.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolver_accepts_metadata_punctuation_and_case_drift(monkeypatch):
    resolver = _load_resolver()
    fetched = "@article{Wohlwend_2024, title={boltz-1 democratizing biomolecular interaction modeling}}"
    monkeypatch.setattr(resolver, "fetch_bibtex", lambda _doi: fetched)

    resolved = resolver.resolve_entries(
        [
            {
                "doi": "10.1101/2024.11.19.624167",
                "title": "Boltz-1: Democratizing Biomolecular Interaction Modeling",
            }
        ],
        None,
    )

    assert resolved == fetched


@pytest.mark.parametrize(
    ("declared", "fetched_title"),
    [
        (
            "Flexible Protein-Protein Docking with a Multi-Track Iterative Transformer",
            "flexible protein–protein docking with a multitrack iterative transformer",
        ),
        (
            "P(all-atom) Is Unlocking New Path For Protein Design",
            "p( <i>all-atom</i> ) is unlocking new path for protein design",
        ),
    ],
)
def test_resolver_accepts_markup_and_compound_word_drift(monkeypatch, declared, fetched_title):
    resolver = _load_resolver()
    fetched = f"@article{{x, title={{{fetched_title}}}}}"
    monkeypatch.setattr(resolver, "fetch_bibtex", lambda _doi: fetched)

    assert resolver.resolve_entries([{"doi": "10.1/example", "title": declared}], None) == fetched


def test_resolver_still_rejects_a_different_title(monkeypatch):
    resolver = _load_resolver()
    monkeypatch.setattr(resolver, "fetch_bibtex", lambda _doi: "@article{x, title={A different method}}")

    with pytest.raises(RuntimeError, match="title mismatch"):
        resolver.resolve_entries([{"doi": "10.1/example", "title": "Expected scientific method"}], None)
