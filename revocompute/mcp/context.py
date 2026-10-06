# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""MCP authentication and in-process access to the canonical web application.

Two access paths exist, and both terminate in the *same* code the HTTP API and
the Web application already run:

* read-only operations call canonical Python functions (``task_types``,
  ``task_store``, ``storage_resolver``, ``result_projection``);
* the request-bound mutating entry points (task submission and preflight) are
  invoked through the canonical WSGI application **in process** with Werkzeug's
  test client -- no socket, no loopback HTTP, no second admission path.  The
  caller's observed client address and ``User-Agent`` are carried into the
  synthesized environ so the existing per-IP rate limiter, the immutable input
  snapshot, and every admission decision behave exactly as they do for a real
  HTTP request.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
from dataclasses import dataclass
from typing import Any

from revocompute.mcp.errors import AUTH_REQUIRED, INVALID_PARAMETERS, McpError
from revocompute.mcp.handles import canonical_state

#: Request headers forwarded verbatim into the canonical request.  Deliberately
#: an allow-list: the MCP surface must not be able to smuggle a cookie, a proxy
#: header it does not own, or an arbitrary trust-bearing header into a canonical
#: call.
_FORWARDED_HEADERS = ("X-Forwarded-For", "X-Forwarded-Proto", "User-Agent", "X-Request-ID")


@dataclass(frozen=True)
class McpPrincipal:
    """The authenticated scientific user for one MCP call."""

    user: dict[str, Any]
    user_id: int
    username: str
    credential_headers: dict[str, str]
    client_ip: str | None
    forwarded_headers: dict[str, str]

    @property
    def is_guest(self) -> bool:
        return self.user.get("role") == "guest"


def _request(ctx: Any) -> Any:
    """Return the underlying ASGI request for this tool call, if reachable."""
    request_context = getattr(ctx, "request_context", None)
    return getattr(request_context, "request", None)


def _header(ctx: Any, name: str) -> str | None:
    request = _request(ctx)
    headers = getattr(request, "headers", None)
    if not headers:
        return None
    value = headers.get(name)
    return value if value else None


def _client_ip(ctx: Any) -> str | None:
    request = _request(ctx)
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host) if host else None


def authenticate(ctx: Any, *, allow_guest: bool = False) -> McpPrincipal:
    """Resolve the caller's REvoCompute credential without redesigning auth.

    The MCP surface accepts the credentials the HTTP API already accepts: a
    time-limited Bearer token or a long-lived ``X-API-Key``.  Verification runs
    against the canonical user database, so account state, token version, and
    every existing block rule are the ones the rest of the server enforces.
    """
    from revocompute.auth import _is_account_blocked, validate_token

    state = canonical_state()
    db = state.user_db

    credential_headers: dict[str, str] = {}
    authorization = _header(ctx, "authorization")
    api_key = _header(ctx, "x-api-key")
    if authorization:
        credential_headers["Authorization"] = authorization
    if api_key:
        credential_headers["X-API-Key"] = api_key

    user: dict[str, Any] | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        payload = validate_token(token)
        if payload is not None:
            candidate = db.get_user(payload["uid"])
            if (
                candidate is not None
                and _is_account_blocked(candidate) is None
                and payload.get("ver", 0) == candidate.get("token_version", 0)
            ):
                user = candidate
    elif api_key:
        candidate = db.validate_api_key(api_key)
        if (
            candidate is not None
            and _is_account_blocked(candidate) is None
            and candidate.get("role") != "guest"
        ):
            user = candidate

    if user is None:
        raise McpError(
            AUTH_REQUIRED,
            "Authentication required",
            detail="Provide a Bearer token in Authorization or an X-API-Key header.",
        )
    if user.get("role") == "guest" and not allow_guest:
        raise McpError(AUTH_REQUIRED, "Guest accounts cannot use this operation")

    forwarded = {}
    for header in _FORWARDED_HEADERS:
        value = _header(ctx, header)
        if value:
            forwarded[header] = value
    client_ip = _client_ip(ctx)
    if client_ip is None:
        # The canonical client-IP resolver trusts a client-supplied
        # X-Forwarded-For only from a trusted-proxy peer.  If this listener
        # could not observe a socket peer, forwarding a client XFF would let the
        # caller mint unlimited rate-limit identities, so drop it.
        forwarded.pop("X-Forwarded-For", None)
    return McpPrincipal(
        user=user,
        user_id=int(user["id"]),
        username=str(user["username"]),
        credential_headers=credential_headers,
        client_ip=client_ip,
        forwarded_headers=forwarded,
    )


@dataclass(frozen=True)
class CanonicalResponse:
    status: int
    body: Any
    headers: dict[str, str]

    @property
    def task_id(self) -> str | None:
        """Extract the canonical Task id from a canonical response."""
        if isinstance(self.body, dict):
            for key in ("task_id", "md5sum"):
                value = self.body.get(key)
                if isinstance(value, str) and value:
                    return value
        location = self.headers.get("Location", "")
        if not location:
            return None
        candidate = location.rstrip("/").rsplit("/", 1)[-1]
        return candidate or None


def _environ_overrides(principal: McpPrincipal) -> dict[str, str]:
    overrides: dict[str, str] = {}
    if principal.client_ip:
        # The canonical rate limiter and client-IP resolution read the socket
        # peer; carry the MCP caller's peer so buckets match a direct HTTP call.
        overrides["REMOTE_ADDR"] = principal.client_ip
    return overrides


def call_canonical(
    principal: McpPrincipal,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    data: dict[str, Any] | None = None,
    query_string: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> CanonicalResponse:
    """Invoke one canonical Flask handler in process and return its response.

    ``data`` is a multipart form mapping whose values are either strings or
    ``(filename, bytes, content_type)`` tuples, exactly what Werkzeug's test
    client encodes into ``request.form``/``request.files``.
    """
    state = canonical_state()
    headers = {**principal.forwarded_headers, **principal.credential_headers}
    if extra_headers:
        headers.update(extra_headers)

    body_kwargs: dict[str, Any] = {}
    if json_body is not None:
        body_kwargs["json"] = json_body
    elif data is not None:
        body_kwargs["data"] = data
        body_kwargs["content_type"] = "multipart/form-data"

    # ``follow_redirects=False``: canonical handlers answer a submission with a
    # 302 whose Location carries the created Task identity, and that identity is
    # what the MCP layer maps to an opaque handle.
    client = state.web.app.test_client()
    response = client.open(
        path,
        method=method,
        headers=headers,
        query_string=query_string,
        follow_redirects=False,
        environ_overrides=_environ_overrides(principal) or None,
        **body_kwargs,
    )
    body: Any
    try:
        body = response.get_json(silent=True)
    except Exception:  # noqa: BLE001 - a non-JSON body is not fatal here
        body = None
    return CanonicalResponse(
        status=response.status_code,
        body=body,
        headers={key: value for key, value in response.headers.items()},
    )


#: Canonical multipart field names for a Task submission.  These are the field
#: names ``revocompute.routes._handle_submission`` already reads; the MCP layer
#: must not invent a parallel vocabulary.
TASK_TYPE_FIELD = "task_type"
INPUT_ROLES_FIELD = "input_roles"
INPUT_PATHS_FIELD = "input_paths"
FILES_FIELD = "files"
WORKSPACE_FIELD = "workspace"


def build_submission_data(
    *,
    task_type: str,
    params: dict[str, Any] | None,
    inputs: Any,
    workspace: Any = None,
    max_total_bytes: int,
) -> dict[str, Any]:
    """Build the canonical multipart body for one task submission.

    Parameters travel as ``params[<name>]`` exactly as the canonical handler
    parses them; each input carries its declared role and optional relative
    path.  The MCP layer performs transport decoding only -- the canonical
    server still validates roles, formats, cardinality, sizes, and schema.
    """
    if not isinstance(task_type, str) or not task_type.strip():
        raise McpError(INVALID_PARAMETERS, "task_type is required")
    if params is not None and not isinstance(params, dict):
        raise McpError(INVALID_PARAMETERS, "params must be an object")

    body: dict[str, Any] = {TASK_TYPE_FIELD: task_type.strip().lower()}
    for name, value in (params or {}).items():
        body[f"params[{name}]"] = _scalar(value)

    entries = decode_inputs(inputs, max_total_bytes=max_total_bytes)
    roles: list[str] = []
    paths: list[str] = []
    file_parts: list[tuple[io.BytesIO, str, str]] = []
    for role, (name, raw, content_type) in entries:
        roles.append(role)
        paths.append(name)
        file_parts.append((io.BytesIO(raw), name, content_type))

    if workspace is not None:
        if not isinstance(workspace, dict):
            raise McpError(INVALID_PARAMETERS, "workspace must be an object")
        body[WORKSPACE_FIELD] = json.dumps(workspace, ensure_ascii=True, sort_keys=True)
    body[INPUT_ROLES_FIELD] = roles
    body[INPUT_PATHS_FIELD] = paths
    body[FILES_FIELD] = file_parts
    return body


def _scalar(value: Any) -> Any:
    """Render one parameter value as the flat string the canonical form holds."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


#: Multipart field name used to carry raw input bytes.  One repeated field
#: holds every input, with the parallel ``INPUT_ROLES_FIELD`` list binding each
#: entry to its declared role.
def encode_multipart(body: dict[str, Any]) -> dict[str, Any]:
    """Encode a canonical form mapping into a Werkzeug-safe multipart body.

    Werkzeug encodes a list value by inspecting its first element: a list whose
    head is a ``(filename, bytes, content_type)`` tuple becomes repeated file
    parts, and a list of scalars becomes repeated fields.  A list of scalars is
    therefore emitted as one field per entry; the canonical handler reads them
    with ``getlist``.
    """
    encoded: dict[str, Any] = {}
    for key, value in body.items():
        if isinstance(value, list):
            if not value:
                encoded[key] = ""
            elif isinstance(value[0], tuple):
                encoded[key] = value
            else:
                for item in value:
                    encoded.setdefault(key, [])
                    if isinstance(encoded[key], list):
                        encoded[key].append(item)
                    else:  # pragma: no cover - defensive
                        encoded[key] = [encoded[key], item]
        else:
            encoded[key] = value
    # A scalar list must reach Werkzeug as a list, which it encodes as repeated
    # fields (all values of equal length).  Werkzeug accepts a list of strings.
    return encoded


def decode_inputs(inputs: Any, *, max_total_bytes: int) -> list[tuple[str, tuple[str, bytes, str]]]:
    """Decode bounded base64 MCP inputs into canonical multipart upload entries.

    Each entry is ``(role, (filename, bytes, content_type))`` in submission
    order, and the declared relative path is used as the uploaded filename so
    the canonical handler's own path-safety and format checks still apply.
    """
    if inputs is None:
        return []
    if not isinstance(inputs, list):
        raise McpError(INVALID_PARAMETERS, "inputs must be a list")
    decoded: list[tuple[str, tuple[str, bytes, str]]] = []
    total = 0
    for index, item in enumerate(inputs):
        if not isinstance(item, dict):
            raise McpError(INVALID_PARAMETERS, f"inputs[{index}] must be an object")
        role = item.get("role")
        filename = item.get("filename")
        content = item.get("content_base64")
        if not isinstance(role, str) or not role:
            raise McpError(INVALID_PARAMETERS, f"inputs[{index}].role is required")
        if not isinstance(filename, str) or not filename:
            raise McpError(INVALID_PARAMETERS, f"inputs[{index}].filename is required")
        if not isinstance(content, str):
            raise McpError(INVALID_PARAMETERS, f"inputs[{index}].content_base64 is required")
        try:
            raw = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError):
            raise McpError(INVALID_PARAMETERS, f"inputs[{index}].content_base64 is not valid base64") from None
        total += len(raw)
        if total > max_total_bytes:
            from revocompute.mcp.errors import CONTENT_TOO_LARGE

            raise McpError(CONTENT_TOO_LARGE, f"Submitted inputs exceed the {max_total_bytes} byte limit")
        relative = item.get("path")
        name = relative if isinstance(relative, str) and relative else filename
        decoded.append((role, (name, raw, "application/octet-stream")))
    return decoded
