# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The deployment's own build identity and the canonical bounded changelog.

One base version is hand-edited, in ``pyproject.toml``; Python packaging
projects it as installed package metadata, so this module reads it back rather
than parsing a second source. Everything else about a build is immutable and
baked in at image build: ``REVOCOMPUTE_BUILD_GIT_SHA`` (a full 40-hex commit),
``REVOCOMPUTE_BUILD_TIME`` (ISO-8601 UTC), ``REVOCOMPUTE_BUILD_ID`` and
``REVOCOMPUTE_RELEASE_CHANNEL``. Nothing here reads a live git ref or the wall
clock per request.

The changelog is parsed server-side into structured plain text. No Markdown or
HTML is handed to the browser, and every dimension is bounded so a large or
hostile file cannot become an unbounded response.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path
from typing import Any

MAX_CHANGELOG_BYTES = 64 * 1024
MAX_SECTIONS = 50
MAX_CATEGORIES_PER_SECTION = 12
MAX_ITEMS_PER_CATEGORY = 200
MAX_ITEMS_TOTAL = 1000
MAX_ITEM_CHARS = 500

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_CHANNEL = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
# An opaque builder identifier: no slash, so a registry path or host name can
# never reach the browser through this field.
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SECTION = re.compile(r"^\[([^\]]+)\](?:\s+-\s+(\d{4}-\d{2}-\d{2}))?\s*$")
_ITEM = re.compile(r"^(?P<indent>\s*)[-*]\s+(?P<text>.+)$")
_INLINE_LINK = re.compile(r"!\[([^\]]*)\]\([^)]*\)|\[([^\]]*)\]\([^)]*\)")


def _package_directory() -> Path:
    return Path(__file__).resolve().parent


def _changelog_candidates() -> tuple[Path, ...]:
    package = _package_directory()
    return (
        # The repository root first: /app/server in the image, the source
        # checkout in development.
        package.parent / "CHANGELOG.md",
        # Installed data-files fallback for a wheel that is not beside its
        # source tree.
        Path(sys.prefix) / "share" / "revocompute" / "CHANGELOG.md",
        package.parent.parent / "CHANGELOG.md",
    )


def _pyproject_candidates() -> tuple[Path, ...]:
    package = _package_directory()
    return (package.parent / "pyproject.toml", package.parent.parent / "pyproject.toml")


def base_version() -> str:
    """The application's editable base SemVer.

    The builder's ``REVOCOMPUTE_BASE_VERSION`` (taken from pyproject at build
    time) wins, then the source ``pyproject.toml``, then installed package
    metadata. An editable development install can leave stale metadata behind,
    so the source tree is preferred over it.
    """
    configured = (os.environ.get("REVOCOMPUTE_BASE_VERSION") or "").strip()
    if configured:
        return configured
    source = _pyproject_version(required=False)
    if source:
        return source
    try:
        return distribution_version("revocompute")
    except PackageNotFoundError:
        raise RuntimeError(
            "The application base version is unavailable: "
            "REVOCOMPUTE_BASE_VERSION, pyproject.toml and package metadata are all missing"
        ) from None


def _pyproject_version(required: bool = True) -> str:
    """Read ``[project].version`` from the nearest source ``pyproject.toml``."""
    import tomllib

    for candidate in _pyproject_candidates():
        if not candidate.is_file():
            continue
        try:
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        value = data.get("project", {}).get("version")
        if isinstance(value, str) and value:
            return value
    if not required:
        return ""
    raise RuntimeError(
        "The application base version is unavailable: revocompute metadata and pyproject.toml are missing"
    )


def _utc_timestamp(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _release_channel(value: str | None) -> str:
    text = (value or "").strip().lower()
    return text if _CHANNEL.fullmatch(text) else "development"


def _optional_token(value: str | None) -> str | None:
    text = (value or "").strip()
    return text if _TOKEN.fullmatch(text) else None


def build_identity() -> dict[str, Any]:
    """The immutable build identity baked into this image."""
    raw_sha = (os.environ.get("REVOCOMPUTE_BUILD_GIT_SHA") or "").strip().lower()
    git_sha = raw_sha if _FULL_SHA.fullmatch(raw_sha) else None
    release_channel = _release_channel(os.environ.get("REVOCOMPUTE_RELEASE_CHANNEL"))
    base = base_version()
    return {
        "base_version": base,
        "app_version": base if release_channel == "release" else f"{base}+{git_sha[:7] if git_sha else 'unknown'}",
        "git_sha": git_sha,
        "revision_status": "verified" if git_sha else "unknown",
        "release_channel": release_channel,
        "built_at": _utc_timestamp(os.environ.get("REVOCOMPUTE_BUILD_TIME")),
        # The opaque builder identifier is meaningful only beside a verified
        # commit; without one it is null rather than a path or registry name.
        "build_id": _optional_token(os.environ.get("REVOCOMPUTE_BUILD_ID")) if git_sha else None,
    }


def _plain_text(value: str) -> str:
    """Flatten one changelog item to the plain text the browser receives."""
    text = _INLINE_LINK.sub(lambda match: match.group(1) or match.group(2) or "", value)
    text = text.replace("**", "").replace("`", "")
    text = " ".join(text.split())
    return text[: MAX_ITEM_CHARS - 1] + "…" if len(text) > MAX_ITEM_CHARS else text


def _section_kind(version: str) -> str:
    if version == "Unreleased":
        return "unreleased"
    return "development-snapshot" if "+" in version else "release"


def _valid_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def parse_changelog(text: str) -> dict[str, Any]:
    """Parse Keep a Changelog 1.0.0 Markdown into the bounded payload shape.

    Sections keep file order (reverse chronological by convention). A parse that
    reaches any bound stops adding and reports ``truncated`` rather than growing
    the response.
    """
    sections: list[dict[str, Any]] = []
    section: dict[str, Any] | None = None
    category: dict[str, Any] | None = None
    total_items = 0
    truncated = False

    def close_section() -> None:
        nonlocal section, category
        if section is not None:
            sections.append(section)
        section = None
        category = None

    for raw_line in text.splitlines():
        heading = re.match(r"^##\s+(?!#)(.*)$", raw_line)
        if heading:
            close_section()
            match = _SECTION.fullmatch(heading.group(1).strip())
            if match is None:
                # A non-version H2 (a template or preamble) is not a release.
                continue
            if len(sections) >= MAX_SECTIONS:
                truncated = True
                continue
            version = match.group(1).strip()
            section = {
                "version": version,
                "date": _valid_date(match.group(2)),
                "kind": _section_kind(version),
                "categories": [],
            }
            continue
        if section is None:
            continue
        category_heading = re.match(r"^###\s+(?!#)(.*)$", raw_line)
        if category_heading:
            if len(section["categories"]) >= MAX_CATEGORIES_PER_SECTION:
                truncated = True
                category = None
                continue
            category = {"name": category_heading.group(1).strip(), "items": []}
            section["categories"].append(category)
            continue
        if category is None:
            continue
        item = _ITEM.match(raw_line)
        if item is None:
            continue
        if len(category["items"]) >= MAX_ITEMS_PER_CATEGORY or total_items >= MAX_ITEMS_TOTAL:
            truncated = True
            continue
        text_value = _plain_text(item.group("text"))
        if not text_value:
            continue
        category["items"].append({"text": text_value, "depth": 1 if item.group("indent") else 0})
        total_items += 1
    close_section()
    return {"source_sha256": None, "truncated": truncated, "sections": sections}


def _read_bounded(path: Path) -> tuple[bytes, bool]:
    """Read at most the changelog byte bound, ending on a whole line."""
    with path.open("rb") as handle:
        content = handle.read(MAX_CHANGELOG_BYTES + 1)
    if len(content) <= MAX_CHANGELOG_BYTES:
        return content, False
    content = content[:MAX_CHANGELOG_BYTES]
    boundary = content.rfind(b"\n")
    return content[: boundary + 1] if boundary > 0 else content, True


def load_changelog() -> dict[str, Any]:
    """Project the canonical root ``CHANGELOG.md``, or an explicit empty payload."""
    for candidate in _changelog_candidates():
        if not candidate.is_file():
            continue
        try:
            content, truncated = _read_bounded(candidate)
        except OSError:
            continue
        payload = parse_changelog(content.decode("utf-8", errors="replace"))
        payload["source_sha256"] = hashlib.sha256(content).hexdigest()
        payload["truncated"] = payload["truncated"] or truncated
        return payload
    return {"source_sha256": None, "truncated": False, "sections": []}


def version_info() -> dict[str, Any]:
    """The complete authenticated version projection."""
    return {**build_identity(), "changelog": load_changelog()}
