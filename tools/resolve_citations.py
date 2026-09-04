#!/usr/bin/env python3
"""Resolve task citations in distributed task manifests.

Each task type declares an ordered map ``citation_dois: {1: <doi>, 2: <doi>}``
(position -> DOI; projects with multiple papers list them all). This tool
fetches the BibTeX for every DOI via DOI content negotiation
(https://doi.org/<doi> with Accept: application/x-bibtex, Crossref-backed)
and writes the checked-in ``citation_bibtex`` field into each task manifest.
BibTeX is never hand-guessed, and DOIs are
validated against Crossref before entering the registry.

Usage:
  python3 tools/resolve_citations.py                 # resolve all declared DOIs
  python3 tools/resolve_citations.py --check         # verify no resolution is missing
  python3 tools/resolve_citations.py --search TITLE  # Crossref search for review
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

RUNNERS_DIR = Path(__file__).resolve().parents[1] / "docker" / "runners"


def fetch_bibtex(doi: str) -> str:
    request = urllib.request.Request(
        f"https://doi.org/{urllib.parse.quote(doi, safe='')}",
        headers={"Accept": "application/x-bibtex"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if not response.headers.get_content_type().startswith("application/x-bibtex"):
            raise RuntimeError(f"doi.org did not return BibTeX for {doi}")
        return response.read().decode("utf-8").strip()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _bibtex_title(bibtex: str) -> str:
    match = re.search(r"title=\{([^}]*)\}", bibtex)
    return _normalize(match.group(1)) if match else ""


def search_doi(title: str) -> list[tuple[str, str]]:
    """Crossref bibliographic search — return (DOI, title) hits for review.

    Exact-title acceptance only: the caller confirms the hit before a DOI
    ever enters the registry (EndnoteTweak's DOI-first discipline).
    """
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode({"query.bibliographic": title, "rows": "5"})
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    hits = []
    for item in payload.get("message", {}).get("items", []):
        item_title = (item.get("title") or [""])[0].strip().lower()
        hits.append((item.get("DOI", ""), item_title))
    return hits


def resolve_entries(entries: list[dict[str, object]], existing: str | None) -> str | None:
    if not entries:
        return None
    resolved = []
    for entry in entries:
        doi = str(entry["doi"])
        title = str(entry["title"])
        bibtex = fetch_bibtex(doi)
        if not bibtex:
            raise RuntimeError(f"empty BibTeX for {doi}")
        fetched_title = _bibtex_title(bibtex)
        if fetched_title and _normalize(title) not in fetched_title:
            # Human check: the fetched record disagrees with the declared
            # title — do not write it into the registry.
            raise RuntimeError(f"title mismatch for {doi}: declared {title!r} vs fetched {fetched_title!r}")
        resolved.append(bibtex)
    merged = "\n\n".join(resolved)
    if existing and merged in existing:
        return None
    return merged


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runners-dir", type=Path, default=RUNNERS_DIR)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--search")
    args = parser.parse_args()
    if args.search:
        for doi, hit_title in search_doi(args.search):
            print(f"{doi}\t{hit_title}")
        return 0
    failures = 0
    changed = 0
    for task_path in sorted(args.runners_dir.glob("*/tasks/*/task.yaml")):
        data = yaml.safe_load(task_path.read_text(encoding="utf-8")) or {}
        entries = data.get("citation_dois") if isinstance(data, dict) else None
        if not entries:
            continue
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            print(f"FAIL {task_path}: citation_dois must be a list of mappings", file=sys.stderr)
            failures += 1
            continue
        existing = str(data.get("citation_bibtex") or "")
        try:
            replacement = resolve_entries(entries, existing)
        except (RuntimeError, OSError, urllib.error.URLError) as exc:
            print(f"FAIL {task_path}: {exc}", file=sys.stderr)
            failures += 1
            continue
        if replacement is None:
            continue
        changed += 1
        if not args.check:
            data["citation_bibtex"] = replacement
            task_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(f"resolved {len(entries)} DOI(s) for {task_path}")
    if failures:
        return 1
    if args.check:
        if changed:
            print("resolutions are stale — rerun without --check", file=sys.stderr)
            return 1
        return 0
    print("manifests updated" if changed else "nothing to resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
