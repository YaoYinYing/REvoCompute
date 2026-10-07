# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""User-owned task storage and immutable storage-identity tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from revocompute.auth import UserDatabase
from revocompute.storage import StorageResolver


def _task(**overrides):
    task = {
        "md5sum": "a" * 32,
        "storage_key": "alice-k7m4qx",
        "username": "alice",
    }
    task.update(overrides)
    return task


class _ManifestAnchorStore:
    """The task store's publication anchor, as the resolver consumes it.

    Publication identity lives in server-owned state rather than in the result
    tree, so a resolver-only test supplies the same anchor Core would record at
    finalization instead of writing a digest the reader could not verify.
    """

    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def publish(self, task: dict, data: bytes) -> None:
        self.records[task["md5sum"]] = {
            "manifest_sha256": hashlib.sha256(data).hexdigest(),
            "manifest_size": len(data),
            "revision": 1,
        }

    def get_result_publication(self, task_id: str) -> dict | None:
        return self.records.get(task_id)


def _publish_manifest(resolver: StorageResolver, store: _ManifestAnchorStore, task: dict, manifest: dict) -> None:
    """Write a finalized manifest and anchor it, as Core finalization does."""
    data = json.dumps(manifest).encode("utf-8")
    Path(resolver.get_manifest_path(task)).write_bytes(data)
    store.publish(task, data)


def test_task_roots_are_derived_from_immutable_user_storage_key(tmp_path):
    resolver = StorageResolver(str(tmp_path / "results"), str(tmp_path / "workspaces"))
    task_root = resolver.get_task_root(_task())

    assert task_root == str(tmp_path / "results" / "users" / "alice-k7m4qx" / "tasks" / ("a" * 32))
    assert resolver.get_input_root(_task()) == str(
        tmp_path / "workspaces" / "users" / "alice-k7m4qx" / "tasks" / ("a" * 32)
    )


def test_recorded_path_cannot_override_storage_identity(tmp_path):
    resolver = StorageResolver(str(tmp_path / "results"), str(tmp_path / "workspaces"))
    task = _task(result_dir=str(tmp_path / "attacker-selected"))
    assert resolver.get_task_root(task) != task["result_dir"]


def test_user_storage_keys_are_unique_and_immutable_across_rename(tmp_path):
    path = tmp_path / "users.sqlite3"
    db = UserDatabase(str(path))
    first = db.create_user("alice", "alice@example.test", "password123")
    second = db.create_user("bob", "bob@example.test", "password123")
    key = first["storage_key"]
    other_key = second["storage_key"]
    assert key != other_key
    reopened = UserDatabase(str(path))
    assert reopened.get_user(first["id"])["storage_key"] == key
    reopened.update_user(first["id"], username="alice_renamed")
    assert reopened.get_user(first["id"])["storage_key"] == key
    assert key.startswith("alice-")


def test_manifest_artifact_resolution_rejects_traversal_tampering_and_symlink_escape(tmp_path):
    store = _ManifestAnchorStore()
    resolver = StorageResolver(str(tmp_path / "results"), str(tmp_path / "workspaces"), store)
    task = _task()
    root = Path(resolver.get_task_root(task))
    root.mkdir(parents=True)
    artifact = root / "model.pdb"
    content = b"ATOM\n"
    artifact.write_bytes(content)
    _publish_manifest(
        resolver,
        store,
        task,
        {
            "artifacts": [
                {
                    "path": "model.pdb",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                }
            ]
        },
    )
    assert resolver.resolve_artifact(task, "model.pdb") is not None
    for unsafe in ("../model.pdb", "../../etc/passwd", "/etc/passwd", "..\\model.pdb"):
        assert resolver.resolve_artifact(task, unsafe) is None
    artifact.write_bytes(b"changed")
    assert resolver.resolve_artifact(task, "model.pdb") is None
    artifact.unlink()
    outside = tmp_path / "outside.pdb"
    outside.write_bytes(content)
    artifact.symlink_to(outside)
    assert resolver.resolve_artifact(task, "model.pdb") is None


def test_manifest_artifact_resolution_rejects_a_second_hardlink(tmp_path):
    """A published artifact must be reachable only through its manifest entry.
    A second link would let the bytes be replaced under a verified digest."""
    store = _ManifestAnchorStore()
    resolver = StorageResolver(str(tmp_path / "results"), str(tmp_path / "workspaces"), store)
    task = _task()
    root = Path(resolver.get_task_root(task))
    root.mkdir(parents=True)
    artifact = root / "model.pdb"
    content = b"ATOM\n"
    artifact.write_bytes(content)
    _publish_manifest(
        resolver,
        store,
        task,
        {
            "artifacts": [
                {
                    "path": "model.pdb",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                }
            ]
        },
    )
    assert resolver.resolve_artifact(task, "model.pdb") is not None

    outside = tmp_path / "outside.pdb"
    outside.write_bytes(content)
    artifact.unlink()
    artifact.hardlink_to(outside)

    assert resolver.resolve_artifact(task, "model.pdb") is None


def test_invalid_storage_identity_fails_closed(tmp_path):
    resolver = StorageResolver(str(tmp_path / "results"), str(tmp_path / "workspaces"))
    assert resolver.get_task_root({"md5sum": "a" * 32, "storage_key": "alice-abcdef"}).endswith("/" + "a" * 32)
    for key in ("../alice", "/absolute", "a", "alice/other", "alice\\other"):
        with pytest.raises(ValueError, match="storage key"):
            resolver.get_task_root(_task(storage_key=key))
