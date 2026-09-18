# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Isolated ephemeral workspace and typed result handling for Tool calls."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, BinaryIO

from werkzeug.utils import secure_filename

from revocompute.tool_calls import normalize_tool_call_id
from revocompute.tool_types import ToolType


class ToolWorkspaceError(ValueError):
    pass


class ToolWorkspace:
    def __init__(self, root: str | Path, *, request_max_bytes: int, output_max_bytes: int) -> None:
        self.root = Path(root).resolve()
        self.request_max_bytes = request_max_bytes
        self.output_max_bytes = output_max_bytes

    def call_root(self, tool_call_id: str) -> Path:
        if normalize_tool_call_id(tool_call_id) is None:
            raise ToolWorkspaceError("Invalid Tool call id")
        return self.root / tool_call_id

    def create(self, tool_call_id: str) -> Path:
        call_root = self.call_root(tool_call_id)
        self.root.mkdir(parents=True, exist_ok=True)
        call_root.mkdir(mode=0o700)
        for name in ("input", "output", "scratch"):
            (call_root / name).mkdir(mode=0o700)
        return call_root

    @staticmethod
    def _format_for_filename(filename: str, accepted: tuple[str, ...]) -> str:
        extension = Path(filename).suffix.lower().removeprefix(".")
        aliases = {"cif": "mmcif", "fa": "fasta", "faa": "fasta"}
        candidate = extension if extension in accepted else aliases.get(extension, extension)
        if candidate not in accepted:
            raise ToolWorkspaceError("Input file format is incompatible with its Tool role")
        return candidate

    def materialize_stream(
        self,
        tool_call_id: str,
        *,
        role: str,
        filename: str,
        accepted_formats: tuple[str, ...],
        stream: BinaryIO,
    ) -> dict[str, Any]:
        safe_name = secure_filename(Path(filename).name)
        if not safe_name:
            raise ToolWorkspaceError("Tool input filename is invalid")
        format_name = self._format_for_filename(safe_name, accepted_formats)
        role_root = self.call_root(tool_call_id) / "input" / role
        role_root.mkdir(mode=0o700)
        target = role_root / safe_name
        if target.exists():
            raise ToolWorkspaceError("Tool input filenames must be unique within a role")
        digest = hashlib.sha256()
        size = 0
        with target.open("xb") as output:
            while chunk := stream.read(65536):
                size += len(chunk)
                if size > self.request_max_bytes:
                    raise ToolWorkspaceError("Tool request input limit exceeded")
                digest.update(chunk)
                output.write(chunk)
        target.chmod(0o400)
        return {
            "original_name": filename,
            "relative_path": f"{role}/{safe_name}",
            "path": f"/tool/input/{role}/{safe_name}",
            "physical_path": str(target),
            "format": format_name,
            "sha256": digest.hexdigest(),
            "size": size,
        }

    def materialize_file(
        self,
        tool_call_id: str,
        *,
        role: str,
        filename: str,
        accepted_formats: tuple[str, ...],
        source: str | Path,
    ) -> dict[str, Any]:
        source_path = Path(source)
        if source_path.is_symlink() or not source_path.is_file():
            raise ToolWorkspaceError("Tool input source is unavailable")
        with source_path.open("rb") as stream:
            return self.materialize_stream(
                tool_call_id,
                role=role,
                filename=filename,
                accepted_formats=accepted_formats,
                stream=stream,
            )

    def write_request(self, tool_call_id: str, tool: ToolType, inputs: dict[str, list[dict]], parameters: dict) -> Path:
        public_inputs = {
            role: [
                {key: item[key] for key in ("original_name", "path", "format", "sha256", "size")}
                for item in values
            ]
            for role, values in inputs.items()
        }
        target = self.call_root(tool_call_id) / "scratch" / "request.json"
        target.write_text(
            json.dumps({"tool": tool.name, "parameters": parameters, "inputs": public_inputs}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        target.chmod(0o400)
        return target

    def collect(
        self, tool_call_id: str, tool: ToolType
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict], dict[str, Any]]:
        output_root = self.call_root(tool_call_id) / "output"
        response_path = output_root / ".tool-response.json"
        if response_path.is_symlink() or not response_path.is_file():
            raise ToolWorkspaceError("Tool did not produce a response manifest")
        try:
            response = json.loads(response_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolWorkspaceError("Tool response manifest is invalid") from exc
        raw_outputs = response.get("outputs") if isinstance(response, dict) else None
        warnings = response.get("warnings", []) if isinstance(response, dict) else None
        if not isinstance(raw_outputs, dict) or not isinstance(warnings, list) or not all(isinstance(item, dict) for item in warnings):
            raise ToolWorkspaceError("Tool response manifest has invalid outputs or warnings")
        unknown = set(raw_outputs) - {role.name for role in tool.outputs}
        if unknown:
            raise ToolWorkspaceError("Tool response declares an unknown logical output")
        result: dict[str, list[dict[str, Any]]] = {}
        total_size = 0
        for role in tool.outputs:
            values = raw_outputs.get(role.name, [])
            if not isinstance(values, list) or not role.minimum <= len(values) <= role.maximum:
                raise ToolWorkspaceError(f"Tool output {role.name!r} violates its cardinality")
            collected: list[dict[str, Any]] = []
            for item in values:
                if not isinstance(item, dict) or set(item) != {"path", "format"} or item["format"] not in role.formats:
                    raise ToolWorkspaceError(f"Tool output {role.name!r} has an invalid declaration")
                relative = Path(str(item["path"]))
                if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
                    raise ToolWorkspaceError("Tool output path is invalid")
                physical = output_root / relative
                if physical.is_symlink() or not physical.is_file() or not physical.resolve().is_relative_to(output_root):
                    raise ToolWorkspaceError("Tool output is unavailable or escapes its workspace")
                size = physical.stat().st_size
                total_size += size
                if total_size > self.output_max_bytes:
                    raise ToolWorkspaceError("Tool output limit exceeded")
                digest = hashlib.sha256(physical.read_bytes()).hexdigest()
                collected.append(
                    {
                        "path": relative.name,
                        "format": item["format"],
                        "logical_type": role.type,
                        "sha256": digest,
                        "size": size,
                        "physical_path": str(physical),
                    }
                )
            result[role.name] = collected
        backend = response.get("backend", {}) if isinstance(response, dict) else {}
        if not isinstance(backend, dict) or any(not isinstance(key, str) for key in backend):
            raise ToolWorkspaceError("Tool response backend provenance is invalid")
        return result, warnings, backend

    def bytes_used(self, tool_call_id: str) -> int:
        return sum(path.stat().st_size for path in self.call_root(tool_call_id).rglob("*") if path.is_file() and not path.is_symlink())

    def delete(self, tool_call_id: str) -> None:
        call_root = self.call_root(tool_call_id)
        if call_root.exists() and not call_root.is_symlink():
            shutil.rmtree(call_root)
