# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The producer -> consumer contract of GPU live-test accounting, one row set.

GPU live acceptance has two halves that only ever ran apart in tests: a
worker-side projector (``live_test_executor._gpu_accounting_evidence``) and the
validating predicate (``RunnerLiveTestWorker._gpu_accounting_valid``).  Each half
was asserted against a hand-built shape, so a legacy-key validator and a
canonical-shape projector could drift with CI green -- and they did, which is why
every GPU family failed ``GPU_ACCOUNTING_FAILURE`` on the target host while the
physical accounting was correct.

This module closes that gap the way the maintainer asked: write the canonical
``resource_allocations`` / ``resource_ledger`` rows a real two-stage NVIDIA Task
produces (a CPU-only ``features`` stage and a GPU ``model`` stage), pass the
projector's own output *unchanged* into the validator, and assert the three-way
equality the acceptance exists to prove:

    allocated GPU seconds == negative settled GPU usage == balance decrement

The CPU facts a GPU settlement must never credit are present in the same rows:
the zero-``resource_count`` ``gpu_second`` row the canonical model deliberately
writes for a CPU-only stage, and the ``cpu_core_second`` row every Slurm
allocation carries.  Every negative case is fail-closed: a mismatched stage, job,
subject, period, quantity, or a missing settlement is refused.
"""

from __future__ import annotations

import math
import time
from types import SimpleNamespace

import pytest

from revocompute import live_test_executor
from revocompute.db import TaskDatabase
from revocompute.runner_live_test import RunnerLiveTestWorker

TASK_ID = "7c1f" + "a" * 28
FEATURES_JOB = "217682"
MODEL_JOB = "217685"


def _evidence_for(two_stage_task, tmp_path, *, features_elapsed=18, model_elapsed=93):
    """Drive the real store, then project it exactly as the worker does.

    The allocation starts are stamped with the real clock, as the Producer stamps
    them: the case's settled facts and the balance the projector reads must belong
    to the same UTC month, or the ledger window would be empty for a reason that
    has nothing to do with the acceptance.
    """
    database = TaskDatabase(str(tmp_path / "gpu-accounting.sqlite3"))
    task_type = SimpleNamespace(
        gpus=True,
        runtime=SimpleNamespace(name="gpu-demo", access_policy=SimpleNamespace(requires=("licensed",))),
    )
    # ``_prepare_gpu_accounting`` reads ``task_runtime.task_store``/``CONFIG`` by
    # module attribute, so they are bound explicitly for the duration of the case.
    two_stage_task(database, tmp_path)
    context = live_test_executor._prepare_gpu_accounting(task_type)
    assert context is not None

    started = time.time()
    # A CPU-only stage: the canonical model writes a gpu_second fact with
    # ``resource_count`` 0 -- it held no GPU -- and a cpu_core_second fact.
    database.record_allocation_start(
        user_id=1,
        task_id=TASK_ID,
        stage_id="features",
        slurm_job_id=FEATURES_JOB,
        gpu_count=0,
        cpu_cores=16,
        started_at=started,
        required_entitlements=("licensed",),
    )
    database.settle_allocation_elapsed(
        FEATURES_JOB, elapsed_seconds=features_elapsed, finished_at=started + features_elapsed
    )
    # The GPU stage the case actually accepts: one A100 held for the elapsed time.
    gpu_started = started + 100
    database.record_allocation_start(
        user_id=1,
        task_id=TASK_ID,
        stage_id="model",
        slurm_job_id=MODEL_JOB,
        gpu_count=1,
        cpu_cores=4,
        started_at=gpu_started,
        required_entitlements=("licensed",),
        gres="gpu:a100:1",
    )
    database.settle_allocation_elapsed(
        MODEL_JOB, elapsed_seconds=model_elapsed, finished_at=gpu_started + model_elapsed
    )
    # The projector's real output, unmodified, is what the acceptance validator
    # is handed; the elapsed durations above are the same explicit seconds the
    # parameterized tests then mutate.
    return database, live_test_executor._gpu_accounting_evidence(TASK_ID, context)


@pytest.fixture
def two_stage_task(monkeypatch):
    """Bind the executor's module-level task store, one database per case."""

    def bind(database: TaskDatabase, tmp_path) -> None:
        monkeypatch.setattr(live_test_executor.task_runtime, "task_store", database)
        monkeypatch.setattr(live_test_executor.task_runtime, "CONFIG", SimpleNamespace(server_dir=str(tmp_path)))

    return bind


@pytest.fixture
def execution() -> dict[str, object]:
    """The Slurm identity the accepting execution reports: both stages, this Task."""
    return {
        "slurm_job_id": MODEL_JOB,
        "slurm_jobs": [
            {"stage": "features", "job_id": FEATURES_JOB},
            {"stage": "model", "job_id": MODEL_JOB},
        ],
    }


def test_the_projectors_own_output_reconciles_against_the_real_rows(two_stage_task, tmp_path, execution):
    """allocated GPU seconds == negative settled usage == balance decrement, exactly.

    The evidence is the projector's output, unmodified: 1 GPU x 93 s = 93 -- the
    ceiling of the elapsed allocation the ledger charges -- and every one of the
    four facts the settlement publishes is read back from it.
    """
    database, evidence = _evidence_for(two_stage_task, tmp_path)
    assert evidence is not None

    # Only the GPU fact the ledger charges is published: the zero-GPU features
    # stage and both cpu_core_second rows are real accounting facts, not credits.
    assert [(row["unit"], row["resource_count"], row["slurm_job_id"]) for row in evidence["allocations"]] == [
        ("gpu_second", 1, MODEL_JOB)
    ]
    assert [row["unit"] for row in evidence["usage_entries"]] == ["gpu_second"]
    assert all(row["stage_id"] == "model" for row in evidence["usage_entries"])
    # CPU evidence is present in the store and absent from the GPU projection.
    assert {row["unit"] for row in database.list_task_allocations(TASK_ID)} == {"gpu_second", "cpu_core_second"}

    allocated = sum(int(row["quantity"]) for row in evidence["allocations"])
    charged = -sum(int(row["quantity"]) for row in evidence["usage_entries"])
    decrement = evidence["before_remaining_gpu_seconds"] - evidence["after_remaining_gpu_seconds"]
    assert allocated == charged == decrement == 93
    assert allocated == math.ceil(93.0) == evidence["usage_gpu_seconds"]

    assert RunnerLiveTestWorker._gpu_accounting_valid(execution, evidence)


def test_a_cpu_only_features_stage_is_never_credited_as_gpu_seconds(two_stage_task, tmp_path, execution):
    """The GPU projection is not a Task-wide all-units read.

    Projecting the CPU facts as GPU credit is the second defect the fix closed:
    doing so here would publish the features stage's 16 x 18 = 288 core-seconds
    and the model stage's so-far-zero GPU facts as a GPU settlement.
    """
    database, evidence = _evidence_for(two_stage_task, tmp_path)
    assert evidence is not None
    rows = database.list_task_allocations(TASK_ID)
    assert {row["stage_id"] for row in rows if row["unit"] == "gpu_second"} == {"features", "model"}

    # A projection that kept every unit is refused by the validator, not credited.
    all_units = [dict(row) for row in rows]
    assert not RunnerLiveTestWorker._gpu_accounting_valid(execution, {**evidence, "allocations": all_units})
    # And so is one that published the CPU unit as the GPU fact.
    cpu_only = [dict(row) for row in rows if row["unit"] == "cpu_core_second"]
    assert not RunnerLiveTestWorker._gpu_accounting_valid(execution, {**evidence, "allocations": cpu_only})


@pytest.mark.parametrize(
    "mutate",
    [
        # A settlement that names a stage the allocation does not hold.
        lambda e: {**e, "allocations": [{**e["allocations"][0], "stage_id": "features"}]},
        # A job the accepting execution never reported.
        lambda e: {**e, "allocations": [{**e["allocations"][0], "slurm_job_id": "999999"}]},
        # Another subject's allocation.
        lambda e: {**e, "allocations": [{**e["allocations"][0], "subject_id": 2}]},
        # A quantity that is not ``resource_count * elapsed``.
        lambda e: {**e, "allocations": [{**e["allocations"][0], "quantity": 92}]},
    ],
)
def test_mismatched_allocation_facts_are_refused(two_stage_task, tmp_path, execution, mutate):
    _database, evidence = _evidence_for(two_stage_task, tmp_path)
    assert evidence is not None
    assert not RunnerLiveTestWorker._gpu_accounting_valid(execution, mutate(evidence))


@pytest.mark.parametrize(
    "mutate",
    [
        # A ledger usage fact in another period.
        lambda e: {**e, "usage_entries": [{**e["usage_entries"][0], "period": "1999-01"}]},
        # A ledger usage fact for another subject.
        lambda e: {**e, "usage_entries": [{**e["usage_entries"][0], "subject_id": 2}]},
        # A ledger usage fact whose stage does not match its own allocation.
        lambda e: {**e, "usage_entries": [{**e["usage_entries"][0], "stage_id": "features"}]},
        # A ledger quantity that does not equal the allocation it settles.
        lambda e: {**e, "usage_entries": [{**e["usage_entries"][0], "quantity": -92}]},
        # A ledger usage fact charged to another Task.
        lambda e: {**e, "usage_entries": [{**e["usage_entries"][0], "task_id": "b" * 32}]},
    ],
)
def test_mismatched_ledger_facts_are_refused(two_stage_task, tmp_path, execution, mutate):
    _database, evidence = _evidence_for(two_stage_task, tmp_path)
    assert evidence is not None
    assert not RunnerLiveTestWorker._gpu_accounting_valid(execution, mutate(evidence))


def test_a_missing_settlement_is_refused(two_stage_task, tmp_path, execution):
    """An unsettled allocation never proves a GPU draw, whichever half is missing."""
    _database, evidence = _evidence_for(two_stage_task, tmp_path)
    assert evidence is not None
    # No ledger fact at all: the balance may have moved, but nothing settled it.
    assert not RunnerLiveTestWorker._gpu_accounting_valid(execution, {**evidence, "usage_entries": []})
    # An allocation still in flight is not a settled fact.
    pending = {**evidence["allocations"][0], "status": "active"}
    assert not RunnerLiveTestWorker._gpu_accounting_valid(
        execution, {**evidence, "allocations": [pending], "usage_entries": []}
    )


def test_a_balance_that_does_not_match_the_settlement_is_refused(two_stage_task, tmp_path, execution):
    _database, evidence = _evidence_for(two_stage_task, tmp_path)
    assert evidence is not None
    for key, value in (("usage_gpu_seconds", 94), ("after_remaining_gpu_seconds", 1.0)):
        assert not RunnerLiveTestWorker._gpu_accounting_valid(execution, {**evidence, key: value})


def test_a_cpu_only_task_settles_no_gpu_credit(two_stage_task, tmp_path, execution):
    """A GPU live case that drew no GPU second has not proved the accounting."""
    database = TaskDatabase(str(tmp_path / "cpu-only.sqlite3"))
    task_type = SimpleNamespace(
        gpus=True,
        runtime=SimpleNamespace(name="gpu-demo", access_policy=SimpleNamespace(requires=("licensed",))),
    )
    two_stage_task(database, tmp_path)
    context = live_test_executor._prepare_gpu_accounting(task_type)
    assert context is not None
    started = time.time()
    database.record_allocation_start(
        user_id=1,
        task_id=TASK_ID,
        stage_id="features",
        slurm_job_id=FEATURES_JOB,
        gpu_count=0,
        cpu_cores=16,
        started_at=started,
        required_entitlements=("licensed",),
    )
    database.settle_allocation_elapsed(FEATURES_JOB, elapsed_seconds=30, finished_at=started + 30)

    evidence = live_test_executor._gpu_accounting_evidence(TASK_ID, context)
    assert evidence is not None
    # The store recorded the facts -- including the zero-GPU gpu_second row -- but
    # the projector publishes no GPU credit and the validator refuses the case.
    assert evidence["allocations"] == []
    assert evidence["usage_entries"] == []
    assert not RunnerLiveTestWorker._gpu_accounting_valid(execution, evidence)
