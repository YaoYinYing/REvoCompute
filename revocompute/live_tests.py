# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Family-owned live-test declarations and hash-bound validation receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator, FormatChecker

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SECRET_KEY = re.compile(r"(secret|password|token|credential|private.?key)", re.IGNORECASE)


class LiveTestConfigurationError(ValueError):
    """A family live-test declaration is unsafe or invalid."""


@dataclass(frozen=True, slots=True)
class LiveTestCase:
    id: str
    task: str
    files: tuple[str, ...]
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LiveTestPlan:
    path: Path
    collections: Mapping[str, tuple[LiveTestCase, ...]]
    digest: str

    def select(self, collection: str, *, task: str | None = None) -> tuple[LiveTestCase, ...]:
        if collection not in self.collections:
            raise LiveTestConfigurationError(f"Unknown live-test collection: {collection!r}")
        return tuple(case for case in self.collections[collection] if task is None or case.task == task)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def sanitized_mapping(value: Any) -> Any:
    """Return deterministic public configuration with likely secrets removed."""
    if isinstance(value, Mapping):
        return {
            str(key): sanitized_mapping(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not _SECRET_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [sanitized_mapping(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def resolve_fixture(repo_root: str | Path, relative: str) -> Path:
    """Resolve one immutable repository fixture inside tests/data."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise LiveTestConfigurationError("Live-test fixture paths must be POSIX repository-relative paths")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts[:2] == ("tests", "data"):
        raise LiveTestConfigurationError(f"Live-test fixture must stay under tests/data: {relative!r}")
    allowed = (Path(repo_root) / "tests" / "data").resolve()
    candidate = (Path(repo_root) / path).resolve()
    if not candidate.is_relative_to(allowed):
        raise LiveTestConfigurationError(f"Live-test fixture escapes tests/data: {relative!r}")
    if not candidate.is_file():
        raise LiveTestConfigurationError(f"Live-test fixture does not exist: {relative!r}")
    return candidate


def load_live_test_plan(
    path: str | Path,
    *,
    repo_root: str | Path,
    task_schemas: Mapping[str, Mapping[str, Any]],
    task_defaults: Mapping[str, Mapping[str, Any]] | None = None,
) -> LiveTestPlan:
    """Parse and statically validate a version-1 family test.yaml."""
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise LiveTestConfigurationError(f"Unable to parse {source}: {exc}") from exc
    if not isinstance(raw, Mapping) or set(raw) - {"version", "collections"}:
        raise LiveTestConfigurationError("test.yaml must contain only version and collections")
    if raw.get("version") != 1:
        raise LiveTestConfigurationError("Unsupported live-test schema version")
    collections = raw.get("collections")
    if not isinstance(collections, Mapping) or not collections:
        raise LiveTestConfigurationError("test.yaml collections must be a non-empty mapping")
    parsed: dict[str, tuple[LiveTestCase, ...]] = {}
    seen: set[str] = set()
    defaults = task_defaults or {}
    for name, declaration in collections.items():
        if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
            raise LiveTestConfigurationError(f"Invalid live-test collection name: {name!r}")
        if not isinstance(declaration, Mapping) or set(declaration) != {"cases"}:
            raise LiveTestConfigurationError(f"Collection {name!r} must contain only cases")
        raw_cases = declaration["cases"]
        if not isinstance(raw_cases, list) or not raw_cases:
            raise LiveTestConfigurationError(f"Collection {name!r} cases must be a non-empty list")
        cases: list[LiveTestCase] = []
        for raw_case in raw_cases:
            if not isinstance(raw_case, Mapping) or set(raw_case) - {"id", "task", "input", "parameters"}:
                raise LiveTestConfigurationError(f"Collection {name!r} contains an invalid case")
            case_id = raw_case.get("id")
            task = raw_case.get("task")
            if not isinstance(case_id, str) or not _IDENTIFIER.fullmatch(case_id):
                raise LiveTestConfigurationError(f"Invalid live-test case ID: {case_id!r}")
            if case_id in seen:
                raise LiveTestConfigurationError(f"Duplicate live-test case ID: {case_id!r}")
            seen.add(case_id)
            if task not in task_schemas:
                raise LiveTestConfigurationError(f"Unknown TaskType in live test: {task!r}")
            input_decl = raw_case.get("input")
            files = input_decl.get("files") if isinstance(input_decl, Mapping) else None
            if not isinstance(files, list) or not files or any(not isinstance(item, str) for item in files):
                raise LiveTestConfigurationError(f"Live-test case {case_id!r} must declare one or more files")
            for fixture in files:
                resolve_fixture(repo_root, fixture)
            parameters = raw_case.get("parameters", {})
            if not isinstance(parameters, Mapping):
                raise LiveTestConfigurationError(f"Live-test case {case_id!r} parameters must be a mapping")
            merged = {**defaults.get(str(task), {}), **parameters}
            try:
                Draft202012Validator(task_schemas[str(task)], format_checker=FormatChecker()).validate(merged)
            except Exception as exc:
                message = getattr(exc, "message", str(exc))
                raise LiveTestConfigurationError(
                    f"Live-test case {case_id!r} parameters are invalid for {task!r}: {message}"
                ) from None
            cases.append(LiveTestCase(case_id, str(task), tuple(files), dict(parameters)))
        parsed[name] = tuple(cases)
    if "smoke" not in parsed:
        raise LiveTestConfigurationError("test.yaml must define a smoke collection")
    return LiveTestPlan(source, parsed, sha256_file(source))


@dataclass(slots=True)
class LiveTestReport:
    runner_family: str
    collection: str
    sif_sha256: str
    build_provenance_digest: str
    test_definition_digest: str
    configuration_digest: str
    state: str = "PREPARING"
    transitions: list[str] = field(default_factory=lambda: ["PREPARING"])
    passed: bool = False
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ended_at: str | None = None
    duration_seconds: float | None = None
    apptainer_version: str = ""
    resource_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    cases: list[dict[str, Any]] = field(default_factory=list)
    failure_category: str | None = None
    failure_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def atomic_write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False)
    try:
        json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, destination)


def receipt_matches(
    receipt: Mapping[str, Any],
    *,
    sif_sha256: str,
    build_provenance_digest: str,
    test_definition_digest: str,
    configuration_digest: str,
    required_case_ids: set[str],
) -> bool:
    passed_cases = {
        str(case.get("case_id"))
        for case in receipt.get("cases", ())
        if isinstance(case, Mapping) and case.get("passed") is True
    }
    return (
        receipt.get("passed") is True
        and receipt.get("sif_sha256") == sif_sha256
        and receipt.get("build_provenance_digest") == build_provenance_digest
        and receipt.get("test_definition_digest") == test_definition_digest
        and receipt.get("configuration_digest") == configuration_digest
        and required_case_ids <= passed_cases
    )
