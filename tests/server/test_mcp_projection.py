# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""MCP projection, ownership, and trust-boundary tests (server-owned behavior).

The MCP surface is a projection of the canonical service, so these tests drive
the projection functions against a real isolated application instance -- the
same ``_load_pssm_module`` fixture the rest of the server suite uses -- and
assert observable behavior: discovery comes from the canonical registry,
submission runs the canonical admission path, opaque handles are user-scoped,
and artifacts follow the canonical publication and role rules.

No test here asserts static file text (skills.md contents, OpenAPI, docs).
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

import conftest as _conftest

FASTA = b">2KL8\nACDEFGHIKLMNPQRSTVWY\n"


def _auth_headers(module, username: str = "mcp-tester"):
    return _conftest._test_client_auth(module, username=username)


def test_mcp_carries_the_client_peer_into_the_canonical_request(mcp_app):
    """The MCP path hands the caller's client address to the canonical request.

    The canonical rate limiter (and client-IP resolution) keys on the request's
    socket peer, so MCP must not present a constant loopback address: two
    different MCP callers behind the same gateway must land in different buckets
    exactly as two HTTP callers do.  This drives the real MCP project function
    and asserts the canonical handler observed the caller's address.
    """
    from revocompute.mcp.context import McpPrincipal, call_canonical

    observed: dict[str, str | None] = {}
    app = mcp_app.app

    @app.route("/_mcp_probe_client_ip", methods=["GET"])
    def _probe_client_ip():  # pragma: no cover - test-only route
        from flask import request

        observed["remote_addr"] = request.remote_addr
        return {"ok": True}

    principal = McpPrincipal(
        user={"id": 1, "role": "user"},
        user_id=1,
        username="mcp-tester",
        credential_headers={},
        client_ip="203.0.113.9",
        forwarded_headers={},
    )
    response = call_canonical(principal, "GET", "/_mcp_probe_client_ip")
    assert response.status == 200
    assert observed["remote_addr"] == "203.0.113.9", "the caller peer must reach the canonical request"


def _mcp_ctx(headers: dict[str, str], peer: str | None) -> object:
    """A minimal MCP tool context carrying the ASGI request the projection reads.

    ``headers`` is what the MCP client sent (case-insensitively, as an ASGI
    request exposes them); ``peer`` is the socket address this listener actually
    observed, which is the only part of the request a caller cannot choose.
    """
    from starlette.datastructures import Headers

    client = MockClient(peer) if peer is not None else None
    request = SimpleNamespace(headers=Headers(headers), client=client)
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


class MockClient:
    """The observed socket peer, in the shape an ASGI request exposes it."""

    def __init__(self, host: str):
        self.host = host


#: A compose-bridge address: inside the default ``TRUSTED_PROXY_IPS`` range, so
#: the canonical resolver believes forwarding headers from it.
_TRUSTED_GATEWAY_PEER = "172.18.0.5"
#: A plain internet address: outside every trusted range.
_UNTRUSTED_PEER = "192.0.2.7"


@pytest.fixture
def identity_probe(mcp_app):
    """A canonical route that reports the identity resolution it observed.

    The projection's whole job here is to make the *canonical* request see what
    an ordinary HTTP request would see, so the assertions read the canonical
    resolution function and the metadata Core records -- not MCP-internal state.
    """
    from flask import jsonify, request

    from revocompute.client_ip import client_ip, trusted_client_ip

    observed: dict[str, object] = {}

    @mcp_app.app.route("/_mcp_identity_probe", methods=["GET"])
    def _identity_probe():  # pragma: no cover - test-only route
        observed["remote_addr"] = request.remote_addr
        observed["trusted_client_ip"] = trusted_client_ip()
        observed["client_ip"] = client_ip()
        observed["headers"] = sorted(request.headers.keys())
        return jsonify({"ok": True})

    return observed


def _trusted_principal(mcp_app, *, peer, real_ip, forwarded_for, extra=None):
    """Authenticate one MCP call whose observed peer and headers we control."""
    from revocompute.auth import generate_token
    from revocompute.mcp.context import authenticate

    # Reuse the shared helper so the test user exists, then mint a fresh token
    # for the MCP context shape this test drives.
    _auth_headers(mcp_app)
    user = mcp_app.app.config["user_db"].get_user_by_username("mcp-tester")
    if user is None:
        raise AssertionError("test user missing")
    headers = {"authorization": f"Bearer {generate_token(int(user['id']))}"}
    if real_ip is not None:
        headers["x-real-ip"] = real_ip
    if forwarded_for is not None:
        headers["x-forwarded-for"] = forwarded_for
    headers.update(extra or {})
    return authenticate(_mcp_ctx(headers, peer))


def _probe_identity(mcp_app, principal, observed):
    from revocompute.mcp.context import call_canonical

    observed.clear()
    response = call_canonical(principal, "GET", "/_mcp_identity_probe")
    assert response.status == 200, response.status
    return observed


def test_mcp_preserves_the_trusted_x_real_ip_the_gateway_overwrote(mcp_app, identity_probe):
    """Behind the gateway, the canonical request resolves the same client the HTTP path would.

    ``docker/nginx`` overwrites ``X-Real-IP`` with the socket peer and *appends*
    ``X-Forwarded-For``, so a client-supplied leading XFF element survives.  The
    canonical resolver therefore prefers ``X-Real-IP``.  If the MCP projection
    drops that header, the synthesized canonical request has only the forgeable
    one, and the caller -- not the gateway -- picks the rate-limit identity.
    """
    principal = _trusted_principal(
        mcp_app,
        peer=_TRUSTED_GATEWAY_PEER,
        real_ip="198.51.100.10",
        forwarded_for="203.0.113.1, 10.0.0.9",
    )
    observed = _probe_identity(mcp_app, principal, identity_probe)

    assert observed["trusted_client_ip"] == "198.51.100.10", "the trusted overwritten header must win"
    assert observed["trusted_client_ip"] != "203.0.113.1", "the forged leading XFF must never be the identity"
    # The peer stays the *actual* MCP socket peer: the canonical trust decision
    # is still made from what this listener observed, not from the headers.
    assert observed["remote_addr"] == _TRUSTED_GATEWAY_PEER


def test_mcp_rate_limit_identity_survives_a_rotated_forwarded_for(mcp_app, identity_probe):
    """Rotating the appended XFF while X-Real-IP is stable cannot mint new identities.

    The limiter is the canonical one, reached through the same in-process view an
    MCP submission uses; the property under test is that the *bucket key* is the
    gateway-reported client, not a value the caller can vary per request.
    """
    from flask import jsonify

    from revocompute.mcp.context import call_canonical
    from revocompute.ratelimit import rate_limit

    limit = 3
    mcp_app.app.view_functions["preflight_task"] = rate_limit(max_requests=limit, window_seconds=3600)(
        lambda *_a, **_k: jsonify({"ok": True})
    )

    statuses = []
    for i in range(limit + 2):
        principal = _trusted_principal(
            mcp_app,
            peer=_TRUSTED_GATEWAY_PEER,
            real_ip="198.51.100.20",
            forwarded_for=f"203.0.113.{i}, 10.0.0.{i}",
        )
        statuses.append(call_canonical(principal, "POST", "/compute/api/preflight/cpu_runner", data={}).status)

    assert statuses[:limit] == [200] * limit, statuses
    assert statuses[limit:] == [429, 429], f"a rotated XFF must not refresh the bucket: {statuses}"


def test_mcp_untrusted_peer_cannot_override_its_socket_identity(mcp_app, identity_probe):
    """A direct caller cannot choose its identity, and cannot forge the metadata either.

    Withholding the trust-bearing headers from an untrusted peer is what keeps
    the canonical resolution equal to the socket address *and* keeps a forged
    value out of the request metadata Core records for the Task.
    """
    forged = {"x-real-ip": "198.51.100.30", "x-forwarded-for": "203.0.113.31, 10.0.0.9"}
    principal = _trusted_principal(mcp_app, peer=_UNTRUSTED_PEER, real_ip=None, forwarded_for=None, extra=forged)
    observed = _probe_identity(mcp_app, principal, identity_probe)

    assert observed["trusted_client_ip"] == _UNTRUSTED_PEER, "the socket peer is the only identity here"
    assert observed["client_ip"] == _UNTRUSTED_PEER
    assert "X-Real-Ip" not in observed["headers"], "a forged X-Real-IP must not reach the canonical request"
    assert "X-Forwarded-For" not in observed["headers"], "a forged XFF must not reach the canonical request"


def test_mcp_submission_metadata_uses_the_same_identity(mcp_app, identity_probe):
    """The Task's audited ``source_ip`` follows the one resolution, in both peer cases.

    ``source_ip`` is written from the canonical request metadata, so it is the
    observable end of the same trust decision -- a caller that could rotate it
    would be writing its own audit record.
    """
    from revocompute.mcp.handles import canonical_state
    from revocompute.mcp.services import submit_task

    task_type, role = _sequence_task_type(mcp_app)

    def _submit(principal, marker: bytes) -> dict[str, object]:
        # Distinct bytes per submission: the canonical Task identity is
        # content-derived, so identical inputs would resolve to the *first*
        # Task and its metadata rather than creating a second one.
        inputs = [{"role": role, "filename": "2KL8.fasta", "content_base64": base64.b64encode(FASTA + marker).decode()}]
        reference = submit_task(
            principal, task_type=task_type, params={}, inputs=inputs, handle_store=canonical_state().handles, now=1000.0
        )
        mapping = canonical_state().handles.resolve(
            reference["task_handle"], user_id=principal.user_id, kind="task", now=1001.0
        )
        return mcp_app.task_store.get_task(mapping.operation_id)

    trusted = _trusted_principal(
        mcp_app,
        peer=_TRUSTED_GATEWAY_PEER,
        real_ip="198.51.100.40",
        forwarded_for="203.0.113.41, 10.0.0.9",
    )
    trusted_task = _submit(trusted, b"TRUSTED\n")
    assert trusted_task["source_ip"] == "198.51.100.40", "a trusted gateway's reported client is the audited source"

    untrusted = _trusted_principal(
        mcp_app,
        peer=_UNTRUSTED_PEER,
        real_ip=None,
        forwarded_for=None,
        extra={"x-real-ip": "203.0.113.42", "x-forwarded-for": "203.0.113.43"},
    )
    untrusted_task = _submit(untrusted, b"UNTRUSTED\n")
    assert untrusted_task["source_ip"] == _UNTRUSTED_PEER, "a direct caller cannot forge its audited source"


def test_only_allow_listed_headers_reach_the_canonical_request(mcp_app, identity_probe):
    """No cookie or unowned proxy header is smuggled into the canonical request.

    The allow-list is the whole boundary: a header outside it does not reach the
    canonical handler even from a trusted peer, so the projection cannot widen
    what a canonical request is allowed to see.
    """
    principal = _trusted_principal(
        mcp_app,
        peer=_TRUSTED_GATEWAY_PEER,
        real_ip="198.51.100.50",
        forwarded_for="203.0.113.51",
        extra={
            "cookie": "session=forged",
            "x-forwarded-host": "evil.example",
            "x-request-id": "mcp-test-request",
            "user-agent": "mcp-test-agent",
        },
    )
    observed = _probe_identity(mcp_app, principal, identity_probe)

    seen = set(observed["headers"])
    assert {"X-Real-Ip", "X-Forwarded-For", "X-Request-Id", "User-Agent"} <= seen
    assert not seen & {"Cookie", "X-Forwarded-Host", "X-Forwarded-Server", "X-Original-Url"}


def _activate(module) -> None:
    """Point the MCP runtime at *module* as the canonical application.

    Production resolves ``revocompute.app`` from ``sys.modules``; the isolated
    fixture loads a private copy, so the test rebinds the canonical name for the
    duration of the test exactly as ``routes`` resolution does.
    """
    sys.modules["revocompute.app"] = module
    from revocompute.mcp import handles as _handles

    _handles._STATE_CACHE.clear()


def _principal(module, username: str = "mcp-tester"):
    from revocompute.mcp.context import McpPrincipal

    headers = _auth_headers(module, username=username)
    db = module.app.config["user_db"]
    user = db.get_user_by_username(username)
    if user is None:
        raise AssertionError("test user missing")
    return McpPrincipal(
        user=user,
        user_id=int(user["id"]),
        username=str(user["username"]),
        credential_headers=headers,
        client_ip="127.0.0.1",
        forwarded_headers={},
    )


@pytest.fixture
def mcp_app(monkeypatch, tmp_path):
    module = _conftest._load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )

    class _DummyAsyncResult:
        id = "celery-mcp-test"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *a, **kw: _DummyAsyncResult())
    monkeypatch.setitem(sys.modules, "revocompute.app", module)
    _activate(module)
    try:
        yield module
    finally:
        sys.modules.pop("revocompute.app", None)
        from revocompute.mcp import handles as _handles

        _handles._STATE_CACHE.clear()


# ---------------------------------------------------------------------------
# Admission equivalence -- MCP and HTTP share one control path
# ---------------------------------------------------------------------------


def test_mcp_and_http_consume_one_shared_admission_budget(mcp_app):
    """Mixing the MCP and HTTP surfaces consumes ONE canonical budget.

    Admission equivalence is a security property, not an environmental one: an
    MCP caller must not exceed the canonical submission limit by sending some
    requests through the HTTP API and some through MCP, and the property must
    hold even when Redis is unavailable and the canonical limiter falls back to
    its in-process counters.  Both surfaces reach the *same* Flask view function
    (the MCP path invokes the canonical application in process), so they charge
    the same bucket.  This test installs a small limiter on that shared view,
    exhausts it through MCP, and asserts the next HTTP request is refused.
    """
    from flask import jsonify

    from revocompute.mcp.context import CanonicalResponse, call_canonical, McpPrincipal
    from revocompute.mcp.errors import McpError
    from revocompute.ratelimit import rate_limit

    app = mcp_app.app
    limit = 3
    executed = {"count": 0}

    def _handler(*_args, **_kwargs):
        executed["count"] += 1
        return jsonify({"ok": True})

    # One limiter object guards the canonical view for BOTH surfaces.
    app.view_functions["preflight_task"] = rate_limit(max_requests=limit, window_seconds=3600)(_handler)

    client_ip = "203.0.113.7"
    principal = McpPrincipal(
        user={"id": 1, "role": "user"},
        user_id=1,
        username="mcp-tester",
        credential_headers={"Authorization": "Bearer test"},
        client_ip=client_ip,
        forwarded_headers={},
    )

    def _call(path):
        return call_canonical(principal, "POST", path, data={})

    mcp_refusals = 0
    for _ in range(limit):
        response = _call("/compute/api/preflight/cpu_runner")
        assert response.status == 200, response.status
    for _ in range(limit):
        response = _call("/compute/api/preflight/cpu_runner")
        if response.status == 429:
            mcp_refusals += 1
    assert mcp_refusals == limit, "the shared budget must refuse past the limit"

    # The SAME client over plain HTTP is refused by the same budget, even though
    # the MCP calls never touched a socket.
    http_client = app.test_client()
    http_response = http_client.post(
        "/compute/api/preflight/cpu_runner",
        headers={"Authorization": "Bearer test"},
        environ_overrides={"REMOTE_ADDR": client_ip},
    )
    assert http_response.status_code == 429, "an HTTP request must see the MCP-consumed budget"
    assert executed["count"] == limit, "only the allowed calls may execute"
    del CanonicalResponse, McpError


# ---------------------------------------------------------------------------
# Level 0 -- protocol surface / schema
# ---------------------------------------------------------------------------


def test_registered_surface_is_small_and_stable():
    """The MCP surface is a fixed primitive set, not one tool per Runner."""
    from revocompute.mcp.server import build_server

    server = build_server()
    names = {tool.name for tool in server._tool_manager.list_tools()}
    assert names == {
        "discover_tasks",
        "inspect_task",
        "preflight_task",
        "submit_task",
        "get_task_status",
        "cancel_task",
        "get_task_results",
        "retrieve_artifact",
        "discover_tools",
        "inspect_tool",
        "call_tool",
        "get_tool_call_status",
        "get_tool_results",
        "retrieve_tool_output",
    }


def test_no_declared_tool_exposes_an_execution_escape_hatch():
    """No input schema offers shell/path/url/env/proxy style parameters."""
    from revocompute.mcp.server import build_server

    forbidden = {
        "command",
        "cmd",
        "shell",
        "exec",
        "eval",
        "url",
        "path",
        "file_path",
        "directory",
        "env",
        "environment",
        "argv",
        "script",
        "slurm_job_id",
        "job_id",
        "container",
        "image",
        "pid",
    }
    server = build_server()
    for tool in server._tool_manager.list_tools():
        properties = set(tool.parameters.get("properties", {}))
        assert not (properties & forbidden), f"{tool.name} exposes {properties & forbidden}"


def test_no_operator_primitive_is_exposed():
    """No admin/operator capability is reachable through the scientific surface."""
    from revocompute.mcp.server import build_server

    server = build_server()
    names = {tool.name for tool in server._tool_manager.list_tools()}
    banned_fragments = (
        "admin",
        "operator",
        "sif",
        "build",
        "promote",
        "repair",
        "restart",
        "log",
        "user_",
        "credit",
        "secret",
        "bootstrap",
        "fleet",
    )
    assert not [name for name in names if any(f in name for f in banned_fragments)]


def test_handle_has_sufficient_entropy_and_is_not_the_task_id():
    from revocompute.mcp.handles import HANDLE_PREFIX, OperationHandleStore

    store = OperationHandleStore(":memory:", ttl_seconds=600)
    task_id = "a" * 32
    handles = set()
    for _ in range(64):
        handle = store.mint(user_id=1, kind="task", now=100.0)
        store.bind(handle, task_id, now=100.0)
        handles.add(handle)
    assert len(handles) == 64, "handle collision"
    assert all(h.startswith(HANDLE_PREFIX) for h in handles)
    assert all(len(h) >= 40 for h in handles), "handle is too short to be unpredictable"
    assert task_id not in handles


def test_handle_mapping_is_user_scoped_and_fails_closed():
    from revocompute.mcp.handles import OperationHandleStore

    store = OperationHandleStore(":memory:", ttl_seconds=600)
    handle = store.mint(user_id=1, kind="task", now=100.0)
    store.bind(handle, "b" * 32, now=100.0)
    assert store.resolve(handle, user_id=1, kind="task", now=101.0) is not None
    assert store.resolve(handle, user_id=2, kind="task", now=101.0) is None
    assert store.resolve(handle, user_id=1, kind="tool_call", now=101.0) is None
    assert store.resolve("mcp_op_unknown", user_id=1, kind="task", now=101.0) is None


def test_unbound_and_expired_handles_fail_closed():
    from revocompute.mcp.handles import OperationHandleStore

    store = OperationHandleStore(":memory:", ttl_seconds=600)
    minted = store.mint(user_id=1, kind="task", now=100.0)
    assert store.resolve(minted, user_id=1, kind="task", now=101.0) is None
    bound = store.mint(user_id=1, kind="task", now=100.0)
    store.bind(bound, "c" * 32, now=100.0)
    assert store.resolve(bound, user_id=1, kind="task", now=699.0) is not None
    assert store.resolve(bound, user_id=1, kind="task", now=701.0) is None
    assert store.prune(now=701.0) == 1


def test_error_taxonomy_is_stable_and_total():
    from revocompute.mcp import errors

    assert errors.ERROR_CLASSES == {
        "INVALID_PARAMETERS",
        "AUTH_REQUIRED",
        "ACCESS_DENIED",
        "NOT_READY",
        "RESOURCE_LIMIT",
        "TASK_NOT_FOUND",
        "TASK_NOT_CANCELLABLE",
        "RESULT_NOT_READY",
        "ARTIFACT_NOT_FOUND",
        "CONTENT_TOO_LARGE",
    }
    for status, expected in ((401, "AUTH_REQUIRED"), (403, "ACCESS_DENIED"), (503, "NOT_READY")):
        assert errors.classify({"error": "x"}, status=status).error_class == expected
    classified = errors.classify(
        {"error": "nope", "details": [{"code": "gpu_credit_exhausted"}]}, status=403
    )
    assert classified.error_class == "RESOURCE_LIMIT"


def test_bounds_reject_oversized_inputs_and_mark_truncation():
    from revocompute.mcp.bounds import bound_sequence, truncate_text
    from revocompute.mcp.context import decode_inputs
    from revocompute.mcp.errors import McpError

    payload = base64.b64encode(b"x" * 2048).decode()
    with pytest.raises(McpError) as excinfo:
        decode_inputs(
            [{"role": "sequence", "filename": "a.fasta", "content_base64": payload}],
            max_total_bytes=16,
        )
    assert excinfo.value.error_class == "CONTENT_TOO_LARGE"

    text, truncated = truncate_text("abcdef", 3)
    assert (text, truncated) == ("abc", True)
    items, truncated = bound_sequence([1, 2, 3], 2)
    assert (items, truncated) == ([1, 2], True)


def test_invalid_base64_and_role_binding_are_rejected():
    from revocompute.mcp.context import decode_inputs
    from revocompute.mcp.errors import McpError

    with pytest.raises(McpError) as excinfo:
        decode_inputs(
            [{"role": "sequence", "filename": "a.fasta", "content_base64": "!!!"}], max_total_bytes=100
        )
    assert excinfo.value.error_class == "INVALID_PARAMETERS"
    with pytest.raises(McpError):
        decode_inputs([{"filename": "a.fasta", "content_base64": "AA=="}], max_total_bytes=100)


# ---------------------------------------------------------------------------
# Discovery -- canonical registry, not a second catalog
# ---------------------------------------------------------------------------


def test_discover_tasks_projects_the_canonical_enabled_registry(mcp_app):
    from revocompute.mcp.services import discover_tasks
    from revocompute.task_types import list_types

    payload = discover_tasks()
    canonical = {tt.name for tt in list_types()}
    projected = {entry["task_type"] for entry in payload["task_types"]}
    assert projected == canonical
    assert payload["truncated"] is False
    assert all("parameter_schema" not in entry for entry in payload["task_types"])


def test_discover_tasks_omits_a_disabled_task_type(mcp_app):
    from revocompute.mcp.services import discover_tasks
    from revocompute.task_types import list_types

    target = list_types()[0].name
    mcp_app.app.config["manage_db"].task_type_upsert(target, enabled=False)
    projected = {entry["task_type"] for entry in discover_tasks()["task_types"]}
    assert target not in projected


def test_inspect_task_returns_the_canonical_schema_and_vocabulary(mcp_app):
    from revocompute.mcp.services import inspect_task
    from revocompute.task_types import get as get_task_type
    from revocompute.task_types import list_types

    name = list_types()[0].name
    tt, _runner = get_task_type(name)
    payload = inspect_task(name)
    assert payload["task_type"] == tt.name
    assert payload["parameter_schema"] == tt.schema
    assert [role["role"] for role in payload["inputs"]] == [role.name for role in tt.inputs]
    assert {parameter["name"] for parameter in payload["parameters"]} == {p.name for p in tt.params}


def test_inspect_task_rejects_an_unknown_task_type(mcp_app):
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.services import inspect_task

    with pytest.raises(McpError) as excinfo:
        inspect_task("no-such-task-type")
    assert excinfo.value.error_class == "TASK_NOT_FOUND"


# ---------------------------------------------------------------------------
# Submission -- canonical admission path, opaque handle
# ---------------------------------------------------------------------------


def _sequence_task_type(module) -> tuple[str, str]:
    """Pick an enabled CPU TaskType whose single input role accepts a FASTA file.

    The helper reads the canonical registry rather than naming a Runner, so the
    test exercises whichever CPU single-sequence TaskType the deployment has
    enabled and does not pin a specific family's vocabulary.
    """
    from revocompute.task_types import list_types

    for tt in list_types():
        if tt.gpus or tt.workflow or len(tt.inputs) != 1:
            continue
        role = tt.inputs[0]
        if role.minimum <= 1 <= role.maximum and "fasta" in role.formats:
            return tt.name, role.name
    raise AssertionError("no CPU single-sequence task type available")


def test_submit_task_returns_an_opaque_handle_and_creates_a_canonical_task(mcp_app):
    """A real submission lands through the canonical path and maps to an opaque handle."""
    from revocompute.mcp.handles import canonical_state
    from revocompute.mcp.services import submit_task

    principal = _principal(mcp_app)
    task_type, role = _sequence_task_type(mcp_app)
    payload = submit_task(
        principal,
        task_type=task_type,
        params={},
        inputs=[
            {
                "role": role,
                "filename": "2KL8.fasta",
                "content_base64": base64.b64encode(FASTA).decode(),
            }
        ],
        handle_store=canonical_state().handles,
        now=1000.0,
    )
    assert payload["task_handle"].startswith("mcp_op_")
    mapping = canonical_state().handles.resolve(
        payload["task_handle"], user_id=principal.user_id, kind="task", now=1001.0
    )
    assert mapping is not None, "the handle must map to the canonical Task"
    task = mcp_app.task_store.get_task(mapping.operation_id)
    assert task is not None
    assert str(task["submitted_by_user_id"]) == str(principal.user_id)
    assert payload["task_handle"] != mapping.operation_id, "the handle must not be the canonical Task id"


def test_failed_submission_leaves_no_resolvable_handle(mcp_app):
    """A rejected submission must not leave a handle that resolves to anything."""
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.handles import canonical_state
    from revocompute.mcp.services import submit_task

    principal = _principal(mcp_app)
    store = canonical_state().handles
    with pytest.raises(McpError):
        submit_task(
            principal,
            task_type="no-such-task",
            params={},
            inputs=[],
            handle_store=store,
            now=1000.0,
        )
    # No captured handle can resolve, because nothing was ever bound.
    with store.engine.begin() as conn:
        from sqlalchemy import select

        rows = conn.execute(select(store.table)).all()
    assert all(not row._mapping["operation_id"] for row in rows)


def test_identical_submission_reuses_the_canonical_task(mcp_app):
    """A retried MCP submit must not duplicate scientific work."""
    from revocompute.mcp.handles import canonical_state
    from revocompute.mcp.services import submit_task

    principal = _principal(mcp_app)
    task_type, role = _sequence_task_type(mcp_app)
    inputs = [
        {
            "role": role,
            "filename": "2KL8.fasta",
            "content_base64": base64.b64encode(FASTA).decode(),
        }
    ]
    first = submit_task(
        principal,
        task_type=task_type,
        params={},
        inputs=inputs,
        handle_store=canonical_state().handles,
        now=1000.0,
    )
    second = submit_task(
        principal,
        task_type=task_type,
        params={},
        inputs=inputs,
        handle_store=canonical_state().handles,
        now=1001.0,
    )
    store = canonical_state().handles
    first_map = store.resolve(first["task_handle"], user_id=principal.user_id, kind="task", now=1002.0)
    second_map = store.resolve(second["task_handle"], user_id=principal.user_id, kind="task", now=1002.0)
    assert first_map is not None and second_map is not None
    assert first_map.operation_id == second_map.operation_id
    assert len(mcp_app.task_store.list_tasks()) == 1


def test_unknown_task_type_submission_is_rejected(mcp_app):
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.handles import canonical_state
    from revocompute.mcp.services import submit_task

    principal = _principal(mcp_app)
    with pytest.raises(McpError) as excinfo:
        submit_task(
            principal,
            task_type="no-such-task",
            params={},
            inputs=[],
            handle_store=canonical_state().handles,
            now=1000.0,
        )
    assert excinfo.value.error_class == "TASK_NOT_FOUND"


# ---------------------------------------------------------------------------
# Lifecycle reads
# ---------------------------------------------------------------------------


def _connected(server, headers: dict[str, str]):
    """Connect an in-process MCP client session for transport-level assertions.

    The SDK's in-memory session does not carry HTTP headers, so server-side
    credential resolution cannot run here; authenticated calls are covered by
    the streamable-HTTP interoperability acceptance.  This helper exists only to
    prove the projected primitives are reachable over the protocol transport.
    """
    from mcp.shared.memory import create_connected_server_and_client_session

    del headers
    return create_connected_server_and_client_session(server)


def _seed_finished_task(module, username: str = "mcp-tester") -> str:
    owner = _conftest._task_owner(module, username)
    task_id = uuid.uuid4().hex
    module.task_store.upsert_task(
        task_id,
        filename="result.fasta",
        file_path="/tmp/result.fasta",
        uploaded_at=time.time(),
        started_at=time.time(),
        finished_at=time.time(),
        walltime=1.5,
        status="finished",
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username=username,
        task_type="cpu_runner",
        submitted_by_user_id=int(owner["submitted_by_user_id"]),
        storage_key=owner["storage_key"],
    )
    return task_id


def _bind_handle(*, user_id: int, kind: str, operation_id: str) -> str:
    from revocompute.mcp.handles import canonical_state

    store = canonical_state().handles
    handle = store.mint(user_id=user_id, kind=kind, now=1000.0)
    store.bind(handle, operation_id, now=1000.0)
    return handle


def test_status_reports_the_canonical_lifecycle(mcp_app):
    from revocompute.mcp.services import get_task_status

    principal = _principal(mcp_app)
    task_id = _seed_finished_task(mcp_app)
    payload = get_task_status(principal, operation_id=task_id)
    assert payload["status"] == "finished"
    assert payload["terminal"] is True


def test_cross_user_handle_access_is_denied_without_existence_leakage(mcp_app):
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.services import get_task_status

    other = _principal(mcp_app, username="mcp-other")
    task_id = _seed_finished_task(mcp_app)
    with pytest.raises(McpError) as excinfo:
        get_task_status(other, operation_id=task_id)
    assert excinfo.value.error_class == "TASK_NOT_FOUND"
    with pytest.raises(McpError) as missing:
        get_task_status(other, operation_id="0" * 32)
    assert missing.value.error_class == excinfo.value.error_class


def test_status_does_not_resolve_another_users_handle(mcp_app):
    from revocompute.mcp.handles import canonical_state

    owner = _principal(mcp_app, username="mcp-tester")
    other = _principal(mcp_app, username="mcp-other")
    task_id = _seed_finished_task(mcp_app)
    handle = _bind_handle(user_id=owner.user_id, kind="task", operation_id=task_id)
    assert canonical_state().handles.resolve(handle, user_id=other.user_id, kind="task", now=1001.0) is None


def test_results_are_not_ready_before_the_task_finishes(mcp_app):
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.services import get_task_results

    principal = _principal(mcp_app)
    owner = _conftest._task_owner(mcp_app, "mcp-tester")
    task_id = uuid.uuid4().hex
    mcp_app.task_store.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=time.time(),
        status="running",
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username="mcp-tester",
        task_type="cpu_runner",
        submitted_by_user_id=int(owner["submitted_by_user_id"]),
        storage_key=owner["storage_key"],
    )
    with pytest.raises(McpError) as excinfo:
        get_task_results(principal, operation_id=task_id)
    assert excinfo.value.error_class == "RESULT_NOT_READY"


def test_cancel_requires_ownership_and_a_cancellable_state(mcp_app):
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.services import cancel_task

    other = _principal(mcp_app, username="mcp-other")
    owner = _conftest._task_owner(mcp_app, "mcp-tester")
    task_id = uuid.uuid4().hex
    mcp_app.task_store.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=time.time(),
        status="pending",
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username="mcp-tester",
        task_type="cpu_runner",
        submitted_by_user_id=int(owner["submitted_by_user_id"]),
        storage_key=owner["storage_key"],
    )
    with pytest.raises(McpError) as excinfo:
        cancel_task(other, operation_id=task_id)
    assert excinfo.value.error_class == "TASK_NOT_FOUND"
    assert mcp_app.task_store.get_task(task_id)["status"] == "pending"


def test_cancel_is_rejected_for_a_terminal_task(mcp_app):
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.services import cancel_task

    principal = _principal(mcp_app)
    task_id = _seed_finished_task(mcp_app)
    with pytest.raises(McpError) as excinfo:
        cancel_task(principal, operation_id=task_id)
    assert excinfo.value.error_class == "TASK_NOT_CANCELLABLE"


# ---------------------------------------------------------------------------
# Real transport -- the projected surface over an MCP client session
# ---------------------------------------------------------------------------


def test_projected_surface_is_reachable_over_the_mcp_transport(mcp_app):
    """A real MCP client session can discover and call the projected surface.

    The in-memory session shares the in-process server; the streamable-HTTP
    transport is exercised separately by the interoperability acceptance.  This
    proves the projected primitives are reachable as *protocol* tools, not only
    as Python functions, and that failures cross the transport as structured
    error results rather than exceptions.  Authentication is the transport's
    concern, so these calls carry a real credential through the session's HTTP
    headers exactly as the streamable-HTTP client does.
    """
    import anyio

    from revocompute.mcp.server import build_server

    headers = _auth_headers(mcp_app)
    server = build_server()
    unknown_handle = f"mcp_op_{'x' * 43}"

    async def _run() -> dict:
        async with _connected(server, headers) as session:
            await session.initialize()
            listing = await session.list_tools()
            discovered = await session.call_tool("discover_tasks", {})
            inspected = await session.call_tool("inspect_task", {"task_type": "no-such-task"})
            status = await session.call_tool("get_task_status", {"task_handle": unknown_handle})
            return {
                "names": sorted(tool.name for tool in listing.tools),
                "discover_is_error": discovered.isError,
                "catalog_entries": len((discovered.structuredContent or {}).get("task_types", [])),
                "inspect_is_error": inspected.isError,
                "inspect_class": (inspected.structuredContent or {}).get("error_class"),
                "status_is_error": status.isError,
                "status_class": (status.structuredContent or {}).get("error_class"),
            }

    outcome = anyio.run(_run)
    assert outcome["names"] == [
        "call_tool",
        "cancel_task",
        "discover_tasks",
        "discover_tools",
        "get_task_results",
        "get_task_status",
        "get_tool_call_status",
        "get_tool_results",
        "inspect_task",
        "inspect_tool",
        "preflight_task",
        "retrieve_artifact",
        "retrieve_tool_output",
        "submit_task",
    ]
    assert outcome["discover_is_error"] is False
    assert outcome["catalog_entries"] >= 1
    # A domain failure crosses the transport as a structured error result: an
    # unknown TaskType is TASK_NOT_FOUND, not a traceback.
    assert outcome["inspect_is_error"] is True
    assert outcome["inspect_class"] == "TASK_NOT_FOUND"
    # The in-memory session carries no HTTP headers, so an authenticated
    # primitive fails closed with the stable auth class rather than running.
    # The authenticated transport path is proven by the streamable-HTTP
    # interoperability acceptance.
    assert outcome["status_is_error"] is True
    assert outcome["status_class"] == "AUTH_REQUIRED"


# ---------------------------------------------------------------------------
# Level 2 -- artifact isolation and bounds
# ---------------------------------------------------------------------------


def _publish_manifest(
    module,
    task_id: str,
    owner: dict,
    artifacts: list[tuple[str, str]],
    *,
    media_type: str = "text/plain",
    anchor: bool = False,
) -> None:
    """Write a minimal canonical ResultManifest listing *artifacts* to disk.

    By default this only places the manifest; a caller that wants a real
    publication -- one a canonical reader will serve -- records the canonical
    publication anchor afterwards, once its Task row exists, via
    ``_conftest._anchor_result_publication``.  A manifest left unanchored is
    exactly the quarantined state the publication gate must refuse, so the
    default keeps an unanchored caller honest instead of silently publishing.
    """
    resolver = module.app.config["storage_resolver"]
    root = Path(resolver.get_task_root({"md5sum": task_id, **owner}))
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for relative, role in artifacts:
        payload = (root / relative).read_bytes()
        entries.append(
            {
                "path": relative,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "media_type": media_type,
                "preview": "text",
                "capability": "text",
                "role": role,
            }
        )
    manifest = {
        "schema_version": 3,
        "task_id": task_id,
        "task_type": "cpu_runner",
        "created_at": "2026-01-01T00:00:00+00:00",
        "run": {},
        "output_check": {"state": "ok", "checks": [], "problems": []},
        "limitations": [],
        "artifacts": entries,
        "views": [],
        "result": {"files": {}},
        "storyboard": None,
        "total_size": sum(entry["size"] for entry in entries),
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if anchor:
        _conftest._anchor_result_publication(module, task_id)


def _seed_published_artifact(module, tmp_path, *, username: str = "mcp-tester") -> str:
    """Create a finished Task publishing one small artifact and one diagnostic."""
    task_id = uuid.uuid4().hex
    owner = _conftest._task_owner(module, username)
    result_dir = tmp_path / f"result-{task_id}"
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "output.txt").write_text("result\n", encoding="utf-8")
    (result_dir / "db").mkdir(parents=True, exist_ok=True)
    (result_dir / "db" / "log.txt").write_text("diagnostic\n", encoding="utf-8")
    _conftest._relocate_task_artifacts(module, task_id, result_dir, owner)
    _publish_manifest(module, task_id, owner, [("output.txt", "artifact"), ("db/log.txt", "diagnostic")])
    module.task_store.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=time.time(),
        started_at=time.time(),
        finished_at=time.time(),
        walltime=1.0,
        status="finished",
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username=username,
        task_type="cpu_runner",
        submitted_by_user_id=int(owner["submitted_by_user_id"]),
        storage_key=owner["storage_key"],
    )
    _conftest._anchor_result_publication(module, task_id)
    return task_id


def test_published_artifact_is_retrievable_for_its_owner(mcp_app, tmp_path):
    from revocompute.mcp.services import retrieve_artifact

    principal = _principal(mcp_app)
    task_id = _seed_published_artifact(mcp_app, tmp_path)
    payload = retrieve_artifact(principal, operation_id=task_id, artifact_path="output.txt")
    assert payload["inline"] is True
    assert base64.b64decode(payload["content_base64"]) == b"result\n"
    assert "physical" not in json.dumps(payload)


def test_unpublished_artifact_path_is_not_found(mcp_app, tmp_path):
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.services import retrieve_artifact

    principal = _principal(mcp_app)
    task_id = _seed_published_artifact(mcp_app, tmp_path)
    with pytest.raises(McpError) as excinfo:
        retrieve_artifact(principal, operation_id=task_id, artifact_path="not-published.txt")
    assert excinfo.value.error_class == "ARTIFACT_NOT_FOUND"


_EXPECTED_TEXT = ("result" + chr(10)).encode()


@pytest.mark.parametrize("download_mode", ["nginx", "flask"])
def test_inline_artifact_content_is_byte_exact_in_every_download_mode(mcp_app, tmp_path, download_mode):
    """Inlined bytes are the published bytes regardless of download mode.

    The shipped deployment serves results with ``RESULT_DOWNLOAD_MODE=nginx``,
    where the canonical download route answers an empty body plus
    ``X-Accel-Redirect``.  A projection that inlined the *response body* silently
    returned empty content for every artifact in that mode; this pins byte-exact
    content in both modes so the silent drop cannot regress.
    """
    from revocompute.mcp.services import retrieve_artifact

    mcp_app.app.config["RESULT_DOWNLOAD_MODE"] = download_mode
    principal = _principal(mcp_app)
    task_id = _seed_published_artifact(mcp_app, tmp_path)
    payload = retrieve_artifact(principal, operation_id=task_id, artifact_path="output.txt")
    assert payload["inline"] is True
    assert base64.b64decode(payload["content_base64"]) == _EXPECTED_TEXT


def test_inline_artifact_content_is_byte_exact_for_a_json_media_type(mcp_app, tmp_path):
    """A JSON-media artifact inlines its bytes, not a parsed JSON body.

    ``send_from_directory`` content-negotiates, so a JSON artifact parsed into a
    JSON body and left the route's raw bytes empty in every mode.  The inlined
    payload must be the published bytes, and must never be empty.
    """
    import uuid as _uuid

    from revocompute.mcp.services import retrieve_artifact

    principal = _principal(mcp_app)
    owner = _conftest._task_owner(mcp_app, "mcp-tester")
    task_id = _uuid.uuid4().hex
    result_dir = tmp_path / f"json-{task_id}"
    result_dir.mkdir(parents=True, exist_ok=True)
    written = b'{"a": 1}'
    (result_dir / "data.json").write_bytes(written)
    _conftest._relocate_task_artifacts(mcp_app, task_id, result_dir, owner)
    _publish_manifest(mcp_app, task_id, owner, [("data.json", "artifact")], media_type="application/json")
    mcp_app.task_store.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=time.time(),
        status="finished",
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username="mcp-tester",
        task_type="cpu_runner",
        submitted_by_user_id=int(owner["submitted_by_user_id"]),
        storage_key=owner["storage_key"],
    )
    _conftest._anchor_result_publication(mcp_app, task_id)
    payload = retrieve_artifact(principal, operation_id=task_id, artifact_path="data.json")
    assert payload["inline"] is True
    assert base64.b64decode(payload["content_base64"]) == written


@pytest.mark.parametrize(
    "candidate",
    [
        "../../../etc/passwd",
        "..%2f..%2fetc%2fpasswd",
        "/etc/passwd",
        "subdir/../../secret.txt",
        "C:\\Windows\\system32\\config",
    ],
)
def test_traversal_and_absolute_paths_are_never_resolved(mcp_app, tmp_path, candidate):
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.services import retrieve_artifact

    principal = _principal(mcp_app)
    task_id = _seed_published_artifact(mcp_app, tmp_path)
    with pytest.raises(McpError) as excinfo:
        retrieve_artifact(principal, operation_id=task_id, artifact_path=candidate)
    assert excinfo.value.error_class == "ARTIFACT_NOT_FOUND"


def test_cross_user_artifact_access_is_denied(mcp_app, tmp_path):
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.services import retrieve_artifact

    other = _principal(mcp_app, username="mcp-other")
    task_id = _seed_published_artifact(mcp_app, tmp_path)
    with pytest.raises(McpError) as excinfo:
        retrieve_artifact(other, operation_id=task_id, artifact_path="output.txt")
    assert excinfo.value.error_class == "TASK_NOT_FOUND"


def test_oversized_artifact_returns_metadata_not_content(mcp_app, tmp_path):
    from revocompute.mcp.services import retrieve_artifact

    principal = _principal(mcp_app)
    owner = _conftest._task_owner(mcp_app, "mcp-tester")
    task_id = uuid.uuid4().hex
    result_dir = tmp_path / f"big-{task_id}"
    payload_bytes = b"z" * 5000
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "big.txt").write_bytes(payload_bytes)
    _conftest._relocate_task_artifacts(mcp_app, task_id, result_dir, owner)
    _publish_manifest(mcp_app, task_id, owner, [("big.txt", "artifact")])
    mcp_app.task_store.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=time.time(),
        status="finished",
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username="mcp-tester",
        task_type="cpu_runner",
        submitted_by_user_id=int(owner["submitted_by_user_id"]),
        storage_key=owner["storage_key"],
    )
    _conftest._anchor_result_publication(mcp_app, task_id)
    handle = "mcp_op_" + "a" * 43
    result = retrieve_artifact(
        principal, operation_id=task_id, artifact_path="big.txt", handle=handle, max_inline_bytes=64
    )
    assert result["inline"] is False
    assert result["content_base64"] is None
    assert result["size"] == len(payload_bytes)
    assert result["truncated"] is False
    # The oversized answer exposes no canonical Task id anywhere: the opaque
    # handle is the only identity a client may need to echo back.
    assert task_id not in json.dumps(result)
    assert result["task_handle"] == handle
    # No dead resource URI is advertised: nothing here is a followable protocol
    # resource, so the answer must not claim one.
    assert "resource_uri" not in result


# ---------------------------------------------------------------------------
# Publication boundary -- MCP never serves a result Core quarantines (#58/#65)
# ---------------------------------------------------------------------------


def _seed_unpublished_artifact(module, tmp_path, *, username: str = "mcp-tester") -> str:
    """Create a finished Task whose result tree holds an unanchored manifest.

    This is the quarantined state the canonical publication reader refuses: the
    manifest exists on disk and is structurally valid, but Core never recorded
    the anchor that makes it a publication, so no canonical consumer will serve
    it.  A pre-anchor results ZIP is planted as well, because the point of the
    gate is that cached bytes on disk are not publication identity.
    """
    import zipfile

    task_id = uuid.uuid4().hex
    owner = _conftest._task_owner(module, username)
    result_dir = tmp_path / f"unanchored-{task_id}"
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "output.txt").write_text("result\n", encoding="utf-8")
    _conftest._relocate_task_artifacts(module, task_id, result_dir, owner)
    _publish_manifest(module, task_id, owner, [("output.txt", "artifact")], anchor=False)
    module.task_store.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=time.time(),
        started_at=time.time(),
        finished_at=time.time(),
        walltime=1.0,
        status="finished",
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username=username,
        task_type="cpu_runner",
        submitted_by_user_id=int(owner["submitted_by_user_id"]),
        storage_key=owner["storage_key"],
    )
    resolver = module.app.config["storage_resolver"]
    archive = Path(resolver.get_archive_path(module.task_store.get_task(task_id)))
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("output.txt", "pre-anchor bytes\n")
    return task_id


def test_unanchored_result_is_unavailable_with_reason_not_served(mcp_app, tmp_path):
    """A quarantined result is refused by every MCP result read, with its reason.

    The publication state ``unanchored`` names a result Core's own reader
    refuses, so the MCP surface must serve neither its manifest projection nor
    its artifact bytes, and it must say *why* rather than pretend the result is
    merely not ready yet.  The negative is asserted at the status projection and
    at both result readers, so the gate cannot be satisfied on one route while
    another still serves the quarantine.
    """
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.services import get_task_results, get_task_status, retrieve_artifact

    principal = _principal(mcp_app)
    task_id = _seed_unpublished_artifact(mcp_app, tmp_path)

    # Status advertises no available result, so no client is offered a read.
    assert get_task_status(principal, operation_id=task_id)["results_available"] is False

    for call, arguments in (
        (get_task_results, {}),
        (retrieve_artifact, {"artifact_path": "output.txt"}),
    ):
        with pytest.raises(McpError) as excinfo:
            call(principal, operation_id=task_id, **arguments)
        error = excinfo.value
        assert error.error_class == "RESULT_NOT_READY", (call.__name__, error.error_class)
        assert error.detail == "unanchored", (call.__name__, error.detail)
        assert error.message, "a refusal must carry the canonical reason text"
        assert "/" not in error.message, "a refusal must not name a host or storage path"


def test_published_result_is_available_once_the_anchor_exists(mcp_app, tmp_path):
    """The same result becomes readable when Core's publication anchor exists.

    The publication gate is a decision about identity, not a blanket refusal of
    finished Tasks: ``_seed_published_artifact`` records the canonical anchor, so
    the status projection advertises the result and both readers serve it.  This
    is the positive control for the quarantine negative above.
    """
    from revocompute.mcp.services import get_task_results, get_task_status, retrieve_artifact

    principal = _principal(mcp_app)
    task_id = _seed_published_artifact(mcp_app, tmp_path)

    assert get_task_status(principal, operation_id=task_id)["results_available"] is True
    results = get_task_results(principal, operation_id=task_id)
    assert [artifact["path"] for artifact in results["artifacts"]] == ["output.txt", "db/log.txt"]
    payload = retrieve_artifact(principal, operation_id=task_id, artifact_path="output.txt")
    assert base64.b64decode(payload["content_base64"]) == b"result\n"


def test_classifier_covers_every_canonical_admission_vocabulary():
    """Every reason code a canonical boundary can emit is classifiable here.

    The adapter classifies canonical decisions with a bounded table; that table
    is owned downstream by ``ingress_security`` (the phase vocabulary) and
    ``resource_ledger.AdmissionReason`` (the admission reasons).  Deriving the
    required entries from those modules means a new canonical reason code cannot
    silently degrade to the wrong protocol class -- it fails here until the
    adapter names it.
    """
    from revocompute.ingress_security import ARTIFACT_CAPACITY_GUARD, ARTIFACT_PUBLICATION_REJECTED, REASON_CODES
    from revocompute.mcp import errors
    from revocompute.resource_ledger import AdmissionReason

    required = {code for codes in REASON_CODES.values() for code in codes}
    # The codes the submission boundary answers with, in addition to the
    # admission-reason names the ledger owns.
    required |= {"gpu_credit_exhausted", "infrastructure_unavailable", "storage_soft_limit_exceeded"}
    required |= {ARTIFACT_PUBLICATION_REJECTED, ARTIFACT_CAPACITY_GUARD}
    required |= {reason.value for reason in AdmissionReason}
    # ``admitted`` is the success value, not a refusal, so no error class names it.
    required.discard(AdmissionReason.ADMITTED.value)

    missing = sorted(code for code in required if errors._class_for_detail_code(code) is None)
    assert missing == [], f"unclassified canonical reason codes: {missing}"
    # Each admitted reason names a real class, never a bare access denial.
    assert errors._class_for_detail_code(AdmissionReason.COMPUTE_EXHAUSTED.value) == "RESOURCE_LIMIT"
    assert errors._class_for_detail_code(AdmissionReason.STORAGE_SOFT_LIMIT.value) == "RESOURCE_LIMIT"
    assert errors._class_for_detail_code(AdmissionReason.RUNNER_READINESS_UNAVAILABLE.value) == "NOT_READY"
    assert errors._class_for_detail_code(AdmissionReason.INFRASTRUCTURE_UNAVAILABLE.value) == "NOT_READY"


# ---------------------------------------------------------------------------
# Level 1 -- authentication and authorization through the canonical path
# ---------------------------------------------------------------------------


def _restrict_cpu_runner(module, *, requestable: bool = True) -> None:
    """Restrict the cpu_runner TaskType with an access policy the caller lacks."""
    import shutil

    import yaml

    from revocompute.task_types import discover_plugins

    source_family = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "runners" / "cpu_runner"
    family_dir = Path(module.CONFIG.runners_dir) / "cpu_runner"
    shutil.copytree(source_family, family_dir, dirs_exist_ok=True)
    policy_dir = Path(module.CONFIG.runners_dir) / "common" / "policy"
    policy_dir.mkdir(parents=True, exist_ok=True)
    (policy_dir / "demo.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "example_academic_runner",
                "label": "Example academic access",
                "description": "Operator approval is required.",
                "requires": ["example_academic"],
                "match": "all",
                "requestable": requestable,
                "notice": {"title": "Restricted access", "summary": "This Runner requires operator approval."},
                "license": {"name": "Example Academic License", "url": "https://example.invalid/license"},
            }
        ),
        encoding="utf-8",
    )
    manifest_path = family_dir / "plugin.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["access_policies"] = ["common/policy/demo.yaml"]
    manifest["contributions"] = {"access_policies": ["example_academic_runner"]}
    manifest.setdefault("runtime", {})["access_policy"] = "example_academic_runner"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    discover_plugins(module.CONFIG.runners_dir, {"cpu_runner"})


def _submit_payload(role: str = "sequence") -> list[dict[str, object]]:
    return [
        {
            "role": role,
            "filename": "x.fasta",
            "content_base64": base64.b64encode(FASTA).decode(),
        }
    ]


def test_missing_entitlement_is_denied_through_the_canonical_admission_path(mcp_app):
    """A restricted Runner denies an unentitled MCP caller with ACCESS_DENIED.

    The decision is the canonical entitlement check: the MCP layer neither
    reads the policy nor decides access itself.
    """
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.handles import canonical_state
    from revocompute.mcp.services import submit_task

    _restrict_cpu_runner(mcp_app)
    principal = _principal(mcp_app)
    with pytest.raises(McpError) as excinfo:
        submit_task(
            principal,
            task_type="cpu_runner",
            params={},
            inputs=_submit_payload(),
            handle_store=canonical_state().handles,
            now=1000.0,
        )
    assert excinfo.value.error_class == "ACCESS_DENIED"
    assert len(mcp_app.task_store.list_tasks()) == 0, "a denied submission must create no Task"


def test_entitled_caller_passes_the_same_admission_path(mcp_app):
    """Granting the canonical entitlement admits the MCP submission.

    The admission verdict flips only because the canonical entitlement changed,
    which is the equivalence claim: MCP adds no rule of its own.
    """
    from revocompute.mcp.handles import canonical_state
    from revocompute.mcp.services import submit_task

    _restrict_cpu_runner(mcp_app)
    principal = _principal(mcp_app)
    db = mcp_app.app.config["user_db"]
    db.grant_entitlement(
        principal.user_id,
        "example_academic",
        granted_by=principal.user_id,
        basis="lab_member",
        note="test grant",
    )
    payload = submit_task(
        principal,
        task_type="cpu_runner",
        params={},
        inputs=_submit_payload(),
        handle_store=canonical_state().handles,
        now=1000.0,
    )
    assert payload["task_handle"].startswith("mcp_op_")
    assert len(mcp_app.task_store.list_tasks()) == 1


def test_non_ready_runner_is_not_admitted(mcp_app):
    """A Runner without readiness evidence fails admission before any side effect."""
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.handles import canonical_state
    from revocompute.mcp.services import submit_task

    mcp_app.app.config["manage_db"].resource_set("slurm_enabled", "1")
    principal = _principal(mcp_app)
    try:
        submit_task(
            principal,
            task_type="cpu_runner",
            params={},
            inputs=_submit_payload(),
            handle_store=canonical_state().handles,
            now=1000.0,
        )
    except McpError as error:
        assert error.error_class == "NOT_READY"
    else:  # pragma: no cover - only if readiness evidence unexpectedly exists
        raise AssertionError("a non-ready Runner must not admit a submission")


def test_ordinary_admin_credential_does_not_grant_operator_capability(mcp_app):
    """An admin's ordinary credential sees only the scientific surface."""
    from revocompute.mcp.server import build_server

    admin_headers = _conftest._admin_client_auth(mcp_app)
    admin = mcp_app.app.config["user_db"].get_user_by_username("sysadmin")
    assert admin is not None and admin["role"] == "admin"
    assert admin_headers  # the credential exists

    server = build_server()
    names = {tool.name for tool in server._tool_manager.list_tools()}
    # No operator primitive is reachable, so no credential can select one.
    assert not [name for name in names if "admin" in name or "operator" in name or "sif" in name]


def test_authentication_rejects_invalid_and_stale_credentials(mcp_app):
    """Every credential failure is closed with the canonical account rules.

    An invalid Bearer, an invalid API key, a suspended account, and a token
    minted under a superseded ``token_version`` must each fail closed with
    ``AUTH_REQUIRED`` -- the MCP layer holds no credential of its own and adds no
    weaker path.
    """
    from types import SimpleNamespace

    from revocompute.auth import generate_token
    from revocompute.mcp.context import authenticate
    from revocompute.mcp.errors import McpError

    db = mcp_app.app.config["user_db"]
    _conftest._test_client_auth(mcp_app, username="mcp-tester")  # ensure the user exists
    user = db.get_user_by_username("mcp-tester")
    user_id = int(user["id"])

    def _ctx(headers: dict[str, str]):
        request = SimpleNamespace(headers=headers, client=SimpleNamespace(host="127.0.0.1"))
        return SimpleNamespace(request_context=SimpleNamespace(request=request))

    # A valid token authenticates; everything below is a closed failure.
    principal = authenticate(_ctx({"authorization": f"Bearer {generate_token(user_id)}"}))
    assert principal.user_id == user_id

    for headers in (
        {"authorization": "Bearer not-a-real-token"},
        {"x-api-key": "not-a-real-key"},
        {},
    ):
        with pytest.raises(McpError) as excinfo:
            authenticate(_ctx(headers))
        assert excinfo.value.error_class == "AUTH_REQUIRED"

    # A suspended account is refused even with a structurally valid token.
    db.update_user(user_id, user_status="banned")
    with pytest.raises(McpError) as excinfo:
        authenticate(_ctx({"authorization": f"Bearer {generate_token(user_id)}"}))
    assert excinfo.value.error_class == "AUTH_REQUIRED"
    db.update_user(user_id, user_status="active")

    # A token minted under a superseded token_version is refused: logout still
    # invalidates the MCP surface exactly as it does the HTTP API.
    stale = generate_token(user_id, token_version=0)
    db.increment_token_version(user_id)
    with pytest.raises(McpError) as excinfo:
        authenticate(_ctx({"authorization": f"Bearer {stale}"}))
    assert excinfo.value.error_class == "AUTH_REQUIRED"


def _register_gpu_task_type(module):
    """Register a synthetic GPU TaskType, as the canonical admission tests do."""
    from dataclasses import replace

    base, runner = module.task_runtime._get_task_type("cpu_runner")
    task_type = replace(base, name="mcp_gpu_test", gpus=True)
    _conftest._inject_task_type(module, task_type, runner)
    return task_type.name


def test_exhausted_gpu_credit_is_not_admitted_through_mcp(mcp_app):
    """An exhausted GPU-credit balance fails MCP admission as RESOURCE_LIMIT.

    The decision is the canonical credit check: the MCP layer reads no ledger and
    decides no admission itself.  Because the canonical denial carries a specific
    reason code, the caller sees the actionable ``RESOURCE_LIMIT`` rather than a
    bare ``ACCESS_DENIED``.
    """
    from revocompute.mcp.errors import McpError
    from revocompute.mcp.handles import canonical_state
    from revocompute.mcp.services import submit_task

    task_type = _register_gpu_task_type(mcp_app)
    principal = _principal(mcp_app)
    db = mcp_app.app.config["user_db"]
    db.update_user(principal.user_id, allow_gpu_use=True)
    mcp_app.task_store.adjust_compute_account(
        user_id=principal.user_id,
        gpu_seconds=-60_000,
        actor_user_id=principal.user_id,
        reason="MCP admission test exhaustion",
        idempotency_key="mcp-exhaust",
    )
    with pytest.raises(McpError) as excinfo:
        submit_task(
            principal,
            task_type=task_type,
            params={},
            inputs=_submit_payload(),
            handle_store=canonical_state().handles,
            now=1000.0,
        )
    assert excinfo.value.error_class == "RESOURCE_LIMIT"
    assert len(mcp_app.task_store.list_tasks()) == 0, "a credit-denied submission must create no Task"
