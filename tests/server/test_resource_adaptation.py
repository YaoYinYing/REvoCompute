# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Resource adaptation policy, observation ingest, and per-item progress.

Synthetic on purpose: these exercise the server's own behavior — manifest
projection, observation storage and dedupe, the runner-stdout vocabulary, and
per-item outcome publication — without a real runner or a real GPU.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from conftest import _load_pssm_module, _test_client_auth, _upsert_task_for_user
from revocompute import resource_observations as ro
from revocompute import resource_model as rm
from revocompute.db import TaskDatabase
from revocompute.resource_model import FallbackPlan
from revocompute.task_types import (
    ExecutionQueuePolicy,
    ExecutionSettings,
    ResourceAdaptation,
    _load_execution,
    _load_execution_queue,
    _load_resource_adaptation,
)

import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]


def _observation(**overrides):
    payload = {
        "runner": "gpu_runner",
        "runner_version": "1",
        "model_revision": "fast",
        "runtime_fingerprint": "fp-1",
        "device": {
            "vendor": "nvidia",
            "model": "A100-PCIE-40GB",
            "compute_capability": "8.0",
            "total_vram_mb": 40960,
            "mig_profile": "",
        },
        "features": {
            "runner": "gpu_runner",
            "model_revision": "fast",
            "runtime_fingerprint": "fp-1",
            "sequence_length": 400,
            "sequence_count": 1,
            "batch_size": 1,
            "sample_count": 1,
            "parameters": {},
        },
        "outcome": "success",
        "baseline_mb": 8000,
        "peak_allocated_mb": 12000,
        "peak_reserved_mb": 14000,
        "peak_process_mb": 13000,
        "available_mb": 40000,
        "quality": "valid",
        "runtime_seconds": 12.5,
        "task_id": "a" * 32,
        "work_item": "protein_001",
        "attempt": 1,
        "created_at": 1_700_000_000.0,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Policy parsing
# ---------------------------------------------------------------------------


def test_a_fallback_changing_a_scientific_parameter_is_rejected():
    """The manifest's adjustments are execution-only by construction."""
    with pytest.raises(ValueError, match="non-resource parameter"):
        _load_resource_adaptation(
            {"stage": "recover", "fallback_plans": [{"label": "x", "adjustments": {"num_samples": 2}}]},
            "gpu_runner_predict",
        )
    with pytest.raises(ValueError, match="non-resource parameter"):
        _load_resource_adaptation(
            {
                "stage": "observe",
                "fallback_plans": [{"label": "x", "adjustments": {"seed": 7}}],
            },
            "gpu_runner_predict",
        )


def test_unknown_policy_fields_stage_and_plan_shapes_are_rejected():
    for raw in (
        {"stage": "sometimes"},
        {"stage": "observe", "oom_recovery": True},
        {"stage": "observe", "fallback_plans": {"label": "x"}},
        {"stage": "observe", "fallback_plans": [{"label": "x", "adjustments": {"batch_size": 1}, "note": "no"}]},
        {"stage": "observe", "fallback_plans": [{"label": "x", "adjustments": {}}]},
    ):
        with pytest.raises(ValueError):
            _load_resource_adaptation(raw, "t")


def test_absent_policy_keeps_the_existing_defaults():
    adaptation = _load_resource_adaptation(None, "t")
    assert adaptation == ResourceAdaptation()
    assert adaptation.stage == "observe"
    assert adaptation.fallback_plans == ()
    assert adaptation.to_dict() == {"stage": "observe", "fallback_plans": []}
    assert _load_execution(None, "t") == ExecutionSettings()
    assert _load_execution_queue(None, "t") == ExecutionQueuePolicy()


def test_declared_policy_and_execution_settings_are_loaded():
    adaptation = _load_resource_adaptation(
        {
            "stage": "recover",
            "fallback_plans": [
                {"label": "split-samples", "title": "Split samples", "adjustments": {"sample_group_size": 1}}
            ],
        },
        "gpu_runner_predict",
    )
    assert adaptation.stage == "recover"
    assert [plan.label for plan in adaptation.fallback_plans] == ["split-samples"]
    assert adaptation.to_dict()["fallback_plans"] == [
        {"label": "split-samples", "title": "Split samples", "adjustments": {"sample_group_size": 1}}
    ]
    assert _load_execution({"batch_size": 2, "max_item_attempts": 3, "max_runtime_restarts": 1}, "t") == (
        ExecutionSettings(batch_size=2, max_item_attempts=3, max_runtime_restarts=1)
    )
    assert _load_execution_queue({"ratios": [1.5, 2.0]}, "t") == ExecutionQueuePolicy(ratios=(1.5, 2.0))


def test_execution_settings_reject_nonsense_budgets():
    for raw in ({"batch_size": 0}, {"max_item_attempts": 0}, {"max_runtime_restarts": -1}, {"junk": 1}):
        with pytest.raises(ValueError):
            _load_execution(raw, "t")
    for raw in ({"ratios": [1.0]}, {"ratios": []}, {"other": {}}):
        with pytest.raises(ValueError):
            _load_execution_queue(raw, "t")


def test_execution_settings_reject_non_integer_counts_by_type():
    """A string, bool, or float count must be a ValueError, never a silent accept."""
    for raw in (
        {"batch_size": "2"},
        {"batch_size": True},
        {"batch_size": 2.5},
        {"max_item_attempts": 3.7},
        {"max_runtime_restarts": False},
    ):
        with pytest.raises(ValueError, match="must be"):
            _load_execution(raw, "t")
    for raw in ({"ratios": [True, 2.0]}, {"ratios": ["2"]}, {"constraints": [1, 2]}, {"constraints": "x"}):
        with pytest.raises(ValueError):
            _load_execution_queue(raw, "t")


def test_guidance_publishes_nothing_until_evidence_supports_it():
    plans = FallbackPlan.parse_all([{"label": "split", "adjustments": {"sample_group_size": 1}}])
    observing = rm.guidance_for(plans, [], stage="observe")
    assert observing == {"stage": "observe", "plan_order": ["", "split"], "profiles": []}
    # A single OOM is not enough to establish a region; the runner falls back to
    # plain bounded recovery.
    thin = [rm.ResourceObservation.from_dict(_observation(outcome="oom", available_mb=100, plan_label=""))]
    assert rm.guidance_for(plans, thin, stage="avoid")["profiles"] == []


def test_guidance_avoids_a_plan_that_only_ever_failed():
    plans = FallbackPlan.parse_all([{"label": "split", "adjustments": {"sample_group_size": 1}}])
    rows = [rm.ResourceObservation.from_dict(_observation(work_item=f"p{i}")) for i in range(4)]
    split_oom = rm.ResourceObservation.from_dict(
        _observation(outcome="oom", available_mb=100, plan_label="split", work_item="p9", attempt=2)
    )
    guidance = rm.guidance_for(plans, [*rows, split_oom], stage="avoid")
    (profile,) = guidance["profiles"]
    assert (profile["runner"], profile["model_revision"], profile["runtime_fingerprint"]) == (
        "gpu_runner",
        "fast",
        "fp-1",
    )
    assert profile["device_model"] == "A100-PCIE-40GB"
    assert profile["total_vram_mb"] == 40960
    assert profile["known_failing_plans"] == ["split"]
    assert profile["avoid_scale_at_or_above"] == int(split_oom.features.requested_scale)


def test_guidance_is_selected_per_device_after_allocation():
    """The runner picks the entry matching the GPU it was actually given.

    Two devices in the same runner/model/fingerprint scope publish independent
    entries: the submission path cannot know the device in advance, so the
    server never collapses them into one threshold.
    """
    plans = FallbackPlan.parse_all([{"label": "split", "adjustments": {"sample_group_size": 1}}])
    rows = [rm.ResourceObservation.from_dict(_observation(work_item=f"p{i}")) for i in range(4)]
    h100_device = {
        "vendor": "nvidia",
        "model": "H100-PCIE-80GB",
        "compute_capability": "9.0",
        "total_vram_mb": 81559,
        "mig_profile": "",
    }
    a100_oom = rm.ResourceObservation.from_dict(
        _observation(outcome="oom", available_mb=100, plan_label="split", work_item="p9", attempt=2)
    )
    h100_oom = rm.ResourceObservation.from_dict(
        _observation(
            device=h100_device,
            outcome="oom",
            available_mb=100,
            plan_label="split",
            work_item="q9",
            attempt=2,
        )
    )
    guidance = rm.guidance_for(plans, [*rows, a100_oom, h100_oom], stage="avoid")
    # Both entries belong to the one scope the evidence came from; only the
    # device differs, and each is self-describing so the runner can bind it.
    assert [(entry["model_revision"], entry["runtime_fingerprint"]) for entry in guidance["profiles"]] == [
        ("fast", "fp-1"),
        ("fast", "fp-1"),
    ]
    assert [entry["device_model"] for entry in guidance["profiles"]] == ["A100-PCIE-40GB", "H100-PCIE-80GB"]
    assert [entry["total_vram_mb"] for entry in guidance["profiles"]] == [40960, 81559]
    # Evidence about one device never sets the other's threshold: the 40 GiB
    # entry keeps its own failed plan and scale.
    assert guidance["profiles"][0]["avoid_scale_at_or_above"] == int(a100_oom.features.requested_scale)
    assert guidance["profiles"][1]["avoid_scale_at_or_above"] == int(h100_oom.features.requested_scale)


def test_guidance_never_borrows_another_profiles_oom():
    """A positive "this will fail" claim needs evidence about *this* profile.

    The rows a family accumulates span every model revision, runtime, and device
    it has run on. One OOM from a larger model must not establish a threshold
    for a smaller one, or the runner would proactively skip a safe default.
    """
    plans = FallbackPlan.parse_all([{"label": "split", "adjustments": {"sample_group_size": 1}}])
    same_profile = [rm.ResourceObservation.from_dict(_observation(work_item=f"p{i}")) for i in range(4)]
    foreign = rm.ResourceObservation.from_dict(
        _observation(
            runner="gpu_runner",
            model_revision="standard",
            runtime_fingerprint="fp-other",
            outcome="oom",
            available_mb=100,
            plan_label="split",
            work_item="foreign",
            attempt=2,
        )
    )

    # The foreign row alone cannot speak, and it cannot move the threshold for
    # the profile that *does* have successes either.
    assert rm.guidance_for(plans, [*same_profile, foreign], stage="avoid")["profiles"] == []

    # The same OOM on the profile's own revision/fingerprint does establish it.
    native = rm.ResourceObservation.from_dict(
        _observation(outcome="oom", available_mb=100, plan_label="split", work_item="p9", attempt=2)
    )
    (profile,) = rm.guidance_for(plans, [*same_profile, native], stage="avoid")["profiles"]
    assert (profile["model_revision"], profile["runtime_fingerprint"]) == ("fast", "fp-1")
    assert profile["known_failing_plans"] == ["split"]
    assert profile["avoid_scale_at_or_above"] == int(native.features.requested_scale)


def test_known_failure_knowledge_survives_a_restart_by_rebuilding_from_rows(tmp_path):
    """Production correctness is the observation store, not an estimator file.

    A server restart rebuilds its picture from stored rows alone; nothing about
    the known-failure knowledge may depend on process-local state or a cache.
    """
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    for index in range(4):
        store.record_resource_observation(_observation(task_id=f"{index:032x}", work_item=f"p{index}", attempt=1))
    store.record_resource_observation(
        _observation(task_id="f" * 32, work_item="p9", attempt=2, outcome="oom", available_mb=100, plan_label="split")
    )
    plans = FallbackPlan.parse_all([{"label": "split", "adjustments": {"sample_group_size": 1}}])
    adaptation = ResourceAdaptation(stage="avoid", fallback_plans=plans)

    # A brand-new store handle and a brand-new estimator built purely from the
    # persisted rows yield the same knowledge — no in-process state is required.
    restarted = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    rebuilt = rm.VRAMEstimator(
        rm.ResourceObservation.from_dict(ro._observation_payload(row))
        for row in restarted.list_resource_observations(runners=("gpu_runner",))
    )

    guidance = ro.observations_for_guidance("gpu_runner", adaptation, store=restarted)
    assert guidance["profiles"][0]["model_revision"] == "fast"
    assert guidance["profiles"][0]["runtime_fingerprint"] == "fp-1"
    assert guidance["profiles"][0]["known_failing_plans"] == ["split"]
    assert rebuilt.known_failure_envelope(
        rm.WorkloadFeatures("gpu_runner", "fast", "fp-1", 400), rm.DeviceProfile("nvidia", "A100-PCIE-40GB", "8.0", 40960)
    ) is not None


def test_guidance_is_total_for_unknown_stages_and_plans():
    guidance = rm.guidance_for((), (), stage="nonsense")
    assert guidance["stage"] == "observe"
    assert guidance["plan_order"] == [""]




# ---------------------------------------------------------------------------
# Observation store and ingest
# ---------------------------------------------------------------------------


def test_a_re_read_stdout_line_does_not_append_a_duplicate(tmp_path):
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    first = store.record_resource_observation(_observation())
    assert first is not None
    assert store.record_resource_observation(_observation()) is None, "same attempt must dedupe"
    retry = store.record_resource_observation(_observation(attempt=2, plan_label="split"))
    assert retry is not None, "a bounded retry is a distinct attempt"
    rows = store.list_resource_observations(runners=("gpu_runner",))
    assert [(row["attempt"], row["plan_label"]) for row in rows] == [(2, "split"), (1, "")]
    assert store.list_resource_observations(runners=("other",)) == []
    assert store.list_resource_observations(model_versions=("fast",))
    assert store.list_resource_observations(model_versions=("other",)) == []


def test_a_stored_observation_keeps_the_full_normalized_json(tmp_path):
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    store.record_resource_observation(_observation())
    (row,) = store.list_resource_observations()
    # The class key comes from DeviceProfile, so two A100 SKUs share one history.
    assert row["device_class"] == rm.DeviceProfile(**json.loads(row["device_profile_json"])).device_class
    assert row["vram_class"] == "40GiB"
    assert json.loads(row["observation_json"])["features"]["sequence_length"] == 400
    assert json.loads(row["device_profile_json"])["compute_capability"] == "8.0"


def test_malformed_observations_are_dropped_without_raising(tmp_path):
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    assert store.record_resource_observation({}) is None
    assert store.record_resource_observation({"runner": "x", "baseline_mb": "not a number"}) is None
    assert store.list_resource_observations() == []


def test_an_observation_that_cannot_be_read_back_is_never_stored(tmp_path):
    """Ingest and the guidance reader must accept exactly the same set of rows.

    A device with no vendor is accepted by the projection but rejected by
    ``ResourceObservation.from_dict``; storing it would poison guidance for the
    whole family while still being published to runners.
    """
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    assert store.record_resource_observation(_observation()) is not None
    assert store.record_resource_observation(_observation(device={"model": "no-vendor", "total_vram_mb": 1}, attempt=2)) is None
    assert [row["attempt"] for row in store.list_resource_observations()] == [1]


def test_non_finite_observation_values_are_dropped_not_stored(tmp_path):
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    assert store.record_resource_observation(_observation(peak_reserved_mb=float("inf"))) is None
    assert store.record_resource_observation(_observation(runtime_seconds=float("nan"))) is None
    assert store.list_resource_observations() == []


def test_a_poisoned_row_does_not_silence_the_families_guidance(tmp_path):
    """One unreadable stored row must not empty guidance for every task."""
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    for index in range(4):
        store.record_resource_observation(_observation(task_id=f"{index:032x}", work_item=f"p{index}", attempt=1))
    # Bypass ingest, as a row written by an older revision would have been.
    with store.engine.begin() as conn:
        conn.execute(
            store.resource_observations_table.insert().values(
                runner="gpu_runner",
                model_version="fast",
                observation_json=json.dumps({"runner": "gpu_runner"}),
                created_at=1.0,
            )
        )
    plans = FallbackPlan.parse_all([{"label": "split", "adjustments": {"sample_group_size": 1}}])
    guidance = ro.observations_for_guidance(
        "gpu_runner", ResourceAdaptation(stage="recover", fallback_plans=plans), store=store
    )
    assert guidance["plan_order"] == ["", "split"]
    assert guidance["stage"] == "recover"


def test_a_poisoned_row_alone_still_yields_guidance(tmp_path):
    """With only unreadable rows the family gets its default guidance, not an error."""
    empty = TaskDatabase(str(tmp_path / "only-poison.sqlite3"))
    with empty.engine.begin() as conn:
        conn.execute(
            empty.resource_observations_table.insert().values(
                runner="gpu_runner",
                model_version="fast",
                observation_json=json.dumps({"runner": "gpu_runner"}),
                created_at=1.0,
            )
        )
    assert ro.observations_for_guidance("gpu_runner", ResourceAdaptation(), store=empty)["plan_order"] == [""]


def test_resource_observations_are_retained_newest_first_per_profile(tmp_path, monkeypatch):
    monkeypatch.setattr("revocompute.db.RESOURCE_OBSERVATION_RETENTION", 3)
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    for index in range(5):
        store.record_resource_observation(
            _observation(task_id=f"{index:032x}", work_item=f"p{index}", attempt=1)
        )
        store.record_resource_observation(
            _observation(runner="other", task_id=f"{index:032x}", work_item=f"p{index}", attempt=1)
        )
    kept = store.list_resource_observations(runners=("gpu_runner",), limit=50)
    assert [row["work_item"] for row in kept] == ["p4", "p3", "p2"]
    assert len(store.list_resource_observations(runners=("other",), limit=50)) == 3


def test_retention_is_stratified_so_one_device_class_cannot_evict_another(tmp_path, monkeypatch):
    """A busy common GPU must not erase a rarer class' whole history.

    Retention is capped per (runner, model_version, device_class): many A100
    rows leave the H100 rows for the same runner/model intact, and each class
    stays bounded on its own.
    """
    monkeypatch.setattr("revocompute.db.RESOURCE_OBSERVATION_RETENTION", 3)
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    h100_device = {"vendor": "nvidia", "model": "H100-PCIE-80GB", "compute_capability": "9.0", "total_vram_mb": 81559}
    a100_device = {"vendor": "nvidia", "model": "A100-PCIE-40GB", "compute_capability": "8.0", "total_vram_mb": 40960}
    store.record_resource_observation(_observation(task_id="0" * 32, work_item="rare", attempt=1, device=h100_device))
    for index in range(8):
        store.record_resource_observation(
            _observation(device=a100_device, task_id=f"{index:032x}", work_item=f"common{index}", attempt=1)
        )

    kept = store.list_resource_observations(runners=("gpu_runner",), limit=50)
    classes = {row["device_class"] for row in kept}
    assert classes == {"nvidia/A100", "nvidia/H100"}
    assert [row["work_item"] for row in kept if row["device_class"] == "nvidia/H100"] == ["rare"]
    assert len([row for row in kept if row["device_class"] == "nvidia/A100"]) == 3


def test_deleting_a_task_removes_its_progress_row(tmp_path):
    """A re-submitted identical task id must not inherit a stale progress row."""
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "e" * 32
    store.upsert_task(
        task_id,
        filename="x.fasta",
        file_path="/tmp/x.fasta",
        uploaded_at=1.0,
        status="failed",
        is_binary=0,
        task_type="multistage_runner",
        storage_key="tester",
        submitted_by_user_id=1,
    )
    store.record_task_progress(task_id, progress={"total_items": 4}, outcome="PARTIAL_SUCCESS")
    store.record_resource_observation(_observation(task_id=task_id, work_item="p0", attempt=1))
    store.delete_task(task_id)
    assert store.get_task(task_id) is None
    assert store.get_task_progress(task_id) is None
    assert store.list_resource_observations() == []


def test_re_preparing_an_unowned_task_clears_its_stale_progress(tmp_path):
    """A re-prepared task must not read its predecessor's outcome back as its own."""
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "d" * 32
    store.upsert_task(
        task_id,
        filename="x.fasta",
        file_path="/tmp/x.fasta",
        uploaded_at=time.time(),
        status="failed",
        is_binary=0,
        task_type="multistage_runner",
        storage_key="tester",
        submitted_by_user_id=1,
    )
    store.record_task_progress(task_id, progress={"total_items": 4}, outcome="PARTIAL_SUCCESS")

    claim = store.claim_task_preparation(task_id)

    assert claim.outcome == "UNOWNED" and claim.owned()
    assert store.get_task_progress(task_id) is None


def test_line_parsers_ignore_unknown_and_malformed_runner_output():
    assert ro.parse_observation_line("plain runner output") is None
    assert ro.parse_observation_line("REVODESIGN_OBSERVATION:{not json") is None
    assert ro.parse_observation_line("REVODESIGN_OBSERVATION:" + json.dumps({"runner": "x"}))["runner"] == "x"
    assert ro.parse_progress_line("prefix " + ro.PROGRESS_PREFIX + '{"total_items": 2}') == {"total_items": 2}
    assert ro.parse_progress_line(ro.PROGRESS_PREFIX + "{") is None
    assert ro.parse_task_outcome_line(ro.TASK_OUTCOME_PREFIX + "PARTIAL_SUCCESS") == "PARTIAL_SUCCESS"
    assert ro.parse_task_outcome_line(ro.TASK_OUTCOME_PREFIX + "SOMETHING_ELSE") is None


def test_line_parsers_are_total_for_hostile_runner_output():
    """A pathological line must be dropped, never raised, in any caller.

    ``json.loads`` raises ``RecursionError`` — not ``ValueError`` — on a deeply
    nested payload, and an oversized line must be refused before a structure is
    built from it at all.
    """
    nested = "[" * 20_000
    assert ro.parse_observation_line("REVODESIGN_OBSERVATION:" + nested) is None
    assert ro.parse_progress_line(ro.PROGRESS_PREFIX + nested) is None
    oversized = ro.PROGRESS_PREFIX + "x" * (ro.PROTOCOL_LINE_MAX_BYTES + 1)
    assert ro.parse_progress_line(oversized) is None
    assert ro.parse_observation_line(
        "REVODESIGN_OBSERVATION:" + json.dumps({"runner": "x", "pad": "y" * ro.PROTOCOL_LINE_MAX_BYTES})
    ) is None


def test_progress_and_outcome_are_recorded_on_the_task_row(tmp_path):
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "b" * 32
    store.record_task_progress(task_id, progress={"total_items": 5, "completed_items": 2})
    store.record_task_progress(task_id, outcome="PARTIAL_SUCCESS")
    recorded = store.get_task_progress(task_id)
    assert recorded["progress"] == {"total_items": 5, "completed_items": 2}
    assert recorded["outcome"] == "PARTIAL_SUCCESS"
    assert store.get_task_progress("c" * 32) is None


def test_the_observation_workflow_state_column_stays_workflow_owned(tmp_path):
    """Runner progress must never write the workflow engine's durable state."""
    store = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    task_id = "d" * 32
    store.upsert_task(
        task_id,
        filename="x.fasta",
        file_path="/tmp/x.fasta",
        uploaded_at=1.0,
        status="running",
        is_binary=0,
        task_type="multistage_runner",
        storage_key="tester",
        submitted_by_user_id=1,
        workflow_state=json.dumps({"multistage_runner.model": {"status": "running"}}),
    )
    store.record_task_progress(task_id, progress={"total_items": 1}, outcome="SUCCESS")
    assert json.loads(store.get_task(task_id)["workflow_state"]) == {"multistage_runner.model": {"status": "running"}}


def test_work_items_manifest_projection_is_ordered_and_bounded(tmp_path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    manifest = {
        "version": 1,
        "task_id": "e" * 32,
        "runner": "gpu_runner",
        "outcome": "PARTIAL_SUCCESS",
        "items": [
            {"id": "long", "status": "SUCCEEDED", "attempts": 1, "output_path": "long/", "error": None},
            {"id": "short", "status": "FAILED_RESOURCE", "attempts": 3, "output_path": "short/", "error": "OOM"},
            {"id": "tiny", "status": "PENDING", "attempts": 0, "output_path": "tiny/", "error": None},
        ],
    }
    (result_dir / "work_items.json").write_text(json.dumps(manifest), encoding="utf-8")
    projection = ro.work_items_projection(str(result_dir))
    assert [item["id"] for item in projection["work_items"]] == ["long", "short", "tiny"]
    assert projection["outcome"] == "CANCELLED_PARTIAL", "the derived outcome replaces the runner's string"
    assert projection["progress"] == {
        "total_items": 3,
        "completed_items": 1,
        "failed_items": 1,
        "pending_items": 1,
        "running_items": 0,
        "current_item": None,
    }


def test_work_items_projection_publishes_the_recovery_provenance(tmp_path):
    """The smallest existing result surface exposes requested vs effective.

    The per-item recovery record the runner kept is republished beside the
    item's state, with the scientific-impact class of the action aggregated onto
    the item, so a consumer reads whether the requested science survived
    recovery without touching scheduler logs.
    """
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    manifest = {
        "version": 1,
        "runner": "gpu_runner",
        "outcome": "SUCCESS",
        "items": [
            {
                "id": "clean",
                "status": "SUCCEEDED",
                "attempts": 1,
                "output_path": "clean/",
                "recovery": [
                    {"attempt": 1, "plan_label": "", "action": "", "resources": {}, "effective_parameters": {"n": 1}}
                ],
            },
            {
                "id": "adapted",
                "status": "SUCCEEDED",
                "attempts": 2,
                "output_path": "adapted/",
                "recovery": [
                    {"attempt": 1, "plan_label": "", "action": "", "resources": {}, "effective_parameters": {"n": 1}},
                    {
                        "attempt": 2,
                        "plan_label": "clear_cache",
                        "action": "resource_only",
                        "resources": {"cache_clear": True},
                        "effective_parameters": {"n": 1},
                    },
                ],
            },
            {
                "id": "split",
                "status": "SUCCEEDED",
                "attempts": 2,
                "output_path": "split/",
                "recovery": [
                    {"attempt": 1, "plan_label": "", "action": "", "resources": {}, "effective_parameters": {"n": 4}},
                    {
                        "attempt": 2,
                        "plan_label": "samples_two_at_a_time",
                        "action": "scientific_output",
                        "resources": {},
                        "effective_parameters": {"n": 4, "sample_groups": [2, 2]},
                    },
                ],
            },
        ],
    }
    (result_dir / "work_items.json").write_text(json.dumps(manifest), encoding="utf-8")

    projection = ro.work_items_projection(str(result_dir))

    clean, adapted, split = projection["work_items"]
    # The item that never adapted discloses no recovery action.
    assert clean["recovery_action"] == ""
    assert [record["attempt"] for record in clean["recovery"]] == [1]
    # A resource-only recovery action leaves the requested set untouched.
    assert adapted["recovery_action"] == ro.RECOVERY_ACTION_RESOURCE_ONLY
    assert [record["action"] for record in adapted["recovery"]] == ["", "resource_only"]
    assert adapted["recovery"][-1]["resources"] == {"cache_clear": True}
    assert all(record["effective_parameters"] == {"n": 1} for record in adapted["recovery"])
    # A scientific-output action (a sample-grouping change) is reported as one,
    # and its divergence from the request is visible in the effective set.
    assert split["recovery_action"] == ro.RECOVERY_ACTION_SCIENTIFIC_OUTPUT
    assert split["recovery"][-1]["effective_parameters"]["sample_groups"] == [2, 2]


def test_recovery_action_class_reports_the_most_impactful_action(tmp_path):
    """A numerical or unsafe action is never reported as resource-only."""
    assert ro.recovery_action_class({}) == ""
    assert ro.recovery_action_class({"recovery": [{"action": "resource_only"}]}) == ro.RECOVERY_ACTION_RESOURCE_ONLY
    assert (
        ro.recovery_action_class({"recovery": [{"action": "resource_only"}, {"action": "numerical_backend"}]})
        == ro.RECOVERY_ACTION_NUMERICAL_BACKEND
    )
    assert (
        ro.recovery_action_class({"recovery": [{"action": "numerical_backend"}, {"action": "unsafe"}]})
        == ro.RECOVERY_ACTION_UNSAFE
    )
    # A malformed record is not a claim of neutrality.
    assert ro.recovery_action_class({"recovery": ["not a record"]}) == ""




def test_work_items_recovery_records_are_bounded(tmp_path):
    result_dir = tmp_path / "bounded"
    result_dir.mkdir()
    records = [{"attempt": index, "action": "resource_only"} for index in range(ro.RECOVERY_RECORDS_LIMIT + 20)]
    (result_dir / "work_items.json").write_text(
        json.dumps({"items": [{"id": "a", "status": "SUCCEEDED", "recovery": records}]}), encoding="utf-8"
    )

    projection = ro.work_items_projection(str(result_dir))

    assert len(projection["work_items"][0]["recovery"]) == ro.RECOVERY_RECORDS_LIMIT


def test_work_items_reads_are_failure_tolerant(tmp_path):
    result_dir = tmp_path / "empty"
    result_dir.mkdir()
    assert ro.read_work_items(str(result_dir)) is None
    (result_dir / "work_items.json").write_text("{half written", encoding="utf-8")
    assert ro.work_items_projection(str(result_dir)) is None
    (result_dir / "work_items.json").write_text('{"items": "not a list"}', encoding="utf-8")
    assert ro.read_work_items(str(result_dir)) is None


def test_work_items_reader_is_bounded_and_structure_checked(tmp_path):
    """A byte cap is not a structure cap: nested lists are small and unbounded."""
    result_dir = tmp_path / "manifest"
    result_dir.mkdir()
    manifest = result_dir / "work_items.json"
    manifest.write_text('{"items": ' + "[" * 20_000, encoding="utf-8")
    assert ro.read_work_items(str(result_dir)) is None
    manifest.write_text(json.dumps({"outcome": "SUCCESS", "items": [{"id": "a"}, "not a dict"]}), encoding="utf-8")
    assert ro.read_work_items(str(result_dir)) is None
    manifest.write_text(
        json.dumps({"items": [{"id": f"p{i}"} for i in range(ro.WORK_ITEMS_MAX_ITEMS + 10)]}), encoding="utf-8"
    )
    assert len(ro.read_work_items(str(result_dir))["items"]) == ro.WORK_ITEMS_MAX_ITEMS


def test_work_items_reader_never_follows_a_symlink(tmp_path):
    """A symlinked manifest must not project another task's items into this one."""
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    (elsewhere / "work_items.json").write_text(
        json.dumps({"outcome": "FAILED", "items": [{"id": "other-task-item", "status": "FAILED_RUNTIME"}]}),
        encoding="utf-8",
    )
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    (result_dir / "work_items.json").symlink_to(elsewhere / "work_items.json")
    assert ro.read_work_items(str(result_dir)) is None
    assert ro.work_items_projection(str(result_dir)) is None


def test_a_disagreeing_runner_outcome_is_replaced_by_the_derived_one(tmp_path):
    """The server owns the derived semantics; the runner's string is a cross-check."""
    result_dir = tmp_path / "outcome"
    result_dir.mkdir()
    (result_dir / "work_items.json").write_text(
        json.dumps(
            {
                "outcome": "SUCCESS",
                "items": [
                    {"id": "p1", "status": "SUCCEEDED", "attempts": 1},
                    {"id": "p2", "status": "FAILED_RESOURCE", "attempts": 3},
                    {"id": "p3", "status": "RUNNING", "attempts": 1},
                ],
            }
        ),
        encoding="utf-8",
    )
    projection = ro.work_items_projection(str(result_dir))
    assert projection["outcome"] == "CANCELLED_PARTIAL"
    (result_dir / "work_items.json").write_text(
        json.dumps({"outcome": "FAILED", "items": [{"id": "p1", "status": "SUCCEEDED", "attempts": 1}]}),
        encoding="utf-8",
    )
    assert ro.work_items_projection(str(result_dir))["outcome"] == "SUCCESS"


def test_derive_outcome_matches_the_runner_rule():
    def item(status):
        return {"id": "x", "status": status}

    assert ro.derive_outcome([item("SUCCEEDED"), item("SUCCEEDED")]) == "SUCCESS"
    assert ro.derive_outcome([item("SUCCEEDED"), item("FAILED_RESOURCE")]) == "PARTIAL_SUCCESS"
    assert ro.derive_outcome([item("FAILED_INPUT"), item("FAILED_RUNTIME")]) == "FAILED"
    for pending in ("PENDING", "RUNNING", "CANCELLED"):
        assert ro.derive_outcome([item("SUCCEEDED"), item(pending)]) == "CANCELLED_PARTIAL"


# ---------------------------------------------------------------------------
# task.json (runner protocol v4)
# ---------------------------------------------------------------------------


def test_submission_manifest_is_v4_and_keeps_params_and_inputs(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "cpu_runner"},
    )
    get_task_type = module.task_runtime._get_task_type
    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    class _Queued:
        id = "queued-demo"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: _Queued())
    with (ROOT / "tests/data/msa/2KL8.fasta").open("rb") as handle:
        response = client.post(
            "/compute/api/post",
            headers=auth_header,
            data={
                "task_type": "cpu_runner",
                "params[mass_precision]": "4",
                "file": (handle, "2KL8.fasta"),
                "input_roles": "sequence",
            },
            content_type="multipart/form-data",
        )
    assert response.status_code == 302, response.get_data(as_text=True)[:300]
    task = module.task_store.get_task(response.headers["Location"].rsplit("/", 1)[-1])
    manifest = json.loads(
        (Path(module.app.config["storage_resolver"].get_input_root(task)) / "inputs" / "task.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["version"] == 4
    assert manifest["params"]["mass_precision"] == 4
    assert manifest["inputs"]["sequence"][0]["relative_path"] == "2KL8.fasta"
    assert manifest["execution"] == {"batch_size": 1, "max_item_attempts": 1, "max_runtime_restarts": 1}
    assert manifest["execution_queue"]["ratios"] == [1.5, 2.0]
    assert manifest["resource_adaptation"]["stage"] in rm.STAGES
    # Whatever the owning manifest declares is exactly what the runner is told:
    # the example family declares a serial fallback, an undeclared family would
    # project an empty plan list.
    declared = get_task_type("cpu_runner")[0].resource_adaptation
    assert manifest["resource_adaptation"] == declared.to_dict()
    assert manifest["resource_guidance"]["plan_order"] == ["", *[plan.label for plan in declared.fallback_plans]]
    assert manifest["resource_guidance"]["profiles"] == []


def test_manifest_projects_the_owning_manifests_policy_and_observed_guidance(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "synthetic"},
    )
    family = Path(module.CONFIG.runners_dir) / "synthetic"
    task_dir = family / "tasks" / "echo"
    task_dir.mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        "api_version: 1\nid: synthetic\nversion: '1'\n"
        "runtime: {image_artifact: synthetic.sif, definition: synthetic.def}\n"
        "tasks: [tasks/echo/task.yaml]\n",
        encoding="utf-8",
    )
    (family / "synthetic.def").write_text("Bootstrap: synthetic\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        "id: echo\ndisplay_name: Echo\n"
        "inputs:\n  sequence: {type: protein_sequence, formats: [fasta], cardinality: {min: 1, max: 1}}\n"
        "execution: {batch_size: 2, max_item_attempts: 3, max_runtime_restarts: 1}\n"
        "execution_queue: {ratios: [1.5, 2.0]}\n"
        "resource_adaptation:\n  stage: recover\n  fallback_plans:\n"
        "  - label: split-samples\n    title: Split samples\n    adjustments: {sample_group_size: 1}\n"
        "parameters:\n  type: object\n  additionalProperties: false\n  properties:\n"
        "    iter: {type: integer}\n",
        encoding="utf-8",
    )
    module.task_runtime._discover_plugins(str(module.CONFIG.runners_dir), {"synthetic"})

    for index in range(4):
        module.task_store.record_resource_observation(
            _observation(runner="synthetic", task_id=f"{index:032x}", work_item=f"p{index}", attempt=1)
        )
    module.task_store.record_resource_observation(
        _observation(
            runner="synthetic",
            task_id="f" * 32,
            work_item="p9",
            attempt=2,
            outcome="oom",
            available_mb=100,
            plan_label="split-samples",
        )
    )

    client = module.app.test_client()
    auth_header = _test_client_auth(module)

    class _Queued:
        id = "queued-synthetic"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: _Queued())
    response = client.post(
        "/compute/api/post",
        headers=auth_header,
        data={
            "task_type": "echo",
            "params[iter]": "3",
            "file": (__import__("io").BytesIO(b">x\nACDE\n"), "x.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302, response.get_data(as_text=True)[:300]
    task = module.task_store.get_task(response.headers["Location"].rsplit("/", 1)[-1])
    manifest = json.loads(
        (Path(module.app.config["storage_resolver"].get_input_root(task)) / "inputs" / "task.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["execution"] == {"batch_size": 2, "max_item_attempts": 3, "max_runtime_restarts": 1}
    assert manifest["resource_adaptation"] == {
        "stage": "recover",
        "fallback_plans": [
            {"label": "split-samples", "title": "Split samples", "adjustments": {"sample_group_size": 1}}
        ],
    }
    # The runner owns the stage; the server's guidance only carries what it has
    # learned, so a recover-stage task publishes the order and no avoidance.
    assert manifest["resource_guidance"] == {
        "stage": "recover",
        "plan_order": ["", "split-samples"],
        "profiles": [],
    }
    # The runner history stays server-side: guidance is its only projection into
    # the manifest, so the raw observation rows are not shipped to the job.
    assert "observations" not in manifest


# ---------------------------------------------------------------------------
# Partial-success outcome in the finalized manifest
# ---------------------------------------------------------------------------


def test_a_partial_success_still_finalizes_as_finished(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gpu_runner"},
    )
    # The bearer identity must exist before the task row is owned by it:
    # ``_task_owner`` creates the user unverified, so an auth header taken
    # afterwards would resolve to no user and read as not_found.
    auth_header = _test_client_auth(module)
    md5sum = uuid.uuid4().hex
    result_dir = tmp_path / "partial"
    result_dir.mkdir()
    (result_dir / "protein_001").mkdir()
    (result_dir / "protein_001" / "sample_0.cif").write_text("data_x\n", encoding="utf-8")
    (result_dir / "work_items.json").write_text(
        json.dumps(
            {
                "version": 1,
                "task_id": md5sum,
                "runner": "gpu_runner",
                "outcome": "PARTIAL_SUCCESS",
                "items": [
                    {"id": "protein_001", "status": "SUCCEEDED", "attempts": 1, "output_path": "protein_001/"},
                    {
                        "id": "protein_002",
                        "status": "FAILED_RESOURCE",
                        "attempts": 3,
                        "output_path": "protein_002/",
                        "error": "CUDA out of memory",
                        "recovery": [
                            {"attempt": 1, "plan_label": "", "action": "", "resources": {}, "effective_parameters": {}},
                            {
                                "attempt": 2,
                                "plan_label": "samples_one_at_a_time",
                                "action": "scientific_output",
                                "resources": {},
                                "effective_parameters": {"sample_group_size": 1},
                            },
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    _upsert_task_for_user(
        module,
        md5sum,
        filename="multi.fasta",
        file_path=result_dir / "multi.fasta",
        result_dir=result_dir,
        username="tester",
        task_type="gpu_runner_predict",
    )
    task = module.task_store.get_task(md5sum)
    module.task_runtime._finalize_results_manifest(task, execution_state="completed", finished_at=1_700_000_000)
    module.task_store.update_task(md5sum, status="finished", finished_at=1_700_000_000)

    client = module.app.test_client()
    payload = client.get(f"/compute/api/results/{md5sum}", headers=auth_header).get_json()
    assert payload["outcome"] == "PARTIAL_SUCCESS"
    assert [item["id"] for item in payload["work_items"]] == ["protein_001", "protein_002"]
    assert payload["work_items"][1]["error"] == "CUDA out of memory"
    # The adaptive-OOM provenance reaches the published result: the failing item
    # names the recovery action it took at the class the runner assigned it. A
    # sample_group_size split is a scientific-output change, so the published
    # class must be scientific_output — never resource_only.
    assert payload["work_items"][1]["recovery_action"] == "scientific_output"
    assert [record["plan_label"] for record in payload["work_items"][1]["recovery"]] == [
        "",
        "samples_one_at_a_time",
    ]
    assert payload["progress"]["completed_items"] == 1
    assert payload["progress"]["failed_items"] == 1
    assert client.get(f"/compute/api/running/{md5sum}", headers=auth_header).status_code == 200


def test_a_single_item_task_publishes_a_null_outcome(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gpu_runner"},
    )
    auth_header = _test_client_auth(module)
    del auth_header
    md5sum = uuid.uuid4().hex
    result_dir = tmp_path / "single"
    result_dir.mkdir()
    (result_dir / "sample_0.cif").write_text("data_x\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="one.fasta",
        file_path=result_dir / "one.fasta",
        result_dir=result_dir,
        username="tester",
        task_type="gpu_runner_predict",
    )
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(md5sum), execution_state="completed", finished_at=1_700_000_000
    )
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["outcome"] is None
    assert "work_items" not in manifest
    assert "progress" not in manifest


# ---------------------------------------------------------------------------
# Live progress in the running payload
# ---------------------------------------------------------------------------


def test_running_payload_reports_live_per_item_progress(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gpu_runner"},
    )
    auth_header = _test_client_auth(module)
    md5sum = uuid.uuid4().hex
    result_dir = tmp_path / "live"
    result_dir.mkdir()
    (result_dir / "work_items.json").write_text(
        json.dumps(
            {
                "version": 1,
                "task_id": md5sum,
                "runner": "gpu_runner",
                "outcome": None,
                "items": [
                    {"id": "protein_001", "status": "SUCCEEDED", "attempts": 1, "output_path": "protein_001/"},
                    {"id": "protein_002", "status": "FAILED_RESOURCE", "attempts": 3, "output_path": "protein_002/"},
                    {"id": "protein_003", "status": "RUNNING", "attempts": 1, "output_path": "protein_003/"},
                ],
            }
        ),
        encoding="utf-8",
    )
    _upsert_task_for_user(
        module,
        md5sum,
        filename="multi.fasta",
        file_path=result_dir / "multi.fasta",
        result_dir=result_dir,
        username="tester",
        status="running",
        task_type="gpu_runner_predict",
    )

    client = module.app.test_client()
    payload = client.get(f"/compute/api/running/{md5sum}", headers=auth_header).get_json()
    assert payload["progress"] == {
        "total_items": 3,
        "completed_items": 1,
        "failed_items": 1,
        "pending_items": 0,
        "running_items": 1,
        "current_item": "protein_003",
    }
    assert payload.get("outcome") == "CANCELLED_PARTIAL", "a pending item derives CANCELLED_PARTIAL, not the runner's null"

    # The canonical Task list exposes the same projection consumed by Dashboard.
    tasks = client.get("/compute/api/tasks", headers=auth_header).get_json()["tasks"]
    listed = next(item for item in tasks if item["task_id"] == md5sum)
    assert listed["progress"]["current_item"] == "protein_003"


def test_live_progress_falls_back_to_the_runners_own_report(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gpu_runner"},
    )
    auth_header = _test_client_auth(module)
    md5sum = uuid.uuid4().hex
    result_dir = tmp_path / "reported"
    result_dir.mkdir()
    _upsert_task_for_user(
        module,
        md5sum,
        filename="multi.fasta",
        file_path=result_dir / "multi.fasta",
        result_dir=result_dir,
        username="tester",
        status="running",
        task_type="gpu_runner_predict",
    )
    module.task_store.record_task_progress(
        md5sum, progress={"total_items": 500, "completed_items": 217, "failed_items": 3}, outcome="PARTIAL_SUCCESS"
    )
    payload = module.app.test_client().get(f"/compute/api/running/{md5sum}", headers=auth_header).get_json()
    assert payload["progress"]["completed_items"] == 217
    assert payload["progress"]["failed_items"] == 3
    assert payload["outcome"] == "PARTIAL_SUCCESS"


def test_a_non_running_task_never_reads_the_live_manifest(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gpu_runner"},
    )
    _test_client_auth(module)
    md5sum = uuid.uuid4().hex
    result_dir = tmp_path / "settled"
    result_dir.mkdir()
    (result_dir / "work_items.json").write_text("{broken", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename="multi.fasta",
        file_path=result_dir / "multi.fasta",
        result_dir=result_dir,
        username="tester",
        status="finished",
        task_type="gpu_runner_predict",
    )
    task = module.task_store.get_task(md5sum)
    assert module.task_runtime._progress_summary(task) is None


def test_one_bad_manifest_does_not_500_the_dashboard(monkeypatch, tmp_path):
    """A hostile result tree degrades to no Task detail, never a list error."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "gpu_runner"},
    )
    auth_header = _test_client_auth(module)
    hostile = tmp_path / "hostile"
    hostile.mkdir()
    hostile_id = uuid.uuid4().hex
    _upsert_task_for_user(
        module,
        hostile_id,
        filename="multi.fasta",
        file_path=hostile / "multi.fasta",
        result_dir=hostile,
        username="tester",
        status="running",
        task_type="gpu_runner_predict",
    )
    # The runner owns its result tree, so it can plant a manifest that points at
    # another task's tree; the reader must refuse it rather than publish that
    # task's item ids and errors here.
    hostile_result = Path(module.task_runtime._task_result_dir(module.task_store.get_task(hostile_id)))
    upstream = hostile_result.parent / "other-task"
    upstream.mkdir()
    (upstream / "work_items.json").write_text(
        json.dumps({"outcome": "SUCCESS", "items": [{"id": "leaked_foreign_item", "status": "RUNNING"}]}),
        encoding="utf-8",
    )
    (hostile_result / "work_items.json").symlink_to(upstream / "work_items.json")
    (result_dir := tmp_path / "healthy").mkdir()
    (result_dir / "work_items.json").write_text(
        json.dumps({"items": [{"id": "healthy_item", "status": "RUNNING", "attempts": 1}]}), encoding="utf-8"
    )
    _upsert_task_for_user(
        module,
        uuid.uuid4().hex,
        filename="healthy.fasta",
        file_path=result_dir / "healthy.fasta",
        result_dir=result_dir,
        username="tester",
        status="running",
        task_type="gpu_runner_predict",
    )

    client = module.app.test_client()
    response = client.get("/compute/api/tasks", headers=auth_header)
    assert response.status_code == 200
    payload = response.get_json()
    assert any((item.get("progress") or {}).get("current_item") == "healthy_item" for item in payload["tasks"])
    assert "leaked_foreign_item" not in json.dumps(payload), "a symlinked manifest must not project another task's items"
