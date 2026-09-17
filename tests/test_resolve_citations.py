# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Authoring-helper coverage for tools/resolve_citations.py.

The resolver is an authoring tool, never a runtime metadata authority.  Local
``--check`` must work without network access; remote fetch is explicit and
mockable.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

FILLED = "@article{Sun_2025, title={Ultrafast stability prediction}, DOI={10.1016/j.xinn.2024.100750}}"
REFRESHED = "@article{Sun_2025, title={Refreshed record}, DOI={10.1016/j.xinn.2024.100750}}"


def _load_resolver():
    spec = importlib.util.spec_from_file_location("resolve_citations", ROOT / "tools/resolve_citations.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(tmp_path: Path, citations: list[dict]) -> Path:
    task = tmp_path / "demo" / "tasks" / "echo" / "task.yaml"
    task.parent.mkdir(parents=True)
    task.write_text(
        yaml.safe_dump(
            {"id": "echo", "display_name": "Echo", "citations": citations},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return task


def _run(resolver, monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["resolve_citations", *argv])
    return resolver.main()


def test_local_check_passes_without_network(monkeypatch, tmp_path):
    resolver = _load_resolver()
    _manifest(tmp_path, [{"num": 1, "doi": "10.1016/j.xinn.2024.100750", "bibtex": FILLED}])
    monkeypatch.setattr(resolver, "fetch_bibtex", lambda _doi: (_ for _ in ()).throw(AssertionError("network")))

    assert _run(resolver, monkeypatch, "--runners-dir", str(tmp_path), "--check") == 0


def test_local_check_reports_missing_bibtex_and_legacy_fields(monkeypatch, tmp_path):
    resolver = _load_resolver()
    task = _manifest(tmp_path, [{"num": 1, "doi": "10.1016/j.xinn.2024.100750", "bibtex": ""}])

    assert _run(resolver, monkeypatch, "--runners-dir", str(tmp_path), "--check") == 1

    task.write_text(
        "id: echo\ncitation_dois:\n- num: 1\n  doi: 10.1016/j.xinn.2024.100750\n  title: Legacy\n",
        encoding="utf-8",
    )
    assert _run(resolver, monkeypatch, "--runners-dir", str(tmp_path), "--check") == 1


def test_fill_missing_fetches_validates_and_writes(monkeypatch, tmp_path):
    resolver = _load_resolver()
    task = _manifest(tmp_path, [{"num": 1, "doi": "10.1016/j.xinn.2024.100750", "bibtex": ""}])
    monkeypatch.setattr(resolver, "fetch_bibtex", lambda _doi: FILLED)

    assert _run(resolver, monkeypatch, "--runners-dir", str(tmp_path), "--fill-missing") == 0

    data = yaml.safe_load(task.read_text(encoding="utf-8"))
    assert data["citations"] == [{"num": 1, "doi": "10.1016/j.xinn.2024.100750", "bibtex": FILLED}]
    # The written record must round-trip through the same Core contract.
    resolver.load_citations(data["citations"], "echo")


def test_fill_missing_skips_a_valid_checked_in_record(monkeypatch, tmp_path):
    resolver = _load_resolver()
    task = _manifest(tmp_path, [{"num": 1, "doi": "10.1016/j.xinn.2024.100750", "bibtex": FILLED}])
    monkeypatch.setattr(resolver, "fetch_bibtex", lambda _doi: (_ for _ in ()).throw(AssertionError("network")))
    before = task.read_text(encoding="utf-8")

    assert _run(resolver, monkeypatch, "--runners-dir", str(tmp_path), "--fill-missing") == 0

    assert task.read_text(encoding="utf-8") == before


def test_refresh_explicitly_replaces_the_checked_in_record(monkeypatch, tmp_path):
    resolver = _load_resolver()
    task = _manifest(tmp_path, [{"num": 1, "doi": "10.1016/j.xinn.2024.100750", "bibtex": FILLED}])
    monkeypatch.setattr(resolver, "fetch_bibtex", lambda _doi: REFRESHED)

    assert _run(resolver, monkeypatch, "--runners-dir", str(tmp_path), "--refresh") == 0

    data = yaml.safe_load(task.read_text(encoding="utf-8"))
    assert data["citations"][0]["bibtex"] == REFRESHED


def test_multiple_citations_are_filled_independently(monkeypatch, tmp_path):
    resolver = _load_resolver()
    task = _manifest(
        tmp_path,
        [
            {"num": 2, "doi": "10.1073/pnas.1314045110", "bibtex": ""},
            {"num": 1, "doi": "10.1016/j.xinn.2024.100750", "bibtex": ""},
        ],
    )
    fetched = {
        "10.1016/j.xinn.2024.100750": FILLED,
        "10.1073/pnas.1314045110": "@article{K_2013, title={Contacts}, DOI={10.1073/pnas.1314045110}}",
    }
    monkeypatch.setattr(resolver, "fetch_bibtex", lambda doi: fetched[doi])

    assert _run(resolver, monkeypatch, "--runners-dir", str(tmp_path), "--fill-missing") == 0

    data = yaml.safe_load(task.read_text(encoding="utf-8"))
    assert [entry["num"] for entry in data["citations"]] == [2, 1]
    assert all(entry["bibtex"] for entry in data["citations"])


@pytest.mark.parametrize(
    ("returned", "match"),
    [
        ("@article{Other, title={Other}, DOI={10.1/other}}", "disagrees"),
        ("", "empty"),
        ("@article{Broken, title={oops}", "did not parse cleanly"),
    ],
)
def test_fill_missing_rejects_invalid_fetched_records(monkeypatch, tmp_path, returned, match):
    resolver = _load_resolver()
    task = _manifest(tmp_path, [{"num": 1, "doi": "10.1016/j.xinn.2024.100750", "bibtex": ""}])
    monkeypatch.setattr(resolver, "fetch_bibtex", lambda _doi: returned)

    assert _run(resolver, monkeypatch, "--runners-dir", str(tmp_path), "--fill-missing") == 1
    assert match in task.read_text(encoding="utf-8") or yaml.safe_load(task.read_text())["citations"][0]["bibtex"] == ""


def test_fill_missing_reports_network_failure(monkeypatch, tmp_path, capsys):
    resolver = _load_resolver()
    task = _manifest(tmp_path, [{"num": 1, "doi": "10.1016/j.xinn.2024.100750", "bibtex": ""}])
    monkeypatch.setattr(resolver, "fetch_bibtex", lambda _doi: (_ for _ in ()).throw(OSError("offline")))

    assert _run(resolver, monkeypatch, "--runners-dir", str(tmp_path), "--fill-missing") == 1
    assert "offline" in capsys.readouterr().err


def test_search_is_authoring_only(monkeypatch, capsys):
    resolver = _load_resolver()
    monkeypatch.setattr(resolver, "search_doi", lambda _title: [("10.1/x", "a title")])

    assert _run(resolver, monkeypatch, "--search", "title") == 0
    assert "10.1/x\ta title" in capsys.readouterr().out
