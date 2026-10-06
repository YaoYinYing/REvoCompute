# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Architecture boundary tests for the MCP adapter layer.

The MCP surface is a protocol projection of the canonical application, so its
modules may depend on canonical application/service/domain contracts and may NOT
reach past them into execution internals: Runner implementations, the Slurm job
executor, Apptainer/SIF build code, the deployment controller, or a raw host
filesystem layer.

These are dependency tests, not text tests: they parse the real import graph of
the adapter package and fail on a forbidden target, so a future change that turns
MCP into a shortcut around Core fails here.  ``tools/check_mcp_boundary.py``
enforces the same rule in CI over the same forbidden-target list.
"""

from __future__ import annotations

import ast
from pathlib import Path

MCP_PACKAGE = Path(__file__).resolve().parents[2] / 'revocompute' / 'mcp'

# Import targets the adapter must never acquire.  Each entry is a module prefix.
FORBIDDEN_PREFIXES = (
    # Runner and Tool implementation trees.
    'docker.runners',
    'docker.tools',
    # Execution internals: scheduler runner, live-test executor, process runtime.
    'revocompute.job.runners',
    'revocompute.live_test_executor',
    'revocompute.live_tests',
    'revocompute.tool_runtime',
    'revocompute.tool_runtime_manager',
    # Deployment controller / operator control plane.
    'revocompute_ctl',
    # Operator maintenance tasks.
    'revocompute.maintenance',
    # Raw process execution.
    'subprocess',
)


def _imports(path: Path) -> set[str]:
    """Return every module name imported by *path* (static import statements)."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 0:
                found.add(node.module)
            else:
                found.add('.' * node.level + node.module)
    return found


def _mcp_modules() -> list[Path]:
    return sorted(p for p in MCP_PACKAGE.glob('*.py'))


def test_adapter_package_exists_and_is_importable_as_a_layer():
    assert _mcp_modules(), 'the MCP adapter package has no modules'


def test_adapter_never_imports_an_execution_internal():
    """No adapter module may reach Runner/Slurm/Apptainer/build/maintenance code."""
    violations: list[str] = []
    for path in _mcp_modules():
        for module in _imports(path):
            normalized = module.lstrip('.')
            for forbidden in FORBIDDEN_PREFIXES:
                if normalized == forbidden or normalized.startswith(forbidden + '.'):
                    violations.append(f'{path.name}: {module}')
    assert not violations, f'MCP adapter imports execution internals: {violations}'


def test_adapter_has_no_filesystem_or_network_escape_layer():
    """The adapter imports no raw HTTP client, URL opener, or shell escape."""
    forbidden_modules = {'requests', 'urllib.request', 'http.client', 'socket', 'shutil'}
    violations: list[str] = []
    for path in _mcp_modules():
        for module in _imports(path):
            normalized = module.lstrip('.')
            if normalized in forbidden_modules:
                violations.append(f'{path.name}: {module}')
    assert not violations, f'MCP adapter imports an escape-layer module: {violations}'


def test_adapter_reaches_the_application_only_through_canonical_modules():
    """Every revocompute import from the adapter is a canonical service/domain module."""
    allowed = {
        'revocompute.app',
        'revocompute.auth',
        'revocompute.config',
        'revocompute.db',
        'revocompute.operating',
        'revocompute.result_projection',
        'revocompute.storage',
        'revocompute.task_runtime',
        'revocompute.task_types',
        'revocompute.tool_calls',
        'revocompute.tool_types',
        'revocompute.mcp',
    }
    violations: list[str] = []
    for path in _mcp_modules():
        for module in _imports(path):
            if not module.startswith('revocompute'):
                continue
            top = '.'.join(module.split('.')[:2])
            if top not in allowed and module not in allowed:
                violations.append(f'{path.name}: {module}')
    assert not violations, f'MCP adapter bypasses the canonical layer: {violations}'


def test_canonical_application_does_not_depend_on_the_mcp_adapter():
    """The dependency direction is one-way: Core never imports the MCP adapter."""
    app_source = (Path(__file__).resolve().parents[2] / 'revocompute').glob('*.py')
    violations = [
        path.name
        for path in app_source
        if any(module.startswith('revocompute.mcp') for module in _imports(path))
    ]
    assert not violations, f'canonical modules import the MCP adapter: {violations}'


def test_server_declares_only_tools_and_resources():
    """The advertised capability set carries no bidirectional capability.

    Sampling and Elicitation are *client* capabilities; a server that declares
    neither cannot be asked to create messages or to request user input, and the
    initialization options are what actually negotiate that.
    """
    from revocompute.mcp.server import build_server

    server = build_server()
    options = server._mcp_server.create_initialization_options()
    capabilities = options.capabilities.model_dump(exclude_none=True)
    # Only tools and resources are advertised; nothing server-initiated.
    assert set(capabilities) <= {"experimental", "tools", "resources", "prompts", "logging", "completions"}
    assert "tools" in capabilities and "resources" in capabilities
    assert capabilities["tools"] == {"listChanged": False}
    assert capabilities["resources"] == {"subscribe": False, "listChanged": False}
    # No prompts are registered, so the server initiates no user-input flow.
    assert not list(server._prompt_manager.list_prompts())
