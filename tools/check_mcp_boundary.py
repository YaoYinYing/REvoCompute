#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Reject an MCP adapter module that reaches past the canonical Core boundary.

The MCP layer is a protocol projection of the canonical application; it may
depend on canonical application/service/domain contracts but must never import
Runner implementations, the job executor, the container runtime, the deployment
controller, operator maintenance, or raw process execution.  A module that does
has started to become a shortcut around Core, which is exactly the drift this
gate exists to stop.

The gate parses the real import graph, so a comment or a docstring that merely
mentions a forbidden path does not trip it.  Run it from the repository root::

    python tools/check_mcp_boundary.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_PACKAGE = REPO_ROOT / "revocompute" / "mcp"

FORBIDDEN_PREFIXES = (
    "docker.runners",
    "docker.tools",
    "revocompute.job.runners",
    "revocompute.live_test_executor",
    "revocompute.live_tests",
    "revocompute.tool_runtime",
    "revocompute.tool_runtime_manager",
    "revocompute_ctl",
    "revocompute.maintenance",
    "subprocess",
)

#: Modules whose import would give the adapter a filesystem/network escape.
FORBIDDEN_ESCAPES = frozenset({"requests", "urllib.request", "http.client", "socket"})


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module if node.level == 0 else "." * node.level + node.module)
        elif isinstance(node, ast.Call):
            # A dynamic ``importlib.import_module("<literal>")`` is a real
            # dependency the static walk would miss, so resolve literal targets.
            target = _dynamic_import_target(node)
            if target:
                found.add(target)
    return found


def _dynamic_import_target(node: ast.Call) -> str | None:
    func = node.func
    is_import_module = (
        (isinstance(func, ast.Attribute) and func.attr == "import_module")
        or (isinstance(func, ast.Name) and func.id == "import_module")
    )
    if not is_import_module or not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def main() -> int:
    if not MCP_PACKAGE.is_dir():
        print(f"MCP adapter package is missing: {MCP_PACKAGE}", file=sys.stderr)
        return 1
    violations: list[str] = []
    for path in sorted(MCP_PACKAGE.glob("*.py")):
        for module in imported_modules(path):
            normalized = module.lstrip(".")
            if normalized in FORBIDDEN_ESCAPES:
                violations.append(f"{path.name}: escape module {module}")
            for forbidden in FORBIDDEN_PREFIXES:
                if normalized == forbidden or normalized.startswith(forbidden + "."):
                    violations.append(f"{path.name}: forbidden import {module}")
    if violations:
        print("MCP adapter crossed the Core boundary:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    print("MCP adapter boundary is clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
