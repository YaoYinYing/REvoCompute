# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from revocompute.tool_types import ToolRegistry, public_tool


def _family(root: Path, *, family: str = "fixture", timeout: int = 30) -> None:
    family_root = root / family
    tool_root = family_root / "tools" / "inspect"
    tool_root.mkdir(parents=True)
    (family_root / f"{family}.def").touch()
    (family_root / "plugin.yaml").write_text(
        yaml.safe_dump(
            {
                "id": family,
                "version": "1.0.0",
                "runtime": {
                    "definition": f"{family}.def",
                    "image": f"{family}.sif",
                    "entrypoint": ["python", "-m", "fixture_tool"],
                    "health_command": ["python", "-m", "fixture_tool", "health"],
                },
                "tools": ["tools/inspect/tool.yaml"],
            }
        ),
        encoding="utf-8",
    )
    (tool_root / "tool.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "inspect",
                "display_name": "Inspect",
                "summary": "Inspect one typed fixture.",
                "guidance": "Use for bounded fixture metadata.",
                "version": "1",
                "runtime_family": family,
                "inputs": {
                    "structure": {
                        "type": "protein_structure",
                        "formats": ["pdb", "mmcif"],
                        "cardinality": {"min": 1, "max": 1},
                    }
                },
                "outputs": {
                    "inspection": {
                        "type": "inspection",
                        "formats": ["json"],
                        "cardinality": {"min": 1, "max": 1},
                    }
                },
                "parameters": {"type": "object", "additionalProperties": False},
                "timeout_seconds": timeout,
            }
        ),
        encoding="utf-8",
    )


def test_discovery_projects_typed_tool_contract(tmp_path):
    _family(tmp_path)

    registry = ToolRegistry.discover(tmp_path, enabled={"fixture"}, maximum_timeout=60)
    tool = registry.get("inspect")
    payload = public_tool(tool)

    assert tool.runtime.name == "fixture"
    assert tool.inputs[0].type == "protein_structure"
    assert tool.outputs[0].formats == ("json",)
    assert payload["inputs"][0]["cardinality"] == {"min": 1, "max": 1}
    assert payload["runtime_identity"] == tool.runtime.identity


def test_discovery_requires_explicit_valid_family_enablement(tmp_path):
    _family(tmp_path)

    assert ToolRegistry.discover(tmp_path, enabled=set()).list() == ()
    with pytest.raises(ValueError, match="not installed"):
        ToolRegistry.discover(tmp_path, enabled={"missing"})


def test_tool_contract_cannot_raise_deployment_timeout(tmp_path):
    _family(tmp_path, timeout=61)

    with pytest.raises(ValueError, match="between 1 and 60"):
        ToolRegistry.discover(tmp_path, enabled={"fixture"}, maximum_timeout=60)
