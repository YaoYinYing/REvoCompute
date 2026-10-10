# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic stage-level placement, exercised without hardware.

Every case here builds a real :class:`~revocompute.manage_db.ManageDatabase` on a
temporary SQLite file and configures it through the *same* admin entry point
production uses, so the deployment-local names are stored, serialized, read back,
and resolved by real code rather than by a test double whose ``resource_all()``
returns strings no reader would accept.  No GPU, no production Runner image, and
no multi-partition cluster is involved: the accelerator capability is declared as
configuration, which is exactly what it is.

What is proven is the boundary the placement layer owns — REvoCompute decides what
a stage requests and why, before submission, and a requirement it cannot honour
fails closed with a bounded machine-readable reason.  The canonical resolution
itself (``resolve_resources``) is covered by ``tests/test_resource_policy.py``;
these cases cover the decision the placement layer records over it, and the admin
path that configures it.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import _load_pssm_module, _test_client_auth, _upsert_task_for_user
from revocompute.manage_db import ManageDatabase
from revocompute.placement import (
    ACCELERATOR_CLASS_MISMATCH,
    ACCELERATOR_CLASS_UNVERIFIED,
    ACCELERATOR_COUNT_MISMATCH,
    ACCELERATOR_UNAVAILABLE,
    CPU_STAGE_REQUESTS_ACCELERATOR,
    PLACED_ACCELERATOR,
    PLACED_ACCELERATOR_UNTYPED,
    PLACED_CPU,
    QUEUE_UNKNOWN,
    AcceleratorRequirement,
    ExecutionClass,
    PlacementDecision,
    PlacementError,
    explain_placement,
    place_resolved,
    place_stage,
    placement_policy,
    resolve_submission_placement,
)
from revocompute.resource_policy import ResourceValidationError, ResolvedResources, resolve_resources


class _Deployment:
    """A real deployment configuration store, configured as an admin configures it.

    ``ManageDatabase`` is the production configuration owner: its ``resource_set``
    is the same call the admin HTTP path makes, so a value that cannot survive the
    store cannot survive this fixture either.  The only thing this class adds is a
    convenient constructor; it never bypasses the store.
    """

    def __init__(self, tmp_path: Path, *, globals_=None, tasks=None, allowed_queues=(), classes=None):
        self.db = ManageDatabase(str(tmp_path / "manage.sqlite"))
        if allowed_queues:
            self.db.resource_set("slurm_allowed_queues", list(allowed_queues))
        if classes:
            self.db.resource_set("slurm_execution_classes", classes)
        for key, value in (globals_ or {}).items():
            self.db.resource_set(key, value)
        for tool, values in (tasks or {}).items():
            self.db.task_type_upsert(tool, **values)

    def close(self) -> None:
        self.db.close()

    # -- the production resolver interface --------------------------------

    def resolve_task_resources(self, tool, *, requires_gpu, default_timeout_seconds):
        return self.db.resolve_task_resources(
            tool, requires_gpu=requires_gpu, default_timeout_seconds=default_timeout_seconds
        )

    def task_type_get(self, tool):
        return self.db.task_type_get(tool) or {}

    def resource_all(self):
        return self.db.resource_all()

    def slurm_allowed_queues(self):
        return self.db.slurm_allowed_queues()


@pytest.fixture
def deployment(tmp_path):
    created: list[_Deployment] = []

    def _make(**kwargs) -> _Deployment:
        store = _Deployment(tmp_path, **kwargs)
        created.append(store)
        return store

    yield _make
    for store in created:
        store.close()


def _task_type(name="demo", *, gpus=False, workflow=(), requirement=None):
    return SimpleNamespace(
        name=name,
        gpus=gpus,
        accelerator_requirement=requirement,
        workflow=workflow,
    )


def _stage(name, *, requires_gpu, requirement=None):
    return SimpleNamespace(name=name, requires_gpu=requires_gpu, accelerator_requirement=requirement)


def _place(store, task_type, *, requirement=None, requires_accelerator=None):
    requires = task_type.gpus if requires_accelerator is None else requires_accelerator
    resources = store.resolve_task_resources(
        task_type.name, requires_gpu=requires, default_timeout_seconds=3600
    )
    return place_resolved(
        resources,
        stage=None,
        requires_accelerator=requires,
        requirement=requirement,
        policy=placement_policy(store, task_type.name),
    )


def _plan(store, task_type, *, requirement=None, requires_accelerator=None):
    """The same placement, reached through the submission planner."""
    return place_stage(
        store.resolve_task_resources,
        owner=task_type.name,
        stage=None,
        requires_accelerator=task_type.gpus if requires_accelerator is None else requires_accelerator,
        requirement=requirement,
        policy=placement_policy(store, task_type.name),
        default_timeout_seconds=3600,
    )


# --------------------------------------------------------------------------- #
# The class map survives the real configuration store
# --------------------------------------------------------------------------- #


def test_execution_classes_round_trip_through_the_admin_configuration_store(deployment):
    store = deployment(
        globals_={"slurm_partition": "normal"},
        allowed_queues=("normal", "gpu"),
        classes="cpu=normal;a100=gpu",
    )

    # The stored spelling is the one its reader parses, and reading it back yields
    # the same pairs: one spelling, not a writer's and a reader's.
    assert store.db.resource_get("slurm_execution_classes") == "cpu=normal;a100=gpu"
    assert store.db.resource_set("slurm_execution_classes", "cpu=normal;a100=gpu") is None
    assert store.db.resource_get("slurm_execution_classes") == "cpu=normal;a100=gpu"

    cpu = store.resolve_task_resources("demo", requires_gpu=False, default_timeout_seconds=3600)
    accelerator = store.resolve_task_resources("demo", requires_gpu=True, default_timeout_seconds=3600)
    assert cpu.partition == "normal"
    assert cpu.gres is None
    assert accelerator.partition == "gpu"


def test_a_malformed_execution_class_is_refused_by_the_admin_path(deployment):
    store = deployment(allowed_queues=("normal",))

    with pytest.raises(ResourceValidationError, match="cpu=normal"):
        store.db.resource_set("slurm_execution_classes", "cpu normal")


def test_a_cpu_stage_resolves_through_the_cpu_class_not_the_accelerator_class(deployment):
    store = deployment(
        globals_={"slurm_partition": "normal"},
        allowed_queues=("normal", "gpu"),
        classes="cpu=normal;a100=gpu",
    )

    decision = _plan(store, _task_type(gpus=False))

    assert decision.reason_code == PLACED_CPU
    assert decision.resources.partition == "normal"
    assert decision.resources.gres is None
    assert decision.execution_class.identifier == "cpu|normal|none"


def test_a_typed_accelerator_stage_resolves_its_own_class(deployment):
    store = deployment(
        globals_={"slurm_gres": "gpu:a100:1"},
        allowed_queues=("normal", "gpu"),
        classes="cpu=normal;a100=gpu",
    )

    decision = _plan(store, _task_type(gpus=True), requirement=AcceleratorRequirement("a100", 1))

    assert decision.reason_code == PLACED_ACCELERATOR
    assert decision.resources.partition == "gpu"
    assert decision.resources.gres == "gpu:a100:1"
    assert decision.execution_class.identifier == "accelerator|gpu|a100x1"
    assert decision.policy_revision.startswith("sha256:")


def test_an_untyped_accelerator_request_joins_an_accelerator_class_not_the_cpu_class(deployment):
    store = deployment(
        globals_={"slurm_partition": "normal"},
        allowed_queues=("normal", "gpu"),
        classes="cpu=normal;gpu=gpu",
    )

    decision = _plan(store, _task_type(gpus=True))

    assert decision.reason_code == PLACED_ACCELERATOR_UNTYPED
    assert decision.resources.partition == "gpu"
    assert decision.resources.gres == "gpu:1"
    assert decision.execution_class.device_class == ""


def test_a_deployment_declaring_no_classes_resolves_exactly_as_before(deployment):
    """Declaring no classes cannot reconfigure a deployment that never used them."""
    store = deployment(globals_={"slurm_partition": "cpu", "slurm_gres": "gpu:a100:1"})

    decision = _place(store, _task_type(gpus=False))

    assert decision.reason_code == PLACED_CPU
    assert decision.resources.gres is None
    assert decision.resources.partition == "cpu"


# --------------------------------------------------------------------------- #
# Fail closed before submission
# --------------------------------------------------------------------------- #


def test_device_specific_requirement_refuses_an_incompatible_class(deployment):
    store = deployment(
        globals_={"slurm_gres": "gpu:a100:1"},
        allowed_queues=("normal", "gpu"),
        classes="cpu=normal;a100=gpu",
    )

    with pytest.raises(PlacementError) as raised:
        _plan(store, _task_type(gpus=True), requirement=AcceleratorRequirement("h100", 1))

    assert raised.value.reason_code in {ACCELERATOR_CLASS_MISMATCH, QUEUE_UNKNOWN}
    assert "never falls back" in str(raised.value) or "execution class" in str(raised.value)


def test_device_specific_requirement_refuses_an_untyped_deployment_request(deployment):
    store = deployment(globals_={"slurm_partition": "gpu"}, allowed_queues=("gpu",))

    with pytest.raises(PlacementError) as raised:
        _plan(store, _task_type(gpus=True), requirement=AcceleratorRequirement("a100", 1))

    assert raised.value.reason_code == ACCELERATOR_CLASS_UNVERIFIED


def test_device_count_requirement_refuses_a_smaller_allocation(deployment):
    store = deployment(globals_={"slurm_gres": "gpu:a100:1"}, allowed_queues=("gpu",))

    with pytest.raises(PlacementError) as raised:
        _plan(store, _task_type(gpus=True), requirement=AcceleratorRequirement("a100", 2))

    assert raised.value.reason_code == ACCELERATOR_COUNT_MISMATCH


def test_an_accelerator_requirement_on_a_cpu_stage_is_refused(deployment):
    store = deployment(globals_={"slurm_partition": "cpu"}, allowed_queues=("cpu",))

    with pytest.raises(PlacementError) as raised:
        _plan(
            store,
            _task_type(gpus=False),
            requires_accelerator=False,
            requirement=AcceleratorRequirement("a100", 1),
        )

    assert raised.value.reason_code == CPU_STAGE_REQUESTS_ACCELERATOR


def test_an_accelerator_stage_with_no_accelerator_class_available_fails_closed(deployment):
    """A deployment that declares CPU classes and no accelerator class refuses GPU work.

    The declaration is what makes this detectable: the deployment has said which
    local queue each kind of work belongs to, and none of them holds a device, so
    accelerator work has nowhere to go and must be refused rather than sent to the
    partition the deployment happens to name by default.
    """
    store = deployment(
        globals_={"slurm_partition": "normal"},
        allowed_queues=("normal",),
        classes="cpu=normal",
    )

    with pytest.raises(PlacementError) as raised:
        _plan(store, _task_type(gpus=True))

    assert raised.value.reason_code == ACCELERATOR_UNAVAILABLE


def test_an_unknown_queue_fails_closed_rather_than_reaching_the_scheduler(deployment):
    store = deployment(globals_={"slurm_partition": "debug"}, allowed_queues=("cpu", "gpu"))

    with pytest.raises(ResourceValidationError, match="allowed queue"):
        _place(store, _task_type(gpus=False))


def test_a_resolver_refusal_reached_through_the_planner_keeps_a_bounded_code(deployment):
    store = deployment(globals_={"slurm_partition": "debug"}, allowed_queues=("cpu", "gpu"))

    with pytest.raises(PlacementError) as raised:
        _plan(store, _task_type(gpus=False))

    assert raised.value.reason_code == QUEUE_UNKNOWN


def test_an_accelerator_requirement_the_deployment_cannot_honour_is_bounded(deployment):
    store = deployment(
        globals_={"slurm_partition": "normal", "slurm_gres": "gpu:a100:1"},
        allowed_queues=("normal",),
        classes="cpu=normal",
    )

    with pytest.raises(PlacementError) as raised:
        _plan(store, _task_type(gpus=True), requirement=AcceleratorRequirement("a100", 1))

    assert raised.value.reason_code in {ACCELERATOR_CLASS_MISMATCH, ACCELERATOR_UNAVAILABLE}


def test_a_placement_error_is_a_resource_policy_failure_not_a_second_vocabulary():
    # Submission, preflight, and the configuration API already treat a policy
    # rejection as ResourceValidationError; a placement refusal is one of those.
    assert issubclass(PlacementError, ResourceValidationError)


# --------------------------------------------------------------------------- #
# Stage-specific workflow placement
# --------------------------------------------------------------------------- #


def test_each_workflow_stage_is_placed_independently(deployment):
    store = deployment(
        globals_={"slurm_partition": "normal"},
        allowed_queues=("normal", "gpu"),
        classes="cpu=normal;a100=gpu",
        tasks={"demo.model": {"slurm_gres": "gpu:a100:1"}},
    )
    task_type = _task_type(
        "demo",
        gpus=True,
        workflow=(
            _stage("demo.features", requires_gpu=False),
            _stage("demo.model", requires_gpu=True, requirement=AcceleratorRequirement("a100", 1)),
        ),
    )
    placement = resolve_submission_placement(store, task_type, SimpleNamespace(max_runtime_seconds=3600))

    assert placement.primary is None
    assert set(placement.stage_resources) == {"demo.features", "demo.model"}
    assert placement.stage_decisions["demo.features"].reason_code == PLACED_CPU
    assert placement.stage_decisions["demo.features"].execution_class.partition == "normal"
    assert placement.stage_decisions["demo.model"].reason_code == PLACED_ACCELERATOR
    assert placement.stage_decisions["demo.model"].execution_class.partition == "gpu"


def test_one_unplaceable_stage_refuses_the_whole_submission(deployment):
    store = deployment(
        globals_={"slurm_partition": "normal"},
        allowed_queues=("normal", "gpu"),
        classes="cpu=normal;a100=gpu",
        tasks={"demo.model": {"slurm_gres": "gpu:a100:1"}},
    )
    task_type = _task_type(
        "demo",
        gpus=True,
        workflow=(
            _stage("demo.features", requires_gpu=False),
            _stage("demo.model", requires_gpu=True, requirement=AcceleratorRequirement("h100", 1)),
        ),
    )

    with pytest.raises(PlacementError) as raised:
        resolve_submission_placement(store, task_type, SimpleNamespace(max_runtime_seconds=3600))

    assert raised.value.reason_code in {ACCELERATOR_CLASS_MISMATCH, QUEUE_UNKNOWN}


# --------------------------------------------------------------------------- #
# The recorded decision is history, not a recomputation
# --------------------------------------------------------------------------- #


def test_a_recorded_decision_survives_a_policy_edit_unchanged(deployment):
    store = deployment(globals_={"slurm_gres": "gpu:a100:1"}, allowed_queues=("gpu",))
    recorded = _place(store, _task_type(gpus=True), requirement=AcceleratorRequirement("a100", 1))
    record = recorded.record()
    frozen = recorded.resources

    # The deployment is re-pointed at a different accelerator class afterwards.
    store.db.resource_set("slurm_gres", "gpu:h100:1")

    restored = PlacementDecision.from_record(record, ResolvedResources.from_snapshot(frozen.public_dict()))
    assert restored.execution_class.identifier == "accelerator|gpu|a100x1"
    assert restored.resources.partition == "gpu"
    assert restored.policy_revision == recorded.policy_revision
    assert restored.reason_code == PLACED_ACCELERATOR


def test_a_decision_whose_record_disagrees_with_its_snapshot_is_rejected(deployment):
    store = deployment(globals_={"slurm_gres": "gpu:a100:1"}, allowed_queues=("gpu",))
    recorded = _place(store, _task_type(gpus=True), requirement=AcceleratorRequirement("a100", 1))
    record = recorded.record()
    record["execution_class"] = {**record["execution_class"], "partition": "elsewhere"}

    with pytest.raises(ResourceValidationError, match="does not describe its frozen resource snapshot"):
        PlacementDecision.from_record(record, recorded.resources)


def test_the_record_carries_no_second_copy_of_the_resolved_fields(deployment):
    store = deployment(globals_={"slurm_gres": "gpu:a100:1"}, allowed_queues=("gpu",))
    record = _place(store, _task_type(gpus=True)).record()

    assert "resources" not in record and "resource_sources" not in record
    assert set(record) == {
        "stage",
        "requires_accelerator",
        "accelerator_requirement",
        "execution_class",
        "policy_revision",
        "reason_code",
        "reason",
    }


def test_the_policy_revision_changes_with_every_value_that_can_change_a_decision(deployment):
    store = deployment(globals_={"slurm_partition": "normal"}, allowed_queues=("normal",))
    first = placement_policy(store, "demo").revision
    assert placement_policy(store, "demo").revision == first

    for key, value in (
        ("slurm_partition", "fast"),
        ("slurm_allowed_queues", ["normal", "gpu"]),
        ("slurm_execution_classes", "cpu=normal;a100=gpu"),
        ("cpus", 8),
    ):
        store.db.resource_set(key, value)
        assert placement_policy(store, "demo").revision != first, key
        first = placement_policy(store, "demo").revision


def test_the_policy_revision_is_the_same_for_one_policy_spelled_two_ways(deployment, tmp_path):
    """A revision has to describe the policy, not the spelling it was stored with."""
    left = _Deployment(tmp_path / "a")
    right = _Deployment(tmp_path / "b")
    try:
        left.db.resource_set("cpus", 4)
        right.db.resource_set("cpus", "4")
        assert placement_policy(left, "demo").revision == placement_policy(right, "demo").revision
    finally:
        left.close()
        right.close()


# --------------------------------------------------------------------------- #
# Dry-run explainability
# --------------------------------------------------------------------------- #


def test_explain_reports_each_stage_and_its_reason_without_submitting(deployment):
    store = deployment(
        globals_={"slurm_partition": "normal"},
        allowed_queues=("normal", "gpu"),
        classes="cpu=normal;a100=gpu",
        tasks={"demo.model": {"slurm_gres": "gpu:a100:1"}},
    )
    task_type = _task_type(
        "demo",
        gpus=True,
        workflow=(
            _stage("demo.features", requires_gpu=False),
            _stage("demo.model", requires_gpu=True, requirement=AcceleratorRequirement("a100", 1)),
        ),
    )
    report = explain_placement(store, task_type, SimpleNamespace(max_runtime_seconds=3600))

    assert report["placeable"] is True
    assert [decision["stage"] for decision in report["decisions"]] == ["demo.features", "demo.model"]
    assert [decision["reason_code"] for decision in report["decisions"]] == [PLACED_CPU, PLACED_ACCELERATOR]
    assert report["decisions"][1]["execution_class"]["partition"] == "gpu"


def test_explain_reports_an_impossible_placement_as_its_bounded_reason(deployment):
    store = deployment(globals_={"slurm_gres": "gpu:a100:1"}, allowed_queues=("gpu",))
    report = explain_placement(
        store,
        _task_type(gpus=True, requirement=AcceleratorRequirement("h100", 1)),
        SimpleNamespace(max_runtime_seconds=3600),
    )

    assert report["placeable"] is False
    assert report["reason_code"] in {ACCELERATOR_CLASS_MISMATCH, QUEUE_UNKNOWN}
    assert report["decisions"] == []


def test_execution_class_identity_is_stable_and_totally_derived():
    assert ExecutionClass.from_resolved(
        resolve_resources(
            lambda _field: None,
            lambda _field: None,
            requires_gpu=False,
            allowed_queues=(),
            default_timeout_seconds=60,
        )
    ).identifier == "cpu|scheduler-default|none"


# --------------------------------------------------------------------------- #
# The submission path records what it resolved
# --------------------------------------------------------------------------- #


def _submit(client, headers, task_type="cpu_runner"):
    return client.post(
        "/compute/api/post",
        headers=headers,
        data={
            "task_type": task_type,
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )


def _run_queued(monkeypatch, module):
    """Dispatch nothing, but hand the submission a Celery result with an id."""
    monkeypatch.setattr(
        module.run_compute_task,
        "apply_async",
        lambda *args, **kwargs: SimpleNamespace(id="celery-dispatch-id"),
    )


def test_a_submitted_task_records_the_decision_that_placed_it(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    _run_queued(monkeypatch, module)
    client = module.app.test_client()
    headers = _test_client_auth(module)

    response = _submit(client, headers)
    assert response.status_code in {200, 201, 202, 302}, response.get_data(as_text=True)

    task = module.task_store.list_tasks()[0]
    recorded = json.loads(task["input_form"])
    decision = recorded["placement_decision"]
    assert decision["reason_code"] == PLACED_CPU
    assert decision["stage"] is None
    assert decision["execution_class"]["state"] == "cpu"
    assert decision["policy_revision"].startswith("sha256:")

    # The decision describes exactly the frozen snapshot stored beside it.
    assert decision["execution_class"]["partition"] == recorded["resource_policy"]["partition"]
    assert recorded["placement_decisions"] == {}


def test_the_stored_placement_decision_is_readable_by_the_canonical_reader(monkeypatch, tmp_path):
    """A submitted Task's recorded decision is history a later reader can join."""
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    _run_queued(monkeypatch, module)
    client = module.app.test_client()
    assert _submit(client, _test_client_auth(module)).status_code in {200, 201, 202, 302}

    recorded = json.loads(module.task_store.list_tasks()[0]["input_form"])
    decision = PlacementDecision.from_record(
        recorded["placement_decision"], ResolvedResources.from_snapshot(recorded["resource_policy"])
    )

    assert decision.execution_class.identifier.startswith("cpu|")
    assert decision.reason_code == PLACED_CPU


def test_the_task_list_reports_the_recorded_execution_class_not_a_recomputation(monkeypatch, tmp_path):
    """The API reader answers from the Task's own decision, even after a policy edit.

    This is the "why is this Task on that queue?" question an operator actually
    asks, and the answer must be the decision that was made.  The policy is
    re-pointed at a different queue afterwards: a reader that re-resolved would
    report the new one.
    """
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    _run_queued(monkeypatch, module)
    client = module.app.test_client()
    assert _submit(client, _test_client_auth(module)).status_code in {200, 201, 202, 302}

    before = client.get("/compute/api/tasks", headers=_test_client_auth(module)).get_json()["tasks"][0]
    assert before["placement"] is not None
    assert before["placement"]["id"].startswith("cpu|")

    module.app.config["manage_db"].resource_set("slurm_partition", "elsewhere")

    after = client.get("/compute/api/tasks", headers=_test_client_auth(module)).get_json()["tasks"][0]
    assert after["placement"] == before["placement"]


def test_the_task_list_reports_no_class_for_a_task_with_no_recorded_decision(monkeypatch, tmp_path):
    """A Task that predates recorded decisions reports nothing, never a guess."""
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    client = module.app.test_client()
    headers = _test_client_auth(module)
    task_root = tmp_path / "legacy-task"
    task_root.mkdir()
    _upsert_task_for_user(
        module,
        "b" * 32,
        filename="old.fasta",
        file_path=task_root / "old.fasta",
        result_dir=task_root,
        username="tester",
        status="finished",
    )
    module.task_store.update_task("b" * 32, input_form=json.dumps({"entities": []}))
    response = client.get("/compute/api/tasks", headers=headers)
    assert response.status_code == 200, response.get_data(as_text=True)
    tasks = response.get_json()["tasks"]

    assert tasks[0]["placement"] is None


def test_the_task_list_reports_no_class_when_the_record_contradicts_its_snapshot(monkeypatch, tmp_path):
    """An edited record is not evidence, so it reads as absent rather than as truth."""
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    client = module.app.test_client()
    headers = _test_client_auth(module)
    task_root = tmp_path / "edited-task"
    task_root.mkdir()
    _upsert_task_for_user(
        module,
        "c" * 32,
        filename="old.fasta",
        file_path=task_root / "old.fasta",
        result_dir=task_root,
        username="tester",
        status="finished",
    )
    module.task_store.update_task(
        "c" * 32,
        input_form=json.dumps(
            {
                "entities": [],
                "resource_policy": {
                    "cpus": 1, "memory": "4G", "max_runtime_seconds": 60, "nodes": 1, "ntasks": 1,
                    "requires_gpu": False, "partition": "normal", "gres": None, "qos": None,
                    "account": None, "constraint": None, "exclusive": False,
                },
                "placement_decision": {
                    "stage": None,
                    "requires_accelerator": False,
                    "accelerator_requirement": None,
                    # The class names a partition the frozen snapshot does not,
                    # so the two halves of one decision disagree.
                    "execution_class": {
                        "id": "cpu|elsewhere|none", "state": "cpu", "partition": "elsewhere",
                        "device_class": None, "device_count": 0, "qos": None, "constraint": None,
                        "account": None, "exclusive": False,
                    },
                    "policy_revision": "sha256:deadbeef",
                    "reason_code": "placed_cpu",
                    "reason": "Placed in the CPU class.",
                },
            }
        ),
    )
    tasks = client.get("/compute/api/tasks", headers=headers).get_json()["tasks"]

    assert tasks[0]["placement"] is None


def test_an_admin_can_explain_where_a_task_type_would_be_placed(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    from conftest import _admin_client_auth

    client = module.app.test_client()
    anonymous = client.get("/compute/api/auth/admin/placement/explain/cpu_runner")
    assert anonymous.status_code == 401
    user = client.get(
        "/compute/api/auth/admin/placement/explain/cpu_runner", headers=_test_client_auth(module)
    )
    assert user.status_code == 403

    report = client.get(
        "/compute/api/auth/admin/placement/explain/cpu_runner", headers=_admin_client_auth(module)
    )
    assert report.status_code == 200
    payload = report.get_json()
    assert payload["placeable"] is True
    assert payload["decisions"][0]["reason_code"] == PLACED_CPU
    assert payload["decisions"][0]["resources"]["gres"] is None

    missing = client.get(
        "/compute/api/auth/admin/placement/explain/not_a_runner", headers=_admin_client_auth(module)
    )
    assert missing.status_code == 404


def test_the_explain_projection_matches_what_a_submission_records(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    _run_queued(monkeypatch, module)
    from conftest import _admin_client_auth

    client = module.app.test_client()
    assert _submit(client, _test_client_auth(module)).status_code in {200, 201, 202, 302}
    recorded = json.loads(module.task_store.list_tasks()[0]["input_form"])["placement_decision"]

    explained = client.get(
        "/compute/api/auth/admin/placement/explain/cpu_runner", headers=_admin_client_auth(module)
    ).get_json()["decisions"][0]

    # The dry run re-resolves today's policy, so it agrees with the submission
    # whenever the policy has not changed — which is the property an operator
    # reads: "this is where it would go, and why".
    assert explained["execution_class"] == recorded["execution_class"]
    assert explained["reason_code"] == recorded["reason_code"]
    assert explained["policy_revision"] == recorded["policy_revision"]


def test_the_execution_class_map_is_configurable_through_the_admin_http_path(monkeypatch, tmp_path):
    """The acceptance gate: the class map is set through the real admin API.

    A configuration value an operator cannot persist is not a feature, so the
    class map is proven end to end through the route the Admin UI calls: stored,
    read back identically, and changing what a submission resolves to.
    """
    module = _load_pssm_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    from conftest import _admin_client_auth

    client = module.app.test_client()
    admin = _admin_client_auth(module)

    accepted = client.put(
        "/compute/api/auth/admin/config",
        headers=admin,
        json={
            "slurm": {"enabled": True, "allowed_queues": ["normal", "gpu"]},
            "resources": {"slurm_execution_classes": "cpu=normal;gpu=gpu"},
        },
    )
    assert accepted.status_code == 200, accepted.get_data(as_text=True)

    payload = client.get("/compute/api/auth/admin/config", headers=admin).get_json()
    assert payload["resources"]["slurm_execution_classes"] == "cpu=normal;gpu=gpu"

    cpu_runner = next(item for item in payload["task_types"] if item["tool"] == "cpu_runner")
    assert cpu_runner["effective_resources"]["partition"] == "normal"
    assert cpu_runner["effective_resources"]["gres"] is None
    assert cpu_runner["resource_sources"]["partition"] == "execution_class:cpu"

    explained = client.get(
        "/compute/api/auth/admin/placement/explain/cpu_runner", headers=admin
    ).get_json()
    assert explained["placeable"] is True
    assert explained["decisions"][0]["execution_class"]["partition"] == "normal"

    rejected = client.put(
        "/compute/api/auth/admin/config",
        headers=admin,
        json={"resources": {"slurm_execution_classes": "not a class"}},
    )
    assert rejected.status_code == 400
    assert "cpu=normal" in rejected.get_json()["error"]
