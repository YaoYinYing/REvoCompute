# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Placement submission correctness: persistence, idempotence, and crash safety.

Submission is the half of placement that can create a job, so these tests are
about *what a retry is allowed to do*: inject a crash before the scheduler is
asked, after it accepted and the response was lost, a lost job-id write, a
worker restart, a cancellation racing a submit, a stale partition, and a policy
change between planning and dispatch.  In every case recovery must either reuse
the recorded plan or stop and surface the ambiguity — never resolve a fresh
placement for a stage the scheduler may already own, and never ask the
scheduler twice for one stage.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from revocompute.db import TaskDatabase
from revocompute.job.runners.slurm_runner import SlurmJob
from revocompute.placement_dispatch import (
    DISPATCH_ALREADY_SUBMITTED,
    DISPATCH_SUBMISSION_UNRESOLVED,
    PlacementDispatchRefused,
    abandon_stage_submission,
    begin_stage_submission,
    confirm_stage_submitted,
    plan_stage_for_dispatch,
)
from revocompute.placement_policy import (
    PLACEMENT_RESOLVED_ACCELERATOR,
    PLACEMENT_RESOLVED_CPU,
    PLAN_STATE_SUBMITTED,
    PLAN_STATE_SUPERSEDED,
    PlacementPlan,
    PlacementPolicy,
    WorkloadRequirement,
)
from revocompute.resource_policy import resolve_resources

from test_slurm_runner import _FakeSrunProcess, _make_entities, _make_runner, _make_task_type

TASK_ID = "f" * 32
STAGE = "demo.model"

CLASSES = [
    {"name": "cpu", "partition": "cpu-dedicated", "accelerator": "none"},
    {"name": "gpu-standard", "partition": "gpu", "accelerator": "cuda"},
]
QUEUES = ("normal", "gpu", "cpu-dedicated")


def _policy(classes=None) -> PlacementPolicy:
    return PlacementPolicy.validate({"classes": list(classes or CLASSES)}, allowed_queues=QUEUES)


def _resolved(*, requires_gpu: bool = False) -> ResolvedResources:
    return resolve_resources(
        lambda _field: None,
        lambda _field: None,
        requires_gpu=requires_gpu,
        allowed_queues=QUEUES,
        default_timeout_seconds=3600,
    )


@pytest.fixture()
def store(tmp_path):
    return TaskDatabase(str(tmp_path / "tasks.sqlite3"))


def _plan(store, **overrides):
    """Plan one stage through the real dispatch seam.

    ``resolved``/``policy``/``allowed_queues`` are test inputs; everything the
    seam itself takes is forwarded unchanged, so the helper cannot hide a
    parameter the production callers rely on.
    """
    resolved = overrides.pop("resolved", None) or _resolved(
        requires_gpu=overrides.pop("requires_gpu", False)
    )
    policy = overrides.pop("policy", None) or _policy()
    return plan_stage_for_dispatch(
        store,
        task_id=overrides.pop("task_id", TASK_ID),
        stage_id=overrides.pop("stage_id", STAGE),
        requirement=WorkloadRequirement.from_resolved(resolved),
        resolved=resolved,
        policy=policy,
        allowed_queues=overrides.pop("allowed_queues", QUEUES),
        at=overrides.pop("at", None),
    )


# -- the plan is written before dispatch ---------------------------------------


def test_a_dispatch_plan_is_persisted_before_the_job_adapter_exists(store):
    dispatch = _plan(store)
    assert dispatch.reused is False
    record = store.get_live_placement_plan(TASK_ID, STAGE)
    assert record is not None
    assert record["state"] == "planned"
    assert record["reason_code"] == PLACEMENT_RESOLVED_CPU
    assert record["plan_digest"] == dispatch.plan_digest
    assert record["slurm_job_id"] is None
    assert record["submitted_at"] is None


def test_repeated_planning_reuses_the_recorded_request_byte_for_byte(store):
    first = _plan(store)
    second = _plan(store)
    assert second.reused is True
    assert second.plan_id == first.plan_id
    assert second.resolved == first.resolved
    assert store.get_placement_plan(TASK_ID, STAGE)["revision"] == 1


def test_a_policy_change_between_plan_and_dispatch_does_not_change_the_request(store):
    gpu = _resolved(requires_gpu=True)
    first = _plan(store, resolved=gpu, requires_gpu=True)
    assert first.plan.matched_class == "gpu-standard"
    # The operator changes the policy so the accelator class requests a
    # different partition.  The stage already has a live plan, so the request it
    # dispatches is the one recorded, not one re-resolved from the new policy.
    changed = _policy(
        [
            {"name": "cpu", "partition": "cpu-dedicated", "accelerator": "none"},
            {"name": "gpu-standard", "partition": "normal", "accelerator": "cuda"},
        ]
    )
    second = _plan(store, resolved=gpu, requires_gpu=True, policy=changed)
    assert second.reused is True
    assert second.resolved.partition == "gpu"
    assert second.plan_digest == first.plan_digest


def test_a_stale_partition_is_resolved_at_dispatch_and_recorded(store):
    dispatch = _plan(store, allowed_queues=("normal", "cpu-dedicated"))
    assert dispatch.resolved.partition == "cpu-dedicated"
    assert store.get_live_placement_plan(TASK_ID, STAGE)["resolved_json"].find("cpu-dedicated") > 0


# -- a submitted plan is historical fact ---------------------------------------


def test_a_submitted_plan_is_refused_rather_than_replanned_or_resubmitted(store):
    dispatch = _plan(store)
    begin_stage_submission(store, dispatch, at=10.0)
    confirm_stage_submitted(store, dispatch, slurm_job_id="4242", at=11.0)
    assert store.get_live_placement_plan(TASK_ID, STAGE)["state"] == PLAN_STATE_SUBMITTED

    with pytest.raises(PlacementDispatchRefused) as caught:
        _plan(store)
    assert caught.value.reason_code == DISPATCH_ALREADY_SUBMITTED
    # The recorded request is untouched by the refused dispatch.
    record = store.get_live_placement_plan(TASK_ID, STAGE)
    assert record["slurm_job_id"] == "4242"
    assert record["revision"] == 1


def test_the_submission_transition_is_one_way_and_idempotent(store):
    dispatch = _plan(store)
    begin_stage_submission(store, dispatch, at=10.0)
    confirm_stage_submitted(store, dispatch, slurm_job_id="4242", at=11.0)
    assert store.get_live_placement_plan(TASK_ID, STAGE)["state"] == PLAN_STATE_SUBMITTED
    # A reconciliation re-reading the same job must not write a second state.
    confirm_stage_submitted(store, dispatch, slurm_job_id="4242", at=12.0)
    record = store.get_live_placement_plan(TASK_ID, STAGE)
    assert record["state"] == PLAN_STATE_SUBMITTED
    assert record["submitted_at"] == 11.0


# -- crash injection -----------------------------------------------------------


def test_a_crash_after_planning_and_before_submit_leaves_a_resolved_plan(store):
    # Plan persisted, then the process dies before the adapter is constructed.
    _plan(store)
    # A restart re-enters dispatch for the same stage.
    replay = _plan(store)
    assert replay.reused is True
    assert store.get_live_placement_plan(TASK_ID, STAGE)["revision"] == 1


def test_a_lost_submit_response_stops_the_retry_instead_of_asking_again(store):
    dispatch = _plan(store)
    # srun was launched and the worker died before the scheduler's answer was
    # recorded.  Nothing here can tell whether a job exists, so the retry must
    # stop and surface it rather than submit a second request.
    begin_stage_submission(store, dispatch, at=10.0)
    with pytest.raises(PlacementDispatchRefused) as caught:
        _plan(store)
    assert caught.value.reason_code == DISPATCH_SUBMISSION_UNRESOLVED


def test_a_failed_launch_returns_the_plan_to_dispatchable(store):
    # The adapter reports that no scheduler process was ever started, so no
    # request can exist and the stage must not be blocked by its own attempt.
    dispatch = _plan(store)
    begin_stage_submission(store, dispatch, at=10.0)
    abandon_stage_submission(store, dispatch)
    retry = _plan(store)
    assert retry.reused is True
    record = store.get_live_placement_plan(TASK_ID, STAGE)
    assert record["submission_started_at"] is None
    assert record["state"] == "planned"


def test_a_restart_that_replans_a_superseded_stage_records_a_new_revision(store):
    first = _plan(store)
    # Recovery supersedes a stage it can no longer account for (a workflow stage
    # killed mid-run); the previous plan stays as history.
    assert store.supersede_placement_plan(first.plan_id) is True
    assert store.get_live_placement_plan(TASK_ID, STAGE) is None
    second = _plan(store)
    assert second.reused is False
    assert store.get_placement_plan(TASK_ID, STAGE)["revision"] == 2
    assert store.get_placement_plan(TASK_ID, STAGE, revision=1)["state"] == PLAN_STATE_SUPERSEDED


def test_an_explicit_replan_of_a_planned_stage_supersedes_the_previous_record(store):
    first = _plan(store)
    record = first.plan.to_record()
    # A different decision for the same stage, still before any dispatch: the
    # documented replan path.
    record["plan_digest"] = "sha256:" + "0" * 64
    record["reason_code"] = PLACEMENT_RESOLVED_ACCELERATOR
    stored = store.record_placement_plan(record=record)
    assert stored["revision"] == 2
    assert stored["state"] == "planned"
    assert store.get_placement_plan(TASK_ID, STAGE, revision=1)["state"] == PLAN_STATE_SUPERSEDED
    assert store.get_live_placement_plan(TASK_ID, STAGE)["plan_digest"] == record["plan_digest"]


def test_replanning_a_submitted_stage_is_refused_by_the_store(store):
    dispatch = _plan(store)
    begin_stage_submission(store, dispatch, at=1.0)
    confirm_stage_submitted(store, dispatch, slurm_job_id="7", at=2.0)
    record = dispatch.plan.to_record()
    record["plan_digest"] = "sha256:" + "1" * 64
    with pytest.raises(ValueError, match="already has a submitted placement plan"):
        store.record_placement_plan(record=record)


def test_recording_the_same_decision_twice_is_idempotent(store):
    dispatch = _plan(store)
    stored = store.record_placement_plan(record=dispatch.plan.to_record())
    assert stored["id"] == dispatch.plan_id
    assert stored["revision"] == 1


# -- the adapter drives the plan's submission transitions -----------------------


def _slurm_job(store, output_dir, *, policy=None, placement_dispatch=None):
    return SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=bool(policy and policy.requires_gpu)),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=policy,
        placement_dispatch=placement_dispatch,
        task_store=store,
    )


def test_a_successful_submit_marks_the_plan_submitted_and_reports_its_job(store, tmp_path):
    dispatch = _plan(store)
    job = _slurm_job(store, tmp_path / "out", policy=dispatch.resolved, placement_dispatch=dispatch)
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=0, pid=99)

    with patch("subprocess.Popen", return_value=fake_proc):
        assert job.submit() == "4217"

    stored = store.get_live_placement_plan(TASK_ID, STAGE)
    assert stored["state"] == PLAN_STATE_SUBMITTED
    assert stored["slurm_job_id"] == "4217"
    assert stored["submitted_at"] is not None


def test_a_launch_failure_leaves_the_plan_dispatchable(store, tmp_path):
    dispatch = _plan(store)
    job = _slurm_job(store, tmp_path / "out", policy=dispatch.resolved, placement_dispatch=dispatch)

    with patch("subprocess.Popen", side_effect=FileNotFoundError("srun not found")):
        with pytest.raises(FileNotFoundError):
            job.submit()

    stored = store.get_placement_plan(TASK_ID, STAGE)
    assert stored["state"] == "planned"
    assert stored["submission_started_at"] is None


def test_a_submit_whose_job_id_never_arrives_keeps_its_unresolved_stamp(store, tmp_path):
    dispatch = _plan(store)
    job = _slurm_job(store, tmp_path / "out", policy=dispatch.resolved, placement_dispatch=dispatch)
    fake_proc = _FakeSrunProcess(stdout="no id here\n", stderr="unexpected\n", returncode=None)

    with patch("subprocess.Popen", return_value=fake_proc):
        with pytest.raises(RuntimeError, match="did not return a scheduler job ID"):
            job.submit()

    # srun was launched, so a request may exist: the stamp stays, and the retry
    # is refused rather than launching a second one.
    stored = store.get_placement_plan(TASK_ID, STAGE)
    assert stored["state"] == "planned"
    assert stored["submission_started_at"] is not None
    with pytest.raises(PlacementDispatchRefused):
        _plan(store)


def test_the_argv_the_scheduler_receives_is_the_recorded_plan(store, tmp_path):
    gpu = _resolved(requires_gpu=True)
    dispatch = _plan(store, resolved=gpu, requires_gpu=True)
    job = _slurm_job(store, tmp_path / "out", policy=dispatch.resolved, placement_dispatch=dispatch)
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=0, pid=99)

    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        job.submit()

    argv = mock_popen.call_args.args[0]
    assert "--partition=gpu" in argv
    assert "--gres=gpu:1" in argv
    recorded = store.get_placement_plan(TASK_ID, STAGE)
    resolved = json.loads(recorded["resolved_json"])
    assert resolved["partition"] == "gpu"
    assert resolved["gres"] == "gpu:1"


def test_a_stage_without_a_plan_still_dispatches_through_the_adapter(store, tmp_path):
    # The adapter is usable without a plan (a synthetic SIF render, a test): the
    # plan is the decision record, not a precondition of the Job ABC.
    job = _slurm_job(store, tmp_path / "out", policy=_resolved(), placement_dispatch=None)
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=0, pid=99)
    with patch("subprocess.Popen", return_value=fake_proc):
        assert job.submit() == "4217"


# -- reading a historical plan -------------------------------------------------


def test_reading_a_stored_plan_never_consults_the_current_policy(store):
    dispatch = _plan(store, resolved=_resolved(requires_gpu=True), requires_gpu=True)
    begin_stage_submission(store, dispatch, at=1.0)
    confirm_stage_submitted(store, dispatch, slurm_job_id="9", at=2.0)
    record = store.get_placement_plan(TASK_ID, STAGE)
    # Rebuild from the stored columns alone: this reader takes no policy at all.
    plan = PlacementPlan.from_record(record)
    assert plan.resolved.partition == "gpu"
    assert plan.resolved.gres == "gpu:1"
    assert plan.policy_digest == dispatch.plan.policy_digest
    assert plan.slurm_job_id == "9"


def test_the_plan_reader_supports_the_reporting_surface(store):
    _plan(store, stage_id="demo.features", resolved=_resolved())
    _plan(store, stage_id="demo.model", resolved=_resolved(requires_gpu=True), requires_gpu=True)
    plans = store.list_placement_plans(task_id=TASK_ID)
    assert {record["stage_id"] for record in plans} == {"demo.features", "demo.model"}
    assert store.list_placement_plans(task_id=TASK_ID, state="planned") == plans
    assert store.list_placement_plans(task_id=TASK_ID, state="submitted") == []
