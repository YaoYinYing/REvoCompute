# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Shared persistent-runner failure classification.

A plugin reports a recoverable OOM as an outcome, and only that path may walk
the declared resource-fallback ladder. An exception that reaches the generic
handler was never classified as recoverable, so it must fail the item as
``FAILED_RUNTIME`` on its first attempt: retrying a validation, filesystem, or
model bug under a smaller plan repeats the same bug and spends the ladder on
it. These tests pin both halves — no fallback for an unclassified exception,
and the ladder still walked for a real OOM — with a fake plugin that counts how
many times each item actually ran.
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
    OUTCOME_OOM,
    OUTCOME_SUCCESS,
    PersistentTask,
    PlanSequence,
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


if __name__ == "__main__":
    test_a_generic_runtime_exception_is_a_runtime_failure_and_consumes_no_fallback()
    test_an_explicit_oom_still_walks_the_declared_fallback_ladder()
    print("persistent_runner classification check passed")
