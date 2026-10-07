# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic placement resolution: policy matching, precedence, and refusal.

These tests are about the *decision*, so they exercise the resolver directly
against canonical :class:`ResolvedResources` snapshots.  The end-to-end
dispatch path (plan persistence, submission transitions, argv) is covered by
``tests/test_placement_submission.py``; the admin surface by
``tests/server/test_placement_api.py``.
"""

from __future__ import annotations

import pytest
from revocompute.placement_policy import (
    ACCELERATOR_CUDA,
    NO_VALID_PLACEMENT,
    PARTITION_NOT_ALLOWED,
    PLACEMENT_FALLBACK_APPLIED,
    PLACEMENT_RESOLVED_ACCELERATOR,
    PLACEMENT_RESOLVED_CPU,
    PLACEMENT_SCHEDULER_DEFAULT,
    PLACEMENT_UNMANAGED,
    REQUIRED_ACCELERATOR_UNAVAILABLE,
    RESOURCE_OVERRIDE_CONFLICT,
    NoValidPlacement,
    PartitionNotAllowed,
    PlacementClass,
    PlacementError,
    PlacementPlan,
    PlacementPolicy,
    PlacementPolicyInvalid,
    RequiredAcceleratorUnavailable,
    ResourceOverrideConflict,
    WorkloadRequirement,
    build_placement_plan,
    explain_placement,
    memory_to_mb,
    plan_task_stages,
    resolve_placement,
)
from revocompute.resource_policy import ResolvedResources, resolve_resources

QUEUES = ("normal", "gpu", "cpu-dedicated")


def _resolved(**overrides) -> ResolvedResources:
    """A canonical snapshot built through the real resolver, then adjusted.

    Building it through ``resolve_resources`` keeps the fixtures honest about
    field provenance, which is what the precedence model reads.
    """
    requires_gpu = overrides.pop("requires_gpu", False)
    task = overrides.pop("task", None) or {}
    global_values = overrides.pop("global_values", None) or {}
    queues = overrides.pop("allowed_queues", QUEUES)
    resolved = resolve_resources(
        task.get,
        global_values.get,
        requires_gpu=requires_gpu,
        allowed_queues=queues,
        default_timeout_seconds=3600,
    )
    return resolved if not overrides else ResolvedResources(**{**resolved.__dict__, **overrides})


def _policy(classes, queues=QUEUES) -> PlacementPolicy:
    return PlacementPolicy.validate({"classes": list(classes)}, allowed_queues=queues)


CPU_CLASSES = [
    {"name": "cpu", "partition": "cpu-dedicated", "accelerator": "none"},
    {"name": "gpu-standard", "partition": "gpu", "accelerator": "cuda"},
    {"name": "mixed", "partition": "normal", "accelerator": "none"},
]


def _requirement(**overrides) -> WorkloadRequirement:
    payload = {"cpus": 1, "memory_mb": 4096, "max_runtime_seconds": 3600}
    payload.update(overrides)
    return WorkloadRequirement(**payload)


# -- memory normalization ------------------------------------------------------


def test_memory_strings_convert_to_binary_mebibytes():
    assert memory_to_mb("4G") == 4096
    assert memory_to_mb("512M") == 512
    assert memory_to_mb("2T") == 2 * 1024 * 1024
    with pytest.raises(PlacementPolicyInvalid):
        memory_to_mb("plenty")


# -- policy validation ---------------------------------------------------------


def test_policy_rejects_a_class_naming_a_partition_outside_the_allowed_surface():
    with pytest.raises(PartitionNotAllowed) as caught:
        _policy([{"name": "cpu", "partition": "debug", "accelerator": "none"}])
    assert caught.value.reason_code == PARTITION_NOT_ALLOWED


def test_policy_rejects_unknown_classes_fields_and_fallback_cycles():
    with pytest.raises(PlacementPolicyInvalid, match="falls back to undeclared"):
        _policy([{"name": "cpu", "partition": "normal", "fallback_classes": ["ghost"]}])
    with pytest.raises(PlacementPolicyInvalid, match="cycle"):
        _policy(
            [
                {"name": "a", "partition": "normal", "fallback_classes": ["b"]},
                {"name": "b", "partition": "normal", "fallback_classes": ["a"]},
            ]
        )
    with pytest.raises(PlacementPolicyInvalid, match="Unknown placement class fields"):
        _policy([{"name": "cpu", "partition": "normal", "gpu_partition": "gpu"}])
    with pytest.raises(PlacementPolicyInvalid, match="must name a partition"):
        PlacementClass(name="cpu", partition="")


def test_a_cpu_class_cannot_declare_an_accelerator_identity():
    with pytest.raises(PlacementPolicyInvalid, match="cannot name an accelerator class"):
        PlacementClass(name="cpu", partition="normal", accelerator_class="a100")
    with pytest.raises(PlacementPolicyInvalid, match="CPU-only requirement"):
        WorkloadRequirement(accelerator="none", gpu_count=2)
    with pytest.raises(PlacementPolicyInvalid, match="at least one device"):
        WorkloadRequirement(accelerator=ACCELERATOR_CUDA, gpu_count=0)


def test_policy_digest_tracks_content_and_not_revision_or_operator_metadata():
    base = _policy(CPU_CLASSES)
    same = PlacementPolicy(
        revision=99,
        classes=base.classes,
        updated_at=1234.0,
        updated_by_user_id=7,
    )
    changed = _policy([*CPU_CLASSES[:2], {"name": "mixed", "partition": "gpu", "accelerator": "none"}])
    assert same.policy_digest == base.policy_digest
    assert changed.policy_digest != base.policy_digest


# -- CPU vs accelerator routing ------------------------------------------------


def test_cpu_only_stage_resolves_without_any_gpu_request():
    requirement = WorkloadRequirement.from_resolved(_resolved())
    decision = resolve_placement(requirement, _resolved(), _policy(CPU_CLASSES), allowed_queues=QUEUES)
    assert decision.reason_code == PLACEMENT_RESOLVED_CPU
    assert decision.matched_class == "cpu"
    assert decision.resolved.partition == "cpu-dedicated"
    assert decision.resolved.gres is None
    assert decision.resolved.requires_gpu is False


def test_cpu_only_stage_never_inherits_gpu_from_a_global_gres_or_a_gpu_sibling():
    # A global GPU GRES is ignored for a CPU task by the canonical resolver, and
    # the GPU class in the policy must not be reachable either.
    cpu = _resolved(global_values={"slurm_gres": "gpu:a100:1"}, requires_gpu=False)
    assert cpu.gres is None
    requirement = WorkloadRequirement.from_resolved(cpu)
    assert requirement.requires_accelerator is False
    decision = resolve_placement(requirement, cpu, _policy(CPU_CLASSES), allowed_queues=QUEUES)
    assert decision.resolved.gres is None
    assert decision.matched_class == "cpu"


def test_gpu_stage_requests_the_accelerator_class_declared_by_policy():
    # No explicit GRES override, so the requested count and class both come from
    # the policy: the requirement supplies how many devices, the class which one.
    resolved = _resolved(requires_gpu=True)
    requirement = WorkloadRequirement.from_resolved(resolved, min_vram_mb=0)
    requirement = WorkloadRequirement(**{**requirement.to_dict(), "gpu_count": 2})
    assert requirement.accelerator == ACCELERATOR_CUDA
    policy = _policy(
        [
            {"name": "cpu", "partition": "cpu-dedicated", "accelerator": "none"},
            {"name": "gpu-large", "partition": "gpu", "accelerator": "cuda", "accelerator_class": "a100"},
        ]
    )
    decision = resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    assert decision.reason_code == PLACEMENT_RESOLVED_ACCELERATOR
    assert decision.matched_class == "gpu-large"
    assert decision.resolved.gres == "gpu:a100:2"


def test_an_explicit_gres_override_outranks_the_class_accelerator_class():
    # Precedence rule 1: an Admin override wins for the field it names, as long
    # as it does not weaken the requirement.
    resolved = _resolved(requires_gpu=True, task={"slurm_gres": "gpu:a100:2"})
    requirement = WorkloadRequirement.from_resolved(resolved)
    policy = _policy(
        [
            {"name": "cpu", "partition": "cpu-dedicated", "accelerator": "none"},
            {"name": "gpu-large", "partition": "gpu", "accelerator": "cuda", "accelerator_class": "h100"},
        ]
    )
    decision = resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    assert decision.resolved.gres == "gpu:a100:2"
    assert decision.resolved.sources["gres"] == "task:slurm_gres"


def test_an_untyped_gpu_class_asks_for_untyped_gpu_capacity():
    resolved = _resolved(requires_gpu=True)
    requirement = WorkloadRequirement.from_resolved(resolved)
    decision = resolve_placement(
        requirement,
        resolved,
        _policy([{"name": "gpu", "partition": "gpu", "accelerator": "cuda"}]),
        allowed_queues=QUEUES,
    )
    assert decision.resolved.gres == "gpu:1"


def test_capacity_drives_class_selection_rather_than_declaration_order():
    resolved = _resolved(requires_gpu=True)
    requirement = WorkloadRequirement.from_resolved(resolved, min_vram_mb=40_000)
    policy = _policy(
        [
            {"name": "gpu-small", "partition": "normal", "accelerator": "cuda", "vram_mb": 16_000},
            {"name": "gpu-large", "partition": "gpu", "accelerator": "cuda", "vram_mb": 80_000},
        ]
    )
    decision = resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    assert decision.matched_class == "gpu-large"


def test_a_requirement_larger_than_every_class_fails_closed():
    requirement = _requirement(cpus=64)
    resolved = _resolved(task={"cpus": 64})
    policy = _policy([{"name": "cpu", "partition": "normal", "accelerator": "none", "cpus": 8}])
    with pytest.raises(NoValidPlacement) as caught:
        resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    assert caught.value.reason_code == NO_VALID_PLACEMENT


def test_a_gpu_requirement_is_never_met_by_a_cpu_class_even_as_a_fallback():
    resolved = _resolved(requires_gpu=True)
    requirement = WorkloadRequirement.from_resolved(resolved)
    policy = _policy(
        [
            {"name": "gpu", "partition": "gpu", "accelerator": "cuda", "fallback_classes": ["cpu"]},
            {"name": "cpu", "partition": "cpu-dedicated", "accelerator": "none"},
        ]
    )
    decision = resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    assert decision.matched_class == "gpu"
    assert decision.resolved.gres == "gpu:1"


def test_no_accelerator_class_at_all_reports_the_bounded_reason():
    resolved = _resolved(requires_gpu=True)
    requirement = WorkloadRequirement.from_resolved(resolved)
    policy = _policy([{"name": "cpu", "partition": "normal", "accelerator": "none"}])
    with pytest.raises(RequiredAcceleratorUnavailable) as caught:
        resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    assert caught.value.reason_code == REQUIRED_ACCELERATOR_UNAVAILABLE


def test_an_accelerator_requirement_without_a_gpu_snapshot_is_refused():
    resolved = _resolved()
    requirement = _requirement(accelerator=ACCELERATOR_CUDA, gpu_count=1)
    with pytest.raises(RequiredAcceleratorUnavailable):
        resolve_placement(requirement, resolved, _policy(CPU_CLASSES), allowed_queues=QUEUES)


# -- fallback ------------------------------------------------------------------


def test_fallback_is_taken_only_when_policy_declares_it_and_is_recorded():
    resolved = _resolved()
    requirement = WorkloadRequirement.from_resolved(resolved)
    policy = _policy(
        [
            {
                "name": "cpu",
                "partition": "cpu-dedicated",
                "accelerator": "none",
                "fallback_classes": ["mixed"],
            },
            {"name": "mixed", "partition": "normal", "accelerator": "none"},
        ]
    )
    # The primary partition left the allowed surface, so the declared fallback is
    # the only remaining option.
    decision = resolve_placement(requirement, resolved, policy, allowed_queues=("normal", "gpu"))
    assert decision.reason_code == PLACEMENT_FALLBACK_APPLIED
    assert decision.matched_class == "mixed"
    assert decision.resolved.partition == "normal"
    assert any(PLACEMENT_FALLBACK_APPLIED in note for note in decision.notes)


def test_an_undeclared_fallback_is_never_taken():
    resolved = _resolved()
    requirement = WorkloadRequirement.from_resolved(resolved)
    policy = _policy([{"name": "cpu", "partition": "cpu-dedicated", "accelerator": "none"}])
    with pytest.raises(PartitionNotAllowed):
        resolve_placement(requirement, resolved, policy, allowed_queues=("normal", "gpu"))


def test_no_placement_ever_falls_through_to_the_slurm_default_partition():
    # The only declared class cannot be used, and the policy declares no
    # fallback: the request is refused rather than sent to Slurm's default queue.
    resolved = _resolved()
    requirement = WorkloadRequirement.from_resolved(resolved)
    policy = _policy([{"name": "cpu", "partition": "cpu-dedicated", "accelerator": "none"}])
    with pytest.raises(PlacementError) as caught:
        resolve_placement(requirement, resolved, policy, allowed_queues=("normal", "gpu"))
    assert caught.value.reason_code == PARTITION_NOT_ALLOWED


# -- precedence ----------------------------------------------------------------


def test_an_explicit_override_refines_the_matched_class():
    resolved = _resolved(task={"slurm_qos": "priority", "slurm_account": "lab"})
    requirement = WorkloadRequirement.from_resolved(resolved)
    policy = _policy(
        [
            {
                "name": "cpu",
                "partition": "cpu-dedicated",
                "accelerator": "none",
                "qos": "normal",
                "account": "default-project",
                "constraint": "avx512",
            }
        ]
    )
    decision = resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    assert decision.resolved.qos == "priority"
    assert decision.resolved.account == "lab"
    # A field the override did not name still comes from the class.
    assert decision.resolved.constraint == "avx512"
    assert decision.resolved.sources["qos"] == "task:slurm_qos"
    assert decision.resolved.sources["constraint"] == "placement"


def test_an_override_that_weakens_a_gpu_requirement_is_refused():
    resolved = _resolved(requires_gpu=True, task={"slurm_gres": "gpu:1"})
    requirement = _requirement(accelerator=ACCELERATOR_CUDA, gpu_count=4)
    policy = _policy([{"name": "gpu", "partition": "gpu", "accelerator": "cuda"}])
    with pytest.raises(ResourceOverrideConflict) as caught:
        resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    assert caught.value.reason_code == RESOURCE_OVERRIDE_CONFLICT


def test_an_override_that_strengthens_a_gpu_requirement_is_honored():
    resolved = _resolved(requires_gpu=True, task={"slurm_gres": "gpu:a100:4"})
    requirement = _requirement(accelerator=ACCELERATOR_CUDA, gpu_count=2)
    policy = _policy([{"name": "gpu", "partition": "gpu", "accelerator": "cuda"}])
    decision = resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    assert decision.resolved.gres == "gpu:a100:4"


def test_a_cpu_stage_carrying_an_override_gres_is_refused():
    resolved = _resolved()
    requirement = WorkloadRequirement.from_resolved(resolved)
    # A GRES that reached placement on a CPU stage can only have come from a
    # policy or a hand-built snapshot; it must never be carried into the request.
    poisoned = ResolvedResources(**{**resolved.__dict__, "gres": "gpu:1", "sources": {"gres": "global:slurm_gres"}})
    with pytest.raises(ResourceOverrideConflict):
        resolve_placement(requirement, poisoned, _policy(CPU_CLASSES), allowed_queues=QUEUES)


def test_an_override_partition_outside_the_allowed_surface_is_refused():
    resolved = _resolved(task={"slurm_partition": "normal"})
    requirement = WorkloadRequirement.from_resolved(resolved)
    policy = _policy(CPU_CLASSES)
    with pytest.raises(PartitionNotAllowed):
        resolve_placement(requirement, resolved, policy, allowed_queues=("gpu",))


# -- unmanaged deployments -----------------------------------------------------


def test_a_deployment_with_no_classes_records_the_canonical_policy_as_the_placement():
    resolved = _resolved(task={"slurm_partition": "normal", "cpus": 8})
    requirement = WorkloadRequirement.from_resolved(resolved)
    decision = resolve_placement(requirement, resolved, PlacementPolicy(), allowed_queues=QUEUES)
    assert decision.reason_code == PLACEMENT_UNMANAGED
    assert decision.matched_class == ""
    assert decision.resolved.partition == "normal"
    assert PLACEMENT_UNMANAGED in decision.notes


def test_an_unmanaged_deployment_names_the_slurm_default_explicitly():
    # No allowed queue list and no configured partition: nothing has resolved a
    # partition, so the request carries none and Slurm's default applies.  That
    # is recorded, not left indistinguishable from a policy that chose nothing.
    resolved = _resolved(allowed_queues=())
    requirement = WorkloadRequirement.from_resolved(resolved)
    decision = resolve_placement(requirement, resolved, PlacementPolicy())
    assert decision.reason_code == PLACEMENT_UNMANAGED
    assert decision.resolved.partition is None
    assert PLACEMENT_SCHEDULER_DEFAULT in decision.notes


# -- determinism and explanation -----------------------------------------------


def test_resolution_is_deterministic_and_the_digest_is_stable():
    resolved = _resolved(requires_gpu=True)
    requirement = WorkloadRequirement.from_resolved(resolved)
    policy = _policy(CPU_CLASSES)
    first = resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    second = resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    assert first.as_dict() == second.as_dict()
    assert first.plan_digest == second.plan_digest


def test_the_plan_digest_changes_when_the_policy_content_changes():
    resolved = _resolved()
    requirement = WorkloadRequirement.from_resolved(resolved)
    first = resolve_placement(requirement, resolved, _policy(CPU_CLASSES), allowed_queues=QUEUES)
    other = _policy([*CPU_CLASSES[:1], {"name": "gpu-standard", "partition": "gpu", "accelerator": "cuda"},
                     {"name": "mixed", "partition": "gpu", "accelerator": "none"}])
    second = resolve_placement(requirement, resolved, other, allowed_queues=QUEUES)
    assert first.plan_digest != second.plan_digest


def test_dry_run_returns_the_same_decision_dispatch_would_make():
    resolved = _resolved()
    requirement = WorkloadRequirement.from_resolved(resolved)
    policy = _policy(CPU_CLASSES)
    dry = explain_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    real = resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    assert dry["placed"] is True
    assert dry["plan_digest"] == real.plan_digest
    assert dry["resolved"] == real.resolved.public_dict()


def test_dry_run_reports_a_refusal_as_a_reason_code_not_an_exception():
    resolved = _resolved(requires_gpu=True)
    requirement = WorkloadRequirement.from_resolved(resolved)
    outcome = explain_placement(
        requirement,
        resolved,
        _policy([{"name": "cpu", "partition": "normal", "accelerator": "none"}]),
    )
    assert outcome["placed"] is False
    assert outcome["reason_code"] == REQUIRED_ACCELERATOR_UNAVAILABLE
    assert outcome["message"]


# -- plan identity -------------------------------------------------------------


def test_a_plan_records_the_stage_the_decision_and_the_policy_identity():
    resolved = _resolved()
    requirement = WorkloadRequirement.from_resolved(resolved)
    policy = PlacementPolicy(
        revision=4,
        classes=_policy(CPU_CLASSES).classes,
        updated_at=10.0,
        updated_by_user_id=3,
    )
    decision = resolve_placement(requirement, resolved, policy, allowed_queues=QUEUES)
    plan = build_placement_plan(decision, task_id="a" * 32, stage_id="demo", created_at=123.0)
    assert plan.revision == 1
    assert plan.policy_revision == 4
    assert plan.policy_digest == policy.policy_digest
    assert plan.state == "planned"
    assert plan.dispatched is False
    assert plan.submission_unresolved is False
    record = plan.to_record()
    assert record["reason_code"] == PLACEMENT_RESOLVED_CPU
    assert record["matched_class"] == "cpu"


def test_a_plan_round_trips_through_its_stored_columns_without_any_policy():
    resolved = _resolved()
    requirement = WorkloadRequirement.from_resolved(resolved)
    decision = resolve_placement(requirement, resolved, _policy(CPU_CLASSES), allowed_queues=QUEUES)
    plan = build_placement_plan(decision, task_id="a" * 32, stage_id="demo", created_at=123.0)
    restored = PlacementPlan.from_record(plan.to_record())
    assert restored.as_dict() == plan.as_dict()
    # The resolved request is re-readable exactly, provenance included.
    assert restored.resolved == plan.resolved
    assert restored.resolved.sources == plan.resolved.sources


def test_a_plan_carries_the_identity_of_the_resource_contract_it_consumes():
    resolved = _resolved(requires_gpu=True, task={"slurm_gres": "gpu:a100:2"})
    requirement = WorkloadRequirement.from_resolved(resolved)
    decision = resolve_placement(requirement, resolved, _policy(CPU_CLASSES), allowed_queues=QUEUES)
    payload = decision.resolved.public_dict()
    # The resolved request is the canonical accounting resource contract, so the
    # numbers the plan explains are the numbers the ledger will charge.
    assert {"cpus", "memory", "max_runtime_seconds", "requires_gpu", "gres"} <= set(payload)
    assert payload["requires_gpu"] is True


class _Stage:
    def __init__(self, name, requires_gpu, requires_network=False):
        self.name = name
        self.requires_gpu = requires_gpu
        self.requires_network = requires_network


class _TaskType:
    def __init__(self, name, workflow, requires_network=False):
        self.name = name
        self.workflow = tuple(workflow)
        self.requires_network = requires_network


def test_a_composed_workflow_plans_each_stage_independently():
    stages = [
        _Stage("demo.features", False, requires_network=True),
        _Stage("demo.model", True),
        _Stage("demo.analyze", False),
    ]
    task_type = _TaskType("demo", stages)
    resolved_stages = {
        "demo.features": _resolved(task={"cpus": 8}),
        "demo.model": _resolved(requires_gpu=True),
        "demo.analyze": _resolved(task={"cpus": 4}),
    }
    policy = _policy(CPU_CLASSES)
    _, placed, decisions = plan_task_stages(
        task_type, None, resolved_stages, policy, allowed_queues=QUEUES
    )
    assert placed["demo.features"].partition == "cpu-dedicated"
    assert placed["demo.features"].gres is None
    assert placed["demo.model"].partition == "gpu"
    assert placed["demo.model"].gres == "gpu:1"
    # The trailing CPU stage is placed on CPU again: a GPU stage in the middle of
    # the workflow does not drag the last stage onto accelerator resources.
    assert placed["demo.analyze"].partition == "cpu-dedicated"
    assert placed["demo.analyze"].gres is None
    assert decisions["demo.model"].reason_code == PLACEMENT_RESOLVED_ACCELERATOR
    assert decisions["demo.analyze"].reason_code == PLACEMENT_RESOLVED_CPU


def test_a_workflow_stage_without_a_snapshot_fails_closed():
    task_type = _TaskType("demo", [_Stage("demo.model", True)])
    with pytest.raises(PlacementError):
        plan_task_stages(task_type, None, {}, _policy(CPU_CLASSES), allowed_queues=QUEUES)
