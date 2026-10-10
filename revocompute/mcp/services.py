# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Canonical-service projections for the MCP surface.

Every function here reads or writes REvoCompute state through the *same* module
the HTTP API and Web application use:

* discovery and parameter schemas come from ``revocompute.task_types`` and the
  owning ``task.yaml``-derived ``TaskType.schema``;
* lifecycle reads come from the canonical ``task_store``;
* results and artifacts come from the canonical ``StorageResolver`` and
  ``project_result_manifest``;
* the two request-bound mutating entry points are invoked through the canonical
  WSGI application in process (see :mod:`revocompute.mcp.context`).

Nothing in this module reimplements discovery, parameter defaults, JSON-Schema
validation, preflight, admission, entitlement, readiness, GPU credit, lifecycle,
ResultManifest interpretation, artifact ownership, or cancellation.
"""

from __future__ import annotations

import json
from typing import Any

from revocompute.mcp.bounds import (
    MAX_CATALOG_ENTRIES,
    MAX_INLINE_ARTIFACT_BYTES,
    MAX_RESULT_ENTRIES,
    MAX_SCHEMA_BYTES,
    bound_sequence,
)
from revocompute.mcp.errors import (
    ARTIFACT_NOT_FOUND,
    INVALID_PARAMETERS,
    McpError,
    RESULT_NOT_READY,
    TASK_NOT_CANCELLABLE,
    TASK_NOT_FOUND,
    classify,
)
from revocompute.mcp.handles import canonical_state
from revocompute.storage import PUBLICATION_AVAILABLE, PUBLICATION_NOT_FINALIZED

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_tasks() -> dict[str, Any]:
    """Return the compact, ordered catalog of enabled scientific TaskTypes.

    This is the same projection the Web catalog renders: ``list_types`` ordered
    by category, filtered by the canonical ``manage_db`` enablement flag.  Only
    the compact summary is returned -- the full parameter schema is a separate
    ``inspect_task`` call, so a catalog of many Runners stays small.
    """
    state = canonical_state()
    web = state.web
    from revocompute.task_types import list_categories, list_types

    manage_db = web.app.config.get("manage_db")
    entries = []
    for task_type in list_types():
        if manage_db is not None and manage_db.task_type_is_enabled(task_type.name) is False:
            continue
        entries.append(_catalog_entry(task_type))
    entries, truncated = bound_sequence(entries, MAX_CATALOG_ENTRIES)
    return {
        "version": 1,
        "task_types": entries,
        "truncated": truncated,
        "categories": [
            {"name": category.name, "label": category.label}
            for category in list_categories()
            if any(entry["category"] == category.name for entry in entries)
        ],
    }


def _catalog_entry(task_type: Any) -> dict[str, Any]:
    policy = task_type.runtime.access_policy
    return {
        "task_type": task_type.name,
        "display_name": task_type.display_name,
        "category": task_type.category,
        "summary": task_type.summary,
        "gpus": bool(task_type.gpus),
        "runtime_family": task_type.runtime.name,
        "restricted": policy is not None,
    }


def inspect_task(task_type: str) -> dict[str, Any]:
    """Return one canonical Task contract and its parameter vocabulary."""
    tt = _resolve_task_type(task_type)
    state = canonical_state()
    schema = _bounded_schema(tt.schema)
    return {
        "task_type": tt.name,
        "display_name": tt.display_name,
        "category": tt.category,
        "summary": tt.summary,
        "use_when": tt.use_when,
        "input_summary": tt.input_summary,
        "output_summary": tt.output_summary,
        "considerations": list(tt.considerations),
        "gpus": bool(tt.gpus),
        "runtime_family": tt.runtime.name,
        "restricted": tt.runtime.access_policy is not None,
        "inputs": [
            {
                "role": role.name,
                "title": role.title,
                "type": role.type,
                "formats": list(role.formats),
                "cardinality": {"min": role.minimum, "max": role.maximum},
                "description": role.description,
            }
            for role in tt.inputs
        ],
        "parameters": [
            {
                "name": parameter.name,
                "type": parameter.type,
                "label": parameter.label or parameter.name.replace("_", " ").title(),
                "description": parameter.description,
                "default": parameter.default,
                "required": parameter.required,
                "choices": list(parameter.choices),
                "minimum": parameter.minimum,
                "maximum": parameter.maximum,
                "unit": parameter.unit,
            }
            for parameter in tt.params
        ],
        "parameter_schema": schema,
        "parameter_schema_truncated": schema.get("x-truncated", False),
        "citations": [citation.projection() for citation in tt.citations],
        "max_request_bytes": state.web.app.config.get("MAX_CONTENT_LENGTH"),
    }


def _bounded_schema(schema: Any) -> dict[str, Any]:
    """Return the canonical JSON Schema, bounded for a model context."""
    encoded = json.dumps(schema, ensure_ascii=True, sort_keys=True)
    if len(encoded) <= MAX_SCHEMA_BYTES:
        return dict(schema) if isinstance(schema, dict) else {"schema": schema}
    return {"x-truncated": True, "schema_digest": _digest(encoded), "schema_bytes": len(encoded)}


def _digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _resolve_task_type(task_type: Any) -> Any:
    from revocompute.task_types import get as _get_task_type
    from revocompute.task_types import list_types

    if not isinstance(task_type, str) or not task_type.strip():
        raise McpError(INVALID_PARAMETERS, "task_type is required")
    name = task_type.strip().lower()
    try:
        tt, _runner = _get_task_type(name)
    except KeyError:
        raise McpError(TASK_NOT_FOUND, f"Unknown task type: {name!r}") from None
    state = canonical_state()
    manage_db = state.web.app.config.get("manage_db")
    if manage_db is not None and manage_db.task_type_is_enabled(tt.name) is False:
        raise McpError(TASK_NOT_FOUND, f"Task type {tt.name!r} is not enabled")
    if tt.name not in {item.name for item in list_types()}:
        raise McpError(TASK_NOT_FOUND, f"Task type {tt.name!r} is not available")
    return tt


# ---------------------------------------------------------------------------
# Preflight / submission
# ---------------------------------------------------------------------------


def preflight_task(
    principal: Any,
    *,
    task_type: str,
    params: dict[str, Any] | None,
    inputs: Any,
    workspace: Any = None,
) -> dict[str, Any]:
    """Run the canonical preflight for one TaskType.

    The canonical preflight handler runs the same security, contract, and
    admission phases as a real submission, so this is a projection of it -- not
    a second validator.
    """
    from revocompute.mcp.context import build_submission_data, call_canonical, encode_multipart
    from revocompute.mcp.bounds import MAX_SUBMISSION_INPUT_BYTES

    tt = _resolve_task_type(task_type)
    body = build_submission_data(
        task_type=tt.name,
        params=params,
        inputs=inputs,
        workspace=workspace,
        max_total_bytes=MAX_SUBMISSION_INPUT_BYTES,
    )
    response = call_canonical(
        principal,
        "POST",
        f"/compute/api/preflight/{tt.name}",
        data=encode_multipart(body),
    )
    if response.status < 400:
        payload = response.body if isinstance(response.body, dict) else {}
        return {"valid": True, **_compact_preflight(payload)}
    error = classify(response.body, status=response.status)
    raise error


def _compact_preflight(payload: dict[str, Any]) -> dict[str, Any]:
    admission = payload.get("admission") if isinstance(payload.get("admission"), dict) else {}
    return {
        "admission": {
            "allowed": bool(admission.get("allowed")),
            "runner_ready": admission.get("runner_ready"),
            "infrastructure_ready": admission.get("infrastructure_ready"),
            "infrastructure_status": admission.get("infrastructure_status"),
            "scheduler_capacity": admission.get("scheduler_capacity"),
            "gpu_capacity": admission.get("gpu_capacity"),
            "gpu_credit_sufficient": admission.get("gpu_credit_sufficient"),
            "gpu_credit_remaining_seconds": admission.get("gpu_credit_remaining_seconds"),
        },
        "normalized_params": payload.get("normalized_params", {}),
    }


def submit_task(
    principal: Any,
    *,
    task_type: str,
    params: dict[str, Any] | None,
    inputs: Any,
    workspace: Any = None,
    handle_store: Any,
    now: float,
) -> dict[str, Any]:
    """Submit a Task through the canonical application and mint an opaque handle.

    The opaque handle is minted *before* the canonical call and bound only after
    it returns an identity, so a canonical rejection never leaves a resolvable
    handle behind.  Idempotency is the canonical content-derived Task ID plus
    the canonical preparation claim: an identical resubmission answers with the
    same Task, so a retried MCP call cannot duplicate scientific work.
    """
    from revocompute.mcp.bounds import MAX_SUBMISSION_INPUT_BYTES
    from revocompute.mcp.context import build_submission_data, call_canonical, encode_multipart
    from revocompute.mcp.handles import KIND_TASK

    tt = _resolve_task_type(task_type)
    body = build_submission_data(
        task_type=tt.name,
        params=params,
        inputs=inputs,
        workspace=workspace,
        max_total_bytes=MAX_SUBMISSION_INPUT_BYTES,
    )
    handle = handle_store.mint(user_id=principal.user_id, kind=KIND_TASK, now=now)
    response = call_canonical(
        principal,
        "POST",
        "/compute/api/post",
        data=encode_multipart(body),
    )
    if response.status >= 400:
        handle_store.revoke(handle, user_id=principal.user_id)
        raise classify(response.body, status=response.status)
    task_id = response.task_id
    if not task_id:
        handle_store.revoke(handle, user_id=principal.user_id)
        raise McpError(RESULT_NOT_READY, "Canonical submission did not return a Task identity")
    handle_store.bind(handle, task_id, now=now)
    payload = response.body if isinstance(response.body, dict) else {}
    return {
        "task_handle": handle,
        "status": str(payload.get("status") or "pending"),
        "task_type": tt.name,
        "status_url": None,
        "results_available": False,
    }


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def _owned_task(principal: Any, operation_id: str) -> dict[str, Any]:
    """Return a Task the caller owns, or fail closed without existence leakage."""
    from revocompute.task_runtime import _normalize_task_id

    state = canonical_state()
    task_id = _normalize_task_id(operation_id)
    if task_id is None:
        raise McpError(TASK_NOT_FOUND, "Unknown task handle")
    task = state.web.task_store.get_task(task_id)
    if task is None:
        raise McpError(TASK_NOT_FOUND, "Unknown task handle")
    owner = str(task.get("submitted_by_user_id")) == str(principal.user_id)
    if not owner:
        raise McpError(TASK_NOT_FOUND, "Unknown task handle")
    return task


def get_task_status(principal: Any, *, operation_id: str) -> dict[str, Any]:
    """Project one owned Task's canonical lifecycle state."""
    from revocompute.task_runtime import _progress_summary, _sanitize_task_error

    state = canonical_state()
    task = _owned_task(principal, operation_id)
    status = str(task.get("status") or "").strip().lower()
    summary = _progress_summary(task) or {}
    payload: dict[str, Any] = {
        "status": status,
        "terminal": status in state.web.task_store.STOP_POLLING_STATUSES,
        "task_type": task.get("task_type"),
        "submitted_at": _iso(task.get("uploaded_at")),
        "finished_at": _iso(task.get("finished_at")),
        "walltime_seconds": task.get("walltime"),
        "progress": summary.get("progress"),
        "outcome": summary.get("outcome"),
        "results_available": _manifest_available(task),
        "cancellable": status in {"pending", "queued", "running"},
    }
    error = _sanitize_task_error(task, task.get("error"))
    if error:
        from revocompute.mcp.bounds import truncate_detail

        payload["error"] = truncate_detail(error)
    return payload


def cancel_task(principal: Any, *, operation_id: str) -> dict[str, Any]:
    """Cancel one owned Task through the canonical cancellation path.

    The capability check (ownership, cancellability, atomic status transition,
    worker-side resource teardown) belongs entirely to the canonical handler;
    this function only projects its answer.
    """
    from revocompute.mcp.context import call_canonical

    task = _owned_task(principal, operation_id)
    task_id = str(task["md5sum"])
    response = call_canonical(principal, "POST", f"/compute/api/cancel/{task_id}")
    if response.status >= 400:
        error = classify(response.body, status=response.status)
        if error.error_class == INVALID_PARAMETERS:
            error = McpError(TASK_NOT_CANCELLABLE, error.message)
        raise error
    return {"status": "cancelled"}


def get_task_results(principal: Any, *, operation_id: str) -> dict[str, Any]:
    """Project the canonical finalized ResultManifest for one owned Task.

    A Task whose results are not finalized is ``RESULT_NOT_READY`` rather than a
    partial manifest, so an agent never mistakes an unfinished run for a
    complete one.
    """
    task = _owned_task(principal, operation_id)
    status = str(task.get("status") or "").strip().lower()
    if status not in {"finished", "failed"}:
        raise McpError(RESULT_NOT_READY, f"Results are not ready (task status: {status or 'unknown'})")
    body = _canonical_result_body(principal, task)
    artifacts = body.get("artifacts") if isinstance(body.get("artifacts"), list) else []
    logical = body.get("result", {}).get("files", {}) if isinstance(body.get("result"), dict) else {}
    bounded_artifacts, artifacts_truncated = bound_sequence(artifacts, MAX_RESULT_ENTRIES)
    result_files, files_truncated = bound_result_files(logical)
    work_items = body.get("work_items") if isinstance(body.get("work_items"), list) else None
    bounded_work_items, work_items_truncated = (
        bound_sequence(work_items, MAX_RESULT_ENTRIES) if work_items else (None, False)
    )
    return {
        "status": status,
        "terminal": True,
        "error": body.get("error"),
        "result_files": result_files,
        "result_files_truncated": files_truncated,
        "artifacts": [
            {
                "path": artifact.get("path"),
                "size": artifact.get("size"),
                "media_type": artifact.get("media_type"),
                "role": artifact.get("role"),
                "capability": artifact.get("capability"),
            }
            for artifact in bounded_artifacts
        ],
        "artifacts_truncated": artifacts_truncated,
        "archive_ready": bool(body.get("archive", {}).get("ready")),
        "work_items": bounded_work_items,
        "work_items_truncated": work_items_truncated,
    }


def bound_result_files(logical: Any) -> tuple[dict[str, Any], bool]:
    """Bound the logical files of one result manifest, reporting truncation.

    The canonical manifest can hold far more files than a model context should
    carry (an upstream bound allows up to 100k work items), so both the number
    of file ids and the entries per id are bounded and *flagged* -- a bounded
    result must never look complete.
    """
    if not isinstance(logical, dict):
        return {}, False
    truncated = len(logical) > MAX_RESULT_ENTRIES
    bounded: dict[str, Any] = {}
    for file_id, items in list(logical.items())[:MAX_RESULT_ENTRIES]:
        entries = items if isinstance(items, list) else []
        if len(entries) > MAX_RESULT_ENTRIES:
            truncated = True
        bounded[file_id] = [
            {
                "name": item.get("name"),
                "size": item.get("size"),
                "media_type": item.get("media_type"),
                "role": item.get("role"),
                "capability": item.get("capability"),
            }
            for item in entries[:MAX_RESULT_ENTRIES]
        ]
    return bounded, truncated


def retrieve_artifact(
    principal: Any,
    *,
    operation_id: str,
    artifact_path: str,
    handle: str | None = None,
    max_inline_bytes: int = MAX_INLINE_ARTIFACT_BYTES,
) -> dict[str, Any]:
    """Retrieve one published artifact, bounded and never by host path.

    Resolution, publication, containment, hash/size verification, and role-based
    visibility all belong to the canonical resolver; this function inlines bytes
    only when the artifact is small enough for a model context.

    Authorization still runs through the canonical artifact route (so ownership
    and role visibility are the canonical rules), but the bytes are read from the
    resolver's already-verified physical file rather than the route's response
    body.  The route answers an *empty* body plus ``X-Accel-Redirect`` in the
    shipped ``nginx`` download mode and content-negotiates otherwise, so a
    response-body read silently returned empty content for every non-text
    artifact; the verified file is the same content in every mode.
    """
    from urllib.parse import quote

    from revocompute.mcp.context import call_canonical

    task = _owned_task(principal, operation_id)
    task_id = str(task["md5sum"])
    if not isinstance(artifact_path, str) or not artifact_path.strip():
        raise McpError(INVALID_PARAMETERS, "artifact_path is required")
    normalized = artifact_path.strip()
    if _looks_like_host_path(normalized):
        raise McpError(ARTIFACT_NOT_FOUND, "Artifact not found")
    _require_published_result(principal, task)
    resolved = canonical_state().web.app.config["storage_resolver"].resolve_artifact(task, normalized)
    if resolved is None:
        raise McpError(ARTIFACT_NOT_FOUND, "Artifact not found")
    size = int(resolved.get("size") or 0)
    encoded = quote(normalized, safe="/")
    if size > max_inline_bytes:
        return {
            "artifact_path": normalized,
            "size": size,
            "media_type": resolved.get("media_type"),
            "role": resolved.get("role"),
            "inline": False,
            "truncated": False,
            "content_base64": None,
            "task_handle": handle,
            "note": "Artifact exceeds the inline context limit and is not returned inline. Fetch it out of "
            "band through the canonical results API; no host, container, or object-store path is exposed.",
        }
    # Authorize + gate on publication through the canonical artifact route (so
    # ownership, role visibility, and *publication* are its rules), but read the
    # bytes from the resolver's already-verified descriptor rather than the
    # route's response body.  The route answers an empty body plus
    # ``X-Accel-Redirect`` in the shipped ``nginx`` download mode and
    # content-negotiates otherwise, so a response-body read silently returned
    # empty content; the verified descriptor is the same content in every mode,
    # and a quarantined result is refused by the route before any bytes are read.
    response = call_canonical(
        principal,
        "GET",
        f"/compute/api/results/{task_id}/artifacts/{encoded}",
        query_string="download=0",
    )
    if response.status >= 400:
        raise classify(response.body, status=response.status)
    raw = _read_verified_stream(resolved.get("verified_stream"), size)
    import base64

    return {
        "artifact_path": normalized,
        "size": size,
        "media_type": resolved.get("media_type"),
        "role": resolved.get("role"),
        "inline": True,
        "truncated": False,
        "content_base64": base64.b64encode(raw).decode("ascii"),
    }


def _read_verified_stream(stream: Any, expected_size: int) -> bytes:
    """Read a verified published descriptor, never beyond its published size.

    The descriptor is the one whose size and SHA-256 the canonical resolver
    checked against the manifest, so the bytes are read from the verified inode
    rather than by resolving the artifact's name a second time -- a name that
    could by then resolve to a different file.  The caller must close it.
    """
    if stream is None:
        raise McpError(ARTIFACT_NOT_FOUND, "Artifact not found")
    try:
        data = stream.read(expected_size)
    except OSError:
        raise McpError(ARTIFACT_NOT_FOUND, "Artifact not found") from None
    finally:
        stream.close()
    if len(data) != expected_size:
        # The file changed after verification: fail closed rather than serve a
        # different byte count than the manifest (and the caller) was told.
        raise McpError(ARTIFACT_NOT_FOUND, "Artifact not found")
    return data


def _looks_like_host_path(value: str) -> bool:
    return value.startswith("/") or value.startswith("\\") or ":" in value.split("/")[0]


def _canonical_result_body(principal: Any, task: dict[str, Any]) -> dict[str, Any] | None:
    """The canonical result projection for one owned Task, or a refusal.

    The canonical results route owns publication: it answers with the manifest
    projection only for a result Core anchored and can still verify, and with
    the bounded publication *state* plus its reason for anything else.  A
    non-200 answer is therefore the publication decision, not a transport
    hiccup, so it is raised as ``RESULT_NOT_READY`` carrying that state -- an
    agent sees "quarantined, and here is why" rather than a bare not-ready.
    Only a result that never finalized (the ordinary not-yet case) keeps the
    plain message.
    """
    from revocompute.mcp.context import call_canonical

    task_id = str(task["md5sum"])
    response = call_canonical(principal, "GET", f"/compute/api/results/{task_id}")
    if response.status == 200 and isinstance(response.body, dict):
        return response.body
    body = response.body if isinstance(response.body, dict) else {}
    publication = str(body.get("result_publication") or "")
    if publication and publication != PUBLICATION_NOT_FINALIZED:
        raise McpError(
            RESULT_NOT_READY,
            str(body.get("message") or "Result manifest is not published"),
            detail=publication,
        )
    if response.status == 404:
        raise McpError(RESULT_NOT_READY, "Result manifest is not published")
    raise classify(body, status=response.status)


def _require_published_result(principal: Any, task: dict[str, Any]) -> None:
    """Refuse a result the canonical results route refuses.

    One publication authority: the exact call the Web and HTTP surfaces make.
    The MCP surface therefore never answers a quarantined, unanchored, replaced,
    or unverifiable result with bytes, and never paraphrases the canonical
    reason.
    """
    _canonical_result_body(principal, task)


def _manifest_available(task: dict[str, Any]) -> bool:
    """Report whether the canonical publication reader will serve this result.

    Answered from the canonical resolver's own verified publication read -- the
    same authority the results route, the archive request, and the download
    route consult -- so a status poll neither builds a result projection nor
    advertises a result the canonical surface quarantines.
    """
    resolver = canonical_state().web.app.config["storage_resolver"]
    try:
        return resolver.publication_state(task) == PUBLICATION_AVAILABLE
    except (AttributeError, ValueError):
        return False


def _iso(value: Any) -> str | None:
    from datetime import datetime, timezone

    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (OSError, OverflowError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def discover_tools() -> dict[str, Any]:
    """Return the compact canonical Tool catalog."""
    state = canonical_state()
    from revocompute.tool_types import public_tool

    registry = state.web.tool_registry
    entries = []
    for tool in registry.list():
        projection = public_tool(tool)
        entries.append(
            {
                "tool": projection["id"],
                "display_name": projection["display_name"],
                "summary": projection["summary"],
                "runtime_family": projection["runtime_family"],
                "inputs": projection["inputs"],
                "outputs": projection["outputs"],
                "available": tool.runtime.image.is_file(),
            }
        )
    entries, truncated = bound_sequence(entries, MAX_CATALOG_ENTRIES)
    return {"tools": entries, "truncated": truncated}


def inspect_tool(tool_name: str) -> dict[str, Any]:
    """Return one canonical Tool contract and its parameter schema."""
    state = canonical_state()
    from revocompute.tool_types import public_tool

    if not isinstance(tool_name, str) or not tool_name.strip():
        raise McpError(INVALID_PARAMETERS, "tool_name is required")
    try:
        tool = state.web.tool_registry.get(tool_name.strip())
    except KeyError:
        raise McpError(TASK_NOT_FOUND, f"Unknown Tool: {tool_name!r}") from None
    schema = _bounded_schema(tool.schema)
    return {
        **public_tool(tool),
        "parameter_schema": schema,
        "parameter_schema_truncated": schema.get("x-truncated", False),
        "available": tool.runtime.image.is_file(),
    }


def get_tool_call_status(principal: Any, *, operation_id: str) -> dict[str, Any]:
    """Project one owned ToolCall's canonical state."""
    state = canonical_state()
    from revocompute.tool_calls import normalize_tool_call_id

    call_id = normalize_tool_call_id(operation_id)
    if call_id is None:
        raise McpError(TASK_NOT_FOUND, "Unknown tool handle")
    call = state.web.tool_calls.get_owned(call_id, principal.user_id)
    if call is None:
        raise McpError(TASK_NOT_FOUND, "Unknown tool handle")
    return {
        "status": str(call.get("status")),
        "tool": call.get("tool_type"),
        "created_at": call.get("created_at"),
        "started_at": call.get("started_at"),
        "finished_at": call.get("finished_at"),
        "expires_at": call.get("expires_at"),
        "error_class": call.get("error_class"),
    }


def get_tool_results(principal: Any, *, operation_id: str) -> dict[str, Any]:
    """Return a finished ToolCall's bounded canonical result manifest."""
    state = canonical_state()
    from revocompute.tool_calls import normalize_tool_call_id

    call_id = normalize_tool_call_id(operation_id)
    if call_id is None:
        raise McpError(TASK_NOT_FOUND, "Unknown tool handle")
    call = state.web.tool_calls.get_owned(call_id, principal.user_id)
    if call is None:
        raise McpError(TASK_NOT_FOUND, "Unknown tool handle")
    status = str(call.get("status"))
    if status != "finished":
        raise McpError(RESULT_NOT_READY, f"Tool result is not ready (status: {status})")
    raw = call.get("result_manifest_json")
    manifest = json.loads(raw) if raw else {}
    outputs = manifest.get("outputs", {}) if isinstance(manifest, dict) else {}
    return {
        "tool": call.get("tool_type"),
        "outputs": {
            output_id: [
                {"path": item.get("path"), "format": item.get("format"), "size": item.get("size")}
                for item in items
            ]
            for output_id, items in list(outputs.items())[:MAX_RESULT_ENTRIES]
        },
    }


def call_tool(
    principal: Any,
    *,
    tool_name: str,
    parameters: dict[str, Any] | None,
    inputs: Any,
    artifact_references: list[dict[str, Any]] | None = None,
    idempotency_key: str | None = None,
    handle_store: Any,
    now: float,
) -> dict[str, Any]:
    """Invoke one canonical Tool through the canonical call route.

    Tool admission (per-user and global active-call limits, storage share,
    parameter JSON-Schema validation, input role validation, workspace
    materialization, process-isolated execution) belongs entirely to the
    canonical handler.  The opaque handle is minted first and bound only after
    the canonical call returns an identity; the canonical ``Idempotency-Key``
    remains the deduplication source of truth for a retried call.
    """
    from revocompute.mcp.bounds import MAX_SUBMISSION_INPUT_BYTES
    from revocompute.mcp.context import call_canonical, decode_inputs, encode_multipart
    from revocompute.mcp.handles import KIND_TOOL_CALL

    state = canonical_state()
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise McpError(INVALID_PARAMETERS, "tool_name is required")
    name = tool_name.strip()
    try:
        state.web.tool_registry.get(name)
    except KeyError:
        raise McpError(TASK_NOT_FOUND, f"Unknown Tool: {name!r}") from None

    entries = decode_inputs(inputs, max_total_bytes=MAX_SUBMISSION_INPUT_BYTES)
    roles = [role for role, _payload in entries]
    parts = [payload for _role, payload in entries]

    refs: list[str] = []
    ref_roles: list[str] = []
    for index, item in enumerate(artifact_references or []):
        if not isinstance(item, dict):
            raise McpError(INVALID_PARAMETERS, f"artifact_references[{index}] must be an object")
        expression = item.get("reference")
        role = item.get("role")
        if not isinstance(expression, str) or not expression:
            raise McpError(INVALID_PARAMETERS, f"artifact_references[{index}].reference is required")
        if not isinstance(role, str) or not role:
            raise McpError(INVALID_PARAMETERS, f"artifact_references[{index}].role is required")
        refs.append(expression)
        ref_roles.append(role)

    body: dict[str, Any] = {
        "parameters": json.dumps(parameters or {}, ensure_ascii=True, sort_keys=True),
        "file_roles": roles,
        "artifact_roles": ref_roles,
        "artifact_references": refs,
        "files": [(item, item[1], item[2]) for item in parts],
    }
    for key in ("file_roles", "artifact_roles", "artifact_references"):
        if not body[key]:
            body.pop(key)
    if not parts:
        body.pop("files")

    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    handle = handle_store.mint(user_id=principal.user_id, kind=KIND_TOOL_CALL, now=now)
    response = call_canonical(
        principal,
        "POST",
        f"/compute/api/tools/{name}/call",
        data=encode_multipart(body),
        extra_headers=headers,
    )
    if response.status >= 400:
        handle_store.revoke(handle, user_id=principal.user_id)
        raise classify(response.body, status=response.status)
    payload = response.body if isinstance(response.body, dict) else {}
    call_id = payload.get("tool_call_id")
    if not call_id:
        handle_store.revoke(handle, user_id=principal.user_id)
        raise McpError(RESULT_NOT_READY, "Canonical Tool call did not return a ToolCall identity")
    handle_store.bind(handle, str(call_id), now=now)
    return {
        "tool_handle": handle,
        "status": str(payload.get("status") or "queued"),
        "tool": name,
    }


def retrieve_tool_output(
    principal: Any,
    *,
    operation_id: str,
    output_id: str,
    index: int = 0,
    handle: str | None = None,
    max_inline_bytes: int = MAX_INLINE_ARTIFACT_BYTES,
) -> dict[str, Any]:
    """Retrieve one finished ToolCall output, bounded and never by host path.

    Ownership and output identity come from the canonical ToolCall record; the
    bytes are read from the call's isolated workspace, whose containment the
    canonical workspace object owns.  The content is not read through the
    download route, so neither the shipped ``nginx`` download mode nor a
    content-negotiated media type can turn an inlined payload into empty bytes.
    """
    import base64
    from pathlib import Path

    state = canonical_state()
    from revocompute.tool_calls import normalize_tool_call_id

    call_id = normalize_tool_call_id(operation_id)
    if call_id is None:
        raise McpError(TASK_NOT_FOUND, "Unknown tool handle")
    call = state.web.tool_calls.get_owned(call_id, principal.user_id)
    if call is None:
        raise McpError(TASK_NOT_FOUND, "Unknown tool handle")
    if str(call.get("status")) != "finished":
        raise McpError(RESULT_NOT_READY, "Tool output is not ready")
    raw_manifest = call.get("result_manifest_json")
    manifest = json.loads(raw_manifest) if raw_manifest else {}
    outputs = manifest.get("outputs", {}) if isinstance(manifest, dict) else {}
    items = outputs.get(output_id)
    if not isinstance(items, list) or not items:
        raise McpError(ARTIFACT_NOT_FOUND, "Tool output not found")
    if index < 0 or index >= len(items):
        raise McpError(ARTIFACT_NOT_FOUND, "Tool output not found")
    item = items[index]
    size = int(item.get("size") or 0)
    if size > max_inline_bytes:
        return {
            "output_id": output_id,
            "index": index,
            "size": size,
            "format": item.get("format"),
            "inline": False,
            "truncated": False,
            "content_base64": None,
            "tool_handle": handle,
            "note": "Tool output exceeds the inline context limit and is not returned inline. Fetch it out "
            "of band; no host, container, or object-store path is exposed.",
        }
    # Resolve inside the call's isolated workspace; the manifest names a relative
    # path, and containment keeps it there.
    workspace_root = Path(state.web.app.config["tool_workspace"].call_root(call_id)) / "output"
    root_resolved = workspace_root.resolve()
    candidate = (workspace_root / str(item.get("path") or "")).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise McpError(ARTIFACT_NOT_FOUND, "Tool output not found")
    payload = _read_verified_bytes(str(candidate), size)
    return {
        "output_id": output_id,
        "index": index,
        "size": size,
        "format": item.get("format"),
        "inline": True,
        "truncated": False,
        "content_base64": base64.b64encode(payload).decode("ascii"),
    }
