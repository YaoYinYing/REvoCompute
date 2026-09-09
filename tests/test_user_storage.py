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
    resolver = StorageResolver(str(tmp_path / "results"), str(tmp_path / "workspaces"))
    task = _task()
    root = Path(resolver.get_task_root(task))
    root.mkdir(parents=True)
    artifact = root / "model.pdb"
    content = b"ATOM\n"
    artifact.write_bytes(content)
    manifest = {
        "artifacts": [
            {
                "path": "model.pdb",
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
        ]
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
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


def test_invalid_storage_identity_fails_closed(tmp_path):
    resolver = StorageResolver(str(tmp_path / "results"), str(tmp_path / "workspaces"))
    assert resolver.get_task_root({"md5sum": "a" * 32, "storage_key": "alice-abcdef"}).endswith("/" + "a" * 32)
    for key in ("../alice", "/absolute", "a", "alice/other", "alice\\other"):
        with pytest.raises(ValueError, match="storage key"):
            resolver.get_task_root(_task(storage_key=key))
