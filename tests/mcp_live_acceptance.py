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


def _seed_finished_task(module, username: str = "mcp-acceptance") -> tuple[str, str]:
    """Create a finished Task publishing one artifact, and return (task_id, token)."""
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
    task_id = hashlib.sha256(f"{username}:{time.time()}".encode()).hexdigest()[:32]
    resolver = module.app.config["storage_resolver"]
    root = Path(resolver.get_task_root({"md5sum": task_id, **owner}))
    root.mkdir(parents=True, exist_ok=True)
    payload = b"acceptance-artifact\n"
    (root / "output.txt").write_bytes(payload)
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
                "path": "output.txt",
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
    return task_id, generate_token(user["id"])


def _mint_handle(module, user_id: int, task_id: str) -> str:
    from revocompute.mcp.handles import canonical_state

    store = canonical_state().handles
    handle = store.mint(user_id=user_id, kind="task", now=time.time())
    store.bind(handle, task_id, now=time.time())
    return handle


async def _workflow(url: str, token_a: str, token_b: str, handle_a: str, handle_b: str) -> dict:
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

    async with _session(token_b) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            stolen = await session.call_tool("get_task_status", {"task_handle": handle_a})
            receipt["steps"]["negative_stolen_handle"] = {
                "error": stolen.isError,
                "error_class": (stolen.structuredContent or {}).get("error_class"),
            }

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            anonymous = await session.call_tool("discover_tools", {})
            receipt["steps"]["negative_anonymous"] = {
                "error": anonymous.isError,
                "error_class": (anonymous.structuredContent or {}).get("error_class"),
            }

    return receipt


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
    parser.add_argument("--json", action="store_true")
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

        task_id, token = _seed_finished_task(module)
        db = module.app.config["user_db"]
        user = db.get_user_by_username("mcp-acceptance")
        handle = _mint_handle(module, int(user["id"]), task_id)
        other_token, other_id = _second_user(module)
        foreign_handle = _mint_handle(module, other_id, task_id)

        import anyio

        url = f"http://127.0.0.1:{args.port}/k/mcp"
        receipt = anyio.run(_workflow, url, token, other_token, handle, foreign_handle)
        receipt["transport"] = "streamable-http"
        receipt["endpoint"] = url
        receipt["client"] = "official mcp python SDK"
        receipt["exact_head"] = os.environ.get("GITHUB_SHA") or _git_head()

    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


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
