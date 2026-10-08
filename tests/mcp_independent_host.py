# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Independent-host interoperability acceptance for the REvoCompute MCP surface.

``tests/mcp_live_acceptance.py`` drives the surface with the *official* MCP
Python SDK -- the same distribution family the adapter itself is built on, so it
is not an independent implementation.  This script closes that gap with a
genuinely independent host: ``fastmcp`` (jlowin/fastmcp), a separate project and
codebase that speaks the MCP wire protocol with its own client, its own
transport stack, and its own protocol library (``mcp`` 2.x, a different major
line from the adapter's pinned ``mcp`` 1.x).

The two halves run in *different* Python processes on purpose, and with
different dependency sets:

* the **server** half runs in this repository's environment and starts the
  canonical web process with the MCP companion listener, exactly as
  ``mcp_live_acceptance`` does;
* the **client** half is spawned through an isolated ``uv`` environment that
  installs only ``fastmcp``, so the host under test cannot accidentally import
  the adapter's own SDK (or the adapter) and cannot share its process state.

It performs the complete workflow -- connect, discover, inspect, preflight,
submit, track, result, artifact -- plus the negative cases, and writes a JSON
receipt.  It **asserts** its expectations and exits non-zero on any mismatch.

Usage::

    uv run --extra test --extra mcp python tests/mcp_independent_host.py
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FASTA = b">independent\nACDEFGHIKLMNPQRSTVWY\n"

#: The two independent hosts, each pinned.  Neither is a dependency of
#: REvoCompute; each is installed only inside the ephemeral environment its
#: client half runs in.
#:
#: * ``fastmcp`` (jlowin/fastmcp) is a different project and codebase from the
#:   ``mcp`` Python SDK the adapter is built on, and it carries its own protocol
#:   library on the ``mcp`` 2.x line.
#: * ``@modelcontextprotocol/sdk`` is the official MCP *TypeScript* SDK: a
#:   different language, implementation, and transport stack.
HOSTS = {
    "fastmcp": {
        "spec": "fastmcp==4.0.11",
        "runner": "python",
        "display": "fastmcp",
        # The host's own protocol library, recorded so the receipt proves it is
        # not the adapter's `mcp` 1.x line.
        "protocol_library": "mcp",
        "receipt": "mcp_independent_host_receipt.json",
    },
    "typescript": {
        "spec": "@modelcontextprotocol/sdk@1.32.1",
        "runner": "node",
        "display": "mcp-typescript-sdk",
        "protocol_library": "@modelcontextprotocol/sdk",
        "receipt": "mcp_typescript_host_receipt.json",
    },
}


# ---------------------------------------------------------------------------
# Client half -- runs in the isolated environment, imports only fastmcp
# ---------------------------------------------------------------------------


async def _run_client(url: str, token: str, handle: str, fixtures: dict) -> dict:  # pragma: no cover - subprocess
    import importlib.metadata as metadata

    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    receipt: dict = {
        "host": "fastmcp",
        "host_version": metadata.version("fastmcp"),
        "host_protocol_library": f"mcp {metadata.version('mcp')}",
        "endpoint": url,
        "steps": {},
    }

    def _structured(result) -> dict:
        payload = getattr(result, "structured_content", None)
        if isinstance(payload, dict):
            return payload
        # Older/unstructured answers carry their JSON as text content.
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", None)
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return {}

    def _error(payload: dict) -> str | None:
        return payload.get("error_class")

    async def call(client, name: str, arguments: dict) -> tuple[bool, dict]:
        """Call one tool and normalize the host's answer to (is_error, payload).

        A conformant MCP host may surface a tool-declared failure either as an
        ``isError`` result or as the client's own raised error (fastmcp raises
        ``ToolError`` carrying the structured payload); both are the same
        protocol fact, so they normalize to one shape here rather than making
        the assertions depend on a client's error style.
        """
        import fastmcp.exceptions

        try:
            result = await client.call_tool(name, arguments)
        except fastmcp.exceptions.ToolError as exc:
            message = str(exc)
            try:
                payload = json.loads(message)
            except ValueError:
                payload = {"message": message}
            return True, payload if isinstance(payload, dict) else {"message": message}
        return bool(result.is_error), _structured(result)

    transport = StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"})
    async with Client(transport) as client:
        init = client.initialize_result
        receipt["protocol_version"] = init.protocolVersion
        receipt["server"] = {"name": init.serverInfo.name, "version": init.serverInfo.version}

        tools = await client.list_tools()
        receipt["tools"] = sorted(tool.name for tool in tools)
        receipt["steps"]["list_tools"] = {"error": False, "count": len(tools)}

        resources = await client.list_resources()
        receipt["steps"]["list_resources"] = {
            "error": False,
            "uris": sorted(str(item.uri) for item in resources),
        }

        discovered_error, discovered_payload = await call(client, "discover_tasks", {})
        catalog = discovered_payload.get("task_types", [])
        receipt["steps"]["discover_tasks"] = {
            "error": discovered_error,
            "count": len(catalog),
            "sample": catalog[0]["task_type"] if catalog else None,
        }

        target = catalog[0]["task_type"] if catalog else None
        if target:
            inspected_error, inspected_payload = await call(client, "inspect_task", {"task_type": target})
            receipt["steps"]["inspect_task"] = {
                "error": inspected_error,
                "task_type": inspected_payload.get("task_type"),
                "has_schema": bool(inspected_payload.get("parameter_schema")),
            }

        task_type = fixtures["submit_task_type"]
        role = fixtures["submit_role"]
        submission_inputs = [
            {"role": role, "filename": "independent.fasta", "content_base64": base64.b64encode(FASTA).decode()}
        ]
        preflight_error, preflight_payload = await call(
            client, "preflight_task", {"task_type": task_type, "params": {}, "inputs": submission_inputs}
        )
        receipt["steps"]["preflight_task"] = {
            "error": preflight_error,
            "valid": preflight_payload.get("valid"),
            "error_class": _error(preflight_payload),
        }

        submitted_error, submitted_payload = await call(
            client, "submit_task", {"task_type": task_type, "params": {}, "inputs": submission_inputs}
        )
        fresh_handle = submitted_payload.get("task_handle")
        receipt["steps"]["submit_task"] = {
            "error": submitted_error,
            "error_class": _error(submitted_payload),
            "handle_returned": bool(fresh_handle),
            "handle_is_not_task_id": bool(fresh_handle) and not _is_hex32(str(fresh_handle)),
        }

        status_error, status_payload = await call(client, "get_task_status", {"task_handle": handle})
        receipt["steps"]["status_own_handle"] = {"error": status_error, "status": status_payload.get("status")}

        results_error, results_payload = await call(client, "get_task_results", {"task_handle": handle})
        receipt["steps"]["results_own_handle"] = {
            "error": results_error,
            "artifacts": len(results_payload.get("artifacts", [])),
        }

        artifact_error, artifact_payload = await call(
            client, "retrieve_artifact", {"task_handle": handle, "artifact_path": "output.txt"}
        )
        content = artifact_payload.get("content_base64")
        receipt["steps"]["retrieve_artifact"] = {
            "error": artifact_error,
            "inline": artifact_payload.get("inline"),
            "bytes_ok": content is not None and base64.b64decode(content) == b"independent-artifact\n",
        }

        traversal_error, traversal_payload = await call(
            client, "retrieve_artifact", {"task_handle": handle, "artifact_path": "../../etc/passwd"}
        )
        receipt["steps"]["negative_traversal"] = {
            "error": traversal_error,
            "error_class": _error(traversal_payload),
        }

        missing_error, missing_payload = await call(
            client, "retrieve_artifact", {"task_handle": handle, "artifact_path": "missing.txt"}
        )
        receipt["steps"]["negative_missing_artifact"] = {
            "error": missing_error,
            "error_class": _error(missing_payload),
        }

        quarantined_error, quarantined_payload = await call(
            client,
            "retrieve_artifact",
            {"task_handle": fixtures["quarantine_handle"], "artifact_path": "quarantined.txt"},
        )
        receipt["steps"]["negative_quarantined_artifact"] = {
            "error": quarantined_error,
            "error_class": _error(quarantined_payload),
            "detail": quarantined_payload.get("detail"),
            "content_base64": quarantined_payload.get("content_base64"),
        }

        cross_error, cross_payload = await call(
            client, "get_task_status", {"task_handle": fixtures["foreign_handle"]}
        )
        receipt["steps"]["negative_cross_user_handle"] = {
            "error": cross_error,
            "error_class": _error(cross_payload),
        }

        unknown_error, unknown_payload = await call(
            client,
            "submit_task",
            {
                "task_type": "definitely-not-a-task",
                "params": {},
                "inputs": [{"role": role, "filename": "x.fasta", "content_base64": base64.b64encode(FASTA).decode()}],
            },
        )
        receipt["steps"]["negative_unknown_submit"] = {
            "error": unknown_error,
            "error_class": _error(unknown_payload),
        }

        invalid_error, invalid_payload = await call(
            client,
            "submit_task",
            {
                "task_type": task_type,
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
            "error": invalid_error,
            "error_class": _error(invalid_payload),
        }

        retry_error, retry_payload = await call(
            client, "submit_task", {"task_type": task_type, "params": {}, "inputs": submission_inputs}
        )
        retry_handle = retry_payload.get("task_handle")
        receipt["steps"]["retry_submit"] = {
            "error": retry_error,
            "fresh_handle": bool(retry_handle) and retry_handle != fresh_handle,
        }

        cancel_error, cancel_payload = await call(client, "cancel_task", {"task_handle": handle})
        receipt["steps"]["cancel_terminal_task"] = {
            "error": cancel_error,
            "error_class": _error(cancel_payload),
        }

        oversized_error, oversized_payload = await call(
            client, "retrieve_artifact", {"task_handle": fixtures["big_handle"], "artifact_path": "big.txt"}
        )
        receipt["steps"]["negative_oversized_artifact"] = {
            "error": oversized_error,
            "inline": oversized_payload.get("inline"),
            "content_base64": oversized_payload.get("content_base64"),
            "leaks_task_id": fixtures["big_task_id"] in json.dumps(oversized_payload),
        }

    # A second credential: the first user's handle must not resolve for them.
    other_transport = StreamableHttpTransport(url, headers={"Authorization": f"Bearer {fixtures['other_token']}"})
    async with Client(other_transport) as client:
        stolen_error, stolen_payload = await call(client, "get_task_status", {"task_handle": handle})
        receipt["steps"]["negative_stolen_handle"] = {
            "error": stolen_error,
            "error_class": _error(stolen_payload),
        }

    # Anonymous and forged-credential requests are refused by the canonical rules.
    anonymous_transport = StreamableHttpTransport(url)
    async with Client(anonymous_transport) as client:
        anonymous_error, anonymous_payload = await call(client, "discover_tools", {})
        receipt["steps"]["negative_anonymous"] = {
            "error": anonymous_error,
            "error_class": _error(anonymous_payload),
        }

    forged_transport = StreamableHttpTransport(url, headers={"Authorization": "Bearer not-a-real-token"})
    async with Client(forged_transport) as client:
        forged_error, forged_payload = await call(client, "discover_tools", {})
        receipt["steps"]["negative_invalid_bearer"] = {
            "error": forged_error,
            "error_class": _error(forged_payload),
        }

    return receipt


def _is_hex32(value: str) -> bool:
    return len(value) == 32 and all(character in "0123456789abcdefABCDEF" for character in value)


def _client_main(argv: list[str]) -> int:  # pragma: no cover - subprocess
    import anyio

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--server-fixtures", required=True)
    args = parser.parse_args(argv)
    fixtures = json.loads(Path(args.server_fixtures).read_text(encoding="utf-8"))
    receipt = anyio.run(lambda: _run_client(args.url, fixtures["token"], fixtures["handle"], fixtures))
    # The revision is recorded by the client half, which runs in its own
    # environment: the receipt then names the head that actually served it.
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        receipt["exact_head"] = completed.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        receipt["exact_head"] = "unknown"
    print(json.dumps(receipt, sort_keys=True))
    return 0


# ---------------------------------------------------------------------------
# Server half -- the canonical process with the MCP companion listener
# ---------------------------------------------------------------------------


def _wait_for_port(port: int, deadline_seconds: float = 45.0) -> bool:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def _start_server(url_port: int, fixtures_path: Path) -> None:  # pragma: no cover - subprocess
    from tests.mcp_live_acceptance import _isolated_env, _mint_handle, _second_user, _submission_target

    root = fixtures_path.parent
    _isolated_env(root)
    os.environ["MCP_ENABLED"] = "true"
    os.environ["MCP_PORT"] = str(url_port)
    os.environ["MCP_LOG_LEVEL"] = "warning"

    import revocompute.app as module

    if not _wait_for_port(url_port):
        print("MCP listener did not start", file=sys.stderr)
        raise SystemExit(1)

    class _Queued:
        id = "independent-host-acceptance"

    module.task_runtime.run_compute_task.apply_async = lambda *_a, **_k: _Queued()

    submit_type, submit_role = _submission_target(module)
    big_payload = b"z" * (200 * 1024)
    task_id, token = _seed(module, "independent-artifact\n")
    big_task_id, _ = _seed(module, big_payload, artifact_name="big.txt")
    quarantine_task_id, _ = _seed(module, "quarantined\n", artifact_name="quarantined.txt", anchor=False)

    db = module.app.config["user_db"]
    user = db.get_user_by_username("mcp-acceptance")
    other_token, other_id = _second_user(module)
    fixtures = {
        "token": token,
        "other_token": other_token,
        "handle": _mint_handle(module, int(user["id"]), task_id),
        "big_handle": _mint_handle(module, int(user["id"]), big_task_id),
        "big_task_id": big_task_id,
        "quarantine_handle": _mint_handle(module, int(user["id"]), quarantine_task_id),
        "foreign_handle": _mint_handle(module, other_id, task_id),
        "submit_task_type": submit_type,
        "submit_role": submit_role,
    }
    fixtures_path.write_text(json.dumps(fixtures), encoding="utf-8")
    (fixtures_path.parent / "ready").write_text("ok", encoding="utf-8")
    print("SERVER READY", flush=True)
    while True:
        time.sleep(3600)


def _seed(module, payload: str, *, artifact_name: str = "output.txt", anchor: bool = True) -> tuple[str, str]:
    """Seed a finished Task publishing one artifact (optionally un-anchored)."""
    from revocompute.auth import generate_token

    username = "mcp-acceptance"
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
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    (root / artifact_name).write_bytes(data)
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
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "media_type": "text/plain",
                "preview": "text",
                "capability": "text",
                "role": "artifact",
            }
        ],
        "views": [],
        "result": {"files": {}},
        "storyboard": None,
        "total_size": len(data),
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
        user_agent=username,
        username=username,
        task_type="gremlin",
        submitted_by_user_id=int(user["id"]),
        storage_key=user["storage_key"],
    )
    if anchor:
        raw = (root / "manifest.json").read_bytes()
        module.task_store.record_result_publication(
            task_id,
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
            manifest_size=len(raw),
            published_at=time.time(),
        )
    return task_id, generate_token(user["id"])


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _assert_receipt(receipt: dict) -> list[str]:
    """Assert one independent host's receipt against the interop contract.

    The host's independence is part of the claim, so it is asserted, not merely
    noted: the driver records the host's own dependency, and this refuses a
    receipt whose protocol library is the ``mcp`` 1.x line the adapter is built
    on -- a host sharing the adapter's SDK would not be an independent host.
    """
    failures: list[str] = []
    protocol_library = str(receipt.get("host_protocol_library") or "")
    if not protocol_library or "mcp 1." in protocol_library or protocol_library == "mcp 1":
        failures.append(
            f"independence: the host's protocol library must be a different implementation, got {protocol_library!r}"
        )
    if not receipt.get("protocol_version"):
        failures.append("protocol_version: the independent host negotiated no protocol version")
    if len(receipt.get("tools") or []) != 14:
        failures.append(f"tools: expected 14, got {len(receipt.get('tools') or [])}")

    steps = receipt.get("steps") or {}
    for name in ("list_tools", "list_resources", "discover_tasks", "inspect_task"):
        if steps.get(name, {}).get("error") is not False:
            failures.append(f"{name}: expected an error-free answer, got {steps.get(name)}")
    if not (steps.get("discover_tasks") or {}).get("count"):
        failures.append("discover_tasks: no catalog returned")
    if (steps.get("inspect_task") or {}).get("has_schema") is not True:
        failures.append("inspect_task: no parameter schema returned")
    if not any(uri.endswith("://skills") for uri in steps.get("list_resources", {}).get("uris", [])):
        failures.append("list_resources: the canonical skills resource was not advertised")

    _expect(receipt, failures, "preflight_task", "error", False)
    _expect(receipt, failures, "submit_task", "error", False)
    _expect(receipt, failures, "submit_task", "handle_is_not_task_id", True)
    _expect(receipt, failures, "status_own_handle", "status", "finished")
    _expect(receipt, failures, "results_own_handle", "error", False)
    _expect(receipt, failures, "retrieve_artifact", "inline", True)
    _expect(receipt, failures, "retrieve_artifact", "bytes_ok", True)
    _expect(receipt, failures, "retry_submit", "fresh_handle", True)

    for step, error_class in (
        ("negative_traversal", "ARTIFACT_NOT_FOUND"),
        ("negative_missing_artifact", "ARTIFACT_NOT_FOUND"),
        ("negative_quarantined_artifact", "RESULT_NOT_READY"),
        ("negative_cross_user_handle", "TASK_NOT_FOUND"),
        ("negative_stolen_handle", "TASK_NOT_FOUND"),
        ("negative_unknown_submit", "TASK_NOT_FOUND"),
        ("negative_invalid_parameters", "INVALID_PARAMETERS"),
        ("cancel_terminal_task", "TASK_NOT_CANCELLABLE"),
        ("negative_anonymous", "AUTH_REQUIRED"),
        ("negative_invalid_bearer", "AUTH_REQUIRED"),
    ):
        _expect(receipt, failures, step, "error", True)
        _expect(receipt, failures, step, "error_class", error_class)

    quarantined = steps.get("negative_quarantined_artifact") or {}
    if quarantined.get("content_base64") is not None:
        failures.append("negative_quarantined_artifact: a quarantined result must return no bytes")
    if not quarantined.get("detail"):
        failures.append("negative_quarantined_artifact: expected the canonical publication state as detail")

    oversized = steps.get("negative_oversized_artifact") or {}
    if oversized.get("inline") is not False or oversized.get("content_base64") is not None:
        failures.append("negative_oversized_artifact: expected metadata only")
    if oversized.get("leaks_task_id") is not False:
        failures.append("negative_oversized_artifact: the canonical Task id leaked")
    return failures


def _expect(receipt: dict, failures: list[str], step: str, field: str, expected: object) -> None:
    actual = ((receipt.get("steps") or {}).get(step) or {}).get(field)
    if actual != expected:
        failures.append(f"{step}.{field}: expected {expected!r}, got {actual!r}")


def _main(argv: list[str]) -> int:
    """Dispatch: ``--serve`` (server half) or ``--client`` (isolated client half)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--client", action="store_true")
    parser.add_argument("--port", type=int, default=8281)
    parser.add_argument("--url")
    parser.add_argument("--server-fixtures")
    parser.add_argument("--receipt")
    parser.add_argument("--host", choices=sorted(HOSTS), default="fastmcp")
    args = parser.parse_args(argv)

    if args.serve:
        _start_server(args.port, Path(args.server_fixtures))
        return 0
    if args.client:
        return _client_main(["--url", args.url, "--server-fixtures", args.server_fixtures])
    return _orchestrate(args)


def _run_host(name: str, url: str, fixtures_path: Path, scratch: Path) -> dict:
    """Run one independent host's client half in its own isolated environment."""
    host = HOSTS[name]
    script = Path(__file__).resolve()
    if host["runner"] == "python":
        command = [
            shutil.which("uv") or "uv",
            "run",
            "--no-project",
            "--python",
            "3.12",
            "--with",
            host["spec"],
            "python",
            str(script),
            "--client",
            "--url",
            url,
            "--server-fixtures",
            str(fixtures_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
        runner = "uv"
    else:  # node
        # Node resolves packages from the script's own directory upward, so the
        # host is installed into a scratch prefix and the driver is run from
        # inside it -- the isolated install is what makes the host independent,
        # and it never touches this repository's tree.
        npm = shutil.which("npm")
        if npm is None:
            raise RuntimeError("npm is required to run the TypeScript host")
        prefix = scratch / "ts-host"
        prefix.mkdir(parents=True, exist_ok=True)
        install = subprocess.run(
            [npm, "install", "--no-audit", "--no-fund", host["spec"]],
            cwd=prefix,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if install.returncode != 0:
            raise RuntimeError(f"TypeScript host install failed\n{install.stdout[-4000:]}\n{install.stderr[-4000:]}")
        driver = prefix / "independent_ts_host.mjs"
        shutil.copyfile(script.parent / "mcp_independent_ts_host.mjs", driver)
        installed = json.loads((prefix / "node_modules" / "@modelcontextprotocol" / "sdk" / "package.json").read_text())
        environment = {**os.environ, "REVOCOMPUTE_TS_HOST_VERSION": str(installed["version"])}
        command = [shutil.which("node") or "node", str(driver), str(fixtures_path), url]
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=600, check=False, env=environment
        )
        runner = "npm"

    if completed.returncode != 0:
        raise RuntimeError(
            f"{name} host failed (exit {completed.returncode})\n{completed.stdout[-4000:]}\n{completed.stderr[-4000:]}"
        )
    receipt = json.loads(completed.stdout.strip().splitlines()[-1])
    receipt["host_key"] = name
    receipt["host_runner"] = runner
    return receipt


def _orchestrate(args: argparse.Namespace) -> int:
    """Start the canonical server once, run every independent host against it."""
    if shutil.which("uv") is None:
        print("uv is required to run the independent hosts", file=sys.stderr)
        return 1
    if "typescript" in HOSTS and shutil.which("npm") is None:
        print("npm is required to run the TypeScript host", file=sys.stderr)
        return 1

    receipts: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="mcp-independent-host-") as tmp:
        root = Path(tmp)
        fixtures_path = root / "fixtures.json"
        server_log = root / "server.log"
        with server_log.open("w", encoding="utf-8") as log_handle:
            server = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--serve",
                    "--port",
                    str(args.port),
                    "--server-fixtures",
                    str(fixtures_path),
                ],
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline and not fixtures_path.exists():
                    if server.poll() is not None:
                        print(server_log.read_text(encoding="utf-8"), file=sys.stderr)
                        return 1
                    time.sleep(0.5)
                if not fixtures_path.exists():
                    print("server fixtures were never written", file=sys.stderr)
                    print(server_log.read_text(encoding="utf-8"), file=sys.stderr)
                    return 1
                url = f"http://127.0.0.1:{args.port}/k/mcp"
                for name in sorted(HOSTS):
                    receipts.append(_run_host(name, url, fixtures_path, root))
            finally:
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()

    receipt_dir = Path(args.receipt).parent
    failures: list[str] = []
    for receipt in receipts:
        host_failures = _assert_receipt(receipt)
        receipt["failures"] = host_failures
        failures.extend(f"{receipt['host']}: {failure}" for failure in host_failures)
        target = receipt_dir / HOSTS[receipt["host_key"]]["receipt"]
        target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2, sort_keys=True))
        print(f"wrote {target}")

    if failures:
        print(f"independent-host acceptance FAILED: {len(failures)} unmet expectation(s)", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
