# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""One editable version source, validated mirrors, and the release tag gate.

``pyproject.toml [project].version`` is the only SemVer a maintainer edits.
The frontend package metadata, the frontend lockfile and the OpenAPI
``info.version`` are mirrors written only by ``sync`` and rejected by ``check``.
The release commands validate an exact tested commit and the dated changelog
section; they never commit, tag, push, publish or deploy.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from datetime import date, datetime, timezone
from pathlib import Path

SEMVER = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
PRODUCT_TAG = re.compile(
    r"^v(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)$"
)
_OPENAPI_INFO = re.compile(r'"info"\s*:\s*\{')
_OPENAPI_VERSION = re.compile(r'"version"\s*:\s*"([^"]*)"')
# uv's lock records the editable project as one package block. Only the version
# value inside that block is ever changed; uv itself is never run.
_UV_PACKAGE = re.compile(r'(?ms)^\[\[package\]\]\nname = "revocompute"\nversion = "([^"]*)"')

PYPROJECT = "pyproject.toml"
PACKAGE_JSON = "frontend/package.json"
PACKAGE_LOCK = "frontend/package-lock.json"
OPENAPI = "revocompute/static/openapi.json"
UV_LOCK = "uv.lock"
CHANGELOG = "CHANGELOG.md"


class ReleaseError(Exception):
    """A release command refused or a repository invariant is broken."""


def find_root(start: Path | None = None) -> Path:
    """The repository root: the nearest ancestor declaring this project."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        path = candidate / PYPROJECT
        if not path.is_file():
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("project", {}).get("name") == "revocompute":
            return candidate
    raise ReleaseError("Could not locate the revocompute repository root from the current directory")


def canonical_version(root: Path) -> str:
    """The one editable base version."""
    path = root / PYPROJECT
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReleaseError(f"{PYPROJECT}: cannot read project metadata ({error})") from error
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ReleaseError(f"{PYPROJECT}: [project].version is missing")
    return version


def _read_json(root: Path, relative: str) -> dict:
    path = root / relative
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReleaseError(f"{relative}: cannot read ({error})") from error
    if not isinstance(data, dict):
        raise ReleaseError(f"{relative}: expected a JSON object")
    return data


def _openapi_version(root: Path) -> str:
    data = _read_json(root, OPENAPI)
    value = data.get("info", {}).get("version")
    if not isinstance(value, str) or not value:
        raise ReleaseError(f"{OPENAPI}: info.version is missing")
    return value


def _uv_lock_version(root: Path) -> str:
    path = root / UV_LOCK
    match = _UV_PACKAGE.search(path.read_text(encoding="utf-8")) if path.is_file() else None
    if match is None:
        raise ReleaseError(f"{UV_LOCK}: no [[package]] entry for revocompute")
    return match.group(1)


def check(root: Path) -> list[str]:
    """Return one line per repository invariant the mirrors violate."""
    try:
        version = canonical_version(root)
    except ReleaseError as error:
        return [str(error)]
    if not SEMVER.fullmatch(version):
        return [f"{PYPROJECT}: version {version!r} is not valid SemVer (MAJOR.MINOR.PATCH with optional prerelease)"]
    drifts: list[str] = []
    try:
        package = _read_json(root, PACKAGE_JSON).get("version")
        if package != version:
            drifts.append(f"{PACKAGE_JSON}: version {package!r} != {version!r}")
        lock = _read_json(root, PACKAGE_LOCK)
        if lock.get("version") != version:
            drifts.append(f"{PACKAGE_LOCK}: version {lock.get('version')!r} != {version!r}")
        locked_package = lock.get("packages", {}).get("", {}) if isinstance(lock.get("packages"), dict) else {}
        if locked_package.get("version") != version:
            drifts.append(f"{PACKAGE_LOCK}: packages[''].version {locked_package.get('version')!r} != {version!r}")
        openapi = _openapi_version(root)
        if openapi != version:
            drifts.append(f"{OPENAPI}: info.version {openapi!r} != {version!r}")
        uv_lock = _uv_lock_version(root)
        if uv_lock != version:
            drifts.append(f"{UV_LOCK}: revocompute version {uv_lock!r} != {version!r}")
    except ReleaseError as error:
        drifts.append(str(error))
    return drifts


def _write_pyproject_version(root: Path, version: str) -> bool:
    path = root / PYPROJECT
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    section = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped
            continue
        match = re.fullmatch(r'(?P<indent>\s*)version\s*=\s*"[^"]*"(?P<newline>\r?\n)?', line)
        if section == "[project]" and match:
            replacement = f'{match.group("indent")}version = "{version}"{match.group("newline") or ""}'
            if replacement == line:
                return False
            lines[index] = replacement
            path.write_text("".join(lines), encoding="utf-8")
            return True
    raise ReleaseError(f"{PYPROJECT}: no version entry inside [project]")


def _write_json_version(root: Path, relative: str, version: str, *, lock: bool) -> bool:
    path = root / relative
    data = _read_json(root, relative)
    if lock:
        data["version"] = version
        packages = data.get("packages")
        if not isinstance(packages, dict) or not isinstance(packages.get(""), dict):
            raise ReleaseError(f"{relative}: packages[''] is missing")
        packages[""]["version"] = version
    else:
        data["version"] = version
    rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if rendered == path.read_text(encoding="utf-8"):
        return False
    path.write_text(rendered, encoding="utf-8")
    return True


def _write_openapi_version(root: Path, version: str) -> bool:
    """Replace only ``info.version``, preserving every other byte."""
    path = root / OPENAPI
    text = path.read_text(encoding="utf-8")
    info = _OPENAPI_INFO.search(text)
    if info is None:
        raise ReleaseError(f"{OPENAPI}: no info object")
    match = _OPENAPI_VERSION.search(text, info.end())
    if match is None:
        raise ReleaseError(f"{OPENAPI}: no info.version")
    if match.group(1) == version:
        return False
    updated = text[: match.start(1)] + version + text[match.end(1):]
    path.write_text(updated, encoding="utf-8")
    return True


def _write_uv_lock_version(root: Path, version: str) -> bool:
    """Replace only the revocompute package's version in the lock."""
    path = root / UV_LOCK
    text = path.read_text(encoding="utf-8")
    match = _UV_PACKAGE.search(text)
    if match is None:
        raise ReleaseError(f"{UV_LOCK}: no [[package]] entry for revocompute")
    if match.group(1) == version:
        return False
    path.write_text(text[: match.start(1)] + version + text[match.end(1):], encoding="utf-8")
    return True


def sync(root: Path) -> list[str]:
    """Write every mirror from the canonical version; return changed paths."""
    version = canonical_version(root)
    if not SEMVER.fullmatch(version):
        raise ReleaseError(f"{PYPROJECT}: version {version!r} is not valid SemVer")
    changed: list[str] = []
    if _write_pyproject_version(root, version):
        changed.append(PYPROJECT)
    if _write_json_version(root, PACKAGE_JSON, version, lock=False):
        changed.append(PACKAGE_JSON)
    if _write_json_version(root, PACKAGE_LOCK, version, lock=True):
        changed.append(PACKAGE_LOCK)
    if _write_openapi_version(root, version):
        changed.append(OPENAPI)
    if _write_uv_lock_version(root, version):
        changed.append(UV_LOCK)
    return changed


def changelog_section_in_text(text: str, version: str, day: str | None = None) -> bool:
    """Whether the text holds a real calendar-dated section for one version.

    A heading-shaped date that cannot exist (for example 2026-13-45) is not a
    release date and is rejected, matching the prepare-release gate. ``day``
    narrows the match to one date when supplied.
    """
    pattern = re.compile(rf"(?m)^##\s+\[{re.escape(version)}\]\s+-\s+(\d{{4}}-\d{{2}}-\d{{2}})\s*$")
    for candidate in pattern.findall(text):
        try:
            date.fromisoformat(candidate)
        except ValueError:
            continue
        if day is None or candidate == day:
            return True
    return False


def changelog_section_days(root: Path, version: str) -> list[str]:
    """Every valid dated section for one version, in file order."""
    path = root / CHANGELOG
    if not path.is_file():
        return []
    pattern = re.compile(rf"(?m)^##\s+\[{re.escape(version)}\]\s+-\s+(\d{{4}}-\d{{2}}-\d{{2}})\s*$")
    days: list[str] = []
    for candidate in pattern.findall(path.read_text(encoding="utf-8")):
        try:
            date.fromisoformat(candidate)
        except ValueError:
            continue
        days.append(candidate)
    return days


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def _head(root: Path) -> str:
    result = _git(root, "rev-parse", "HEAD")
    sha = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ReleaseError("Could not resolve the repository HEAD commit")
    return sha


def prepare_release(root: Path, version: str, sha: str | None = None) -> list[str]:
    """Validate a release cut and update the version sources. Never commits."""
    if not SEMVER.fullmatch(version):
        raise ReleaseError(f"{version!r} is not valid SemVer")
    head = _head(root)
    tested = sha.lower() if sha else head
    if not re.fullmatch(r"[0-9a-f]{40}", tested):
        raise ReleaseError("--sha must be a full 40-character commit SHA")
    if head != tested:
        raise ReleaseError(f"HEAD {head} is not the tested commit {tested}")
    status = _git(root, "status", "--porcelain")
    if status.returncode:
        raise ReleaseError("Could not read the working tree status")
    if status.stdout.strip():
        raise ReleaseError("The working tree is dirty; commit or stash changes before preparing a release")
    tag = f"v{version}"
    if _git(root, "tag", "--list", tag).stdout.strip():
        raise ReleaseError(f"Tag {tag} already exists")
    today = datetime.now(timezone.utc).date().isoformat()
    if not any(day <= today for day in changelog_section_days(root, version)):
        raise ReleaseError(f"{CHANGELOG}: no dated section for {version} on or before {today}")
    changed = [PYPROJECT] if _write_pyproject_version(root, version) else []
    return changed + sync(root)


def _tagged_text(root: Path, commit: str, relative: str) -> str | None:
    result = _git(root, "show", f"{commit}:{relative}")
    return result.stdout if result.returncode == 0 else None


def _version_from_pyproject(text: str) -> str | None:
    try:
        value = tomllib.loads(text).get("project", {}).get("version")
    except ValueError:
        return None
    return value if isinstance(value, str) and value else None


def _resolve_commit(root: Path, value: str) -> str | None:
    """Resolve a revision (including an annotated tag object) to its commit."""
    result = _git(root, "rev-parse", f"{value}^{{commit}}")
    resolved = result.stdout.strip().lower()
    if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", resolved):
        return resolved
    fallback = value.strip().lower()
    return fallback if re.fullmatch(r"[0-9a-f]{40}", fallback) else None


def verify_tag(root: Path, tag: str, sha: str | None = None) -> list[str]:
    """Validate a product tag against the exact commit's own tree.

    The tag's commit, ``pyproject.toml`` and ``CHANGELOG.md`` are read from Git
    objects, never from the working tree, so a dirty checkout cannot make an
    invalid release look valid. Without ``--sha`` an existing tag validates
    itself, so running the gate from a later HEAD is not a mismatch. A
    prospective tag that does not exist yet may be checked by supplying
    ``--sha``; the local release step does that before the tag is created.
    """
    errors: list[str] = []
    match = PRODUCT_TAG.fullmatch(tag)
    if match is None:
        return [f"{tag!r} is not a product version tag vMAJOR.MINOR.PATCH (optional prerelease)"]
    version = match.group("version")
    existing = _git(root, "rev-list", "-n1", tag)
    tag_commit = existing.stdout.strip().lower()
    tag_exists = existing.returncode == 0 and bool(tag_commit)
    supplied = _resolve_commit(root, sha) if sha else None
    if sha and supplied is None:
        return ["--sha must resolve to a full 40-character commit SHA"]
    if tag_exists:
        target = tag_commit
        if supplied and supplied != tag_commit:
            errors.append(f"Tag {tag} points at {tag_commit}, not the supplied commit {supplied}")
    elif supplied:
        target = supplied
    else:
        return [f"Tag {tag} does not exist; supply --sha to validate the prospective commit"]
    pyproject_text = _tagged_text(root, target, PYPROJECT)
    if pyproject_text is None:
        errors.append(f"{PYPROJECT}: not readable at commit {target}")
    else:
        canonical = _version_from_pyproject(pyproject_text)
        if canonical is None:
            errors.append(f"{PYPROJECT}: [project].version is missing at commit {target}")
        elif canonical != version:
            errors.append(f"Tag version {version} != {PYPROJECT} version {canonical} at commit {target}")
    changelog_text = _tagged_text(root, target, CHANGELOG)
    if changelog_text is None or not changelog_section_in_text(changelog_text, version):
        errors.append(f"{CHANGELOG}: no dated section for version {version} with a YYYY-MM-DD date")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="revocompute-release", description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="repository root (default: discover from cwd)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="validate SemVer and mirror drift")
    commands.add_parser("sync", help="write every mirror from pyproject.toml")
    prepare = commands.add_parser("prepare-release", help="validate an exact tested commit and update version sources")
    prepare.add_argument("--version", required=True)
    prepare.add_argument("--sha", default=None)
    tag = commands.add_parser("verify-tag", help="validate a product release tag")
    tag.add_argument("--tag", required=True)
    tag.add_argument("--sha", default=None)
    args = parser.parse_args(argv)

    try:
        root = find_root(args.root)
        if args.command == "check":
            errors = check(root)
            for error in errors:
                print(error, file=sys.stderr)
            return 1 if errors else 0
        if args.command == "sync":
            for path in sync(root):
                print(f"Updated {path}")
            return 0
        if args.command == "prepare-release":
            for path in prepare_release(root, args.version, args.sha):
                print(f"Updated {path}")
            print("Version sources updated; nothing was committed, tagged, pushed or published.")
            print(
                "Before tagging: build with REVOCOMPUTE_RELEASE_CHANNEL=release, then run "
                f"'revocompute-release verify-tag --tag v{args.version} --sha <tested commit>'."
            )
            return 0
        errors = verify_tag(root, args.tag, args.sha)
        for error in errors:
            print(error, file=sys.stderr)
        return 1 if errors else 0
    except ReleaseError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
