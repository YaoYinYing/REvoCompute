# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Runtime Bundle deployment lifecycle: candidate, activation, pinning, GC.

The property under test is that a deployment change never rewrites what an
already-submitted Task will execute, and never deletes the code it will need.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "run"))
sys.path.insert(0, str(ROOT / "tests"))

from revocompute import runtime_bundle as rb  # noqa: E402
from revocompute_ctl import steps as steps_mod  # noqa: E402
from revocompute_ctl.registry import RuntimeFamily  # noqa: E402


class _State:
    def __init__(self, root: Path, values: dict[str, str] | None = None):
        self.root = root
        self._values = values or {}

    def server_dir(self) -> str:
        return str(self.root / "server")

    def get(self, key: str) -> str:
        return self._values.get(key, "")


def _family(root: Path, name: str = "demo") -> RuntimeFamily:
    family_root = root / "runners" / name
    (family_root).mkdir(parents=True)
    (family_root / "run.sh").write_text("#!/bin/sh\necho one\n", encoding="utf-8")
    return RuntimeFamily(name, "1", f"{name}.def", f"{name}.sif", str(root / "images" / f"{name}.sif"), root=family_root, runtime_overlay=(f"{name}/run.sh",))


def _pin_task(state: _State, task_id: str, digest: str, status: str = "queued", job: str | None = None) -> None:
    server = Path(state.server_dir())
    server.mkdir(parents=True, exist_ok=True)
    database = server / "revocompute.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS tasks "
            "(task_id TEXT, status TEXT, input_form TEXT, slurm_job_id TEXT, container_id TEXT)"
        )
        connection.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, NULL)",
            (task_id, status, json.dumps({"runtime_bundle_sha256": digest}), job),
        )


def test_candidate_materialization_does_not_publish_and_activation_makes_it_eligible(tmp_path: Path) -> None:
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    family = _family(tmp_path)

    candidate = steps_mod.materialize_runner_bundles(state, [family], activate=False)
    digest_x = candidate["demo"]

    # Validation has a snapshot to test, but a new submission must fail closed
    # rather than pin nothing: the candidate is not yet eligible.
    assert rb.resolve_pinned(store, digest_x) is not None
    assert rb.load_index(store) == {}
    with pytest.raises(rb.RuntimeBundleError, match="no published bundle"):
        rb.resolve_for_submission(store, rb.load_index(store), "demo", declares_overlay=True)

    steps_mod.materialize_runner_bundles(state, [family], digests=candidate)
    assert rb.load_index(store) == {"demo": digest_x}
    assert rb.resolve_for_submission(store, rb.load_index(store), "demo", declares_overlay=True) == digest_x


def test_a_task_pinned_to_x_still_launches_x_after_y_activates(tmp_path: Path) -> None:
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    family = _family(tmp_path)

    digest_x = steps_mod.materialize_runner_bundles(state, [family])["demo"]
    _pin_task(state, "task-a", digest_x)
    steps_mod.prune_runtime_bundles(state, {})

    # Runtime code changes; a new bundle Y is built and activated.
    (family.root / "run.sh").write_text("#!/bin/sh\necho two\n", encoding="utf-8")
    digest_y = steps_mod.materialize_runner_bundles(state, [family])["demo"]
    assert digest_y != digest_x

    # Y is what a new Task pins ...
    assert rb.resolve_for_submission(store, rb.load_index(store), "demo", declares_overlay=True) == digest_y
    # ... while the queued Task still resolves exactly the code it was submitted
    # against, because its pin is read from the immutable task snapshot.
    assert rb.resolve_for_submission(
        store, rb.load_index(store), "demo", declares_overlay=True, digest=digest_x
    ) == digest_x
    assert rb.resolve_pinned(store, digest_x) is not None

    # GC must keep both: X because a queued Task pinned it, Y because it is active.
    steps_mod.prune_runtime_bundles(state, {})
    assert rb.resolve_pinned(store, digest_x) is not None
    assert rb.resolve_pinned(store, digest_y) is not None


def test_failed_candidate_validation_leaves_the_active_bundle_untouched(tmp_path: Path) -> None:
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    family = _family(tmp_path)
    active = steps_mod.materialize_runner_bundles(state, [family])["demo"]

    # A source edit that fails validation still materializes a snapshot (that is
    # what gets tested), but the published binding is unchanged.
    (family.root / "run.sh").write_text("#!/bin/sh\necho broken\n", encoding="utf-8")
    steps_mod.materialize_runner_bundles(state, [family], activate=False)

    assert rb.load_index(store) == {"demo": active}
    assert rb.resolve_for_submission(store, rb.load_index(store), "demo", declares_overlay=True) == active


def test_gc_keeps_every_family_the_active_index_binds(tmp_path: Path) -> None:
    """Pruning on behalf of one family must not delete another family's code."""
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    alpha = _family(tmp_path, "alpha")
    beta = _family(tmp_path, "beta")

    steps_mod.materialize_runner_bundles(state, [alpha, beta])
    bound = rb.load_index(store)
    assert set(bound) == {"alpha", "beta"}

    # A live test for alpha alone finishes and prunes: beta's bundle is in the
    # index and must survive.
    steps_mod.prune_runtime_bundles(state, {"alpha": bound["alpha"]})

    assert rb.load_index(store) == bound
    assert rb.resolve_pinned(store, bound["beta"]) is not None


def test_a_malformed_task_pin_is_inert(tmp_path: Path) -> None:
    """A damaged pin must not fault GC, nor keep an unreferenced bundle alive."""
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store), "RUNTIME_BUNDLE_RETENTION_DAYS": "0"})
    family = _family(tmp_path)
    digest = steps_mod.materialize_runner_bundles(state, [family], activate=False)["demo"]
    _pin_task(state, "legacy", "not-a-digest")

    steps_mod.prune_runtime_bundles(state, {})

    assert rb.resolve_pinned(store, digest) is None
    assert rb.load_index(store) == {}


def test_terminal_tasks_do_not_hold_a_bundle_alive(tmp_path: Path) -> None:
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    family = _family(tmp_path)
    digest = steps_mod.materialize_runner_bundles(state, [family], activate=False)["demo"]
    _pin_task(state, "done", digest, status="succeeded")

    assert steps_mod.task_pinned_bundle_digests(state) == set()


def test_a_terminal_row_that_still_owns_a_job_keeps_its_bundle(tmp_path: Path) -> None:
    """Cancellation writes the status before the scheduler confirms the stop."""
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    family = _family(tmp_path)
    digest = steps_mod.materialize_runner_bundles(state, [family], activate=False)["demo"]
    _pin_task(state, "cancelled-but-running", digest, status="cancelled", job="64352")

    assert steps_mod.task_pinned_bundle_digests(state) == {digest}
    steps_mod.prune_runtime_bundles(state, {})

    assert rb.resolve_pinned(store, digest) is not None
