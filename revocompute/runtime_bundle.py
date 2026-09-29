# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Immutable, content-addressed Runtime Bundles for Runner execution.

A Runner SIF describes an execution *environment*.  REvoCompute-owned
executable code — shared runtime helpers and family adapters — is delivered
instead as a Runtime Bundle: a read-only snapshot of the declared sources,
identified by the content of exactly those sources.  Build the environment;
mount the orchestration.

Identity rules (see ``TODO.md`` §6):

- only the paths a family declares participate in that family's digest;
- an executable bit is part of identity, timestamps and ownership are not;
- the digest is reproducible across machines, umasks and deployments;
- the bundle is materialized read-only and never mutated afterwards.

Stdlib only: this module is imported by the server worker, which does not carry
the runner tree's dependencies.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

#: Reserved in-container root for every Runtime Bundle.  One fixed namespace,
#: never user-configurable, never a per-family mount destination.
RUNTIME_MOUNT_TARGET = "/opt/revocompute/runtime"

#: Directory name for one materialized snapshot: ``sha256-<hex>``.
_BUNDLE_PREFIX = "sha256-"
_INDEX_NAME = "index.json"

_DIR_MODE = 0o555
_FILE_MODE = 0o444
_EXEC_MODE = 0o555


class RuntimeBundleError(ValueError):
    """A runtime-overlay declaration is unsafe, invalid, or unavailable."""


@dataclass(frozen=True, slots=True)
class OverlayEntry:
    """One regular file in a runtime overlay, with its identity-bearing mode."""

    relative: str  # normalized POSIX path relative to the runner tree root
    path: Path  # absolute source path
    executable: bool


def normalize_overlay_paths(declared: Iterable[str]) -> tuple[str, ...]:
    """Validate and normalize a ``runtime_overlay`` declaration.

    Rejects absolute paths, backslashes, empty/``.``/``..`` segments, and
    duplicates after normalization — an ambiguous spelling is an ambiguous
    digest, so it is refused rather than resolved.  Also rejects a declaration
    that contains another: ``a`` and ``a/b`` cannot both be snapshotted, because
    one is a file and the other a directory that contains it.
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in declared:
        # A trailing slash only says "directory" — it carries no identity, so it
        # normalizes away rather than rejecting an otherwise safe declaration.
        value = raw.rstrip("/") if isinstance(raw, str) else ""
        if not value or "\\" in value or value.startswith("/"):
            raise RuntimeBundleError(f"Runtime overlay path must be a relative POSIX path: {raw!r}")
        if any(part in {"", ".", ".."} for part in value.split("/")):
            raise RuntimeBundleError(f"Runtime overlay path contains an unsafe segment: {raw!r}")
        if value in seen:
            raise RuntimeBundleError(f"Duplicate runtime overlay path: {value!r}")
        for other in normalized:
            if value.startswith(other + "/") or other.startswith(value + "/"):
                raise RuntimeBundleError(f"Runtime overlay paths collide: {other!r} contains {value!r}")
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)


def overlay_build_overlap(declared: Iterable[str], build_inputs: Iterable[str]) -> tuple[str, ...]:
    """Build inputs a runtime overlay also delivers.

    A path is in both identities if it is declared directly *or* sits inside a
    declared directory: ``runtime_overlay: [family/]`` already ships
    ``family/requirements.lock``, so listing that lock as a build input would
    make one file whose change means both "rebuild the SIF" and "re-validate
    without rebuilding".  Containment, not string equality, is what decides.
    """
    overlay = normalize_overlay_paths(declared)
    return tuple(
        sorted(
            build_input
            for build_input in build_inputs
            if isinstance(build_input, str)
            and any(build_input == path or build_input.startswith(path + "/") for path in overlay)
        )
    )


def _resolve_source(runner_root: Path, relative: str) -> Path:
    """Resolve one declared source beneath ``runner_root`` without following links."""
    root = Path(runner_root).resolve()
    candidate = root / relative
    if candidate.is_symlink():
        raise RuntimeBundleError(f"Runtime overlay source must not be a symlink: {relative!r}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise RuntimeBundleError(f"Runtime overlay source escapes the runner tree: {relative!r}")
    try:
        mode = os.lstat(resolved).st_mode
    except OSError as exc:
        raise RuntimeBundleError(f"Runtime overlay source is unavailable: {relative!r}") from exc
    if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise RuntimeBundleError(f"Runtime overlay source must be a file or directory: {relative!r}")
    return resolved


def _walk_declaration(root: Path, relative: str) -> list[tuple[str, Path]]:
    """Every regular file a declaration names, as (relative, resolved) pairs.

    Symlinks and other non-regular objects anywhere beneath a declared
    directory are refused rather than followed, so a declaration can never
    reach outside the runner tree.
    """
    source = _resolve_source(root, relative)
    if stat.S_ISREG(os.lstat(source).st_mode):
        return [(relative, source)]
    candidates: list[tuple[str, Path]] = []
    for directory, dirnames, filenames in os.walk(source, followlinks=False):
        dirnames.sort()
        filenames.sort()
        for name in dirnames + filenames:
            child = Path(directory) / name
            child_mode = os.lstat(child).st_mode
            if stat.S_ISLNK(child_mode):
                raise RuntimeBundleError(f"Runtime overlay source must not contain a symlink: {name!r}")
            if not (stat.S_ISREG(child_mode) or stat.S_ISDIR(child_mode)):
                raise RuntimeBundleError(
                    f"Runtime overlay source contains an unsupported filesystem object: {name!r}"
                )
            if stat.S_ISREG(child_mode):
                inner = child.relative_to(root).as_posix()
                candidates.append((inner, child.resolve()))
    return candidates


def collect_overlay_entries(runner_root: str | os.PathLike[str], declared: Iterable[str]) -> tuple[OverlayEntry, ...]:
    """Enumerate a declaration into its sorted, identity-bearing file set."""
    root = Path(runner_root).resolve()
    entries: list[OverlayEntry] = []
    normalized = normalize_overlay_paths(declared)
    if not normalized:
        # An empty overlay is a family with no repository-owned runtime code —
        # a legitimate state, not an error.
        return ()
    for relative in normalized:
        for inner, path in _walk_declaration(root, relative):
            entries.append(OverlayEntry(inner, path, bool(os.stat(path).st_mode & 0o111)))
    entries.sort(key=lambda entry: entry.relative)
    if not entries:
        raise RuntimeBundleError("Runtime overlay declares no files")
    return tuple(entries)


#: Build byproducts that are not part of a declaration's identity.  A ``.pyc``
#: embeds its machine-local source mtime and interpreter version, so hashing one
#: would make the digest differ between two checkouts of the same revision — and
#: change under a running deployment whenever Python imports a helper.
_IGNORED_DIRS = {"__pycache__"}


def _hashable(entries: Iterable[OverlayEntry]) -> tuple[OverlayEntry, ...]:
    return tuple(
        entry for entry in entries if not (_IGNORED_DIRS & set(Path(entry.relative).parts))
    )


def _manifest_json(manifest: list[dict[str, str]]) -> str:
    return json.dumps(
        {"version": 1, "files": manifest}, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )


def _manifest_digest(manifest: list[dict[str, str]]) -> str:
    return f"sha256:{hashlib.sha256(_manifest_json(manifest).encode()).hexdigest()}"


def _entry_manifest(relative: str, executable: bool, sha256: str) -> dict[str, str]:
    return {"path": relative, "mode": "exec" if executable else "file", "sha256": sha256}


def _walk_stored(directory: Path) -> list[tuple[str, Path]]:
    """Every regular file beneath a stored bundle, refusing anything else.

    Materialization creates only one shape — directories containing regular
    files — so an entry that is neither means the tree was not produced by
    materialization and no longer speaks for its digest.  Two of those shapes
    are also actively dangerous: ``os.walk`` neither descends into nor lists a
    *directory* symlink, so a linked-in tree would be invisible to the digest
    while still reachable through the bundle path; and hashing a FIFO or device
    node could block or read from somewhere no file was ever written.  Every
    entry is therefore ``lstat``-ed and admitted only as a directory or a
    regular file.
    """
    found: list[tuple[str, Path]] = []
    for current, dirnames, filenames in os.walk(directory):
        for name in dirnames + filenames:
            child = Path(current) / name
            mode = os.lstat(child).st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise RuntimeBundleError(
                    f"Stored runtime bundle must contain only files and directories: {name!r}"
                )
        for name in filenames:
            path = Path(current) / name
            found.append((path.relative_to(directory).as_posix(), path))
    return found


def _digest_of(entries: tuple[OverlayEntry, ...]) -> str:
    """Content digest of an enumerated declaration.

    Hashes the normalized path, the file contents, and the executable bit.
    mtime, uid, gid and umask never participate, so two checkouts of the same
    revision on two machines agree.
    """
    return _manifest_digest(
        [_entry_manifest(entry.relative, entry.executable, _file_digest(entry.path)) for entry in entries]
    )


def verify_bundle(directory: str | os.PathLike[str], digest: str) -> bool:
    """Whether the bytes under ``directory`` still hash to ``digest``.

    A name is not identity: a bundle whose tree was partially removed, or whose
    files were replaced, still carries the digest it was named for.  Only the
    object types materialization creates are accepted, so a symlink or other
    unexpected entry fails the check rather than hiding from it.  Anything about
    to execute a pinned bundle — a launch, a submission — confirms this first, so
    a task never runs bytes that disagree with its own pin.
    """
    root = Path(directory)
    try:
        # Sorted by relative path, exactly as a declaration enumerates: the
        # manifest is a list, so walk order would change the digest.
        entries = _hashable(
            tuple(
                OverlayEntry(relative, path, bool(path.stat().st_mode & 0o111))
                for relative, path in sorted(_walk_stored(root))
            )
        )
        return _digest_of(entries) == digest
    except (OSError, RuntimeBundleError):
        return False


def overlay_digest(runner_root: str | os.PathLike[str], declared: Iterable[str]) -> str:
    """Content digest of exactly the declared sources."""
    return _digest_of(_hashable(collect_overlay_entries(runner_root, declared)))


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_directory(store_root: str | os.PathLike[str], digest: str) -> Path:
    """The content-addressed directory for one digest.  The digest is identity;
    the path is a derived, disposable implementation detail."""
    hexdigest = digest.split(":", 1)[1] if isinstance(digest, str) and ":" in digest else ""
    if len(hexdigest) != 64 or any(character not in "0123456789abcdef" for character in hexdigest):
        raise RuntimeBundleError(f"Invalid runtime bundle digest: {digest!r}")
    return Path(store_root) / f"{_BUNDLE_PREFIX}{hexdigest}"


def materialize(
    runner_root: str | os.PathLike[str],
    declared: Iterable[str],
    store_root: str | os.PathLike[str],
) -> tuple[str, Path]:
    """Snapshot a declaration into the store, returning ``(digest, path)``.

    Idempotent: an already-materialized digest is returned untouched, because
    an existing directory with that digest is by definition the same content.

    The published bytes are hashed as they are written, and must hash to the
    same manifest as the enumerated source, so a directory named ``sha256-H``
    always contains content hashing to H — a source edited mid-copy fails the
    materialization instead of publishing a name that lies.
    """
    entries = _hashable(collect_overlay_entries(runner_root, declared))
    if not entries:
        raise RuntimeBundleError("Runtime overlay declares no files")
    digest = _digest_of(entries)
    destination = bundle_directory(store_root, digest)
    if destination.is_dir():
        # Published bundles are immutable, so the name is normally enough.  It
        # is not enough after a partial removal (an interrupted prune, an
        # operator's rm) freed some of the tree without changing the name; the
        # existing receipt still names this digest, so re-publishing it blind
        # would put a task in front of a bundle that is missing files.
        if verify_bundle(destination, digest):
            return digest, destination
        _remove_tree(destination)
    store = Path(store_root)
    store.mkdir(parents=True, exist_ok=True)
    staging = store / f".staging-{os.getpid()}-{digest.split(':', 1)[1][:12]}"
    if staging.exists():
        _remove_tree(staging)
    staging.mkdir(mode=0o700)
    try:
        copied_manifest: list[dict[str, str]] = []
        for entry in entries:
            target = staging / entry.relative
            target.parent.mkdir(parents=True, exist_ok=True)
            written = hashlib.sha256()
            with entry.path.open("rb") as source, target.open("wb") as output:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    written.update(chunk)
                    output.write(chunk)
            copied_manifest.append(_entry_manifest(entry.relative, entry.executable, written.hexdigest()))
            os.chmod(target, _EXEC_MODE if entry.executable else _FILE_MODE)
        if _manifest_digest(copied_manifest) != digest:
            raise RuntimeBundleError(f"Runtime overlay changed while it was being materialized: {digest!r}")
        for directory, _dirnames, _filenames in os.walk(staging, topdown=False):
            os.chmod(directory, _DIR_MODE)
        try:
            os.rename(staging, destination)
        except OSError:
            if not destination.is_dir():  # a concurrent materialization won the race
                raise
            _remove_tree(staging)
    except BaseException:
        if staging.exists():
            _remove_tree(staging)
        raise
    return digest, destination


def _remove_tree(path: Path) -> None:
    """Remove a read-only tree: restoring owner-write on the way down."""
    for directory, dirnames, filenames in os.walk(path):
        os.chmod(directory, 0o700)
        for name in dirnames + filenames:
            try:
                os.chmod(Path(directory) / name, 0o600)
            except OSError:
                pass
    import shutil

    shutil.rmtree(path, ignore_errors=True)


# -- deployment index --------------------------------------------------------
#
# The index is the activation record: which family is currently bound to which
# immutable bundle.  Submission reads it (never the mutable tree) so a queued
# task cannot observe a bundle change, and GC reads it as its reference set.


def index_path(store_root: str | os.PathLike[str]) -> Path:
    return Path(store_root) / _INDEX_NAME


def load_index(store_root: str | os.PathLike[str]) -> dict[str, str]:
    """The published ``family -> bundle digest`` binding.

    Only the digest is stored: the directory is derived from it, so a second
    spelling of the same fact could only ever disagree with the first.
    """
    try:
        raw = json.loads(index_path(store_root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, Mapping):
        return {}
    return {
        family: str(digest)
        for family, digest in raw.items()
        if isinstance(family, str) and isinstance(digest, str) and digest
    }


def write_index(store_root: str | os.PathLike[str], index: Mapping[str, str]) -> None:
    """Atomically publish the family → bundle binding."""
    payload = {family: digest for family, digest in sorted(index.items())}
    destination = index_path(store_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{_INDEX_NAME}.{os.getpid()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o444)
    os.replace(temporary, destination)


def index_digests(store_root: str | os.PathLike[str]) -> set[str]:
    """Every digest the published binding currently references."""
    return set(load_index(store_root).values())


def resolve_pinned(store_root: str | os.PathLike[str], digest: Any) -> Path | None:
    """Resolve a task's pinned bundle directory, failing closed on any mismatch.

    The pinned digest and the bytes on disk must agree; a bundle that was
    pruned, replaced, or partially removed is a hard error, never a silent
    fallback to ``current`` and never a launch of bytes the pin does not name.
    """
    if not isinstance(digest, str) or not digest:
        return None
    try:
        directory = bundle_directory(store_root, digest)
    except RuntimeBundleError:
        return None
    # Containment is proven by construction: ``bundle_directory`` joins the
    # caller's store with a name derived from a validated hex digest, so no
    # ``..`` can appear.  A resolved comparison here would reject a store whose
    # own ancestors contain a symlink — a legitimate deployment layout — while
    # adding no safety, because the path is not attacker-chosen.
    if not directory.is_dir() or not verify_bundle(directory, digest):
        return None
    return directory


def resolve_for_submission(
    store_root: str | os.PathLike[str],
    index: Mapping[str, str],
    family: str,
    *,
    declares_overlay: bool,
    digest: str | None = None,
) -> str | None:
    """Resolve the bundle digest a *new* task for ``family`` must pin.

    ``declares_overlay`` is the family's own declaration, read from its owning
    manifest.  It is required because the index cannot distinguish "no overlay"
    from "overlay whose binding was never published": an absent or unreadable
    index yields the same empty mapping for both, and treating the second as the
    first is exactly the fail-open case where a task is accepted with no bundle
    and dies at launch with its entrypoint unmounted.

    ``digest`` overrides the published binding for candidate validation: a live
    test must exercise the exact snapshot it just materialized, which is not yet
    eligible for new submissions.

    Returns ``None`` only when the family declares no overlay, so a task without
    a runtime overlay is exactly the task it was before this mechanism existed.
    A family that *does* declare one but has no resolvable snapshot raises.
    """
    chosen = digest if digest is not None else index.get(family)
    if chosen is None:
        if declares_overlay:
            raise RuntimeBundleError(
                f"Runner family {family!r} declares a runtime overlay but has no published bundle"
            )
        return None
    if resolve_pinned(store_root, chosen) is None:
        raise RuntimeBundleError(
            f"Runtime bundle {chosen!r} for {family!r} is unavailable in {store_root!r}"
        )
    return chosen


def garbage_collect(
    store_root: str | os.PathLike[str],
    referenced: Iterable[str],
    *,
    min_age_seconds: float = 0.0,
) -> list[str]:
    """Prune bundles no longer referenced by the active index.

    Conservative by construction: only the deployment-owned store is touched,
    only directories named as digest snapshots are candidates, a directory that
    no longer parses as a digest is left alone, and a bundle younger than the
    retention window is retained.  Callers pass every digest that is active,
    prepared, or pinned by a queued/running task, so an in-flight execution's
    code is never removed.
    """
    store = Path(store_root)
    keep = {digest for digest in referenced if isinstance(digest, str) and digest}
    removed: list[str] = []
    try:
        candidates = sorted(store.iterdir())
    except OSError:
        return removed
    now = time.time()
    for candidate in candidates:
        if not candidate.is_dir() or candidate.is_symlink():
            continue
        name = candidate.name
        if not name.startswith(_BUNDLE_PREFIX):
            continue
        digest = f"sha256:{name[len(_BUNDLE_PREFIX):]}"
        if digest in keep:
            continue
        if min_age_seconds > 0:
            try:
                # A bundle's own mtime is when it was materialized, which is the
                # only clock that matters for the retention window.
                if now - candidate.stat().st_mtime < min_age_seconds:
                    continue
            except OSError:
                continue
        _remove_tree(candidate)
        removed.append(digest)
    return removed


__all__ = [
    "RUNTIME_MOUNT_TARGET",
    "OverlayEntry",
    "RuntimeBundleError",
    "bundle_directory",
    "collect_overlay_entries",
    "garbage_collect",
    "index_path",
    "load_index",
    "materialize",
    "normalize_overlay_paths",
    "overlay_build_overlap",
    "overlay_digest",
    "resolve_pinned",
    "verify_bundle",
    "write_index",
]
