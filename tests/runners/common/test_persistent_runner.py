# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Shared persistent-runner failure classification and recovery provenance.

A plugin reports a recoverable OOM as an outcome, and only that path may walk
the declared resource-fallback ladder. An exception that reaches the generic
handler was never classified as recoverable, so it must fail the item as
``FAILED_RUNTIME`` on its first attempt: retrying a validation, filesystem, or
model bug under a smaller plan repeats the same bug and spends the ladder on
it. These tests pin both halves — no fallback for an unclassified exception,
and the ladder still walked for a real OOM — with a fake plugin that counts how
many times each item actually ran.

The second half of the file covers the adaptive-OOM provenance and the item
machinery that makes persistent batch execution equivalent to single-input
execution: per-item requested-versus-effective capture, item-identity mapping
regardless of execution order, duplicate/lost prevention, restart reconstruction,
and the bounded retry discipline.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMMON = ROOT / "docker/runners/common/runtime"
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

from persistent_runner import (  # noqa: E402
    NUMERICAL_BACKEND,
    OUTCOME_OOM,
    OUTCOME_SUCCESS,
    RESOURCE_ONLY,
    SCIENTIFIC_OUTPUT,
    UNSAFE,
    PersistentTask,
    PlanSequence,
    classify_adjustments,
    exit_code_for,
)


class FakePlugin:
    """The ``_self_check`` fake, plus a hook to raise from ``run_item``."""

    runner = "fake"
    runner_version = "1"
    model_revision = "m1"
    runtime_fingerprint = "fp"

    def __init__(self) -> None:
        self.loads = 0
        self.applied: dict[str, list[dict]] = {}
        self.raise_on: dict[str, str] = {}
        self.oom_once: set[str] = set()

    def initialize_runtime(self, execution):
        self.loads += 1
        return {"loaded": self.loads}

    def finalize(self, runtime):
        pass

    def runtime_usage(self, runtime):
        return (100, 100, 120)

    def available_vram_mb(self, runtime):
        return 40000

    def device_profile(self, runtime):
        return {
            "vendor": "nvidia",
            "model": "A100-PCIE-40GB",
            "compute_capability": "8.0",
            "total_vram_mb": 40960,
            "mig_profile": "",
        }

    def run_item(self, runtime, payload, adjustments, work_dir, execution):
        identifier = payload["id"]
        self.applied.setdefault(identifier, []).append(dict(adjustments))
        if identifier in self.raise_on:
            raise ValueError(self.raise_on[identifier])
        if identifier in self.oom_once and not adjustments:
            self.oom_once.discard(identifier)
            return OUTCOME_OOM, 1000, 1200, 900, "CUDA_OOM"
        with open(Path(work_dir) / "result.txt", "w", encoding="utf-8") as handle:
            handle.write(str(adjustments.get("sample_group_size", "1")))
        return OUTCOME_SUCCESS, 1000, 1200, 900, ""

    def validate_item(self, work_dir, payload, adjustments):
        assert (Path(work_dir) / "result.txt").is_file()

    def finalize_task(self, output_dir, manifest):
        pass


class VerbosePlugin(FakePlugin):
    """A fake plugin that records each attempt and resolves effective parameters.

    Extends :class:`FakePlugin` with the two hooks the provenance audit needs: a
    per-attempt effective *scientific* parameter set (a family that resolves its
    own plan supplies one), and a work-item result that names the item itself, so
    item-identity mapping is provable rather than assumed. ``calls`` records the
    adjustments of every attempt, in the order they ran.
    """

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict] = []
        self.effective: dict = {}
        self.effective_by_adjustment: dict = {}
        self.always_oom: set[str] = set()

    def effective_parameters(self, payload, adjustments):
        """A family's resolution: the effective set depends on the plan applied."""
        if self.effective_by_adjustment:
            key = tuple(sorted((str(k), v) for k, v in dict(adjustments or {}).items()))
            return dict(self.effective_by_adjustment.get(key, self.effective))
        return dict(self.effective)

    def run_item(self, runtime, payload, adjustments, work_dir, execution):
        identifier = payload["id"]
        self.calls.append({"id": identifier, "adjustments": dict(adjustments)})
        self.applied.setdefault(identifier, []).append(dict(adjustments))
        if identifier in self.raise_on:
            raise ValueError(self.raise_on[identifier])
        if identifier in self.always_oom or (identifier in self.oom_once and not adjustments):
            self.oom_once.discard(identifier)
            return OUTCOME_OOM, 1000, 1200, 900, "CUDA_OOM"
        with open(Path(work_dir) / "result.txt", "w", encoding="utf-8") as handle:
            handle.write(identifier)
        return OUTCOME_SUCCESS, 1000, 1200, 900, ""


def _config(items, plan_order):
    return {
        "task_id": "t1",
        "runner": "fake",
        "items": items,
        "execution": {"max_item_attempts": 2},
        "resource_adaptation": {
            "stage": "recover",
            "fallback_plans": [
                {"label": "one", "adjustments": {"sample_group_size": 1}},
                {"label": "two", "adjustments": {"sample_group_size": 2}},
                {"label": "three", "adjustments": {"sample_group_size": 3}},
            ],
        },
        "resource_guidance": {"plan_order": plan_order},
    }


def test_a_generic_runtime_exception_is_a_runtime_failure_and_consumes_no_fallback():
    items = [{"id": "p0", "length": 10}, {"id": "p1", "length": 20}, {"id": "p2", "length": 30}]
    config = _config(items, ["", "one", "two", "three"])
    plugin = FakePlugin()
    plugin.raise_on["p1"] = "output validation failed"

    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()

    failed = manifest["items"][1]
    assert failed["status"] == "FAILED_RUNTIME", failed
    assert failed["attempts"] == 1
    assert plugin.applied["p1"] == [{}], "an unclassified exception must not be retried"
    # The other items are unaffected.
    assert [entry["status"] for entry in manifest["items"]] == ["SUCCEEDED", "FAILED_RUNTIME", "SUCCEEDED"]
    assert manifest["outcome"] == "PARTIAL_SUCCESS", manifest["outcome"]
    # The observation agrees with the item state: an ordinary exception is an
    # error row, never a censored OOM row.
    assert failed["resource_events"][-1]["outcome"] == "error", failed["resource_events"]
    assert failed["resource_events"][-1]["plan_label"] == ""


def test_an_explicit_oom_still_walks_the_declared_fallback_ladder():
    items = [{"id": "p0", "length": 10}]
    config = _config(items, ["", "one", "two", "three"])
    plugin = FakePlugin()
    plugin.oom_once.add("p0")

    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()

    entry = manifest["items"][0]
    assert entry["status"] == "SUCCEEDED", entry
    assert entry["attempts"] >= 2
    assert [event["plan_label"] for event in entry["resource_events"]] == ["", "one"]
    assert entry["resource_events"][0]["outcome"] == "oom"
    # The later plan really ran with its declared adjustment applied.
    assert plugin.applied["p0"] == [{}, {"sample_group_size": 1}]


def _sequence(profiles):
    return PlanSequence(
        {"stage": "avoid", "fallback_plans": [{"label": "split", "adjustments": {"sample_group_size": 1}}]},
        {"plan_order": ["", "split"], "profiles": profiles},
        {"max_item_attempts": 2},
    )


def test_guidance_binds_only_the_exact_revision_runtime_and_device():
    device = {"model": "A100-PCIE-40GB", "total_vram_mb": 40960}
    profile_fast = {
        "model_revision": "fast",
        "runtime_fingerprint": "fp-fast",
        "device_model": "A100-PCIE-40GB",
        "total_vram_mb": 40960,
        "known_failing_plans": [""],
        "avoid_scale_at_or_above": 100,
    }
    profile_standard = {
        "model_revision": "standard",
        "runtime_fingerprint": "fp-standard",
        "device_model": "A100-PCIE-40GB",
        "total_vram_mb": 40960,
        "known_failing_plans": [],
        "avoid_scale_at_or_above": 500,
    }
    sequence = _sequence([profile_fast, profile_standard])

    sequence.bind_identity("fast", "fp-fast", device)
    assert sequence.known_failing == {""}
    assert sequence.avoid_at_or_above == 100

    # Another revision on the same GPU must not inherit the evidence.
    sequence.bind_identity("standard", "fp-standard", device)
    assert sequence.known_failing == set()
    assert sequence.avoid_at_or_above == 500
    assert sequence.plan_for(0, [], scale=100).label == ""
    assert sequence.plan_for(0, [], scale=500).label == "split"

    # A different runtime of the same revision is not a match either.
    sequence.bind_identity("fast", "fp-other", device)
    assert sequence.known_failing == set()
    assert sequence.avoid_at_or_above is None

    # Nor is a different device.
    sequence.bind_identity("fast", "fp-fast", {"model": "H100-PCIE-80GB", "total_vram_mb": 81559})
    assert sequence.known_failing == set()
    assert sequence.avoid_at_or_above is None


def test_a_cross_revision_profile_never_skips_the_default_path():
    items = [{"id": "p0", "length": 10}]
    config = _config(items, ["", "one"])
    config["resource_adaptation"] = {
        **config["resource_adaptation"],
        "stage": "avoid",
        "fallback_plans": [{"label": "split", "adjustments": {"sample_group_size": 1}}],
    }
    config["resource_guidance"] = {
        "plan_order": ["", "split"],
        "profiles": [
            {
                "model_revision": "fast",
                "runtime_fingerprint": "fp-fast",
                "device_model": "A100-PCIE-40GB",
                "total_vram_mb": 40960,
                "known_failing_plans": [""],
                "avoid_scale_at_or_above": 0,
            }
        ],
    }
    plugin = FakePlugin()
    plugin.model_revision = "standard"
    plugin.runtime_fingerprint = "fp-standard"

    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()

    assert manifest["skipped_known_failure_plans"] == []
    entry = manifest["items"][0]
    assert entry["status"] == "SUCCEEDED", entry
    assert entry["attempts"] == 1, entry
    assert plugin.applied["p0"] == [{}], "the default path must still run"


def test_a_broken_runtime_never_becomes_the_reason_success_reports_failure():
    """A committed item is a result, so a failed measurement is only bookkeeping.

    The device can die after inference — the post-run residency read raises — and
    a restart can itself fail. Neither may turn a published item into a runtime
    failure or abort the remaining items.
    """

    class DeadMeasurement(FakePlugin):
        def __init__(self) -> None:
            super().__init__()
            self.die_once = False

        def runtime_usage(self, runtime):
            if self.die_once:
                # One-shot: the context dies exactly at the success
                # observation's read, as a card that faults after inference.
                self.die_once = False
                raise RuntimeError("CUDA error: no kernel image is available")
            return super().runtime_usage(runtime)

    items = [{"id": "p0", "length": 10}, {"id": "p1", "length": 20}]
    config = _config(items, ["", "one"])
    plugin = DeadMeasurement()

    original = plugin.run_item

    def then_die(*args, **kwargs):
        result = original(*args, **kwargs)
        plugin.die_once = True
        return result

    plugin.run_item = then_die
    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()

    # Both items succeeded, so the task did not abort on the failed read.
    assert manifest["outcome"] == "SUCCESS", manifest["outcome"]
    assert [entry["status"] for entry in manifest["items"]] == ["SUCCEEDED", "SUCCEEDED"]

    # A CUDA fault that cannot be restarted fails its own item and leaves the
    # remaining items to run, rather than taking the task down with it.
    class Unrestartable(FakePlugin):
        def __init__(self) -> None:
            super().__init__()
            self.loads = 0

        def initialize_runtime(self, execution):
            self.loads += 1
            if self.loads > 1:
                raise RuntimeError("CUDA error: cannot reinitialize context")
            return {"loaded": self.loads}

        def run_item(self, runtime, payload, adjustments, work_dir, execution):
            if payload["id"] == "p0":
                raise RuntimeError("CUDA error: an illegal memory access was encountered")
            return super().run_item(runtime, payload, adjustments, work_dir, execution)

    plugin = Unrestartable()
    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()

    assert [entry["status"] for entry in manifest["items"]] == ["FAILED_RUNTIME", "SUCCEEDED"]
    assert manifest["outcome"] == "PARTIAL_SUCCESS", manifest["outcome"]


# ---------------------------------------------------------------------------
# Recovery provenance (requested vs effective)
# ---------------------------------------------------------------------------


def test_recovery_action_classification_is_by_scientific_impact():
    """TODO.md 8: every recovery action carries its scientific-impact class.

    ``sample_group_size`` changes how many samples each draw takes together, and
    the samples inside a group share that group's stochastic stream, so the same
    requested samples come out with different coordinates — a scientific-output
    change, reported as one, never as a neutral resource knob. A kernel-backend
    change may change floating behavior; a plan naming a scientific parameter is
    an action automatic recovery must never be able to take. The most impactful
    key in a combined plan decides the whole action's class.
    """
    assert classify_adjustments(None) == ""
    assert classify_adjustments({}) == "", "the default path is not a recovery action"
    assert classify_adjustments({"sample_group_size": 1}) == SCIENTIFIC_OUTPUT
    assert classify_adjustments({"cache_clear": True}) == RESOURCE_ONLY
    assert classify_adjustments({"batch_size": 1, "cache_clear": True}) == RESOURCE_ONLY
    assert classify_adjustments({"kernel_backend": "reference"}) == NUMERICAL_BACKEND
    # Ranked: a scientific-output change dominates the backend change it ships with.
    assert classify_adjustments({"sample_group_size": 1, "kernel_backend": "reference"}) == SCIENTIFIC_OUTPUT
    # A key outside the execution-only vocabulary is unsafe by construction.
    assert classify_adjustments({"num_diffusion_samples": 2}) == UNSAFE
    assert classify_adjustments({"sample_group_size": 1, "model_variant": "standard"}) == UNSAFE


def test_the_shared_action_vocabulary_matches_the_runner_adjustment_vocabulary():
    """TODO.md 1/8: the classification vocabulary is bound to the runner's own.

    ``ADJUSTMENT_ACTIONS`` and the families' ``RESOURCE_ONLY_PARAMETERS`` are two
    spellings of the same execution-only vocabulary; a key added to one and
    missed in the other would be silently classified ``unsafe``. This binds them,
    and binds both to the estimator's ``ADAPTATION_KEYS`` (the server-side
    admission vocabulary), so drift fails loudly here rather than at runtime.
    """
    import importlib.util
    from pathlib import Path as _Path

    from persistent_runner import ADJUSTMENT_ACTIONS, RECOVERY_ACTION_CLASSES

    root = _Path(__file__).resolve().parents[3]
    family_keys = set()
    for family in ("esmfold2", "simplefold"):
        script = "predict.py" if family == "esmfold2" else "offline_predict.py"
        spec = importlib.util.spec_from_file_location(
            f"_pr47_{family}", root / "docker" / "runners" / family / script
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        family_keys |= set(module.RESOURCE_ONLY_PARAMETERS)
        assert set(module.SUPPORTED_ADJUSTMENTS) <= set(module.RESOURCE_ONLY_PARAMETERS)

    assert set(ADJUSTMENT_ACTIONS) == family_keys, (set(ADJUSTMENT_ACTIONS) ^ family_keys)
    assert all(ADJUSTMENT_ACTIONS[key] in RECOVERY_ACTION_CLASSES for key in ADJUSTMENT_ACTIONS)

    from revocompute.resource_model import ADAPTATION_KEYS

    assert set(ADJUSTMENT_ACTIONS) <= set(ADAPTATION_KEYS), set(ADJUSTMENT_ACTIONS) - set(ADAPTATION_KEYS)


def test_every_recorded_attempt_carries_requested_and_effective_parameters():
    """TODO.md 7/10: per item/attempt the provenance shows requested vs effective."""
    items = [{"id": "a", "length": 10, "sample_count": 2, "requested_parameters": {"n": 1, "seed": 4}}]
    config = _config(items, ["", "one"])
    plugin = VerbosePlugin()
    plugin.oom_once.add("a")
    # The plugin resolves its effective set per attempt, as a family does.
    plugin.effective = {"n": 1, "seed": 4}
    plugin.effective_by_adjustment = {(): {"n": 1, "seed": 4}, (("sample_group_size", 1),): {"n": 1, "seed": 4, "sample_group_size": 1}}

    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()

    entry = manifest["items"][0]
    assert entry["status"] == "SUCCEEDED"
    records = entry["recovery"]
    assert [record["attempt"] for record in records] == [1, 2]
    assert [record["plan_label"] for record in records] == ["", "one"]
    assert [record["action"] for record in records] == ["", SCIENTIFIC_OUTPUT]
    # The requested count and seed survive the grouping change at every attempt.
    assert [record["effective_parameters"]["n"] for record in records] == [1, 1]
    assert [record["effective_parameters"]["seed"] for record in records] == [4, 4]
    # The grouping change is a scientific-output change and is reported in the
    # effective set, not buried as a resource-only setting.
    assert records[1]["effective_parameters"]["sample_group_size"] == 1
    assert records[0]["resources"] == {} and records[1]["resources"] == {}


def test_a_plan_naming_a_scientific_parameter_is_refused_and_never_executed():
    """TODO.md 8: automatic recovery fails closed on a scientific mutation.

    The server rejects such a declaration, but the runner refuses it on its own
    too: the plan is dropped before the ladder is walked, so it can never mutate
    the scientific execution. It is recorded as refused, and no attempt reports a
    changed effective set.
    """
    items = [{"id": "a", "length": 10, "requested_parameters": {"n": 1}}]
    config = _config(items, ["", "cheat"])
    config["resource_adaptation"] = {
        "stage": "recover",
        "fallback_plans": [{"label": "cheat", "adjustments": {"n": 2}}],
    }
    config["resource_guidance"] = {"plan_order": ["", "cheat"]}
    plugin = VerbosePlugin()
    plugin.oom_once.add("a")
    # If the plan were executed, the plugin would report the mutated set.
    plugin.effective_by_adjustment = {(): {"n": 1}, (("n", 2),): {"n": 2}}

    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()

    entry = manifest["items"][0]
    # The default path OOMs, the unsafe fallback is refused, so the item fails.
    assert entry["status"] == "FAILED_RESOURCE"
    assert entry["attempts"] == 1
    # Every recorded attempt is the default path; the unsafe plan left no record
    # because it never ran.
    assert [record["plan_label"] for record in entry["recovery"]] == [""]
    assert {record["action"] for record in entry["recovery"]} == {""}
    assert all(record["effective_parameters"] == {"n": 1} for record in entry["recovery"])
    # The plan never reached the plugin: only the default path executed.
    assert plugin.applied["a"] == [{}]
    assert manifest.get("refused_unsafe_plans") == ["cheat"]


def test_failure_observation_and_recovery_record_agree_on_the_attempt_index():
    """The audit trail references the resource row by attempt number, not a copy."""
    items = [{"id": "a", "length": 10, "requested_parameters": {"n": 1}}]
    config = _config(items, ["", "one"])
    plugin = VerbosePlugin()
    plugin.always_oom = {"a"}

    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()

    entry = manifest["items"][0]
    assert entry["status"] == "FAILED_RESOURCE"
    assert [row["outcome"] for row in entry["resource_events"]] == ["oom", "oom"]
    assert [row["action"] for row in entry["resource_events"]] == ["", SCIENTIFIC_OUTPUT]
    assert [record["attempt"] for record in entry["recovery"]] == [1, 2]
    assert {record["action"] for record in entry["recovery"]} == {"", SCIENTIFIC_OUTPUT}


def test_a_measurement_hook_failure_is_not_an_oom_and_spends_no_ladder():
    """TODO.md 9: a device that cannot be measured is a runtime fault, not an OOM.

    The peak measurement precedes execution; a dead context makes that read
    raise. Nothing ran, so no plan can be blamed and none may be spent: the item
    is a runtime failure with no recovery record and no censored OOM row.
    """
    items = [{"id": "a", "length": 10, "requested_parameters": {"n": 1}}]

    class Unmeasurable(VerbosePlugin):
        def runtime_usage(self, runtime):
            raise RuntimeError("CUDA error: no kernel image is available")

    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(_config(items, ["", "one"]), Unmeasurable(), output_dir=root).run()

    entry = manifest["items"][0]
    assert entry["status"] == "FAILED_RUNTIME"
    assert entry["attempts"] == 1, "an unmeasurable device must not spend a fallback"
    assert entry["recovery"] == [], "no plan was tried, so nothing is disclosed as recovery"
    assert all(row["outcome"] != "oom" for row in entry["resource_events"]), entry["resource_events"]


# ---------------------------------------------------------------------------
# Item identity: mapping, order independence, no duplicate/lost items
# ---------------------------------------------------------------------------


def test_every_item_maps_to_exactly_one_result_regardless_of_execution_order():
    """TODO.md 4: each input maps to one result; order never cross-contaminates."""
    # Lengths force the queue to execute the longest first, not input order.
    items = [
        {"id": "short", "length": 10, "requested_parameters": {"n": 1}},
        {"id": "long", "length": 3000, "requested_parameters": {"n": 1}},
        {"id": "medium", "length": 200, "requested_parameters": {"n": 1}},
    ]
    config = _config(items, ["", "one"])
    plugin = VerbosePlugin()

    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()
        assert manifest["outcome"] == "SUCCESS"
        # Manifest keeps input order; each item's own directory is named after it.
        assert [entry["id"] for entry in manifest["items"]] == ["short", "long", "medium"]
        for entry in manifest["items"]:
            assert (Path(root) / entry["name"] / "result.txt").read_text(encoding="utf-8") == entry["id"]

    # Execution order really differed from input order.
    ran = [call["id"] for call in plugin.calls]
    assert ran == ["long", "medium", "short"], ran
    assert sorted(ran) == sorted(entry["id"] for entry in manifest["items"])


def test_a_failed_item_does_not_relabel_a_later_items_result():
    items = [
        {"id": "first", "length": 10, "requested_parameters": {"n": 1}},
        {"id": "bad", "length": 20, "requested_parameters": {"n": 1}},
        {"id": "third", "length": 30, "requested_parameters": {"n": 1}},
    ]
    config = _config(items, ["", "one"])
    plugin = VerbosePlugin()
    plugin.raise_on["bad"] = "validation failed"

    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()
        states = {entry["id"]: entry["status"] for entry in manifest["items"]}
        assert states == {"first": "SUCCEEDED", "bad": "FAILED_RUNTIME", "third": "SUCCEEDED"}
        assert not (Path(root) / "bad").exists()
        assert (Path(root) / "third" / "result.txt").read_text(encoding="utf-8") == "third"


def test_duplicate_items_are_rejected_before_any_path_exists():
    items = [{"id": "a", "length": 1}, {"id": "a", "length": 2}]
    with tempfile.TemporaryDirectory() as root:
        try:
            PersistentTask(_config(items, ["", "one"]), VerbosePlugin(), output_dir=root).run()
        except Exception as error:  # noqa: BLE001 - the point is the task is refused
            assert "duplicate" in str(error).lower()
        else:  # pragma: no cover - regression guard
            raise AssertionError("a duplicate identifier must be rejected")
        assert not list(Path(root).glob("*/"))


# ---------------------------------------------------------------------------
# Restart / resume
# ---------------------------------------------------------------------------


def test_resume_restores_item_identity_without_recomputing_or_duplicating():
    """TODO.md 5: a restart keeps every completed item and loses none."""
    items = [
        {"id": "a", "length": 10, "requested_parameters": {"n": 1}},
        {"id": "b", "length": 20, "requested_parameters": {"n": 1}},
        {"id": "c", "length": 30, "requested_parameters": {"n": 1}},
    ]
    config = _config(items, ["", "one"])
    config["input_sha256"] = "snapshot-1"
    plugin = VerbosePlugin()
    plugin.raise_on["b"] = "worker killed"

    with tempfile.TemporaryDirectory() as root:
        first = PersistentTask(config, plugin, output_dir=root).run()
        assert [entry["status"] for entry in first["items"]] == ["SUCCEEDED", "FAILED_RUNTIME", "SUCCEEDED"]
        before = list(plugin.calls)

        # Second run: only the unfinished item runs again.
        plugin2 = VerbosePlugin()
        resumed = PersistentTask(config, plugin2, output_dir=root).run()

        assert [entry["id"] for entry in resumed["items"]] == ["a", "b", "c"]
        assert [entry["id"] for entry in resumed["items"]] == [entry["id"] for entry in first["items"]], (
            "item identity set must be coherent across restart"
        )
        ran = [call["id"] for call in plugin2.calls]
        assert ran == ["b"], ran
        assert {call["id"] for call in before} >= {"a", "c"}, "committed items must not rerun"


def test_a_changed_input_snapshot_recomputes_instead_of_binding_stale_results():
    """TODO.md 5: resume is only safe against the same immutable input snapshot.

    Two FASTA files can carry the same record headers with different sequences,
    so identical item names do not prove identical inputs. The manifest records
    the snapshot identity; a resume whose snapshot differs recomputes every item
    rather than skipping a committed result that belongs to different input.
    """
    items = [
        {"id": "a", "length": 10, "requested_parameters": {"n": 1}},
        {"id": "b", "length": 20, "requested_parameters": {"n": 1}},
    ]
    config = _config(items, ["", "one"])
    config["input_sha256"] = "snapshot-1"

    with tempfile.TemporaryDirectory() as root:
        assert PersistentTask(config, VerbosePlugin(), output_dir=root).run()["outcome"] == "SUCCESS"

        # Same item names, different input snapshot: every item must rerun.
        changed = {**config, "input_sha256": "snapshot-2"}
        plugin2 = VerbosePlugin()
        resumed = PersistentTask(changed, plugin2, output_dir=root).run()

        assert resumed["outcome"] == "SUCCESS"
        assert sorted(call["id"] for call in plugin2.calls) == ["a", "b"], "changed input must recompute"

        # A different task reusing the directory is likewise a fresh run.
        plugin3 = VerbosePlugin()
        other = {**config, "task_id": "t2"}
        PersistentTask(other, plugin3, output_dir=root).run()
        assert sorted(call["id"] for call in plugin3.calls) == ["a", "b"], "a different task must recompute"


# ---------------------------------------------------------------------------
# Monotonicity / bounded retries
# ---------------------------------------------------------------------------


def test_monotone_ladder_stays_monotone_and_bounded():
    items = [{"id": "a", "length": 40, "sample_count": 8, "requested_parameters": {"n": 1}}]
    config = _config(items, ["", "pair", "single"])
    config["resource_adaptation"] = {
        "stage": "recover",
        "fallback_plans": [
            {"label": "pair", "adjustments": {"sample_group_size": 2}},
            {"label": "single", "adjustments": {"sample_group_size": 1}},
        ],
    }
    config["resource_guidance"] = {"plan_order": ["", "pair", "single"]}
    plugin = VerbosePlugin()
    plugin.always_oom = {"a"}

    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()

    entry = manifest["items"][0]
    assert entry["status"] == "FAILED_RESOURCE"
    # Every declared plan ran exactly once, in order; the ladder never repeated a
    # rung and never rose.
    assert [call["adjustments"] for call in plugin.calls] == [
        {},
        {"sample_group_size": 2},
        {"sample_group_size": 1},
    ]
    assert entry["attempts"] == 3, "retries are bounded by the declared ladder"


def test_all_failed_items_yield_a_terminal_nonzero_failure():
    items = [{"id": "a", "length": 10}, {"id": "b", "length": 20}]
    config = _config(items, ["", "one"])
    plugin = VerbosePlugin()
    plugin.always_oom = {"a", "b"}

    with tempfile.TemporaryDirectory() as root:
        manifest = PersistentTask(config, plugin, output_dir=root).run()

    assert manifest["outcome"] == "FAILED"
    assert exit_code_for(manifest) != 0


if __name__ == "__main__":
    test_a_generic_runtime_exception_is_a_runtime_failure_and_consumes_no_fallback()
    test_an_explicit_oom_still_walks_the_declared_fallback_ladder()
    print("persistent_runner classification check passed")
