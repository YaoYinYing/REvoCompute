# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Behavioral tests for the CPU-only VRAM estimator and resource planner."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from revocompute.resource_model import (
    DeviceProfile,
    FallbackPlan,
    OUTCOME_OOM,
    OUTCOME_SUCCESS,
    QUALITY_INTERFERENCE,
    QUALITY_SUSPECT,
    QUALITY_VALID,
    ResourceModelError,
    ResourceObservation,
    ResourcePlanner,
    VRAMEstimator,
    WorkloadFeatures,
)

DEVICE = DeviceProfile("nvidia", "A100-PCIE-40GB", "8.0", 40960)
OTHER_DEVICE = DeviceProfile("nvidia", "H100-PCIE-80GB", "9.0", 81559)


def _observation(length: int, peak: int, *, device: DeviceProfile = DEVICE, seed: int = 0) -> ResourceObservation:
    return ResourceObservation(
        runner="esmfold2",
        model_revision="fast",
        runtime_fingerprint="fp-1",
        device=device,
        features=WorkloadFeatures("esmfold2", "fast", "fp-1", length + seed, sample_count=1),
        outcome=OUTCOME_SUCCESS,
        baseline_mb=8000,
        peak_reserved_mb=peak,
    )


def _fitted_estimator() -> VRAMEstimator:
    return VRAMEstimator(
        [_observation(length, peak) for length, peak in ((100, 14000), (300, 18000), (600, 26000), (1200, 44000))]
    )


def test_prediction_is_bounded_and_ordered() -> None:
    prediction = _fitted_estimator().predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 900), DEVICE)

    assert prediction.applicable
    assert 0 < prediction.expected_mb <= prediction.upper_bound_mb
    assert 0.0 < prediction.confidence <= 1.0


def test_out_of_distribution_workload_is_refused_not_extrapolated() -> None:
    prediction = _fitted_estimator().predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 100_000), DEVICE)

    assert not prediction.applicable
    assert prediction.source == "extrapolation"


def test_cold_start_reports_inapplicable_rather_than_a_guess() -> None:
    estimator = VRAMEstimator([_observation(100, 14000)])

    prediction = estimator.predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 100), DEVICE)

    assert not prediction.applicable
    assert prediction.confidence < 0.5


def test_new_device_class_starts_from_the_shared_baseline() -> None:
    prediction = _fitted_estimator().predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 900), OTHER_DEVICE)

    assert prediction.applicable
    assert prediction.expected_mb > 0


def test_new_device_class_without_same_runner_evidence_is_refused() -> None:
    estimator = _fitted_estimator()
    unseen = DeviceProfile("amd", "MI300", "9.0", 192000)

    # Same runner, unseen device class: the runner's shared envelope (observed
    # on its own classes) still bounds the request, so a huge ask is refused
    # rather than extrapolated with a confident bound.
    big = estimator.predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 100_000), unseen)
    assert not big.applicable
    assert big.source == "extrapolation"
    assert big.basis["observed_max_scale"] > 0
    # A runner/model with no evidence anywhere has no envelope and no baseline:
    # another runner's rows on the same class cannot supply either.
    unknown = estimator.predict(WorkloadFeatures("otherfold", "fast", "fp-1", 900), unseen)
    assert not unknown.applicable
    assert unknown.source == "no_observations"


def test_runtime_change_demotes_old_observations_instead_of_hiding_them() -> None:
    estimator = _fitted_estimator()

    matched = estimator.predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 900), DEVICE)
    mismatched = estimator.predict(WorkloadFeatures("esmfold2", "fast", "fp-2", 900), DEVICE)

    assert len(estimator.observations) == 4
    assert mismatched.source in {"fitted", "heuristic_median"}
    # The old rows still inform the expected value, but they cannot confer
    # applicability or confidence on a runtime they did not run.
    assert not mismatched.applicable
    assert mismatched.confidence < matched.confidence
    assert mismatched.expected_mb > 0
    assert (mismatched.expected_mb, mismatched.upper_bound_mb, mismatched.confidence) != (
        matched.expected_mb,
        matched.upper_bound_mb,
        matched.confidence,
    )


def test_foreign_runner_evidence_cannot_move_another_runners_prediction() -> None:
    baseline = _fitted_estimator()
    features = WorkloadFeatures("esmfold2", "fast", "fp-1", 900)
    alone = baseline.predict(features, DEVICE)
    foreign = [
        ResourceObservation(
            runner="otherfold",
            model_revision="slow",
            runtime_fingerprint="fp-1",
            device=DEVICE,
            features=WorkloadFeatures("otherfold", "slow", "fp-1", length),
            outcome=OUTCOME_SUCCESS,
            baseline_mb=40000,
            peak_reserved_mb=90000,
        )
        for length in (100, 300, 600, 1200) * 3
    ]

    blended = VRAMEstimator([*baseline.observations, *foreign]).predict(features, DEVICE)

    assert abs(blended.expected_mb - alone.expected_mb) < 2000
    assert abs(blended.upper_bound_mb - alone.upper_bound_mb) < 2000
    # A brand-new runner/model has no evidence of its own, so it is not given a
    # trusted answer merely because other runners have rows.
    fresh = VRAMEstimator([*baseline.observations, *foreign]).predict(
        WorkloadFeatures("newfold", "v1", "fp-1", 900), DEVICE
    )
    assert not fresh.applicable


def test_oom_is_retained_as_a_censored_constraint() -> None:
    estimator = _fitted_estimator()
    estimator.observe(
        ResourceObservation(
            runner="esmfold2",
            model_revision="fast",
            runtime_fingerprint="fp-1",
            device=DEVICE,
            features=WorkloadFeatures("esmfold2", "fast", "fp-1", 2000),
            outcome=OUTCOME_OOM,
            baseline_mb=8000,
            available_mb=39000,
            error_class="CUDA_OOM",
        )
    )

    # The failed row is not training data, but it is evidence about the boundary.
    assert len(estimator.observations) == 5
    assert estimator.known_failure_envelope(WorkloadFeatures("esmfold2", "fast", "fp-1", 100), DEVICE) == 2000


def test_interference_is_excluded_from_training() -> None:
    noisy = ResourceObservation(
        runner="esmfold2",
        model_revision="fast",
        runtime_fingerprint="fp-1",
        device=DEVICE,
        features=WorkloadFeatures("esmfold2", "fast", "fp-1", 900),
        outcome=OUTCOME_SUCCESS,
        baseline_mb=8000,
        peak_reserved_mb=39000,
        available_mb=20000,
    )

    # The workload needed 31000 MiB of growth on a device that had 20000 MiB
    # free at start, so another process was holding memory.
    assert noisy.incremental_mb > noisy.available_mb
    assert noisy.effective_quality == QUALITY_INTERFERENCE
    estimator = VRAMEstimator([noisy, *[_observation(length, 20000 + length) for length in (100, 300, 600, 1200)]])
    # A contaminated row is diagnostic only: it must not be learned as extra
    # workload demand.
    assert estimator.predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 100), DEVICE).upper_bound_mb < 39000


def test_a_large_legitimate_run_is_not_demoted_to_interference() -> None:
    # A big run on an idle device: the available memory at start covered the
    # workload, and the peak exceeding it is simply how memory reporting works.
    legitimate = ResourceObservation(
        runner="esmfold2",
        model_revision="fast",
        runtime_fingerprint="fp-1",
        device=DEVICE,
        features=WorkloadFeatures("esmfold2", "fast", "fp-1", 1200),
        outcome=OUTCOME_SUCCESS,
        baseline_mb=8000,
        peak_reserved_mb=44000,
        available_mb=39000,
    )
    unknown = ResourceObservation(
        runner="esmfold2",
        model_revision="fast",
        runtime_fingerprint="fp-1",
        device=DEVICE,
        features=WorkloadFeatures("esmfold2", "fast", "fp-1", 1200),
        outcome=OUTCOME_SUCCESS,
        baseline_mb=8000,
        peak_reserved_mb=44000,
    )

    assert legitimate.effective_quality == QUALITY_VALID
    assert unknown.effective_quality == QUALITY_VALID


def test_plan_rejects_an_adjustment_that_changes_scientific_intent() -> None:
    with pytest.raises(ResourceModelError, match="non-resource"):
        FallbackPlan.parse_all([{"label": "shrink", "adjustments": {"num_samples": 1}}])


def test_plan_accepts_only_resource_equivalent_adjustments() -> None:
    plans = FallbackPlan.parse_all(
        [
            {"label": "split", "title": "Split samples", "adjustments": {"sample_group_size": 1}},
            {"label": "offload", "adjustments": {"cpu_offload": True}},
        ]
    )

    assert [plan.label for plan in plans] == ["split", "offload"]


def test_observe_stage_never_modifies_a_successful_execution() -> None:
    planner = ResourcePlanner(
        _fitted_estimator(),
        FallbackPlan.parse_all([{"label": "split", "adjustments": {"sample_group_size": 1}}]),
        stage="observe",
    )
    features = WorkloadFeatures("esmfold2", "fast", "fp-1", 100_000)

    decision = planner.decide(features, DEVICE, 40960, attempt=0)
    retry = planner.decide(features, DEVICE, 40960, attempt=1)

    assert decision.action == "allow" and decision.plan_label == ""
    assert not retry.allowed, "observation-only rollout must not adapt"


def test_recover_stage_walks_declared_fallbacks_within_a_budget() -> None:
    planner = ResourcePlanner(
        _fitted_estimator(),
        FallbackPlan.parse_all(
            [
                {"label": "split", "adjustments": {"sample_group_size": 1}},
                {"label": "offload", "adjustments": {"cpu_offload": True}},
            ]
        ),
        stage="recover",
    )

    assert planner.decide(WorkloadFeatures("esmfold2", "fast", "fp-1", 100), DEVICE, 40960, attempt=0).plan_label == ""
    assert planner.decide(WorkloadFeatures("esmfold2", "fast", "fp-1", 100), DEVICE, 40960, attempt=1).plan_label == "split"
    second = planner.decide(
        WorkloadFeatures("esmfold2", "fast", "fp-1", 100), DEVICE, 40960, attempt=2, failed_plans=("split",)
    )
    assert second.plan_label == "offload"
    exhausted = planner.decide(
        WorkloadFeatures("esmfold2", "fast", "fp-1", 100), DEVICE, 40960, attempt=3, failed_plans=("split", "offload")
    )
    assert exhausted.action == "reject"
    assert "FAILED_RESOURCE" in exhausted.reason


def test_recover_stage_rejects_only_when_the_bound_cannot_fit() -> None:
    planner = ResourcePlanner(
        _fitted_estimator(),
        FallbackPlan.parse_all([{"label": "split", "adjustments": {"sample_group_size": 1}}]),
        stage="recover",
    )
    features = WorkloadFeatures("esmfold2", "fast", "fp-1", 900)
    prediction = _fitted_estimator().predict(features, DEVICE)
    assert prediction.applicable and prediction.upper_bound_mb > 0

    roomy = planner.decide(features, DEVICE, 10_000_000, attempt=1)
    assert roomy.action == "adapt" and roomy.plan_label == "split"
    assert roomy.prediction is not None and roomy.prediction.fits(10_000_000)
    # The bound cannot fit even the last fallback: reject with the basis rather
    # than adapting into an attempt that is known to fail.
    impossible = planner.decide(features, DEVICE, prediction.upper_bound_mb // 2, attempt=1)
    assert impossible.action == "reject"
    assert impossible.reason == "conservative bound still exceeds available VRAM"
    assert impossible.prediction is not None and not impossible.allowed


def test_avoid_stage_skips_a_known_failure_region_on_the_first_attempt() -> None:
    estimator = _fitted_estimator()
    estimator.observe(
        ResourceObservation(
            runner="esmfold2",
            model_revision="fast",
            runtime_fingerprint="fp-1",
            device=DEVICE,
            features=WorkloadFeatures("esmfold2", "fast", "fp-1", 900),
            outcome=OUTCOME_OOM,
            baseline_mb=8000,
            available_mb=39000,
        )
    )
    planner = ResourcePlanner(
        estimator,
        FallbackPlan.parse_all([{"label": "split", "adjustments": {"sample_group_size": 1}}]),
        stage="avoid",
    )

    decision = planner.decide(WorkloadFeatures("esmfold2", "fast", "fp-1", 2000), DEVICE, 40960, attempt=0)

    assert decision.action == "adapt"
    assert decision.plan_label == "split"
    assert decision.adjustments == {"sample_group_size": 1}


def test_avoid_stage_leaves_unrelated_workloads_on_the_default_path() -> None:
    estimator = _fitted_estimator()
    estimator.observe(
        ResourceObservation(
            runner="esmfold2",
            model_revision="fast",
            runtime_fingerprint="fp-1",
            device=DEVICE,
            features=WorkloadFeatures("esmfold2", "fast", "fp-1", 900),
            outcome=OUTCOME_OOM,
            baseline_mb=8000,
            available_mb=39000,
        )
    )
    planner = ResourcePlanner(estimator, (), stage="avoid")

    decision = planner.decide(WorkloadFeatures("esmfold2", "fast", "fp-1", 100), DEVICE, 40960, attempt=0)

    assert decision.action == "allow"


def test_decisions_are_explainable() -> None:
    planner = ResourcePlanner(
        _fitted_estimator(),
        FallbackPlan.parse_all([{"label": "split", "adjustments": {"sample_group_size": 1}}]),
        stage="recover",
    )

    decision = planner.decide(WorkloadFeatures("esmfold2", "fast", "fp-1", 400), DEVICE, 40960, attempt=1)

    assert decision.explain()
    assert decision.prediction is not None


def test_state_round_trips_through_plain_json() -> None:
    estimator = _fitted_estimator()
    estimator.observe(
        ResourceObservation(
            runner="esmfold2",
            model_revision="fast",
            runtime_fingerprint="fp-1",
            device=DEVICE,
            features=WorkloadFeatures("esmfold2", "fast", "fp-1", 2000),
            outcome=OUTCOME_OOM,
            baseline_mb=8000,
            available_mb=39000,
            quality=QUALITY_SUSPECT,
        )
    )
    with tempfile.TemporaryDirectory() as root:
        path = str(Path(root) / "estimator.json")
        estimator.save(path)
        loaded = VRAMEstimator.load(path)

    assert len(loaded.observations) == len(estimator.observations)
    assert "numpy" not in json.dumps(loaded.to_dict()).lower()
    # The persisted rows are the same evidence: the failure envelope survives.
    assert loaded.known_failure_envelope(WorkloadFeatures("esmfold2", "fast", "fp-1", 100), DEVICE) == 2000


def test_device_profile_shares_observations_across_equivalent_devices() -> None:
    same_class = DeviceProfile("nvidia", "A100-PCIE-40GB", "8.0", 40960)
    larger_sku = DeviceProfile("nvidia", "A100-SXM4-80GB", "8.0", 81920)

    assert same_class.device_class == DEVICE.device_class
    assert same_class.profile_key == DEVICE.profile_key
    # A different SKU is a different VRAM class but still the same device class,
    # so it shares observations rather than needing its own model.
    assert larger_sku.device_class == DEVICE.device_class
    assert larger_sku.profile_key != DEVICE.profile_key


def test_device_class_reduces_real_gpu_names_to_a_model_family() -> None:
    def device_class(name: str) -> str:
        return DeviceProfile("nvidia", name, "9.0", 81559).device_class

    # Form factor and memory size are SKUs of one model family, not classes.
    assert device_class("NVIDIA H100 PCIe") == "nvidia/H100"
    assert device_class("NVIDIA H100 80GB HBM3") == "nvidia/H100"
    assert device_class("NVIDIA H100 NVL") == "nvidia/H100"
    assert device_class("NVIDIA A100-SXM4-80GB") == "nvidia/A100"
    assert device_class("NVIDIA A100-PCIE-40GB") == "nvidia/A100"
    assert device_class("NVIDIA GeForce RTX 4090") == "nvidia/4090"
    assert device_class("Tesla T4") == "nvidia/T4"
    # A name with no family token keeps its whole name rather than collapsing
    # onto an unrelated class.
    assert device_class("GPU") == "nvidia/GPU"
    assert device_class("B200") == "nvidia/B200"
