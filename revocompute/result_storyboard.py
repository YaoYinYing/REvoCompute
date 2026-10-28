# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Runner-declared result files and trusted storyboard assets.

A Runner family declares one *result contract* per Task: the logical identities
its published files resolve to (``expected_files.yaml``) and, optionally, the
trusted Storyboard module that gives a result its task-level meaning.  A
contract is owned either

* **Task-scoped** -- ``expected_files.yaml`` and ``storyboard/`` beside the
  owning Task manifest, inside that family's ``tasks/<task-id>/`` directory, or
* **family-scoped** -- the same two names directly under the family directory,
  shared by every Task of that family which ships no contract of its own.

Precedence is positional and total, never inferred:

* A Task whose own manifest directory ships ``expected_files.yaml`` is resolved
  entirely from that directory -- its Storyboard comes from there too.  One
  family may host TaskTypes whose result trees are mutually incompatible:
  ``foundry`` folds with RF3 (``<example_id>_seed-<n>_sample-<n>_model.cif``
  beside a ``seed,sample,ranking_score`` table) and designs with RFD3/RFD3NA
  (``<example_id>_model_<n>.cif.gz``), so one shared tree can only
  under-describe at least one of them.
* Every other Task keeps the family-scoped contract, unchanged.

The Task's own directory is the one discovery recorded on the TaskType
(``task_dir``, family-relative) from a manifest path the Server already
validated, so ownership never comes from a result filename, a task name, or
anything a task's own output can influence.  It is still re-checked here
against traversal and symlinks, and a Task directory shipping a ``storyboard/``
without its own ``expected_files.yaml`` is refused rather than answered from
the family tree: that declaration means "this Storyboard binds to logical files
this Task declares", and another Task's tree would bind the module to
identities it never declared.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
import os
from pathlib import Path
import re
from typing import Any

import yaml

_LOGICAL_FILE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# A runner may declare how one of its own files is presented.  ``primary`` is
# absent on purpose: it belongs to the task's single primary view, which the
# server owns, not to a runner file declaration.
_RESULT_FILE_ROLES = frozenset({"evidence", "provenance", "diagnostic", "artifact"})


class ResultContractError(ValueError):
    """A runner result declaration is malformed or unsafe."""


def runner_root(task_type: Any, server_dir: str) -> Path:
    """Return the configured runner directory, never a task-output directory."""
    source_root = Path(__file__).resolve().parents[1]
    root = Path(task_type.runtime.root).resolve() if task_type.runtime.root else (source_root / task_type.runtime.definition).resolve().parent
    configured_runners = os.environ.get("RUNNERS_DIR")
    runners = (
        Path(configured_runners).resolve()
        if configured_runners
        else (Path(server_dir) / "docker" / "runners").resolve()
        if server_dir
        else (source_root / "docker" / "runners").resolve()
    )
    if not root.is_relative_to(runners):
        raise ResultContractError("Runner assets must live under docker/runners")
    return root


def contract_directory(family_root: str | Path, task_dir: str) -> Path:
    """The one directory that owns a Task's result contract.

    ``family_root`` is the family directory and ``task_dir`` the owning Task's
    manifest directory relative to it (empty when the family declares the Task
    at its own root).  The family's own directory answers only when the Task
    ships no contract of its own, so a Task can never take its logical files
    from one directory and its Storyboard from another.

    This is the single precedence rule: ``contract_dir`` resolves the family
    root to reach it, and a caller that already holds the family directory --
    the live-test validation identity -- uses it directly rather than
    re-deriving the rule.
    """
    root = Path(family_root)
    if not task_dir:
        return root
    if Path(task_dir).is_absolute() or any(part in {"", ".", ".."} for part in task_dir.split("/")):
        raise ResultContractError("Task result contract must live beneath its runner family")
    directory = (root / task_dir).resolve()
    if not directory.is_dir() or not directory.is_relative_to(root.resolve()):
        raise ResultContractError("Task result contract must live beneath its runner family")
    if (directory / "expected_files.yaml").is_file():
        return directory
    if (directory / "storyboard").is_dir():
        raise ResultContractError("A Task Storyboard needs its own expected_files.yaml")
    return root


def contract_dir(task_type: Any, server_dir: str) -> Path:
    """The contract directory of one discovered Task."""
    return contract_directory(runner_root(task_type, server_dir), str(getattr(task_type, "task_dir", "") or ""))


def _safe_relative(value: Any) -> str:
    """Validate a runner-controlled relative path."""
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise ResultContractError("Result paths must be non-empty relative paths")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ResultContractError("Result paths must not escape their runner")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a small runner-owned YAML declaration."""
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ResultContractError(f"Could not read {path.name}") from exc
    if not isinstance(value, dict):
        raise ResultContractError(f"{path.name} must be a mapping")
    return value


def load_expected_file_tree(path: str | Path) -> dict[str, dict[str, Any]]:
    """Parse one logical-file contract."""
    path = Path(path)
    if not path.is_file():
        return {}
    raw = _load_yaml(path)
    if set(raw) != {"result"} or not isinstance(raw["result"], dict) or set(raw["result"]) != {"files"}:
        raise ResultContractError("expected_files.yaml must contain result.files")
    files = raw["result"]["files"]
    if not isinstance(files, dict):
        raise ResultContractError("result.files must be a mapping")
    parsed: dict[str, dict[str, Any]] = {}
    for logical_id, entry in files.items():
        if not isinstance(logical_id, str) or not _LOGICAL_FILE_ID.fullmatch(logical_id) or not isinstance(entry, dict):
            raise ResultContractError("Invalid logical result file")
        if set(entry) - {"path", "pattern", "required", "type", "cardinality", "role"}:
            raise ResultContractError(f"Unknown fields for result file {logical_id}")
        selector = entry.get("path", entry.get("pattern"))
        if ("path" in entry) == ("pattern" in entry) or not _safe_relative(selector):
            raise ResultContractError(f"Result file {logical_id} needs exactly one path or pattern")
        cardinality = entry.get("cardinality", "one")
        if cardinality not in {"one", "many"} or not isinstance(entry.get("required"), bool):
            raise ResultContractError(f"Result file {logical_id} has invalid cardinality or required")
        # The value is hashed by the membership test below, so a YAML list or
        # mapping would raise TypeError instead of the contract error callers
        # catch; require a string first.
        if "role" in entry and (not isinstance(entry["role"], str) or entry["role"] not in _RESULT_FILE_ROLES):
            raise ResultContractError(
                f"Result file {logical_id} role must be one of {', '.join(sorted(_RESULT_FILE_ROLES))}"
            )
        parsed[logical_id] = {**entry, "cardinality": cardinality}
    return parsed


def expected_file_tree(task_type: Any, server_dir: str) -> dict[str, dict[str, Any]]:
    """Load the small logical-file contract owned by one Task's runner family."""
    return load_expected_file_tree(contract_dir(task_type, server_dir) / "expected_files.yaml")


def is_server_record(path: str) -> bool:
    """True for the input snapshot and execution records the server owns."""
    return path.startswith(("debug/", "execution/", "log/"))


def resolve_expected_files(
    tree: dict[str, dict[str, Any]], artifacts: list[dict[str, Any]]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[str]]:
    """Resolve only manifest-published regular files into logical identities."""
    by_path = {item["path"]: item for item in artifacts}
    resolved: dict[str, list[dict[str, Any]]] = {}
    checks: list[dict[str, Any]] = []
    problems: list[str] = []
    for logical_id, definition in tree.items():
        selector = definition.get("path") or definition["pattern"]
        # A scientific selector must not claim the input snapshot or an
        # execution record just because a basename happens to match: an upload
        # named ``3fap_model.pdb`` would otherwise turn ``*_model.pdb`` into
        # "expected one file, found 2". Entries that declare themselves
        # provenance or diagnostic still address those server-owned paths.
        record_eligible = definition.get("role") in {"provenance", "diagnostic"}
        matches = [
            {
                **by_path[path],
                "logical_type": definition.get("type") or by_path[path].get("preview"),
                "cardinality": definition["cardinality"],
            }
            for path in sorted(by_path)
            if fnmatchcase(path, selector)
            and by_path[path]["size"] > 0
            and (record_eligible or not is_server_record(path))
        ]
        if definition["cardinality"] == "one" and len(matches) > 1:
            problems.append(f"{logical_id}: expected one file, found {len(matches)}")
            matches = matches[:1]
        if len(matches) > 500:
            problems.append(f"{logical_id}: matched more than 500 files")
            matches = matches[:500]
        if definition["required"] and not matches:
            problems.append(f"{logical_id}: required output is missing or empty")
        resolved[logical_id] = matches
        checks.append(
            {
                "file_id": logical_id,
                "required": definition["required"],
                "matched": len(matches),
                "status": "passed" if matches or not definition["required"] else "failed",
            }
        )
    return resolved, checks, problems


def declared_file_roles(tree: dict[str, dict[str, Any]], paths: list[str]) -> dict[str, str]:
    """Map each published path to the role its logical file declares.

    The runner owns this knowledge in ``expected_files.yaml``; the server only
    carries it into role resolution.  ``paths`` are the artifact paths already
    published for this task.  A selector is either an exact ``path:`` — matched
    literally, never as a glob — or a ``pattern:``, matched with the same
    ``fnmatchcase`` rule ``resolve_expected_files`` uses, so both spellings
    resolve against the same published set the logical file resolves against.
    """
    roles: dict[str, str] = {}
    by_path = set(paths)
    for definition in tree.values():
        declared = definition.get("role")
        if not declared:
            continue
        if "path" in definition:
            if definition["path"] in by_path:
                roles[definition["path"]] = declared
            continue
        selector = definition["pattern"]
        for path in paths:
            if fnmatchcase(path, selector):
                roles[path] = declared
    return roles


def declared_result_contracts(family_root: str | Path, task_dirs: dict[str, str]) -> dict[str, Any]:
    """The logical-output contract each owner of a family declares.

    ``task_dirs`` maps each Task id the family declares to that Task's manifest
    directory relative to ``family_root``.  A family whose Tasks all resolve to
    one logical-output contract records that one contract -- the shape every
    family-scoped family had before Task-scoped contracts existed, and the shape
    a family declaring no tree at all still has -- so a family that adopts no
    Task-scoped contract keeps an identical record and its live-test receipt
    stays current.  Once Tasks differ, each one records its own, because from
    then on each Task's accepted outputs are decided by its own declaration.

    "One contract" is decided by the resolved trees, not by where they are
    spelled: the owners are compared with *each other*, and the record is the
    common tree whenever they agree -- whether it sits at the family root or in
    each owner's own directory.  Comparing each owner against the family-root
    position instead answers a different question: after the documented
    ``git mv`` of a single-Task family such as ``example`` the root holds no
    tree at all, so one unchanged contract would be recorded under its task id,
    changing the live-test configuration digest for a move no Runner can
    observe.
    """
    root = Path(family_root)
    shared = load_expected_file_tree(root / "expected_files.yaml")
    resolved = {
        task_id: load_expected_file_tree(contract_directory(root, task_dir) / "expected_files.yaml")
        for task_id, task_dir in sorted(task_dirs.items())
    }
    owners = list(resolved.values())
    common = owners[0] if owners else shared
    return common if all(tree == common for tree in owners) else resolved


def storyboard_declaration(task_type: Any, server_dir: str, file_ids: set[str]) -> dict[str, Any] | None:
    """Read a trusted, local runner declaration; never discover task output code."""
    path = contract_dir(task_type, server_dir) / "storyboard" / "storyboard.yaml"
    if not path.is_file():
        return None
    raw = _load_yaml(path)
    if set(raw) != {"identifier", "entrypoint", "requires", "optional"}:
        raise ResultContractError("storyboard.yaml has unknown or missing fields")
    identifier = raw["identifier"]
    entrypoint = raw["entrypoint"]
    if isinstance(entrypoint, str) and entrypoint.startswith("./"):
        entrypoint = entrypoint[2:]
    entrypoint = _safe_relative(entrypoint)
    if not isinstance(identifier, str) or not identifier.replace("-", "").isalnum():
        raise ResultContractError("Storyboard identifier is invalid")
    asset = (path.parent / entrypoint).resolve()
    if not asset.is_file() or not asset.is_relative_to(path.parent.resolve()) or asset.suffix != ".js":
        raise ResultContractError("Storyboard entrypoint must be a local JavaScript asset")
    requires, optional = raw["requires"], raw["optional"]
    if not all(
        isinstance(items, list) and all(isinstance(item, str) for item in items) for items in (requires, optional)
    ):
        raise ResultContractError("Storyboard file references must be lists")
    if set(requires) & set(optional) or not set(requires + optional).issubset(file_ids):
        raise ResultContractError("Storyboard references unknown logical files")
    return {"identifier": identifier, "entrypoint": entrypoint, "requires": requires, "optional": optional}


def storyboard_asset_root(task_type: Any, server_dir: str) -> Path:
    """The directory the Storyboard route serves from.

    It is the ``storyboard`` directory inside the very contract directory
    ``storyboard_declaration`` read the declaration from, so the module the
    Server serves is the module it validated, not a second resolution that
    could name a different file.
    """
    return contract_dir(task_type, server_dir) / "storyboard"


__all__ = [
    "ResultContractError",
    "contract_dir",
    "contract_directory",
    "declared_file_roles",
    "declared_result_contracts",
    "is_server_record",
    "expected_file_tree",
    "load_expected_file_tree",
    "resolve_expected_files",
    "runner_root",
    "storyboard_asset_root",
    "storyboard_declaration",
]
