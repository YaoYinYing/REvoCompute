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
from jsonschema import Draft202012Validator
from revocompute.plugins import PluginManager

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
        if manifest.id not in selected: continue
        family = root / manifest.id; runtime = manifest.metadata.get("runtime", {})
        definition = runtime.get("definition", f"{manifest.id}.def") if isinstance(runtime, dict) else f"{manifest.id}.def"
        if not (family / definition).exists(): diagnostics.append(Diagnostic("E2003", "error", "runner", "Declared runner definition is missing", manifest.id, source=str(family)))
        for ref in manifest.metadata.get("tasks", []):
            path = family / str(ref)
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}; schema = doc.get("parameters") or doc.get("schema") or {}; Draft202012Validator.check_schema(schema); checked.append(f"{manifest.id}/{doc.get('id', path.parent.name)}")
            except Exception as exc: diagnostics.append(Diagnostic("E3002", "error", "schema", f"Invalid task manifest/schema: {exc}", manifest.id, source=str(path)))
    if probe:
        checked.append("infrastructure probe")
        for command in ("sbatch", "squeue", "sacct", "scancel", "apptainer"):
            if shutil.which(command) is None: diagnostics.append(Diagnostic("W4001", "warning", "infrastructure", f"Command unavailable: {command}"))
            else: subprocess.run([command, "--version"], capture_output=True, text=True, timeout=5, check=False)
    return DoctorReport(tuple(diagnostics), tuple(dict.fromkeys(checked)))
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="revocompute doctor"); p.add_argument("--config-root", default=os.environ.get("RUNNERS_DIR", "docker/runners")); p.add_argument("--runner"); p.add_argument("--task"); p.add_argument("--probe", action="store_true"); p.add_argument("--strict", action="store_true"); p.add_argument("--json", dest="as_json", action="store_true"); a = p.parse_args(argv); report = diagnose(a.config_root, runner=a.runner, task=a.task, probe=a.probe); print(report.as_json() if a.as_json else report.as_text()); return 0 if report.ok or not a.strict else 1
if __name__ == "__main__": raise SystemExit(main())
