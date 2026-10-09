# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Explicit, tested context/resource bounds for the MCP surface.

A scientific result can be gigabytes; a model context is not.  Every MCP
response is therefore bounded by a named constant here, and a bounded response
always says so -- an agent must never have to infer that truncated content is
complete.
"""

from __future__ import annotations

from typing import Any

#: Maximum number of catalog entries returned by ``discover_tasks``.
MAX_CATALOG_ENTRIES = 200
#: Maximum bytes of a single Task/Tool parameter schema, or of any text
#: resource the server serves inline.
MAX_SCHEMA_BYTES = 64 * 1024
MAX_TEXT_RESOURCE_BYTES = 64 * 1024
#: Maximum bytes of a single inlined artifact payload.  Anything larger is
#: metadata plus an authorized retrieval resource, never inline content.
MAX_INLINE_ARTIFACT_BYTES = 128 * 1024
#: Maximum number of artifacts or logical files listed in one result summary.
MAX_RESULT_ENTRIES = 500
#: Maximum bytes of secondary human-readable error detail.
MAX_ERROR_DETAIL_BYTES = 2 * 1024
#: Maximum total bytes of inputs a single MCP submission may carry.
MAX_SUBMISSION_INPUT_BYTES = 16 * 1024 * 1024
#: Maximum length of any single client-supplied string parameter.
MAX_STRING_LENGTH = 8192


def truncate_text(value: str, limit: int) -> tuple[str, bool]:
    """Return ``(text, truncated)`` with *limit* honoured on a character bound."""
    if len(value) <= limit:
        return value, False
    return value[:limit], True


def bound_sequence(values: list[Any], limit: int) -> tuple[list[Any], bool]:
    """Return ``(values, truncated)`` with at most *limit* entries."""
    if len(values) <= limit:
        return values, False
    return values[:limit], True


def truncate_detail(value: str | None) -> str | None:
    if value is None:
        return None
    text, truncated = truncate_text(value, MAX_ERROR_DETAIL_BYTES)
    return text + "…" if truncated else text
