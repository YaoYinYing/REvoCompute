# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The durable dispatch contract: a queued Task keeps the placement it recorded.

A Task is placed once, before submission, and that placement is written beside its
frozen resource snapshot into ``input_form``.  Every case drives that record
through a real consumer — the Flask submission route, the worker's own
reconstruction path (``task_runtime._execute_compute_task``), the workflow
composer, the Slurm adapter's resolution boundary, and the Admin read model — and
asserts the behaviour an operator depends on:

* a Task queued under one execution-class map dispatches with *that* map and
  reports *that* revision after the deployment moves on, while a fresh submission
  moves;
* each workflow stage dispatches the class its own declaration resolved to, and a
  CPU stage never carries an accelerator request;
* the adapter's re-resolution fallback exists only for a caller with no snapshot;
* a corrupt snapshot, a record that disagrees with its own snapshot, and an
  accelerator request this deployment cannot place all fail closed before
  anything is dispatched, with a bounded reason rather than a traceback.

A recorded decision whose frozen snapshot is gone is a torn record: the worker
fails that Task closed rather than re-resolving it, so a Task placed under one
policy is never dispatched under another.  A row that recorded neither half
predates the record and still dispatches through the deployment's own resolver.

No GPU, no cluster, no SIF: the accelerator capability is deployment
configuration, which is exactly what it is.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import _load_pssm_module, _test_client_auth
from revocompute import admin_reports as ar
from revocompute.job.runners.slurm_runner import SlurmJob
from revocompute.manage_db import ManageDatabase
from revocompute.placement import (
    ACCELERATOR_UNAVAILABLE,
    PLACED_ACCELERATOR,
    PLACED_ACCELERATOR_UNTYPED,
    PLACED_CPU,
    AcceleratorRequirement,
    PlacementDecision,
    resolve_submission_placement,
)
from revocompute.resource_policy import ResolvedResources
from revocompute.task_types import get as get_task_type
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[2]
CPU_GRES = "gpu:a100:1"
#: One deployment that names two classes: a CPU queue and a typed accelerator.
CPU_CLASSES = "cpu=normal;a100=swift"
#: The same map, plus the deployment-local values that make device work resolvable.
ACCELERATOR_DEPLOYMENT = {"slurm_allowed_queues": ["normal", "swift"], "slurm_gres": CPU_GRES}


# --------------------------------------------------------------------------- #
# Real consumers, driven directly
# --------------------------------------------------------------------------- #


def _module(monkeypatch, tmp_path):
    return _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})


def _queued(monkeypatch, module):
    """Dispatch nothing, but hand the submission a Celery result with an id."""
    monkeypatch.setattr(
        module.run_compute_task,
        "apply_async",
        lambda *args, **kwargs: SimpleNamespace(id="celery-dispatch-id"),
    )


def _submit(client, headers, *, task_type="cpu_runner", content=b">sequence\nACDEFGHIK\n", filename="sequence.fasta"):
    return client.post(
        "/compute/api/post",
        headers=headers,
        data={
            "task_type": task_type,
            "files": (io.BytesIO(content), filename),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )


def _submitted_task(module, client, headers, **kwargs) -> str:
    response = _submit(client, headers, **kwargs)
    assert response.status_code in {200, 201, 202, 302}, response.get_data(as_text=True)
    # The row list is newest-first, so index 0 is the Task just submitted.
    return module.task_store.list_tasks()[0]["md5sum"]


def _recorded_form(module, task_id) -> dict:
    return json.loads(module.task_store.get_task(task_id)["input_form"])


def _run_worker(module, monkeypatch, task_id) -> list:
    """Run the worker's real reconstruction path, returning what it dispatched with.

    Only the allocation itself is replaced: ``_execute_compute_task`` reads the
    Task row, rebuilds the snapshot from ``input_form``, and hands what it built to
    the job adapter.  The list therefore holds the resource plan the worker would
    have submitted, one entry per allocation.
    """
    captured: list = []

    def _capture(task_id, tt, runner, entities, output_dir, stage_callback=None, username="", resource_policy=None):
        captured.append(resource_policy)
        return module.task_runtime.JobState.CANCELLED

    monkeypatch.setattr(module.task_runtime, "_run_compute_job", _capture)
    module.task_runtime._execute_compute_task(task_id)
    return captured


def _recorded_join(module, task_id) -> dict:
    """The recorded decision joined to the frozen snapshot stored beside it."""
    form = _recorded_form(module, task_id)
    return {
        "record": form["placement_decision"],
        "resources": ResolvedResources.from_snapshot(form["resource_policy"]),
    }


def _class_map(module, *, classes=None, globals_=None):
    manage_db = module.app.config["manage_db"]
    if classes is not None:
        manage_db.resource_set("slurm_execution_classes", classes)
    for key, value in (globals_ or {}).items():
        manage_db.resource_set(key, value)
    return manage_db


# --------------------------------------------------------------------------- #
# 1 & 5. The queued Task dispatches the plan it recorded, at the revision it recorded
# --------------------------------------------------------------------------- #


def test_the_worker_dispatches_the_persisted_plan_not_a_re_resolution(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _queued(monkeypatch, module)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    _class_map(module, classes="cpu=normal", globals_={"slurm_allowed_queues": ["normal"]})

    first = _submitted_task(module, client, headers)
    form = _recorded_form(module, first)
    frozen = form["resource_policy"]
    assert frozen["partition"] == "normal"
    before = PlacementDecision.from_record(**_recorded_join(module, first))
    assert before.policy_revision.startswith("sha256:")
    assert before.execution_class.identifier == "cpu|normal|none"

    # The deployment moves to another map while the Task is still queued — and the
    # queue the Task was placed on is no longer one this deployment names.
    _class_map(module, classes="cpu=swift", globals_={"slurm_allowed_queues": ["swift"]})

    second = _submitted_task(module, client, headers, content=b">sequence\nACDEFGHIL\n")
    after = PlacementDecision.from_record(**_recorded_join(module, second))
    assert after.policy_revision != before.policy_revision, "a different map is a different revision"
    assert after.execution_class.identifier == "cpu|swift|none"

    # The queued Task still dispatches the plan it recorded, at the revision it
    # recorded: a revision is version identity, not a verdict on today's policy.
    dispatched = _run_worker(module, monkeypatch, first)
    assert len(dispatched) == 1, "exactly one allocation is dispatched"
    assert dispatched[0].public_dict() == frozen
    assert _recorded_form(module, first) == form
    assert PlacementDecision.from_record(**_recorded_join(module, first)).policy_revision == before.policy_revision

    # ...while a Task submitted under the new map dispatches the new one.
    assert _run_worker(module, monkeypatch, second)[0].partition == "swift"


# --------------------------------------------------------------------------- #
# 2. Stage-level placement is per stage, and a CPU stage never asks for a device
# --------------------------------------------------------------------------- #


def _staged(names, *, gpu, requirement=None):
    """A task whose stages are named, of which only the accelerator stage is a device."""
    stages = []
    for name in names:
        is_device_stage = name == gpu
        stages.append(
            SimpleNamespace(
                name=name,
                requires_gpu=is_device_stage,
                accelerator_requirement=requirement if is_device_stage else None,
            )
        )
    return SimpleNamespace(name="staged", gpus=True, accelerator_requirement=None, workflow=tuple(stages))


def test_every_workflow_stage_resolves_the_class_its_own_declaration_names(tmp_path):
    manage_db = ManageDatabase(str(tmp_path / "manage.sqlite3"))
    try:
        manage_db.resource_set("slurm_execution_classes", CPU_CLASSES)
        manage_db.resource_set("slurm_allowed_queues", ["normal", "swift"])
        manage_db.resource_set("slurm_gres", CPU_GRES)
        with isolated_discovery(str(ROOT / "tests" / "fixtures" / "runners"), {"multistage_runner"}):
            task_type, runner = get_task_type("multistage_runner")
            placement = resolve_submission_placement(manage_db, task_type, runner)

        # The real multistage fixture: its declared preparation stage is CPU work
        # and its declared calculation stage is device work.
        assert placement.primary is None
        assert list(placement.stage_resources) == ["multistage_runner.features", "multistage_runner.model"]
        features = placement.stage_resources["multistage_runner.features"]
        model = placement.stage_resources["multistage_runner.model"]
        assert (features.requires_gpu, features.gres, features.partition) == (False, None, "normal")
        assert (model.requires_gpu, model.gres, model.partition) == (True, CPU_GRES, "swift")
        assert placement.stage_decisions["multistage_runner.features"].reason_code == PLACED_CPU
        assert placement.stage_decisions["multistage_runner.model"].reason_code == PLACED_ACCELERATOR_UNTYPED

        # The requested shape, end to end: CPU -> GPU -> CPU, each leg on its own
        # class, and the two CPU legs must not carry an accelerator request.
        staged = _staged(
            ["staged.prep", "staged.calc", "staged.report"],
            gpu="staged.calc",
            requirement=AcceleratorRequirement("a100", 1),
        )
        staged_placement = resolve_submission_placement(manage_db, staged, SimpleNamespace(max_runtime_seconds=3600))

        assert list(staged_placement.stage_resources) == ["staged.prep", "staged.calc", "staged.report"]
        assert [(p.requires_gpu, p.gres, p.partition) for p in staged_placement.stage_resources.values()] == [
            (False, None, "normal"),
            (True, CPU_GRES, "swift"),
            (False, None, "normal"),
        ]
        assert [d.reason_code for d in staged_placement.stage_decisions.values()] == [
            PLACED_CPU,
            PLACED_ACCELERATOR,
            PLACED_CPU,
        ]
        # A CPU stage never requests an accelerator.
        assert all(p.gres is None for p in staged_placement.stage_resources.values() if not p.requires_gpu)

        # The same holds when the device stage comes first.
        leading = resolve_submission_placement(
            manage_db,
            _staged(["staged.calc", "staged.report"], gpu="staged.calc", requirement=AcceleratorRequirement("a100", 1)),
            SimpleNamespace(max_runtime_seconds=3600),
        )
        assert [(p.requires_gpu, p.gres, p.partition) for p in leading.stage_resources.values()] == [
            (True, CPU_GRES, "swift"),
            (False, None, "normal"),
        ]
    finally:
        manage_db.close()


def test_a_multistage_submission_dispatches_each_stage_with_its_own_snapshot(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _queued(monkeypatch, module)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    module.app.config["user_db"].update_user(
        module.app.config["user_db"].get_user_by_username("tester")["id"], allow_gpu_use=True
    )
    _class_map(module, classes=CPU_CLASSES, globals_=ACCELERATOR_DEPLOYMENT)

    task_id = _submitted_task(module, client, headers, task_type="multistage_runner")
    form = _recorded_form(module, task_id)
    assert form["placement_decision"] is None
    assert set(form["placement_decisions"]) == {"multistage_runner.features", "multistage_runner.model"}
    assert form["resource_policies"]["multistage_runner.features"]["gres"] is None
    assert form["resource_policies"]["multistage_runner.model"]["gres"] == CPU_GRES

    # Each leg is one allocation, and the composer consumes the stage's own
    # snapshot for it.
    dispatched: list[tuple[str, object]] = []

    class _CompletedJob:
        def submit(self):
            return "42"

        def poll(self):
            return module.task_runtime.JobState.COMPLETED

    def _capture(_task_id, tt, runner, entities, output_dir, stage_callback=None, username="", **kwargs):
        dispatched.append((tt.name, kwargs.get("resource_policy")))
        return _CompletedJob()

    monkeypatch.setattr(module.task_runtime, "_create_job", _capture)
    monkeypatch.setattr(
        module.task_runtime,
        "_run_compute_job",
        lambda *args, **kwargs: pytest.fail("a workflow stage is not a single job"),
    )
    module.task_runtime._execute_compute_task(task_id)

    assert [name for name, _policy in dispatched] == ["multistage_runner-features", "multistage_runner-model"]
    (features, model) = (policy for _name, policy in dispatched)
    assert (features.requires_gpu, features.gres, features.partition) == (False, None, "normal")
    assert (model.requires_gpu, model.gres, model.partition) == (True, CPU_GRES, "swift")
    # Both legs ran to completion, in declared order, each under its own handle.
    workflow_state = json.loads(module.task_store.get_task(task_id)["workflow_state"])
    assert list(workflow_state) == ["multistage_runner.features", "multistage_runner.model"]
    assert [state["status"] for state in workflow_state.values()] == ["completed", "completed"]



# --------------------------------------------------------------------------- #
# 3. The adapter's fallback is for a caller with no snapshot, and only that caller
# --------------------------------------------------------------------------- #


def _srun(module, tmp_path, *, manage_db=None, resource_policy=None, task_type="cpu_runner") -> list[str]:
    tt, runner = module.task_runtime._get_task_type(task_type)
    job = SlurmJob(
        "a" * 32,
        tt,
        runner,
        [],
        str(tmp_path / "out"),
        manage_db=manage_db,
        resource_policy=resource_policy,
    )
    return job._build_srun_args()


def _option(args: list[str], name: str) -> str | None:
    prefix = f"--{name}="
    return next((arg[len(prefix) :] for arg in args if arg.startswith(prefix)), None)


def test_the_adapter_submits_a_supplied_snapshot_and_re_resolves_only_without_one(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    manage_db = _class_map(module, classes="cpu=normal", globals_={"slurm_allowed_queues": ["normal"]})
    snapshot = manage_db.resolve_task_resources("cpu_runner", requires_gpu=False, default_timeout_seconds=3600)
    assert snapshot.partition == "normal"

    # The deployment moves on; only a caller that supplies the snapshot is pinned.
    _class_map(module, classes="cpu=swift", globals_={"slurm_allowed_queues": ["normal", "swift"]})

    pinned = _srun(module, tmp_path, manage_db=manage_db, resource_policy=snapshot)
    re_resolved = _srun(module, tmp_path, manage_db=manage_db)
    bare = _srun(module, tmp_path)

    assert _option(pinned, "partition") == "normal"
    assert _option(re_resolved, "partition") == "swift"
    # A caller with neither a snapshot nor a store resolves the safe defaults,
    # which name no deployment queue and request no device.
    assert _option(bare, "partition") is None
    assert _option(bare, "gres") is None
    assert _option(pinned, "gres") is None and _option(re_resolved, "gres") is None


# --------------------------------------------------------------------------- #
# 4. Fail closed, before anything is dispatched, with a bounded reason
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("corruption", ["missing_field", "unparseable"])
def test_a_corrupt_resource_snapshot_fails_the_task_without_dispatching(monkeypatch, tmp_path, corruption):
    module = _module(monkeypatch, tmp_path)
    _queued(monkeypatch, module)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    _class_map(module, classes="cpu=normal", globals_={"slurm_allowed_queues": ["normal"]})

    task_id = _submitted_task(module, client, headers)
    form = _recorded_form(module, task_id)
    if corruption == "missing_field":
        del form["resource_policy"]["cpus"]
        input_form = json.dumps(form)
    else:
        input_form = "{not json at all"
    module.task_store.update_task(task_id, input_form=input_form)

    assert _run_worker(module, monkeypatch, task_id) == []

    task = module.task_store.get_task(task_id)
    assert task["status"] == "failed"
    error = str(task["error"] or "")
    assert error and "Traceback" not in error and str(tmp_path) not in error
    assert task.get("slurm_job_id") in (None, "")


def test_a_row_predating_the_snapshot_dispatches_through_the_deployment_resolver(monkeypatch, tmp_path):
    """The one case the adapter's fallback exists for, reached through the worker.

    A Task that records neither a snapshot nor a decision predates the record
    entirely, so the worker supplies no plan and the adapter's own resolution is
    what runs.  This is the compatibility path, not a failure — and it is the
    reason the fallback must never be reachable for a row that *does* carry a
    snapshot.
    """
    module = _module(monkeypatch, tmp_path)
    _queued(monkeypatch, module)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    _class_map(module, classes="cpu=normal", globals_={"slurm_allowed_queues": ["normal"]})

    task_id = _submitted_task(module, client, headers)
    form = _recorded_form(module, task_id)
    del form["resource_policy"]
    del form["placement_decision"]
    module.task_store.update_task(task_id, input_form=json.dumps(form))

    dispatched = _run_worker(module, monkeypatch, task_id)

    assert dispatched == [None], "no snapshot is supplied, so the adapter resolves it"
    assert module.task_store.get_task(task_id)["status"] == "cancelled"


def test_a_queued_task_that_recorded_a_placement_never_dispatches_from_a_re_resolution(monkeypatch, tmp_path):
    """A recorded decision without its snapshot is a torn record, not a licence to re-plan."""
    module = _module(monkeypatch, tmp_path)
    _queued(monkeypatch, module)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    _class_map(module, classes="cpu=normal", globals_={"slurm_allowed_queues": ["normal", "swift"]})

    task_id = _submitted_task(module, client, headers)
    form = _recorded_form(module, task_id)
    assert form["placement_decision"]["execution_class"]["partition"] == "normal"

    # The Task is still queued when the deployment moves to another map, and its
    # frozen snapshot is gone.  What it recorded is still "normal".
    _class_map(module, classes="cpu=swift", globals_={"slurm_allowed_queues": ["normal", "swift"]})
    del form["resource_policy"]
    module.task_store.update_task(task_id, input_form=json.dumps(form))

    dispatched = _run_worker(module, monkeypatch, task_id)

    assert dispatched == [], (
        "required: a Task whose recorded placement can no longer be honoured is failed, never dispatched from "
        f"today's policy; it dispatched {len(dispatched)} allocation(s) instead, resolved from the deployment's "
        "current map rather than from the decision recorded on the Task"
    )


def test_a_record_that_disagrees_with_its_snapshot_is_unreadable_and_never_dispatched_from(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _queued(monkeypatch, module)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    _class_map(module, classes="cpu=normal", globals_={"slurm_allowed_queues": ["normal"]})

    task_id = _submitted_task(module, client, headers)
    form = _recorded_form(module, task_id)
    form["placement_decision"]["execution_class"]["partition"] = "elsewhere"
    module.task_store.update_task(task_id, input_form=json.dumps(form))

    projected = ar.placement_projection(module.task_store.get_task(task_id))
    assert projected["state"] == ar.PLACEMENT_UNREADABLE
    assert projected["execution_class_id"] is None
    assert projected["error"]

    # A record is evidence about the request, not the request: what is submitted
    # is the frozen snapshot, and a tampered record does not move it.
    dispatched = _run_worker(module, monkeypatch, task_id)
    assert len(dispatched) == 1
    assert dispatched[0].partition == form["resource_policy"]["partition"] == "normal"


def test_a_map_with_no_accelerator_class_refuses_gpu_work_at_submission(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _queued(monkeypatch, module)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    module.app.config["user_db"].update_user(
        module.app.config["user_db"].get_user_by_username("tester")["id"], allow_gpu_use=True
    )
    queued: list[str] = []
    monkeypatch.setattr(
        module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append("dispatched")
    )
    _class_map(module, classes="cpu=normal", globals_={"slurm_allowed_queues": ["normal"]})

    response = _submit(client, headers, task_type="gpu_runner")

    assert response.status_code == 503, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["reason_code"] == ACCELERATOR_UNAVAILABLE
    assert queued == []
    assert module.task_store.list_tasks() == []


def test_a_deployment_declaring_no_map_submits_gpu_work_unchanged(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _queued(monkeypatch, module)
    client = module.app.test_client()
    headers = _test_client_auth(module)
    module.app.config["user_db"].update_user(
        module.app.config["user_db"].get_user_by_username("tester")["id"], allow_gpu_use=True
    )
    _class_map(module, globals_={"slurm_partition": "gpu", "slurm_gres": CPU_GRES, "slurm_allowed_queues": ["gpu"]})

    task_id = _submitted_task(module, client, headers, task_type="gpu_runner")
    form = _recorded_form(module, task_id)

    assert form["resource_policy"]["requires_gpu"] is True
    assert form["resource_policy"]["gres"] == CPU_GRES
    assert form["resource_policy"]["partition"] == "gpu"
    assert form["placement_decision"]["reason_code"] == PLACED_ACCELERATOR_UNTYPED
