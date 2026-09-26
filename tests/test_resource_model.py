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


def test_runtime_change_demotes_old_observations_instead_of_hiding_them() -> None:
    estimator = _fitted_estimator()

    prediction = estimator.predict(WorkloadFeatures("esmfold2", "fast", "fp-2", 900), DEVICE)

    assert len(estimator.observations) == 4
    assert prediction.source in {"fitted", "heuristic_median"}


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

    assert noisy.effective_quality == QUALITY_INTERFERENCE
    estimator = VRAMEstimator([noisy, *[_observation(length, 20000 + length) for length in (100, 300, 600, 1200)]])
    # A row whose peak exceeds free memory is diagnostic only: it must not be
    # learned as extra workload demand.
    assert estimator.predict(WorkloadFeatures("esmfold2", "fast", "fp-1", 100), DEVICE).upper_bound_mb < 39000


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
