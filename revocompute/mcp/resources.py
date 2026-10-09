# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Bounded, read-only MCP resources projected from canonical REvoCompute state.

Resources expose scientific/contextual data a client may read without a tool
call.  Every read re-checks authorization at read time: a resource URI is not a
capability, so ownership is verified on each access exactly as it is for the
tool surface.

The agent-workflow resource serves the canonical ``revocompute/static/skills.md``
verbatim.  There is no MCP-specific prose manual -- the workflow guidance has one
maintained source.
"""

from __future__ import annotations

import json
from typing import Any

from revocompute.mcp.bounds import MAX_TEXT_RESOURCE_BYTES, truncate_text
from revocompute.mcp.errors import INVALID_PARAMETERS, TASK_NOT_FOUND, McpError
from revocompute.mcp.handles import canonical_state

SKILLS_URI = "revocompute://skills"
TASK_SCHEMA_URI = "revocompute://task/{task_type}/schema"
RESULT_MANIFEST_URI = "revocompute://result/{task_handle}/manifest"


def read_skills() -> str:
    """Return the canonical agent-workflow document, bounded."""
    import os

    state = canonical_state()
    path = os.path.join(state.web.app.static_folder or "", "skills.md")
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:  # pragma: no cover - the file ships with the package
        raise McpError(INVALID_PARAMETERS, f"Agent workflow guide is unavailable: {exc}") from None
    bounded, truncated = truncate_text(text, MAX_TEXT_RESOURCE_BYTES)
    return bounded + ("\n\n<!-- truncated -->" if truncated else "")


def read_task_schema(task_type: str) -> str:
    """Return the canonical parameter JSON Schema for one enabled TaskType."""
    from revocompute.mcp.services import inspect_task

    payload = inspect_task(task_type)
    return json.dumps(payload.get("parameter_schema", {}), ensure_ascii=True, sort_keys=True)


def read_result_manifest(principal: Any, task_handle: str) -> str:
    """Return the owner-scoped ResultManifest summary for one opaque handle."""
    from revocompute.mcp.services import get_task_results

    mapping = canonical_state().handles.resolve(
        task_handle, user_id=principal.user_id, kind="task", now=_now()
    )
    if mapping is None:
        # Same class the tool layer uses for an unknown/foreign handle, so an
        # agent sees one answer for one condition regardless of surface.
        raise McpError(TASK_NOT_FOUND, "Unknown task handle")
    return json.dumps(get_task_results(principal, operation_id=mapping.operation_id), ensure_ascii=True, sort_keys=True)


def _now() -> float:
    import time

    return time.time()
