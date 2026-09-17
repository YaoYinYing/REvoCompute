# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Canonical Runner citation contract.

A Task manifest declares its method citations as one ordered ``citations`` list.
Each entry carries exactly three source fields:

```yaml
citations:
  - num: 1
    doi: 10.xxxx/xxxxx
    bibtex: >-
      @article{...}
```

The BibTeX record is the authoritative bibliographic source (including the
title). The explicit bare DOI is the canonical external locator. Display titles
and ``https://doi.org/...`` links are derived here at load time and are never
written back into the manifest, so a citation has exactly one checked-in source
of truth.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import bibtexparser

# Bare DOI only: a canonical locator is derived as https://doi.org/<doi>, so
# URL/``doi:`` prefixes are rejected rather than silently normalized.
_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")

_CITATION_KEYS = {"num", "doi", "bibtex"}


@dataclass(frozen=True, slots=True)
class Citation:
    """One resolved citation: source fields plus derived presentation data."""

    num: int
    doi: str
    bibtex: str
    title: str
    url: str

    def projection(self) -> dict[str, Any]:
        """Lightweight derived representation for catalog/Runner/detail APIs."""
        return {"num": self.num, "doi": self.doi, "title": self.title, "url": self.url}


def normalize_doi(value: str) -> str:
    """Normalize a DOI for equality comparison (whitespace and case only)."""
    return value.strip().lower()


def _fields(entry: bibtexparser.model.Entry) -> dict[str, str]:
    return {str(name).lower(): str(field.value) for name, field in entry.fields_dict.items()}


def _parse_single_entry(bibtex: str, label: str) -> bibtexparser.model.Entry:
    library = bibtexparser.parse_string(bibtex)
    if library.failed_blocks:
        raise ValueError(f"{label} BibTeX did not parse cleanly")
    if library.strings or library.preambles or library.comments:
        raise ValueError(f"{label} BibTeX must contain exactly one bibliographic entry")
    if len(library.entries) != 1:
        raise ValueError(f"{label} BibTeX must contain exactly one bibliographic entry")
    return library.entries[0]


def load_citations(raw: Any, name: str) -> tuple[Citation, ...]:
    """Validate and resolve the ordered ``citations`` list of one Task manifest.

    Owns manifest shape validation, DOI validation/normalization, BibTeX parsing
    (including failed-block rejection), single-entry validation, title
    extraction, the BibTeX/declared DOI cross-check, and ascending ``num``
    ordering.  Import-safe: no network access.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"Task type {name!r} citations must be a list of {{num, doi, bibtex}}")

    resolved: list[Citation] = []
    seen: set[int] = set()
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != _CITATION_KEYS:
            raise ValueError(f"Task type {name!r} citation entries must be exactly {{num, doi, bibtex}}")
        num = entry["num"]
        if not isinstance(num, int) or isinstance(num, bool) or num <= 0:
            raise ValueError(f"Task type {name!r} has an invalid citation num: {num!r}")
        if num in seen:
            raise ValueError(f"Task type {name!r} has a duplicate citation num: {num!r}")
        seen.add(num)

        doi = entry["doi"]
        if not isinstance(doi, str) or not _DOI_PATTERN.fullmatch(doi.strip()):
            raise ValueError(f"Task type {name!r} has an invalid citation DOI: {doi!r}")
        doi = doi.strip()

        bibtex = entry["bibtex"]
        if not isinstance(bibtex, str) or not bibtex.strip():
            raise ValueError(f"Task type {name!r} citation {num} must declare BibTeX")
        bibtex = bibtex.strip()

        label = f"Task type {name!r} citation {num}"
        parsed = _parse_single_entry(bibtex, label)
        fields = _fields(parsed)
        title = " ".join(fields.get("title", "").split())
        if not title:
            raise ValueError(f"{label} BibTeX must declare a title")
        if "doi" in fields and normalize_doi(fields["doi"]) != normalize_doi(doi):
            raise ValueError(
                f"{label} BibTeX DOI {fields['doi']!r} disagrees with the declared DOI {doi!r}"
            )
        resolved.append(
            Citation(num=num, doi=doi, bibtex=bibtex, title=title, url=f"https://doi.org/{doi}")
        )

    return tuple(sorted(resolved, key=lambda citation: citation.num))


def citations_bibtex(citations: tuple[Citation, ...]) -> str:
    """Assemble the exported ``citations.bib`` from ordered source records."""
    ordered = sorted(citations, key=lambda citation: citation.num)
    if not ordered:
        return ""
    return "\n\n".join(citation.bibtex for citation in ordered) + "\n"
