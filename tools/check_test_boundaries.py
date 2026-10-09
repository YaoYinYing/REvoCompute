#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Check executable Server/Core sources for concrete Runner dependencies.

Fleet projections/replays intentionally enumerate shipped assets and live in
``tests/fleet``. Frontend replay support carries authentic captured identities;
CI policy tests exercise concrete path transitions. Those bounded namespaces are
excluded; generic protocol tests are not. Comments/docstrings are not behavior.
Logical data-format dialects and existing legacy HTTP routes have explicit,
value-scoped exceptions below. New unexplained identities fail closed.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_TEST_NAMESPACES = ("tests/fleet/", "tests/frontend_fixtures/")
BOUNDARY_FILES = {
    "tests/test_ci_scope_classifier.py": "CI policy deliberately classifies real fleet paths",
    "tests/test_campaign_merge_candidate.py": "drift policy deliberately compares real fleet paths",
    "tests/full_stack_smoke.py": "target-stack acceptance deliberately exercises installed Runner",
    "tests/mcp_independent_host.py": "independent live acceptance deliberately exercises installed Runner",
    "tests/data/test_data.py": "shared immutable historical scientific corpus helper",
}
# These are protocol vocabularies or legacy route targets, not dispatch branches.
VALUE_EXCEPTIONS = {
    "revocompute/input_validators/profiles.py": {
        "alphafold3", "AlphaFold 3 JSON object must declare the alphafold3 dialect and a positive integer version",
    },
    "revocompute/routes.py": {"/compute/create_task?task_type=gremlin"},
    "tests/server/test_application_frontend_contract.py": {"/compute/create_task?task_type=gremlin"},
    "tests/server/test_preflight_boundary.py": {"alphafold3"},
    # Counterexamples intentionally use the identity that collides with reserved DNS.
    "tests/test_test_boundaries.py": {
        "example", 'family = "example"', 'path = "docker/runners/example/plugin.yaml"',
    },
    # Immutable format-parser corpus is shared input data, not plugin assets.
    "tests/test_input_validation.py": {
        "tests/data/foundry/rf3_monomer.json", "tests/data/foundry/rfd3_unconditional.json",
        "tests/data/chai1/entity_ligand.fasta", "alphafold3",
    },
}
FORBIDDEN_IMPORTS = ("docker.runners", "docker.runner_testkit", "tests.runners", "runner_protocol")


def runner_identities(root: Path) -> set[str]:
    """Use installed manifest vocabulary, including task IDs and directory names."""
    identities: set[str] = set()
    for manifest_path in sorted(root.glob("*/plugin.yaml")):
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        identities.update((manifest["id"], manifest_path.parent.name))
        for task_path in manifest.get("tasks", []):
            task = yaml.safe_load((manifest_path.parent / task_path).read_text(encoding="utf-8"))
            identities.add(task["id"])
    if not identities:
        raise ValueError("production Runner manifest inventory is empty")
    return identities


def inspect_source(source: str, path: str, identities: set[str]) -> list[str]:
    """Bounded AST check: imports and executable string/path/identity literals."""
    tree = ast.parse(source, filename=path)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    violations: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == "import_module") or (
                isinstance(func, ast.Name) and func.id in {"import_module", "__import__"}
            ):
                if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    modules.append(node.args[0].value)
        for module in modules:
            if any(module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN_IMPORTS):
                violations.append(f"{path}:{node.lineno}: Runner implementation/testkit import {module!r}")
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or id(node) in docstrings:
            continue
        if node.value in VALUE_EXCEPTIONS.get(path, set()):
            continue
        # A token boundary catches family paths/URLs/JSON values while avoiding
        # accidental substring matches (e.g. 'prime' inside 'primary').
        value = re.sub(r"\bexample\.(?:invalid|test|com|org|net)\b|\b[A-Za-z0-9-]+\.example\b", "documentation_domain", node.value)
        tokens = set(re.findall(r"[A-Za-z0-9_]+", value))
        for identity in sorted(tokens & identities):
            violations.append(f"{path}:{node.lineno}: concrete Runner identity {identity!r}")
    return violations


def check_repository(root: Path) -> list[str]:
    identities = runner_identities(root / "docker" / "runners")
    violations: list[str] = []
    for namespace in ("revocompute", "tests"):
        for path in sorted((root / namespace).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if relative in BOUNDARY_FILES or relative.startswith(EXCLUDED_TEST_NAMESPACES):
                continue
            violations.extend(inspect_source(path.read_text(encoding="utf-8"), relative, identities))
    if (root / "docker" / "runners" / "_testkit").exists():
        violations.append("docker/runners/_testkit: testkit must be outside production discovery root")
    if (root / "tests" / "runners").exists():
        violations.append("tests/runners: family tests must be Runner-owned")
    return violations


def main() -> int:
    violations = check_repository(ROOT)
    if violations:
        print("\n".join(violations))
        return 1
    print("Server/Core Runner architecture boundary is clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
