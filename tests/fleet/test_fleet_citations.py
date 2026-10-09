# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations
from pathlib import Path
import pytest
from revocompute.citations import (
    Citation,
    citations_bibtex,
    load_citations,
    normalize_doi,
    presentation_title,
)
from revocompute.task_types import discover_plugins, get, list_types
import yaml
ROOT = Path(__file__).resolve().parents[2]


def test_checked_in_markup_titles_are_presentation_safe():
    expected = {
        "autodock_gpu": "Accelerating AutoDock4 with GPUs and Gradient-Based Local Search",
        "foundry_rfd3_design": "De novo Design of All-atom Biomolecular Interactions with RFdiffusion3",
        "pallatom_generate": "P(all-atom) Is Unlocking New Path For Protein Design",
    }
    paths = {
        "autodock_gpu": ROOT / "docker/runners/autodock_gpu/tasks/autodock_gpu/task.yaml",
        "foundry_rfd3_design": ROOT / "docker/runners/foundry/tasks/foundry_rfd3_design/task.yaml",
        "pallatom_generate": ROOT / "docker/runners/pallatom/tasks/pallatom_generate/task.yaml",
    }
    for task_id, task_path in paths.items():
        data = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        citation = load_citations(data["citations"], task_id)[0]
        assert citation.title == expected[task_id]
        assert "<" not in citation.title and ">" not in citation.title
        # The checked-in BibTeX stays the source of truth, markup included.
        assert "<" in citation.bibtex

def test_complete_runner_tree_loads_every_migrated_citation():
    discover_plugins(str(ROOT / "docker" / "runners"))
    tasks = list_types()

    with_citations = [task for task in tasks if task.citations]
    assert len(with_citations) >= 40
    for task in with_citations:
        assert [citation.num for citation in task.citations] == sorted(
            citation.num for citation in task.citations
        )
        for citation in task.citations:
            assert citation.title.strip()
            assert "<" not in citation.title and ">" not in citation.title
            assert citation.url == f"https://doi.org/{citation.doi}"

    gremlin, _ = get("gremlin_lh_fit")
    assert [citation.num for citation in gremlin.citations] == [1, 2]
    assert gremlin.citations[0].doi == "10.1103/PRXLife.2.023005"
    assert "Disentanglement" in gremlin.citations[0].title
