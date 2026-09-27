# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Runtime Bundle identity: hashing, materialization, pinning, and GC.

These prove the properties the refactor depends on, not the implementation of
them: an identical source tree hashes identically on any host and umask, an
executable bit is identity while a timestamp is not, and a bundle a Task pinned
is never removed by deployment bookkeeping.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "run"))

from revocompute import runtime_bundle as rb


def _overlay(root: Path, files: dict[str, tuple[str, bool]]) -> None:
    for relative, (content, executable) in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if executable:
            os.chmod(path, 0o755)


def test_identical_content_hashes_identically_regardless_of_order(tmp_path: Path) -> None:
    root = tmp_path / "runners"
    _overlay(root, {"common/runtime/a.py": ("print('a')\n", False), "fam/run.sh": ("#!/bin/sh\n", True)})
    declared = ["common/runtime", "fam/run.sh"]
    reversed_declaration = ["fam/run.sh", "common/runtime"]

    assert rb.overlay_digest(root, declared) == rb.overlay_digest(root, reversed_declaration)


def test_timestamp_and_mode_of_the_source_do_not_change_identity(tmp_path: Path) -> None:
    root = tmp_path / "runners"
    _overlay(root, {"fam/run.sh": ("#!/bin/sh\necho hi\n", True)})
    before = rb.overlay_digest(root, ["fam/run.sh"])

    # A host umask cannot reach the declared file, and mtime is never hashed.
    os.utime(root / "fam/run.sh", (0, 0))
    os.chmod(root / "fam", 0o700)

    assert rb.overlay_digest(root, ["fam/run.sh"]) == before


def test_content_change_changes_identity(tmp_path: Path) -> None:
    root = tmp_path / "runners"
    _overlay(root, {"fam/run.sh": ("#!/bin/sh\necho one\n", True)})
    before = rb.overlay_digest(root, ["fam/run.sh"])
    _overlay(root, {"fam/run.sh": ("#!/bin/sh\necho two\n", True)})

    assert rb.overlay_digest(root, ["fam/run.sh"]) != before


def test_executable_bit_is_identity(tmp_path: Path) -> None:
    root = tmp_path / "runners"
    _overlay(root, {"fam/run.sh": ("#!/bin/sh\n", False)})
    before = rb.overlay_digest(root, ["fam/run.sh"])
    os.chmod(root / "fam/run.sh", 0o755)

    assert rb.overlay_digest(root, ["fam/run.sh"]) != before


def test_family_identity_covers_only_its_own_declaration(tmp_path: Path) -> None:
    """A family-specific adapter change must not invalidate another family."""
    root = tmp_path / "runners"
    _overlay(
        root,
        {
            "common/runtime/lifecycle.py": ("LIFECYCLE = 1\n", False),
            "simplefold/finalize.py": ("FINALIZE = 1\n", False),
            "esmfold2/predict.py": ("PREDICT = 1\n", False),
        },
    )
    simplefold = ["common/runtime/lifecycle.py", "simplefold/finalize.py"]
    esmfold = ["common/runtime/lifecycle.py", "esmfold2/predict.py"]
    shared_before, esm_before = (
        rb.overlay_digest(root, simplefold),
        rb.overlay_digest(root, esmfold),
    )

    _overlay(root, {"simplefold/finalize.py": ("FINALIZE = 2\n", False)})

    assert rb.overlay_digest(root, simplefold) != shared_before
    assert rb.overlay_digest(root, esmfold) == esm_before

    # A change in the *shared* helper invalidates every family that declares it.
    _overlay(root, {"common/runtime/lifecycle.py": ("LIFECYCLE = 2\n", False)})
    assert rb.overlay_digest(root, simplefold) != shared_before
    assert rb.overlay_digest(root, esmfold) != esm_before


@pytest.mark.parametrize(
    "declared",
    ["/etc/passwd", "../escape.py", "fam/../../escape.py", "fam\\run.sh", "", "fam/./run.sh"],
)
def test_unsafe_overlay_paths_are_rejected(declared: str) -> None:
    with pytest.raises(rb.RuntimeBundleError):
        rb.normalize_overlay_paths([declared])


def test_duplicate_and_colliding_declarations_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(rb.RuntimeBundleError):
        rb.normalize_overlay_paths(["fam/run.sh", "fam/run.sh"])
    root = tmp_path / "runners"
    _overlay(root, {"fam/run.sh": ("#!/bin/sh\n", True)})
    # `fam` contains `fam/run.sh`: the materialized tree cannot be both.
    with pytest.raises(rb.RuntimeBundleError):
        rb.collect_overlay_entries(root, ["fam", "fam/run.sh"])


def test_symlink_source_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "runners"
    _overlay(root, {"real/run.sh": ("#!/bin/sh\n", False)})
    (root / "fam").mkdir()
    os.symlink(root / "real" / "run.sh", root / "fam" / "run.sh")

    with pytest.raises(rb.RuntimeBundleError):
        rb.collect_overlay_entries(root, ["fam/run.sh"])


def test_symlink_inside_a_declared_directory_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "runners"
    _overlay(root, {"fam/run.sh": ("#!/bin/sh\n", False), "outside.txt": ("x\n", False)})
    os.symlink(root / "outside.txt", root / "fam" / "linked.txt")

    with pytest.raises(rb.RuntimeBundleError):
        rb.collect_overlay_entries(root, ["fam"])


def test_materialized_bundle_is_read_only_and_content_addressed(tmp_path: Path) -> None:
    root = tmp_path / "runners"
    store = tmp_path / "runtime-bundles"
    _overlay(root, {"common/runtime/a.py": ("A = 1\n", False), "fam/run.sh": ("#!/bin/sh\n", True)})
    declared = ["common/runtime", "fam/run.sh"]

    digest, path = rb.materialize(root, declared, store)

    assert path == rb.bundle_directory(store, digest)
    assert path.name == f"sha256-{digest.split(':', 1)[1]}"
    assert not (path.stat().st_mode & 0o222)
    assert (path / "common/runtime/a.py").read_text(encoding="utf-8") == "A = 1\n"
    assert (path / "fam/run.sh").stat().st_mode & 0o111
    assert not (path / "common/runtime/a.py").stat().st_mode & 0o111
    # Idempotent: materializing twice returns the same immutable snapshot.
    assert rb.materialize(root, declared, store) == (digest, path)


def test_pinned_resolution_fails_closed_when_the_bundle_is_gone(tmp_path: Path) -> None:
    store = tmp_path / "runtime-bundles"

    assert rb.resolve_pinned(store, "fam", "sha256:" + "a" * 64) is None
    assert rb.resolve_pinned(store, "fam", None) is None
    assert rb.resolve_pinned(store, "fam", "not-a-digest") is None
    assert rb.resolve_pinned(store, "fam", "sha256:deadbeef") is None


def test_gc_keeps_referenced_bundles_and_prunes_only_superseded_ones(tmp_path: Path) -> None:
    root = tmp_path / "runners"
    store = tmp_path / "runtime-bundles"
    _overlay(root, {"fam/run.sh": ("#!/bin/sh\necho one\n", True)})
    old_digest, old_path = rb.materialize(root, ["fam/run.sh"], store)
    _overlay(root, {"fam/run.sh": ("#!/bin/sh\necho two\n", True)})
    new_digest, new_path = rb.materialize(root, ["fam/run.sh"], store)
    # Age the superseded bundle past any retention window.
    past = time.time() - 90 * 86400
    os.utime(old_path, (past, past))

    removed = rb.garbage_collect(store, [new_digest])

    assert removed == [old_digest]
    assert new_path.is_dir()
    assert not old_path.exists()


def test_gc_retains_an_unreferenced_bundle_within_the_retention_window(tmp_path: Path) -> None:
    root = tmp_path / "runners"
    store = tmp_path / "runtime-bundles"
    _overlay(root, {"fam/run.sh": ("#!/bin/sh\n", True)})
    digest, path = rb.materialize(root, ["fam/run.sh"], store)

    assert rb.garbage_collect(store, [], min_age_seconds=14 * 86400) == []
    assert path.is_dir()
    assert rb.garbage_collect(store, []) == [digest]


def test_generated_bytecode_does_not_change_identity(tmp_path: Path) -> None:
    """A declaration's identity is its source, not its interpreter's byproducts.

    ``__pycache__`` is git-ignored, machine-local, and rewritten whenever Python
    imports a helper, so counting it would make two checkouts of one revision
    disagree — and change the digest under a running deployment.
    """
    root = tmp_path / "runners"
    _overlay(root, {"common/runtime/a.py": ("A = 1\n", False)})
    before = rb.overlay_digest(root, ["common/runtime"])
    cache = root / "common/runtime/__pycache__"
    cache.mkdir()
    (cache / "a.cpython-312.pyc").write_bytes(b"\x00\x01machine-local")

    assert rb.overlay_digest(root, ["common/runtime"]) == before
    digest, path = rb.materialize(root, ["common/runtime"], tmp_path / "runtime-bundles")
    assert digest == before
    assert not (path / "common/runtime/__pycache__").exists()


def test_materialized_content_always_hashes_to_its_directory_name(tmp_path: Path) -> None:
    """The digest and the bytes under it come from one enumeration of the source."""
    from revocompute import runtime_bundle as module

    root = tmp_path / "runners"
    _overlay(root, {"fam/a.py": ("A = 1\n", False), "fam/run.sh": ("#!/bin/sh\n", True)})
    calls = 0
    real = module._walk_declaration

    def counting_walk(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    module._walk_declaration = counting_walk
    try:
        digest, path = module.materialize(root, ["fam"], tmp_path / "store")
    finally:
        module._walk_declaration = real

    assert calls == 1, "materialize must hash and copy from a single enumeration"
    assert module.overlay_digest(path, ["fam"]) == digest


def test_declared_but_unresolvable_source_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "runners"
    root.mkdir()

    with pytest.raises(rb.RuntimeBundleError):
        rb.collect_overlay_entries(root, ["missing/run.sh"])


def test_index_round_trips_and_rejects_a_binding_to_a_missing_bundle(tmp_path: Path) -> None:
    store = tmp_path / "runtime-bundles"
    root = tmp_path / "runners"
    _overlay(root, {"fam/run.sh": ("#!/bin/sh\n", True)})
    digest, path = rb.materialize(root, ["fam/run.sh"], store)

    rb.write_index(store, {"fam": digest})

    assert rb.load_index(store) == {"fam": digest}
    assert rb.index_digests(store) == {digest}
    assert rb.resolve_for_submission(store, rb.load_index(store), "fam")["sha256"] == digest
    # A family with no overlay declares no bundle: the key is absent, not None.
    assert rb.resolve_for_submission(store, rb.load_index(store), "other") is None
    # A digest override selects the candidate the live test just materialized.
    assert rb.resolve_for_submission(store, {}, "fam", digest=digest)["sha256"] == digest
    # A family that declares an overlay but whose snapshot is gone must fail
    # loudly, not submit a task that cannot mount its own entrypoint.
    with pytest.raises(rb.RuntimeBundleError, match="unavailable"):
        rb.resolve_for_submission(store, {"fam": "sha256:" + "f" * 64}, "fam")
