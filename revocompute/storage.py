# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Authoritative immutable user-owned task storage resolution.

This module owns the one publication boundary the Server trusts: a Task result
directory is an untrusted filesystem namespace written by the runner's Unix
identity, so every byte a consumer serves is obtained through a verified
descriptor opened relative to the trusted result root -- never by re-resolving a
validated pathname, which is a statement about a name rather than about the file
the reader ends up holding.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

_STORAGE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,119}\Z")
_TASK_ID = re.compile(r"[a-fA-F0-9]{32}\Z")
_SHA256 = re.compile(r"[a-fA-F0-9]{64}\Z")


def path_is_within(base_dir: str, candidate: str) -> bool:
    """Return whether a path is lexically and symlink-resolved within base."""
    base_abs, target_abs = os.path.abspath(base_dir), os.path.abspath(candidate)
    try:
        if os.path.commonpath([base_abs, target_abs]) != base_abs:
            return False
    except ValueError:
        return False
    probe, tail = target_abs, []
    while probe and not os.path.lexists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        tail.append(os.path.basename(probe))
        probe = parent
    resolved = os.path.realpath(os.path.join(probe, *reversed(tail)))
    try:
        return os.path.commonpath([os.path.realpath(base_abs), resolved]) == os.path.realpath(base_abs)
    except ValueError:
        return False


def safe_join(base_dir: str, *parts: str) -> str:
    candidate = os.path.abspath(os.path.join(base_dir, *parts))
    if not path_is_within(base_dir, candidate):
        raise ValueError("path escapes configured storage root")
    return candidate


# Stream a published artifact in bounded chunks: artifacts are scientific files
# that can be gigabytes wide, so nothing here ever reads one wholly into memory.
_HASH_CHUNK_BYTES = 1024 * 1024

#: The one maximum serialized-manifest byte limit, shared by the writer that
#: anchors a manifest and the reader that serves it.  Two constants would be two
#: contracts, and a writer that can emit a manifest its own reader must reject
#: leaves a Task finished with a result no consumer can open.
MANIFEST_MAX_BYTES = 8 * 1024 * 1024


def manifest_byte_limit() -> int:
    """Return the one serialized-manifest byte ceiling writer and reader share.

    The single read site for the limit: the publication writer asks for the
    ceiling instead of restating it, so the two sides cannot drift into two
    contracts -- a writer that anchors a manifest the canonical reader classifies
    as unreadable would leave a finished Task no consumer can open.
    """
    return MANIFEST_MAX_BYTES


#: A component of a result-relative path.  The result tree is runner-writable
#: and a hostile name is not merely long: a newline or a NUL in a manifest entry
#: reaches HTTP headers, ZIP member names, and log lines.  A publisher that ever
#: writes one through would create a publication its own reader refuses, so both
#: sides judge a component with this expression.
_MANIFEST_PATH_COMPONENT = re.compile(r"[^\x00-\x1f\x7f/\\]{1,255}\Z")


def manifest_relative_parts(relative_path: str) -> tuple[str, ...] | None:
    """Split a manifest-relative artifact path into its components, or ``None``.

    The one path vocabulary every consumer shares: ``.``/``..``/empty/absolute
    components, backslashes, control characters, and overlong components are
    refused here rather than at each call site, so a path accepted by the reader
    is a path the writer could have published.
    """
    if not isinstance(relative_path, str) or not relative_path:
        return None
    parts = relative_path.split("/")
    if any(_MANIFEST_PATH_COMPONENT.fullmatch(part) is None or part in {".", ".."} for part in parts):
        return None
    return tuple(parts)


@dataclass(frozen=True, slots=True)
class _VerifiedFile:
    """One verified published file: the descriptor plus the digests of its bytes."""

    handle: Any
    digest: str
    size: int


class _ResultTreeWalker:
    """Enumerate and open files relative to one trusted, opened result root.

    The root descriptor is opened once with ``O_DIRECTORY|O_NOFOLLOW``; every
    walk and every open is relative to it.  A walk yields an opaque token that
    holds the *opened parent descriptor* the entry was enumerated from, so
    opening it later re-resolves only the entry's own name inside a directory
    whose identity was already checked -- an intermediate component replaced by
    a symlink after enumeration cannot redirect the open, because the open never
    mentions that component again.
    """

    def __init__(self, root: str):
        try:
            info = os.stat(root, follow_symlinks=False)
        except FileNotFoundError as exc:
            # No result tree at all: the ordinary "nothing was published" case,
            # not a refused publication.
            raise FileNotFoundError(f"result root does not exist: {root}") from exc
        except OSError as exc:
            raise ArtifactIdentityError(f"result root is unreadable: {root}") from exc
        if not stat.S_ISDIR(info.st_mode):
            raise ArtifactIdentityError(f"result root is not a directory: {root}")
        try:
            self._root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        except OSError as exc:
            raise ArtifactIdentityError(f"result root cannot be opened safely: {root}") from exc

    def __enter__(self) -> "_ResultTreeWalker":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._root_fd >= 0:
            os.close(self._root_fd)
            self._root_fd = -1

    def walk(self) -> Iterator[tuple[tuple[str, ...], int, str]]:
        """Yield ``(relative parts, parent descriptor, name)`` for every entry.

        Intermediate components are filesystem objects, not strings: a directory
        that cannot be opened as a directory is never descended into, so a
        symlinked or special component hides its contents instead of redirecting
        the walk outside the result tree.
        """
        yield from self._walk(self._root_fd, ())

    def _walk(self, directory_fd: int, prefix: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], int, str]]:
        try:
            names = sorted(os.listdir(directory_fd))
        except OSError:
            return
        for name in names:
            if _MANIFEST_PATH_COMPONENT.fullmatch(name) is None or name in {".", ".."}:
                continue
            path = (*prefix, name)
            try:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError:
                yield path, directory_fd, name
                continue
            # Only a real directory is descended into.  A symlink, a regular
            # file, and every special file are yielded as candidates instead, so
            # the publishability check refuses them by the same rule it applies
            # everywhere else -- and a component that is not a directory hides
            # its contents rather than redirecting the walk outside the root.
            if not stat.S_ISDIR(info.st_mode):
                yield path, directory_fd, name
                continue
            try:
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=directory_fd,
                )
            except OSError:
                # The component claimed to be a directory during enumeration and
                # could not be re-opened as one: it was swapped in between, so
                # fail closed and descend into nothing.
                yield path, directory_fd, name
                continue
            try:
                yield from self._walk(child, path)
            finally:
                os.close(child)

    @staticmethod
    def open_verified(
        directory_fd: int, name: str, *, max_bytes: int, expected: tuple[int, str] | None = None
    ) -> _VerifiedFile:
        """Open one enumerated entry as a verified private regular file.

        The one bounded-hash implementation in the system: the reader and the
        publication writer both consume it, so neither can drift into a second
        idea of what "the published bytes" are.  ``O_NOFOLLOW`` refuses a
        final-component symlink atomically at open time and the ``fstat`` runs on
        the *opened descriptor*, not on the name, so a regular single-linked file
        is the only thing the descriptor can be reading.  The size the descriptor
        reports is checked against *max_bytes* before any byte is read, and the
        hash loop is bounded by that same size, so an entry that grows underneath
        the hasher yields a size mismatch instead of an unbounded read.  With
        ``expected`` the bytes must also match the manifest entry's
        ``(size, sha256)``, which is why no caller needs a second open of the name.
        """
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), dir_fd=directory_fd)
        handle = os.fdopen(descriptor, "rb")
        try:
            status = os.fstat(handle.fileno())
            if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
                raise ArtifactIdentityError(f"not a private regular file: {name}")
            if status.st_size > max_bytes:
                raise ArtifactOversizedError(f"published file exceeds its bound: {name}")
            size, digest = _hash_bounded(handle, status.st_size)
            if size != status.st_size:
                raise ArtifactChangedError(f"published file changed while being read: {name}")
            if expected is not None:
                declared_size, declared_digest = expected
                if size != declared_size:
                    raise ArtifactIdentityError(f"published artifact does not match its declared size: {name}")
                if digest != declared_digest:
                    raise ArtifactIdentityError(f"published artifact does not match its declared digest: {name}")
            handle.seek(0)
            return _VerifiedFile(handle, digest, size)
        except BaseException:
            handle.close()
            raise

    def open_published_file(
        self, parts: tuple[str, ...], *, max_bytes: int | None = None, expected: tuple[int, str] | None = None
    ) -> _VerifiedFile:
        """Open an already-validated result-relative path from the root.

        Every intermediate component is opened relative to its parent with
        ``O_DIRECTORY|O_NOFOLLOW`` and ``fstat``-checked, so a component swapped
        for a symlink fails the open instead of being followed; each descriptor
        stays open until the next one exists, so no directory can be exchanged
        for a different one between two steps of the walk.
        """
        descriptors: list[int] = []
        try:
            current = self._root_fd
            for part in parts[:-1]:
                current = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), dir_fd=current
                )
                descriptors.append(current)
            return self.open_verified(current, parts[-1], max_bytes=max_bytes, expected=expected)
        except ArtifactIdentityError as exc:
            # Not found is the one open failure that is not an identity refusal:
            # a caller distinguishes "there is no manifest" from "the manifest is
            # there and unusable", so a missing entry has to survive the
            # normalization below.
            if isinstance(exc.__cause__, FileNotFoundError):
                raise exc.__cause__ from exc
            raise
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise ArtifactIdentityError(f"published entry is unreachable: {'/'.join(parts)}") from exc
        finally:
            for descriptor in descriptors:
                os.close(descriptor)


def _hash_bounded(handle: Any, limit: int) -> tuple[int, str]:
    """Stream-hash at most *limit* bytes, returning ``(size, sha256)``.

    The loop is bounded by the size the descriptor reported before the read
    started, so an artifact that grows while it is being hashed cannot hold the
    reader in an unbounded stream: the extra bytes are simply not hashed, and the
    size mismatch that leaves is what rejects the candidate.
    """
    digest = hashlib.sha256()
    size = 0
    while size < limit:
        chunk = handle.read(min(_HASH_CHUNK_BYTES, limit - size))
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    return size, digest.hexdigest()


class ArtifactIdentityError(OSError):
    """A candidate does not satisfy the published-artifact identity contract.

    It is an ``OSError`` because it is a failure to obtain the published file at
    all, so every caller that already fails closed on an unreadable file fails
    closed on a symlinked, linked, or substituted one with no extra branch.
    """


class ArtifactOversizedError(ArtifactIdentityError):
    """The candidate is larger than the bound its reader is allowed to hold.

    Distinct because it is answered with the capacity vocabulary: the size was
    refused from the descriptor before the file was hashed.
    """


class ArtifactChangedError(ArtifactIdentityError):
    """The candidate changed length between its size report and the bounded read.

    Raised only after a bounded hash produced fewer bytes than the descriptor
    reported, so the digest describes no single version of the file.
    """


class PublicationAnchor:
    """The identity of a published manifest, as recorded outside the result tree.

    A published manifest is self-describing: it declares the artifacts, their
    sizes, and their digests.  Nothing *inside* the result tree can therefore
    say whether the manifest being read is the one Core finalized — the runner's
    Unix identity writes both.  This is that statement, resolved from
    server-owned state: the digest and size recorded when Core published, plus
    the revision, so a re-publication is a new revision of the same task's
    publication rather than an unanchored replacement.
    """

    __slots__ = ("sha256", "size", "revision")

    def __init__(self, sha256: str, size: int, revision: int):
        self.sha256 = sha256
        self.size = size
        self.revision = revision

    def matches(self, digest: str, size: int) -> bool:
        return self.sha256 == digest and self.size == size


#: Publication states.  Every state but ``AVAILABLE`` is a refusal, and each
#: refusal names *why* the manifest on disk is not a publication Core finalized
#: — so a consumer answers with a bounded reason instead of a bare not-found,
#: and an operator can tell a transient establishment failure (which the task's
#: own retry settles) from a result that predates the anchor (which only a fresh
#: run of the task can publish).
PUBLICATION_AVAILABLE = "available"
#: The result tree holds no manifest at all, and no anchor row either: nothing
#: was ever published for the task, which is the absence of a publication rather
#: than a refusal of one.
PUBLICATION_NOT_FINALIZED = "not_finalized"
#: An anchor row exists but the manifest on disk is missing: a publication whose
#: bytes went away.
PUBLICATION_MANIFEST_MISSING = "manifest_missing"
#: A manifest exists but no anchor row does.  This is the state of every result
#: finalized before the publication anchor existed, and of a run that died
#: between writing its manifest and recording the anchor.
PUBLICATION_UNANCHORED = "unanchored"
#: An anchor row exists but the manifest on disk is not an ordinary readable
#: file any more: a symlink, a second link, or an oversized or truncated entry.
PUBLICATION_MANIFEST_UNREADABLE = "manifest_unreadable"
#: An anchor row exists and the manifest bytes no longer match it: the manifest
#: was replaced after finalization.
PUBLICATION_ANCHOR_MISMATCH = "anchor_mismatch"
#: Reader and writer disagree about the anchor itself (a malformed row).
PUBLICATION_ANCHOR_INVALID = "anchor_invalid"

#: The states a published-but-unreadable result can be in.  These are the
#: *states that carry a reason*, as opposed to ``not_finalized`` (nothing was
#: published) — a consumer that wants to say "this result exists but is
#: quarantined, and here is why" switches on these.
PUBLICATION_QUARANTINE_STATES = frozenset(
    {
        PUBLICATION_UNANCHORED,
        PUBLICATION_MANIFEST_MISSING,
        PUBLICATION_MANIFEST_UNREADABLE,
        PUBLICATION_ANCHOR_MISMATCH,
        PUBLICATION_ANCHOR_INVALID,
    }
)


class ResultPublicationError(RuntimeError):
    """The publication anchor could not be established in server-owned state.

    Publication is one transition: the anchor is the durable authority a reader
    verifies against, so a publication that could not record its anchor never
    happened.  Raising here is what stops a run from reporting a finished task,
    emitting a publication event, and leaving a result Core's own reader will
    refuse — the task records a failure instead, and a retry re-publishes.
    """


class StorageResolver:
    """Resolve every task path from its immutable user storage identity."""

    def __init__(self, results_dir: str, workspace_dir: str, task_store: Any = None):
        self.results_dir = os.path.abspath(results_dir)
        self.workspace_dir = os.path.abspath(workspace_dir)
        # The task store owns the finalized-manifest publication anchor; a
        # resolver built without it can still resolve paths but cannot verify a
        # publication, so it refuses one rather than trusting the result tree.
        self.task_store = task_store

    @staticmethod
    def _task_parts(task: dict[str, Any]) -> tuple[str, str]:
        storage_key = str(task.get("storage_key") or "")
        task_id = str(task.get("md5sum") or "").lower()
        if not _STORAGE_KEY.fullmatch(storage_key):
            raise ValueError("invalid user storage key")
        if not _TASK_ID.fullmatch(task_id):
            raise ValueError("invalid task id")
        return storage_key, task_id

    def get_user_root(self, storage_key: str, *, inputs: bool = False) -> str:
        if not _STORAGE_KEY.fullmatch(storage_key):
            raise ValueError("invalid user storage key")
        base = self.workspace_dir if inputs else self.results_dir
        return safe_join(base, "users", storage_key)

    def get_task_root(self, task: dict[str, Any]) -> str:
        storage_key, task_id = self._task_parts(task)
        return safe_join(self.get_user_root(storage_key), "tasks", task_id)

    def get_input_root(self, task: dict[str, Any]) -> str:
        storage_key, task_id = self._task_parts(task)
        return safe_join(self.get_user_root(storage_key, inputs=True), "tasks", task_id)

    def get_output_root(self, task: dict[str, Any]) -> str:
        return self.get_task_root(task)

    def get_manifest_path(self, task: dict[str, Any]) -> str:
        return safe_join(self.get_task_root(task), "manifest.json")

    def get_archive_path(self, task: dict[str, Any]) -> str:
        task_id = str(task.get("md5sum") or "").lower()
        if not _TASK_ID.fullmatch(task_id):
            raise ValueError("invalid task id")
        return safe_join(os.path.dirname(self.get_task_root(task)), f"{task_id}_results.zip")

    def task_root(self, storage_key: str, task_id: str) -> str:
        return self.get_task_root({"storage_key": storage_key, "md5sum": task_id})

    manifest_path = get_manifest_path

    def read_manifest_bytes(self, task: dict[str, Any]) -> bytes | None:
        """Return the exact verified bytes of the finalized results manifest.

        One verified descriptor, one bounded read: callers that both select
        artifacts from the manifest and republish it (the results archive) must
        use *these* bytes, so the entries in the republished manifest can never
        describe a different manifest than the one that selected them.

        The bytes are additionally checked against the publication anchor Core
        recorded outside the result tree, so "is this the manifest Core
        finalized?" is answered with evidence the runner's Unix identity cannot
        rewrite.  The anchor is resolved through the caller's own task store, so
        every consumer of this reader -- every web surface, worker path, and
        maintenance job -- inherits the check and agrees on the same authority.
        A manifest that is unreadable, unanchored, or that no longer matches its
        anchor is ``None``; :meth:`publication_state` reports *which* of those it
        is, so a caller can answer with a bounded reason.
        """
        return self._read_verified_manifest(task)[0]

    def _read_verified_manifest(self, task: dict[str, Any]) -> tuple[bytes | None, str]:
        """Read the manifest and classify it in one pass.

        One implementation of the publication read: every caller gets either the
        verified bytes or the state that explains the refusal, so no consumer can
        disagree with another about whether a result is published, and no
        consumer has to re-derive the reason by re-opening the file.  The bytes
        come from a descriptor opened relative to the trusted result root, so an
        intermediate directory swapped for a symlink cannot point the read at a
        different manifest.
        """
        try:
            result_root = self.get_task_root(task)
        except (AttributeError, ValueError):
            return None, PUBLICATION_NOT_FINALIZED
        try:
            with _ResultTreeWalker(result_root) as walker:
                verified = walker.open_published_file(("manifest.json",), max_bytes=manifest_byte_limit())
                try:
                    data = verified.handle.read(manifest_byte_limit())
                    if len(data) != verified.size:
                        # The manifest changed between the descriptor's own size
                        # report and the bounded read: it was replaced while it
                        # was being read.
                        raise ArtifactIdentityError("manifest changed while being read")
                finally:
                    verified.handle.close()
        except FileNotFoundError:
            # Nothing at the canonical manifest path at all.
            if self._anchor_row(task):
                return None, PUBLICATION_MANIFEST_MISSING
            return None, PUBLICATION_NOT_FINALIZED
        except (AttributeError, OSError, ValueError):
            # No usable manifest on disk.  Whether *anything* was published is
            # the anchor's answer, and the two "no anchor" cases are different
            # facts: an anchor with the bytes gone is a publication lost after
            # the fact, while a missing file with no anchor is simply a task that
            # never finalized -- the ordinary not-yet case, not a quarantine.
            if self._anchor_row(task):
                return None, PUBLICATION_MANIFEST_MISSING
            return None, PUBLICATION_MANIFEST_UNREADABLE
        anchor, raw = self._publication_anchor(task)
        if raw is not None and anchor is None:
            return None, PUBLICATION_ANCHOR_INVALID
        if anchor is None:
            # A structurally valid manifest with no server-owned anchor.  This is
            # the legacy corpus: results finalized before publication identity was
            # recorded here.  It is quarantined, never re-anchored from the result
            # tree, because the tree is exactly the namespace this anchor exists
            # to stop trusting.
            return None, PUBLICATION_UNANCHORED
        if not anchor.matches(hashlib.sha256(data).hexdigest(), len(data)):
            return None, PUBLICATION_ANCHOR_MISMATCH
        return data, PUBLICATION_AVAILABLE
        return data, PUBLICATION_AVAILABLE

    def publication_state(self, task: dict[str, Any]) -> str:
        """Return the bounded publication state of one task's result.

        Answered from the same verified read every consumer uses, so the status
        endpoint, the results route, the archive builder, and the reconciliation
        sweep cannot disagree about whether a result is published.
        """
        return self._read_verified_manifest(task)[1]

    def _anchor_row(self, task: dict[str, Any]) -> dict[str, Any] | None:
        """Return the raw anchor row for a task, or ``None`` when there is none.

        Resolved from the task store this resolver was built with — the one
        authority the web, worker, and maintenance processes already share.  A
        resolver built without that store cannot answer the question at all, so
        it reports no anchor, which is exactly the refusal it is entitled to
        make.
        """
        task_id = str(task.get("md5sum") or "").lower()
        if self.task_store is None or not _TASK_ID.fullmatch(task_id):
            return None
        try:
            record = self.task_store.get_result_publication(task_id)
        except Exception:  # pylint: disable=broad-except
            return None
        return dict(record) if record else None

    def _publication_anchor(self, task: dict[str, Any]) -> tuple[PublicationAnchor | None, dict[str, Any] | None]:
        """Resolve the finalized-manifest identity Core recorded for one task.

        Returns ``(anchor, raw_row)``.  ``anchor`` is ``None`` both when there is
        no row and when the row is not a usable anchor; the caller distinguishes
        the two by whether ``raw_row`` is present.
        """
        record = self._anchor_row(task)
        if record is None:
            return None, None
        digest = str(record.get("manifest_sha256") or "")
        size = record.get("manifest_size")
        if not _SHA256.fullmatch(digest) or not isinstance(size, int) or isinstance(size, bool) or size < 0:
            return None, record
        return PublicationAnchor(digest, size, int(record.get("revision") or 1)), record

    def load_manifest(self, task: dict[str, Any]) -> dict[str, Any] | None:
        """Return the finalized results manifest, or ``None`` when unreadable.

        The manifest is the publication authority, so it is read from one
        verified descriptor -- private regular file, no symlink, single link,
        bounded size -- and never from a pathname that could be swapped for a
        second manifest between the read and an artifact lookup.
        """
        data = self.read_manifest_bytes(task)
        if data is None:
            return None
        try:
            manifest = json.loads(data)
        except ValueError:
            return None
        return manifest if isinstance(manifest, dict) else None

    def resolve_declared_artifact(
        self, task: dict[str, Any], relative_path: str, manifest: dict[str, Any] | None = None
    ) -> tuple[tuple[str, ...], dict[str, Any]] | None:
        """Resolve a manifest-declared artifact to its component parts and entry.

        Path normalization and declaration lookup only.  The result is the
        *components*, never a pathname: every consumer opens them relative to the
        trusted result root through the one walker, so no consumer can turn a
        declaration back into an absolute path and reopen it.  A caller that
        already holds the parsed manifest passes it in rather than re-reading it
        once per artifact.
        """
        parts = manifest_relative_parts(relative_path)
        if parts is None:
            return None
        if manifest is None:
            manifest = self.load_manifest(task)
        if manifest is None:
            return None
        declared = "/".join(parts)
        artifact = next(
            (item for item in manifest.get("artifacts", []) if isinstance(item, dict) and item.get("path") == declared),
            None,
        )
        if artifact is None:
            return None
        return parts, artifact

    @staticmethod
    def _declared_identity(artifact: dict[str, Any]) -> tuple[int, str]:
        """Return the ``(size, sha256)`` identity a manifest entry must carry."""
        declared_size = artifact.get("size")
        declared_digest = artifact.get("sha256")
        if not isinstance(declared_size, int) or isinstance(declared_size, bool) or declared_size < 0:
            raise ArtifactIdentityError("published artifact declares no usable size")
        if not isinstance(declared_digest, str) or not _SHA256.fullmatch(declared_digest):
            raise ArtifactIdentityError("published artifact declares no usable digest")
        return declared_size, declared_digest

    def open_verified_artifact(
        self, task: dict[str, Any], relative_path: str, manifest: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Resolve a manifest-declared artifact and its verified open descriptor.

        The one published-artifact identity contract: a private regular file (no
        symlink, single link, every intermediate component a real directory)
        whose declared size and SHA-256 match the bytes of the opened descriptor.
        Both are required -- an entry without them carries no identity evidence.
        The returned ``verified_stream`` is the descriptor whose size and SHA-256
        were just checked against the manifest entry, left open and rewound.  A
        consumer must read *that* descriptor: after publication identity has been
        verified, a reopen -- of a pathname, or of a name a second walk would
        resolve again -- could serve bytes that never satisfied the manifest
        identity.  The provenance digest is the one computed while verifying that
        descriptor.  ``None`` means the artifact is refused; the caller owns the
        descriptor of a returned result and must close it.
        """
        resolved = self.resolve_declared_artifact(task, relative_path, manifest)
        if resolved is None:
            return None
        parts, artifact = resolved
        try:
            declared = self._declared_identity(artifact)
            verified = self._open_verified_parts(task, parts, declared)
        except (ArtifactIdentityError, OSError, ValueError):
            return None
        return {
            **artifact,
            "path": "/".join(parts),
            "verified_stream": verified.handle,
            "sha256": verified.digest,
            "size": verified.size,
            "type": artifact.get("type") or artifact.get("media_type"),
        }

    def _open_verified_parts(
        self, task: dict[str, Any], parts: tuple[str, ...], declared: tuple[int, str]
    ) -> _VerifiedFile:
        """Open *parts* from the task's trusted result root and verify the bytes."""
        with _ResultTreeWalker(self.get_task_root(task)) as walker:
            return walker.open_published_file(parts, max_bytes=declared[0], expected=declared)

    def resolve_artifact(self, task: dict[str, Any], relative_path: str) -> dict[str, Any] | None:
        """Resolve a manifest-declared artifact for a read consumer.

        The name the download, projection, and Tool paths call.  It delegates to
        the one implementation, so every consumer consumes one identity contract
        whether or not it already holds the parsed manifest.
        """
        return self.open_verified_artifact(task, relative_path)

