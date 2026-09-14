# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Independent discovery and contracts for short-lived scientific Tools."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from revocompute.io_contracts import NamedFileRole, ROLE_ID_PATTERN, load_named_file_roles


@dataclass(frozen=True)
class ToolFileRole(NamedFileRole):
    """One named Tool input or output role."""


@dataclass(frozen=True)
class ToolRuntimeFamily:
    name: str
    version: str
    root: Path
    definition: Path
    image: Path
    entrypoint: tuple[str, ...]
    health_command: tuple[str, ...]
    identity: str


@dataclass(frozen=True)
class ToolType:
    name: str
    display_name: str
    summary: str
    guidance: str
    version: str
    runtime: ToolRuntimeFamily
    inputs: tuple[ToolFileRole, ...]
    outputs: tuple[ToolFileRole, ...]
    schema: Mapping[str, Any]
    timeout_seconds: int

    def role(self, name: str, *, output: bool = False) -> ToolFileRole | None:
        roles = self.outputs if output else self.inputs
        return next((role for role in roles if role.name == name), None)


class ToolRegistry:
    """Validated catalog built only from explicitly enabled Tool families."""

    def __init__(self, tools: Mapping[str, ToolType] | None = None) -> None:
        self._tools = dict(tools or {})
        self._families = {tool.runtime.name: tool.runtime for tool in self._tools.values()}

    @classmethod
    def discover(
        cls,
        root: str | Path,
        *,
        enabled: set[str],
        image_root: str | Path | None = None,
        maximum_timeout: int = 300,
    ) -> "ToolRegistry":
        root_path = Path(root).resolve()
        manifests: dict[str, Path] = {}
        for path in sorted(root_path.glob("*/plugin.yaml")) if root_path.exists() else ():
            raw = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, "Tool plugin manifest")
            family_id = _identifier(raw.get("id"), "Tool runtime family id")
            if family_id in manifests:
                raise ValueError(f"Duplicate Tool runtime family: {family_id!r}")
            manifests[family_id] = path
        unknown = enabled - manifests.keys()
        if unknown:
            raise ValueError(f"Enabled Tool runtime families are not installed: {', '.join(sorted(unknown))}")
        tools: dict[str, ToolType] = {}
        for family_id in sorted(enabled):
            path = manifests[family_id]
            raw = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, "Tool plugin manifest")
            family_root = path.parent.resolve()
            version = _text(raw.get("version"), f"Tool family {family_id!r} version")
            runtime_raw = _mapping(raw.get("runtime"), f"Tool family {family_id!r} runtime")
            definition = _relative_file(family_root, runtime_raw.get("definition"), "runtime definition")
            image_name = _text(runtime_raw.get("image", f"{family_id}.sif"), "runtime image")
            image = Path(image_root).resolve() / image_name if image_root else family_root / image_name
            entrypoint = _argv(runtime_raw.get("entrypoint"), "runtime entrypoint")
            health_command = _argv(runtime_raw.get("health_command"), "runtime health command")
            image_digest = _sha256(image) if image.is_file() else "missing"
            identity_payload = f"{family_id}\0{version}\0{image}\0{image_digest}"
            identity = hashlib.sha256(identity_payload.encode("utf-8")).hexdigest()[:16]
            runtime = ToolRuntimeFamily(
                family_id, version, family_root, definition, image, entrypoint, health_command, identity
            )
            refs = raw.get("tools")
            if not isinstance(refs, list) or not refs:
                raise ValueError(f"Tool family {family_id!r} must declare Tool manifests")
            for ref in refs:
                tool_path = _relative_file(family_root, ref, "Tool manifest")
                tool = _load_tool(tool_path, runtime, maximum_timeout)
                if tool.name in tools:
                    raise ValueError(f"Duplicate Tool id: {tool.name!r}")
                tools[tool.name] = tool
        return cls(tools)

    def get(self, name: str) -> ToolType:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown Tool: {name!r}") from exc

    def list(self) -> tuple[ToolType, ...]:
        return tuple(self._tools[name] for name in sorted(self._tools))

    def families(self) -> tuple[ToolRuntimeFamily, ...]:
        return tuple(self._families[name] for name in sorted(self._families))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _identifier(value: Any, label: str) -> str:
    text = _text(value, label)
    if not ROLE_ID_PATTERN.fullmatch(text):
        raise ValueError(f"{label} is invalid")
    return text


def _argv(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must be a non-empty argv list")
    return tuple(value)


def _relative_file(root: Path, value: Any, label: str) -> Path:
    text = _text(value, label)
    relative = Path(text)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} must stay within its Tool family")
    result = (root / relative).resolve()
    if not result.is_relative_to(root) or not result.is_file():
        raise ValueError(f"{label} does not resolve to a file: {text}")
    return result


def _load_tool(path: Path, runtime: ToolRuntimeFamily, maximum_timeout: int) -> ToolType:
    raw = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, "Tool manifest")
    allowed = {
        "id", "display_name", "summary", "guidance", "version", "runtime_family",
        "inputs", "outputs", "parameters", "timeout_seconds",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Tool manifest {path} contains unknown fields: {sorted(unknown)}")
    name = _identifier(raw.get("id"), "Tool id")
    if raw.get("runtime_family") != runtime.name:
        raise ValueError(f"Tool {name!r} does not reference its owning runtime family")
    inputs = load_named_file_roles(
        raw.get("inputs"), owner=f"Tool {name!r}", collection="inputs", factory=ToolFileRole
    )
    outputs = load_named_file_roles(
        raw.get("outputs"), owner=f"Tool {name!r}", collection="outputs", factory=ToolFileRole
    )
    if not inputs or not outputs:
        raise ValueError(f"Tool {name!r} must declare at least one input and output")
    schema = _mapping(
        raw.get("parameters", {"type": "object", "additionalProperties": False}),
        f"Tool {name!r} parameters",
    )
    Draft202012Validator.check_schema(schema)
    timeout = raw.get("timeout_seconds", maximum_timeout)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1 or timeout > maximum_timeout:
        raise ValueError(f"Tool {name!r} timeout must be between 1 and {maximum_timeout} seconds")
    return ToolType(
        name=name,
        display_name=_text(raw.get("display_name"), f"Tool {name!r} display name"),
        summary=_text(raw.get("summary"), f"Tool {name!r} summary"),
        guidance=_text(raw.get("guidance"), f"Tool {name!r} guidance"),
        version=_text(raw.get("version"), f"Tool {name!r} version"),
        runtime=runtime,
        inputs=inputs,
        outputs=outputs,
        schema=dict(schema),
        timeout_seconds=timeout,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def public_tool(tool: ToolType) -> dict[str, Any]:
    def role_payload(role: ToolFileRole) -> dict[str, Any]:
        return {
            "id": role.name,
            "title": role.title,
            "type": role.type,
            "formats": list(role.formats),
            "cardinality": {"min": role.minimum, "max": role.maximum},
            "description": role.description,
        }

    return {
        "id": tool.name,
        "display_name": tool.display_name,
        "summary": tool.summary,
        "guidance": tool.guidance,
        "version": tool.version,
        "runtime_family": tool.runtime.name,
        "runtime_identity": tool.runtime.identity,
        "inputs": [role_payload(role) for role in tool.inputs],
        "outputs": [role_payload(role) for role in tool.outputs],
        "timeout_seconds": tool.timeout_seconds,
    }


def canonical_parameters(parameters: Mapping[str, Any]) -> str:
    return json.dumps(parameters, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
