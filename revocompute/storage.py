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


class ArtifactIdentityError(Exception):
    """A candidate does not satisfy the published-artifact identity contract."""


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


def _sha256_file(path: str) -> str:
    with open(path, "rb") as handle:
        digest, _size = _hash_open_file(handle)
    return digest


class StorageResolver:
    """Resolve every task path from its immutable user storage identity."""

    def __init__(self, results_dir: str, workspace_dir: str):
        self.results_dir = os.path.abspath(results_dir)
        self.workspace_dir = os.path.abspath(workspace_dir)

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

    def load_manifest(self, task: dict[str, Any]) -> dict[str, Any] | None:
        """Return the finalized results manifest, or ``None`` when unreadable."""
        try:
            with open(self.get_manifest_path(task), encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (AttributeError, OSError, ValueError, TypeError):
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
    def open_verified_artifact(path: str, artifact: dict[str, Any]) -> Any:
        """Open a published artifact and verify it against its manifest entry.

        This is *the* published-artifact identity contract: a private regular
        file (no symlink, single link) whose observed size and SHA-256 match the
        manifest — verified on the exact descriptor the caller then reads.
        Returns the open handle rewound to the start; the caller must close it.
        """
        handle = _open_published_file(path)
        try:
            digest, size = _hash_open_file(handle)
            if artifact.get("size") is not None and artifact["size"] != size:
                raise ArtifactIdentityError("published artifact does not match its declared size")
            if artifact.get("sha256") and artifact["sha256"] != digest:
                raise ArtifactIdentityError("published artifact does not match its declared digest")
            handle.seek(0)
        except BaseException:
            handle.close()
            raise
        return handle

    def resolve_artifact(self, task: dict[str, Any], relative_path: str) -> dict[str, Any] | None:
        resolved = self.resolve_declared_artifact(task, relative_path)
        if resolved is None:
            return None
        path, artifact = resolved
        try:
            with self.open_verified_artifact(path, artifact) as handle:
                size = os.fstat(handle.fileno()).st_size
        except (ArtifactIdentityError, OSError, ValueError):
            return None
        return {
            **artifact,
            "path": relative_path.replace("\\", "/"),
            "physical_path": path,
            "sha256": artifact.get("sha256") or _sha256_file(path),
            "size": size if artifact.get("size") is None else artifact["size"],
            "type": artifact.get("type") or artifact.get("media_type"),
        }

