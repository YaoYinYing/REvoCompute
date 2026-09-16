# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""JSON content validator (DoS caps only, no schema checks)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from revocompute.input_validators.common import MAX_JSON_BYTES, MAX_JSON_DEPTH, MAX_JSON_NODES


def _json_stats(root: Any) -> tuple[int, int]:
    """Return ``(node_count, max_depth)`` with an iterative stack walk."""
    nodes = 0
    depth = 0
    stack: list[tuple[Any, int]] = [(root, 1)]
    while stack:
        node, level = stack.pop()
        nodes += 1
        if level > depth:
            depth = level
        if isinstance(node, dict):
            stack.extend((child, level + 1) for child in node.values())
        elif isinstance(node, list):
            stack.extend((child, level + 1) for child in node)
    return nodes, depth


# One shared bounded decoder serves both uploaded JSON files and the
# multipart ``workspace`` document, so untrusted structured input cannot reach
# a Runner-owned workspace normalizer without the same byte/depth/node policy.
_JSON_ERROR_SUFFIXES = {
    "nul": "contains binary content (NUL byte)",
    "too_large": f"exceeds the {MAX_JSON_BYTES // (1024 * 1024)} MiB input limit",
    "not_utf8": "is not valid UTF-8 text",
    "invalid": "does not appear to be valid JSON",
    "too_many_nodes": f"contains more than {MAX_JSON_NODES} values",
    "too_deep": f"is nested deeper than {MAX_JSON_DEPTH} levels",
}


def parse_bounded_json(data: bytes | str) -> tuple[Any, str | None]:
    """Decode one bounded JSON document, returning ``(value, error_code)``.

    Complexity caps only — no schema checks.  A ``RecursionError`` from a
    deeply nested document is treated as invalid input, not a server failure.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    if b"\0" in data:
        return None, "nul"
    if len(data) > MAX_JSON_BYTES:
        return None, "too_large"
    try:
        value = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        return None, "not_utf8"
    except (json.JSONDecodeError, ValueError, RecursionError):
        return None, "invalid"
    nodes, depth = _json_stats(value)
    if nodes > MAX_JSON_NODES:
        return None, "too_many_nodes"
    if depth > MAX_JSON_DEPTH:
        return None, "too_deep"
    return value, None


def json_error_message(code: str, *, subject: str) -> str:
    """Render one bounded-JSON error code for a caller's user-facing subject."""
    return f"{subject} {_JSON_ERROR_SUFFIXES[code]}"


def validate_json(path: str) -> str | None:
    """Return an error message if *path* is not parseable JSON within caps.

    Complexity caps only — no schema checks; any well-formed JSON document
    passes.
    """
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return f"Could not read uploaded JSON file: {exc}"
    _, error = parse_bounded_json(data)
    if error is not None:
        return json_error_message(error, subject="Uploaded JSON file")
    return None
