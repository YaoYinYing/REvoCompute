# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Canonical Task citation contract coverage.

One checked-in ``citations`` list is the single bibliographic source of truth:
BibTeX owns the record (title included) and the explicit bare DOI is the
canonical locator.  Derived titles/URLs are computed at load time.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from revocompute.citations import Citation, citations_bibtex, load_citations, normalize_doi
from revocompute.task_types import discover_plugins, get, list_types

ROOT = Path(__file__).resolve().parents[1]

SINGLE = "@article{Sun_2025, title={Ultrafast stability prediction}, DOI={10.1016/j.xinn.2024.100750}}"
OTHER = "@article{Kamisetty_2013, title={Coevolution-based contact prediction}, DOI={10.1073/pnas.1314045110}}"


def _entry(num: int, doi: str, bibtex: str) -> dict:
    return {"num": num, "doi": doi, "bibtex": bibtex}


def test_valid_single_citation_derives_title_and_url():
    citations = load_citations([_entry(1, "10.1016/j.xinn.2024.100750", SINGLE)], "demo")

    assert citations == (
        Citation(
            num=1,
            doi="10.1016/j.xinn.2024.100750",
            bibtex=SINGLE,
            title="Ultrafast stability prediction",
            url="https://doi.org/10.1016/j.xinn.2024.100750",
        ),
    )


def test_valid_multiple_citations_are_ordered_by_num_independent_of_list_order():
    citations = load_citations(
        [_entry(2, "10.1073/pnas.1314045110", OTHER), _entry(1, "10.1016/j.xinn.2024.100750", SINGLE)],
        "demo",
    )

    assert [citation.num for citation in citations] == [1, 2]
    assert citations[0].title == "Ultrafast stability prediction"
    assert citations[1].title == "Coevolution-based contact prediction"


def test_absent_citations_are_allowed():
    assert load_citations(None, "demo") == ()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([_entry(1, "not-a-doi", SINGLE)], "invalid citation DOI"),
        ([_entry(1, "https://doi.org/10.1/x", SINGLE)], "invalid citation DOI"),
        ([_entry(0, "10.1016/j.xinn.2024.100750", SINGLE)], "invalid citation num"),
        ([_entry(-1, "10.1016/j.xinn.2024.100750", SINGLE)], "invalid citation num"),
        ([_entry(True, "10.1016/j.xinn.2024.100750", SINGLE)], "invalid citation num"),
        ([_entry(1, "10.1016/j.xinn.2024.100750", "")], "must declare BibTeX"),
        ([_entry(1, "10.1016/j.xinn.2024.100750", "   ")], "must declare BibTeX"),
    ],
)
def test_invalid_citation_fields_are_rejected(raw, message):
    with pytest.raises(ValueError, match=message):
        load_citations(raw, "demo")


def test_duplicate_citation_num_is_rejected():
    with pytest.raises(ValueError, match="duplicate citation num"):
        load_citations(
            [_entry(1, "10.1016/j.xinn.2024.100750", SINGLE), _entry(1, "10.1073/pnas.1314045110", OTHER)],
            "demo",
        )


def test_citation_entry_requires_exactly_the_source_keys():
    with pytest.raises(ValueError, match="exactly"):
        load_citations([{"num": 1, "doi": "10.1/x", "bibtex": SINGLE, "title": "declared"}], "demo")
    with pytest.raises(ValueError, match="exactly"):
        load_citations([{"num": 1, "doi": "10.1/x"}], "demo")


def test_malformed_bibtex_failed_block_is_rejected():
    # bibtexparser v2 is fault-tolerant; a syntactically broken record lands in
    # failed_blocks rather than raising, so the loader must reject it explicitly.
    import bibtexparser

    broken = "@article{Broken_2024, title={Missing close"
    assert bibtexparser.parse_string(broken).failed_blocks
    with pytest.raises(ValueError, match="did not parse cleanly"):
        load_citations([_entry(1, "10.1016/j.xinn.2024.100750", broken)], "demo")


def test_bibtex_requires_exactly_one_bibliographic_entry():
    with pytest.raises(ValueError, match="exactly one"):
        load_citations([_entry(1, "10.1016/j.xinn.2024.100750", SINGLE + "\n\n" + OTHER)], "demo")
    with pytest.raises(ValueError, match="exactly one"):
        load_citations([_entry(1, "10.1016/j.xinn.2024.100750", "@string{foo = {bar}}")], "demo")


def test_bibtex_record_must_declare_a_title():
    with pytest.raises(ValueError, match="must declare a title"):
        load_citations(
            [_entry(1, "10.1016/j.xinn.2024.100750", "@article{No_Title, journal={The Innovation}}")],
            "demo",
        )


def test_bibtex_doi_must_agree_with_the_declared_bare_doi():
    with pytest.raises(ValueError, match="disagrees with the declared DOI"):
        load_citations([_entry(1, "10.1016/j.xinn.2024.100750", OTHER)], "demo")


def test_doi_case_and_whitespace_are_normalized_for_the_cross_check():
    bibtex = "@article{Wang_2024, title={Disentanglement}, DOI={10.1103/PRXLIFE.2.023005}}"
    citations = load_citations([_entry(1, "10.1103/PRXLife.2.023005", bibtex)], "demo")

    assert normalize_doi(citations[0].doi) == "10.1103/prxlife.2.023005"
    assert citations[0].doi == "10.1103/PRXLife.2.023005"


def test_citations_bibtex_exports_ordered_source_records():
    citations = load_citations(
        [_entry(2, "10.1073/pnas.1314045110", OTHER), _entry(1, "10.1016/j.xinn.2024.100750", SINGLE)],
        "demo",
    )

    exported = citations_bibtex(citations)

    assert exported == f"{SINGLE}\n\n{OTHER}\n"
    assert exported.index("Sun_2025") < exported.index("Kamisetty_2013")
    assert citations_bibtex(()) == ""


def test_removed_legacy_citation_fields_fail_normal_registry_loading(tmp_path):
    import yaml

    family = tmp_path / "demo"
    task_dir = family / "tasks" / "echo"
    task_dir.mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "id: demo\nversion: '1'\nruntime: {image_artifact: demo.sif, definition: demo.def}\n"
        "tasks: [tasks/echo/task.yaml]\n",
        encoding="utf-8",
    )
    (family / "demo.def").write_text("Bootstrap: demo\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "echo",
                "display_name": "Echo",
                "inputs": {"source": {"type": "text", "formats": ["json"], "cardinality": {"min": 1, "max": 1}}},
                "citation_dois": [{"num": 1, "doi": "10.1016/j.xinn.2024.100750", "title": "Legacy"}],
                "citation_bibtex": SINGLE,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="removed citation fields"):
        discover_plugins(str(tmp_path))


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
            assert citation.url == f"https://doi.org/{citation.doi}"

    gremlin, _ = get("gremlin_lh_fit")
    assert [citation.num for citation in gremlin.citations] == [1, 2]
    assert gremlin.citations[0].doi == "10.1103/PRXLife.2.023005"
    assert "Disentanglement" in gremlin.citations[0].title
