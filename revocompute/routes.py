# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""HTTP route handlers for the REvoCompute server.

All ``@app.route`` decorators live here.  The module is imported by
``revocompute.__init__`` *after* ``revocompute.app`` has
created the Flask ``app``, so the decorators register against an
already-initialised application.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import mimetypes
import ntpath
import os
import re
import shutil
import time
import unicodedata
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from celery.result import AsyncResult
from flask import (
    Response,
    abort,
    current_app,
    g,
    jsonify,
    make_response,
    redirect,
    request,
    send_from_directory,
    url_for,
)
from pydantic import ValidationError
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.http import parse_range_header
from revocompute.admin_pages import register_admin_pages
from revocompute.access_control import (
    authorize,
    policy_state,
    project_effective_entitlements,
)
from revocompute.admission import invalidate_submission_attestations, resolve_submission_readiness
from revocompute import access_guard
from revocompute.app import (
    CONFIG,
    ENABLE_REGISTER,
    TOOL_CONFIG,
    _client_country,
    _client_ip,
    _delete_task_artifacts,
    _is_admin_user,
    _is_binary_file,
    _is_deleted_status,
    _request_metadata,
    _revoke_celery_task,
    _task_access_allowed,
    _task_artifact_access_allowed,
    _task_full_results_allowed,
    _task_id_for_upload,
    _task_mutation_allowed,
    _task_not_found,
    _task_zip_download_name,
    app,
    celery,
    tool_calls,
    tool_registry,
    tool_workspace,
)
from revocompute.auth import (
    _DUMMY_PASSWORD_HASH,
    UserDatabase,
    _env_str,
    _is_account_blocked,
    generate_captcha,
    generate_token,
    load_current_user,
    login_required,
    optional_user,
    require_bearer_auth,
    require_web_login,
    send_approval_email,
    send_password_reset_email,
    send_rejection_email,
    send_verification_email,
    validate_captcha,
    validate_email_token,
    validate_reset_token,
)
from revocompute.input_validators import validate_input_file, validate_logical_input
from revocompute.input_validators.isolated_validation import VALIDATOR_RESOURCE_LIMIT_ERROR
from revocompute.input_validators.json_file import json_error_message, parse_bounded_json
from revocompute.ingress_security import (
    ValidationReceipt,
    canonical_relative_path,
    event_for_code,
    phase_for_code,
)
from revocompute.ndarray import ArrayAccessError, MAX_PROJECTION_ELEMENTS, read_array_projection
from revocompute.db import GPUCreditUnavailableError, TaskIdReservedError
from revocompute.operational_events import emit_event
from revocompute.ratelimit import rate_limit
from revocompute import resource_lifecycle
from revocompute import resource_ledger as rloan
from revocompute.resource_ledger import (
    AdmissionReason,
    LedgerReason,
    ReservationReason,
    SECONDS_PER_CREDIT,
)
from revocompute.resource_observations import observations_for_guidance
from revocompute.resource_policy import (
    GLOBAL_RESOURCE_KEYS,
    ResourceValidationError,
    normalize_resource_value,
    resolve_submission_resources,
)
from revocompute.result_projection import project_result_manifest
from revocompute.storage import (
    PUBLICATION_ANCHOR_INVALID,
    PUBLICATION_ANCHOR_MISMATCH,
    PUBLICATION_AVAILABLE,
    PUBLICATION_MANIFEST_MISSING,
    PUBLICATION_MANIFEST_UNREADABLE,
    PUBLICATION_NOT_FINALIZED,
    PUBLICATION_UNANCHORED,
)
from revocompute.result_storyboard import ResultContractError, expected_file_tree, runner_root, storyboard_declaration
from revocompute import runtime_bundle
from revocompute.schemas import (
    AccessDecisionRequest,
    AccessRequestCreate,
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    BatchUserRequest,
    EntitlementGrantRequest,
    ForgotPasswordRequest,
    GPUCreditAllowanceRequest,
    GPUCreditAdjustmentRequest,
    GPUCreditResetRequest,
    LoginRequest,
    OperatorJobRequest,
    OperatorPlanRequest,
    PreflightAdmission,
    PreflightFinding,
    PreflightPhase,
    RegisterRequest,
    ResetPasswordRequest,
    TaskSubmissionRequest,
    TaskPreflightResult,
    UpdateCurrentUserRequest,
    UserResponse,
    VerifyEmailRequest,
)
from revocompute.task_runtime import (
    _cleanup_task_workspace,
    _finalize_failed_results,
    _get_task_type,
    _local_user_identity,
    _normalize_task_id,
    _path_is_within,
    _progress_summary,
    _safe_join,
    _sanitize_task_error,
    _task_zip_path,
    build_results_archive,
    cancel_compute_resources,
    reconcile_slurm_allocations,
    run_compute_task,
    task_store,
)
from revocompute.task_types import default_task_type, get as get_task_type
from revocompute.task_types import (
    declared_entitlements,
    get_policy,
    iter_capabilities,
    list_categories,
    list_policies,
    list_types,
    workspace_plugin_descriptor,
)
from revocompute.workspace_contracts import WorkspaceValidationError, normalize_capability, validate_capability
from revocompute.task_types import workspace_backend
from revocompute.tool_calls import ToolAdmissionError, new_tool_call_id, normalize_tool_call_id
from revocompute.tool_types import canonical_parameters, public_tool
from revocompute.tool_workspace import ToolWorkspaceError
from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema import validate as validate_json_schema
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

MAX_TABLE_PAGE_BYTES = 8 * 1024 * 1024
MAX_TABLE_CELL_BYTES = 16 * 1024
_TABLE_PAGE_ENVELOPE_BYTES = 512
# Read a verified descriptor in bounded chunks; no read is ever sized by the
# artifact, so a large download streams instead of issuing one huge read.
_STREAM_CHUNK_BYTES = 64 * 1024

# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@app.route("/", methods=["GET"])
def index_page():
    return _serve_frontend_entry()


@app.route("/api-docs", methods=["GET"])
def api_docs_page():
    return _serve_frontend_entry()


@app.route("/openapi.json", methods=["GET"])
def openapi_spec():
    return send_from_directory(app.static_folder, "openapi.json", mimetype="application/json")


@app.route("/skills.md", methods=["GET"])
def agent_skills_document():
    """Serve the stable anonymous agent API bootstrap guide."""
    response = send_from_directory(app.static_folder, "skills.md", mimetype="text/markdown")
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@app.route("/runners", methods=["GET"])
@optional_user
def runners_page():
    return _serve_frontend_entry()


@app.route("/runners/<name>", methods=["GET"])
@optional_user
def runner_detail_page(name: str):
    return _serve_frontend_entry()


@app.route("/compute/health", methods=["GET"])
def health():
    """Liveness probe — unauthenticated, empty 200 when the process answers."""
    return "", 200


@app.route("/compute/api/infrastructure", methods=["GET"])
@login_required
def infrastructure_readiness():
    """Return safe current infrastructure evidence, with details for admins."""
    service = current_app.config["infrastructure_readiness"]
    return jsonify(service.report(admin=_is_admin_user())), 200


@app.route("/compute/api/auth/admin/infrastructure/refresh", methods=["POST"])
@login_required
def refresh_infrastructure_readiness():
    """Run every bounded readiness probe and return detailed evidence."""
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    service = current_app.config["infrastructure_readiness"]
    return jsonify(service.report(force=True, admin=True)), 200


@app.route("/compute/login", methods=["GET"])
def login_page():
    return_to = request.args.get("return_to", "")
    if not _safe_return_target(return_to):
        return_to = url_for("task_dashboard")
    if load_current_user() is not None:
        return redirect(return_to)
    return _serve_frontend_entry()


def _safe_return_target(target: str) -> bool:
    """Accept only a same-origin absolute path, including after URL decoding."""
    decoded = target
    for _ in range(3):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded
    try:
        parsed = urlsplit(decoded)
    except ValueError:
        return False
    return bool(
        decoded.startswith("/")
        and not decoded.startswith("//")
        and not parsed.scheme
        and not parsed.netloc
        and "\\" not in decoded
        and all(ord(character) >= 32 and ord(character) != 127 for character in decoded)
    )


@app.route("/compute/terms", methods=["GET"])
def terms_page():
    return _serve_frontend_entry()


@app.route("/compute/register", methods=["GET"])
def register_page():
    if load_current_user() is not None:
        return redirect(url_for("task_dashboard"))
    return _serve_frontend_entry()


@app.route("/compute/create_task", methods=["GET"])
@login_required
def create_task():
    return _serve_frontend_entry(private=True)


# Explicit legacy browser entry points whose canonical destinations are known.
# Temporary redirects (302) during the migration; no wildcard forwarding exists,
# and the set is closed to these two paths.
# These routes need no login guard: the destination enforces its own boundary,
# and the redirect target is a fixed literal, never request-derived.
@app.route("/PSSM_GREMLIN/dashboard", methods=["GET"])
def legacy_pssm_gremlin_dashboard():
    return redirect("/compute/dashboard", code=302)


@app.route("/PSSM_GREMLIN/create_task", methods=["GET"])
def legacy_pssm_gremlin_create_task():
    return redirect("/compute/create_task?task_type=gremlin", code=302)


@app.route("/compute/profile", methods=["GET"])
@login_required
def profile_page():
    return _serve_frontend_entry(private=True)


@app.route("/compute/api/workspace/plugins/<owner>/<plugin_id>", methods=["GET"])
@optional_user
def workspace_plugin_descriptor_api(owner: str, plugin_id: str):
    """Return a descriptor for one installed runner-owned workspace plugin."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", owner) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", plugin_id):
        return jsonify({"error": "Workspace plugin not found"}), 404
    descriptor = workspace_plugin_descriptor(plugin_id, owner=owner)
    if descriptor is None:
        return jsonify({"error": "Workspace plugin not found"}), 404
    return jsonify(_workspace_plugin_payload(descriptor))


def _workspace_plugin_payload(descriptor: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": descriptor.id,
        "owner": descriptor.owner,
        "global_id": descriptor.global_id,
        "descriptor_url": url_for(
            "workspace_plugin_descriptor_api", owner=descriptor.owner, plugin_id=descriptor.id
        ),
        "module": {
            "url": url_for(
                "workspace_plugin_asset", owner=descriptor.owner, plugin_id=descriptor.id, asset=descriptor.module
            ),
            "type": "module",
        },
        "stylesheets": [
            {
                "url": url_for(
                    "workspace_plugin_asset", owner=descriptor.owner, plugin_id=descriptor.id, asset=path
                ),
                "media_type": "text/css",
            }
            for path in descriptor.styles
        ],
    }
    if descriptor.configuration_schema:
        payload["configuration_schema_url"] = url_for(
            "workspace_plugin_asset",
            owner=descriptor.owner,
            plugin_id=descriptor.id,
            asset=descriptor.configuration_schema,
        )
    return payload


@app.route("/compute/api/workspace/assets/<owner>/<plugin_id>/<path:asset>", methods=["GET"])
@login_required
def workspace_plugin_asset(owner: str, plugin_id: str, asset: str):
    """Serve only module/style/schema assets explicitly registered by a plugin.

    Login is required: this is runner-authored JavaScript served under the app
    CSP (`script-src 'self'`), so anonymous access would let any caller execute
    it on the app origin.  Its only consumer is the authenticated
    `/compute/create_task` workspace editor, which loads these as same-origin
    scripts with the session cookie.
    """
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", owner) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", plugin_id):
        abort(404)
    descriptor = workspace_plugin_descriptor(plugin_id, owner=owner)
    if descriptor is None:
        abort(404)
    requested = asset.replace("\\", "/").strip("/")
    declared = {descriptor.module, *descriptor.styles}
    if descriptor.configuration_schema:
        declared.add(descriptor.configuration_schema)
    if not requested or requested not in declared or any(part in {"", ".", ".."} for part in requested.split("/")):
        abort(404)
    try:
        target = descriptor.asset_path(requested)
    except ValueError:
        abort(404)
    if not target.is_file():
        abort(404)
    response = send_from_directory(descriptor.root, requested, conditional=True)
    response.headers["Cache-Control"] = "private, no-cache"
    return response


# ---------------------------------------------------------------------------
# Tool API routes (authenticated-only, with no collection/history endpoint)
# ---------------------------------------------------------------------------


def _tool_access(tool_call_id: str) -> dict[str, Any] | None:
    normalized = normalize_tool_call_id(tool_call_id)
    return tool_calls.get_owned(normalized, int(g.current_user["id"])) if normalized else None


def _tool_follow_up(call: dict[str, Any]) -> dict[str, Any]:
    call_id = str(call["tool_call_id"])
    return {
        key: call.get(key)
        for key in (
            "tool_call_id", "tool_type", "status", "created_at", "started_at", "finished_at",
            "expires_at", "error_class", "error",
        )
    } | {
        "status_url": f"/compute/api/tool-calls/{call_id}",
        "results_url": f"/compute/api/tool-calls/{call_id}/results",
    }


@app.route("/compute/api/tools", methods=["GET"])
@login_required
def tool_catalog():
    tools = []
    for tool in tool_registry.list():
        payload = public_tool(tool)
        payload["available"] = tool.runtime.image.is_file()
        tools.append(payload)
    return jsonify({"tools": tools})


@app.route("/compute/api/tools/<name>", methods=["GET"])
@login_required
def tool_detail(name):
    try:
        tool = tool_registry.get(name)
    except KeyError:
        return jsonify({"error": "Tool not found"}), 404
    payload = public_tool(tool)
    payload.update(
        available=tool.runtime.image.is_file(),
        parameters_url=f"/compute/api/tool-parameters/{tool.name}",
        call_url=f"/compute/api/tools/{tool.name}/call",
    )
    return jsonify(payload)


@app.route("/compute/api/tool-parameters/<tool_type>", methods=["GET"])
@login_required
def tool_parameter_schema(tool_type):
    try:
        return jsonify(tool_registry.get(tool_type).schema)
    except KeyError:
        return jsonify({"error": "Tool not found"}), 404


def _reclaim_tool_storage(required_bytes: int) -> bool:
    if tool_calls.total_accounted_bytes() + required_bytes <= TOOL_CONFIG.storage_max_bytes:
        return True
    for candidate in tool_calls.cleanup_candidates(now=time.time(), storage_pressure=True):
        call_id = str(candidate["tool_call_id"])
        tool_workspace.delete(call_id)
        tool_calls.delete_terminal(call_id)
        if tool_calls.total_accounted_bytes() + required_bytes <= TOOL_CONFIG.storage_max_bytes:
            return True
    return False


def _tool_task_artifact(tool_call_id: str, role: Any, expression: str) -> dict[str, Any]:
    match = _ARTIFACT_REFERENCE_PATTERN.fullmatch(expression)
    if not match:
        raise ToolWorkspaceError("Invalid Task artifact reference")
    source_id, logical_path = match.groups()
    source = task_store.get_task(source_id.lower())
    if (
        source is None
        or source.get("status") != "finished"
        or str(source.get("submitted_by_user_id")) != str(g.current_user["id"])
    ):
        raise PermissionError("Task artifact reference is unavailable")
    resolved = current_app.config["storage_resolver"].resolve_artifact(source, logical_path)
    if resolved is None:
        raise ToolWorkspaceError("Task artifact reference is unavailable")
    stream = resolved.pop("verified_stream")
    try:
        # Materialize from the verified descriptor, not from ``physical_path``:
        # the bytes copied into the Tool workspace are exactly the bytes whose
        # manifest identity was checked, so a replacement between resolution and
        # materialization cannot enter the workspace.
        item = tool_workspace.materialize_stream(
            tool_call_id,
            role=role.name,
            filename=Path(logical_path).name,
            accepted_formats=role.formats,
            stream=stream,
        )
    finally:
        stream.close()
    item["source"] = {
        "kind": "task_artifact",
        "task_id": source_id.lower(),
        "artifact_path": resolved["path"],
        "sha256": resolved["sha256"],
    }
    return item


@app.route("/compute/api/tools/<name>/call", methods=["POST"])
@login_required
@rate_limit(max_requests=60, window_seconds=3600)
def submit_tool_call(name):
    if blocked := require_bearer_auth():
        return blocked
    if blocked := _reject_guest():
        return blocked
    if os.path.exists(os.path.join(CONFIG.server_dir, ".maintenance")):
        return jsonify({"error": "Server is in maintenance; submissions are paused"}), 503
    try:
        tool = tool_registry.get(name)
    except KeyError:
        return jsonify({"error": "Tool not found"}), 404
    if not tool.runtime.image.is_file():
        return jsonify({"error": "Tool runtime is unavailable", "error_class": "runtime_unavailable"}), 503
    idempotency_key = request.headers.get("Idempotency-Key", "").strip() or None
    if idempotency_key is not None and (len(idempotency_key) > 255 or any(ord(char) < 33 for char in idempotency_key)):
        return jsonify({"error": "Idempotency-Key is invalid"}), 400
    try:
        parameters = json.loads(request.form.get("parameters", "{}"))
        if not isinstance(parameters, dict):
            raise ValueError
        validate_json_schema(parameters, tool.schema)
    except (json.JSONDecodeError, ValueError, JSONSchemaValidationError):
        return jsonify({"error": "Tool parameters are invalid", "error_class": "invalid_parameters"}), 400

    uploads, upload_roles = request.files.getlist("files"), request.form.getlist("file_roles")
    artifact_refs, artifact_roles = request.form.getlist("artifact_references"), request.form.getlist("artifact_roles")
    if len(uploads) != len(upload_roles) or len(artifact_refs) != len(artifact_roles):
        return jsonify({"error": "Every Tool input must be bound to a named role"}), 400
    submitted_roles = [*upload_roles, *artifact_roles]
    known_roles = {role.name: role for role in tool.inputs}
    if any(role not in known_roles for role in submitted_roles):
        return jsonify({"error": "Unknown Tool input role"}), 400
    for role in tool.inputs:
        if not role.minimum <= submitted_roles.count(role.name) <= role.maximum:
            return jsonify({"error": f"Tool input role {role.name!r} violates its cardinality"}), 400

    call_id = new_tool_call_id()
    inputs: dict[str, list[dict[str, Any]]] = {role.name: [] for role in tool.inputs}
    try:
        tool_workspace.create(call_id)
        for uploaded, role_name in zip(uploads, upload_roles, strict=True):
            if not uploaded.filename:
                raise ToolWorkspaceError("Tool input filename is required")
            role = known_roles[role_name]
            inputs[role_name].append(
                tool_workspace.materialize_stream(
                    call_id, role=role_name, filename=uploaded.filename,
                    accepted_formats=role.formats, stream=uploaded.stream,
                )
            )
        for expression, role_name in zip(artifact_refs, artifact_roles, strict=True):
            inputs[role_name].append(_tool_task_artifact(call_id, known_roles[role_name], expression))
        for role_name, values in inputs.items():
            role = known_roles[role_name]
            for item in values:
                error = validate_input_file(item["physical_path"], item["original_name"], logical_type=role.type)
                error = error or validate_logical_input(item["physical_path"], item["format"], role.type)
                if error:
                    raise ToolWorkspaceError(error)
        tool_workspace.write_request(call_id, tool, inputs, parameters)
        input_bytes = sum(int(item["size"]) for values in inputs.values() for item in values)
        if input_bytes > TOOL_CONFIG.request_max_bytes:
            raise ToolWorkspaceError("Tool request input limit exceeded")
        workspace_bytes = tool_workspace.bytes_used(call_id)
        output_headroom = TOOL_CONFIG.output_max_bytes
        required_bytes = workspace_bytes + output_headroom
        input_manifest = {
            "inputs": {
                role: [
                    {key: item[key] for key in ("original_name", "path", "format", "sha256", "size", "source") if key in item}
                    for item in values
                ]
                for role, values in inputs.items()
            }
        }

        def reserve_call():
            return tool_calls.reserve(
                tool_call_id=call_id,
                tool_type=tool.name,
                runtime_family=tool.runtime.name,
                runtime_identity=tool.runtime.identity,
                user_id=int(g.current_user["id"]),
                username=str(g.current_user["username"]),
                parameter_json=canonical_parameters(parameters),
                input_manifest_json=json.dumps(input_manifest, separators=(",", ":"), sort_keys=True),
                idempotency_key=idempotency_key,
                per_user_limit=TOOL_CONFIG.max_active_per_user,
                global_limit=TOOL_CONFIG.max_active_global,
                workspace_bytes=workspace_bytes,
                reserved_bytes=output_headroom,
                storage_max_bytes=TOOL_CONFIG.storage_max_bytes,
            )

        try:
            reservation = reserve_call()
        except ToolAdmissionError as exc:
            # reserve() resolves Idempotency-Key atomically before it checks
            # storage, so repeating an accepted call returns its original row
            # without touching admission.  A storage rejection — global or the
            # caller's own share — may reclaim terminal workspaces, and then
            # only once.
            if exc.reason not in {"storage_limit", "user_storage_limit"} or not _reclaim_tool_storage(required_bytes):
                raise
            reservation = reserve_call()
        if not reservation.created:
            tool_workspace.delete(call_id)
            return jsonify(_tool_follow_up(reservation.call)), 202
    except PermissionError as exc:
        tool_workspace.delete(call_id)
        return jsonify({"error": str(exc)}), 403
    except ToolWorkspaceError as exc:
        tool_workspace.delete(call_id)
        return jsonify({"error": str(exc), "error_class": "invalid_input"}), 400
    except ToolAdmissionError as exc:
        tool_workspace.delete(call_id)
        response = jsonify({"error": "Tool admission limit reached", "reason": exc.reason})
        response.headers["Retry-After"] = "5"
        return response, 507 if exc.reason in {"storage_limit", "user_storage_limit"} else 429

    try:
        async_result = celery.send_task("revocompute.run_tool_call", args=[call_id], queue="tools")
        tool_calls.update(call_id, celery_task_id=async_result.id)
    except Exception:
        logging.exception("Failed to enqueue Tool call %s", call_id)
        now = time.time()
        tool_calls.transition(
            call_id, expected=("queued",), status="failed", finished_at=now,
            expires_at=now + TOOL_CONFIG.call_ttl_seconds, error_class="runtime_unavailable",
            error="Tool queue is unavailable",
        )
        return jsonify({"error": "Tool queue is unavailable", "error_class": "runtime_unavailable"}), 503
    call = tool_calls.get(call_id) or reservation.call
    response = jsonify(_tool_follow_up(call))
    response.headers["Location"] = f"/compute/api/tool-calls/{call_id}"
    return response, 202


@app.route("/compute/api/tool-calls/<tool_call_id>", methods=["GET"])
@login_required
def tool_call_status(tool_call_id):
    call = _tool_access(tool_call_id)
    return jsonify(_tool_follow_up(call)) if call else (jsonify({"error": "Tool call not found"}), 404)


@app.route("/compute/api/tool-calls/<tool_call_id>/results", methods=["GET"])
@login_required
def tool_call_results(tool_call_id):
    call = _tool_access(tool_call_id)
    if call is None:
        return jsonify({"error": "Tool call not found"}), 404
    if call["status"] in {"queued", "preparing", "running"}:
        return jsonify(_tool_follow_up(call)), 202
    if call["status"] == "failed":
        return jsonify(_tool_follow_up(call)), 422
    return jsonify(json.loads(str(call["result_manifest_json"])))


@app.route("/compute/api/tool-calls/<tool_call_id>/outputs/<output_id>", methods=["GET"])
@login_required
def tool_call_output(tool_call_id, output_id):
    call = _tool_access(tool_call_id)
    if call is None or call["status"] != "finished":
        return jsonify({"error": "Tool output not found"}), 404
    values = json.loads(str(call["result_manifest_json"])).get("outputs", {}).get(output_id)
    if not isinstance(values, list):
        return jsonify({"error": "Tool output not found"}), 404
    if len(values) > 1 and request.args.get("index") is None:
        return jsonify({"error": "An output index is required"}), 400
    try:
        item = values[int(request.args.get("index", "0"))]
    except (ValueError, IndexError):
        return jsonify({"error": "Tool output index is invalid"}), 400
    return send_from_directory(
        tool_workspace.call_root(str(call["tool_call_id"])) / "output", item["path"],
        as_attachment=True, download_name=item["path"],
    )


# ---------------------------------------------------------------------------
# Task API routes
# ---------------------------------------------------------------------------


@app.route("/compute/api/types", methods=["GET"])
@optional_user
def task_types_list():
    """Return registered task types (public — needed by the create-task page)."""
    return jsonify(_available_task_types())


@app.route("/compute/api/task-parameters/<task_type>", methods=["GET"])
def task_parameter_schema(task_type: str):
    """Return the canonical task.yaml-owned JSON Schema for one enabled TaskType."""
    try:
        tt, _runner = _get_task_type(task_type)
    except KeyError:
        return jsonify({"error": f"Unknown task type: {task_type!r}"}), 404

    manage_db = current_app.config.get("manage_db")
    if manage_db is not None and manage_db.task_type_is_enabled(tt.name) is False:
        return jsonify({"error": f"Task type {task_type!r} is disabled"}), 404
    return jsonify(tt.schema)


def _task_guidance(tt) -> dict[str, Any]:
    return {
        "summary": tt.summary,
        "use_when": tt.use_when,
        "input_summary": tt.input_summary,
        "output_summary": tt.output_summary,
        "considerations": list(tt.considerations),
    }


def _parameter_payload(parameter, *, include_help: bool = False) -> dict[str, Any]:
    payload = {
        "name": parameter.name,
        "type": parameter.type,
        "default": parameter.default,
        "required": parameter.required,
        "description": parameter.description,
        "label": parameter.label or parameter.name.replace("_", " ").title(),
        "choices": list(parameter.choices),
        "minimum": parameter.minimum,
        "maximum": parameter.maximum,
        "step": parameter.step,
        "unit": parameter.unit,
        "advanced": parameter.advanced,
        "ui_control": parameter.ui_control,
    }
    if include_help:
        payload["help"] = parameter.help
    return payload


def _task_summary(tt, *, include_internal_metadata: bool = False) -> dict[str, Any]:
    payload = {
        "name": tt.name,
        "display_name": tt.display_name,
        "category": tt.category,
        "summary": tt.summary,
        "access": _runner_access_payload(tt, compact=not include_internal_metadata),
        "detail_url": f"/compute/api/types/{tt.name}",
        "parameters_url": f"/compute/api/task-parameters/{tt.name}",
    }
    if include_internal_metadata:
        payload.update(
            _task_guidance(tt),
            gpus=tt.gpus,
            requires_network=tt.requires_network or any(stage.requires_network for stage in tt.workflow),
            inputs=[
                {
                    "id": role.name,
                    "title": role.title,
                    "type": role.type,
                    "formats": list(role.formats),
                    "cardinality": {"min": role.minimum, "max": role.maximum},
                    "description": role.description,
                }
                for role in tt.inputs
            ],
            stage_markers=tt.stage_markers,
            runtime_family=tt.runtime.name,
            citations=[citation.projection() for citation in tt.citations],
        )
        payload["params"] = [_parameter_payload(parameter) for parameter in tt.params]
    return payload


def _runner_access_payload(tt, *, compact: bool = False) -> dict[str, Any]:
    policy = tt.runtime.access_policy
    if policy is None:
        return {"restricted": False, "granted": True, "request_status": None} if compact else {"restricted": False}
    user = g.get("current_user")
    state = policy_state(policy, current_app.config["user_db"], int(user["id"]) if user else None)
    if compact:
        return {
            "restricted": True,
            "granted": bool(state.get("granted")),
            "request_status": state.get("request_status"),
        }
    return state


def _available_task_types(*, include_runner_metadata: bool = False) -> dict[str, Any]:
    """Serialize the ordered, enabled scientific method catalog."""
    manage_db = current_app.config.get("manage_db")
    enabled_types = []
    for tt in list_types():
        if manage_db is not None and manage_db.task_type_is_enabled(tt.name) is False:
            continue
        enabled_types.append(_task_summary(tt, include_internal_metadata=include_runner_metadata))
    category_order = {category.name: category.order for category in list_categories()}
    enabled_types.sort(key=lambda item: (category_order[item["category"]], item["display_name"].lower()))
    return {
        "version": 3,
        "categories": [
            {
                "name": category.name,
                "label": category.label,
                **({"description": category.description, "order": category.order} if include_runner_metadata else {}),
            }
            for category in list_categories()
            if any(task["category"] == category.name for task in enabled_types)
        ],
        "task_types": enabled_types,
    }


def _input_workspace_payload(tt) -> dict:
    """Serialize the declarative, non-executable input workspace contract."""
    plugin_ids = {capability.plugin for step in tt.input_workspace for capability in step.capabilities}
    descriptors = []
    for plugin_id in sorted(plugin_ids):
        descriptor = workspace_plugin_descriptor(plugin_id, owner=tt.runtime.name)
        if descriptor is None:
            continue
        descriptors.append(_workspace_plugin_payload(descriptor))
    return {
        "version": 3,
        "plugins": descriptors,
        "steps": [
            {
                "id": step.id,
                "title": step.title,
                "description": step.description,
                "capabilities": [
                    {
                        "plugin": capability.plugin,
                        "id": capability.id,
                        "title": capability.title,
                        "description": capability.description,
                        "options": capability.options,
                    }
                    for capability in step.capabilities
                ],
            }
            for step in tt.input_workspace
        ],
    }


@app.route("/compute/api/types/<name>", methods=["GET"])
@optional_user
def task_type_form(name: str):
    """Return a single task type's full form definition (public).

    The client fetches this when the user selects a task type, then
    dynamically builds the upload form from the response.
    """
    try:
        tt, runner = _get_task_type(name)
    except KeyError:
        return jsonify({"error": f"Unknown task type: {name!r}"}), 404

    manage_db = current_app.config.get("manage_db")
    if manage_db is not None:
        enabled = manage_db.task_type_is_enabled(tt.name)
        if enabled is False:
            return jsonify({"error": f"Task type {name!r} is disabled"}), 404

    if manage_db is not None:
        # Fail the form early on a broken policy, but do not expose the
        # resolved resource usage to users — resource review is not part of
        # the submission flow.  The real enforcement happens at submission.
        try:
            manage_db.resolve_task_resources(
                tt.name,
                requires_gpu=tt.gpus,
                default_timeout_seconds=runner.max_runtime_seconds,
            )
        except ResourceValidationError as exc:
            return jsonify({"error": f"Task resource policy is invalid: {exc}"}), 503

    workspace_payload = _input_workspace_payload(tt)
    return jsonify(
        {
            **_task_summary(tt),
            **_task_guidance(tt),
            "access": _runner_access_payload(tt),
            "definition_version": 4,
            "runtime_family": tt.runtime.name,
            "gpus": tt.gpus,
            "requires_network": tt.requires_network or any(stage.requires_network for stage in tt.workflow),
            "inputs": [
                {
                    "id": role.name,
                    "title": role.title,
                    "type": role.type,
                    "formats": list(role.formats),
                    "extensions": list(role.extensions),
                    "accept": ",".join(role.extensions),
                    "cardinality": {"min": role.minimum, "max": role.maximum},
                    "description": role.description,
                }
                for role in tt.inputs
            ],
            "citations": [citation.projection() for citation in tt.citations],
            "workflow": [
                {
                    "name": stage.name,
                    "display_name": stage.display_name,
                    "requires_gpu": stage.requires_gpu,
                    "requires_network": stage.requires_network,
                    "stage_markers": list(stage.stage_markers),
                }
                for stage in tt.workflow
            ],
            "max_request_bytes": current_app.config["MAX_CONTENT_LENGTH"],
            "input_workspace": workspace_payload,
        }
    )


@app.route("/compute/api/types/<name>/workspace/normalize", methods=["POST"])
@login_required
def normalize_workspace(name: str):
    """Normalize one stateful capability through its server-owned adapter.

    This runs the same Runner-owned normalizer the submission path runs, so it
    carries the same CSRF gate as every other state-changing POST: the caller
    must present a Bearer token.  The endpoint has no side effects, but keeping
    "state-changing POST" one rule rather than a per-route judgement call is what
    keeps the next POST from being the one that is missed.
    """
    if blocked := require_bearer_auth():
        return blocked
    try:
        tt, _ = _get_task_type(name)
    except KeyError:
        return jsonify({"error": f"Unknown task type: {name!r}"}), 404
    payload = request.get_json(silent=True) or {}
    capability = next((item for item in iter_capabilities(tt) if item.id == payload.get("capability_id")), None)
    adapter = workspace_backend(capability.plugin) if capability is not None else None
    if adapter is None:
        return jsonify({"error": "Unknown normalizable workspace capability"}), 400
    try:
        result = normalize_capability(adapter[0], payload.get("value"))
    except WorkspaceValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


_WORKSPACE_KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

# Batch delete runs one synchronous artifact removal per supplied id inside
# the request, so the batch is bounded like every other caller-supplied list.
_MAX_BATCH_DELETE_TASKS = 100


class InputPreflightError(ValueError):
    def __init__(self, item: dict[str, Any], code: str, message: str):
        super().__init__(message)
        self.item = item
        self.code = code


def _input_contract_error(code: str, message: str, *, role: str | None = None, format_name: str | None = None):
    detail = {"code": code, "message": message}
    if role is not None:
        detail["role"] = role
    if format_name is not None:
        detail["format"] = format_name
    return jsonify({"error": message, "details": [detail]}), 400


def _role_by_name(task_type: Any, name: str):
    return next((role for role in task_type.inputs if role.name == name), None)


def _validate_role_counts(task_type: Any, role_names: list[str]):
    known = {role.name for role in task_type.inputs}
    unknown = next((name for name in role_names if name not in known), None)
    if unknown is not None:
        return _input_contract_error("input_role_unknown", f"Unknown input role: {unknown}", role=unknown)
    for role in task_type.inputs:
        count = role_names.count(role.name)
        if count < role.minimum or count > role.maximum:
            message = f"Input role {role.name!r} requires {role.minimum}..{role.maximum} file(s); received {count}."
            return _input_contract_error("input_role_cardinality", message, role=role.name)
    return None


def _validate_input_uploads(task_type: str | None = None):
    """Apply transport and task-role checks without assigning meaning by upload order."""
    task_type = task_type or default_task_type()
    try:
        tt, _ = _get_task_type(task_type)
    except KeyError:
        return None, (jsonify({"error": f"Unknown task type: {task_type}"}), 400)
    uploads = request.files.getlist("files") or request.files.getlist("file")
    uploads = [uploaded for uploaded in uploads if uploaded.filename]
    max_input_files = int(current_app.config["MAX_INPUT_FILES"])
    if len(uploads) > max_input_files:
        return None, _input_contract_error(
            "input_file_count_limit",
            f"Submission contains more than the {max_input_files} input file limit.",
        )
    submitted_roles = request.form.getlist("input_roles")
    if len(submitted_roles) != len(uploads):
        return None, _input_contract_error(
            "input_role_binding", "Every uploaded file must be bound to an input role."
        )
    if error := _validate_role_counts(tt, submitted_roles):
        return None, error
    submitted_paths = request.form.getlist("input_paths")
    validated: list[tuple[Any, str, str, str]] = []
    seen_paths: set[tuple[str, str]] = set()
    for index, (uploaded, role_name) in enumerate(zip(uploads, submitted_roles, strict=True)):
        raw_path = submitted_paths[index] if index < len(submitted_paths) else uploaded.filename
        safe_path, reason = canonical_relative_path(raw_path)
        role = _role_by_name(tt, role_name)
        if safe_path is None:
            return None, _input_contract_error(reason or "input_path_invalid", "Invalid input path")
        key = (role_name, safe_path)
        if key in seen_paths:
            # The canonical path is the namespace identity, so a repeat is either
            # an outright duplicate claim or a collision the sanitizer created
            # (two distinct submissions folding onto one path).  Both are
            # failures: the snapshot is a filesystem, and one submission must
            # never silently overwrite another's bytes.
            return None, _input_contract_error(
                "input_namespace_collision",
                "Two inputs resolve to the same path within one role.",
                role=role_name,
            )
        format_name = os.path.splitext(safe_path)[1].lower().removeprefix(".")
        if role is None or format_name not in role.formats:
            return None, _input_contract_error(
                "input_role_format",
                f"Input role {role_name!r} does not accept {format_name or 'files without a format extension'}.",
                role=role_name,
                format_name=format_name or None,
            )
        seen_paths.add(key)
        validated.append((uploaded, safe_path, role_name, format_name))
    # A path may not also be a directory prefix of another path in the same role:
    # ``x.pdb`` cannot be both a file and the directory ``x.pdb/`` the other path
    # needs.  The collision set above only catches exact repeats, so a prefix
    # pair would otherwise reach materialization, where ``copyfile`` fails and the
    # request dies as a 500 with a durable failed row and orphan state.
    for _uploaded, safe_path, role_name, _format in validated:
        prefix = safe_path + "/"
        if any(
            other_role == role_name and other_path.startswith(prefix)
            for _other_uploaded, other_path, other_role, _other_format in validated
        ):
            return None, _input_contract_error(
                "input_namespace_collision",
                f"Input path {safe_path!r} is also used as a directory by another input.",
                role=role_name,
            )
    return validated, None


def _quarantine_uploaded_inputs(
    uploads: list[tuple[Any, str, str, str]],
    task_type: str,
) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    """Quarantine and validate every input before extension code can inspect it."""
    metadata = _request_metadata()
    saved: list[dict[str, Any]] = []
    quarantined: list[str] = []
    total_bytes = 0
    try:
        for uploaded, relative_path, role, format_name in uploads:
            temp_name = f".tmp_{os.urandom(8).hex()}_{os.path.basename(relative_path)}"
            temp_path = _safe_join(app.config["UPLOAD_FOLDER"], temp_name)
            quarantined.append(temp_path)
            hasher = hashlib.sha256()
            item = {
                "original_name": uploaded.filename,
                "relative_path": relative_path,
                "blob_path": temp_path,
                "role": role,
                "format": format_name,
            }
            file_bytes = 0
            with open(temp_path, "wb") as handle:
                while chunk := uploaded.stream.read(65536):
                    file_bytes += len(chunk)
                    total_bytes += len(chunk)
                    if file_bytes > int(current_app.config["MAX_INPUT_FILE_BYTES"]):
                        raise InputPreflightError(
                            item,
                            "input_file_size_limit",
                            f"Input file exceeds the {current_app.config['MAX_INPUT_FILE_BYTES']} byte limit.",
                        )
                    if total_bytes > int(current_app.config["MAX_INPUT_TOTAL_BYTES"]):
                        limit = current_app.config["MAX_INPUT_TOTAL_BYTES"]
                        raise InputPreflightError(
                            item,
                            "input_total_size_limit",
                            f"Combined uploaded inputs exceed the {limit} byte limit.",
                        )
                    handle.write(chunk)
                    hasher.update(chunk)
            item["hash"] = hasher.hexdigest()
            item["size"] = file_bytes
            saved.append(item)
        tt = _get_task_type(task_type)[0]
        for item in saved:
            role = _role_by_name(tt, item["role"])
            logical_type = role.type if role else "file"
            error = validate_input_file(item["blob_path"], item["relative_path"], logical_type=logical_type)
            code = "input_format_invalid"
            if error is None:
                error = validate_logical_input(item["blob_path"], item["format"], logical_type)
                code = "input_logical_type_invalid"
            if error is not None:
                # A resource-limit outcome carries the bounded code itself, so a
                # hostile input that exhausted the isolated parser is reported as
                # a resource limit rather than as an indistinguishable malformed
                # file whose only distinguishing detail is prose.
                if error == VALIDATOR_RESOURCE_LIMIT_ERROR:
                    code = VALIDATOR_RESOURCE_LIMIT_ERROR
                raise InputPreflightError(item, code, error)
            # Bind the admission decision to the exact bytes just validated.  The
            # digest is computed from the quarantine file that validation read,
            # so the receipt names the byte stream execution will later consume,
            # not a path that could be re-resolved to something else.
            item["validation_receipt"] = ValidationReceipt(
                sha256=item["hash"],
                size=item["size"],
                format=item["format"],
                logical_type=logical_type,
                relative_path=item["relative_path"],
                role=item["role"],
            ).as_record()
    except Exception:
        for path in quarantined:
            if os.path.exists(path):
                os.remove(path)
        raise
    return saved, metadata, quarantined


def _derive_task_id(
    saved: list[dict[str, Any]],
    task_type: str,
    params: dict[str, Any],
    user_storage_key: str,
) -> str:
    """Derive the prospective Task ID after security and contract normalization."""
    identity_inputs: dict[str, list[dict[str, str]]] = {}
    for item in saved:
        identity_inputs.setdefault(item["role"], []).append(
            {
                "path": item["relative_path"],
                "sha256": item["hash"],
                "validation_receipt": item.get("validation_receipt"),
            }
        )
    identity = json.dumps(
        {
            "task_type": task_type,
            "params": params,
            "inputs": identity_inputs,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    content_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return _task_id_for_upload(content_id, user_storage_key)


def _promote_preflight_inputs(saved: list[dict[str, Any]]) -> None:
    """Promote security-approved inputs into the content-addressed blob store."""
    for item in saved:
        source = item["blob_path"]
        destination = _safe_join(app.config["UPLOAD_FOLDER"], f"{item['hash']}.upload")
        if not os.path.exists(destination):
            os.replace(source, destination)
        item["blob_path"] = destination


def _cleanup_quarantine(paths: list[str]) -> None:
    for path in paths:
        if os.path.exists(path):
            os.remove(path)


_ARTIFACT_REFERENCE_PATTERN = re.compile(r"@([a-fA-F0-9]{32})/(.+)")


# Which cleanup claim/deleted-status pair a user deletion of each status uses.
# Keyed by the status the route observed; the claim compare-and-set means a
# row that moved since then (including into another claim) is not touched.
_DELETE_CLAIMS = {
    "pending": ("deleting:cancel", "deleted:cancel"),
    "queued": ("deleting:cancel", "deleted:cancel"),
    "running": ("deleting:cancel", "deleted:cancel"),
    "finished": ("deleting:finished", "deleted:finshed"),
    "failed": ("deleting:cancel", "deleted:cancel"),
    "cancelled": ("deleting:cancel", "deleted:cancel"),
    "deleted:finshed": ("deleting:finished", "deleted:finshed"),
    "deleted:cancel": ("deleting:cancel", "deleted:cancel"),
}


def _resolve_task_owner() -> dict[str, Any]:
    user = g.current_user
    storage_key = user.get("storage_key")
    if not storage_key:
        raise RuntimeError("User storage identity is unavailable")
    return {"submitted_by_user_id": int(user["id"]), "storage_key": storage_key}


def _result_publication_state(task: dict[str, Any]) -> str:
    """Return the bounded publication state of a task's result.

    One reader answers for every surface: the status payload, the results route,
    the archive, and the readiness probes all report the same state, so a
    consumer never has to guess why a result it can see is not readable.
    """
    return current_app.config["storage_resolver"].publication_state(task)


#: Operator- and client-facing reason for each non-available publication state.
#: The state is the machine-readable fact; this is its human-readable projection,
#: and it is the difference between "quarantined, and here is why" and a bare
#: not-found.
_PUBLICATION_REASON_TEXT = {
    PUBLICATION_MANIFEST_MISSING: "The published result manifest is missing from storage.",
    PUBLICATION_MANIFEST_UNREADABLE: "The published result manifest is unavailable.",
    PUBLICATION_UNANCHORED: "This result predates server-owned publication identity and is quarantined; run the task again to publish it.",
    PUBLICATION_ANCHOR_MISMATCH: "The result manifest no longer matches the publication Core recorded for this task.",
    PUBLICATION_ANCHOR_INVALID: "The recorded publication identity for this task is invalid.",
    PUBLICATION_NOT_FINALIZED: "The task published no result manifest.",
}


def _publication_report(task: dict[str, Any]) -> dict[str, Any]:
    """Return ``{"state", "reason"}`` for a task's result publication."""
    state = _result_publication_state(task)
    return {"state": state, "reason": None if state == PUBLICATION_AVAILABLE else _PUBLICATION_REASON_TEXT.get(state)}


def _publication_refusal_response(md5sum: str, publication: str):
    """The one 409 body for a result the publication reader will not serve.

    Requesting a new archive and downloading a cached one are the same
    publication decision, so both answer with this: the bounded state and its
    reason, never bytes assembled from a result Core's reader refuses.
    """
    return (
        jsonify(
            {
                "status": "error",
                "md5sum": md5sum,
                "message": _PUBLICATION_REASON_TEXT.get(publication) or "result manifest not found",
                "result_publication": publication,
            }
        ),
        409,
    )


def _task_display_name(task: dict[str, Any], task_id: str) -> str:
    raw = ntpath.basename(os.path.basename(str(task.get("filename") or "")))
    display = "".join(character for character in unicodedata.normalize("NFC", raw) if not unicodedata.category(character).startswith("C"))
    return display[:255] or task_id


def _task_follow_up_payload(md5sum: str, status: str) -> dict[str, Any]:
    task = task_store.get_task(md5sum)
    # A task's result publication is reported as its bounded state, not just a
    # boolean: "finished, results not readable" is answered with *why*, and the
    # legacy corpus -- results finalized before publication identity was recorded
    # -- reports ``unanchored`` here rather than silently disappearing.
    publication = _result_publication_state(task) if task is not None else None
    payload = {
        "task_id": md5sum,
        "md5sum": md5sum,
        "task_type": (task.get("task_type") or default_task_type()) if task is not None else default_task_type(),
        "display_name": _task_display_name(task, md5sum) if task is not None else md5sum,
        "status": status,
        # The server owns which statuses are terminal; clients polling this
        # endpoint stop on this flag rather than mirroring the vocabulary.
        "terminal": str(status).strip().lower() in task_store.STOP_POLLING_STATUSES,
        "status_url": f"/compute/api/running/{md5sum}",
        "results_url": f"/compute/api/results/{md5sum}",
        "result_available": publication == PUBLICATION_AVAILABLE,
        "result_publication": publication,
    }
    # Per-item progress and the standardized task outcome.  Absent until the
    # runner reports them, so a single-input task's payload is unchanged.
    if task is not None:
        summary = _progress_summary(task) or {}
        payload.update({key: value for key, value in summary.items() if value is not None})
    return payload


def _task_submission_response(md5sum: str, status: str, code: int):
    response = jsonify(_task_follow_up_payload(md5sum, status))
    response.headers["Location"] = f"/compute/api/running/{md5sum}"
    return response, code


def _existing_upload_response(existing_task: dict[str, Any] | None, md5sum: str):
    if not existing_task:
        return None
    if not _task_access_allowed(existing_task):
        return _task_not_found(md5sum)
    status = str(existing_task["status"] or "").strip().lower()
    if status == "finished":
        return _task_submission_response(md5sum, "finished", 302)
    if status in {
        "pending",
        "queued",
        "running",
        *task_store.CLEANUP_CLAIM_STATUSES,
    }:
        payload = _task_follow_up_payload(md5sum, "Task already queued or running")
        payload["task_status"] = status
        response = jsonify(payload)
        response.headers["Location"] = payload["status_url"]
        return response, 202
    # The Task ID is derived from the submitted content, so a row that still
    # owns artifacts, a possibly-live allocation, or a resumable cleanup
    # reserves that ID.  Ownership of an allocation is what matters, not status
    # alone: orphan recovery records `failed` without confirming cancellation
    # and leaves `slurm_job_id` set.  Reusing such an ID cannot be distinguished
    # from a retry of the original submission, and the original may still be
    # winding down asynchronously, so the resubmission is answered with the
    # existing task rather than re-prepared and re-dispatched.  A `finished`
    # row keeps its 302 above; a `failed` row whose handle was cleared falls
    # through and may be re-prepared normally.
    if status in task_store.TERMINAL_STATUSES or existing_task.get("slurm_job_id") or existing_task.get("container_id"):
        return _task_submission_response(md5sum, status, 409)
    return None


def _submission_in_progress_response(md5sum: str, claim) -> tuple:
    """Answer a submission that lost, or could not take, the preparation claim.

    The claim distinguishes the cases the old code could not: another request is
    preparing the ID right now, the row is settled, or it was dispatched.  Only
    the first has no row yet — the winner has not written it — so answering from
    the row when there is one keeps every already-visible outcome identical.
    """
    if claim.row is not None:
        return _existing_upload_response(claim.row, md5sum) or _task_submission_response(
            md5sum, str(claim.row.get("status") or "pending"), 409
        )
    payload = _task_follow_up_payload(md5sum, "Task preparation already in progress")
    payload["task_status"] = "pending"
    response = jsonify(payload)
    response.headers["Location"] = payload["status_url"]
    return response, 202


def _prepare_task_record(
    md5sum: str,
    saved_inputs: list[dict[str, Any]],
    metadata: dict[str, str],
    task_type: str | None = None,
    input_form: dict[str, Any] | None = None,
    task_owner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_type = task_type or default_task_type()
    if not task_owner:
        raise ValueError("Task owner is required")
    representative = min(saved_inputs, key=lambda item: (item["role"], item["relative_path"])) if saved_inputs else None
    return {
        "filename": representative["relative_path"] if representative else "Generated structure",
        "file_path": representative["blob_path"] if representative else "",
        "uploaded_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "walltime": None,
        "is_binary": int(_is_binary_file(representative["blob_path"])) if representative else 0,
        "source_ip": metadata["ip"],
        "user_agent": metadata["user_agent"],
        "username": metadata["username"],
        "submitted_by_user_id": task_owner["submitted_by_user_id"],
        "request_headers": metadata["headers_json"],
        "local_user": _local_user_identity(),
        "celery_task_id": None,
        "run_stage": None,
        "task_type": task_type,
        "input_form": json.dumps(input_form) if input_form else None,
        "storage_key": task_owner["storage_key"],
        "artifact_provenance": json.dumps([], sort_keys=True),
    }


def _materialize_task_tree(
    md5sum: str,
    saved_inputs: list[dict[str, Any]],
    task_manifest: dict[str, Any],
    task_owner: dict[str, Any],
) -> None:
    """Write one Task's input snapshot and empty output root.

    Called only by the request that *won* the Task-ID preparation claim, so the
    content-derived directory tree it deletes and recreates is one nobody else
    owns.  Splitting this out of ``_prepare_task_record`` matters because the
    deletion is destructive: it must never run before ownership is settled, or
    two concurrent first submissions of identical content would each destroy
    and rebuild the same tree while racing for the ID.
    """
    task_identity = {
        "md5sum": md5sum,
        "storage_key": task_owner["storage_key"],
    }
    resolver = app.config["storage_resolver"]
    workspace_dir = resolver.get_input_root(task_identity)
    if os.path.exists(workspace_dir):
        shutil.rmtree(workspace_dir)
    snapshot_root = _safe_join(workspace_dir, "inputs")
    os.makedirs(snapshot_root, exist_ok=True)
    for item in saved_inputs:
        destination = _safe_join(snapshot_root, item["role"], *item["relative_path"].split("/"))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(item["blob_path"], destination)
        os.chmod(destination, 0o440)

    result_dir = resolver.get_output_root(task_identity)
    if os.path.exists(result_dir):
        shutil.rmtree(result_dir)
    os.makedirs(result_dir, exist_ok=True)
    zip_path = resolver.get_archive_path(task_identity)
    if os.path.exists(zip_path):
        os.remove(zip_path)

    # The manifest lands inside the snapshot the copy above created.
    manifest_path = _safe_join(snapshot_root, "task.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(task_manifest, handle, indent=2, sort_keys=True)


def _input_preflight_error_response(error: InputPreflightError):
    item = error.item
    message = str(error)
    return jsonify(
        {
            "error": message,
            "details": [
                {
                    "code": error.code,
                    "role": item["role"],
                    "format": item["format"],
                    "path": item["relative_path"],
                    "message": message,
                }
            ],
        }
    ), 400


@app.errorhandler(RequestEntityTooLarge)
def _request_entity_too_large(_error):
    message = f"Request body exceeds the {current_app.config['MAX_CONTENT_LENGTH']} byte limit."
    finding = PreflightFinding(code="request_size_limit", message=message)
    emit_event(
        "preflight.security_rejected",
        level="WARNING",
        request_id=g.request_id,
        reason_code="request_size_limit",
    )
    if request.path.startswith("/compute/api/preflight/"):
        result = TaskPreflightResult(
            valid=False,
            security=PreflightPhase(status="failed"),
            contract=PreflightPhase(status="not_checked"),
            admission=PreflightAdmission(allowed=False),
            errors=[finding],
        )
        return jsonify(result.model_dump(exclude_none=True)), 413
    return jsonify({"error": message, "details": [finding.model_dump(exclude_none=True)]}), 413


@app.errorhandler(RecursionError)
def _request_nesting_too_deep(_error):
    """A deeply nested JSON body is malformed input, not a server fault.

    ``json.loads`` signals excessive nesting with ``RecursionError``, which
    ``get_json(silent=True)`` does not suppress (it only swallows
    ``ValueError``), so without this the body reaches the client as a 500.
    """
    logging.warning("Rejected a request body that exceeded the JSON nesting limit")
    message = "Request body is nested too deeply."
    return jsonify({"error": message, "details": [{"code": "request_size_limit", "message": message}]}), 400


@app.route("/compute/api/post", methods=["POST"])
@login_required
@rate_limit(max_requests=30, window_seconds=3600)
def upload_file():
    emit_event("task.submission.started", request_id=g.request_id)
    return _handle_submission()


@app.route("/compute/api/preflight/<task_type>", methods=["POST"])
@login_required
def preflight_task(task_type: str):
    emit_event("preflight.started", request_id=g.request_id)
    response = make_response(_rate_limited_preflight(task_type))
    if response.status_code < 400:
        return response
    payload = response.get_json(silent=True) or {}
    details = payload.get("details") if isinstance(payload.get("details"), list) else []
    detail = details[0] if details and isinstance(details[0], dict) else {}
    code = str(
        detail.get("code")
        or {
            400: "contract_invalid",
            401: "authentication_required",
            403: "admission_denied",
            429: "admission_limited",
        }.get(response.status_code, "admission_unavailable")
    )
    # The phase and the emitted event come from the one Core-owned vocabulary,
    # so a new admission reason code is classified once rather than re-listed at
    # every ingress that reports it.
    phase = phase_for_code(code, http_status=response.status_code)
    emit_event(
        event_for_code(code, http_status=response.status_code),
        level="WARNING",
        request_id=g.request_id,
        reason_code=code,
    )
    finding = PreflightFinding(
        code=code,
        message=str(payload.get("error") or payload.get("message") or "Preflight failed"),
        **{key: detail[key] for key in ("field", "role", "format", "path") if isinstance(detail.get(key), str)},
    )
    result = TaskPreflightResult(
        valid=False,
        security=PreflightPhase(status="failed" if phase == "security" else "not_checked"),
        contract=PreflightPhase(status="failed" if phase == "contract" else "not_checked"),
        admission=PreflightAdmission(allowed=False),
        errors=[finding],
    )
    failed = jsonify(result.model_dump(exclude_none=True))
    if retry_after := response.headers.get("Retry-After"):
        failed.headers["Retry-After"] = retry_after
    return failed, response.status_code


@rate_limit(max_requests=30, window_seconds=3600)
def _rate_limited_preflight(task_type: str):
    return _handle_submission(task_type_override=task_type, preflight_only=True)


def _handle_submission(  # skipcq: PY-R1000 -- validation branches form one transactional request boundary.
    *, task_type_override: str | None = None, preflight_only: bool = False
):
    if _blocked := require_bearer_auth():
        return _blocked
    # Guests hold no compute authority, so the role rule applies once at this
    # shared boundary for both /compute/api/post and /compute/api/preflight/.
    if _blocked := _reject_guest():
        return _blocked

    # Deployment maintenance sentinel (restart.sh --drain): SERVER_DIR is
    # bind-mounted into the web container, so the host-side file is visible.
    if os.path.exists(os.path.join(CONFIG.server_dir, ".maintenance")):
        return jsonify({"error": "Server is in maintenance; submissions are paused"}), 503

    # Parse flat form data ("params[key]=value") into nested dict
    raw_form = request.form.to_dict(flat=True)
    raw_form.pop("input_paths", None)
    raw_form.pop("input_roles", None)
    form_data: dict[str, Any] = {}
    nested_params: dict[str, Any] = {}
    for key, value in raw_form.items():
        if key.startswith("params[") and key.endswith("]"):
            nested_params[key[len("params[") : -1]] = value
        else:
            form_data[key] = value
    if nested_params:
        form_data["params"] = nested_params
    if task_type_override is not None:
        submitted_task_type = str(form_data.get("task_type") or "").strip().lower()
        if submitted_task_type and submitted_task_type != task_type_override.strip().lower():
            return jsonify({"error": "Path and form task types do not match"}), 400
        form_data["task_type"] = task_type_override

    workspace_payload: dict[str, Any] = {}
    raw_workspace = form_data.pop("workspace", None)
    if raw_workspace is not None:
        # The workspace document is untrusted user input and is later handed to
        # Runner-owned normalization, so it passes the same bounded Core JSON
        # policy as an uploaded JSON file before it is decoded.
        decoded_workspace, workspace_error = parse_bounded_json(raw_workspace)
        if workspace_error is not None:
            message = json_error_message(workspace_error, subject="Workspace JSON")
            return (
                jsonify(
                    {
                        "error": message,
                        "details": [{"code": "workspace_json_invalid", "message": message}],
                    }
                ),
                400,
            )
        workspace_payload = decoded_workspace
        if not isinstance(workspace_payload, dict) or workspace_payload.get("version") != 2:
            return jsonify({"error": "Unsupported workspace document"}), 400

    try:
        submission = TaskSubmissionRequest.model_validate(form_data)
    except ValidationError as exc:
        errors = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return jsonify({"error": "Validation failed", "details": errors}), 400

    task_type = submission.task_type
    try:
        tt, runner = _get_task_type(task_type)
    except KeyError:
        return jsonify({"error": f"Unknown task type: {task_type}"}), 400
    capability_values = workspace_payload.get("capabilities", {})
    if not isinstance(capability_values, dict):
        return jsonify({"error": "Workspace capabilities must be an object"}), 400
    known_capability_ids = {item.id for item in iter_capabilities(tt)}
    if set(capability_values) - known_capability_ids:
        return jsonify({"error": "Workspace contains an unknown capability"}), 400
    pending_capabilities: dict[str, tuple[Any, Any, Any]] = {}
    for capability in iter_capabilities(tt):
        adapter = workspace_backend(capability.plugin)
        if adapter is None:
            continue
        if capability.id not in capability_values:
            return jsonify({"error": "Workspace is missing region state"}), 400
        owned_fields = set(capability.options.get("fields", []))
        if owned_fields & set(submission.params):
            return jsonify({"error": "Region-owned parameters must be submitted through workspace state"}), 400
        # Declarative Core checks above never execute Runner code.  The
        # Runner-owned normalizer/validator entrypoints are only scheduled for
        # real Task preparation, never for the read-only preflight endpoint.
        if not preflight_only:
            pending_capabilities[capability.id] = (capability_values[capability.id], adapter[0], adapter[1])
    coerced_params = submission.coerce_params()
    try:
        task_owner = _resolve_task_owner()
    except RuntimeError:
        logging.exception("Authenticated user has no immutable storage identity")
        return jsonify({"error": "Account storage is not initialized; contact an administrator."}), 503
    workspace_key = task_owner["storage_key"]
    if not _WORKSPACE_KEY_PATTERN.fullmatch(workspace_key):
        return jsonify({"error": "User storage identity is invalid"}), 400

    managedb = current_app.config.get("manage_db")
    infrastructure: dict[str, Any] | None = None
    if managedb is not None:
        enabled = managedb.task_type_is_enabled(task_type)
        if enabled is False:
            return jsonify({"error": f"Task type {task_type!r} is currently disabled"}), 400

    policy = tt.runtime.access_policy
    abuse_scope = getattr(_get_user_db(), "path", "")
    if policy is not None:
        suspension = access_guard.active_suspension(int(g.current_user["id"]), policy.id, abuse_scope)
        if suspension.active:
            already_granted, _ = authorize(policy, current_app.config["user_db"], int(g.current_user["id"]))
            if already_granted:
                access_guard.clear_policy_state(int(g.current_user["id"]), policy.id, abuse_scope)
                suspension = access_guard.SuspensionState(active=False)
        if suspension.active:
            if access_guard.mark_blocked_event(int(g.current_user["id"]), policy.id, abuse_scope):
                _audit_runner_access(
                    _get_user_db(), int(g.current_user["id"]), policy.id, "blocked", "temporary_suspension", tt
                )
            response = jsonify(
                {
                    "error": "Runner access temporarily suspended",
                    "policy_id": policy.id,
                    "retry_after_seconds": max(suspension.retry_after_seconds, 1),
                }
            )
            response.headers["Retry-After"] = str(max(suspension.retry_after_seconds, 1))
            return response, 429
    allowed, access_error = authorize(
        tt.runtime.access_policy, current_app.config["user_db"], int(g.current_user["id"])
    )
    if not allowed:
        if policy is not None:
            state = access_guard.record_denial(int(g.current_user["id"]), policy.id, abuse_scope)
            outcome = "suspended" if state.active else "denied"
            if not state.active or state.newly_suspended:
                _audit_runner_access(
                    _get_user_db(),
                    int(g.current_user["id"]),
                    policy.id,
                    outcome,
                    "temporary_suspension" if state.active else "missing_entitlement",
                    tt,
                )
            elif access_guard.mark_blocked_event(int(g.current_user["id"]), policy.id, abuse_scope):
                _audit_runner_access(
                    _get_user_db(), int(g.current_user["id"]), policy.id, "blocked", "temporary_suspension", tt
                )
            if state.active and not state.newly_suspended:
                response = jsonify(
                    {
                        "error": "Runner access temporarily suspended",
                        "policy_id": policy.id,
                        "retry_after_seconds": max(state.retry_after_seconds, 1),
                    }
                )
                response.headers["Retry-After"] = str(max(state.retry_after_seconds, 1))
                return response, 429
        return jsonify(access_error), 403
    # Admission is based on the same immutable build/live-test evidence shown
    # by runner-status.  Evaluate it before validating or saving uploads so a
    # non-ready Runner cannot create task or scheduler side effects.
    if managedb is not None and managedb.slurm_enabled():
        readiness = resolve_submission_readiness(CONFIG.server_dir, tt.runtime.name)
        if not readiness.ready:
            return (
                jsonify(
                    {
                        "error": "Runner is currently unavailable for new submissions",
                        "runner": tt.runtime.name,
                        "status": readiness.status.value,
                        "reason": readiness.reason_code,
                        "message": readiness.message,
                        "next_action": readiness.next_action,
                    }
                ),
                503,
            )
    # Reject GPU-ineligible users and invalid scheduler configuration before
    # writing uploads or creating a task record.
    if tt.gpus and not g.current_user.get("allow_gpu_use"):
        if policy is not None:
            _audit_runner_access(
                _get_user_db(), int(g.current_user["id"]), policy.id, "denied", "gpu_access_denied", tt
            )
        return jsonify({"error": "GPU access required for this task type. Contact an administrator."}), 403
    if tt.gpus:
        _project_gpu_authorization(int(g.current_user["id"]))
    resource_policy = None
    resource_policies: dict[str, Any] = {}
    try:
        resource_policy, resource_policies = resolve_submission_resources(managedb, tt, runner)
    except ResourceValidationError as exc:
        logging.error("Resource policy rejected submission for %s: %s", task_type, exc)
        return jsonify({"error": "This task type has an invalid resource policy; contact an administrator."}), 503

    uploaded_inputs, upload_error = _validate_input_uploads(task_type)
    if upload_error is not None:
        return upload_error
    quarantined: list[str] = []
    try:
        saved_inputs, metadata, quarantined = _quarantine_uploaded_inputs(
            uploaded_inputs,
            task_type,
        )
        if not preflight_only:
            # Task preparation only: Runner-owned workspace semantics run after
            # Core file security and contract validation, and are never part of
            # the Core-owned preflight boundary.
            normalized_capabilities: dict[str, tuple[dict[str, Any], Any]] = {}
            for capability_id, (raw_value, normalizer, validator) in pending_capabilities.items():
                normalized = normalize_capability(normalizer, raw_value)
                normalized_capabilities[capability_id] = (normalized, validator)
                submission.params.update(normalized.get("params", {}))
            coerced_params = submission.coerce_params()
            for normalized, validator in normalized_capabilities.values():
                if validator is not None:
                    input_paths: dict[str, list[str]] = {}
                    for item in saved_inputs:
                        input_paths.setdefault(item["role"], []).append(item["blob_path"])
                    validate_capability(
                        validator,
                        normalized,
                        {role: tuple(paths) for role, paths in input_paths.items()},
                    )
        md5sum = _derive_task_id(saved_inputs, task_type, coerced_params, workspace_key)
        if managedb is not None and managedb.slurm_enabled():
            readiness_service = current_app.config["infrastructure_readiness"]
            infrastructure = readiness_service.report()
            # Admission is resource-specific: a CPU-only Slurm Task depends on
            # the scheduler/worker/storage path, and only GPU work additionally
            # depends on GPU inventory.  The global aggregate still drives the
            # operator/user overview.
            block = readiness_service.admission_block(requires_gpu=bool(tt.gpus))
            if block is not None:
                # The refusal is an admission decision like any other, so it is
                # reported in the same bounded vocabulary instead of only as
                # response text a client has to parse.
                emit_event(
                    "resource.admission.denied",
                    level="WARNING",
                    request_id=g.request_id,
                    task_type=task_type,
                    runner_family=tt.runtime.name,
                    reason_code=AdmissionReason.INFRASTRUCTURE_UNAVAILABLE.value,
                )
                return (
                    jsonify(
                        {
                            "error": "Compute infrastructure is currently unavailable for new submissions",
                            "details": [
                                {
                                    "code": "infrastructure_unavailable",
                                    "message": (
                                        f"Required infrastructure component {block['component']!r} "
                                        "is unavailable or stale for this Task resource class."
                                    ),
                                }
                            ],
                        }
                    ),
                    503,
                )
        existing_task = task_store.get_task(md5sum)
        existing_response = _existing_upload_response(existing_task, md5sum)
        if existing_response is not None and not preflight_only:
            return existing_response

        gpu_credit = None
        user_id = int(g.current_user["id"])
        envelope = task_store.resource_envelope(user_id)
        # Durable storage is a submission-wide admission concern, not a GPU one:
        # it is the same envelope for every Task, and a user over their soft
        # ceiling is refused a new submission of any kind.  The overrun is
        # reported with its own reason code so the client can explain it.  A
        # result that already crossed the ceiling keeps its scientific value —
        # this restricts *later* admission only.
        if envelope.storage.over_soft_limit:
            emit_event(
                "resource.admission.denied",
                level="WARNING",
                request_id=g.request_id,
                task_type=task_type,
                runner_family=tt.runtime.name,
                user_id=user_id,
                reason_code=AdmissionReason.STORAGE_SOFT_LIMIT.value,
            )
            return (
                jsonify(
                    {
                        "error": "Durable storage quota exceeded",
                        "details": [
                            {
                                "code": "storage_soft_limit_exceeded",
                                "message": (
                                    "Delete or archive retained results before submitting "
                                    "new compute."
                                ),
                            }
                        ],
                    }
                ),
                403,
            )
        if tt.gpus:
            try:
                gpu_credit = task_store.require_compute_entitlement(user_id)
            except GPUCreditUnavailableError:
                emit_event(
                    "resource.admission.denied",
                    level="WARNING",
                    request_id=g.request_id,
                    task_type=task_type,
                    runner_family=tt.runtime.name,
                    user_id=user_id,
                    gpu_seconds=0,
                    reason_code=AdmissionReason.COMPUTE_EXHAUSTED.value,
                )
                return (
                    jsonify(
                        {
                            "error": "GPU credit balance is exhausted for the current UTC month",
                            "details": [
                                {
                                    "code": "gpu_credit_exhausted",
                                    "message": "A positive GPU credit balance is required for a new allocation.",
                                }
                            ],
                        }
                    ),
                    403,
                )
            emit_event(
                "resource.admission.checked",
                request_id=g.request_id,
                task_type=task_type,
                runner_family=tt.runtime.name,
                user_id=user_id,
                gpu_seconds=max(0, int(gpu_credit["remaining_gpu_seconds"])),
                reason_code=AdmissionReason.ADMITTED.value,
            )

        # ponytail: per-user cap on active tasks — the expensive resource is the
        # Celery/Docker queue, not the HTTP layer. Raise this if legitimate batch
        # work routinely reaches it.
        max_active_tasks_per_user = 5
        if (
            existing_response is None
            and task_store.count_user_active_tasks(int(g.current_user["id"])) >= max_active_tasks_per_user
        ):
            return (
                jsonify(
                    {
                        "error": "Too many pending or running tasks. "
                        "Please wait for existing tasks to complete before submitting new ones."
                    }
                ),
                429,
            )
        emit_event(
            "preflight.passed",
            request_id=g.request_id,
            task_type=task_type,
            runner_family=tt.runtime.name,
        )
        if preflight_only:
            return jsonify(
                TaskPreflightResult(
                    valid=True,
                    security=PreflightPhase(status="passed"),
                    contract=PreflightPhase(status="passed"),
                    admission=PreflightAdmission(
                        allowed=True,
                        runner_ready=True if infrastructure else None,
                        infrastructure_ready=True if infrastructure else None,
                        infrastructure_status=infrastructure["status"] if infrastructure else None,
                        infrastructure_stale=infrastructure["stale"] if infrastructure else None,
                        scheduler_capacity=(
                            infrastructure["summary"]["scheduler"].get("capacity", "UNKNOWN")
                            if infrastructure
                            else None
                        ),
                        gpu_capacity=(
                            infrastructure["summary"]["gpu"].get("capacity", "UNKNOWN")
                            if infrastructure
                            else None
                        ),
                        gpu_credit_sufficient=True if gpu_credit else None,
                        gpu_credit_remaining_seconds=(gpu_credit["remaining_gpu_seconds"] if gpu_credit else None),
                    ),
                    normalized_params=coerced_params,
                    inputs=[
                        {"role": item["role"], "format": item["format"], "path": item["relative_path"]}
                        for item in saved_inputs
                    ],
                ).model_dump(exclude_none=True)
            )
        _promote_preflight_inputs(saved_inputs)
    except InputPreflightError as exc:
        return _input_preflight_error_response(exc)
    except WorkspaceValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        _cleanup_quarantine(quarantined)

    # Build entities — one list for files and params together.
    entities: list[dict[str, Any]] = []

    owned_task = {"md5sum": md5sum, **task_owner}
    snapshot_root = _safe_join(app.config["storage_resolver"].get_input_root(owned_task), "inputs")
    virtual_root = "/workspace"
    role_indexes: dict[str, int] = {}
    for item in saved_inputs:
        role_indexes[item["role"]] = role_indexes.get(item["role"], 0) + 1
        role = _role_by_name(tt, item["role"])
        entities.append(
            {
                "name": item["role"] if role and role.maximum == 1 else f"{item['role']}_{role_indexes[item['role']]}",
                "type": "file",
                "role": item["role"],
                "value": item["original_name"],
                "verified_value": item["relative_path"],
                "relative_path": item["relative_path"],
                "mounted": f"{virtual_root}/inputs/{item['role']}/{item['relative_path']}",
                "hash": item["hash"],
                "size": item["size"],
                "format": item["format"],
                "logical_type": role.type if role else "file",
                # The receipt is the validation decision bound to this item's
                # exact immutable bytes.  This is the key the worker reads to
                # prove the snapshot it will execute is this byte stream; a
                # status projection would be a second, weaker assertion.
                "validation_receipt": item["validation_receipt"],
                "snapshot_path": _safe_join(snapshot_root, item["role"], *item["relative_path"].split("/")),
                "snapshot_root": snapshot_root,
                "workspace_key": workspace_key,
            }
        )

    # Param entities — raw form value vs pydantic-coerced verified_value
    known_params = {p.name: p for p in tt.params}
    for key, verified in coerced_params.items():
        param = known_params.get(key)
        if param is None:
            schema_type = (tt.schema.get("properties", {}).get(key, {}) or {}).get("type", "string")
            param = type(
                "SchemaParam",
                (),
                {
                    "name": key,
                    "type": {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}.get(
                        schema_type, "str"
                    ),
                },
            )()
        raw = submission.params.get(key, verified)
        entities.append(
            {
                "name": key,
                "type": param.type,
                "value": raw,
                "verified_value": verified,
            }
        )

    input_form = {
        "user": metadata["username"],
        "workspace_key": workspace_key,
        "virtual_root": virtual_root,
        "snapshot_root": snapshot_root,
        "submitted_at": datetime.now(tz=timezone.utc).isoformat(),
        "entities": entities,
        "resource_policy": resource_policy.public_dict() if resource_policy is not None else None,
        "resource_policies": {name: policy.public_dict() for name, policy in resource_policies.items()},
        "workspace": workspace_payload,
        "request_id": g.request_id,
    }

    # Runner protocol v3: the immutable snapshot carries task.json — the
    # single manifest every runner reads (params + file paths).  No
    # user-shaped data travels through environment variables anymore.
    manifest_inputs: dict[str, list[dict[str, Any]]] = {role.name: [] for role in tt.inputs}
    for entity in entities:
        if entity["type"] != "file":
            continue
        manifest_inputs[entity["role"]].append(
            {
                "original_name": entity["value"],
                "path": entity["mounted"],
                "relative_path": entity["relative_path"],
                "format": entity["format"],
                "logical_type": entity["logical_type"],
                "sha256": entity["hash"],
                "size": entity["size"],
                "validation_receipt": entity["validation_receipt"],
            }
        )
    # Runner protocol v4: additive.  ``params`` and ``inputs`` are byte-for-byte
    # what they were, so a runner that ignores the new keys behaves identically;
    # the new keys project what the owning manifest declared (execution shape,
    # rollout stage, fallback vocabulary) and what the server has learned for
    # this runner family.
    #
    # ``runtime_bundle`` pins the exact immutable snapshot of REvoCompute-owned
    # executable code this task will execute.  It is resolved from the
    # deployment's activation index here, at submission, and never re-resolved
    # at launch: a task queued under bundle A keeps executing A even if bundle B
    # is activated before Slurm starts it.  ``resolve_for_submission`` raises
    # when the family declares an overlay but its bound snapshot is missing, so
    # a submission never silently becomes one that cannot launch.
    try:
        bundle_digest = runtime_bundle.resolve_for_submission(
            CONFIG.runtime_bundle_root,
            runtime_bundle.load_index(CONFIG.runtime_bundle_root),
            tt.runtime.name,
            declares_overlay=bool(tt.runtime.runtime_overlay),
        )
    except runtime_bundle.RuntimeBundleError as exc:
        return jsonify({"error": f"This Runner is not ready to accept submissions: {exc}"}), 503
    # The digest is also recorded on the task row, because the task store is the
    # only durable index of "a Task that can still be launched references this
    # bundle" — retention reads it so a queued Task's runtime code is never
    # pruned before the Task runs.
    input_form["runtime_bundle_sha256"] = bundle_digest
    task_manifest = {
        "version": 4,
        "task_id": md5sum,
        "task_type": task_type,
        "params": {e["name"]: e["verified_value"] for e in entities if e["type"] != "file"},
        "inputs": manifest_inputs,
        "execution": asdict(tt.execution),
        "execution_queue": tt.execution_queue.to_dict(),
        "resource_adaptation": tt.resource_adaptation.to_dict(),
        "resource_guidance": observations_for_guidance(
            tt.runtime.name, tt.resource_adaptation, store=task_store
        ),
        "runtime_bundle_sha256": bundle_digest,
    }
    # Claim the Task ID BEFORE destroying or rebuilding any content-derived
    # directory.  The input/output roots are keyed by the ID, so preparation is
    # only safe once this request owns the ID: two concurrent first submissions
    # of identical content would otherwise both find no row, both rmtree-and-
    # rebuild the same tree, and only then have one lose the race — leaving the
    # winner's snapshot destroyed by the loser.  Ownership comes from the claim
    # below alone; the ``get_task`` above only answered a row that already
    # existed, and a row can appear between it and the claim.
    claim = task_store.claim_task_preparation(md5sum)
    if not claim.owned():
        # The winner owns the ID, the row is settled, or it was dispatched.
        return _existing_upload_response(claim.row, md5sum) or _submission_in_progress_response(md5sum, claim)
    # The row is written first, so the claim covers the whole mutate-then-
    # dispatch window: a request that dies mid-materialization leaves a
    # ``pending`` row no dispatch is en route for, which is the state the next
    # request's claim recovers.
    base_record = _prepare_task_record(
        md5sum,
        saved_inputs,
        metadata,
        task_type=task_type,
        input_form=input_form,
        task_owner=task_owner,
    )
    try:
        task_store.upsert_task(md5sum, refuse_reserved=True, **base_record, status="pending", error=None)
    except TaskIdReservedError:
        # A named task took the ID between the claim and here.  Answer it; do
        # not prepare, do not dispatch, and do not disturb its tree.
        task_store.release_task_preparation(md5sum, token=claim.token)
        racer = task_store.get_task(md5sum)
        return _existing_upload_response(racer, md5sum) or _task_submission_response(md5sum, "pending", 202)
    try:
        _materialize_task_tree(md5sum, saved_inputs, task_manifest, task_owner)
    except BaseException as exc:
        # The row is left ``failed`` with no dispatch state and the claim is
        # released, so the identical resubmission re-claims the ID and re-enters
        # this path rather than waiting out the abandoned window.
        logging.exception("Task preparation failed for %s", md5sum)
        task_store.update_task(md5sum, status="failed", finished_at=time.time(), error=f"Task preparation failed: {exc}")
        task_store.release_task_preparation(md5sum, token=claim.token)
        return jsonify({"error": "Task preparation failed; please retry."}), 500

    # Reserve this submission's entitlement before dispatch.  The hold is taken
    # after the preparation claim and the row write, and it is recorded in the
    # ledger as what *this Task* owes, so a concurrent submission competing for
    # the same final entitlement loses here instead of both being dispatched.
    # The hold is taken on the class-agnostic scope: the allowance is one
    # deployment budget, and the requested GRES class is preserved on the hold
    # rather than opening a per-class balance.  A CPU-only Task holds nothing.
    if tt.gpus:
        reservation = task_store.reserve_compute_admission(
            user_id=int(g.current_user["id"]),
            task_id=md5sum,
            gres=(resource_policy.gres if resource_policy is not None else None) or "",
        )
        if not reservation["allowed"]:
            task_store.release_task_preparation(md5sum, token=claim.token)
            task_store.update_task(
                md5sum,
                status="failed",
                finished_at=time.time(),
                error="Task not admitted: the remaining entitlement is already reserved",
            )
            emit_event(
                "resource.admission.denied",
                level="WARNING",
                request_id=g.request_id,
                task_id=md5sum,
                task_type=task_type,
                runner_family=tt.runtime.name,
                user_id=int(g.current_user["id"]),
                reason_code=reservation["reason_code"],
            )
            return (
                jsonify(
                    {
                        "error": "GPU credit balance is exhausted for the current UTC month",
                        "details": [
                            {
                                "code": "gpu_credit_exhausted",
                                "message": "A positive GPU credit balance is required for a new allocation.",
                            }
                        ],
                    }
                ),
                403,
            )
        emit_event(
            "resource.admission.reserved",
            request_id=g.request_id,
            task_id=md5sum,
            task_type=task_type,
            runner_family=tt.runtime.name,
            user_id=int(g.current_user["id"]),
            gpu_seconds=int(reservation["quantity"]),
            reason_code=reservation["reason_code"],
        )

    try:
        async_result = run_compute_task.apply_async(
            args=[md5sum],
            kwargs={"task_type": task_type, "request_id": g.request_id},
        )
    except Exception:
        logging.exception("Failed to submit compute task %s to Celery", md5sum)
        error_message = "Task queue unavailable — please try again later"
        finished_at = time.time()
        # A dispatch that never reached the queue still releases its hold: the
        # Task is failed, so its reservation must not keep entitlement the user
        # cannot use.  The release is idempotent, so the worker's own release
        # after a successful allocation is unaffected.
        task_store.release_reservation(
            task_id=md5sum, reason_code=ReservationReason.DISPATCH_FAILED.value, at=finished_at
        )
        failed_task = task_store.get_task(md5sum) or dict(md5sum=md5sum, **base_record)
        _finalize_failed_results(failed_task, error_message, finished_at=finished_at)
        _cleanup_task_workspace(failed_task)
        task_store.update_task(
            md5sum,
            status="failed",
            finished_at=finished_at,
            error=error_message,
        )
        emit_event(
            "task.failed",
            level="ERROR",
            request_id=g.request_id,
            task_id=md5sum,
            task_type=task_type,
            runner_family=tt.runtime.name,
            reason_code="task_queue_unavailable",
        )
        return jsonify({"error": error_message}), 503
    task_store.update_task(md5sum, celery_task_id=async_result.id)
    # The claim's work is done: the row now carries dispatch state, so every
    # later request reads it as dispatched whether or not the claim survives.
    task_store.release_task_preparation(md5sum, token=claim.token)
    emit_event(
        "task.submitted",
        request_id=g.request_id,
        task_id=md5sum,
        task_type=task_type,
        runner_family=tt.runtime.name,
        celery_task_id=str(async_result.id),
    )
    if policy is not None:
        _audit_runner_access(_get_user_db(), int(g.current_user["id"]), policy.id, "allowed", "task_accepted", tt)

    return _task_submission_response(md5sum, "pending", 302)


@app.route("/compute/api/running/<md5sum>", methods=["GET"])
@optional_user
def run_gremlin(md5sum):
    md5sum = _normalize_task_id(md5sum)
    if md5sum is None:
        return jsonify({"status": "bad_request", "message": "Invalid task id"}), 400
    task = task_store.get_task(md5sum)
    if not task:
        return jsonify({"status": "not_found", "md5sum": md5sum}), 404
    if not _task_access_allowed(task):
        return _task_not_found(md5sum)

    status = task["status"]
    payload = _task_follow_up_payload(md5sum, str(status))
    if status == "finished":
        return jsonify(payload), 200
    if status == "failed":
        error = _sanitize_task_error(task, task.get("error")) if _task_full_results_allowed(task) else "Task failed"
        return jsonify({**payload, "error": error}), 200
    if status in ("running", "queued"):
        return jsonify(payload), 202
    if status == "pending":
        return jsonify(payload), 202
    if status == "cancelled":
        return jsonify(payload), 200
    if status in task_store.CLEANUP_CLAIM_STATUSES:
        return jsonify(payload), 202
    if status in task_store.CLEANUP_STATUSES:
        return jsonify(payload), 200
    if status == "deleted:finshed":
        return jsonify(payload), 200
    if status == "deleted:cancel":
        return jsonify(payload), 200

    return (
        jsonify({"status": "unknown", "md5sum": md5sum, "error": "Invalid task status"}),
        500,
    )


@app.route("/compute/api/results/<md5sum>", methods=["GET"])
@optional_user
def get_results(md5sum):
    md5sum = _normalize_task_id(md5sum)
    if md5sum is None:
        return jsonify({"status": "bad_request", "message": "Invalid task id"}), 400
    task = task_store.get_task(md5sum)
    if not task:
        return jsonify({"status": "not_found", "md5sum": md5sum}), 404
    if not _task_access_allowed(task):
        return _task_not_found(md5sum)

    if task["status"] not in {"finished", "failed"}:
        return redirect(f"/compute/api/running/{md5sum}", code=302)

    # The manifest is the publication root of trust, so it is read through the
    # canonical bounded verified authority -- never a plain pathname open, which
    # would let a linked or replaced manifest serve a different publication.
    manifest = current_app.config["storage_resolver"].load_manifest(task)
    if manifest is None:
        # A result that exists but is not readable says why: an unanchored
        # (pre-anchor) result and a replaced one are different operator problems,
        # and neither is answered with a bare not-found.
        report = _publication_report(task)
        return (
            jsonify(
                {
                    "status": "error",
                    "md5sum": md5sum,
                    "message": report["reason"] or "result manifest not found",
                    "result_publication": report["state"],
                }
            ),
            404,
        )

    archive_ready = os.path.isfile(_task_zip_path(task))
    payload = dict(manifest)
    full_results = _task_full_results_allowed(task)
    if not full_results:
        payload["artifacts"] = [
            artifact for artifact in payload.get("artifacts", []) if _task_artifact_access_allowed(task, artifact)
        ]
        visible_paths = {artifact["path"] for artifact in payload["artifacts"]}
        visible_views = []
        for view in payload.get("views", []):
            sources = {
                name: [path for path in paths if path in visible_paths]
                for name, paths in view.get("sources", {}).items()
            }
            if any(sources.values()):
                visible_views.append({**view, "sources": sources})
        payload["views"] = visible_views
        result = payload.get("result")
        if isinstance(result, dict) and isinstance(result.get("files"), dict):
            payload["result"] = {
                **result,
                "files": {
                    file_id: [item for item in files if _task_artifact_access_allowed(task, item)]
                    for file_id, files in result["files"].items()
                },
            }
    return jsonify(
        project_result_manifest(
            payload,
            task_id=md5sum,
            status=task["status"],
            terminal=str(task["status"]).strip().lower() in task_store.STOP_POLLING_STATUSES,
            error=_sanitize_task_error(task, task.get("error"))
            if task["status"] == "failed" and full_results
            else None,
            archive={
                "ready": archive_ready and full_results,
                "request_url": f"/compute/api/results/{md5sum}/archive" if full_results else None,
                "download_url": f"/compute/api/download/{md5sum}" if archive_ready and full_results else None,
            },
        )
    )


@app.route("/compute/api/results/<md5sum>/files/<file_id>", methods=["GET"])
@optional_user
def get_result_logical_file(md5sum: str, file_id: str):
    """Serve a single Expected File Tree identity, never a guessed path."""
    normalized = _normalize_task_id(md5sum)
    if normalized is None or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", file_id):
        return jsonify({"error": "Result file not found"}), 404
    task = task_store.get_task(normalized)
    if task is None or not _task_access_allowed(task):
        return jsonify({"error": "Result file not found"}), 404
    # The manifest authorizes which identities exist, so it is read through the
    # canonical bounded verified manifest reader — never a plain pathname open,
    # which would let a replaced or linked manifest name a different identity.
    manifest = current_app.config["storage_resolver"].load_manifest(task)
    if manifest is None:
        return jsonify({"error": "Result file not found"}), 404
    files = manifest.get("result", {}).get("files", {}).get(file_id, [])
    try:
        index = int(request.args.get("index", "0"))
    except ValueError:
        index = -1
    if index < 0 or index >= len(files):
        return jsonify({"error": "Result file not found"}), 404
    return get_result_artifact(md5sum, files[index]["path"])


@app.route("/compute/api/results/<md5sum>/storyboard/<path:asset>", methods=["GET"])
@optional_user
def get_result_storyboard_asset(md5sum: str, asset: str):
    """Serve an explicitly declared, deployment-controlled runner asset."""
    normalized = _normalize_task_id(md5sum)
    task = task_store.get_task(normalized) if normalized else None
    if task is None or not _task_access_allowed(task):
        return jsonify({"error": "Storyboard not found"}), 404
    try:
        task_type, _ = get_task_type(task.get("task_type") or default_task_type())
        declaration = storyboard_declaration(
            task_type, CONFIG.server_dir, set(expected_file_tree(task_type, CONFIG.server_dir))
        )
        root = runner_root(task_type, CONFIG.server_dir) / "storyboard"
        requested = asset.replace("\\", "/").strip("/")
        if (
            not declaration
            or requested != declaration["entrypoint"]
            or not requested
            or any(part in {"", ".", ".."} for part in requested.split("/"))
        ):
            abort(404)
        target = (root / requested).resolve()
        if not target.is_file() or not target.is_relative_to(root.resolve()) or target.suffix != ".js":
            abort(404)
    except (KeyError, ResultContractError):
        abort(404)
    response = send_from_directory(root, requested, mimetype="text/javascript")
    response.headers["Cache-Control"] = "private, no-cache"
    return response


def _result_artifact(task: dict[str, Any], relative_path: str) -> tuple[str, Any, dict[str, Any]] | None:
    """Resolve only regular files published by the task's finalized manifest.

    Returns the path, the verified open descriptor, and the manifest entry.  The
    descriptor's bytes and identity were just checked against the manifest, so a
    consumer must consume *it* rather than reopen ``path``: after publication
    identity has been verified, a pathname reopen would let a replaced file serve
    bytes that never satisfied the manifest identity.
    """
    resolved = current_app.config["storage_resolver"].resolve_artifact(task, relative_path)
    if resolved is None:
        return None
    stream = resolved.pop("verified_stream")
    return resolved.pop("physical_path"), stream, resolved


def _verified_payload(stream: Any) -> Response:
    """Stream a verified descriptor directly, never reopening its pathname.

    Everything — full body, HEAD, and a single bounded ``Range`` — reads from the
    one verified descriptor, so no later pathname open can substitute different
    bytes.  Range support lives here rather than in ``send_from_directory``
    because that helper would reopen the pathname that was just verified.
    """
    size = os.fstat(stream.fileno()).st_size
    raw_range = request.headers.get("Range", "")
    if request.method == "HEAD":
        stream.close()
        response = Response(status=200)
        response.headers["Content-Length"] = str(size)
        return response
    if raw_range:
        # ``parse_range_header`` takes no resource length: the length is applied
        # by ``range_for_length``, which is what resolves a suffix range and
        # reports an unsatisfiable one as ``None``.
        parsed = parse_range_header(raw_range)
        if parsed is not None and len(parsed.ranges) == 1:
            resolved_range = parsed.range_for_length(size)
            if resolved_range is None:
                stream.close()
                response = Response(status=416)
                response.headers["Content-Range"] = f"bytes */{size}"
                return response
            start, end = resolved_range
            stream.seek(start)
            response = Response(_BoundedStream(stream, end - start), status=206, direct_passthrough=True)
            response.headers["Content-Range"] = f"bytes {start}-{end - 1}/{size}"
            response.headers["Content-Length"] = str(end - start)
            return response
    # The whole body is streamed through the same bounded reader: the read size
    # is a chunk constant, never the artifact size, so a large artifact is never
    # read with one artifact-sized request.
    response = Response(_BoundedStream(stream, size), direct_passthrough=True)
    response.headers["Content-Length"] = str(size)
    return response


class _BoundedStream:
    """Yield at most *length* bytes from a verified descriptor, then close it.

    Each read is bounded by the chunk constant rather than the total length, so
    the bytes of a large artifact move in bounded chunks.
    """

    def __init__(self, stream: Any, length: int):
        self._stream = stream
        self._remaining = length

    def __iter__(self):
        while self._remaining > 0:
            chunk = self._stream.read(min(_STREAM_CHUNK_BYTES, self._remaining))
            if not chunk:
                break
            self._remaining -= len(chunk)
            yield chunk

    def close(self):
        self._stream.close()


@app.route("/compute/api/results/<md5sum>/artifacts/<path:relative_path>", methods=["GET"])
@optional_user
def get_result_artifact(md5sum: str, relative_path: str):
    md5sum = _normalize_task_id(md5sum)
    if md5sum is None:
        return jsonify({"error": "Invalid task id"}), 400
    task = task_store.get_task(md5sum)
    if task is None:
        return jsonify({"status": "not_found", "md5sum": md5sum}), 404
    if not _task_access_allowed(task):
        return _task_not_found(md5sum)
    resolved = _result_artifact(task, relative_path)
    if resolved is None:
        return jsonify({"error": "Artifact not found"}), 404
    path, stream, artifact = resolved
    if not _task_artifact_access_allowed(task, artifact):
        stream.close()
        return jsonify({"error": "Artifact not found"}), 404
    # Artifacts are untrusted runner output — default to attachment so they
    # are never rendered same-origin.  `?download=1` still forces a download
    # and `?download=0` explicitly opts back into inline rendering.
    as_attachment = request.args.get("download", "1") in {"1", "true", "yes"}
    # Delivery always consumes the verified descriptor.  ``RESULT_DOWNLOAD_MODE``
    # is accepted for deployment compatibility, but X-Accel-Redirect is NOT used
    # here: the offload would have nginx reopen this mutable pathname, which
    # could serve bytes that never satisfied the manifest identity.  Descriptor-
    # bound delivery therefore replaces the offload on this endpoint; a redesign
    # that could keep the offload needs an immutable publication store, which is
    # out of scope for this change.
    response = _verified_payload(stream)
    response.mimetype = artifact.get("media_type") or "application/octet-stream"
    response.headers.set(
        "Content-Disposition",
        "attachment" if as_attachment else "inline",
        filename=os.path.basename(path),
    )
    response.headers["Cache-Control"] = "private, no-store"
    # Defense in depth: even an explicitly-inline artifact runs no scripts.
    response.headers["Content-Security-Policy"] = "sandbox"
    return response


@app.route("/compute/api/results/<md5sum>/ndarrays/<path:relative_path>", methods=["GET"])
@optional_user
def get_result_ndarray(md5sum: str, relative_path: str):
    """Return one complete bounded projection from a manifest-approved artifact."""
    md5sum = _normalize_task_id(md5sum)
    if md5sum is None:
        return jsonify({"error": "Invalid task id"}), 400
    task = task_store.get_task(md5sum)
    if task is None:
        return jsonify({"status": "not_found", "md5sum": md5sum}), 404
    if not _task_access_allowed(task):
        return _task_not_found(md5sum)
    resolved = _result_artifact(task, relative_path)
    if resolved is None:
        return jsonify({"error": "Array artifact not found"}), 404
    _path, stream, artifact = resolved
    if not _task_artifact_access_allowed(task, artifact):
        stream.close()
        return jsonify({"error": "Array artifact not found"}), 404
    if set(request.args) - {"key", "kind", "max_elements"}:
        stream.close()
        return jsonify({"error": "Invalid array query"}), 400

    def bounded_integer(name: str, default: int) -> int | None:
        values = request.args.getlist(name)
        raw = values[0] if values else str(default)
        if len(values) > 1 or re.fullmatch(r"(?:0|[1-9][0-9]{0,18})", raw) is None:
            return None
        return int(raw)

    max_elements = bounded_integer("max_elements", 0)
    keys = request.args.getlist("key")
    kinds = request.args.getlist("kind")
    if (
        max_elements is None
        or max_elements < 1
        or max_elements > MAX_PROJECTION_ELEMENTS
        or len(keys) > 1
        or len(kinds) > 1
    ):
        stream.close()
        return jsonify({"error": "Array projection is outside allowed bounds"}), 400
    key = keys[0] if keys else None
    kind = kinds[0] if kinds else "numeric"
    try:
        # The projection parses from the verified descriptor itself, so a file
        # replaced after publication identity was checked can never be projected:
        # after publication identity has been verified, a consumer must consume
        # the verified object, not reopen its pathname.
        return jsonify(
            read_array_projection(
                stream, name=relative_path, key=key, kind=kind, max_elements=max_elements
            )
        )
    except ArrayAccessError as error:
        return jsonify({"error": str(error)}), 400
    finally:
        stream.close()


@app.route("/compute/api/results/<md5sum>/tables/<path:relative_path>", methods=["GET"])
@optional_user
def get_result_table(md5sum: str, relative_path: str):
    """Return a bounded, correctly parsed page from a manifest table artifact."""
    md5sum = _normalize_task_id(md5sum)
    if md5sum is None:
        return jsonify({"error": "Invalid task id"}), 400
    task = task_store.get_task(md5sum)
    if task is None:
        return jsonify({"status": "not_found", "md5sum": md5sum}), 404
    if not _task_access_allowed(task):
        return _task_not_found(md5sum)
    resolved = _result_artifact(task, relative_path)
    if resolved is None:
        return jsonify({"error": "Table artifact not found"}), 404
    _path, stream, artifact = resolved
    if not _task_artifact_access_allowed(task, artifact):
        stream.close()
        return jsonify({"error": "Table artifact not found"}), 404
    declared_table = artifact.get("preview") == "table"
    if not declared_table:
        manifest = current_app.config["storage_resolver"].load_manifest(task) or {}
        logical_files = manifest.get("result", {}).get("files", {})
        declared_table = any(
            item.get("path") == artifact.get("path") and item.get("logical_type") == "table"
            for files in logical_files.values()
            for item in files
        )
    if not declared_table:
        stream.close()
        return jsonify({"error": "Artifact is not a table"}), 400
    try:
        offset = int(request.args.get("offset", 0))
        limit = int(request.args.get("limit", 100))
    except ValueError:
        stream.close()
        return jsonify({"error": "Invalid table page"}), 400
    if offset < 0 or offset > 10000 or limit < 1 or limit > 500:
        stream.close()
        return jsonify({"error": "Table page is outside allowed bounds"}), 400
    delimiter = "\t" if relative_path.lower().endswith(".tsv") else ","

    def row_cost(row: list[str], max_columns: int) -> int:
        if len(row) > max_columns:
            raise ValueError("Table row exceeds preview limits")
        cost = 2 + max(0, len(row) - 1)
        for cell in row:
            if len(cell.encode("utf-8")) > MAX_TABLE_CELL_BYTES:
                raise ValueError("Table cell exceeds preview limits")
            cost += len(json.dumps(cell, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
        return cost

    try:
        # The verified descriptor stays open for the whole parse, so the page is
        # read from the same inode whose identity the manifest approved.
        with stream, io.TextIOWrapper(stream, encoding='utf-8', newline='') as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            columns = next(reader, [])
            # A matrix page carries one extra leading column of row labels beside its
            # values, so the matrix cap allows that label column on top of the cap
            # itself; a plain preview keeps its tighter width limit.
            max_columns = (512 + 1) if request.args.get("matrix") == "1" else 100
            page_bytes = _TABLE_PAGE_ENVELOPE_BYTES + row_cost(columns, max_columns)
            if page_bytes > MAX_TABLE_PAGE_BYTES:
                raise ValueError("Table page exceeds the response byte limit")
            rows = []
            has_more = False
            for index, row in enumerate(reader):
                if index < offset:
                    continue
                if len(rows) == limit:
                    has_more = True
                    break
                cost = row_cost(row, max_columns)
                if page_bytes + cost > MAX_TABLE_PAGE_BYTES:
                    raise ValueError("Table page exceeds the response byte limit")
                page_bytes += cost
                rows.append(row)
    except (OSError, UnicodeError, csv.Error, ValueError):
        stream.close()
        logging.exception("Table preview failed for task %s artifact %s", md5sum, relative_path)
        return jsonify({"error": "Table could not be previewed"}), 400
    return jsonify({"columns": columns, "rows": rows, "offset": offset, "limit": limit, "has_more": has_more})


@app.route("/compute/api/results/<md5sum>/archive", methods=["POST"])
@login_required
def request_results_archive(md5sum: str):
    if _blocked := require_bearer_auth():
        return _blocked
    md5sum = _normalize_task_id(md5sum)
    if md5sum is None:
        return jsonify({"error": "Invalid task id"}), 400
    task = task_store.get_task(md5sum)
    if task is None:
        return jsonify({"status": "not_found", "md5sum": md5sum}), 404
    if not _task_full_results_allowed(task):
        return _task_not_found(md5sum)
    if task["status"] not in {"finished", "failed"}:
        return jsonify({"error": "Results are not ready"}), 409
    # Building a ZIP is a publication from the same authority, so a result the
    # reader refuses cannot be packed: the caller gets the bounded state and the
    # reason instead of an archive assembled from a quarantine.
    publication = _result_publication_state(task)
    if publication != PUBLICATION_AVAILABLE:
        return _publication_refusal_response(md5sum, publication)
    if os.path.isfile(_task_zip_path(task)):
        return jsonify({"status": "ready", "download_url": f"/compute/api/download/{md5sum}"}), 200
    async_result = build_results_archive.apply_async(args=[md5sum])
    return jsonify({"status": "building", "job_id": async_result.id, "md5sum": md5sum}), 202


@app.route("/compute/api/download/<md5sum>", methods=["GET"])
@login_required
def download_results(md5sum):
    md5sum = _normalize_task_id(md5sum)
    if md5sum is None:
        return jsonify({"status": "bad_request", "message": "Invalid task id"}), 400
    task = task_store.get_task(md5sum)
    if not task:
        return jsonify({"status": "not_found", "md5sum": md5sum}), 404
    if not _task_full_results_allowed(task):
        return _task_not_found(md5sum)

    if task["status"] not in {"finished", "failed"}:
        return (
            jsonify(
                {
                    "status": "error",
                    "md5sum": md5sum,
                    "message": "results are not ready",
                }
            ),
            400,
        )

    # Serving a cached ZIP is the same publication decision as building one: a
    # result Core's reader refuses is refused here too.  The cached archive may
    # predate the publication anchor, so "the bytes are on disk" never decides
    # this -- the canonical state does, and a quarantined ZIP is not served.
    publication = _result_publication_state(task)
    if publication != PUBLICATION_AVAILABLE:
        return _publication_refusal_response(md5sum, publication)

    zip_filename = _task_zip_path(task)
    if not os.path.exists(zip_filename):
        return (
            jsonify(
                {
                    "status": "not_requested",
                    "md5sum": md5sum,
                    "message": "Request the optional archive first",
                    "request_url": f"/compute/api/results/{md5sum}/archive",
                }
            ),
            409,
        )

    if app.config["RESULT_DOWNLOAD_MODE"] == "nginx":
        archive_name = os.path.relpath(zip_filename, app.config["RESULTS_FOLDER"]).replace(os.sep, "/")
        response = Response(status=200, mimetype="application/zip")
        response.headers["X-Accel-Redirect"] = f"/_protected_results/{archive_name}"
        response.headers.set("Content-Disposition", "attachment", filename=_task_zip_download_name(task))
        response.headers["Cache-Control"] = "private, no-store"
        return response

    return send_from_directory(
        os.path.dirname(zip_filename),
        os.path.basename(zip_filename),
        as_attachment=True,
        download_name=_task_zip_download_name(task),
    )


@app.route("/compute/api/cancel/<md5sum>", methods=["POST"])
@login_required
def cancel_task(md5sum):
    if _blocked := require_bearer_auth():
        return _blocked
    md5sum = _normalize_task_id(md5sum)
    if md5sum is None:
        return jsonify({"status": "bad_request", "message": "Invalid task id"}), 400
    task = task_store.get_task(md5sum)
    if not task:
        return jsonify({"status": "not_found", "md5sum": md5sum}), 404
    if not _task_mutation_allowed(task):
        return _task_not_found(md5sum)

    if task["status"] not in {"pending", "queued", "running"}:
        return (
            jsonify({"error": "Task cannot be cancelled as it is not pending or running"}),
            400,
        )

    now = time.time()
    started_at = task.get("started_at")
    walltime = (now - started_at) if started_at else None
    if not task_store.claim_task_cancellation(
        md5sum,
        finished_at=now,
        walltime=walltime,
        error="Task cancelled by user",
    ):
        return jsonify({"error": "Task state changed before cancellation"}), 409
    task = task_store.get_task(md5sum) or task

    # Claim cancellation in the database before asking the worker to stop
    # resources, so a workflow cannot launch its next stage in between.
    cancel_compute_resources.delay(
        slurm_job_id=str(task["slurm_job_id"]) if task.get("slurm_job_id") else None,
        container_id=str(task["container_id"]) if task.get("container_id") else None,
    )

    celery_id = task.get("celery_task_id")
    if celery_id:
        try:
            result = AsyncResult(celery_id)
            result.revoke(terminate=True)
        except Exception as exc:  # pylint: disable=broad-except
            logging.warning("Failed to revoke Celery task %s: %s", celery_id, exc)

    # The row is already claimed cancelled, so the Task is cancelled whatever
    # the removal does.  A removal that cannot finish (a refused unsafe path, a
    # permission or I/O failure) raises so the interruption is visible and a
    # later sweep retries it, rather than reporting a delete that did not
    # happen -- but it must not overwrite the successful cancellation.
    try:
        _delete_task_artifacts(task)
    except Exception:  # pylint: disable=broad-except
        logging.exception("Could not remove artifacts for cancelled task %s", md5sum)
    return jsonify({"status": "cancelled", "md5sum": md5sum}), 200


def _task_structure_input(task: dict[str, Any]) -> dict[str, Any] | None:
    """Return server-owned metadata for a structure input without reading it."""
    raw_form = task.get("input_form")
    try:
        form = json.loads(raw_form) if isinstance(raw_form, str) else raw_form
    except (json.JSONDecodeError, TypeError):
        form = {}
    entities = form.get("entities", []) if isinstance(form, dict) else []
    if not isinstance(entities, list):
        return None
    structure = next(
        (
            entity
            for entity in entities
            if isinstance(entity, dict)
            and entity.get("type") == "file"
            and entity.get("logical_type") == "protein_structure"
        ),
        None,
    )
    file_path = str(structure.get("snapshot_path") or "") if structure else ""
    if not file_path or not os.path.isfile(file_path):
        return None
    if not any(
        _path_is_within(current_app.config[root], file_path)
        for root in ("UPLOAD_FOLDER", "WORKSPACE_FOLDER", "RESULTS_FOLDER")
    ):
        return None
    return {
        **structure,
        "format": structure.get("format") if isinstance(structure.get("format"), str) else "",
    }


def _iso_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _task_execution_state_payload(task: dict[str, Any]) -> dict[str, Any]:
    try:
        summary = _progress_summary(task) or {}
    except Exception:
        logging.warning("Could not read execution progress for task %s", task.get("md5sum"))
        summary = {}
    return {"progress": summary.get("progress"), "outcome": summary.get("outcome")}


def _task_list_summary(task: dict[str, Any], *, include_owner: bool) -> dict[str, Any]:
    task_id = str(task["md5sum"])
    status = str(task["status"]).strip().lower()
    structure = _task_structure_input(task)
    # One classification serves every affordance on this card, so the dashboard
    # never reads a boolean from one authority and a state from another.
    publication = _result_publication_state(task)
    result_available = publication == PUBLICATION_AVAILABLE
    try:
        archive_ready = os.path.isfile(_task_zip_path(task)) and result_available
    except (OSError, ValueError):
        archive_ready = False
    can_cancel = _task_mutation_allowed(task) and status in {"pending", "queued", "running"}
    can_delete = (
        g.current_user.get("role") != "guest"
        and _task_mutation_allowed(task)
        and status not in task_store.CLEANUP_CLAIM_STATUSES
    )

    return {
        "task_id": task_id,
        "task_type": task.get("task_type") or default_task_type(),
        "display_name": _task_display_name(task, task_id),
        "status": status,
        "terminal": status in task_store.STOP_POLLING_STATUSES,
        "submitted_at": _iso_timestamp(task.get("uploaded_at")),
        "finished_at": _iso_timestamp(task.get("finished_at")),
        "walltime_seconds": task.get("walltime"),
        "owner": (task.get("username") or None) if include_owner else None,
        **_task_execution_state_payload(task),
        "error": _sanitize_task_error(task, task.get("error")),
        "result": {
            "available": result_available,
            # "Available" is the only state a client can open; every other state
            # names itself so a quarantined (legacy) result is distinguishable
            # from a task that never published at all.
            "publication": publication,
            "page_url": f"/compute/results/{task_id}",
            "manifest_url": f"/compute/api/results/{task_id}",
            # Both archive affordances answer for the same publication the
            # download route serves: an unreadable result offers neither a link
            # that would 409 nor a request that would be refused.
            "archive_ready": archive_ready,
            "archive_request_allowed": status in {"finished", "failed"} and result_available and not archive_ready,
            "archive_request_url": f"/compute/api/results/{task_id}/archive",
            "download_url": f"/compute/api/download/{task_id}" if archive_ready else None,
        },
        "actions": {
            "cancel": {"allowed": can_cancel, "url": f"/compute/api/cancel/{task_id}"},
            "delete": {"allowed": can_delete, "url": f"/compute/api/delete/{task_id}"},
        },
        "input_preview": (
            {
                "capability": "molecular_structure",
                "format": "mmcif" if structure and structure.get("format") in {"cif", "mmcif"} else "pdb",
                "url": f"/compute/api/tasks/{task_id}/input",
            }
            if structure is not None
            else None
        ),
    }


@app.route("/compute/api/tasks", methods=["GET"])
@login_required
def task_list():
    """List the caller's visible Tasks as stable, presentation-neutral summaries."""
    is_admin = _is_admin_user()
    user_id = str(g.current_user["id"])
    visible = [
        task
        for task in task_store.list_tasks()
        if (is_admin or str(task.get("submitted_by_user_id")) == user_id)
        and not _is_deleted_status(task.get("status"))
    ]
    visible.sort(key=lambda task: float(task.get("uploaded_at") or 0), reverse=True)
    return jsonify({"tasks": [_task_list_summary(task, include_owner=is_admin) for task in visible]})


@app.route("/compute/dashboard", methods=["GET"])
@login_required
def task_dashboard():
    return _serve_frontend_entry(private=True)


def _serve_frontend_entry(*, private: bool = False, status: int = 200):
    """Serve the built frontend shell without injecting request or domain state."""
    app_root = os.path.join(current_app.static_folder or "", "app")
    if not os.path.isfile(os.path.join(app_root, "index.html")):
        logging.error("Frontend build entry is unavailable")
        abort(503)
    response = send_from_directory(app_root, "index.html", conditional=True)
    response.status_code = status
    response.headers["Cache-Control"] = "private, no-store" if private else "no-cache"
    return response


# Every Administration destination the frontend shell navigates to is served
# from the one declaration the page-route parity contract reads, immediately
# beside the frontend-shell server it renders.
register_admin_pages(app, _serve_frontend_entry)


_MAX_LEGAL_DOCUMENT_BYTES = 64 * 1024
# Operator-editable, repository-owned notice source. Deployments edit the file in
# their checkout; it is never frontend source and never a database row.
_SYSTEM_NOTICES_SOURCE = Path(__file__).with_name("legal") / "SYSTEM_NOTICES.md"


@app.route("/compute/api/legal/terms", methods=["GET"])
def legal_terms():
    """Return the canonical bounded Terms of Service Markdown resource."""
    source = Path(__file__).with_name("legal") / "TERMS_OF_SERVICE.md"
    content = source.read_bytes()
    if len(content) > _MAX_LEGAL_DOCUMENT_BYTES:
        logging.error("Terms of Service exceeds the %d-byte API limit", _MAX_LEGAL_DOCUMENT_BYTES)
        return jsonify({"error": "Terms of Service is unavailable"}), 503
    response = jsonify(
        {
            "document": "terms",
            "version": f"sha256:{hashlib.sha256(content).hexdigest()}",
            "markdown": content.decode("utf-8"),
        }
    )
    response.headers["Cache-Control"] = "public, max-age=300"
    return response, 200


@app.route("/compute/api/system/notices", methods=["GET"])
def system_notices():
    """Return the operator-configured long-form system notice resource.

    The notice text is repository-owned and content-addressed, never frontend
    source. Clients render the Markdown as text and decide locally whether to
    hide it by notice identity.
    """
    source = _SYSTEM_NOTICES_SOURCE
    content = source.read_bytes()
    if len(content) > _MAX_LEGAL_DOCUMENT_BYTES:
        logging.error("System notices exceed the %d-byte API limit", _MAX_LEGAL_DOCUMENT_BYTES)
        return jsonify({"error": "System notices are unavailable"}), 503
    markdown = content.decode("utf-8")
    if not _has_notice_content(markdown):
        return jsonify({"notices": []}), 200
    response = jsonify(
        {
            "notices": [
                {
                    "id": f"operator-notice-{hashlib.sha256(content).hexdigest()[:12]}",
                    "level": "info",
                    "title": "Operator notice",
                    "body": markdown,
                }
            ]
        }
    )
    response.headers["Cache-Control"] = "public, max-age=300"
    return response, 200


def _has_notice_content(markdown):
    """A notice source with no prose (blank and/or HTML-comment only) publishes nothing."""
    without_comments = re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL)
    return bool(without_comments.strip())


@app.route("/compute/results/<md5sum>", methods=["GET"])
@optional_user
def task_results_page(md5sum):
    """Serve the inert frontend shell after preserving task concealment."""
    normalized = _normalize_task_id(md5sum)
    if normalized is None:
        abort(404)
    task = task_store.get_task(normalized)
    if task is None:
        abort(404)
    if not _task_access_allowed(task):
        return _task_not_found(normalized, as_page=True)
    return _serve_frontend_entry()


@app.route("/compute/api/tasks/<md5sum>/input", methods=["GET"])
@login_required
def task_input_file(md5sum):
    """Stream a task's typed structure input for dashboard previews.

    The path comes from the immutable server-owned input snapshot; access is
    restricted to full-result readers.
    """
    normalized = _normalize_task_id(md5sum)
    if normalized is None:
        abort(404)
    task = task_store.get_task(normalized)
    if task is None:
        abort(404)
    if not _task_full_results_allowed(task):
        return _task_not_found(normalized)
    structure = _task_structure_input(task)
    file_path = str(structure.get("snapshot_path") or "") if structure else ""
    if not file_path or not os.path.isfile(file_path):
        return jsonify({"error": "Input file not found"}), 404
    # The row is server-written, but containment is cheap insurance: serve
    # only files that live inside one of the server-owned folders.
    if not (
        _path_is_within(app.config["UPLOAD_FOLDER"], file_path)
        or _path_is_within(app.config["WORKSPACE_FOLDER"], file_path)
        or _path_is_within(app.config["RESULTS_FOLDER"], file_path)
    ):
        return jsonify({"error": "Input file not found"}), 404
    return send_from_directory(
        os.path.dirname(file_path) or ".",
        os.path.basename(file_path),
        mimetype=mimetypes.guess_type(str(structure.get("relative_path") or ""))[0] or "application/octet-stream",
        conditional=True,
    )


def _soft_delete_task(md5sum: str, task: dict[str, Any]) -> bool:
    """Claim, delete, complete — a failed claim leaves the row untouched.

    The status write is the claim and it happens first, so a crash (or a
    failed write) leaves a ``deleting:*`` row that maintenance resumes instead
    of an intact artifact tree whose row still reads ``finished``.
    """
    claim_status, cleaned_status = _DELETE_CLAIMS.get(str(task["status"]), ("deleting:cancel", "deleted:cancel"))
    if not task_store.claim_task_cleanup(
        md5sum,
        expected_status=str(task["status"]),
        expected_finished_at=task.get("finished_at"),
        claim_status=claim_status,
    ):
        return False
    if task["status"] in {"pending", "queued", "running"}:
        _revoke_celery_task(task)

    # A Task that never started holds entitlement it will never consume, so its
    # admission hold is released with the deletion.  Idempotent: a Task whose
    # allocation already started consumed its hold at allocation time.
    task_store.release_reservation(
        task_id=md5sum, reason_code=ReservationReason.TASK_DELETED.value, at=time.time()
    )

    # Durable data is deleted as a transaction, not by ``rm -rf, then mark``:
    # the request is persisted first, then the removal is claimed, and only a
    # completed removal releases the quota that was charged for these bytes.  A
    # crash mid-way leaves a resumable row, so a partial purge never creates
    # phantom free quota.
    resource_lifecycle.request_data_deletion(
        task_store,
        task,
        actor_user_id=int(g.current_user["id"]),
    )
    # A failure here propagates: the row is still in its ``deleting:*`` claim,
    # which is exactly what maintenance resumes, so the request keeps its 500
    # contract and leaves a resumable cleanup rather than an intact tree whose
    # row still reads ``finished``.
    if not resource_lifecycle.purge_task_data(
        task_store,
        task,
        remove_artifacts=_delete_task_artifacts,
    ):
        logging.warning("Data purge for task %s did not complete; it will be retried", md5sum)
    now = time.time()
    started_at = task.get("started_at")
    walltime = task.get("walltime")
    if walltime is None and started_at:
        walltime = now - started_at
    finished_at = task.get("finished_at")
    if cleaned_status == "deleted:cancel" or not finished_at:
        finished_at = now
    if not task_store.complete_task_cleanup(
        md5sum,
        claim_status=claim_status,
        cleaned_status=cleaned_status,
        finished_at=finished_at,
        walltime=walltime,
        error="Task deleted by user",
    ):
        logging.warning("Delete claim changed before completion for task %s", md5sum)
        return False
    return True


@app.route("/compute/api/delete/<md5sum>", methods=["DELETE"])
@login_required
def delete_task(md5sum):
    if _blocked := require_bearer_auth():
        return _blocked
    if _blocked := _reject_guest():
        return _blocked
    md5sum = _normalize_task_id(md5sum)
    if md5sum is None:
        return jsonify({"status": "bad_request", "message": "Invalid task id"}), 400
    task = task_store.get_task(md5sum)
    if not task:
        return jsonify({"status": "not_found", "md5sum": md5sum}), 404
    if not _task_mutation_allowed(task):
        return _task_not_found(md5sum)
    if task["status"] in task_store.CLEANUP_CLAIM_STATUSES:
        return jsonify({"error": "Task cleanup is already in progress", "md5sum": md5sum}), 409

    if not _soft_delete_task(md5sum, task):
        return jsonify({"error": "Task cleanup is already in progress", "md5sum": md5sum}), 409
    return jsonify({"status": "deleted", "md5sum": md5sum}), 200


@app.route("/compute/api/delete", methods=["POST"])
@login_required
def delete_tasks_batch():  # skipcq: PY-R1000 -- per-task authorization and outcome accounting are intentionally atomic.
    if _blocked := require_bearer_auth():
        return _blocked
    if _blocked := _reject_guest():
        return _blocked
    payload = request.get_json(silent=True) or {}
    md5sums = payload.get("md5sums")
    if not isinstance(md5sums, list):
        return jsonify({"error": "md5sums must be a JSON list"}), 400
    # Each element runs a synchronous artifact rmtree in this request, so the
    # batch is bounded like every other caller-supplied collection.
    if len(md5sums) > _MAX_BATCH_DELETE_TASKS:
        return jsonify({"error": f"md5sums must contain at most {_MAX_BATCH_DELETE_TASKS} task ids"}), 400

    deleted: list[str] = []
    not_found: list[str] = []
    ignored: list[str] = []
    seen: set[str] = set()

    for raw_md5 in md5sums:
        raw_md5_text = str(raw_md5).strip()
        md5sum = _normalize_task_id(raw_md5_text)
        if md5sum is None:
            if raw_md5_text:
                ignored.append(raw_md5_text)
            continue
        if md5sum in seen:
            continue
        seen.add(md5sum)

        task = task_store.get_task(md5sum)
        if not task:
            not_found.append(md5sum)
            continue
        if not _task_mutation_allowed(task):
            # A foreign id is reported as missing, not denied, or the outcome
            # list would confirm which task ids exist for another tenant.
            logging.warning("Batch delete denied for task %s by user %s", md5sum, g.current_user["id"])
            not_found.append(md5sum)
            continue
        if task["status"] in task_store.CLEANUP_CLAIM_STATUSES:
            ignored.append(md5sum)
            continue

        if _soft_delete_task(md5sum, task):
            deleted.append(md5sum)
        else:
            ignored.append(md5sum)

    return (
        jsonify(
            {
                "status": "ok",
                "deleted": deleted,
                "not_found": not_found,
                "ignored": ignored,
            }
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Auth API routes
# ---------------------------------------------------------------------------


def _email_configured() -> bool:
    """Return True if email sending is configured (Resend or SMTP)."""
    return bool(_env_str("RESEND_API_KEY", "") or _env_str("SMTP_HOST", ""))


def _allowed_email_domains() -> set[str]:
    """Return the set of allowed email domains from ``ALLOWED_EMAIL_DOMAINS``.

    Empty set means all domains are allowed.
    """
    raw = _env_str("ALLOWED_EMAIL_DOMAINS", "")
    if not raw.strip():
        return set()
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def _get_user_db() -> UserDatabase:
    return current_app.config["user_db"]  # type: ignore[no-any-return]


def _get_operator_service():
    service = current_app.config.get("operator_service")
    if service is None:
        abort(503, description="Operator control plane is unavailable")
    return service


def _runner_family_or_404(runner_family: str):
    """Reject a path family that cannot name a canonical Runner before any lookup.

    The registry is the single source of family identity, but a value that is not
    even the *shape* of an identifier (a path, a shell fragment, an oversized
    string) is a not-found resource rather than something to resolve.
    """
    from revocompute.operator_actions import runner_family_is_resolvable

    if not runner_family_is_resolvable(runner_family):
        return None
    return runner_family


def _operator_error(exc: Exception) -> tuple[Any, int]:
    """Map a typed control-plane rejection to a stable, non-leaking HTTP response.

    The messages are the operator-facing ones the control core already produces;
    an internal failure yields a generic 500 rather than a stack detail.
    """
    from revocompute.operator_executor import ExecutorUnavailable, UnsupportedOperation
    from revocompute.operator_jobs import OperatorConflictError
    from revocompute.operator_plan import StalePlanError
    from revocompute.operator_service import OperatorNotFound
    from revocompute.operator_actions import OperatorActionError

    if isinstance(exc, (OperatorNotFound, KeyError)):
        return jsonify({"error": str(exc) or "Not found"}), 404
    if isinstance(exc, StalePlanError):
        # 409, not 400: the client's request was well-formed but the world moved.
        return jsonify({"error": "State changed; review the new plan", "code": "stale_plan"}), 409
    if isinstance(exc, OperatorConflictError):
        return jsonify({"error": str(exc), "code": "operation_in_progress"}), 409
    if isinstance(exc, ExecutorUnavailable):
        return jsonify({"error": "Operator executor unavailable", "code": "executor_unavailable"}), 503
    if isinstance(exc, (UnsupportedOperation, OperatorActionError)):
        return jsonify({"error": str(exc)}), 400
    from revocompute.operator_jobs import OperatorJobError
    from revocompute.operator_service import OperatorServiceError

    if isinstance(exc, (OperatorJobError, OperatorServiceError, ValueError)):
        return jsonify({"error": str(exc)}), 409
    return jsonify({"error": "Operator operation failed"}), 500


@app.route("/compute/api/auth/admin/runners", methods=["GET"])
@login_required
def admin_runner_fleet():
    """The fleet readiness list: readiness, capacity, access, and in-flight jobs."""
    if _blocked := require_admin():
        return _blocked
    service = _get_operator_service()
    return jsonify(service.fleet(int(g.current_user["id"]))), 200


@app.route("/compute/api/auth/admin/runners/<runner_family>", methods=["GET"])
@login_required
def admin_runner_detail(runner_family: str):
    """One family's evidence lanes and the actions its current state permits."""
    if _blocked := require_admin():
        return _blocked
    if _runner_family_or_404(runner_family) is None:
        return jsonify({"error": "Unknown or disabled Runner family"}), 404
    service = _get_operator_service()
    try:
        return jsonify(service.detail(runner_family, int(g.current_user["id"]))), 200
    except Exception as exc:  # noqa: BLE001 - mapped to a typed status
        return _operator_error(exc)


@app.route("/compute/api/auth/admin/runners/<runner_family>/plan", methods=["POST"])
@login_required
def admin_runner_plan(runner_family: str):
    """Produce the content-addressed plan for one typed action; changes nothing."""
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    if _runner_family_or_404(runner_family) is None:
        return jsonify({"error": "Unknown or disabled Runner family"}), 404
    request_model = _parse_body(OperatorPlanRequest)
    if isinstance(request_model, tuple):
        return request_model
    service = _get_operator_service()
    try:
        plan = service.plan(request_model.action, runner_family)
    except Exception as exc:  # noqa: BLE001 - mapped to a typed status
        return _operator_error(exc)
    return jsonify(plan.as_dict()), 200


@app.route("/compute/api/auth/admin/runners/<runner_family>/actions", methods=["POST"])
@login_required
@rate_limit(max_requests=30, window_seconds=300)
def admin_runner_action(runner_family: str):
    """Execute a planned typed action; the plan digest binds it to its evidence."""
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    if _runner_family_or_404(runner_family) is None:
        return jsonify({"error": "Unknown or disabled Runner family"}), 404
    request_model = _parse_body(OperatorJobRequest)
    if isinstance(request_model, tuple):
        return request_model
    user = g.current_user
    service = _get_operator_service()
    try:
        outcome = service.submit(
            request_model.action,
            runner_family,
            plan_digest=request_model.plan_digest,
            actor_user_id=int(user["id"]),
            actor_username=str(user.get("username") or user["id"]),
            idempotency_key=request_model.idempotency_key,
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a typed status
        return _operator_error(exc)
    status = 200 if not outcome.created else 202
    return jsonify({"job": outcome.job, "plan": outcome.plan.as_dict(), "accepted": outcome.created}), status


@app.route("/compute/api/auth/admin/runners/<runner_family>/history", methods=["GET"])
@login_required
def admin_runner_history(runner_family: str):
    """Bounded append-only operator history for one family, newest first."""
    if _blocked := require_admin():
        return _blocked
    if _runner_family_or_404(runner_family) is None:
        return jsonify({"error": "Unknown or disabled Runner family"}), 404
    service = _get_operator_service()
    limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    return jsonify({"history": service.history(runner_family, limit=limit)}), 200


@app.route("/compute/api/auth/admin/operator/jobs", methods=["GET"])
@login_required
def admin_operator_jobs():
    """Recent Operator Jobs, filterable by family and status."""
    if _blocked := require_admin():
        return _blocked
    service = _get_operator_service()
    limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    family = request.args.get("runner_family") or None
    return jsonify({"jobs": service.jobs(runner_family=family, limit=limit)}), 200


@app.route("/compute/api/auth/admin/operator/jobs/<job_id>", methods=["GET"])
@login_required
def admin_operator_job(job_id: str):
    """One Operator Job's status, stage, bounded log, and structured effect."""
    if _blocked := require_admin():
        return _blocked
    service = _get_operator_service()
    try:
        return jsonify(service.job(job_id)), 200
    except Exception as exc:  # noqa: BLE001 - mapped to a typed status
        return _operator_error(exc)


@app.route("/compute/api/auth/admin/operator/jobs/<job_id>/cancel", methods=["POST"])
@login_required
@rate_limit(max_requests=30, window_seconds=300)
def admin_operator_job_cancel(job_id: str):
    """Request cancellation of a job the calling operator owns."""
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    service = _get_operator_service()
    try:
        return jsonify(service.cancel(job_id, actor_user_id=int(g.current_user["id"]))), 200
    except Exception as exc:  # noqa: BLE001 - mapped to a typed status
        return _operator_error(exc)


def _project_gpu_authorization(user_id: int) -> None:
    """Publish current auth truth to the worker-readable compute database."""
    db = _get_user_db()
    user = db.get_user(user_id)
    now = time.time()
    entitlements: dict[str, float | None] = {}
    if user is not None:
        # The projection is the union of active grants: any indefinite grant
        # wins, otherwise the longest still-valid expiry.  Grants arrive
        # newest-first, so a plain overwrite could keep an older, shorter
        # expiry and deny access while a later grant is still valid.
        entitlements = project_effective_entitlements(
            db.list_entitlement_grants(user_id), now=now
        )
    account_enabled = bool(
        user
        and not user.get("deleted")
        and user.get("email_verified")
        and user.get("registration_status") == "approved"
        and user.get("user_status") == "active"
    )
    task_store.project_gpu_authorization(
        user_id,
        account_enabled=account_enabled,
        allow_gpu_use=bool(user and user.get("allow_gpu_use")),
        entitlements=entitlements,
        updated_at=now,
    )


def require_admin():
    """Return 403 unless the current user has the canonical admin role."""
    if _blocked := require_web_login():
        return _blocked
    if g.current_user.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403
    return None


def _audit_runner_access(db, user_id: int, policy_id: str, outcome: str, reason_code: str, tt=None) -> None:
    """Persist bounded access evidence without changing the admission decision."""
    try:
        metadata = _request_metadata()
        db.record_runner_access_event(
            user_id,
            policy_id,
            outcome,
            reason_code,
            task_type=getattr(tt, "name", ""),
            runtime_family=getattr(getattr(tt, "runtime", None), "name", ""),
            ip_address=metadata.get("ip"),
            user_agent=metadata.get("user_agent"),
            auth_method=g.get("auth_method"),
        )
    except Exception:
        logging.exception("Failed to persist Runner access audit event %s for policy %s", outcome, policy_id)


_ADMIN_LOG_FILES = {
    "gunicorn-access": "gunicorn-access.log",
    "gunicorn-error": "gunicorn-error.log",
    "celery-worker": "celery-worker.log",
    "operational-events": "operational-events.log",
    "maintenance": "maintenance.log",
}
_ADMIN_LOG_TAIL_DEFAULT_BYTES = 1_000_000
_ADMIN_LOG_TAIL_MAX_BYTES = 4_000_000
_ADMIN_LOG_ARCHIVE_PATTERN = re.compile(
    rf"(?:{'|'.join(re.escape(name) for name in _ADMIN_LOG_FILES.values())})" r"\.\d{8}T\d{12}Z\.zip"
)


def _admin_log_archive_path(archive_name: str) -> Path | None:
    """Resolve one managed rotated-log ZIP without allowing arbitrary paths."""
    if _ADMIN_LOG_ARCHIVE_PATTERN.fullmatch(archive_name) is None:
        return None
    log_dir = os.environ.get("LOG_DIR", "").strip()
    if not log_dir:
        return None
    archive_path = Path(log_dir).resolve() / archive_name
    if archive_path.is_symlink() or not archive_path.is_file():
        return None
    return archive_path


@app.route("/compute/api/auth/admin/logs/archives", methods=["GET"])
@login_required
def admin_log_archives():
    """List managed rotated-log ZIPs grouped by active log."""
    if _blocked := require_admin():
        return _blocked
    log_dir = os.environ.get("LOG_DIR", "").strip()
    if not log_dir:
        return jsonify({"error": "LOG_DIR is not configured"}), 503

    directory = Path(log_dir).resolve()
    groups = []
    for log_name, filename in _ADMIN_LOG_FILES.items():
        archives = []
        for archive in directory.glob(f"{filename}.*.zip"):
            if (
                _ADMIN_LOG_ARCHIVE_PATTERN.fullmatch(archive.name) is None
                or archive.is_symlink()
                or not archive.is_file()
            ):
                continue
            try:
                stat = archive.stat()
            except OSError:
                continue
            archives.append(
                {
                    "filename": archive.name,
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
        archives.sort(key=lambda item: (item["modified_at"], item["filename"]), reverse=True)
        groups.append(
            {
                "id": log_name,
                "filename": filename,
                "archives": archives,
            }
        )
    return jsonify({"logs": groups})


@app.route(
    "/compute/api/auth/admin/logs/archives/<archive_name>",
    methods=["GET"],
)
@login_required
def admin_download_log_archive(archive_name: str):
    """Download one managed rotated-log ZIP."""
    if _blocked := require_admin():
        return _blocked
    archive_path = _admin_log_archive_path(archive_name)
    if archive_path is None:
        return jsonify({"error": "Log archive is not available"}), 404
    response = send_from_directory(
        archive_path.parent,
        archive_path.name,
        as_attachment=True,
        download_name=archive_path.name,
        mimetype="application/zip",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/compute/api/auth/admin/logs/<log_name>", methods=["GET"])
@login_required
def admin_stream_log(log_name: str):
    """Stream a bounded tail of one fixed, unrotated server log to an administrator."""
    if _blocked := require_admin():
        return _blocked
    filename = _ADMIN_LOG_FILES.get(log_name)
    if filename is None:
        return jsonify({"error": "Unknown log"}), 404

    log_dir = os.environ.get("LOG_DIR", "").strip()
    if not log_dir:
        return jsonify({"error": "LOG_DIR is not configured"}), 503
    log_path = Path(log_dir).resolve() / filename
    if log_path.is_symlink() or not log_path.is_file():
        return jsonify({"error": "Log is not available"}), 404
    try:
        tail_bytes = int(request.args.get("tail_bytes", _ADMIN_LOG_TAIL_DEFAULT_BYTES))
    except (TypeError, ValueError):
        return jsonify({"error": "tail_bytes must be an integer"}), 400
    if tail_bytes < 1 or tail_bytes > _ADMIN_LOG_TAIL_MAX_BYTES:
        return jsonify({"error": f"tail_bytes must be between 1 and {_ADMIN_LOG_TAIL_MAX_BYTES}"}), 400
    handle = None
    try:
        handle = log_path.open("rb")
        size = os.fstat(handle.fileno()).st_size
        offset = max(0, size - tail_bytes)
        handle.seek(offset)
    except OSError:
        if handle is not None:
            handle.close()
        return jsonify({"error": "Log is not available"}), 404

    def stream():
        remaining = min(size, tail_bytes)
        with handle:
            while remaining and (chunk := handle.read(min(64 * 1024, remaining))):
                remaining -= len(chunk)
                yield chunk

    return Response(
        stream(),
        mimetype="text/plain",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Accel-Buffering": "no",
            "X-Log-Truncated": "true" if offset else "false",
        },
    )


def _reject_guest():
    """Return 403 if the current user is the publicly shared guest account."""
    if g.get("current_user") and g.current_user.get("role") == "guest":
        return jsonify({"error": "Guest accounts cannot perform this action"}), 403
    return None


def _parse_body(model_cls: type):
    """Validate request JSON against *model_cls*.  Returns the model instance
    or a ``(json_response, status_code)`` error tuple."""
    try:
        return model_cls.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"error": e.errors()[0]["msg"]}), 400


@app.route("/compute/api/auth/login", methods=["POST"])
@rate_limit(max_requests=5, window_seconds=60)
def auth_login():
    """Exchange username+password for a Bearer token.

    Accepts a ``username`` field that may be either a username or an email
    address — admin-created users may only know their email.
    """
    req = _parse_body(LoginRequest)
    if isinstance(req, tuple):
        return req

    db = _get_user_db()
    if "@" in req.login_id:
        user = db.get_user_by_email(req.login_id)  # already normalised by schema
    else:
        user = db.get_user_by_username(req.login_id)
    # Constant-time: always run check_password_hash so response latency does
    # not reveal whether the username exists (timing side-channel defence).
    pwd_ok = check_password_hash(
        user["password_hash"] if user is not None else _DUMMY_PASSWORD_HASH,
        req.password,
    )
    if user is None or not pwd_ok:
        return jsonify({"error": "Invalid username or password"}), 401

    if blocked := _is_account_blocked(user):
        return jsonify({"error": blocked}), 403

    token = generate_token(user["id"], user.get("token_version", 0))
    response = jsonify({"token": token, "username": user["username"]})
    response.set_cookie(
        "auth_token",
        token,
        path="/",
        httponly=True,
        samesite="Lax",
        secure=request.is_secure or current_app.config.get("AUTH_COOKIE_SECURE", False),
    )
    return response


@app.route("/compute/api/auth/forgot-password", methods=["POST"])
@rate_limit(max_requests=3, window_seconds=3600)
def auth_forgot_password():
    """Send a password-reset link to the given email address."""
    if not _email_configured():
        return jsonify({"error": "Password reset requires email service to be configured"}), 503

    req = _parse_body(ForgotPasswordRequest)
    if isinstance(req, tuple):
        return req
    email = req.email

    if not email or "@" not in email:
        # Don't leak whether the email is registered
        return jsonify({"message": "If that email is registered, a reset link has been sent."}), 200

    db = _get_user_db()
    send_password_reset_email(email, db)
    return jsonify({"message": "If that email is registered, a reset link has been sent."}), 200


@app.route("/compute/reset_password", methods=["GET"])
def auth_reset_password_page():
    """Serve the inert frontend entry; the reset API owns token authority."""
    return _serve_frontend_entry()


@app.route("/compute/api/auth/reset-password", methods=["POST"])
@rate_limit(max_requests=10, window_seconds=3600)
def auth_reset_password():
    """Set a new password using a password-reset token."""
    req = _parse_body(ResetPasswordRequest)
    if isinstance(req, tuple):
        return req

    db = _get_user_db()
    user_id = validate_reset_token(req.token, db)
    if user_id is None:
        return jsonify({"error": "Invalid or expired reset token"}), 400

    db.update_user(user_id, password_hash=generate_password_hash(req.password))
    db.increment_token_version(user_id)
    logging.info("User %d reset their password", user_id)
    return jsonify({"message": "Password updated - you can now log in."}), 200


@app.route("/compute/api/auth/logout", methods=["POST"])
@optional_user
def auth_logout():
    """Clear the auth cookie and invalidate all tokens for the current user.
    Bearer token required for the token-version bump; cookie-only requests
    only clear the cookie without invalidating tokens (CSRF-safe).
    """
    user = g.get("current_user")
    blocked = require_bearer_auth() if user is not None else None
    # Expire the cookie on every path: a cookie-only request is refused the
    # token-version bump, but the browser session must still end.
    response, status = blocked if blocked else (jsonify({"status": "logged_out"}), 200)
    response.set_cookie(
        "auth_token",
        "",
        max_age=0,
        path="/",
        httponly=True,
        samesite="Lax",
        secure=request.is_secure or current_app.config.get("AUTH_COOKIE_SECURE", False),
    )
    if blocked:
        return response, status
    if user is not None:
        db = _get_user_db()
        db.increment_token_version(user["id"])
    return response


@app.route("/compute/api/auth/captcha", methods=["GET"])
def auth_captcha():
    """Return a math CAPTCHA challenge with a signed token (5-min expiry)."""
    question, token = generate_captcha()
    return jsonify({"question": question, "token": token}), 200


@app.route("/compute/api/auth/registration", methods=["GET"])
def auth_registration_capability():
    """Return the bounded server-owned self-registration capability."""
    return jsonify({"enabled": ENABLE_REGISTER, "email_available": _email_configured()}), 200


@app.route("/compute/api/auth/register", methods=["POST"])
@rate_limit(max_requests=3, window_seconds=3600)
def auth_register():
    """Register a new user account.

    Requires ``ENABLE_REGISTER=true`` AND a configured email service (Resend).
    """
    if not ENABLE_REGISTER:
        return jsonify({"error": "Registration is disabled on this server"}), 403
    if not _email_configured():
        return jsonify({"error": "Registration requires email service to be configured"}), 403

    req = _parse_body(RegisterRequest)
    if isinstance(req, tuple):
        return req

    # CAPTCHA — block bot / programmatic registration
    if not validate_captcha(req.captcha_token, req.captcha_answer):
        return jsonify({"error": "CAPTCHA validation failed. Please try again."}), 400

    # Domain allowlist
    allowed = _allowed_email_domains()
    if allowed:
        domain = req.email.partition("@")[2]
        if domain not in allowed:
            return jsonify({"error": f"Email domain @{domain} is not allowed"}), 400

    db = _get_user_db()
    if db.get_user_by_username(req.username):
        return jsonify({"error": "Username already taken"}), 409
    if db.get_user_by_email(req.email):
        return jsonify({"error": "Email address already registered"}), 409

    try:
        user = db.create_user(
            username=req.username,
            email=req.email,
            password=req.password,
            full_name=req.full_name,
            affiliation=req.affiliation,
            position=req.position,
            pi_name=req.pi_name,
            terms_agreed=req.terms_agreed,
            registration_ip=_client_ip(),
            registration_country=_client_country(),
        )
    except IntegrityError:
        return jsonify({"error": "Username or email already registered"}), 409

    sent = send_verification_email(user)
    if not sent:
        logging.warning("Email verification failed for %r; account created but not verified", req.username)

    if sent:
        message = "Registration successful — check your email to verify your account."
    else:
        message = (
            "Account created, but the verification email could not be sent. "
            + "Contact an administrator to verify your account."
        )

    return jsonify({"message": message, "username": req.username, "email_sent": sent}), 201


@app.route("/compute/api/auth/resend-verification", methods=["POST"])
@rate_limit(max_requests=10, window_seconds=3600)
def auth_resend_verification():
    """Resend the verification email for an unverified account.

    Per-email backoff: first resend is immediate, then 10×n minutes where
    *n* is the number of previous resends.
    """
    req = _parse_body(ForgotPasswordRequest)
    if isinstance(req, tuple):
        return req

    email = req.email
    if not email or "@" not in email:
        return (
            jsonify({"message": "If that email is registered and unverified, a new verification email has been sent."}),
            200,
        )

    db = _get_user_db()
    user = db.get_user_by_email(email)

    # Return a generic response for all non-actionable cases to prevent
    # account enumeration (unknown, deleted, banned, already verified).
    _generic = (
        jsonify({"message": "If that email is registered and unverified, a new verification email has been sent."}),
        200,
    )
    if user is None:
        return _generic
    if user.get("deleted") or user.get("user_status") == "banned":
        return _generic
    if user.get("email_verified"):
        return _generic

    # Per-email backoff: 10×n minutes since last resend
    count = user.get("verification_resend_count") or 0
    last_at = user.get("verification_resend_at")
    if last_at and count > 0:
        cooldown = 10 * 60 * count  # seconds
        elapsed = time.time() - last_at
        if elapsed < cooldown:
            remaining = int((cooldown - elapsed) / 60) + 1
            return jsonify({"error": f"Please wait {remaining} min before requesting another verification email"}), 429

    sent = send_verification_email(user)
    if not sent:
        return jsonify({"error": "Failed to send verification email. Contact an administrator."}), 500

    db.update_user(user["id"], verification_resend_count=count + 1, verification_resend_at=time.time())
    return jsonify({"message": "Verification email sent. Check your inbox."}), 200


@app.route("/compute/user_verify", methods=["GET"])
def auth_user_verify_page():
    """Serve the inert frontend entry; the verification API owns token authority."""
    return _serve_frontend_entry()


@app.route("/compute/api/auth/verify-email", methods=["POST"])
@rate_limit(max_requests=10, window_seconds=3600)
def auth_verify_email():
    """Verify an email address using the signed, expiring link token."""
    req = _parse_body(VerifyEmailRequest)
    if isinstance(req, tuple):
        return req

    user_id = validate_email_token(req.token)
    if user_id is None:
        return jsonify({"error": "Invalid or expired verification token"}), 400

    db = _get_user_db()
    user = db.get_user(user_id)
    if user is None:
        return jsonify({"error": "User not found"}), 404

    db.verify_email(user_id)
    if user.get("registration_status") not in {"approved", "rejected"}:
        db.update_user(user_id, registration_status="verified")
    # user_status stays "pending" — admin must approve
    return jsonify(
        {
            "message": "Email address verified.",
            "email": user["email"],
            "registration_pending": user.get("user_status") != "active",
        }
    ), 200


@app.route("/compute/api/auth/me", methods=["GET"])
@login_required
def auth_me():
    """Return the current authenticated user's profile."""
    user = g.current_user
    return (
        jsonify(
            {
                "username": user["username"],
                "email": user["email"],
                "email_verified": user["email_verified"],
                "role": user.get("role", "user"),
                "full_name": user.get("full_name"),
                "affiliation": user.get("affiliation"),
                "position": user.get("position"),
                "pi_name": user.get("pi_name"),
            }
        ),
        200,
    )


def _gpu_credit_payload(user_id: int, *, admin: bool = False) -> dict[str, Any]:
    summary = task_store.gpu_credit_summary(user_id)
    entries = task_store.list_compute_ledger(user_id, period=summary["period"])
    history = []
    for entry in entries:
        # Zero-value admin_reset rows are durable idempotency markers, not
        # balance-affecting history.  Hide them from the user's own view while
        # keeping them in the administrative audit projection.
        if not admin and entry["kind"] == "admin_reset" and entry["quantity"] == 0:
            continue
        item = {
            "id": entry["id"],
            "period": entry["period"],
            "kind": entry["kind"],
            "gpu_seconds": entry["quantity"],
            "task_id": entry["task_id"],
            "stage_id": entry["stage_id"],
            "slurm_job_id": entry["slurm_job_id"],
            "reason": entry["reason"],
            "created_at": entry["created_at"],
        }
        if admin:
            item["actor_user_id"] = entry["actor_user_id"]
            item["reason_code"] = entry["reason_code"]
            item["evidence_source"] = entry["evidence_source"]
        history.append(item)
    return {
        **summary,
        "credit_unit_gpu_seconds": SECONDS_PER_CREDIT,
        "monthly_grant_credits": summary["monthly_grant_gpu_seconds"] / SECONDS_PER_CREDIT,
        "usage_credits": summary["usage_gpu_seconds"] / SECONDS_PER_CREDIT,
        "adjustment_credits": summary["adjustment_gpu_seconds"] / SECONDS_PER_CREDIT,
        "remaining_credits": summary["remaining_gpu_seconds"] / SECONDS_PER_CREDIT,
        "history": history,
    }


def _entitlement_payload(user_id: int) -> dict[str, Any]:
    """The canonical resource envelope, as the typed projection #60 consumes.

    One shape for compute entitlement, admission state, and durable-storage
    ownership: a later placement or reporting consumer reads this rather than
    re-deriving a balance, and ``enforceable`` distinguishes a unit this
    deployment actually gates from one it only accounts.
    """
    return task_store.resource_envelope(user_id).to_dict()


@app.route("/compute/api/resource-entitlement", methods=["GET"])
@login_required
def current_resource_entitlement():
    """Return only the authenticated user's canonical resource envelope."""
    return jsonify(_entitlement_payload(int(g.current_user["id"]))), 200


@app.route("/compute/api/gpu-credit", methods=["GET"])
@login_required
def current_gpu_credit():
    """Return only the authenticated user's current UTC-period accounting."""
    payload = _gpu_credit_payload(int(g.current_user["id"]))
    payload["allow_gpu_use"] = bool(g.current_user.get("allow_gpu_use"))
    return jsonify(payload), 200


_USER_METRICS_WINDOWS: dict[str, tuple[str, int | None]] = {
    "daily": ("day", 30),
    "weekly": ("week", 30),
    "quarterly": ("quarter", 8),
    "yearly": ("year", None),
}


def _metrics_window(window: str) -> tuple[str, int | None]:
    """Resolve one window to its bucket granularity and fixed bucket count.

    A ``None`` count marks the unbounded ``yearly`` window, which spans every
    calendar year the user has Tasks in through the current year.
    """
    try:
        return _USER_METRICS_WINDOWS[window]
    except KeyError:
        raise ValueError(window) from None


def _bucket_start(granularity: str, day: date) -> date:
    """The ISO start date of the day/week/quarter/year bucket containing ``day``."""
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "quarter":
        return date(day.year, ((day.month - 1) // 3) * 3 + 1, 1)
    if granularity == "year":
        return date(day.year, 1, 1)
    return day


def _advance_bucket(granularity: str, start: date, steps: int) -> date:
    """Move a bucket start ``steps`` whole buckets forward; negative steps go back."""
    if granularity == "week":
        return start + timedelta(days=7 * steps)
    if granularity == "quarter":
        month = start.month - 1 + 3 * steps
        return date(start.year + month // 12, month % 12 + 1, 1)
    if granularity == "year":
        return date(start.year + steps, 1, 1)
    return start + timedelta(days=steps)


def _bucket_steps(granularity: str, first: date, day: date) -> int:
    """Whole buckets from the ``first`` bucket to the bucket containing ``day``.

    The inverse of :func:`_advance_bucket`; negative when ``day`` precedes ``first``.
    """
    if granularity == "week":
        return (day - first).days // 7
    if granularity == "quarter":
        return (day.year - first.year) * 4 + (day.month - 1) // 3 - (first.month - 1) // 3
    if granularity == "year":
        return day.year - first.year
    return (day - first).days


def _project_user_metrics(tasks: list[dict[str, Any]], *, window: str, now: float) -> dict[str, Any]:
    """Aggregate one user's persisted Task rows over one window.

    Pure projection: no Task is written, and the caller passes only rows that
    already belong to the authenticated user. The activity series buckets by the
    window's period (day/week/quarter/year); the ``yearly`` window spans every
    calendar year the user has Tasks in through the current year.
    """
    granularity, count = _metrics_window(window)
    today_start = datetime.fromtimestamp(now, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end = _bucket_start(granularity, today_start.date())
    if count is None:
        earliest = min(
            (datetime.fromtimestamp(float(task["uploaded_at"]), tz=timezone.utc).date() for task in tasks),
            default=today_start.date(),
        )
        first_day = _bucket_start(granularity, min(earliest, today_start.date()))
        spans = end.year - first_day.year + 1
    else:
        first_day = _advance_bucket(granularity, end, -(count - 1))
        spans = count
    buckets: dict[int, int] = {}
    in_window = [
        task
        for task in tasks
        if datetime.fromtimestamp(float(task.get("uploaded_at") or 0), tz=timezone.utc).date() >= first_day
    ]

    submitted = completed = failed = 0
    cpu_tasks = gpu_tasks = 0
    gpu_seconds = 0.0
    runtimes: list[float] = []
    distribution: dict[str, dict[str, Any]] = {}
    for task in in_window:
        status = str(task.get("status") or "")
        submitted += 1
        if status == "finished":
            completed += 1
        elif status == "failed":
            failed += 1
        index = _bucket_steps(
            granularity,
            first_day,
            datetime.fromtimestamp(float(task["uploaded_at"]), tz=timezone.utc).date(),
        )
        if 0 <= index < spans:
            buckets[index] = buckets.get(index, 0) + 1
        walltime = task.get("walltime")
        if walltime is not None and status in {"finished", "failed", "cancelled"}:
            runtimes.append(float(walltime))
        task_type_name = str(task.get("task_type") or default_task_type())
        try:
            task_type, _runner = get_task_type(task_type_name)
            label, gpu = task_type.display_name, task_type.gpus
        except KeyError:
            label, gpu = task_type_name, False
        if status == "finished":
            if gpu:
                gpu_tasks += 1
            else:
                cpu_tasks += 1
        entry = distribution.setdefault(
            task_type_name, {"task_type": task_type_name, "label": label, "gpu": gpu, "tasks": 0}
        )
        entry["tasks"] += 1
        if gpu:
            # ponytail: per-Task allocation read; batch into one query if a user
            # ever accumulates enough GPU Tasks for this to show up in latency.
            # Only the ``gpu_second`` fact is GPU time: every Slurm allocation
            # also records the CPU core-seconds it held, and summing both units
            # into one figure would report 10 GPU-minutes as 15.
            for allocation in task_store.list_task_allocations(str(task["md5sum"])):
                if str(allocation.get("unit")) != rloan.UNIT_GPU_SECOND:
                    continue
                gpu_seconds += float(allocation.get("quantity") or 0)

    runtimes.sort()
    if not runtimes:
        median_runtime = None
    elif len(runtimes) % 2:
        median_runtime = runtimes[len(runtimes) // 2]
    else:
        median_runtime = (runtimes[len(runtimes) // 2 - 1] + runtimes[len(runtimes) // 2]) / 2
    decided = completed + failed
    activity = [
        {"period": _advance_bucket(granularity, first_day, index).isoformat(), "count": buckets.get(index, 0)}
        for index in range(spans)
    ]
    return {
        "window": window,
        "period": today_start.date().isoformat(),
        "tasks_submitted": submitted,
        "tasks_completed": completed,
        "tasks_failed": failed,
        "success_rate": (completed / decided) if decided else None,
        "cpu_tasks": cpu_tasks,
        "gpu_tasks": gpu_tasks,
        # One credit is one GPU-minute, so a single field carries both readings.
        "gpu_minutes": gpu_seconds / 60,
        "total_runtime_seconds": sum(runtimes),
        "median_runtime_seconds": median_runtime,
        "distribution": sorted(distribution.values(), key=lambda item: (-item["tasks"], item["label"])),
        "activity": activity,
    }


@app.route("/compute/api/user-metrics", methods=["GET"])
@login_required
def current_user_metrics():
    """Aggregate the authenticated user's own persisted Tasks over one window.

    Read-only projection over the Task store: no aggregate table, no Task write.
    """
    window = (request.args.get("window") or "daily").strip()
    try:
        _metrics_window(window)
    except ValueError:
        return jsonify({"error": f"Unknown metrics window {window!r}"}), 400
    user_id = str(g.current_user["id"])
    tasks = [task for task in task_store.list_tasks() if str(task.get("submitted_by_user_id")) == user_id]
    return jsonify(_project_user_metrics(tasks, window=window, now=time.time())), 200


@app.route("/compute/api/auth/me", methods=["PUT"])
@login_required
def auth_update_me():
    """Update the current user's research identity or password."""
    if _blocked := require_web_login():
        return _blocked
    if _blocked := _reject_guest():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    user = g.current_user
    req = _parse_body(UpdateCurrentUserRequest)
    if isinstance(req, tuple):
        return req

    db = _get_user_db()
    profile_fields = {"full_name", "affiliation", "position", "pi_name"}
    updates = {field: getattr(req, field) for field in profile_fields if field in req.model_fields_set}
    password_changed = req.current_password is not None

    if password_changed:
        if not check_password_hash(user["password_hash"], req.current_password):
            return jsonify({"error": "Current password is incorrect"}), 400
        updates["password_hash"] = generate_password_hash(req.new_password)

    db.update_user(user["id"], **updates)
    if password_changed:
        db.increment_token_version(user["id"])
    message = "Profile and password updated" if len(updates) > 1 and password_changed else (
        "Password updated" if password_changed else "Profile updated"
    )
    return jsonify({"message": message}), 200


# ---------------------------------------------------------------------------
# Token refresh — cookie-authenticated endpoint that returns a fresh Bearer
# token so pages loaded via cookie navigation can perform state-changing
# operations that require Bearer auth (CSRF protection).
# ---------------------------------------------------------------------------


@app.route("/compute/api/auth/token", methods=["GET"])
@login_required
@rate_limit(max_requests=30, window_seconds=60)
def auth_get_token():
    """Return a fresh session Bearer token (cookie or Bearer auth accepted).

    API keys are refused: a session token carries full web-login privileges
    (password change, API-key management, admin actions), so minting one from
    an API key would launder a deliberately restricted credential into the
    stronger tier.  API-key callers use ``X-API-Key`` directly.
    """
    if _blocked := require_web_login():
        return _blocked
    user = g.current_user
    token = generate_token(user["id"], user.get("token_version", 0))
    return jsonify({"token": token}), 200


# ---------------------------------------------------------------------------
# API key management (long-lived, user-revokable)
# ---------------------------------------------------------------------------


@app.route("/compute/api/auth/me/api-key", methods=["GET"])
@login_required
def auth_api_key_status():
    """Return whether the current user has an active API key."""
    if _blocked := require_web_login():
        return _blocked
    db = _get_user_db()
    user = db.get_user(g.current_user["id"])
    has_key = bool(user and user.get("api_key_digest"))
    return jsonify({"has_api_key": has_key}), 200


@app.route("/compute/api/auth/me/api-key", methods=["POST"])
@login_required
def auth_generate_api_key():
    """Generate a new API key — returns the plaintext key once."""
    if _blocked := require_web_login():
        return _blocked
    if _blocked := _reject_guest():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    db = _get_user_db()
    plaintext = db.generate_api_key(g.current_user["id"])
    return jsonify({"api_key": plaintext, "message": "Store this key securely — it will not be shown again."}), 201


@app.route("/compute/api/auth/me/api-key", methods=["DELETE"])
@login_required
def auth_revoke_api_key():
    """Revoke the current user's API key."""
    if _blocked := require_web_login():
        return _blocked
    if _blocked := _reject_guest():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    db = _get_user_db()
    db.revoke_api_key(g.current_user["id"])
    return jsonify({"message": "API key revoked"}), 200


@app.route("/compute/api/access", methods=["GET"])
@login_required
def current_access():
    """Return the current user's policy-level Runner access state."""
    db = _get_user_db()
    user_id = int(g.current_user["id"])
    return jsonify({"policies": [policy_state(policy, db, user_id, include_history=True) for policy in list_policies()]})


@app.route("/compute/api/access/requests", methods=["POST"])
@login_required
@rate_limit(max_requests=10, window_seconds=3600)
def create_access_request():
    if _blocked := require_bearer_auth():
        return _blocked
    req = _parse_body(AccessRequestCreate)
    if isinstance(req, tuple):
        return req
    try:
        policy = get_policy(req.policy_id)
    except (KeyError, ValueError):
        return jsonify({"error": "Unknown Runner access policy"}), 400
    if not policy.requestable:
        return jsonify({"error": "Runner access policy is not requestable"}), 403
    try:
        access_requests = _get_user_db().create_access_requests(int(g.current_user["id"]), policy.requires, req.reason)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    logging.info("User %s requested Runner access policy %s", g.current_user["id"], policy.id)
    return jsonify({"policy_id": policy.id, "requests": access_requests}), 201


@app.route("/compute/api/auth/admin/access/requests", methods=["GET"])
@login_required
def admin_access_requests():
    if _blocked := require_admin():
        return _blocked
    status = request.args.get("status", "pending")
    if status not in {"pending", "approved", "rejected", "cancelled", "all"}:
        return jsonify({"error": "Invalid access request status"}), 400
    return jsonify({"requests": _get_user_db().list_access_requests(status=None if status == "all" else status)})


@app.route("/compute/api/auth/admin/access/policies", methods=["GET"])
@login_required
def admin_access_policies():
    if _blocked := require_admin():
        return _blocked
    db = _get_user_db()
    users = db.list_users()
    output = []
    for policy in list_policies():
        granted = pending = suspended = 0
        for user in users:
            state = policy_state(policy, db, int(user["id"]))
            if state["granted"]:
                granted += 1
            elif state.get("request_status") == "pending":
                pending += 1
            if access_guard.active_suspension(int(user["id"]), policy.id, getattr(db, "path", "")).active:
                suspended += 1
        output.append(
            {
                "policy_id": policy.id,
                "label": policy.label,
                "description": policy.description,
                "requires": list(policy.requires),
                "notice": policy.notice,
                "license": policy.license,
                "authorized_users": granted,
                "pending_requests": pending,
                "suspended_users": suspended,
            }
        )
    return jsonify({"policies": output})


@app.route("/compute/api/auth/admin/access/policies/<policy_id>", methods=["GET"])
@login_required
def admin_access_policy_detail(policy_id: str):
    if _blocked := require_admin():
        return _blocked
    try:
        policy = get_policy(policy_id)
    except (KeyError, ValueError):
        return jsonify({"error": "Unknown Runner access policy"}), 404
    db = _get_user_db()
    users = db.list_users()
    authorized, suspended = [], []
    for user in users:
        user_id = int(user["id"])
        state = policy_state(policy, db, user_id)
        identity = {
            "user_id": user_id,
            "username": user["username"],
            "full_name": user.get("full_name"),
            "email": user.get("email"),
            "affiliation": user.get("affiliation"),
            "position": user.get("position"),
            "pi_name": user.get("pi_name"),
        }
        if state["granted"]:
            grants = [
                grant
                for grant in db.list_entitlement_grants(user_id)
                if grant["entitlement"] in policy.requires
                and not grant["revoked_at"]
                and (not grant["expires_at"] or grant["expires_at"] > time.time())
            ]
            authorized.append(
                {
                    **identity,
                    "basis": grants[0]["basis"] if grants else None,
                    "grant_id": grants[0]["id"] if grants else None,
                }
            )
        cooldown = access_guard.active_suspension(user_id, policy.id, getattr(db, "path", ""))
        if cooldown.active:
            suspended.append({**identity, "retry_after_seconds": cooldown.retry_after_seconds})
    pending = [
        {**item, "request_id": item["id"]}
        for item in db.list_access_requests(status="pending")
        if item["entitlement"] in policy.requires
    ]
    return jsonify(
        {
            "policy": {
                "policy_id": policy.id,
                "label": policy.label,
                "description": policy.description,
                "requires": list(policy.requires),
                "notice": policy.notice,
                "license": policy.license,
            },
            "authorized_users": authorized,
            "pending_requests": pending,
            "suspended_users": suspended,
            "events": db.list_runner_access_events(policy_id=policy.id, limit=50),
        }
    )


@app.route("/compute/api/auth/admin/access/events", methods=["GET"])
@login_required
def admin_access_events():
    if _blocked := require_admin():
        return _blocked
    policy_id = request.args.get("policy_id")
    if policy_id and policy_id not in {policy.id for policy in list_policies()}:
        return jsonify({"error": "Unknown Runner access policy"}), 400
    limit = request.args.get("limit", "100")
    try:
        limit_value = int(limit)
    except ValueError:
        return jsonify({"error": "Invalid event limit"}), 400
    return jsonify({"events": _get_user_db().list_runner_access_events(policy_id=policy_id, limit=limit_value)})


@app.route("/compute/api/auth/admin/access/requests/<int:request_id>/decision", methods=["POST"])
@login_required
def admin_access_decision(request_id: int):
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    req = _parse_body(AccessDecisionRequest)
    if isinstance(req, tuple):
        return req
    db = _get_user_db()
    access_request = db.get_access_request(request_id)
    if access_request is None:
        return jsonify({"error": "Access request not found"}), 404
    if access_request["entitlement"] not in declared_entitlements():
        return jsonify({"error": "Entitlement is no longer declared"}), 409
    try:
        if req.decision == "approved":
            grant = db.approve_access_request(
                request_id,
                reviewed_by=int(g.current_user["id"]),
                basis=req.basis,
                expires_at=req.expires_at,
                review_note=req.note,
            )
            _project_gpu_authorization(int(access_request["user_id"]))
            for policy in list_policies():
                if (
                    access_request["entitlement"] in policy.requires
                    and policy_state(policy, db, access_request["user_id"])["granted"]
                ):
                    access_guard.clear_policy_state(access_request["user_id"], policy.id, getattr(db, "path", ""))
            logging.info(
                "Admin %s approved Runner entitlement %s for user %s",
                g.current_user["id"],
                access_request["entitlement"],
                access_request["user_id"],
            )
            return jsonify({"grant": grant})
        if not db.reject_access_request(request_id, reviewed_by=int(g.current_user["id"]), review_note=req.note):
            raise ValueError("Access request is not pending")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    logging.info(
        "Admin %s rejected Runner entitlement %s for user %s",
        g.current_user["id"],
        access_request["entitlement"],
        access_request["user_id"],
    )
    return jsonify({"message": "Access request rejected"})


@app.route("/compute/api/auth/admin/users/<int:user_id>/entitlements", methods=["GET", "POST"])
@login_required
def admin_user_entitlements(user_id: int):
    if _blocked := require_admin():
        return _blocked
    db = _get_user_db()
    user = db.get_user(user_id)
    if user is None:
        return jsonify({"error": "User not found"}), 404
    if request.method == "GET":
        policies = []
        for policy in list_policies():
            state = policy_state(policy, db, user_id, include_entitlements=True)
            suspension = access_guard.active_suspension(user_id, policy.id, getattr(db, "path", ""))
            state.update(suspended=suspension.active, retry_after_seconds=suspension.retry_after_seconds)
            policies.append(state)
        return jsonify(
            {
                "grants": db.list_entitlement_grants(user_id),
                "policies": policies,
            }
        )
    if _blocked := require_bearer_auth():
        return _blocked
    req = _parse_body(EntitlementGrantRequest)
    if isinstance(req, tuple):
        return req
    if req.entitlement not in declared_entitlements():
        return jsonify({"error": "Unknown entitlement"}), 400
    try:
        grant = db.grant_entitlement(
            user_id,
            req.entitlement,
            granted_by=int(g.current_user["id"]),
            basis=req.basis,
            expires_at=req.expires_at,
            note=req.note,
        )
        _project_gpu_authorization(user_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    logging.info("Admin %s granted Runner entitlement %s to user %s", g.current_user["id"], req.entitlement, user_id)
    for policy in list_policies():
        if req.entitlement in policy.requires and policy_state(policy, db, user_id)["granted"]:
            access_guard.clear_policy_state(user_id, policy.id, getattr(db, "path", ""))
    return jsonify({"grant": grant}), 201


@app.route(
    "/compute/api/auth/admin/users/<int:user_id>/entitlements/<int:grant_id>/revoke",
    methods=["POST"],
)
@login_required
def admin_revoke_entitlement(user_id: int, grant_id: int):
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    db = _get_user_db()
    grant = db.get_entitlement_grant(grant_id)
    if grant is None or grant["user_id"] != user_id:
        return jsonify({"error": "Entitlement grant not found"}), 404
    task_store.deny_gpu_authorization(user_id)
    if not db.revoke_entitlement(grant_id, revoked_by=int(g.current_user["id"])):
        _project_gpu_authorization(user_id)
        return jsonify({"error": "Entitlement grant is not active"}), 409
    _project_gpu_authorization(user_id)
    logging.info(
        "Admin %s revoked Runner entitlement %s from user %s",
        g.current_user["id"],
        grant["entitlement"],
        user_id,
    )
    return jsonify({"message": "Entitlement revoked"})


@app.route("/compute/api/auth/admin/users/<int:user_id>/access/<policy_id>/clear-suspension", methods=["POST"])
@login_required
def admin_clear_runner_suspension(user_id: int, policy_id: str):
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    try:
        get_policy(policy_id)
    except (KeyError, ValueError):
        return jsonify({"error": "Unknown Runner access policy"}), 404
    db = _get_user_db()
    if db.get_user(user_id) is None:
        return jsonify({"error": "User not found"}), 404
    access_guard.clear_policy_state(user_id, policy_id, getattr(db, "path", ""))
    _audit_runner_access(db, user_id, policy_id, "cleared", "admin_cleared_suspension")
    return jsonify({"message": "Runner access suspension cleared", "policy_id": policy_id})


@app.route("/compute/api/auth/admin/users", methods=["GET"])
@login_required
def admin_users():
    """Admin-only user listing with safe fields only."""
    if _blocked := require_admin():
        return _blocked

    db = _get_user_db()
    users = db.list_users()
    safe = []
    for user in users:
        item = UserResponse.model_validate(user).model_dump()
        item["gpu_credit"] = task_store.gpu_credit_summary(int(user["id"]))
        safe.append(item)
    return jsonify({"users": safe}), 200


@app.route("/compute/api/auth/admin/users/<int:user_id>/resource-entitlement", methods=["GET"])
@login_required
def admin_user_resource_entitlement(user_id: int):
    """Return one existing user's canonical resource envelope for operators."""
    if _blocked := require_admin():
        return _blocked
    user = _get_user_db().get_user(user_id)
    if user is None or user.get("deleted"):
        return jsonify({"error": "User not found"}), 404
    return jsonify(_entitlement_payload(user_id)), 200


@app.route("/compute/api/auth/admin/users/<int:user_id>/gpu-credit", methods=["GET"])
@login_required
def admin_user_gpu_credit(user_id: int):
    """Return current GPU accounting for one existing user."""
    if _blocked := require_admin():
        return _blocked
    user = _get_user_db().get_user(user_id)
    if user is None or user.get("deleted"):
        return jsonify({"error": "User not found"}), 404
    return jsonify(_gpu_credit_payload(user_id, admin=True)), 200


@app.route("/compute/api/auth/admin/users/<int:user_id>/gpu-credit/adjustments", methods=["POST"])
@login_required
def admin_adjust_user_gpu_credit(user_id: int):
    """Append one reasoned, idempotent GPU-credit adjustment."""
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    user = _get_user_db().get_user(user_id)
    if user is None or user.get("deleted"):
        return jsonify({"error": "User not found"}), 404
    req = _parse_body(GPUCreditAdjustmentRequest)
    if isinstance(req, tuple):
        return req
    try:
        entry = task_store.adjust_compute_account(
            user_id=user_id,
            gpu_seconds=req.gpu_seconds,
            actor_user_id=int(g.current_user["id"]),
            reason=req.reason,
            idempotency_key=req.idempotency_key,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    emit_event(
        "resource.policy.adjusted",
        user_id=user_id,
        gpu_seconds=abs(req.gpu_seconds),
        reason_code=LedgerReason.ADMIN_ADJUSTMENT.value,
    )
    return jsonify({"entry_id": entry["id"], "gpu_credit": _gpu_credit_payload(user_id, admin=True)}), 201


@app.route("/compute/api/auth/admin/users/<int:user_id>/gpu-credit/allowance", methods=["PUT"])
@login_required
def admin_set_user_gpu_allowance(user_id: int):
    """Set one user's monthly GPU allowance without rewriting ledger history."""
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    user = _get_user_db().get_user(user_id)
    if user is None or user.get("deleted"):
        return jsonify({"error": "User not found"}), 404
    req = _parse_body(GPUCreditAllowanceRequest)
    if isinstance(req, tuple):
        return req
    try:
        entry = task_store.set_compute_allowance(
            user_id=user_id,
            monthly_gpu_seconds=req.monthly_gpu_seconds,
            actor_user_id=int(g.current_user["id"]),
            idempotency_key=req.idempotency_key,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    emit_event(
        "resource.policy.adjusted",
        user_id=user_id,
        gpu_seconds=abs(int(entry["quantity"])),
        reason_code=LedgerReason.ALLOWANCE_SET.value,
    )
    return jsonify({"entry_id": entry["id"], "gpu_credit": _gpu_credit_payload(user_id, admin=True)}), 200


@app.route("/compute/api/auth/admin/users/<int:user_id>/gpu-credit/reset", methods=["POST"])
@login_required
def admin_reset_user_gpu_credit(user_id: int):
    """Restore one user's current-period balance to their effective allowance.

    Appends one compensating ``admin_reset`` ledger entry; usage history and
    prior adjustments are never modified or removed.
    """
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    user = _get_user_db().get_user(user_id)
    if user is None or user.get("deleted"):
        return jsonify({"error": "User not found"}), 404
    req = _parse_body(GPUCreditResetRequest)
    if isinstance(req, tuple):
        return req
    try:
        result = task_store.reset_compute_account(
            user_id=user_id,
            actor_user_id=int(g.current_user["id"]),
            reason=req.reason,
            idempotency_key=req.idempotency_key,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    emit_event(
        "resource.policy.adjusted",
        user_id=user_id,
        gpu_seconds=abs(int(result["reset_delta_gpu_seconds"])),
        reason_code=LedgerReason.ADMIN_RESET.value,
    )
    return jsonify({**result, "gpu_credit": _gpu_credit_payload(user_id, admin=True)}), 200


@app.route("/compute/api/auth/admin/gpu-credit/reset", methods=["POST"])
@login_required
def admin_reset_all_gpu_credits():
    """Reset every current non-deleted user to their own effective allowance.

    GPU permission is deliberately independent: a user with ``allow_gpu_use``
    disabled is still reset.  Deleted accounts are excluded by the canonical
    user listing.
    """
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    req = _parse_body(GPUCreditResetRequest)
    if isinstance(req, tuple):
        return req
    user_ids = [int(user["id"]) for user in _get_user_db().list_users()]
    try:
        result = task_store.reset_all_compute_accounts(
            user_ids=user_ids,
            actor_user_id=int(g.current_user["id"]),
            reason=req.reason,
            idempotency_key=req.idempotency_key,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    emit_event(
        "resource.policy.adjusted",
        reason_code=LedgerReason.ADMIN_RESET_ALL.value,
        gpu_seconds=abs(int(result["total_delta_gpu_seconds"])),
        batch_id=result["batch_id"],
    )
    return jsonify(result), 200


@app.route("/compute/api/auth/admin/gpu-credit/reconciliation", methods=["GET", "POST"])
@login_required
def admin_gpu_credit_reconciliation():
    """Expose unsettled usage and optionally ask the worker to reconcile it."""
    if _blocked := require_admin():
        return _blocked
    if request.method == "POST":
        if _blocked := require_bearer_auth():
            return _blocked
        try:
            result = reconcile_slurm_allocations.apply_async().get(timeout=20)
        except Exception:
            logging.exception("Allocation reconciliation request failed")
            return jsonify({"error": "Resource reconciliation worker is unavailable"}), 503
    else:
        result = None
    return jsonify({"result": result, "allocations": task_store.list_unsettled_allocations()}), 200


@app.route("/compute/api/auth/admin/users", methods=["POST"])
@login_required
def admin_create_user():
    """Admin-only user creation for pre-approved accounts."""
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked

    db = _get_user_db()
    req = _parse_body(AdminCreateUserRequest)
    if isinstance(req, tuple):
        return req

    if db.get_user_by_username(req.username):
        return jsonify({"error": "Username already taken"}), 409
    if db.get_user_by_email(req.email):
        return jsonify({"error": "Email address already registered"}), 409

    new_user = db.create_user(
        username=req.username,
        email=req.email,
        password=req.password,
        role=req.role,
        full_name=req.full_name,
        affiliation=req.affiliation,
        position=req.position,
        pi_name=req.pi_name,
        registration_status="approved",
        user_status="active",
    )
    db.verify_email(new_user["id"])  # admin-created accounts are pre-verified

    logging.info("Admin %r created user %r", g.current_user["username"], req.username)
    return jsonify({"message": "User created", "username": req.username}), 201


def _admin_email_update(db: UserDatabase, user_id: int, email: str | None):
    if email is None:
        return {}, None
    existing = db.get_user_by_email(email)
    if existing and existing["id"] != user_id:
        return None, (jsonify({"error": "Email address already in use"}), 409)
    return {"email": email}, None


def _admin_profile_update_fields(req: AdminUpdateUserRequest) -> dict[str, Any]:
    update_fields = {
        field: value
        for field in ("affiliation", "full_name", "pi_name", "user_status")
        if (value := getattr(req, field)) is not None
    }
    if "position" in req.model_fields_set:
        update_fields["position"] = req.position
    if req.password is not None:
        update_fields["password_hash"] = generate_password_hash(req.password)
    return update_fields


def _admin_registration_update_fields(
    db: UserDatabase,
    user_id: int,
    user: dict[str, Any],
    registration_status: str | None,
) -> dict[str, Any]:
    update_fields: dict[str, Any] = {}
    if registration_status is None:
        return update_fields
    update_fields["registration_status"] = registration_status
    # Admin approval implies email verification — avoid the gap where
    # an unverified self-registered account becomes active without
    # proving email ownership.
    if registration_status == "approved":
        if not user.get("email_verified"):
            db.verify_email(user_id)
        update_fields["approved_by"] = g.current_user["id"]
        update_fields["approved_at"] = time.time()
    return update_fields


def _admin_user_update_fields(
    db: UserDatabase,
    user_id: int,
    user: dict[str, Any],
    is_self: bool,
    req: AdminUpdateUserRequest,
):
    """Build validated fields for an admin user update."""
    update_fields, update_error = _admin_email_update(db, user_id, req.email)
    if update_error is not None:
        return None, update_error
    if is_self and req.user_status == "banned":
        return None, (jsonify({"error": "Administrators cannot ban their own account"}), 400)
    update_fields.update(_admin_profile_update_fields(req))
    update_fields.update(_admin_registration_update_fields(db, user_id, user, req.registration_status))
    if req.role is not None:
        if is_self and req.role != user.get("role"):
            return None, (jsonify({"error": "Administrators cannot change their own role"}), 400)
        if not is_self:
            update_fields["role"] = req.role
    if req.allow_gpu_use is not None:
        update_fields["allow_gpu_use"] = req.allow_gpu_use
    return update_fields, None


def _notify_admin_user_update(
    db: UserDatabase,
    user_id: int,
    user: dict[str, Any],
    registration_status: str | None,
) -> None:
    if registration_status == "approved":
        approved_user = db.get_user(user_id) or user
        if not send_approval_email(approved_user):
            logging.warning("Approval email failed for %r", user_id)
    elif registration_status == "rejected" and not send_rejection_email(user):
        logging.warning("Rejection email failed for %r", user_id)


@app.route("/compute/api/auth/admin/users/<int:user_id>", methods=["PUT", "DELETE"])
@login_required
def admin_manage_user(user_id):  # skipcq: PY-R1000 -- admin state transitions are kept in one audited transaction.
    """Admin-only: update or soft-delete a user."""
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked

    db = _get_user_db()
    user = db.get_user(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    is_self = user_id == g.current_user["id"]

    if request.method == "DELETE":
        if is_self:
            return jsonify({"error": "Administrators cannot delete their own account"}), 400
        # ponytail: soft-delete — hides from user table, recoverable.
        task_store.deny_gpu_authorization(user_id)
        db.update_user(user_id, deleted=True)
        logging.info("Admin %r soft-deleted user %r", g.current_user["username"], user.get("username"))
        return jsonify({"message": "User deleted"}), 200

    req = _parse_body(AdminUpdateUserRequest)
    if isinstance(req, tuple):
        return req
    update_fields, update_error = _admin_user_update_fields(db, user_id, user, is_self, req)
    if update_error is not None:
        return update_error

    if update_fields:
        if "password_hash" in update_fields:
            # A reset is normally a response to a compromised account, so it
            # must also end the user's existing sessions.
            db.increment_token_version(user_id)
        disables_gpu = (
            update_fields.get("allow_gpu_use") is False
            or ("email_verified" in update_fields and not update_fields["email_verified"])
            or ("registration_status" in update_fields and update_fields["registration_status"] != "approved")
            or ("user_status" in update_fields and update_fields["user_status"] != "active")
            or bool(update_fields.get("deleted"))
        )
        if disables_gpu:
            task_store.deny_gpu_authorization(user_id)
        db.update_user(user_id, **update_fields)
        _project_gpu_authorization(user_id)
        _notify_admin_user_update(db, user_id, user, update_fields.get("registration_status"))

    return jsonify({"message": "User updated"}), 200


@app.route("/compute/api/auth/admin/users/batch", methods=["POST"])
@login_required
def admin_batch_users():
    """Admin-only batch operations on users.

    Accepts ``{"action": "enable"|"disable"|"delete", "user_ids": [...]}``.
    """
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked

    req = _parse_body(BatchUserRequest)
    if isinstance(req, tuple):
        return req

    db = _get_user_db()
    now = time.time()
    admin_id = g.current_user["id"]

    if req.action == "enable":
        updates = {
            "user_status": "active",
            "registration_status": "approved",
            "email_verified": True,
            "deleted": False,
            "approved_by": admin_id,
            "approved_at": now,
        }
    elif req.action == "disable":
        updates = {"user_status": "banned", "approved_by": admin_id, "approved_at": now}
    else:  # delete
        updates = {"deleted": True}

    count = 0
    for uid in req.user_ids:
        user = db.get_user(uid)
        if user is None:
            continue
        if uid == admin_id and req.action in {"disable", "delete"}:
            continue  # don't let an admin lock themselves out
        if user.get("role") == "admin" and req.action == "disable":
            continue  # don't disable other admins
        if req.action in {"disable", "delete"}:
            task_store.deny_gpu_authorization(uid)
        db.update_user(uid, **updates)
        _project_gpu_authorization(uid)
        count += 1

    return jsonify({"message": f"{req.action} action applied to {count} user(s)", "count": count}), 200


# ---------------------------------------------------------------------------
# Admin runtime configuration API
# ---------------------------------------------------------------------------


@app.route("/compute/api/auth/admin/config", methods=["GET"])
@login_required
def admin_get_config():
    """Return structured runtime configuration (admin only).

    Response::

        {
          "task_types": [{"tool": "<task>", "enabled": true, "cpus": null,
            "memory": null, "slurm_partition": null, ...}, ...],
          "resources": {"cpus": "4", "memory": "8G", ...},
          "slurm": {
            "enabled": false,
            "allowed_queues": []
          }
        }
    """
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    manage_db = current_app.config.get("manage_db")
    if manage_db is None:
        return jsonify({"error": "Configuration database not available"}), 500
    task_configs = manage_db.task_type_all()
    type_map = {task_type.name: task_type for task_type in list_types()}
    stage_map = {stage.name: (task_type, stage) for task_type in type_map.values() for stage in task_type.workflow}
    known_tools = set(type_map) | set(stage_map)
    task_configs = [config for config in task_configs if config["tool"] in known_tools]
    for config in task_configs:
        task_type = type_map.get(config["tool"])
        workflow_stage = stage_map.get(config["tool"])
        if task_type is None and workflow_stage is None:
            continue
        stage = workflow_stage[1] if workflow_stage else None
        task_type = task_type or workflow_stage[0]
        config["display_name"] = f"{task_type.display_name} / {stage.display_name}" if stage else task_type.display_name
        config["requires_gpu"] = stage.requires_gpu if stage else task_type.gpus
        config["runtime_family"] = task_type.runtime.name
        config["is_workflow_stage"] = stage is not None
        config["category"] = task_type.category
        config["inputs"] = [
            {"id": role.name, "title": role.title, "formats": list(role.formats)} for role in task_type.inputs
        ] if stage is None else []
        config["parameter_count"] = len(task_type.params) if stage is None else 0
        config["stage_count"] = len(task_type.workflow) if stage is None else 0
        _, runner = _get_task_type(task_type.name)
        try:
            resolved = manage_db.resolve_task_resources(
                config["tool"],
                requires_gpu=config["requires_gpu"],
                default_timeout_seconds=runner.max_runtime_seconds,
            )
            config["effective_resources"] = resolved.public_dict()
            config["resource_sources"] = resolved.sources
            config["resource_error"] = None
        except ResourceValidationError as exc:
            config["effective_resources"] = None
            config["resource_sources"] = {}
            config["resource_error"] = str(exc)
    stored_resources = manage_db.resource_all()
    return jsonify(
        {
            "task_types": task_configs,
            "resources": {key: value for key, value in stored_resources.items() if key in GLOBAL_RESOURCE_KEYS},
            "ignored_resource_keys": sorted(set(stored_resources) - GLOBAL_RESOURCE_KEYS),
            "slurm": {
                "enabled": manage_db.slurm_enabled(),
                "allowed_queues": manage_db.slurm_allowed_queues(),
            },
        }
    )


@app.route("/compute/api/auth/admin/config", methods=["PUT"])
@login_required
def admin_set_config():
    """Update runtime configuration (admin only).

    Accepts the same shape as GET::

        {
          "task_types": [{"tool": "pythia_ddg", "enabled": false,
            "cpus": 4, "memory": "16G", "slurm_partition": "gpu"}],
          "resources": {"cpus": "8", "memory": "16G", "slurm_enabled": "true"},
          "slurm": {"enabled": true, "allowed_queues": ["gpu", "cpu"]}
        }

    Each key is optional — only provided fields are updated.
    """
    if _blocked := require_admin():
        return _blocked
    if _blocked := require_bearer_auth():
        return _blocked
    manage_db = current_app.config.get("manage_db")
    if manage_db is None:
        return jsonify({"error": "Configuration database not available"}), 500

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "Expected a JSON object"}), 400

    _tt_fields = (
        "enabled",
        "cpus",
        "memory",
        "max_runtime_seconds",
        "slurm_partition",
        "slurm_gres",
        "slurm_time",
        "slurm_nodes",
        "slurm_ntasks",
        "slurm_qos",
        "slurm_account",
        "slurm_constraint",
        "slurm_exclusive",
    )

    unknown_sections = set(body) - {"task_types", "resources", "slurm"}
    if unknown_sections:
        return jsonify({"error": f"Unknown configuration sections: {sorted(unknown_sections)}"}), 400

    type_map = {task_type.name: task_type for task_type in list_types()}
    runtime_map = {
        name: task_type.runtime.name
        for task_type in type_map.values()
        for name in (task_type.name, *(stage.name for stage in task_type.workflow))
    }
    known_tools = set(runtime_map)
    profile_gpu = {name: task_type.gpus for name, task_type in type_map.items()}
    profile_gpu.update(
        {stage.name: stage.requires_gpu for task_type in type_map.values() for stage in task_type.workflow}
    )
    pending_task_updates: list[tuple[str, dict[str, Any]]] = []
    pending_resources: list[tuple[str, Any]] = []
    seen_tools: set[str] = set()

    try:
        for entry in body.get("task_types") or []:
            if not isinstance(entry, dict):
                raise ResourceValidationError("Each task_types update must be an object")
            tool = entry.get("tool")
            if tool not in known_tools:
                raise ResourceValidationError(f"Unknown task type: {tool!r}")
            if tool in seen_tools:
                raise ResourceValidationError(f"Duplicate task type update: {tool!r}")
            seen_tools.add(tool)
            unknown_fields = set(entry) - {"tool", *_tt_fields}
            if unknown_fields:
                raise ResourceValidationError(f"Unknown resource fields for {tool}: {sorted(unknown_fields)}")
            current = manage_db.task_type_get(tool) or {}
            fields = {
                field: normalize_resource_value(field, entry[field])
                for field in _tt_fields
                if field in entry and normalize_resource_value(field, entry[field]) != current.get(field)
            }
            if "enabled" in fields and fields["enabled"] is None:
                raise ResourceValidationError("enabled cannot be empty")
            if not profile_gpu.get(tool, False) and fields.get("slurm_gres"):
                raise ResourceValidationError(f"CPU-only task {tool!r} cannot request GPU GRES")
            if fields:
                pending_task_updates.append((tool, fields))

        resources = body.get("resources")
        if resources is not None and not isinstance(resources, dict):
            raise ResourceValidationError("resources must be an object")
        for key, value in (resources or {}).items():
            if key not in GLOBAL_RESOURCE_KEYS:
                raise ResourceValidationError(f"Unknown global resource key: {key}")
            normalized = normalize_resource_value(key, value)
            current = normalize_resource_value(key, manage_db.resource_get(key))
            if normalized != current:
                pending_resources.append((key, normalized))

        slurm = body.get("slurm")
        if slurm is not None and not isinstance(slurm, dict):
            raise ResourceValidationError("slurm must be an object")
        if isinstance(slurm, dict):
            unknown_slurm = set(slurm) - {"enabled", "allowed_queues"}
            if unknown_slurm:
                raise ResourceValidationError(f"Unknown SLURM fields: {sorted(unknown_slurm)}")
            if "enabled" in slurm:
                value = normalize_resource_value("slurm_enabled", slurm["enabled"])
                current = normalize_resource_value("slurm_enabled", manage_db.resource_get("slurm_enabled"))
                if value != current:
                    pending_resources.append(("slurm_enabled", value))
            if "allowed_queues" in slurm:
                value = normalize_resource_value("slurm_allowed_queues", slurm["allowed_queues"])
                current = normalize_resource_value(
                    "slurm_allowed_queues", manage_db.resource_get("slurm_allowed_queues")
                )
                if value != current:
                    pending_resources.append(("slurm_allowed_queues", value))

        proposed_globals = {key: value for key, value in pending_resources}
        if len(proposed_globals) != len(pending_resources):
            raise ResourceValidationError("A global resource key was provided more than once")
        allowed_queues = proposed_globals.get("slurm_allowed_queues", tuple(manage_db.slurm_allowed_queues()))
        global_partition = proposed_globals.get("slurm_partition", manage_db.resource_get("slurm_partition"))
        if allowed_queues and global_partition and global_partition not in allowed_queues:
            raise ResourceValidationError(f"Global partition {global_partition!r} is not in allowed_queues")
        proposed_tasks = {tool: fields for tool, fields in pending_task_updates}
        for config in manage_db.task_type_all():
            partition = proposed_tasks.get(config["tool"], {}).get("slurm_partition", config.get("slurm_partition"))
            if allowed_queues and partition and partition not in allowed_queues:
                raise ResourceValidationError(
                    f"Partition {partition!r} for {config['tool']!r} is not in allowed_queues"
                )
    except ResourceValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    if pending_task_updates or pending_resources:
        try:
            affected_runners = None if pending_resources else {runtime_map[tool] for tool, _ in pending_task_updates}
            invalidate_submission_attestations(CONFIG.server_dir, affected_runners)
        except OSError as exc:
            logging.error("Unable to invalidate Runner readiness evidence: %s", exc)
            return (
                jsonify({"error": "Runner readiness evidence could not be invalidated; no settings were changed."}),
                503,
            )

    count = manage_db.apply_resource_updates(pending_task_updates, pending_resources)

    return jsonify({"message": f"{count} setting(s) updated"}), 200
