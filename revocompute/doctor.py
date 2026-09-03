# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Conformance diagnostics for a deployed REvoCompute instance.

The doctor deliberately validates protocol shape and cross-component links;
scientific semantics remain owned by runner-family plugins.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from revocompute.plugins import PluginManager


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: str
    component: str
    message: str
    runner_family: str | None = None
    task: str | None = None
    source: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DoctorReport:
    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    def as_json(self) -> str:
        return json.dumps([asdict(item) for item in self.diagnostics], indent=2, sort_keys=True)

    def as_text(self) -> str:
        if not self.diagnostics:
            return "REvoCompute Doctor\n\nNo diagnostics."
        lines = ["REvoCompute Doctor", ""]
        for item in self.diagnostics:
            location = ": ".join(part for part in (item.runner_family, item.task) if part)
            if location:
                location = f" [{location}]"
            source = f" ({item.source})" if item.source else ""
            lines.append(f"{item.severity.upper()} {item.code}{location}: {item.message}{source}")
            for key, value in item.details.items():
                lines.append(f"  {key}: {value}")
        return "\n".join(lines)


def _check(report: list[Diagnostic], **kwargs: Any) -> None:
    report.append(Diagnostic(**kwargs))


def _safe_relative(path: str) -> bool:
    candidate = Path(path)
    return not candidate.is_absolute() and ".." not in candidate.parts


def diagnose(config_root: str | Path, *, runner: str | None = None, task: str | None = None, probe: bool = False) -> DoctorReport:
    """Run low-cost conformance checks against a server configuration tree."""
    del probe  # Reserved for low-cost container probes in a future extension.
    root = Path(config_root)
    diagnostics: list[Diagnostic] = []
    registry_path = root / "task_types.yaml"
    if not registry_path.is_file():
        _check(diagnostics, code="E1001", severity="error", component="registry", message="Task registry is missing", source=str(registry_path))
        return DoctorReport(tuple(diagnostics))
    try:
        document = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        _check(diagnostics, code="E1002", severity="error", component="registry", message=f"Unable to parse task registry: {exc}", source=str(registry_path))
        return DoctorReport(tuple(diagnostics))
    if not isinstance(document, dict):
        _check(diagnostics, code="E1003", severity="error", component="registry", message="Task registry must be a mapping", source=str(registry_path))
        return DoctorReport(tuple(diagnostics))

    plugins = root / "plugins"
    manager = PluginManager()
    try:
        manager.discover(plugins)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        _check(diagnostics, code="E1004", severity="error", component="plugin", message=f"Plugin discovery failed: {exc}", source=str(plugins))
    families = document.get("runtime_families") or {}
    if not isinstance(families, dict):
        _check(diagnostics, code="E2001", severity="error", component="runner", message="runtime_families must be a mapping", source=str(registry_path))
        return DoctorReport(tuple(diagnostics))
    selected = {runner} if runner else set(families)
    for family_id in sorted(selected):
        entry = families.get(family_id)
        if entry is None:
            _check(diagnostics, code="E1005", severity="error", component="runner", message="Requested runner family is unknown", runner_family=family_id, source=str(registry_path))
            continue
        if not isinstance(entry, dict):
            _check(diagnostics, code="E2002", severity="error", component="runner", message="Runner family declaration must be a mapping", runner_family=family_id, source=str(registry_path))
            continue
        for key in ("docker_image", "dockerfile", "definition"):
            value = entry.get(key)
            if not isinstance(value, str) or not value.strip():
                _check(diagnostics, code="E2003", severity="error", component="runner", message=f"Missing required field: {key}", runner_family=family_id, source=str(registry_path))
            elif key != "docker_image" and not _safe_relative(value):
                _check(diagnostics, code="E3001", severity="error", component="execution", message=f"Unsafe relative path in {key}", runner_family=family_id, source=str(registry_path), details={"value": value})
        runner_config = root / "runners" / f"{family_id}.yaml"
        if not runner_config.is_file():
            _check(diagnostics, code="E2004", severity="error", component="runner", message="Runner configuration is missing", runner_family=family_id, source=str(runner_config))

    task_defs = document.get("task_types") or {}
    if isinstance(task_defs, dict):
        for task_id, declaration in task_defs.items():
            if task and task_id != task:
                continue
            if not isinstance(declaration, dict):
                _check(diagnostics, code="E2101", severity="error", component="task", message="Task declaration must be a mapping", task=str(task_id), source=str(registry_path))
                continue
            family = declaration.get("runtime_family")
            if family and family not in families:
                _check(diagnostics, code="E5101", severity="error", component="link", message="Task references an unknown runner family", runner_family=str(family), task=str(task_id), source=str(registry_path))
    return DoctorReport(tuple(diagnostics))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="revocompute doctor")
    parser.add_argument("--config-root", default=os.environ.get("CONFIG_DIR", "config"))
    parser.add_argument("--runner")
    parser.add_argument("--task")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    report = diagnose(args.config_root, runner=args.runner, task=args.task, probe=args.probe)
    print(report.as_json() if args.as_json else report.as_text())
    return 0 if report.ok or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())

