# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The REvoCompute MCP server: a protocol projection of the canonical service.

Design rules this module implements (from ``TODO.md``):

* **Progressive discovery.** A small, stable set of primitives -- no MCP tool
  per Runner.  ``discover_tasks`` returns a compact catalog;
  ``inspect_task`` returns one canonical contract.
* **Long-running operations use opaque handles.**  A scientific Task is
  identified to an MCP client by a high-entropy, user-scoped handle minted here
  and mapped server-side to the canonical Task id; the content-derived id is
  never exposed.
* **One canonical control path.**  Every operation terminates in the code the
  HTTP API and Web application already run (see ``services``/``context``).
* **Scientific-user trust domain only.**  No admin/operator capability, no
  shell, no filesystem, no arbitrary fetch, no direct execution, no Sampling or
  Elicitation, no server-initiated user input.
"""

from __future__ import annotations

import time
from typing import Any

from mcp import types
from mcp.server.fastmcp import Context, FastMCP

from revocompute.mcp import resources as _resources
from revocompute.mcp import services
from revocompute.mcp.bounds import MAX_STRING_LENGTH, truncate_detail, truncate_text
from revocompute.mcp.context import authenticate
from revocompute.mcp.errors import INVALID_PARAMETERS, McpError

SERVER_NAME = "revocompute"
SERVER_INSTRUCTIONS = (
    "REvoCompute scientific compute service (scientific-user surface). "
    "Discover TaskTypes with discover_tasks, inspect one with inspect_task, "
    "validate with preflight_task, then submit_task. Long-running work returns "
    "an opaque task_handle used by get_task_status, get_task_results, "
    "cancel_task, and retrieve_artifact. Read revocompute://skills for the "
    "canonical agent workflow. Operator/administrator control is not exposed."
)


def _now() -> float:
    return time.time()


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise McpError(INVALID_PARAMETERS, f"{field} is required")
    if len(value) > MAX_STRING_LENGTH:
        raise McpError(INVALID_PARAMETERS, f"{field} exceeds the {MAX_STRING_LENGTH} character limit")
    return value.strip()


def _ok(payload: dict[str, Any]) -> types.CallToolResult:
    from revocompute.mcp.errors import text

    return types.CallToolResult(content=[text(payload)], structuredContent=payload)


def _error(error: McpError) -> types.CallToolResult:
    payload = error.payload()
    detail = truncate_detail(error.detail)
    if detail:
        payload["detail"] = detail
    message, _truncated = truncate_text(error.message, MAX_STRING_LENGTH)
    payload["message"] = message
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=_json(payload))],
        structuredContent=payload,
        isError=True,
    )


def _json(payload: Any) -> str:
    import json

    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def build_server() -> FastMCP:
    """Construct the MCP server with its fixed, bounded primitive surface."""
    server = FastMCP(name=SERVER_NAME, instructions=SERVER_INSTRUCTIONS, stateless_http=True)

    # -- discovery ---------------------------------------------------------

    @server.tool(
        description="List the enabled scientific TaskTypes as a compact catalog. "
        "Call inspect_task for one TaskType's canonical inputs and parameters.",
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    def discover_tasks() -> types.CallToolResult:
        try:
            return _ok(services.discover_tasks())
        except McpError as error:
            return _error(error)

    @server.tool(
        description="Return one TaskType's canonical input roles, parameter vocabulary, "
        "and parameter JSON Schema (bounded).",
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    def inspect_task(ctx: Context, task_type: str) -> types.CallToolResult:
        try:
            # The canonical catalog and parameter schema are public reads, so
            # inspection stays public here too; execution is what is gated on an
            # authenticated, entitled, ready Runner.
            del ctx
            return _ok(services.inspect_task(_require_str(task_type, "task_type")))
        except McpError as error:
            return _error(error)

    @server.tool(
        description="Validate a prospective Task submission against the canonical security, "
        "contract, and admission rules without creating a Task. Inputs are base64-encoded.",
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    def preflight_task(
        ctx: Context,
        task_type: str,
        params: dict[str, Any] | None = None,
        inputs: list[dict[str, Any]] | None = None,
        workspace: dict[str, Any] | None = None,
    ) -> types.CallToolResult:
        try:
            principal = authenticate(ctx)
            payload = services.preflight_task(
                principal,
                task_type=_require_str(task_type, "task_type"),
                params=params,
                inputs=inputs,
                workspace=workspace,
            )
            return _ok(payload)
        except McpError as error:
            return _error(error)

    @server.tool(
        description="Submit a Task. Returns an opaque task_handle for tracking; the "
        "underlying REvoCompute Task id is never exposed. Identical resubmissions reuse "
        "the same canonical Task rather than duplicating work."
    )
    def submit_task(
        ctx: Context,
        task_type: str,
        params: dict[str, Any] | None = None,
        inputs: list[dict[str, Any]] | None = None,
        workspace: dict[str, Any] | None = None,
    ) -> types.CallToolResult:
        try:
            principal = authenticate(ctx)
            payload = services.submit_task(
                principal,
                task_type=_require_str(task_type, "task_type"),
                params=params,
                inputs=inputs,
                workspace=workspace,
                handle_store=_handles(),
                now=_now(),
            )
            return _ok(payload)
        except McpError as error:
            return _error(error)

    @server.tool(
        description="Return the lifecycle state of one owned Task by opaque task_handle. "
        "Requires authentication and ownership.",
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    def get_task_status(ctx: Context, task_handle: str) -> types.CallToolResult:
        try:
            principal = authenticate(ctx)
            mapping = _resolve(ctx, task_handle, kind="task")
            return _ok(services.get_task_status(principal, operation_id=mapping.operation_id))
        except McpError as error:
            return _error(error)

    @server.tool(
        description="Cancel one owned Task through the canonical cancellation path. "
        "Cross-user or unknown handles fail without revealing another user's Task."
    )
    def cancel_task(ctx: Context, task_handle: str) -> types.CallToolResult:
        try:
            principal = authenticate(ctx)
            mapping = _resolve(ctx, task_handle, kind="task")
            return _ok(services.cancel_task(principal, operation_id=mapping.operation_id))
        except McpError as error:
            return _error(error)

    @server.tool(
        description="Return the finalized ResultManifest projection for one owned Task: "
        "logical files and bounded artifact metadata. Results of an unfinished Task fail.",
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    def get_task_results(ctx: Context, task_handle: str) -> types.CallToolResult:
        try:
            principal = authenticate(ctx)
            mapping = _resolve(ctx, task_handle, kind="task")
            return _ok(services.get_task_results(principal, operation_id=mapping.operation_id))
        except McpError as error:
            return _error(error)

    @server.tool(
        description="Retrieve one published artifact by its ResultManifest path for an owned "
        "Task. A small artifact is inlined (bounded, base64); a larger artifact returns metadata "
        "only, never inline content and never a host path.",
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    def retrieve_artifact(
        ctx: Context, task_handle: str, artifact_path: str
    ) -> types.CallToolResult:
        try:
            principal = authenticate(ctx)
            mapping = _resolve(ctx, task_handle, kind="task")
            return _ok(
                services.retrieve_artifact(
                    principal,
                    operation_id=mapping.operation_id,
                    artifact_path=_require_str(artifact_path, "artifact_path"),
                    handle=mapping.handle,
                )
            )
        except McpError as error:
            return _error(error)

    # -- tools -------------------------------------------------------------

    @server.tool(
        description="List the canonical authenticated Tool catalog.",
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    def discover_tools(ctx: Context) -> types.CallToolResult:
        try:
            authenticate(ctx)
            return _ok(services.discover_tools())
        except McpError as error:
            return _error(error)

    @server.tool(
        description="Return one Tool's canonical contract and parameter JSON Schema (bounded).",
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    def inspect_tool(ctx: Context, tool_name: str) -> types.CallToolResult:
        try:
            authenticate(ctx)
            return _ok(services.inspect_tool(_require_str(tool_name, "tool_name")))
        except McpError as error:
            return _error(error)

    @server.tool(
        description="Invoke one canonical Tool. Returns an opaque tool_handle for tracking. "
        "Pass idempotency_key to make a retried call return the original ToolCall."
    )
    def call_tool(
        ctx: Context,
        tool_name: str,
        parameters: dict[str, Any] | None = None,
        inputs: list[dict[str, Any]] | None = None,
        artifact_references: list[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,
    ) -> types.CallToolResult:
        try:
            principal = authenticate(ctx)
            return _ok(
                services.call_tool(
                    principal,
                    tool_name=_require_str(tool_name, "tool_name"),
                    parameters=parameters,
                    inputs=inputs,
                    artifact_references=artifact_references,
                    idempotency_key=_optional_str(idempotency_key, "idempotency_key"),
                    handle_store=_handles(),
                    now=_now(),
                )
            )
        except McpError as error:
            return _error(error)

    @server.tool(
        description="Return the lifecycle state of one owned ToolCall by opaque tool_handle.",
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    def get_tool_call_status(ctx: Context, tool_handle: str) -> types.CallToolResult:
        try:
            principal = authenticate(ctx)
            mapping = _resolve(ctx, tool_handle, kind="tool_call")
            return _ok(services.get_tool_call_status(principal, operation_id=mapping.operation_id))
        except McpError as error:
            return _error(error)

    @server.tool(
        description="Return a finished ToolCall's bounded output manifest.",
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    def get_tool_results(ctx: Context, tool_handle: str) -> types.CallToolResult:
        try:
            principal = authenticate(ctx)
            mapping = _resolve(ctx, tool_handle, kind="tool_call")
            return _ok(services.get_tool_results(principal, operation_id=mapping.operation_id))
        except McpError as error:
            return _error(error)

    @server.tool(
        description="Retrieve one ToolCall output file, bounded and by manifest identity only.",
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    def retrieve_tool_output(
        ctx: Context, tool_handle: str, output_id: str, index: int = 0
    ) -> types.CallToolResult:
        try:
            principal = authenticate(ctx)
            mapping = _resolve(ctx, tool_handle, kind="tool_call")
            if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                raise McpError(INVALID_PARAMETERS, "index must be a non-negative integer")
            return _ok(
                services.retrieve_tool_output(
                    principal,
                    operation_id=mapping.operation_id,
                    output_id=_require_str(output_id, "output_id"),
                    index=index,
                    handle=mapping.handle,
                )
            )
        except McpError as error:
            return _error(error)

    # -- resources ---------------------------------------------------------

    @server.resource(
        _resources.SKILLS_URI,
        name="Agent workflow guide",
        description="The canonical REvoCompute agent workflow guide (/skills.md).",
        mime_type="text/markdown",
    )
    def skills_resource() -> str:
        return _resources.read_skills()

    @server.resource(
        _resources.TASK_SCHEMA_URI,
        name="Task parameter schema",
        description="The canonical parameter JSON Schema for one enabled TaskType.",
        mime_type="application/json",
    )
    def task_schema_resource(task_type: str) -> str:
        return _resources.read_task_schema(task_type)

    @server.resource(
        _resources.RESULT_MANIFEST_URI,
        name="Task result manifest",
        description="The owner-scoped ResultManifest summary for one opaque task handle.",
        mime_type="application/json",
    )
    def result_manifest_resource(ctx: Context, task_handle: str) -> str:
        principal = authenticate(ctx)
        return _resources.read_result_manifest(principal, task_handle)

    return server


def _handles() -> Any:
    from revocompute.mcp.handles import canonical_state

    return canonical_state().handles


def _resolve(ctx: Context, handle: Any, *, kind: str) -> Any:
    from revocompute.mcp.handles import canonical_state

    handle_value = _require_str(handle, "handle")
    principal = authenticate(ctx)
    mapping = canonical_state().handles.resolve(
        handle_value, user_id=principal.user_id, kind=kind, now=_now()
    )
    if mapping is None:
        from revocompute.mcp.errors import TASK_NOT_FOUND

        raise McpError(TASK_NOT_FOUND, "Unknown handle")
    return mapping


def _optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field)


def mcp_http_app() -> Any:
    """Return the ASGI application serving the MCP endpoint."""
    return build_server().streamable_http_app()


__all__ = ["SERVER_NAME", "SERVER_INSTRUCTIONS", "build_server", "mcp_http_app"]
