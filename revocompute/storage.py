# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Authoritative immutable user-owned task storage resolution."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
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
# The manifest authorizes artifact exposure, so it must not have a weaker trust
# boundary than the artifacts it governs: it is opened as a private file like
# any artifact and bounded like any other file a hostile result tree wrote.
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024


class ArtifactIdentityError(OSError):
    """A candidate does not satisfy the published-artifact identity contract.

    It is an ``OSError`` because it is a failure to obtain the published file at
    all, so every caller that already fails closed on an unreadable file fails
    closed on a symlinked, linked, or substituted one with no extra branch.
    """


def _open_published_file(path: str) -> Any:
    """Open an artifact as a verified descriptor under the private-link contract.

    ``O_NOFOLLOW`` refuses a final-component symlink atomically at open time, and
    the ``fstat`` runs on the *opened descriptor* rather than on a pathname, so a
    regular single-linked file is the only thing this descriptor can be reading.
    The caller must close the returned handle.
    """
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    handle = os.fdopen(descriptor, "rb")
    try:
        status = os.fstat(handle.fileno())
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise ArtifactIdentityError(f"not a private regular file: {path}")
    except BaseException:
        handle.close()
        raise
    return handle


def _hash_open_file(handle: Any) -> tuple[str, int]:
    """Stream-hash an open descriptor, returning ``(sha256, size)`` in bounded chunks."""
    digest = hashlib.sha256()
    size = 0
    while chunk := handle.read(_HASH_CHUNK_BYTES):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


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
        consumer has to re-derive the reason by re-opening the file.
        """
        try:
            manifest_path = self.get_manifest_path(task)
        except (AttributeError, ValueError):
            return None, PUBLICATION_NOT_FINALIZED
        try:
            handle = _open_published_file(manifest_path)
        except (AttributeError, OSError, ValueError) as exc:
            # No usable manifest on disk.  Whether *anything* was published is the
            # anchor's answer, and the two "no anchor" cases are different facts:
            # an anchor with the bytes gone is a publication lost after the fact,
            # while a missing file with no anchor is simply a task that never
            # finalized -- the ordinary not-yet case, not a quarantine.
            if self._anchor_row(task):
                return None, PUBLICATION_MANIFEST_MISSING
            # A manifest that exists but cannot be opened as a private regular
            # file is not a publication either; it is a refused one, and saying
            # "not finalized" for it would be false.
            if isinstance(exc, ArtifactIdentityError) or os.path.lexists(manifest_path):
                return None, PUBLICATION_MANIFEST_UNREADABLE
            return None, PUBLICATION_NOT_FINALIZED
        with handle:
            if os.fstat(handle.fileno()).st_size > _MAX_MANIFEST_BYTES:
                return None, PUBLICATION_MANIFEST_UNREADABLE
            data = handle.read(_MAX_MANIFEST_BYTES + 1)
        if len(data) > _MAX_MANIFEST_BYTES:
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
    ) -> tuple[str, dict[str, Any]] | None:
        """Resolve a manifest-declared artifact to its path and manifest entry.

        Path normalization and declaration lookup only.  Both the download
        resolver and the results archive verify the bytes with
        ``open_verified_artifact``, so both consume one identity contract.  A
        caller that already holds the parsed manifest passes it in rather than
        re-reading it once per artifact.
        """
        normalized = relative_path.replace("\\", "/")
        parts = normalized.split("/")
        if not normalized or normalized.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            return None
        if manifest is None:
            manifest = self.load_manifest(task)
        if manifest is None:
            return None
        artifact = next((item for item in manifest.get("artifacts", []) if item.get("path") == normalized), None)
        if artifact is None:
            return None
        try:
            path = safe_join(self.get_task_root(task), *parts)
        except (AttributeError, ValueError):
            return None
        return path, artifact

    @staticmethod
    def open_verified_artifact(path: str, artifact: dict[str, Any]) -> tuple[Any, str]:
        """Open a published artifact and verify it against its manifest entry.

        This is *the* published-artifact identity contract: a private regular
        file (no symlink, single link) whose declared size and SHA-256 match the
        bytes of the opened descriptor.  Both are required — an entry without
        them carries no identity evidence, so it fails closed rather than being
        trusted on its pathname.  Returns ``(handle, digest)`` with the handle
        rewound to the start; the caller must close it.
        """
        declared_size = artifact.get("size")
        declared_digest = artifact.get("sha256")
        if not isinstance(declared_size, int) or isinstance(declared_size, bool) or declared_size < 0:
            raise ArtifactIdentityError("published artifact declares no usable size")
        if not isinstance(declared_digest, str) or not _SHA256.fullmatch(declared_digest):
            raise ArtifactIdentityError("published artifact declares no usable digest")
        handle = _open_published_file(path)
        try:
            digest, size = _hash_open_file(handle)
            if declared_size != size:
                raise ArtifactIdentityError("published artifact does not match its declared size")
            if declared_digest != digest:
                raise ArtifactIdentityError("published artifact does not match its declared digest")
            handle.seek(0)
        except BaseException:
            handle.close()
            raise
        return handle, digest

    def resolve_artifact(self, task: dict[str, Any], relative_path: str) -> dict[str, Any] | None:
        """Resolve a manifest-declared artifact and its verified open descriptor.

        The returned ``verified_stream`` is the descriptor whose size and SHA-256
        were just checked against the manifest entry, left open and rewound.  A
        consumer must read *that* descriptor rather than reopen ``physical_path``:
        after publication identity has been verified, a pathname reopen would let
        a replaced file serve bytes that never satisfied the manifest identity.
        The provenance digest is the one computed while verifying that descriptor,
        never a second open of the pathname.  The caller owns the descriptor and
        must close it.
        """
        resolved = self.resolve_declared_artifact(task, relative_path)
        if resolved is None:
            return None
        path, artifact = resolved
        try:
            stream, digest = self.open_verified_artifact(path, artifact)
        except (ArtifactIdentityError, OSError, ValueError):
            return None
        return {
            **artifact,
            "path": relative_path.replace("\\", "/"),
            "physical_path": path,
            "verified_stream": stream,
            "sha256": digest,
            "size": os.fstat(stream.fileno()).st_size,
            "type": artifact.get("type") or artifact.get("media_type"),
        }

