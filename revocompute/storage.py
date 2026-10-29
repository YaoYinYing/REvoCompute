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
import io
import json
import os
import re
import stat
import tempfile
import uuid
import weakref
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, BinaryIO

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


# Hash and copy in bounded chunks: an artifact is a scientific file that can be
# gigabytes wide, so it is never handled with one artifact-sized read or buffer.
_HASH_CHUNK_BYTES = 1024 * 1024

#: How every published path is opened: read-only (no write can be requested of a
#: published file), no-follow (a final-component symlink is refused atomically at
#: open time), close-on-exec, and **non-blocking**.  ``O_NONBLOCK`` is what makes
#: the type check that follows reachable for every entry: a FIFO or a socket with
#: no peer would otherwise block the open itself, so one hostile name in one
#: runner-owned result tree could hold a shared Server worker forever.
SAFE_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | os.O_NONBLOCK

#: The flags on which the publication writer creates a fresh entry.  ``O_EXCL``
#: refuses a name that already exists, so a symlink or hard link a Runner planted
#: at a predictable name is never opened through; ``O_NOFOLLOW`` refuses a final
#: symlink outright, so there is no window in which the name could be one.  The
#: file is created mode ``0600`` -- a private regular file owned by this process,
#: the same shape every reader requires of a published artifact.
_MANIFEST_CREATE_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
)

#: The one maximum serialized-manifest byte limit, shared by the writer that
#: anchors a manifest and the reader that serves it.  Two constants would be two
#: contracts, and a writer that can emit a manifest its own reader must reject
#: leaves a Task finished with a result no consumer can open.
MANIFEST_MAX_BYTES = 8 * 1024 * 1024

#: Files the Server writes directly in a Task result root, beside the runner's
#: own tree.  A Runner that turns a user-supplied name into a directory at that
#: level must refuse these: a directory named ``manifest.json`` cannot be
#: replaced by the publication rename, and the Server's ``citations.bib`` or
#: ``task_failed.txt`` write raises over a directory of that name.  The writer
#: sites are :meth:`StorageResolver.get_manifest_path` and the
#: ``publish_result_text`` calls in ``task_runtime``.  Runner-owned result-layout
#: names (``ERR``, ``task_finished``, a family's provenance files) are
#: deliberately absent: each runner owns its own tree and refuses those itself.
RESERVED_RESULT_ROOT_FILES = frozenset({"manifest.json", "citations.bib", "task_failed.txt"})


def manifest_byte_limit() -> int:
    """Return the one serialized-manifest byte ceiling writer and reader share.

    The single read site for the limit: the publication writer asks for the
    ceiling instead of restating it, so the two sides cannot drift into two
    contracts -- a writer that anchors a manifest the canonical reader classifies
    as unreadable would leave a finished Task no consumer can open.
    """
    return MANIFEST_MAX_BYTES


#: A component of a result-relative path.  The result tree is runner-writable and
#: a hostile name is not merely long: a control character in a manifest entry
#: reaches HTTP headers, ZIP member names, and log lines, and ``.``/``..`` are
#: names the walker never emits.  One expression judges a component for the
#: writer, the reader, the walk, and the archive, so the vocabulary cannot differ
#: between them.
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


def verify_regular_file(descriptor: int, limit: int) -> tuple[BinaryIO, str]:
    """Verify an already-opened private regular file into a bounded private snapshot.

    The one publication read, shared by every consumer.  The type, the link
    count, and the size the copy is bounded by are all read from the *opened
    descriptor*, never from a name that produced it: a symlink, a directory, a
    second link, a FIFO, a socket, and a device are refused by one check no name
    swap can outrun, and an entry over *limit* costs a stat rather than a copy.

    What comes back is a private, unlinked, server-owned image of that
    descriptor, positioned at its start, together with the SHA-256 of exactly
    those bytes.  A consumer therefore holds a version of the file rather than a
    window onto a mutable inode: a same-length rewrite of the runner's file --
    which keeps the inode, the link count, and the size, and so passes every
    check a descriptor's metadata can make -- reaches nothing, because the bytes
    served are no longer the file's.  The image is disk-backed rather than
    resident, so a multi-hundred-megabyte artifact is copied in bounded chunks
    instead of held in a worker's heap, and it is removed when the last
    reference to it drops.

    The caller owns the returned object and must close it; the input *descriptor*
    is consumed and closed on every path out of this call.
    """
    # The type and the length are read from the raw descriptor, before it is
    # wrapped: a directory refuses ``fdopen`` with a different error, and the one
    # identity rule has to decide what a candidate is -- not the file-object
    # layer underneath it.
    snapshot: BinaryIO | None = None
    handle: Any = None
    try:
        status = os.fstat(descriptor)
        size = status.st_size
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise ArtifactIdentityError("not a private regular file")
        if size > limit:
            raise ArtifactOversizedError("published file exceeds its bound")
        handle = os.fdopen(descriptor, "rb")
        snapshot = _private_snapshot()
        digest, copied = _copy_bounded(handle, snapshot, size)
        # Growth is reported by the descriptor *after* the copy, not by the count
        # that copy produced: the copy is bounded by the pre-read size, so an inode
        # that grew would otherwise still yield a digest of its first ``size``
        # bytes that matches the manifest.  A file that changed length is not one
        # version of itself, so its digest describes no publication -- and the
        # error names the length the descriptor itself reported *after* the copy,
        # which is the fact that decided.
        final = os.fstat(descriptor).st_size
        if copied != size or final != size:
            raise ArtifactChangedError(f"published file changed from {size} to {final} bytes while being read")
        snapshot.seek(0)
        return snapshot, digest
    except BaseException:
        if snapshot is not None:
            snapshot.close()
        raise
    finally:
        if handle is not None:
            handle.close()
        else:
            # Not wrapped, so the caller's descriptor is this call's to close.
            os.close(descriptor)


def _copy_bounded(handle: Any, destination: BinaryIO, size: int) -> tuple[str, int]:
    """Copy exactly *size* bytes from *handle* into *destination* while hashing.

    The one digest-and-copy pass: the bytes a consumer will be served and the
    digest that says which publication they are come from the same read.  The
    copy is bounded by *size* -- the length the descriptor reported before it
    started -- so a file that grows underneath the reader is never read to its
    new length; a short copy (a file that shrank or was truncated) stops early
    instead of blocking.  Returns ``(sha256, bytes_copied)``; the caller is what
    decides whether the count matches what it expected.
    """
    digest = hashlib.sha256()
    copied = 0
    while copied < size:
        chunk = handle.read(min(_HASH_CHUNK_BYTES, size - copied))
        if not chunk:
            break
        digest.update(chunk)
        destination.write(chunk)
        copied += len(chunk)
    return digest.hexdigest(), copied


def _private_snapshot() -> BinaryIO:
    """Open a private, unlinked, disk-backed image a verified artifact is copied into.

    ``O_TMPFILE`` gives a file with no directory entry at all -- nothing in any
    namespace, the runner's or the server's, can name it, replace it, or read it,
    so the bytes a consumer is served cannot be rewritten after they were
    verified.  The file is anonymous by construction rather than by a predictable
    name plus a later unlink, and it needs no runner-writable directory: the
    service account's own scratch is enough, which is what keeps the server free
    of a shared publication store.  ``tempfile`` falls back to a named temporary
    it unlinks immediately when the kernel or the filesystem cannot do
    ``O_TMPFILE``, so the same guarantee holds either way.
    """
    return tempfile.TemporaryFile(prefix="revocompute-verified-")


def _release_verified(snapshot: BinaryIO | None, descriptor: int) -> None:
    """Release the two resources one verified snapshot owns, exactly once each.

    The one implementation of the release, shared by an explicit ``close`` and the
    stream's finalizer, so a consumer that closes and a consumer that only drops
    its reference cannot release either resource twice or leave one behind.
    """
    if snapshot is not None:
        try:
            snapshot.close()
        except OSError:  # pragma: no cover - closing a private stream does not fail
            pass
    if descriptor >= 0:
        try:
            os.close(descriptor)
        except OSError:
            pass


class _SnapshotStream:
    """A private image of one verified artifact, served under the file protocol.

    The verified bytes live in an unlinked, server-owned snapshot opened by
    :func:`verify_regular_file`, and every consumer reads that snapshot: what a
    caller is handed is a version of the file rather than a window onto a mutable
    inode, so a same-length rewrite of the runner's file after verification
    reaches nothing.  The size the snapshot was copied at bounds every read, so
    growth, shrinkage, and substitution all have no path in.  The snapshot is
    behind this object rather than handed out directly, so closing the stream
    removes the snapshot whatever the consumer does with it -- including a
    consumer that only drops its reference, which the finalizer covers.

    The descriptor the bytes were *verified as* is kept beside the snapshot,
    because a consumer may still ask the verified file about metadata the bytes
    do not describe -- its modification time, which a ZIP member header carries.
    Content never comes from that descriptor again: only :meth:`fileno` reaches
    it, and it exists so a caller can ``fstat`` the very inode the bytes were
    verified as.  Closing this stream closes it exactly once.

    A read that fails underneath is remembered until the stream is closed, so a
    close cannot present a broken stream as a clean one: the failing exception is
    raised from :meth:`close` the way ``BufferedReader`` raises a deferred read
    error from ``flush``.  Information a consumer relies on is not dropped
    between the read that raised and the close that ends the stream.
    """

    __slots__ = ("_snapshot", "_descriptor", "_closed", "_finalizer", "_failure", "__weakref__")

    def __init__(self, snapshot: BinaryIO, descriptor: int):
        self._snapshot = snapshot
        self._descriptor = descriptor
        self._closed = False
        self._failure: BaseException | None = None
        # Removing the snapshot and the verified descriptor is a resource
        # concern, not a semantic one, so it must survive a consumer that never
        # closes: a finalizer releases both exactly once even if the stream is
        # only dropped.  ``weakref.finalize`` is used rather than ``__del__`` so
        # the release still runs when the stream is part of a reference cycle.
        self._finalizer = weakref.finalize(self, _release_verified, snapshot, descriptor)

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        # A verified snapshot is read-only: it stands in for a file the
        # publication contract opened read-only, and ``io.TextIOWrapper`` asks
        # before it will wrap one, so the answer has to be the truth.
        return False

    def seekable(self) -> bool:
        return True

    @property
    def closed(self) -> bool:
        return self._closed

    def fileno(self) -> int:
        """Return the descriptor whose bytes were verified.

        A consumer that wants the verified file's *metadata* -- the ZIP member
        timestamp -- reaches the inode here.  The bytes it serves are the
        snapshot, never this descriptor.
        """
        if self._descriptor < 0:
            raise io.UnsupportedOperation("the verified descriptor is closed")
        return self._descriptor

    def read(self, size: int = -1) -> bytes:
        try:
            return self._snapshot.read(size)
        except OSError as exc:
            self._note_failure(exc)
            raise

    def readinto(self, buffer: Any) -> int:
        try:
            return self._snapshot.readinto(buffer)
        except OSError as exc:
            self._note_failure(exc)
            raise

    def read1(self, size: int = -1) -> bytes:
        try:
            return self._snapshot.read1(size) if hasattr(self._snapshot, "read1") else self._snapshot.read(size)
        except OSError as exc:
            self._note_failure(exc)
            raise

    def readline(self, size: int = -1) -> bytes:
        try:
            return self._snapshot.readline(size)
        except OSError as exc:
            self._note_failure(exc)
            raise

    def __iter__(self) -> Any:
        return iter(self._snapshot)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._snapshot.seek(offset, whence)

    def tell(self) -> int:
        return self._snapshot.tell()

    def flush(self) -> None:
        return None

    def _note_failure(self, error: OSError) -> None:
        """Remember the first read error, so a later ``close`` still reports it."""
        if self._failure is None:
            self._failure = error

    def close(self) -> None:
        # Detach first, so a re-entrant close -- the finalizer running while the
        # caller is inside this call -- cannot double-close either resource.
        snapshot, self._snapshot = self._snapshot, None
        descriptor, self._descriptor = self._descriptor, -1
        self._closed = True
        failure, self._failure = self._failure, None
        if self._finalizer.detach() is not None:
            _release_verified(snapshot, descriptor)
        if failure is not None:
            # The stream broke under a consumer and is now ended; a terminal
            # close must not report a clean stream.  The message is carried so
            # the reason the read failed survives to whoever inspects the close.
            raise _StreamReadError(f"verified snapshot read failed: {failure}") from failure

    def __enter__(self) -> "_SnapshotStream":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class _VerifiedFile:
    """One verified published file: the private snapshot and the digest of its bytes."""

    handle: Any
    digest: str
    size: int


def open_published_regular_file(path: str) -> int | None:
    """Open *path* as the private regular file it claims to be, or ``None``.

    The cached-artifact check: a byte on disk at a canonical name is not evidence
    of anything inside the runner-writable results tree, so a candidate is opened
    once -- read-only, non-blocking, no-final-symlink -- and accepted only if its
    own descriptor proves it is a regular file with a single link.  The
    *descriptor* is returned, never the path again: a caller that closed it and
    reopened the name would have re-created exactly the check-then-use gap this
    open removes.  ``None`` means "there is no such published file".
    """
    try:
        descriptor = os.open(path, SAFE_OPEN_FLAGS)
    except OSError:
        return None
    try:
        status = os.fstat(descriptor)
    except OSError:
        os.close(descriptor)
        return None
    if stat.S_ISREG(status.st_mode) and status.st_nlink == 1:
        return descriptor
    os.close(descriptor)
    return None


def verified_publication_archive(source: Any, manifest_bytes: bytes, artifacts: Iterable[dict[str, Any]]) -> bool:
    """Whether the opened archive is exactly a repackaging of *this* publication.

    A results archive lives in the same runner-writable tree as the results, so
    it is derived, not authoritative: "a ZIP is there" proves nothing, and neither
    does a ZIP whose only checked member is the manifest.  The archive is accepted
    only when its *members* satisfy the identity contract the results themselves
    do -- every member stored rather than compressed (so the bytes verified here
    are the bytes a download delivers, with no decompressor run over
    runner-controlled data), the member set exactly the manifest plus the
    manifest's declared artifacts, the ``manifest.json`` member byte-for-byte the
    anchored manifest, and every artifact member's size and SHA-256 equal to the
    manifest entry that declares it.  A member whose bytes differ from the
    publication, an extra member, and a missing member are all refusals.
    """
    declared: dict[str, tuple[int, str]] = {
        "manifest.json": (len(manifest_bytes), hashlib.sha256(manifest_bytes).hexdigest())
    }
    for artifact in artifacts:
        path = artifact.get("path")
        size, digest = artifact.get("size"), artifact.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str) or not isinstance(size, int):
            return False
        declared[path] = (size, digest)
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if len(members) != len(declared):
                return False
            for member in members:
                if member.compress_type != zipfile.ZIP_STORED:
                    return False
                expected = declared.pop(member.filename, None)
                if expected is None or member.file_size != expected[0]:
                    return False
                digest = hashlib.sha256()
                read = 0
                with archive.open(member) as body:
                    while read <= expected[0] and (chunk := body.read(_HASH_CHUNK_BYTES)):
                        read += len(chunk)
                        digest.update(chunk)
                if read != expected[0] or digest.hexdigest() != expected[1]:
                    # The member's own header is not trusted to bound its bytes:
                    # anything but exactly the declared length is a refusal.
                    return False
    except (OSError, ValueError, zipfile.BadZipFile):
        return False
    return not declared


def create_private_entry(directory_fd: int, name: str) -> int:
    """Create *name* in *directory_fd* as a fresh private regular file.

    The writer's half of the published-artifact identity contract, and the same
    rule the reader applies -- a private regular file, reached by a name that is
    not a symlink.  ``O_CREAT|O_EXCL|O_NOFOLLOW`` is what makes the *name* safe:
    the entry did not exist and is created here, so it cannot be a symlink a
    Runner planted earlier, and a link swapped in afterwards still cannot be
    followed because the writer keeps working through the descriptor this returns.
    """
    return os.open(name, _MANIFEST_CREATE_FLAGS, 0o600, dir_fd=directory_fd)


def replace_entry(directory_fd: int, source_name: str, destination_name: str) -> None:
    """Atomically publish *source_name* as *destination_name*, both in *directory_fd*.

    ``renameat`` replaces the destination directory entry; it never resolves the
    destination *through* anything, so a symlink planted at ``destination_name``
    is replaced rather than written through, and a reader sees either the old
    entry or the new one and never a partial file.
    """
    os.rename(source_name, destination_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)


def publish_result_text(root: str, relative_path: str, payload: str | Iterable[str]) -> None:
    """Atomically write server evidence without following Runner-planted links."""
    parts = manifest_relative_parts(relative_path)
    if not parts:
        raise ArtifactIdentityError("invalid evidence path")
    with _ResultTreeWalker(root) as walker:
        directory = os.dup(walker._root_fd)
        candidate = f".evidence-{uuid.uuid4().hex}"
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, dir_fd=directory)
                except FileExistsError:
                    pass
                child = os.open(part, SAFE_OPEN_FLAGS | os.O_DIRECTORY, dir_fd=directory)
                os.close(directory)
                directory = child
            descriptor = create_private_entry(directory, candidate)
            try:
                handle = os.fdopen(descriptor, "w", encoding="utf-8")
            except BaseException:
                os.close(descriptor)
                raise
            with handle:
                if isinstance(payload, str):
                    handle.write(payload)
                else:
                    handle.writelines(payload)
            replace_entry(directory, candidate, parts[-1])
        finally:
            try:
                os.unlink(candidate, dir_fd=directory)
            except OSError:
                pass
            os.close(directory)


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
            self._root_fd = os.open(root, SAFE_OPEN_FLAGS | os.O_DIRECTORY)
        except OSError as exc:
            raise ArtifactIdentityError(f"result root cannot be opened safely: {root}") from exc
        # The descriptor, not the name, is the root of trust: it must be the very
        # directory that was just checked.  A root replaced between the check and
        # the open is refused here rather than walked.
        opened = os.fstat(self._root_fd)
        if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
            os.close(self._root_fd)
            self._root_fd = -1
            raise ArtifactIdentityError(f"result root changed while being opened: {root}")

    def __enter__(self) -> "_ResultTreeWalker":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._root_fd >= 0:
            os.close(self._root_fd)
            self._root_fd = -1

    def create_entry(self, name: str) -> int:
        """Create one fresh private entry at the root; the caller owns the descriptor."""
        if _MANIFEST_PATH_COMPONENT.fullmatch(name) is None or name in {".", ".."}:
            raise ArtifactIdentityError(f"entry name is not publishable: {name}")
        try:
            return create_private_entry(self._root_fd, name)
        except OSError as exc:
            raise ArtifactIdentityError(f"entry cannot be created: {name}") from exc

    def replace_entry(self, source_name: str, destination_name: str) -> None:
        """Atomically publish one root entry as another, both relative to the root."""
        for name in (source_name, destination_name):
            if _MANIFEST_PATH_COMPONENT.fullmatch(name) is None or name in {".", ".."}:
                raise ArtifactIdentityError(f"entry name is not publishable: {name}")
        replace_entry(self._root_fd, source_name, destination_name)

    def unlink_entry(self, name: str) -> None:
        """Remove one root entry by name; never follows a final symlink to a file."""
        if _MANIFEST_PATH_COMPONENT.fullmatch(name) is None or name in {".", ".."}:
            raise ArtifactIdentityError(f"entry name is not publishable: {name}")
        os.unlink(name, dir_fd=self._root_fd)

    def open_entry(self, name: str) -> int:
        """Open one root entry read-only and without following a final symlink."""
        return os.open(name, SAFE_OPEN_FLAGS, dir_fd=self._root_fd)

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
                child = os.open(name, SAFE_OPEN_FLAGS | os.O_DIRECTORY, dir_fd=directory_fd)
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

        The one publication read in the system: the reader and the publication
        writer both consume it, so neither can drift into a second idea of what
        "the published bytes" are.  The rule is read the type from the *opened
        descriptor* -- never from the name -- and refuse anything that is not a
        private regular file, so a symlink, a directory, a second link, a FIFO, a
        socket, and a device are all rejected by one check that no name swap can
        outrun.  The descriptor is opened with ``SAFE_OPEN_FLAGS``, so the open
        itself cannot block on an empty FIFO and the check is always reachable.
        The size the descriptor reports is checked against *max_bytes* before any
        byte is read, and the copy that follows is bounded by that same size, so
        an entry that grows underneath the reader yields a size mismatch instead
        of an unbounded read.  The verification itself is
        :func:`verify_regular_file`, so there is one copy-and-digest pass.

        What the caller receives is a private *snapshot* of the descriptor, not
        the descriptor: the digest describes exactly the bytes served, and a
        rewrite of the runner's inode -- of any length, in place -- cannot reach a
        consumer that holds the snapshot.  With ``expected`` those bytes must also
        match the manifest entry's ``(size, sha256)``, which remains the authority
        on *which* publication they are.
        """
        descriptor = os.open(name, SAFE_OPEN_FLAGS, dir_fd=directory_fd)
        # The verified stream keeps a descriptor on the *inode* the bytes came
        # from -- a consumer still asks the verified file for its modification
        # time -- so one duplicate is taken before the verification consumes the
        # original: ``verify_regular_file`` closes what it is handed on every
        # path, success or failure, and nothing below may close a number again
        # that by then could already belong to another file.
        try:
            kept = os.dup(descriptor)
        except OSError:
            os.close(descriptor)
            raise
        try:
            snapshot, digest = verify_regular_file(descriptor, max_bytes)
        except ArtifactChangedError as error:
            os.close(kept)
            raise ArtifactChangedError(f"published file changed while being read: {name}") from error
        except ArtifactOversizedError as error:
            os.close(kept)
            raise ArtifactOversizedError(f"published file exceeds its bound: {name}") from error
        except ArtifactIdentityError as error:
            os.close(kept)
            raise ArtifactIdentityError(f"not a private regular file: {name}") from error
        except BaseException:
            os.close(kept)
            raise
        try:
            size = snapshot.seek(0, os.SEEK_END)
            snapshot.seek(0)
            if expected is not None:
                declared_size, declared_digest = expected
                if size != declared_size:
                    raise ArtifactIdentityError(f"published artifact does not match its declared size: {name}")
                if digest != declared_digest:
                    raise ArtifactIdentityError(f"published artifact does not match its declared digest: {name}")
            return _VerifiedFile(_SnapshotStream(snapshot, kept), digest, size)
        except BaseException:
            snapshot.close()
            os.close(kept)
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
                current = os.open(part, SAFE_OPEN_FLAGS | os.O_DIRECTORY, dir_fd=current)
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


class _StreamReadError(OSError):
    """A read failure a verified snapshot was asked to remember until it closes.

    Raised by ``_SnapshotStream.close`` when an earlier read of the snapshot had
    failed: ``BufferedReader`` reports a read that failed in ``flush``/``close``
    rather than only at the call that raised, so a consumer that checks the
    terminal state of its own reader still learns the stream broke.  This carries
    the original message so nothing about the failure is lost between the read
    and the close.
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
        come from the snapshot of a descriptor opened relative to the trusted
        result root, so an intermediate directory swapped for a symlink cannot
        point the read at a different manifest.

        The bytes returned are the bytes the verification hashed, and they are
        compared against the server-owned anchor below, so the caller receives
        exactly the bytes whose digest the anchor describes: a rewrite of
        ``manifest.json`` in place -- of the same length, keeping the inode, the
        link count, and the size -- cannot be handed out as the publication.
        The manifest is bounded by :func:`manifest_byte_limit`, so reading it
        whole into memory is reading a small, contract-bounded string.
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
                finally:
                    verified.handle.close()
        except (AttributeError, OSError, ValueError) as error:
            # No usable manifest, and each fact is answered on its own evidence.
            #
            # The disposition is decided from the *verified read*, not from a
            # second look at the canonical name: a name that ``lexists`` but that
            # the walker refused to open -- a symlink, a second link, a FIFO, a
            # directory, an oversized or truncated file -- was refused for exactly
            # that reason, so it is ``manifest_unreadable`` whether or not the name
            # is still there now.  Only a genuine *absence* at the canonical path
            # falls through to the anchor's answer: an anchor with no bytes is
            # ``manifest_missing``, and with neither there is no publication at all.
            if not isinstance(error, FileNotFoundError):
                return None, PUBLICATION_MANIFEST_UNREADABLE
            if self._anchor_row(task):
                return None, PUBLICATION_MANIFEST_MISSING
            return None, PUBLICATION_NOT_FINALIZED
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
        """Resolve a manifest-declared artifact and its verified private snapshot.

        The one published-artifact identity contract: a private regular file (no
        symlink, single link, every intermediate component a real directory)
        whose declared size and SHA-256 match the bytes of the opened descriptor.
        Both are required -- an entry without them carries no identity evidence.
        The returned ``verified_stream`` is the private snapshot whose size and
        SHA-256 were just checked against the manifest entry, positioned at its
        start.  A consumer must read *that* snapshot: after publication identity
        has been verified, a reopen -- of a pathname, or of a name a second walk
        would resolve again -- could serve bytes that never satisfied the manifest
        identity, and a rewrite in place of the runner's own inode could not be
        refused by any check the file itself can answer.  The provenance digest
        is the one computed while verifying that snapshot.  ``None`` means the
        artifact is refused; the caller owns a returned stream and must close it.
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

