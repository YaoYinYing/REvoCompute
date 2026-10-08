# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
from typing import Any

from mcp import types

# ---------------------------------------------------------------------------
# Stable machine-readable error taxonomy
# ---------------------------------------------------------------------------
#
# An agent recovers from a failure by branching on a small, stable code.  It
# must never be asked to parse a Flask traceback, Slurm stderr, Runner stderr,
# or an arbitrary HTTP error string, so every domain failure is projected into
# exactly one of these classes and any human-readable message travels beside it
# as secondary detail.

INVALID_PARAMETERS = "INVALID_PARAMETERS"
AUTH_REQUIRED = "AUTH_REQUIRED"
ACCESS_DENIED = "ACCESS_DENIED"
NOT_READY = "NOT_READY"
RESOURCE_LIMIT = "RESOURCE_LIMIT"
TASK_NOT_FOUND = "TASK_NOT_FOUND"
TASK_NOT_CANCELLABLE = "TASK_NOT_CANCELLABLE"
RESULT_NOT_READY = "RESULT_NOT_READY"
ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
CONTENT_TOO_LARGE = "CONTENT_TOO_LARGE"

ERROR_CLASSES = frozenset(
    {
        INVALID_PARAMETERS,
        AUTH_REQUIRED,
        ACCESS_DENIED,
        NOT_READY,
        RESOURCE_LIMIT,
        TASK_NOT_FOUND,
        TASK_NOT_CANCELLABLE,
        RESULT_NOT_READY,
        ARTIFACT_NOT_FOUND,
        CONTENT_TOO_LARGE,
    }
)

# HTTP status -> protocol class, used when a canonical handler answers with a
# status and no domain code.  The map is intentionally coarse: a canonical
# handler that knows a more specific class supplies it explicitly.
_STATUS_TO_CLASS = {
    400: INVALID_PARAMETERS,
    401: AUTH_REQUIRED,
    403: ACCESS_DENIED,
    404: TASK_NOT_FOUND,
    409: TASK_NOT_CANCELLABLE,
    413: CONTENT_TOO_LARGE,
    422: RESULT_NOT_READY,
    429: RESOURCE_LIMIT,
    503: NOT_READY,
}

# Canonical detail codes (the ``code`` field of a canonical error payload) ->
# protocol class.  These are the vocabulary the submission/preflight/tool
# boundaries already emit; mapping them here keeps the projection declarative
# instead of re-deriving admission semantics.
#
# The vocabulary is owned elsewhere and consumed here: the ingress reason codes
# (``revocompute.ingress_security``), the artifact-publication codes, and the
# admission reasons ``revocompute.resource_ledger.AdmissionReason`` names.
# ``tests/server/test_mcp_projection.py`` derives this table's required entries
# from those canonical vocabularies, so a reason code a canonical boundary can
# emit and this adapter cannot classify fails CI rather than silently
# degrading.  The mapping stays declarative: it classifies a decision the
# boundary already made, it never re-derives one.
_DETAIL_CODE_TO_CLASS = {
    # ingress_security.Phase.SECURITY -- transport and byte safety.
    "input_path_invalid": INVALID_PARAMETERS,
    "input_namespace_collision": INVALID_PARAMETERS,
    "input_format_invalid": INVALID_PARAMETERS,
    "input_logical_type_invalid": INVALID_PARAMETERS,
    "input_file_count_limit": CONTENT_TOO_LARGE,
    "input_file_size_limit": CONTENT_TOO_LARGE,
    "input_total_size_limit": CONTENT_TOO_LARGE,
    "input_snapshot_mismatch": INVALID_PARAMETERS,
    "request_size_limit": CONTENT_TOO_LARGE,
    "workspace_json_invalid": INVALID_PARAMETERS,
    "validator_resource_limit": RESOURCE_LIMIT,
    # ingress_security.Phase.CONTRACT -- the caller's declared vocabulary.
    "contract_invalid": INVALID_PARAMETERS,
    "input_role_binding": INVALID_PARAMETERS,
    "input_role_format": INVALID_PARAMETERS,
    "input_role_unknown": INVALID_PARAMETERS,
    "input_role_cardinality": INVALID_PARAMETERS,
    # ingress_security.Phase.ADMISSION -- the canonical admission reasons.
    # ``gpu_credit_exhausted`` and ``infrastructure_unavailable`` are the
    # response codes the submission boundary emits for the canonical
    # ``compute_exhausted`` and ``infrastructure_unavailable`` admission reasons;
    # both spellings are named here because both can reach this classifier.
    "admission_denied": ACCESS_DENIED,
    "admission_limited": RESOURCE_LIMIT,
    "admission_unavailable": NOT_READY,
    "gpu_credit_exhausted": RESOURCE_LIMIT,
    "infrastructure_unavailable": NOT_READY,
    "runner_not_ready": NOT_READY,
    # resource_ledger.AdmissionReason -- the durable reason vocabulary #59 owns.
    "compute_exhausted": RESOURCE_LIMIT,
    "storage_soft_limit": RESOURCE_LIMIT,
    "authorization_unavailable": ACCESS_DENIED,
    "runner_readiness_unavailable": NOT_READY,
    # the artifact-publication reason codes.
    "artifact_publication_rejected": ACCESS_DENIED,
    "artifact_capacity_guard": CONTENT_TOO_LARGE,
}

# Suffix/marker rules applied when a canonical ``details[0].code`` is not in the
# table above.  A resource/credit condition is retryable-later, not a policy
# denial, so a reason this adapter has not yet named still lands in a class an
# agent can act on instead of a bare ``ACCESS_DENIED``.  The gate above is what
# keeps this a backstop rather than a habit:
# ``tests/server/test_mcp_projection.py`` fails when a canonical vocabulary
# member has no explicit entry.
_DETAIL_CODE_RULES = (
    ("exhausted", RESOURCE_LIMIT),
    ("_limit_exceeded", RESOURCE_LIMIT),
    ("limit_exceeded", RESOURCE_LIMIT),
    ("insufficient", RESOURCE_LIMIT),
    ("unavailable", NOT_READY),
    ("not_ready", NOT_READY),
    ("_invalid", INVALID_PARAMETERS),
)


class McpError(Exception):
    """A protocol-level error with a stable class and optional agent guidance."""

    def __init__(
        self,
        error_class: str,
        message: str,
        *,
        detail: str | None = None,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ):
        if error_class not in ERROR_CLASSES:
            raise ValueError(f"unknown MCP error class: {error_class!r}")
        super().__init__(message)
        self.error_class = error_class
        self.message = message
        self.detail = detail
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error_class": self.error_class,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.detail:
            payload["detail"] = self.detail
        if self.retry_after_seconds is not None:
            payload["retry_after_seconds"] = self.retry_after_seconds
        return payload


def _class_for_detail_code(detail_code: str) -> str | None:
    """Map a canonical detail code to a class, with a suffix-rule fallback."""
    if not detail_code:
        return None
    mapped = _DETAIL_CODE_TO_CLASS.get(detail_code)
    if mapped is not None:
        return mapped
    for marker, error_class in _DETAIL_CODE_RULES:
        if marker in detail_code:
            return error_class
    return None


def classify(canonical: Any, *, status: int) -> McpError:
    """Project a canonical error response into a protocol error.

    ``canonical`` is the parsed JSON body of a canonical handler response (or
    ``None`` when the body was not JSON).  The function reads only the
    ``error``/``message``/``details[0].code`` fields the existing API already
    produces; it never re-derives an admission decision.
    """
    body = canonical if isinstance(canonical, dict) else {}
    message = str(body.get("error") or body.get("message") or "Request rejected")
    detail_code = ""
    details = body.get("details")
    if isinstance(details, list) and details and isinstance(details[0], dict):
        detail_code = str(details[0].get("code") or "")
    error_class = _class_for_detail_code(detail_code) or _STATUS_TO_CLASS.get(status)
    if error_class is None:
        error_class = ACCESS_DENIED if status >= 400 and status < 500 else NOT_READY
    retry_after = body.get("retry_after_seconds")
    return McpError(
        error_class,
        message,
        detail=detail_code or None,
        retryable=status in {429, 503} or bool(body.get("retryable")),
        retry_after_seconds=int(retry_after) if isinstance(retry_after, int) else None,
    )


def render(text: str) -> types.TextContent:
    return types.TextContent(type="text", text=text)


def render_error(error: McpError) -> str:
    return json.dumps({"error": error.payload()}, ensure_ascii=True, sort_keys=True)


def text(payload: Any) -> types.TextContent:
    if isinstance(payload, str):
        return types.TextContent(type="text", text=payload)
    return types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=True, sort_keys=True))
