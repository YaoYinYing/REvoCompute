# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Reproducible third-party-host receipts for the REvoCompute MCP surface.

``tests/mcp_live_acceptance.py`` proves the workflow with the official MCP
Python SDK.  This script produces the receipts for the two *other* hosts the PR
claims -- the official MCP Inspector CLI and Claude Code -- so those claims are
reproducible from the tree rather than asserted from an interactive session.

It reuses the acceptance bootstrap, starts the real web process with the MCP
companion listener, drives each available host against the endpoint, and writes
one JSON receipt per host.  A host that is not installed is recorded as
unavailable and does not fail the run.

Usage::

    python tests/mcp_host_receipt.py [--port 8282] [--receipt-dir tests/]
"""

from __future__ import annotations

import argparse
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

from tests.mcp_live_acceptance import _isolated_env, _seed_finished_task


def _wait_for_port(port: int, deadline_seconds: float = 30.0) -> bool:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def _run(cmd: list[str], *, timeout: int = 180) -> dict:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "error": str(exc)}
    return {"available": True, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def _json_from_stdout(result: dict) -> object:
    """Parse the first JSON document in a host's output (pretty-printed or one-line)."""
    if not result.get("available"):
        return None
    for stream in ("stdout", "stderr"):
        text = result.get(stream) or ""
        decoder = json.JSONDecoder()
        for index, character in enumerate(text):
            if character not in "{[":
                continue
            try:
                value, _end = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            return value
    return None


def _inspector_receipt(url: str, token: str) -> dict:
    """Drive the official MCP Inspector CLI and capture its answers."""
    npx = shutil.which("npx")
    if npx is None:
        return {"host": "mcp-inspector-cli", "available": False, "reason": "npx not installed"}
    base = [npx, "-y", "@modelcontextprotocol/inspector", "--cli", "--server-url", url, "--transport", "http"]
    header = ["--header", f"Authorization: Bearer {token}"]
    receipt: dict = {"host": "mcp-inspector-cli", "available": True, "server_url": url, "methods": {}}
    for method in ("resources/list", "tools/list"):
        result = _run([*base, *header, "--method", method])
        receipt["methods"][method] = _inspector_summary(method, result)
    call = _run([*base, *header, "--method", "tools/call", "--tool-name", "discover_tasks"])
    receipt["methods"]["tools/call:discover_tasks"] = {
        "returncode": call.get("returncode"),
        "catalog_count": _catalog_count(_json_from_stdout(call)),
    }
    return receipt


def _inspector_summary(method: str, result: dict) -> dict:
    parsed = _json_from_stdout(result)
    summary: dict = {"returncode": result.get("returncode")}
    if not isinstance(parsed, dict):
        summary["raw_tail"] = ((result.get("stdout") or "") + (result.get("stderr") or ""))[-400:]
        return summary
    if method == "resources/list":
        summary["uris"] = sorted(item.get("uri") for item in parsed.get("resources", []) if isinstance(item, dict))
    elif method == "tools/list":
        names = sorted(item.get("name") for item in parsed.get("tools", []) if isinstance(item, dict))
        summary["tool_count"] = len(names)
        summary["tools"] = names
    return summary


def _catalog_count(parsed: object) -> int | None:
    try:
        content = parsed["content"]
        text = content[0]["text"] if isinstance(content, list) else content
        payload = json.loads(text) if isinstance(text, str) else text
        return len(payload.get("task_types", []))
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _claude_receipt(url: str, token: str, tmp_root: Path) -> dict:
    """Drive the primary host (Claude Code) through a real ``--mcp-config``."""
    claude = shutil.which("claude")
    if claude is None:
        return {"host": "claude-code", "available": False, "reason": "claude CLI not installed"}
    config_path = tmp_root / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "revocompute": {
                        "type": "http",
                        "url": url,
                        "headers": {"Authorization": f"Bearer {token}"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    prompt = (
        "Use the revocompute MCP tools. Call discover_tasks and reply with exactly: "
        "COUNT=<number of task types>"
    )
    result = _run(
        [claude, "-p", prompt, "--mcp-config", str(config_path), "--allowedTools", "mcp__revocompute__discover_tasks"],
        timeout=300,
    )
    answer = (result.get("stdout") or "").strip()
    return {
        "host": "claude-code",
        "available": True,
        # ``exercised`` is False when the host ran but produced no agent answer
        # (for example the CLI is a harness that routes to an unrecognized
        # model).  The receipt records the raw outcome rather than implying a
        # successful tool call.
        "exercised": bool(answer),
        "server_url": url,
        "prompt": prompt,
        "returncode": result.get("returncode"),
        "answer": answer,
        "stderr_tail": (result.get("stderr") or "")[-500:],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8282)
    parser.add_argument("--receipt-dir", default=str(REPO_ROOT / "tests"))
    args = parser.parse_args(argv)

    receipts: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="mcp-host-receipts-") as tmp:
        root = Path(tmp)
        _isolated_env(root)
        os.environ["MCP_ENABLED"] = "true"
        os.environ["MCP_PORT"] = str(args.port)
        os.environ["MCP_LOG_LEVEL"] = "warning"

        import revocompute.app as module

        if not _wait_for_port(args.port):
            print("MCP listener did not start", file=sys.stderr)
            return 1

        class _Queued:
            id = "mcp-host-receipt-queued"

        module.task_runtime.run_compute_task.apply_async = lambda *_a, **_k: _Queued()
        _task_id, token = _seed_finished_task(module)

        url = f"http://127.0.0.1:{args.port}/k/mcp"
        receipts["mcp-inspector-cli"] = _inspector_receipt(url, token)
        receipts["claude-code"] = _claude_receipt(url, token, root)

    out_dir = Path(args.receipt_dir)
    for name, receipt in receipts.items():
        target = out_dir / f"{name.replace('-', '_')}_receipt.json"
        target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
