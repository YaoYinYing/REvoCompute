# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Live interoperability acceptance for the REvoCompute MCP surface.

Runs the *deployed* shape: the canonical web process starts the MCP companion
listener in its own process, and an official MCP client talks to it over
streamable HTTP on a real socket.  It exercises the complete progressive
workflow and the negative/security cases, and prints a machine-readable receipt.

Nothing here is a substitute for a GPU or Slurm deployment: the scientific
submission is only required to reach the canonical admission decision, and the
result/artifact half is driven from a seeded finished Task so the protocol path
is proven without occupying an accelerator.

Usage::

    python tests/mcp_live_acceptance.py [--port 8181] [--json]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FASTA = b">accept\nACDEFGHIKLMNPQRSTVWY\n"


def _isolated_env(root: Path) -> None:
    """Prepare an isolated server instance the way ``restart.sh setup`` does."""
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "runtime-bundles").mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / "config" / "access_policies", root / "config" / "access_policies", dirs_exist_ok=True)
    shutil.copytree(REPO_ROOT / "docker" / "runners", root / "docker" / "runners")
    shutil.copytree(REPO_ROOT / "docker" / "tools", root / "docker" / "tools")
    # A real deployment materializes each family's Runtime Bundle before it
    # accepts submissions; a submission fails closed without one.
    from revocompute import runtime_bundle
    from revocompute.plugins import PluginManager

    index: dict[str, str] = {}
    store_root = root / "runtime-bundles"
    for manifest in PluginManager().discover(str(root / "docker" / "runners")):
        if not manifest.runtime_overlay:
            continue
        index[manifest.id] = runtime_bundle.materialize(
            root / "docker" / "runners", manifest.runtime_overlay, store_root
        )[0]
    runtime_bundle.write_index(store_root, index)
    os.environ.update(
        {
            "SERVER_DIR": str(root),
            "DB_PATH": str(root / "tasks.sqlite3"),
            "MANAGE_DB_PATH": str(root / "manage.sqlite3"),
            "LOG_DIR": str(root / "logs"),
            "CONFIG_DIR": str(root / "config"),
            "RUNTIME_BUNDLE_DIR": str(root / "runtime-bundles"),
            "ADMIN_USERS": "admin",
            "ADMIN_BOOTSTRAP_CREDENTIALS": "admin\tlive-test-password",
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            # A dead Redis keeps the limiter's per-process fallback honest and
            # removes an external dependency from the acceptance run.
            "REDIS_URL": "redis://127.0.0.1:1/0",
        }
    )


def _seed_finished_task(
    module,
    username: str = "mcp-acceptance",
    *,
    artifact_name: str = "output.txt",
    payload: bytes = b"acceptance-artifact\n",
    anchor: bool = True,
) -> tuple[str, str]:
    """Create a finished Task publishing one artifact, and return (task_id, token).

    ``anchor=True`` records the canonical publication anchor, as Core's own
    finalization does, so the result is a real publication the canonical surface
    serves.  ``anchor=False`` leaves a structurally valid manifest with no
    server-owned anchor: the quarantined state every canonical reader refuses,
    which is what the publication negative exercises.
    """
    from revocompute.auth import generate_token

    db = module.app.config["user_db"]
    user = db.get_user_by_username(username)
    if user is None:
        user = db.create_user(
            username=username,
            email=f"{username}@acceptance.local",
            password="acceptance-password",
            registration_status="approved",
            user_status="active",
        )
        db.verify_email(user["id"])
    owner = {"submitted_by_user_id": int(user["id"]), "storage_key": user["storage_key"]}
    task_id = hashlib.sha256(f"{username}:{artifact_name}:{time.time_ns()}".encode()).hexdigest()[:32]
    resolver = module.app.config["storage_resolver"]
    root = Path(resolver.get_task_root({"md5sum": task_id, **owner}))
    root.mkdir(parents=True, exist_ok=True)
    (root / artifact_name).write_bytes(payload)
    manifest = {
        "schema_version": 3,
        "task_id": task_id,
        "task_type": "gremlin",
        "created_at": "2026-01-01T00:00:00+00:00",
        "run": {},
        "output_check": {"state": "ok", "checks": [], "problems": []},
        "limitations": [],
        "artifacts": [
            {
                "path": artifact_name,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "media_type": "text/plain",
                "preview": "text",
                "capability": "text",
                "role": "artifact",
            }
        ],
        "views": [],
        "result": {"files": {}},
        "storyboard": None,
        "total_size": len(payload),
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
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
        user_agent="mcp-acceptance",
        username=username,
        task_type="gremlin",
        submitted_by_user_id=int(user["id"]),
        storage_key=user["storage_key"],
    )
    if anchor:
        data = (root / "manifest.json").read_bytes()
        module.task_store.record_result_publication(
            task_id,
            manifest_sha256=hashlib.sha256(data).hexdigest(),
            manifest_size=len(data),
            published_at=time.time(),
        )
    return task_id, generate_token(user["id"])


def _mint_handle(module, user_id: int, task_id: str) -> str:
    from revocompute.mcp.handles import canonical_state

    store = canonical_state().handles
    handle = store.mint(user_id=user_id, kind="task", now=time.time())
    store.bind(handle, task_id, now=time.time())
    return handle


async def _workflow(
    url: str,
    token_a: str,
    token_b: str,
    handle_a: str,
    handle_b: str,
    handle_big: str,
    big_task_id: str,
    quarantined_handle: str,
    submit_task_type: str,
    submit_role: str,
) -> dict:
    """Drive the complete workflow plus the negative cases over a real client."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    receipt: dict = {"steps": {}}

    def _session(auth: str):
        return streamablehttp_client(url, headers={"Authorization": f"Bearer {auth}"})

    async with _session(token_a) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            receipt["protocol_version"] = init.protocolVersion
            receipt["server"] = init.serverInfo.model_dump()
            tools = await session.list_tools()
            receipt["tools"] = sorted(tool.name for tool in tools.tools)

            discovered = await session.call_tool("discover_tasks", {})
            catalog = (discovered.structuredContent or {}).get("task_types", [])
            receipt["steps"]["discover_tasks"] = {
                "error": discovered.isError,
                "count": len(catalog),
                "sample": catalog[0]["task_type"] if catalog else None,
            }

            if catalog:
                target = catalog[0]["task_type"]
                inspected = await session.call_tool("inspect_task", {"task_type": target})
                receipt["steps"]["inspect_task"] = {
                    "error": inspected.isError,
                    "task_type": (inspected.structuredContent or {}).get("task_type"),
                    "has_schema": bool((inspected.structuredContent or {}).get("parameter_schema")),
                }

            preflight = await session.call_tool(
                "preflight_task",
                {
                    "task_type": submit_task_type,
                    "params": {},
                    "inputs": [
                        {
                            "role": submit_role,
                            "filename": "accept.fasta",
                            "content_base64": base64.b64encode(FASTA).decode(),
                        }
                    ],
                },
            )
            receipt["steps"]["preflight_task"] = {
                "error": preflight.isError,
                "valid": (preflight.structuredContent or {}).get("valid"),
                "error_class": (preflight.structuredContent or {}).get("error_class"),
            }

            submitted = await session.call_tool(
                "submit_task",
                {
                    "task_type": submit_task_type,
                    "params": {},
                    "inputs": [
                        {
                            "role": submit_role,
                            "filename": "accept.fasta",
                            "content_base64": base64.b64encode(FASTA).decode(),
                        }
                    ],
                },
            )
            submitted_handle = (submitted.structuredContent or {}).get("task_handle")
            receipt["steps"]["submit_task"] = {
                "error": submitted.isError,
                "handle_returned": bool(submitted_handle),
                "error_class": (submitted.structuredContent or {}).get("error_class"),
                "message": (submitted.structuredContent or {}).get("message"),
            }
            # Guarantee parity: the protocol handle is opaque, is not the
            # canonical Task id, and is re-authorized on every access.
            if submitted_handle:
                receipt["handle_guarantees"] = {
                    "opaque_prefix": submitted_handle.startswith("mcp_op_"),
                    "sufficient_entropy": len(submitted_handle) >= 40,
                    "is_not_canonical_task_id": not _is_hex32(submitted_handle),
                }
            receipt["submitted_handle"] = submitted_handle
            if submitted_handle:
                follow = await session.call_tool("get_task_status", {"task_handle": submitted_handle})
                receipt["steps"]["status_submitted_handle"] = {
                    "error": follow.isError,
                    "status": (follow.structuredContent or {}).get("status"),
                }

            unknown = await session.call_tool("inspect_task", {"task_type": "definitely-not-a-task"})
            receipt["steps"]["negative_unknown_task_type"] = {
                "error": unknown.isError,
                "error_class": (unknown.structuredContent or {}).get("error_class"),
            }

            status = await session.call_tool("get_task_status", {"task_handle": handle_a})
            receipt["steps"]["status_own_handle"] = {
                "error": status.isError,
                "status": (status.structuredContent or {}).get("status"),
            }

            results = await session.call_tool("get_task_results", {"task_handle": handle_a})
            receipt["steps"]["results_own_handle"] = {
                "error": results.isError,
                "artifacts": len((results.structuredContent or {}).get("artifacts", [])),
            }

            artifact = await session.call_tool(
                "retrieve_artifact", {"task_handle": handle_a, "artifact_path": "output.txt"}
            )
            content = (artifact.structuredContent or {}).get("content_base64")
            receipt["steps"]["retrieve_artifact"] = {
                "error": artifact.isError,
                "inline": (artifact.structuredContent or {}).get("inline"),
                "bytes_ok": content is not None and base64.b64decode(content) == b"acceptance-artifact\n",
            }

            traversal = await session.call_tool(
                "retrieve_artifact", {"task_handle": handle_a, "artifact_path": "../../etc/passwd"}
            )
            receipt["steps"]["negative_traversal"] = {
                "error": traversal.isError,
                "error_class": (traversal.structuredContent or {}).get("error_class"),
            }

            cross = await session.call_tool("get_task_status", {"task_handle": handle_b})
            receipt["steps"]["negative_cross_user_handle"] = {
                "error": cross.isError,
                "error_class": (cross.structuredContent or {}).get("error_class"),
            }

            oversized = await session.call_tool(
                "retrieve_artifact", {"task_handle": handle_a, "artifact_path": "missing.txt"}
            )
            receipt["steps"]["negative_missing_artifact"] = {
                "error": oversized.isError,
                "error_class": (oversized.structuredContent or {}).get("error_class"),
            }

            invalid = await session.call_tool(
                "submit_task",
                {
                    "task_type": "definitely-not-a-task",
                    "params": {},
                    "inputs": [
                        {
                            "role": "sequence",
                            "filename": "x.fasta",
                            "content_base64": base64.b64encode(FASTA).decode(),
                        }
                    ],
                },
            )
            receipt["steps"]["negative_unknown_submit"] = {
                "error": invalid.isError,
                "error_class": (invalid.structuredContent or {}).get("error_class"),
            }

            # Invalid parameters: a required-role mismatch on a real TaskType is
            # rejected by the canonical contract validator, not by MCP.
            bad_role = await session.call_tool(
                "submit_task",
                {
                    "task_type": submit_task_type,
                    "params": {"definitely_not_a_parameter": "x"},
                    "inputs": [
                        {
                            "role": "not-a-real-role",
                            "filename": "x.fasta",
                            "content_base64": base64.b64encode(FASTA).decode(),
                        }
                    ],
                },
            )
            receipt["steps"]["negative_invalid_parameters"] = {
                "error": bad_role.isError,
                "error_class": (bad_role.structuredContent or {}).get("error_class"),
            }

            # Idempotent retry: an identical resubmission resolves to the same
            # canonical Task (the handle is fresh, the Task identity is not).
            retry = await session.call_tool(
                "submit_task",
                {
                    "task_type": submit_task_type,
                    "params": {},
                    "inputs": [
                        {
                            "role": submit_role,
                            "filename": "accept.fasta",
                            "content_base64": base64.b64encode(FASTA).decode(),
                        }
                    ],
                },
            )
            retry_handle = (retry.structuredContent or {}).get("task_handle")
            receipt["steps"]["retry_submit"] = {
                "error": retry.isError,
                "fresh_handle": bool(retry_handle) and retry_handle != submitted_handle,
            }

            # Cancellation through the canonical path, on the owned finished
            # handle (a terminal Task is not cancellable: TASK_NOT_CANCELLABLE).
            cancel = await session.call_tool("cancel_task", {"task_handle": handle_a})
            receipt["steps"]["cancel_terminal_task"] = {
                "error": cancel.isError,
                "error_class": (cancel.structuredContent or {}).get("error_class"),
                "status": (cancel.structuredContent or {}).get("status"),
            }

            # Oversized artifact: metadata only, no inline content, no canonical
            # Task id leaked anywhere in the answer.
            oversized_artifact = await session.call_tool(
                "retrieve_artifact", {"task_handle": handle_big, "artifact_path": "big.txt"}
            )
            big_payload = oversized_artifact.structuredContent or {}
            receipt["steps"]["negative_oversized_artifact"] = {
                "error": oversized_artifact.isError,
                "inline": big_payload.get("inline"),
                "content_base64": big_payload.get("content_base64"),
                "leaks_task_id": big_task_id in json.dumps(big_payload),
            }

            # Publication boundary: a finished Task whose manifest Core never
            # anchored is a quarantined result, so neither the result manifest nor
            # a cached archive's bytes may be served -- and the answer names the
            # canonical publication state rather than a bare not-ready.
            quarantined_status = await session.call_tool(
                "get_task_status", {"task_handle": quarantined_handle}
            )
            receipt["steps"]["negative_quarantined_status"] = {
                "error": quarantined_status.isError,
                "results_available": (quarantined_status.structuredContent or {}).get("results_available"),
            }
            quarantined_artifact = await session.call_tool(
                "retrieve_artifact", {"task_handle": quarantined_handle, "artifact_path": "output.txt"}
            )
            quarantined_payload = quarantined_artifact.structuredContent or {}
            receipt["steps"]["negative_quarantined_artifact"] = {
                "error": quarantined_artifact.isError,
                "error_class": quarantined_payload.get("error_class"),
                "detail": quarantined_payload.get("detail"),
                "content_base64": quarantined_payload.get("content_base64"),
            }

    async with _session(token_b) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            stolen = await session.call_tool("get_task_status", {"task_handle": handle_a})
            receipt["steps"]["negative_stolen_handle"] = {
                "error": stolen.isError,
                "error_class": (stolen.structuredContent or {}).get("error_class"),
            }
            # Re-authorization parity: the other user cannot resolve the handle
            # the first user just created through submit_task either.
            if receipt.get("submitted_handle"):
                reused = await session.call_tool(
                    "get_task_status", {"task_handle": receipt["submitted_handle"]}
                )
                receipt["steps"]["negative_reused_handle_other_user"] = {
                    "error": reused.isError,
                    "error_class": (reused.structuredContent or {}).get("error_class"),
                }

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            anonymous = await session.call_tool("discover_tools", {})
            receipt["steps"]["negative_anonymous"] = {
                "error": anonymous.isError,
                "error_class": (anonymous.structuredContent or {}).get("error_class"),
            }

    # An invalid credential is rejected by the canonical account rules, not by a
    # weaker MCP-local check.
    async with streamablehttp_client(url, headers={"Authorization": "Bearer not-a-real-token"}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            forged_bearer = await session.call_tool("discover_tools", {})
            receipt["steps"]["negative_invalid_bearer"] = {
                "error": forged_bearer.isError,
                "error_class": (forged_bearer.structuredContent or {}).get("error_class"),
            }

    async with streamablehttp_client(url, headers={"X-API-Key": "not-a-real-key"}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            forged_key = await session.call_tool("discover_tools", {})
            receipt["steps"]["negative_invalid_api_key"] = {
                "error": forged_key.isError,
                "error_class": (forged_key.structuredContent or {}).get("error_class"),
            }

    return receipt


def _is_hex32(value: str) -> bool:
    return len(value) == 32 and all(character in "0123456789abcdefABCDEF" for character in value)


def _submission_target(module) -> tuple[str, str]:
    """Pick an enabled CPU single-sequence TaskType, or fail the acceptance."""
    from revocompute.task_types import list_types

    for task_type in list_types():
        if task_type.gpus or task_type.workflow or len(task_type.inputs) != 1:
            continue
        role = task_type.inputs[0]
        if role.minimum <= 1 <= role.maximum and "fasta" in role.formats:
            return task_type.name, role.name
    raise AssertionError("no CPU single-sequence task type available for the acceptance")


def _second_user(module) -> tuple[str, int]:
    from revocompute.auth import generate_token

    db = module.app.config["user_db"]
    user = db.get_user_by_username("mcp-acceptance-other")
    if user is None:
        user = db.create_user(
            username="mcp-acceptance-other",
            email="mcp-acceptance-other@acceptance.local",
            password="acceptance-password",
            registration_status="approved",
            user_status="active",
        )
        db.verify_email(user["id"])
    return generate_token(user["id"]), int(user["id"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8181)
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="mcp-acceptance-") as tmp:
        root = Path(tmp)
        _isolated_env(root)
        os.environ["MCP_ENABLED"] = "true"
        os.environ["MCP_PORT"] = str(args.port)
        os.environ["MCP_LOG_LEVEL"] = "warning"

        # Importing the canonical application is the deployed web entrypoint:
        # it starts the MCP companion listener in this same process, so the
        # acceptance exercises the deployed shape (one process, one limiter, one
        # application).
        import revocompute.app as module

        deadline = time.monotonic() + 30
        import socket

        while time.monotonic() < deadline:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", args.port)) == 0:
                    break
            time.sleep(0.5)
        else:
            print("MCP listener did not start", file=sys.stderr)
            return 1

        submit_type, submit_role = _submission_target(module)
        # The canonical web process cannot execute Slurm work, and this
        # acceptance runs without a broker or worker.  Stub only the Celery
        # dispatch step so the *submission* path (security, contract,
        # entitlement, readiness, resource, idempotency, persistence,
        # handle minting) is exercised end to end; no scientific execution is
        # claimed.
        class _Queued:
            id = "mcp-acceptance-queued"

        module.task_runtime.run_compute_task.apply_async = lambda *_args, **_kwargs: _Queued()
        task_id, token = _seed_finished_task(module)
        from revocompute.mcp.bounds import MAX_INLINE_ARTIFACT_BYTES

        big_task_id, _big_token = _seed_finished_task(
            module,
            artifact_name="big.txt",
            payload=b"z" * (MAX_INLINE_ARTIFACT_BYTES + 1024),
        )
        quarantined_task_id, _quarantined_token = _seed_finished_task(
            module, artifact_name="quarantined.txt", anchor=False
        )
        db = module.app.config["user_db"]
        user = db.get_user_by_username("mcp-acceptance")
        handle = _mint_handle(module, int(user["id"]), task_id)
        big_handle = _mint_handle(module, int(user["id"]), big_task_id)
        quarantined_handle = _mint_handle(module, int(user["id"]), quarantined_task_id)
        other_token, other_id = _second_user(module)
        foreign_handle = _mint_handle(module, other_id, task_id)

        import anyio

        url = f"http://127.0.0.1:{args.port}/k/mcp"
        receipt = anyio.run(
            _workflow,
            url,
            token,
            other_token,
            handle,
            foreign_handle,
            big_handle,
            big_task_id,
            quarantined_handle,
            submit_type,
            submit_role,
        )
        receipt["transport"] = "streamable-http"
        receipt["endpoint"] = url
        receipt["client"] = "official mcp python SDK"
        receipt["exact_head"] = os.environ.get("GITHUB_SHA") or _git_head()
        failures = _assert_receipt(receipt)
        receipt["failures"] = failures

    print(json.dumps(receipt, indent=2, sort_keys=True))
    if failures:
        print(f"MCP acceptance FAILED: {len(failures)} unmet expectation(s)", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    return 0


def _expect(receipt: dict, failures: list[str], step: str, field: str, expected: object) -> None:
    actual = (receipt.get("steps", {}).get(step) or {}).get(field)
    if actual != expected:
        failures.append(f"{step}.{field}: expected {expected!r}, got {actual!r}")


def _assert_receipt(receipt: dict) -> list[str]:
    """Assert the acceptance's own expectations so it can fail non-zero.

    The receipt is still printed verbatim on every run; these checks make the
    run *scoring*, not merely illustrative, so a regression turns the exit code
    red instead of asking a human to eyeball JSON.
    """
    failures: list[str] = []
    if receipt.get("protocol_version") != "2025-11-25":
        failures.append(f"protocol_version: expected 2025-11-25, got {receipt.get('protocol_version')!r}")
    if len(receipt.get("tools") or []) != 14:
        failures.append(f"tools: expected 14, got {len(receipt.get('tools') or [])}")

    _expect(receipt, failures, "discover_tasks", "error", False)
    _expect(receipt, failures, "inspect_task", "error", False)
    _expect(receipt, failures, "inspect_task", "has_schema", True)

    guarantees = receipt.get("handle_guarantees") or {}
    for key in ("opaque_prefix", "sufficient_entropy", "is_not_canonical_task_id"):
        if guarantees.get(key) is not True:
            failures.append(f"handle_guarantees.{key}: expected True, got {guarantees.get(key)!r}")

    # Workflow positives.
    _expect(receipt, failures, "status_own_handle", "error", False)
    _expect(receipt, failures, "status_own_handle", "status", "finished")
    _expect(receipt, failures, "results_own_handle", "error", False)
    _expect(receipt, failures, "retrieve_artifact", "error", False)
    _expect(receipt, failures, "retrieve_artifact", "inline", True)
    _expect(receipt, failures, "retrieve_artifact", "bytes_ok", True)
    _expect(receipt, failures, "retry_submit", "error", False)
    _expect(receipt, failures, "retry_submit", "fresh_handle", True)

    # Negatives, each with its canonical error class.
    for step, error_class in (
        ("negative_unknown_task_type", "TASK_NOT_FOUND"),
        ("negative_unknown_submit", "TASK_NOT_FOUND"),
        ("negative_invalid_parameters", "INVALID_PARAMETERS"),
        ("negative_traversal", "ARTIFACT_NOT_FOUND"),
        ("negative_missing_artifact", "ARTIFACT_NOT_FOUND"),
        ("negative_cross_user_handle", "TASK_NOT_FOUND"),
        ("negative_stolen_handle", "TASK_NOT_FOUND"),
        ("negative_reused_handle_other_user", "TASK_NOT_FOUND"),
        ("negative_anonymous", "AUTH_REQUIRED"),
        ("negative_invalid_bearer", "AUTH_REQUIRED"),
        ("negative_invalid_api_key", "AUTH_REQUIRED"),
        ("cancel_terminal_task", "TASK_NOT_CANCELLABLE"),
    ):
        _expect(receipt, failures, step, "error", True)
        _expect(receipt, failures, step, "error_class", error_class)

    oversized = receipt.get("steps", {}).get("negative_oversized_artifact") or {}
    if oversized.get("error") is not False:
        failures.append("negative_oversized_artifact.error: expected False")
    if oversized.get("inline") is not False:
        failures.append("negative_oversized_artifact.inline: expected False")
    if oversized.get("content_base64") is not None:
        failures.append("negative_oversized_artifact.content_base64: expected None")
    if oversized.get("leaks_task_id") is not False:
        failures.append("negative_oversized_artifact.leaks_task_id: expected False (canonical id must not leak)")

    # Publication boundary: a quarantined result is unavailable-with-reason and
    # never served, from either the status projection or an artifact read.
    quarantined_status = receipt.get("steps", {}).get("negative_quarantined_status") or {}
    if quarantined_status.get("error") is not False:
        failures.append("negative_quarantined_status.error: expected False")
    if quarantined_status.get("results_available") is not False:
        failures.append("negative_quarantined_status.results_available: expected False (quarantine is not available)")
    quarantined = receipt.get("steps", {}).get("negative_quarantined_artifact") or {}
    if quarantined.get("error") is not True:
        failures.append("negative_quarantined_artifact.error: expected True (a quarantined result must be refused)")
    if quarantined.get("content_base64") is not None:
        failures.append("negative_quarantined_artifact.content_base64: expected None (no bytes from a quarantine)")
    if quarantined.get("error_class") != "RESULT_NOT_READY":
        failures.append(
            "negative_quarantined_artifact.error_class: expected RESULT_NOT_READY, "
            f"got {quarantined.get('error_class')!r}"
        )
    if not quarantined.get("detail"):
        failures.append("negative_quarantined_artifact.detail: expected the canonical publication state")
    return failures


def _git_head() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
