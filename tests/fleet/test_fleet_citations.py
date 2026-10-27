# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations
from pathlib import Path
from revocompute.task_types import discover_plugins, get, list_types

ROOT = Path(__file__).resolve().parents[2]


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
