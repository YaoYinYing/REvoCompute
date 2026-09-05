# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Static and low-cost conformance checks for runner-family plugins."""
from __future__ import annotations
import argparse, json, os, shutil, subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from revocompute.plugins import PluginManager
from revocompute.access_control import load_policy_documents, resolve_policy
from revocompute.live_tests import LiveTestConfigurationError, load_live_test_plan

@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str; severity: str; component: str; message: str
    runner_family: str | None = None; task: str | None = None; source: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
@dataclass(frozen=True, slots=True)
class DoctorReport:
    diagnostics: tuple[Diagnostic, ...]; checked: tuple[str, ...] = ()
    @property
    def ok(self): return not any(d.severity == "error" for d in self.diagnostics)
    def as_json(self): return json.dumps({"checked": list(self.checked), "diagnostics": [asdict(d) for d in self.diagnostics]}, indent=2, sort_keys=True)
    def as_text(self):
        lines = ["REvoCompute Doctor", "", "Checked: " + (", ".join(self.checked) if self.checked else "none")]
        lines.extend(f"{d.severity.upper()} {d.code}: {d.message}" for d in self.diagnostics)
        if len(lines) == 3: lines.append("OK — No diagnostics")
        return "\n".join(lines)
def diagnose(config_root: str | Path, *, runner: str | None = None, task: str | None = None, probe: bool = False) -> DoctorReport:
    root = Path(config_root); diagnostics: list[Diagnostic] = []; checked = ["plugin discovery", "task manifests", "JSON Schema"]
    manager = PluginManager()
    try: manifests = manager.discover(root)
    except Exception as exc:
        diagnostics.append(Diagnostic("E1004", "error", "plugin", f"Plugin discovery failed: {exc}", source=str(root))); return DoctorReport(tuple(diagnostics), tuple(checked))
    selected = {runner} if runner else {m.id for m in manifests}
    for manifest in manifests:
        api_version = manifest.api_version
        if str(api_version) != "1":
            diagnostics.append(Diagnostic("E1002", "error", "plugin", "Unsupported plugin API version", manifest.id, source=str(manifest.path)))
    if runner and runner not in {m.id for m in manifests}:
        diagnostics.append(Diagnostic("E1005", "error", "plugin", f"Unknown runner plugin: {runner!r}", runner_family=runner))
    task_found = False
    policy_catalog: dict[str, Any] = {}
    for manifest in manifests:
        if manifest.id not in selected: continue
        family = manifest.path; runtime = manifest.runtime
        # Validate runner-owned input workspace contributions and their task links.
        for descriptor in manifest.workspace_plugins.values():
            try:
                module_path = descriptor.asset_path(descriptor.module)
                if not module_path.is_file():
                    raise FileNotFoundError(descriptor.module)
                for style in descriptor.styles:
                    if not descriptor.asset_path(style).is_file():
                        raise FileNotFoundError(style)
                if descriptor.configuration_schema:
                    schema_path = descriptor.asset_path(descriptor.configuration_schema)
                    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
                    Draft202012Validator.check_schema(schema)
            except Exception as exc:
                diagnostics.append(Diagnostic("E2201", "error", "workspace", f"Invalid workspace plugin contribution: {exc}", manifest.id, source=str(family)))
        policy_refs = manifest.access_policies
        if isinstance(policy_refs, str):
            policy_refs = (policy_refs,)
        for policy_ref in policy_refs:
            policy_path = family / str(policy_ref)
            try:
                policies = load_policy_documents(policy_path)
                checked.append(f"{manifest.id}/access policies")
                for policy_id, policy in policies.items():
                    policy_catalog[policy_id] = policy
                    if policy_id not in manifest.contributions.get("access_policies", ()):
                        diagnostics.append(Diagnostic("E2101", "error", "policy", f"Policy {policy_id!r} is not declared as a contribution", manifest.id, source=str(policy_path)))
            except Exception as exc:
                diagnostics.append(Diagnostic("E2100", "error", "policy", f"Invalid access-policy contribution: {exc}", manifest.id, source=str(policy_path)))
        definition = runtime.get("definition", f"{manifest.id}.def") if isinstance(runtime, dict) else f"{manifest.id}.def"
        definition_path = Path(str(definition))
        if definition_path.is_absolute() or ".." in definition_path.parts:
            diagnostics.append(Diagnostic("E2002", "error", "runner", "Manifest runtime path must be relative to plugin root", manifest.id, source=str(family)))
        elif not (family / definition).exists():
            diagnostics.append(Diagnostic("E2003", "error", "runner", "Declared runner definition is missing", manifest.id, source=str(family)))
        policy_id = runtime.get("access_policy") if isinstance(runtime, dict) else None
        if policy_id:
            try:
                resolve_policy(str(policy_id), policy_catalog)
            except (KeyError, ValueError) as exc:
                diagnostics.append(Diagnostic("E2100", "error", "policy", f"Unresolved access policy: {exc}", manifest.id, source=str(family)))
        task_schemas: dict[str, dict[str, Any]] = {}
        task_defaults: dict[str, dict[str, Any]] = {}
        family_tasks: set[str] = set()
        runner_yaml = family / "runner.yaml"
        if runner_yaml.is_file():
            try:
                runner_doc = yaml.safe_load(runner_yaml.read_text(encoding="utf-8")) or {}
                defaults = runner_doc.get("defaults", {}) if isinstance(runner_doc, dict) else {}
            except Exception:
                defaults = {}
        else:
            defaults = {}
        for ref in manifest.tasks:
            ref_path = Path(str(ref))
            if ref_path.is_absolute() or ".." in ref_path.parts:
                diagnostics.append(Diagnostic("E2002", "error", "task", "Manifest task path must be relative to plugin root", manifest.id, source=str(family)))
                continue
            path = family / ref_path
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                task_id = str(doc.get("id", path.parent.name))
                if task_id == task:
                    task_found = True
                family_tasks.add(task_id)
                workspace = doc.get("input_workspace") or {}
                for step in workspace.get("steps", []) if isinstance(workspace, dict) else ():
                    for capability in step.get("capabilities", []) if isinstance(step, dict) else ():
                        plugin_id = capability.get("plugin") if isinstance(capability, dict) else None
                        if plugin_id in {"files", "folder", "artifact", "sequence", "text", "json", "structure", "regions", "parameters", "review"}:
                            continue
                        descriptor = manager.workspace_plugin(str(plugin_id), owner=manifest.runner_family or manifest.id)
                        if descriptor is None:
                            diagnostics.append(Diagnostic("E2202", "error", "workspace", f"Task capability references unresolved workspace plugin: {plugin_id!r}", manifest.id, task=str(doc.get("id", path.parent.name)), source=str(path)))
                            continue
                        if descriptor.backend.get("normalizer") and manager.workspace_backend(
                            descriptor.global_id
                        ) is None:
                            diagnostics.append(Diagnostic(
                                "E2204", "error", "workspace",
                                f"Workspace plugin backend could not be resolved: {descriptor.global_id!r}",
                                manifest.id, task=str(doc.get("id", path.parent.name)), source=str(path),
                            ))
                        if descriptor.configuration_schema and isinstance(capability, dict):
                            schema = yaml.safe_load(descriptor.asset_path(descriptor.configuration_schema).read_text(encoding="utf-8")) or {}
                            try:
                                Draft202012Validator(schema, format_checker=FormatChecker()).validate(capability.get("options", {}))
                            except Exception as exc:
                                diagnostics.append(Diagnostic("E2203", "error", "workspace", f"Workspace plugin options are invalid: {exc}", manifest.id, task=str(doc.get("id", path.parent.name)), source=str(path)))
                schema = doc.get("parameters") or doc.get("schema") or {}
                Draft202012Validator.check_schema(schema)
                Draft202012Validator(schema, format_checker=FormatChecker())
                task_schemas[task_id] = schema
                task_defaults[task_id] = defaults if isinstance(defaults, dict) else {}
                if task is None or task_id == task:
                    checked.append(f"{manifest.id}/{task_id}")
            except Exception as exc: diagnostics.append(Diagnostic("E3002", "error", "schema", f"Invalid task manifest/schema: {exc}", manifest.id, source=str(path)))
        test_path = family / "test.yaml"
        try:
            resolved_root = root.resolve()
            repo_root = resolved_root.parents[1] if resolved_root.parent.name == "docker" else Path(__file__).resolve().parents[1]
            plan = load_live_test_plan(
                test_path,
                repo_root=repo_root,
                task_schemas=task_schemas,
                task_defaults=task_defaults,
            )
            covered = {case.task for case in plan.select("smoke")}
            missing = family_tasks - covered
            if missing:
                raise LiveTestConfigurationError(
                    f"smoke collection does not cover enabled TaskTypes: {', '.join(sorted(missing))}"
                )
            checked.append(f"{manifest.id}/test.yaml")
        except LiveTestConfigurationError as exc:
            diagnostics.append(
                Diagnostic("E3100", "error", "live-test", str(exc), manifest.id, source=str(test_path))
            )
    if task and not task_found:
        diagnostics.append(Diagnostic("E3001", "error", "task", f"Unknown task: {task!r}"))
    if probe:
        checked.append("infrastructure probe")
        for command in ("sbatch", "squeue", "sacct", "scancel", "apptainer"):
            if shutil.which(command) is None: diagnostics.append(Diagnostic("W4001", "warning", "infrastructure", f"Command unavailable: {command}"))
            else: subprocess.run([command, "--version"], capture_output=True, text=True, timeout=5, check=False)
    return DoctorReport(tuple(diagnostics), tuple(dict.fromkeys(checked)))
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="revocompute doctor"); p.add_argument("--config-root", default=os.environ.get("RUNNERS_DIR", "docker/runners")); p.add_argument("--runner"); p.add_argument("--task"); p.add_argument("--probe", action="store_true"); p.add_argument("--strict", action="store_true"); p.add_argument("--json", dest="as_json", action="store_true"); a = p.parse_args(argv); report = diagnose(a.config_root, runner=a.runner, task=a.task, probe=a.probe); print(report.as_json() if a.as_json else report.as_text()); return 0 if report.ok or not a.strict else 1
if __name__ == "__main__": raise SystemExit(main())
