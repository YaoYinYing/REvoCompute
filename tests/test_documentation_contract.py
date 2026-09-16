# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Documentation ownership drift protection.

Issue #18: documentation explains machine-owned contracts but must not restate
their authoritative values.  `revocompute/static/openapi.json` owns API paths,
so any explicit API route a documentation page references must exist in it.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "revocompute" / "static" / "openapi.json"
DOCS = ROOT / "docs"

# Backticked references such as `GET /compute/api/types/<name>` or
# `/compute/api/task-parameters/{task_type}`.  Path placeholders are compared
# by shape, so `<task-type>` and `{task_type}` both mean one parameter.
_ROUTE_REFERENCE = re.compile(r"`(?:(GET|POST|PUT|DELETE|PATCH)\s+)?(/[A-Za-z0-9_./{}<>-]+)`")
_PLACEHOLDER = re.compile(r"[{<][^}>]+[}>]")


def _shape(path: str) -> str:
    return _PLACEHOLDER.sub("{}", path)


def _documentation_routes() -> list[tuple[Path, str, str | None, str]]:
    references: list[tuple[Path, str, str | None, str]] = []
    for page in sorted(DOCS.rglob("*.md")):
        for method, path in _ROUTE_REFERENCE.findall(page.read_text(encoding="utf-8")):
            if path.startswith("/compute/api/") or path in {"/skills.md", "/openapi.json"}:
                references.append((page, path, method or None, _shape(path)))
    return references


def _openapi_shapes() -> dict[str, set[str]]:
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    shapes: dict[str, set[str]] = {}
    for path, operations in spec["paths"].items():
        shapes.setdefault(_shape(path), set()).update(
            method for method in operations if method in {"get", "post", "put", "delete", "patch"}
        )
    return shapes


def test_no_documentation_page_references_an_unknown_api_route() -> None:
    known = _openapi_shapes()
    references = _documentation_routes()
    assert references, "route-reference extraction found no documentation routes"

    problems: list[str] = []
    for page, path, method, shape in references:
        if shape not in known:
            problems.append(f"{page.relative_to(ROOT)}: {path} is not in openapi.json")
        elif method and method.lower() not in known[shape]:
            problems.append(f"{page.relative_to(ROOT)}: {method} {path} is not in openapi.json")
    assert problems == []


@pytest.mark.parametrize(
    "page",
    ["docs/reference/server-api.md", "docs/reference/access-policies.md"],
)
def test_selected_reference_pages_do_not_copy_route_tables(page: str) -> None:
    """Reference pages must not maintain a second endpoint inventory."""
    text = (ROOT / page).read_text(encoding="utf-8")
    assert not re.search(
        r"^\|\s*`?(?:GET|POST|PUT|DELETE|PATCH)`?\s*\|.*\|",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
