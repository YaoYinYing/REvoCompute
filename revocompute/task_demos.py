# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Declared, deployment-controlled demo inputs for one Task.

A Demo is a supported, scientist-facing input preset for one TaskType: a small
redistributable fixture plus the named-role bindings and parameter values that
make it a working example.  It is *not* the operator/CI acceptance contract --
that lives in the family's ``test.yaml`` and ``tests/data`` -- and it is not a
Task: loading one fills a form, and nothing here creates, reserves, or
authorizes anything.

The whole declaration is bounded and declarative.  A demo directory sits beside
its Task (``<task>/demo/``), never at the family root and never discovered by
scanning, so the owning task directory is the only address that resolves one.
This module parses and validates that declaration; it never fetches a remote
dataset, never runs a demo script, and never assigns scientific meaning to a
path or a filename.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import stat as stat_module
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema import ValidationError as JSONSchemaValidationError

from revocompute.input_validators import validate_input_file, validate_logical_input
from revocompute.io_contracts import ROLE_ID_PATTERN

# Bounds every deployment-owned fixture is held to.  A demo is a public sample,
# so it is deliberately small: the corpus is redistributed in the repository and
# a scientific dataset (a real MSA, a structure with its ligands, or a trained
# weight file) belongs in the deployment's data plane, not in Git.
MAX_DEMOS_PER_TASK = 8
MAX_DEMO_FILES = 32
MAX_DEMO_FILE_BYTES = 4 * 1024 * 1024
MAX_DEMO_TOTAL_BYTES = 8 * 1024 * 1024

# One media type is a registered type and subtype, slash-separated.  The value
# is a transport label served with the bytes; the *scientific* gate is the
# owning role's accepted format, checked separately below.
_MEDIA_TYPE_PATTERN = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")

# A fixture is one deployment-owned regular file: not a symlink, not hard
# linked to a second name, and not writable by another user or carrying a
# set-id/sticky bit.  World- and group-*read* are the normal repository state.
_UNSAFE_FILE_MODE = stat_module.S_IWOTH | stat_module.S_ISUID | stat_module.S_ISGID | stat_module.S_ISVTX

# A demo must carry a real redistribution basis.  These spellings all mean "we
# do not actually have one", so accepting them would let an unredistributable
# fixture ship as an example; a family without a usable basis declares no demo
# rather than declaring one under a placeholder licence.
_NO_REDISTRIBUTION = frozenset(
    {"", "unknown", "proprietary", "none", "no-license", "unlicensed", "all-rights-reserved"}
)

_DEMO_KEYS = frozenset({"id", "title", "purpose", "context", "source", "license", "inputs", "parameters"})
_SOURCE_KEYS = frozenset({"name", "url"})
_LICENSE_KEYS = frozenset({"id", "name", "url"})
_FILE_KEYS = frozenset({"path", "sha256", "media_type"})


class DemoContractError(ValueError):
    """A Task's demo declaration is malformed, unsafe, or unredistributable."""


@dataclass(frozen=True)
class DemoFile:
    """One fixture file bound to a named Task input role."""

    role: str
    path: str
    sha256: str
    size: int
    media_type: str


@dataclass(frozen=True)
class TaskDemo:
    """One validated demo preset for a TaskType."""

    id: str
    title: str
    purpose: str
    source: str
    source_url: str
    license_id: str
    license_name: str
    license_url: str
    context: str = ""
    files: tuple[DemoFile, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)

    def files_for(self, role: str) -> tuple[DemoFile, ...]:
        return tuple(item for item in self.files if item.role == role)


def demo_root(task_type: Any) -> Path | None:
    """The one accepted location for a Task's demo declaration, or ``None``.

    This is the module's single dependency on the owning task directory, kept to
    one value so the Task-scoped layout has exactly one reader.  ``None`` means
    the Task is not task-scoped (it declares no directory of its own), and a
    Task that is not task-scoped has no demos: there is deliberately no
    family-level fallback and no scan, because a demo resolved by anything but
    its own Task's declared directory would be a second, unowned convention.
    """
    relative = str(getattr(task_type, "task_dir", "") or "")
    if not relative:
        return None
    if relative.startswith("/") or "\\" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise DemoContractError("A Task demo directory must be relative to the runner family")
    # The root is resolved once, here, so every consumer anchors on the directory
    # the declaration was actually read from.  A symbolic link anywhere in the
    # family path is therefore followed exactly once, when the root is
    # established, rather than being re-followed by a consumer that is deciding
    # whether a fixture is inside it.
    return (Path(str(task_type.runtime.root)) / relative / "demo").resolve()


def demo_manifest_path(task_type: Any) -> Path | None:
    """The declared manifest file for one Task, whether or not it exists."""
    root = demo_root(task_type)
    return None if root is None else root / "demos.yaml"


def load_task_demos(task_type: Any) -> tuple[TaskDemo, ...]:
    """Parse and fully validate one Task's demo declaration.

    Returns ``()`` when the Task declares no demo directory or no demos.  Every
    violation raises ``DemoContractError`` rather than being skipped: a caller
    presenting a demo is about to hand a scientist a supported input, so a
    half-validated fixture must not reach it.
    """
    declared = declared_demos(task_type)
    if declared is None:
        return ()
    root = _declaration_root(task_type)
    demos: list[TaskDemo] = []
    seen: set[str] = set()
    for entry in declared:
        demo = _parse_demo(entry, task_type=task_type, root=root)
        if demo.id in seen:
            raise DemoContractError(f"Duplicate demo identifier: {demo.id!r}")
        seen.add(demo.id)
        demos.append(demo)
    return tuple(demos)


def load_task_demo(task_type: Any, demo_id: str) -> TaskDemo | None:
    """Parse and validate the one demo a request names, or ``None``.

    The declaration is the same one ``load_task_demos`` reads and each demo is
    validated by the same ``_parse_demo``, so there is no second grammar here:
    the difference is that serving one fixture resolves only the demo that binds
    it instead of every demo the Task declares.  The asset route is anonymous, so
    re-validating an unrelated demo on each of up to ``MAX_DEMO_FILES`` requests
    would make one form fill cost a whole catalog's worth of reads.
    """
    declared = declared_demos(task_type)
    if declared is None:
        return None
    root = _declaration_root(task_type)
    entry = next((item for item in declared if isinstance(item, dict) and item.get("id") == demo_id), None)
    return None if entry is None else _parse_demo(entry, task_type=task_type, root=root)


def declared_demos(task_type: Any) -> list[Any] | None:
    """The raw demo list one Task's manifest declares, or ``None``.

    ``None`` means the Task declares no demo directory, no manifest, and so no
    demos.  The surrounding document shape is checked here, once, for every
    reader; each demo entry is then parsed by ``_parse_demo``.
    """
    manifest = demo_manifest_path(task_type)
    if manifest is None or not manifest.is_file():
        return None
    try:
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DemoContractError(f"Could not read {manifest.name}") from exc
    if not isinstance(raw, dict) or set(raw) != {"demos"}:
        raise DemoContractError("demos.yaml must declare exactly one top-level 'demos' list")
    declared = raw["demos"]
    if not isinstance(declared, list) or len(declared) > MAX_DEMOS_PER_TASK:
        raise DemoContractError(f"demos must be a list of at most {MAX_DEMOS_PER_TASK} demos")
    return declared


def _declaration_root(task_type: Any) -> Path:
    """The resolved directory a manifest was read from; its reader guarantees it exists."""
    root = demo_root(task_type)
    assert root is not None  # a manifest exists only under a declared Task directory
    return root


def _parse_demo(entry: Any, *, task_type: Any, root: Path) -> TaskDemo:
    if not isinstance(entry, dict):
        raise DemoContractError("Every demo must be a mapping")
    unknown = set(entry) - _DEMO_KEYS
    if unknown:
        raise DemoContractError(f"Demo contains unknown fields: {sorted(unknown)}")
    demo_id = entry.get("id")
    if not isinstance(demo_id, str) or not ROLE_ID_PATTERN.fullmatch(demo_id):
        raise DemoContractError("A demo needs a stable lowercase identifier")
    title = _required_text(entry, "title", demo_id)
    purpose = _required_text(entry, "purpose", demo_id)
    context = entry.get("context", "")
    if not isinstance(context, str):
        raise DemoContractError(f"Demo {demo_id!r} context must be text")
    source, source_url = _parse_source(entry.get("source"), demo_id)
    license_id, license_name, license_url = _parse_license(entry.get("license"), demo_id)
    files = _parse_inputs(entry.get("inputs"), task_type=task_type, root=root, demo_id=demo_id)
    parameters = _parse_parameters(entry.get("parameters", {}), task_type=task_type, demo_id=demo_id)
    return TaskDemo(
        id=demo_id,
        title=title,
        purpose=purpose,
        source=source,
        source_url=source_url,
        license_id=license_id,
        license_name=license_name,
        license_url=license_url,
        context=context,
        files=files,
        parameters=parameters,
    )


def _required_text(entry: dict[str, Any], key: str, demo_id: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DemoContractError(f"Demo {demo_id!r} needs a non-empty {key}")
    return value.strip()


def _parse_source(raw: Any, demo_id: str) -> tuple[str, str]:
    if not isinstance(raw, dict):
        raise DemoContractError(f"Demo {demo_id!r} must attribute its source")
    if set(raw) - _SOURCE_KEYS:
        raise DemoContractError(f"Demo {demo_id!r} source has unknown fields")
    name = raw.get("name")
    url = raw.get("url", "")
    if not isinstance(name, str) or not name.strip() or not isinstance(url, str):
        raise DemoContractError(f"Demo {demo_id!r} must name the source of its fixture")
    return name.strip(), url.strip()


def _parse_license(raw: Any, demo_id: str) -> tuple[str, str, str]:
    if not isinstance(raw, dict):
        raise DemoContractError(f"Demo {demo_id!r} must declare a licence or redistribution basis")
    if set(raw) - _LICENSE_KEYS:
        raise DemoContractError(f"Demo {demo_id!r} licence has unknown fields")
    identifier = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    url = str(raw.get("url") or "").strip()
    if identifier.lower() in _NO_REDISTRIBUTION or not name:
        raise DemoContractError(
            f"Demo {demo_id!r} cannot be redistributed; declare no demo instead of a placeholder licence"
        )
    return identifier, name, url


def _parse_inputs(raw: Any, *, task_type: Any, root: Path, demo_id: str) -> tuple[DemoFile, ...]:
    if not isinstance(raw, dict) or not raw:
        raise DemoContractError(f"Demo {demo_id!r} must bind at least one named input role")
    roles = {role.name: role for role in task_type.inputs}
    unknown = sorted(set(raw) - set(roles))
    if unknown:
        raise DemoContractError(f"Demo {demo_id!r} names unknown input roles: {unknown}")
    missing = sorted(role.name for role in task_type.inputs if role.minimum >= 1 and role.name not in raw)
    if missing:
        raise DemoContractError(f"Demo {demo_id!r} does not fill required input roles: {missing}")
    files: list[DemoFile] = []
    for role_name, entries in raw.items():
        role = roles[role_name]
        if not isinstance(entries, list) or not entries:
            raise DemoContractError(f"Demo {demo_id!r} role {role_name!r} must be a non-empty list of files")
        if not role.minimum <= len(entries) <= role.maximum:
            raise DemoContractError(
                f"Demo {demo_id!r} role {role_name!r} needs {role.minimum}..{role.maximum} file(s)"
            )
        for item in entries:
            files.append(_parse_file(item, role=role, root=root, demo_id=demo_id))
    if len(files) > MAX_DEMO_FILES:
        raise DemoContractError(f"Demo {demo_id!r} declares more than {MAX_DEMO_FILES} files")
    if sum(item.size for item in files) > MAX_DEMO_TOTAL_BYTES:
        raise DemoContractError(f"Demo {demo_id!r} exceeds the {MAX_DEMO_TOTAL_BYTES} byte fixture budget")
    paths = [item.path for item in files]
    if len(set(paths)) != len(paths):
        raise DemoContractError(f"Demo {demo_id!r} binds one path to two roles")
    return tuple(files)


def _parse_file(raw: Any, *, role: Any, root: Path, demo_id: str) -> DemoFile:
    if not isinstance(raw, dict) or set(raw) != _FILE_KEYS:
        raise DemoContractError(f"Demo {demo_id!r} files declare exactly path, sha256, and media_type")
    relative = raw["path"]
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith("/")
        or "\\" in relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise DemoContractError(f"Demo {demo_id!r} fixture paths must be non-empty relative paths")
    digest = raw["sha256"]
    if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
        raise DemoContractError(f"Demo {demo_id!r} fixture {relative!r} needs a lowercase sha256 digest")
    media_type = raw["media_type"]
    if not isinstance(media_type, str) or not _MEDIA_TYPE_PATTERN.fullmatch(media_type.lower()):
        raise DemoContractError(f"Demo {demo_id!r} fixture {relative!r} needs a type/subtype media type")
    target = root / relative
    _assert_regular_fixture(target, root=root, relative=relative, demo_id=demo_id)
    size = target.stat().st_size
    if size > MAX_DEMO_FILE_BYTES:
        raise DemoContractError(
            f"Demo {demo_id!r} fixture {relative!r} exceeds the {MAX_DEMO_FILE_BYTES} byte limit"
        )
    # The digest is verified here, once, at declaration time, over the bytes this
    # read returns.  The download route serves the declared pathname from the
    # contained root rather than the inode this check read, so it does not re-verify
    # the digest; the client that serves the fixture does, against the declaration's
    # own sha256 (frontend/src/features/create-task/demo.ts).  Replacing a fixture
    # between this read and a serve requires write access inside the demo root,
    # which the single-regular-file, unlinked-inode, world-unwritable, and
    # containment checks are what keep scarce.
    if _sha256_of(target) != digest:
        raise DemoContractError(f"Demo {demo_id!r} fixture {relative!r} does not match its declared digest")
    format_name = os.path.splitext(relative)[1].lower().removeprefix(".")
    if format_name not in role.formats:
        raise DemoContractError(
            f"Demo {demo_id!r} fixture {relative!r} is not a declared format of role {role.name!r}"
        )
    # The fixture is validated by the same Core parsers an uploaded file meets,
    # with the role's own logical type, so a demo can never be a working example
    # of an input the upload path would refuse.
    error = validate_input_file(str(target), relative, logical_type=role.type)
    if error is None:
        error = validate_logical_input(str(target), format_name, role.type)
    if error is not None:
        raise DemoContractError(f"Demo {demo_id!r} fixture {relative!r} is not a valid {role.type}: {error}")
    return DemoFile(role=role.name, path=relative, sha256=digest, size=size, media_type=media_type.lower())


def _assert_regular_fixture(target: Path, *, root: Path, relative: str, demo_id: str) -> None:
    """Refuse a fixture that is not one regular file inside its own demo root.

    Containment is decided on resolved paths rather than on the spelling of
    ``relative``: a path that looks relative and carries no ``..`` can still leave
    the demo directory through a symbolic *parent* component.  Resolving both
    sides and requiring the target to stay under the resolved root is what makes
    the declaration and the serve resolve the same directory, so this reader can
    never validate a file the download route would refuse - or, worse, serve a
    path outside the demo root while the declaration describes it as inside.

    Containment is not a guarantee that the bytes are unchanged between this read
    and a later serve: see ``_parse_file``, where the digest is verified once, at
    declaration time.

    A symbolic final component is refused outright, because the served bytes would
    be whatever that link points at, and a hard-linked, world-writable, or set-id
    inode could be replaced after validation; none of those can be a public
    fixture.
    """
    if not target.resolve().is_relative_to(root.resolve()):
        raise DemoContractError(
            f"Demo {demo_id!r} fixture {relative!r} must resolve inside its Task's demo directory"
        )
    try:
        if os.path.islink(target):
            raise DemoContractError(f"Demo {demo_id!r} fixture {relative!r} must not be a symbolic link")
        info = os.stat(target, follow_symlinks=False)
    except OSError as exc:
        raise DemoContractError(f"Demo {demo_id!r} fixture {relative!r} is missing") from exc
    if not stat_module.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & _UNSAFE_FILE_MODE:
        raise DemoContractError(
            f"Demo {demo_id!r} fixture {relative!r} must be a single regular, non-writable file"
        )


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_parameters(raw: Any, *, task_type: Any, demo_id: str) -> dict[str, Any]:
    """Validate a demo's parameters against the Task's own canonical schema.

    The owning ``task.yaml`` schema is the single parameter grammar, so a demo
    declares a preset in exactly the language the submission boundary accepts:
    an unknown key, a wrong type, or an out-of-range value is refused here, not
    deferred to a preflight the scientist has to read.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise DemoContractError(f"Demo {demo_id!r} parameters must be a mapping")
    try:
        Draft202012Validator(task_type.schema, format_checker=FormatChecker()).validate(raw)
    except JSONSchemaValidationError as exc:
        raise DemoContractError(
            f"Demo {demo_id!r} parameters do not satisfy the Task contract: {exc.message}"
        ) from exc
    return dict(raw)


def resolve_demo_file(demo: TaskDemo, requested: str) -> DemoFile | None:
    """The one declared fixture a request path names, or ``None``.

    A demo file is served by allowlist membership rather than by resolving the
    request, so no request can name a path the validated declaration did not
    already contain.
    """
    normalized = requested.replace("\\", "/").strip("/")
    return next((item for item in demo.files if item.path == normalized), None)
