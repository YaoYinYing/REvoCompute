#!/usr/bin/env python3
"""Authoring helper for the canonical Task ``citations`` contract.

A Task manifest owns exactly one bibliographic source of truth per citation:

```yaml
citations:
- num: 1
  doi: 10.xxxx/xxxxx
  bibtex: >-
    @article{...}
```

BibTeX owns the bibliographic record (title included); the explicit bare DOI is
the canonical locator. Derived titles and ``https://doi.org/...`` links are
computed by Core at load time, never stored or checked in here.

Usage:
  python3 tools/resolve_citations.py --check          # local validation, no network
  python3 tools/resolve_citations.py --fill-missing   # fetch BibTeX for empty entries
  python3 tools/resolve_citations.py --refresh        # refetch and replace every record
  python3 tools/resolve_citations.py --search TITLE   # Crossref search before adding a DOI

``--check`` (and the default action) never touches the network.  ``--fill-missing``
and ``--refresh`` are explicit authoring operations: once a record is committed,
the checked-in BibTeX stays authoritative until an operator asks for a refresh.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

RUNNERS_DIR = Path(__file__).resolve().parents[1] / "docker" / "runners"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from revocompute.citations import load_citations  # noqa: E402


def fetch_bibtex(doi: str) -> str:
    request = urllib.request.Request(
        f"https://doi.org/{urllib.parse.quote(doi, safe='')}",
        headers={"Accept": "application/x-bibtex"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if not response.headers.get_content_type().startswith("application/x-bibtex"):
            raise RuntimeError(f"doi.org did not return BibTeX for {doi}")
        return response.read().decode("utf-8").strip()


def search_doi(title: str) -> list[tuple[str, str]]:
    """Crossref bibliographic search — return (DOI, title) hits for review."""
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode({"query.bibliographic": title, "rows": "5"})
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    hits = []
    for item in payload.get("message", {}).get("items", []):
        item_title = (item.get("title") or [""])[0].strip().lower()
        hits.append((item.get("DOI", ""), item_title))
    return hits


def render_citations_block(entries: list[dict[str, object]]) -> str:
    """Render the canonical ``citations:`` YAML block for *entries*."""
    lines = ["citations:"]
    for entry in entries:
        lines.append(f"- num: {entry['num']}")
        lines.append(f"  doi: {entry['doi']}")
        lines.append("  bibtex: >-")
        for raw_line in str(entry["bibtex"]).splitlines():
            stripped = raw_line.lstrip()
            lines.append(f"    {stripped}" if stripped else "")
    return "\n".join(lines) + "\n"


def find_top_level_block(lines: list[str], key: str) -> tuple[int, int] | None:
    start = None
    for index, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            start = index
            break
    if start is None:
        return None
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.startswith(("- ", " ", "\t")):
            end += 1
            continue
        if not line.strip():
            lookahead = end + 1
            while lookahead < len(lines) and not lines[lookahead].strip():
                lookahead += 1
            if lookahead < len(lines) and lines[lookahead].startswith(("- ", " ", "\t")):
                end = lookahead
                continue
        break
    return (start, end)


def rewrite_citations_block(text: str, entries: list[dict[str, object]]) -> str:
    lines = text.splitlines(keepends=True)
    span = find_top_level_block(lines, "citations")
    if span is None:
        raise ValueError("manifest has no citations block")
    start, end = span
    block = render_citations_block(entries)
    result = "".join(lines[:start]) + block + "".join(lines[end:])
    if not result.endswith("\n"):
        result += "\n"
    return result


def _validated(entry: dict[str, object], task_label: str) -> None:
    """Validate exactly the same contract Core enforces before writing it back."""
    load_citations(
        [{"num": entry["num"], "doi": entry["doi"], "bibtex": entry["bibtex"]}],
        f"{task_label} (resolver)",
    )


def _local_check(task_path: Path, data: dict[str, object]) -> list[str]:
    if "citation_dois" in data or "citation_bibtex" in data:
        return [f"{task_path}: uses removed citation fields; migrate to 'citations'"]
    entries = data.get("citations")
    if not entries:
        return []
    try:
        load_citations(entries, str(data.get("id") or task_path.parent.name))
    except ValueError as exc:
        return [f"{task_path}: {exc}"]
    for entry in entries:
        if not str(entry.get("bibtex") or "").strip():
            return [f"{task_path}: citation {entry.get('num')} has no checked-in BibTeX (run --fill-missing)"]
    return []


def _fill(task_path: Path, entries: list[dict[str, object]], *, refresh: bool) -> tuple[bool, list[str]]:
    changed = False
    problems: list[str] = []
    label = str(task_path)
    for entry in entries:
        current = str(entry.get("bibtex") or "").strip()
        if current and not refresh:
            continue
        try:
            fetched = fetch_bibtex(str(entry["doi"]))
            candidate = {"num": entry["num"], "doi": entry["doi"], "bibtex": fetched}
            _validated(candidate, label)
        except (RuntimeError, OSError, urllib.error.URLError, ValueError) as exc:
            problems.append(f"{task_path}: citation {entry.get('num')}: {exc}")
            continue
        entry["bibtex"] = fetched
        changed = True
    return changed, problems


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runners-dir", type=Path, default=RUNNERS_DIR)
    parser.add_argument("--check", action="store_true", help="validate locally without network access")
    parser.add_argument("--fill-missing", action="store_true", help="fetch BibTeX for entries missing it")
    parser.add_argument("--refresh", action="store_true", help="explicitly refetch and replace every record")
    parser.add_argument("--search", help="Crossref title search before adding a citation")
    args = parser.parse_args()
    network_modes = [flag for flag in (args.fill_missing, args.refresh) if flag]
    if len(network_modes) > 1:
        parser.error("--fill-missing and --refresh are mutually exclusive")
    if args.search:
        for doi, hit_title in search_doi(args.search):
            print(f"{doi}\t{hit_title}")
        return 0

    failures: list[str] = []
    changed_count = 0
    for task_path in sorted(args.runners_dir.glob("*/tasks/*/task.yaml")):
        data = yaml.safe_load(task_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        if args.fill_missing or args.refresh:
            entries = data.get("citations") or []
            changed, problems = _fill(task_path, entries, refresh=args.refresh)
            failures.extend(problems)
            if changed:
                task_path.write_text(rewrite_citations_block(task_path.read_text(encoding="utf-8"), entries), encoding="utf-8")
                changed_count += 1
                print(f"updated {task_path}")
            continue
        failures.extend(_local_check(task_path, data))

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    if args.fill_missing or args.refresh:
        print(f"manifests updated: {changed_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
