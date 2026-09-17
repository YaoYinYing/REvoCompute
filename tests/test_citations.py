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

from revocompute.citations import (
    Citation,
    citations_bibtex,
    load_citations,
    normalize_doi,
    presentation_title,
)
from revocompute.task_types import discover_plugins, get, list_types
import yaml

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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Crossref splits a token around small-caps fragments; join them back.
        (
            "Accelerating A <scp>uto</scp> D <scp>ock</scp> 4 with GPUs and Gradient-Based Local Search",
            "Accelerating AutoDock4 with GPUs and Gradient-Based Local Search",
        ),
        ("<i>De novo</i> Design of All-atom Biomolecular Interactions", "De novo Design of All-atom Biomolecular Interactions"),
        ("P( <i>all-atom</i> ) Is Unlocking New Path For Protein Design", "P(all-atom) Is Unlocking New Path For Protein Design"),
        ("H<sub>2</sub>O and CO<sub>2</sub> capture", "H2O and CO2 capture"),
        ("10<sup>th</sup> edition", "10th edition"),
        # A genuine word boundary around a small-caps word is preserved.
        ("The <scp>ABC</scp> protein family", "The ABC protein family"),
        ("Plain title with no markup", "Plain title with no markup"),
    ],
)
def test_presentation_title_strips_markup_without_corrupting_words(raw, expected):
    title = presentation_title(raw)

    assert title == expected
    assert "<" not in title and ">" not in title


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


def test_removed_legacy_citation_fields_fail_normal_registry_loading(tmp_path):
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
            assert "<" not in citation.title and ">" not in citation.title
            assert citation.url == f"https://doi.org/{citation.doi}"

    gremlin, _ = get("gremlin_lh_fit")
    assert [citation.num for citation in gremlin.citations] == [1, 2]
    assert gremlin.citations[0].doi == "10.1103/PRXLife.2.023005"
    assert "Disentanglement" in gremlin.citations[0].title
