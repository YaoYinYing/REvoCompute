# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Runtime Bundle deployment lifecycle: candidate, activation, pinning, GC.

The property under test is that a deployment change never rewrites what an
already-submitted Task will execute, and never deletes the code it will need.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "run"))
sys.path.insert(0, str(ROOT / "tests"))

from revocompute import runtime_bundle as rb  # noqa: E402
from revocompute import runner_live_test  # noqa: E402
from revocompute_ctl import steps as steps_mod  # noqa: E402
from revocompute.runner_registry import RuntimeFamily  # noqa: E402


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


def _pin_task(
    state: _State,
    task_id: str,
    digest: str,
    status: str = "queued",
    job: str | None = None,
) -> None:
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
            (task_id, status, json.dumps({"runtime_bundles": {"demo": digest}}), job),
        )


def _authorize(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the live-test receipt these activation-mechanics tests aren't about."""
    monkeypatch.setattr(
        "revocompute.runner_live_test.receipt_valid_for_bundle", lambda *_args, **_kwargs: True
    )


def _scheduler_reports(monkeypatch: pytest.MonkeyPatch, job_ids: set[str]) -> None:
    """Make ``squeue`` list exactly ``job_ids`` and resolve on PATH."""
    monkeypatch.setattr(steps_mod.shutil, "which", lambda name: f"/usr/bin/{name}")

    def _run(argv, **_kwargs):
        stdout = "".join(f"{job_id}\n" for job_id in sorted(job_ids))
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(steps_mod.subprocess, "run", _run)


def _scheduler_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make liveness unanswerable: the query tool is not installed."""
    monkeypatch.setattr(steps_mod.shutil, "which", lambda _name: None)


def test_candidate_materialization_does_not_publish_and_activation_makes_it_eligible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    family = _family(tmp_path)
    _authorize(monkeypatch)

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


def test_a_task_pinned_to_x_still_launches_x_after_y_activates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    family = _family(tmp_path)
    _authorize(monkeypatch)

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


def test_failed_candidate_validation_leaves_the_active_bundle_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    family = _family(tmp_path)
    _authorize(monkeypatch)
    active = steps_mod.materialize_runner_bundles(state, [family])["demo"]

    # A source edit that fails validation still materializes a snapshot (that is
    # what gets tested), but the published binding is unchanged.
    (family.root / "run.sh").write_text("#!/bin/sh\necho broken\n", encoding="utf-8")
    steps_mod.materialize_runner_bundles(state, [family], activate=False)

    assert rb.load_index(store) == {"demo": active}
    assert rb.resolve_for_submission(store, rb.load_index(store), "demo", declares_overlay=True) == active


def test_gc_keeps_every_family_the_active_index_binds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pruning on behalf of one family must not delete another family's code."""
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    alpha = _family(tmp_path, "alpha")
    beta = _family(tmp_path, "beta")
    _authorize(monkeypatch)

    steps_mod.materialize_runner_bundles(state, [alpha, beta])
    bound = rb.load_index(store)
    assert set(bound) == {"alpha", "beta"}

    # A live test for alpha alone finishes and prunes: beta's bundle is in the
    # index and must survive.
    steps_mod.prune_runtime_bundles(state, {"alpha": bound["alpha"]})

    assert rb.load_index(store) == bound
    assert rb.resolve_pinned(store, bound["beta"]) is not None


def _rollback_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    family = _family(tmp_path)
    _authorize(monkeypatch)
    previous = steps_mod.materialize_runner_bundles(state, [family])["demo"]
    (family.root / "run.sh").write_text("#!/bin/sh\necho two\n", encoding="utf-8")
    current = steps_mod.materialize_runner_bundles(state, [family])["demo"]
    assert current != previous
    assert rb.load_index(store) == {"demo": current}
    monkeypatch.setattr(
        "revocompute_ctl.steps.load_instance_families", lambda _state: [family]
    )
    return store, state, family, previous, current


def _refuse_rollback(store: Path, state: _State, digest: str) -> None:
    before = rb.index_path(store).read_bytes()
    with pytest.raises(SystemExit) as excinfo:
        steps_mod.cmd_rollback_bundle(state, "demo", digest)
    assert excinfo.value.code == 1
    assert rb.index_path(store).read_bytes() == before


def test_rollback_switches_to_a_prior_accepted_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store, state, family, previous, current = _rollback_setup(tmp_path, monkeypatch)
    seen: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        "revocompute.runner_live_test.receipt_valid_for_bundle",
        lambda _state, selected, digest, **kwargs: seen.append(
            (selected.name, digest, kwargs)
        )
        or True,
    )

    steps_mod.cmd_rollback_bundle(state, "demo", previous)

    assert rb.load_index(store) == {"demo": previous}
    assert seen == [
        ("demo", previous, {"artifact": family.slurm_image, "candidate_bundles": None})
    ]
    # The superseded snapshot is still materialized and verified: rollback is
    # an index switch, never a rewrite or prune.
    assert rb.resolve_pinned(store, current) is not None
    assert rb.resolve_pinned(store, previous) is not None
    out = capsys.readouterr().out
    assert f"demo: {current} -> {previous}" in out


def test_rollback_persists_its_intent_before_the_index_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash after the intent write must not revert to the checkout."""
    store, state, _family, previous, _current = _rollback_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "revocompute.runner_live_test.receipt_valid_for_bundle", lambda *_args, **_kwargs: True
    )

    def fail_write(*_args, **_kwargs):
        raise OSError("simulated index write failure")

    monkeypatch.setattr(rb, "write_index", fail_write)
    with pytest.raises(OSError):
        steps_mod.cmd_rollback_bundle(state, "demo", previous)

    assert rb.load_rollback_holds(store) == {"demo": previous}


@pytest.mark.parametrize("failure", ["unknown", "missing", "corrupt", "no-receipt"])
def test_rollback_refusal_leaves_the_index_byte_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    store, state, _family_obj, previous, _current = _rollback_setup(tmp_path, monkeypatch)
    target = previous
    if failure == "unknown":
        target = "sha256:" + "0" * 64
    elif failure == "missing":
        rb._remove_tree(rb.bundle_directory(store, previous))
    elif failure == "corrupt":
        stored = rb.bundle_directory(store, previous) / "demo" / "run.sh"
        stored.chmod(0o644)
        stored.write_text("#!/bin/sh\necho tampered\n", encoding="utf-8")
    else:
        monkeypatch.setattr(
            "revocompute.runner_live_test.receipt_valid_for_bundle", lambda *_a, **_k: False
        )

    _refuse_rollback(store, state, target)


def test_rollback_refuses_a_family_without_an_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store, state, family, previous, _current = _rollback_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "revocompute_ctl.steps.load_instance_families",
        lambda _state: [replace(family, runtime_overlay=())],
    )

    _refuse_rollback(store, state, previous)
    assert "no runtime overlay" in capsys.readouterr().err


def test_rollback_refuses_an_unknown_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store, state, _family_obj, previous, _current = _rollback_setup(tmp_path, monkeypatch)
    monkeypatch.setattr("revocompute_ctl.steps.load_instance_families", lambda _state: [])

    _refuse_rollback(store, state, previous)
    assert "Unknown Runner Family" in capsys.readouterr().err


def _live_pass(monkeypatch: pytest.MonkeyPatch, family: RuntimeFamily, *, passed: bool = True) -> None:
    """Run the activation path without hardware, keeping the real receipt gate."""
    monkeypatch.setattr("revocompute.runner_live_test.load_plugin_families", lambda _root: [family])
    monkeypatch.setattr(
        "revocompute.runner_live_test.prepare_live_test_server_image", lambda *_args: None
    )
    monkeypatch.setattr(
        "revocompute.runner_live_test.RunnerLiveTestWorker.run",
        lambda *_args, **_kwargs: SimpleNamespace(passed=passed),
    )
    monkeypatch.setattr("revocompute_ctl.attestation.write_runner_attestation", lambda *_args: None)


def test_rollback_survives_a_subsequent_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, state, family, previous, current = _rollback_setup(tmp_path, monkeypatch)

    steps_mod.cmd_rollback_bundle(state, "demo", previous)
    assert rb.load_rollback_holds(store) == {"demo": previous}

    # The checkout still carries the newer sources; a restart must not undo the
    # operator's choice by re-materializing and re-publishing them.
    steps_mod.materialize_runner_bundles(state, [family])

    assert rb.load_index(store) == {"demo": previous}
    assert rb.load_rollback_holds(store) == {"demo": previous}
    assert rb.resolve_for_submission(store, rb.load_index(store), "demo", declares_overlay=True) == previous
    # The superseded snapshot is untouched, not pruned by the restart.
    assert rb.resolve_pinned(store, current) is not None


def test_a_passing_live_test_clears_the_hold_and_activates_the_validated_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, state, family, previous, current = _rollback_setup(tmp_path, monkeypatch)
    steps_mod.cmd_rollback_bundle(state, "demo", previous)
    _live_pass(monkeypatch, family)

    assert runner_live_test.run_live_tests(
        state, runner="demo", task=None, collection="smoke", all_runners=False
    )

    assert rb.load_rollback_holds(store) == {}
    assert rb.load_index(store) == {"demo": current}
    assert rb.resolve_for_submission(store, rb.load_index(store), "demo", declares_overlay=True) == current


def test_a_failed_live_test_preserves_the_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, state, family, previous, _current = _rollback_setup(tmp_path, monkeypatch)
    steps_mod.cmd_rollback_bundle(state, "demo", previous)
    _live_pass(monkeypatch, family, passed=False)

    assert not runner_live_test.run_live_tests(
        state, runner="demo", task=None, collection="smoke", all_runners=False
    )

    assert rb.load_rollback_holds(store) == {"demo": previous}
    assert rb.load_index(store) == {"demo": previous}


def test_a_missing_held_snapshot_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, state, family, previous, _current = _rollback_setup(tmp_path, monkeypatch)
    steps_mod.cmd_rollback_bundle(state, "demo", previous)
    rb._remove_tree(rb.bundle_directory(store, previous))

    with pytest.raises(rb.RuntimeBundleError, match="held"):
        rb.resolve_for_submission(store, rb.load_index(store), "demo", declares_overlay=True)
    with pytest.raises(rb.RuntimeBundleError, match="held"):
        steps_mod.materialize_runner_bundles(state, [family])


def test_a_staged_receipt_does_not_authorize_a_plain_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, state, family, _previous, current = _rollback_setup(tmp_path, monkeypatch)
    (family.root / "run.sh").write_text("#!/bin/sh\necho three\n", encoding="utf-8")
    staged = Path(f"{family.slurm_image}.next")
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"candidate")
    seen: list[str] = []

    def _staged_only(_state, _family, _digest, *, artifact=None, candidate_bundles=None):
        seen.append(Path(artifact).name)
        return Path(artifact).name.endswith(".next")

    monkeypatch.setattr("revocompute.runner_live_test.receipt_valid_for_bundle", _staged_only)

    # A restart activates the artifact execution loads, the active SIF; a
    # receipt for the staged candidate cannot authorize it.
    steps_mod.materialize_runner_bundles(state, [family])
    assert rb.load_index(store) == {"demo": current}

    # The live-test PASS activates the exact pair it ran, the candidate.
    _live_pass(monkeypatch, family)
    assert runner_live_test.run_live_tests(
        state, runner="demo", task=None, collection="smoke", all_runners=False
    )
    candidate = rb.overlay_digest(family.root.parent, family.runtime_overlay)
    assert rb.load_index(store) == {"demo": candidate}
    assert seen[-1] == "demo.sif.next"


def test_rollback_bundle_cli_contract() -> None:
    from revocompute_ctl.__main__ import parse_args

    digest = "sha256:" + "a" * 64
    subcommand, reset_username, flags = parse_args(
        ["rollback-bundle", "--runner", "demo", "--digest", digest]
    )
    assert (subcommand, reset_username, flags.runner, flags.digest) == (
        "rollback-bundle",
        "",
        "demo",
        digest,
    )
    for argv in (
        ["rollback-bundle", "--runner", "demo"],
        ["rollback-bundle", "--digest", digest],
        ["restart", "--digest", digest],
    ):
        with pytest.raises(SystemExit):
            parse_args(argv)


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


def test_a_terminal_row_the_scheduler_still_lists_keeps_its_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation writes the status before the scheduler confirms the stop.

    The scheduler is the authority on liveness, not the row's age: an allocation
    may legitimately run longer than the retention window, so a still-listed job
    keeps its bundle however old the terminal status is.
    """
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store), "RUNTIME_BUNDLE_RETENTION_DAYS": "14"})
    family = _family(tmp_path)
    digest = steps_mod.materialize_runner_bundles(state, [family], activate=False)["demo"]
    _pin_task(state, "cancelled-but-running", digest, status="cancelled", job="64352")
    _scheduler_reports(monkeypatch, {"64352"})

    assert steps_mod.task_pinned_bundle_digests(state) == {digest}
    # Even the retention window cannot expire a bundle the scheduler still holds.
    bundle = store / f"sha256-{digest.split(':', 1)[1]}"
    past = time.time() - 90 * 86400
    os.utime(bundle, (past, past))
    steps_mod.prune_runtime_bundles(state, {})

    assert rb.resolve_pinned(store, digest) is not None


def test_an_old_finished_row_does_not_hold_a_bundle_forever(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Normal completion leaves slurm_job_id set, so the handle must be settled.

    Once the scheduler no longer lists the job the handle carries no liveness,
    so the bundle becomes eligible like any other unreferenced one instead of
    being pinned forever by a historical job id.
    """
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store), "RUNTIME_BUNDLE_RETENTION_DAYS": "14"})
    family = _family(tmp_path)
    digest = steps_mod.materialize_runner_bundles(state, [family], activate=False)["demo"]
    _pin_task(state, "long-finished", digest, status="finished", job="4641")
    _scheduler_reports(monkeypatch, set())

    assert steps_mod.task_pinned_bundle_digests(state) == set()
    # Age the bundle past the retention window too, so the prune runs rather
    # than being held back by the second, independent safety net.
    bundle = store / f"sha256-{digest.split(':', 1)[1]}"
    past = time.time() - 90 * 86400
    os.utime(bundle, (past, past))
    steps_mod.prune_runtime_bundles(state, {})

    assert rb.resolve_pinned(store, digest) is None


def test_liveness_that_cannot_be_established_keeps_the_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unanswerable question is not a licence to delete executable code."""
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    family = _family(tmp_path)
    digest = steps_mod.materialize_runner_bundles(state, [family], activate=False)["demo"]
    _pin_task(state, "unsettled", digest, status="finished", job="4641")
    _scheduler_unavailable(monkeypatch)

    assert steps_mod.task_pinned_bundle_digests(state) == {digest}


def test_a_terminal_row_with_a_non_numeric_handle_is_assumed_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy ``srun-`` handle cannot be queried, so it is not assumed dead."""
    store = tmp_path / "runtime-bundles"
    state = _State(tmp_path, {"RUNTIME_BUNDLE_DIR": str(store)})
    family = _family(tmp_path)
    digest = steps_mod.materialize_runner_bundles(state, [family], activate=False)["demo"]
    _pin_task(state, "legacy-handle", digest, status="failed", job="srun-4711")
    _scheduler_reports(monkeypatch, set())

    assert steps_mod.task_pinned_bundle_digests(state) == {digest}
