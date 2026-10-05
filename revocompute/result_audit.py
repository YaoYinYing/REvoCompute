# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""One canonical static audit of a discovered Runner fleet's result contract.

The audit asks one question: for every shipped Task, does the result contract it
declares internally cohere? It reads the fleet through the loaders production
uses -- ``task_types.discover_plugins`` for the Task and ResultView
declarations, ``result_storyboard`` for the ``expected_files.yaml`` and
``storyboard.yaml`` declarations, and ``result_projection.artifact_capability``
for the renderer the source resolves to -- so it can never accept a declaration
the Server would reject. It is not a second YAML linter.

What the audit proves: the declarations are internally satisfiable -- a required
view source is addressed by a declared result-tree location, a storyboard binds
only to declared logical files, a renderer mapping carries the fields its plugin
requires, and a declared data format matches the artifact it selects. What it
does not prove: that a Runner executed, that the science is valid, or that the
bytes a Runner writes match the declaration. Those claims belong to smoke/live
acceptance and scientific reference tests.

Every finding names the owning Task and view (or logical file) so a failure is
actionable without re-deriving which manifest is at fault.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from revocompute.result_projection import artifact_capability
from revocompute.result_storyboard import (
    ResultContractError,
    expected_file_tree,
    storyboard_declaration,
)
from revocompute.task_types import ResultView, TaskType, discover_plugins, list_types

#: The declared result-tree ``type`` a view source must resolve to, per plugin
#: and source name. ``None`` means the source imposes no type constraint: an
#: evidence bundle carries arbitrary bounded artifacts and a matrix/series/scalar
#: source is parsed, so neither constrains the identity layer. A tree entry that
#: declares no ``type`` is not constrained either.
_REQUIRED_SOURCE_KIND: dict[str, dict[str, str | None]] = {
    "structure": {"structure": "molecular_structure"},
    "candidate-collection": {"candidates": "molecular_structure", "supporting": None},
    "entity-table": {"table": "table", "structure": "molecular_structure"},
    "alignment": {"alignment": "text"},
    "trajectory": {"topology": "molecular_structure", "coordinates": None},
    "metric-series": {"series": None},
    "matrix": {"matrices": None},
    "scalar-summary": {"data": None},
    "evidence-bundle": {"items": None},
}

#: Source names whose selected artifact is not the identity layer the
#: ``expected_files.yaml`` tree enumerates, so an undeclared required source is
#: not a contract defect. An evidence bundle explicitly carries raw artifacts by
#: path (fpocket's own contract requires ``work/*_out/*_info.txt``, which is not
#: a logical file), and a trajectory's coordinates are an optional companion to
#: its declared topology.
_COVERAGE_EXEMPT_SOURCES: frozenset[tuple[str, str]] = frozenset({("evidence-bundle", "items")})

#: File extensions a declared ``format``/``coordinate_format`` may address, and
#: the source it governs. A format is checked only against the source it
#: describes; the trajectory topology is a coordinate file, not the trajectory.
_FORMAT_EXTENSIONS: dict[str, frozenset[str]] = {
    "csv": frozenset({".csv", ".tsv"}),
    "json": frozenset({".json"}),
    "a3m": frozenset({".a3m"}),
    "fasta": frozenset({".fasta", ".fa", ".fas"}),
    "stockholm": frozenset({".sto", ".stockholm"}),
    "pdb": frozenset({".pdb"}),
    "xtc": frozenset({".xtc"}),
    "dcd": frozenset({".dcd"}),
}
#: (plugin, mapping key) -> the source names the key's format constrains.
_FORMAT_SOURCES: dict[tuple[str, str], frozenset[str]] = {
    ("matrix", "format"): frozenset({"matrices"}),
    ("metric-series", "format"): frozenset({"series"}),
    ("alignment", "format"): frozenset({"alignment"}),
    ("trajectory", "coordinate_format"): frozenset({"coordinates"}),
}


class ContractFinding:
    """One actionable result-contract defect, owned by a Task and a view."""

    __slots__ = ("code", "task", "view", "detail")

    def __init__(self, code: str, task: str, detail: str, view: str | None = None) -> None:
        self.code = code
        self.task = task
        self.view = view
        self.detail = detail

    def __str__(self) -> str:
        owner = f"{self.task}/{self.view}" if self.view else self.task
        return f"{self.code}: {owner}: {self.detail}"


@dataclass(frozen=True, slots=True)
class FleetAuditReport:
    """The audit's result: the Tasks it checked and the defects it found."""

    tasks: tuple[str, ...]
    findings: tuple[ContractFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings

    def as_text(self) -> str:
        lines = [f"Result contract audit: {len(self.tasks)} tasks checked"]
        lines.extend(f"  {finding}" for finding in self.findings)
        if not self.findings:
            lines.append("  OK - every declaration is internally satisfiable")
        return "\n".join(lines)


def _covering_entries(tree: Mapping[str, Mapping[str, Any]], selector: Any) -> list[tuple[str, Mapping[str, Any]]]:
    """Return the declared logical files a view selector can select.

    A selector is an exact ``path`` (matched literally, as ``task_runtime`` does)
    or a ``glob``; a declared logical file is an exact ``path`` or a ``pattern``.
    They overlap when either side's glob matches the other's literal, which is
    the same relation ``fnmatchcase`` expresses over the published paths both
    resolve against.
    """
    covered: list[tuple[str, Mapping[str, Any]]] = []
    for logical_id, definition in tree.items():
        declared = definition.get("path") or definition["pattern"]
        if fnmatchcase(selector.value, declared) or fnmatchcase(declared, selector.value):
            covered.append((str(logical_id), definition))
    return covered


def _declared_capability(definition: Mapping[str, Any]) -> str:
    """The renderer capability a declared logical file's ``type`` projects to."""
    return artifact_capability(None, str(definition.get("type") or "") or None)


def _audit_view(task: TaskType, view: ResultView, tree: Mapping[str, Mapping[str, Any]] | None) -> list[ContractFinding]:
    findings: list[ContractFinding] = []
    expectations = _REQUIRED_SOURCE_KIND.get(view.plugin, {})
    for mapping_key in ("format", "coordinate_format"):
        declared_format = view.mapping.get(mapping_key)
        if declared_format is None:
            continue
        extensions = _FORMAT_EXTENSIONS.get(str(declared_format), frozenset())
        governed = _FORMAT_SOURCES.get((view.plugin, mapping_key), frozenset())
        for source_name in governed:
            for selector in view.sources.get(source_name, ()):
                suffix = os.path.splitext(selector.value)[1].lower()
                if suffix and suffix not in extensions:
                    findings.append(
                        ContractFinding(
                            "result.format_source_mismatch",
                            task.name,
                            f"source {source_name!r} selects {selector.value!r}, which the declared "
                            f"{mapping_key} {declared_format!r} cannot be parsed from",
                            view.id,
                        )
                    )
    if tree is None:
        return findings
    exempt = _COVERAGE_EXEMPT_SOURCES
    for source_name, selectors in view.sources.items():
        for selector in selectors:
            covered = _covering_entries(tree, selector)
            if selector.required and (view.plugin, source_name) not in exempt:
                if not covered:
                    findings.append(
                        ContractFinding(
                            "result.required_source_unaddressed",
                            task.name,
                            f"required source {source_name!r} ({selector.value!r}) is addressed by no "
                            f"declared result-tree location",
                            view.id,
                        )
                    )
            expected_kind = expectations.get(source_name)
            if expected_kind is None:
                continue
            for logical_id, entry in covered:
                if "type" not in entry:
                    continue
                actual = _declared_capability(entry)
                if actual != expected_kind:
                    findings.append(
                        ContractFinding(
                            "result.renderer_source_kind_mismatch",
                            task.name,
                            f"source {source_name!r} ({selector.value!r}) feeds a {view.plugin!r} view but "
                            f"logical file {logical_id!r} declares type {entry.get('type')!r} "
                            f"({actual}), not {expected_kind}",
                            view.id,
                        )
                    )
    return findings


def _audit_logical_files(task: TaskType, tree: Mapping[str, Mapping[str, Any]]) -> list[ContractFinding]:
    """Two overlapping logical files with differing role/cardinality are ambiguous."""
    findings: list[ContractFinding] = []
    items = list(tree.items())
    for index, (left_id, left) in enumerate(items):
        left_selector = left.get("path") or left["pattern"]
        for right_id, right in items[index + 1 :]:
            right_selector = right.get("path") or right["pattern"]
            if not (fnmatchcase(left_selector, right_selector) or fnmatchcase(right_selector, left_selector)):
                continue
            if (left.get("role"), left["cardinality"]) != (right.get("role"), right["cardinality"]):
                findings.append(
                    ContractFinding(
                        "result.ambiguous_logical_ownership",
                        task.name,
                        f"logical files {left_id!r} and {right_id!r} can select the same result path but "
                        f"declare different role/cardinality; the published role of a matching file "
                        f"would be ambiguous",
                    )
                )
    return findings


def _audit_storyboard(
    task: TaskType, declaration: Mapping[str, Any] | None, tree: Mapping[str, Mapping[str, Any]] | None
) -> list[ContractFinding]:
    if declaration is None or tree is None:
        return []
    findings: list[ContractFinding] = []
    for logical_id in declaration.get("requires", ()):
        definition = tree.get(str(logical_id))
        if definition is not None and not definition.get("required"):
            findings.append(
                ContractFinding(
                    "result.storyboard_requires_optional_file",
                    task.name,
                    f"storyboard requires logical file {logical_id!r}, which the result tree declares "
                    f"optional, so the storyboard can open on a result that cannot satisfy it",
                )
            )
    return findings


def audit_task(task_type: TaskType, *, server_dir: str | None = None) -> list[ContractFinding]:
    """Audit one discovered Task's result contract against its own declarations."""
    findings: list[ContractFinding] = []
    primaries = [view for view in task_type.result_workspace if view.role == "primary"]
    if len(primaries) > 1:
        findings.append(
            ContractFinding(
                "result.primary_view_not_unique",
                task_type.name,
                f"{len(primaries)} primary views are declared: {', '.join(view.id for view in primaries)}",
            )
        )
    tree: dict[str, dict[str, Any]] | None = None
    try:
        tree = expected_file_tree(task_type, server_dir or "") or None
    except ResultContractError as exc:
        findings.append(ContractFinding("result.expected_files_invalid", task_type.name, str(exc)))
    declaration: Mapping[str, Any] | None = None
    if tree is not None:
        try:
            declaration = storyboard_declaration(task_type, server_dir or "", set(tree))
        except ResultContractError as exc:
            findings.append(ContractFinding("result.storyboard_invalid", task_type.name, str(exc)))
        findings.extend(_audit_logical_files(task_type, tree))
    for view in task_type.result_workspace:
        findings.extend(_audit_view(task_type, view, tree))
    findings.extend(_audit_storyboard(task_type, declaration, tree))
    return findings


def audit_fleet(runners_dir: str | os.PathLike[str], *, server_dir: str | None = None) -> FleetAuditReport:
    """Audit every Task the canonical loader discovers under ``runners_dir``.

    Discovery is the production path; a manifest the loader rejects fails the
    audit with the loader's own message (which names the offending task/view id)
    rather than being silently skipped, so the fleet is audited as a whole.
    """
    try:
        discover_plugins(os.fspath(runners_dir))
    except Exception as exc:  # noqa: BLE001 - any discovery failure is a fleet finding
        return FleetAuditReport((), (ContractFinding("result.fleet_discovery_failed", "-", str(exc)),))
    tasks = sorted(list_types(), key=lambda task_type: task_type.name)
    findings: list[ContractFinding] = []
    for task_type in tasks:
        findings.extend(audit_task(task_type, server_dir=server_dir))
    return FleetAuditReport(tuple(task.name for task in tasks), tuple(findings))


__all__ = ["ContractFinding", "FleetAuditReport", "audit_fleet", "audit_task"]


def _unused(_: Sequence[Any]) -> None:  # pragma: no cover - keeps Sequence import honest
    raise NotImplementedError
