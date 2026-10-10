# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic stage-level placement: canonical requirements to local Slurm fields.

The division of responsibility this module implements is deliberately narrow:

* REvoCompute decides **what a stage requests and why** — the resource class it
  asks the scheduler for, the concrete Slurm fields that request resolves to, and
  a bounded reason for the choice.  A stage is placed once, before submission.
* Slurm decides **when and on which eligible node it runs**.  Queue order,
  fair-share, backfill, and node selection are the scheduler's; nothing here
  scores, ages, prioritizes, or simulates any of that.

``ResolvedResources`` (``revocompute.resource_policy``) already *is* the one
resolution of canonical requirements into local scheduler fields, and already
persisted as the immutable submission snapshot.  Placement therefore adds no
second resolver: an **execution class** is a derived identity over the class of
scheduler resources that resolution selected — the partition, the accelerator
class named by the GRES request, and the CPU/accelerator distinction — plus the
canonical accelerator facts a declared requirement can be checked against.
:func:`place_stage` resolves through the existing resolver, derives the class from
its own output, and then verifies that the resolved snapshot actually is a class
the stage's declared requirement permits.  One resolution function, one persisted
snapshot, one decision record.

What the class layer makes checkable:

* a CPU-only stage resolves with no accelerator GRES, from a CPU class;
* an accelerator-required stage resolves from an accelerator class, and a stage
  that names a device class (``gpu:a100-80gb``) never silently falls back to an
  untyped or different class;
* an impossible or unrepresentable requirement fails **before submission** with a
  bounded machine-readable reason rather than reaching the scheduler.

Deployment-local names stay deployment-local.  Partition, QoS, account, and GRES
values come from the existing admin resource policy; a task manifest may only
declare a *semantic* requirement (that this computation needs an accelerator of a
named device class and how many), never this deployment's partition names.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from revocompute import resource_ledger as rloan
from revocompute.resource_policy import (
    CANONICAL_TASK_FIELDS,
    AcceleratorClassUnavailableError,
    ExecutionClassMismatchError,
    QueueResolutionError,
    ResourceValidationError,
    ResolvedResources,
    policy_revision_namespace,
)

#: Device-class vocabulary a manifest may name.  Matches the GRES class token the
#: ledger and the resolver already accept, so one spelling describes one request.
_DEVICE_CLASS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")

#: Bounded placement reason codes.  A refusal is always machine-readable, and the
#: set is closed so a client cannot be handed a reason it does not understand.
PLACED_CPU = "placed_cpu"
PLACED_ACCELERATOR = "placed_accelerator"
PLACED_ACCELERATOR_UNTYPED = "placed_accelerator_untyped"
CPU_STAGE_REQUESTS_ACCELERATOR = "cpu_stage_requests_accelerator"
ACCELERATOR_CLASS_UNVERIFIED = "accelerator_class_unverified"
ACCELERATOR_CLASS_MISMATCH = "accelerator_class_mismatch"
ACCELERATOR_COUNT_MISMATCH = "accelerator_count_mismatch"
ACCELERATOR_UNAVAILABLE = "accelerator_unavailable"
QUEUE_UNKNOWN = "queue_unknown"

_PLACEMENT_CODES = frozenset(
    {
        PLACED_CPU,
        PLACED_ACCELERATOR,
        PLACED_ACCELERATOR_UNTYPED,
        CPU_STAGE_REQUESTS_ACCELERATOR,
        ACCELERATOR_CLASS_UNVERIFIED,
        ACCELERATOR_CLASS_MISMATCH,
        ACCELERATOR_COUNT_MISMATCH,
        ACCELERATOR_UNAVAILABLE,
        QUEUE_UNKNOWN,
    }
)

_ACCELERATOR_STATES = ("cpu", "accelerator")


class PlacementError(ResourceValidationError):
    """A stage's placement cannot be determined safely; the reason is bounded.

    A subclass of :class:`ResourceValidationError` so every existing
    policy-validation caller — submission, preflight, the configuration API, and
    the deployment audit — treats an impossible placement as the policy failure it
    is, without a second error vocabulary.
    """

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        if reason_code not in _PLACEMENT_CODES:
            raise ValueError(f"Unbounded placement reason code: {reason_code!r}")
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class AcceleratorRequirement:
    """What a stage declares it needs from an accelerator, in semantic terms.

    ``device_class`` is a hardware-class vocabulary token (``a100``,
    ``a100-80gb``), never this deployment's partition or host name.  ``None`` for
    the class means "any accelerator class this deployment offers", which is the
    difference between a generic GPU request and a device-specific one.

    ``count`` is ``None`` when the requirement does not constrain how many devices
    the deployment allocates — the honest default, because "this computation needs
    an accelerator" and "this computation needs exactly one" are different claims
    and only the second can be checked against a resolved request.  A defaulted
    ``1`` would be indistinguishable from a declared ``1``, and would report a
    mismatch against a deployment that legitimately resolves two.
    """

    device_class: str | None = None
    count: int | None = None

    def __post_init__(self) -> None:
        if self.device_class is not None and not _DEVICE_CLASS_RE.fullmatch(self.device_class):
            raise ResourceValidationError(
                f"Accelerator requirement class {self.device_class!r} must be a device-class name"
            )
        if self.count is not None and (
            isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1
        ):
            raise ResourceValidationError("Accelerator requirement count must be a positive integer")

    @classmethod
    def parse(cls, raw: Any, *, owner: str) -> AcceleratorRequirement | None:
        """Load a declared requirement, or ``None`` when the manifest declares none."""
        if raw is None:
            return None
        if not isinstance(raw, dict) or set(raw) - {"class", "count"}:
            raise ResourceValidationError(
                f"{owner} accelerator_requirement must declare only 'class' and 'count'"
            )
        device_class = raw.get("class")
        if device_class is not None and not isinstance(device_class, str):
            raise ResourceValidationError(f"{owner} accelerator_requirement class must be a string")
        return cls(device_class=device_class, count=raw.get("count"))

    def to_dict(self) -> dict[str, Any]:
        return {"class": self.device_class, "count": self.count}


@dataclass(frozen=True, slots=True)
class ExecutionClass:
    """The class of scheduler resources a stage was placed into.

    Derived, never configured: ``state`` is the CPU/accelerator distinction,
    ``partition`` is the local queue the request names, and ``device_class`` is the
    accelerator class the GRES request named (empty when the request is untyped).
    ``identifier`` is the stable projection an operator reads and a report links
    to, so two decisions that selected the same class compare equal.
    """

    state: str
    partition: str | None
    device_class: str
    device_count: int
    qos: str | None = None
    constraint: str | None = None
    account: str | None = None
    exclusive: bool = False

    def __post_init__(self) -> None:
        if self.state not in _ACCELERATOR_STATES:
            raise ResourceValidationError(f"Execution class state must be one of {_ACCELERATOR_STATES}")

    @property
    def identifier(self) -> str:
        accelerator = f"{self.device_class or 'untyped'}x{self.device_count}" if self.state == "accelerator" else "none"
        return f"{self.state}|{self.partition or 'scheduler-default'}|{accelerator}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "state": self.state,
            "partition": self.partition,
            "device_class": self.device_class or None,
            "device_count": self.device_count if self.state == "accelerator" else 0,
            "qos": self.qos,
            "constraint": self.constraint,
            "account": self.account,
            "exclusive": self.exclusive,
        }

    @classmethod
    def from_resolved(cls, resources: ResolvedResources) -> ExecutionClass:
        """Derive the class identity from a resolved resource snapshot.

        The derivation is total: every snapshot the resolver can produce names a
        class, so a decision never has to report "unknown class" for a request the
        server itself just built.
        """
        gres = resources.gres
        return cls(
            state="accelerator" if gres else "cpu",
            partition=resources.partition,
            device_class=rloan.resource_class_for_gres(gres),
            device_count=rloan.units_for_gres(gres),
            qos=resources.qos,
            constraint=resources.constraint,
            account=resources.account,
            exclusive=bool(resources.exclusive),
        )


@dataclass(frozen=True, slots=True)
class PlacementPolicy:
    """The deployment-local policy layer a decision is resolved against.

    ``revision`` is a digest of exactly the configuration values resolution reads,
    so a policy edit produces a new revision while an already-submitted Task keeps
    the revision it recorded.  ``allowed_queues`` is the deployment's partition
    vocabulary; the resolution of a partition name against it stays in
    ``resolve_resources``, which owns it.
    """

    allowed_queues: tuple[str, ...] = ()
    revision: str = "sha256:unconfigured"
    namespace: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"revision": self.revision, "allowed_queues": list(self.allowed_queues)}


def deployment_policy_revision(namespace: Mapping[str, Any]) -> str:
    """A stable digest over the policy values that produced a decision."""
    canonical = json.dumps(namespace, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def placement_policy(manage_db: Any, tool: str) -> PlacementPolicy:
    """Read the deployment policy layer for one task or workflow stage.

    The values are the same ones the resolver reads, projected from the same store
    through the same normalizer, so there is no second configuration source and no
    second spelling of a value.  The revision is computed from that projection
    rather than from a separately maintained counter, so a policy edit that could
    change a decision always produces a new revision while an already-submitted
    Task keeps the revision it recorded.
    """
    allowed = tuple(manage_db.slurm_allowed_queues())
    task_values = manage_db.task_type_get(tool) or {}
    namespace = {
        "tool": tool,
        **policy_revision_namespace(task_values.get, manage_db.resource_all().get),
    }
    return PlacementPolicy(allowed_queues=allowed, revision=deployment_policy_revision(namespace), namespace=namespace)


@dataclass(frozen=True, slots=True)
class PlacementDecision:
    """One stage's placement: what was requested, against which policy, and why.

    Every field answers a question an operator asks months later — which
    requirements were declared, which policy revision resolved them, which
    execution class was selected, which concrete scheduler fields were resolved,
    and the bounded reason for the choice.

    The decision deliberately does **not** restate the resolved scheduler fields
    it was derived from: those are the submission's frozen resource snapshot, which
    the worker validates and the live-test identity hashes, and a second copy would
    be a second source of truth for the same request.  :meth:`record` therefore
    persists the decision's own evidence, and :meth:`from_record` joins it back to
    the stored snapshot.  A recorded decision is read verbatim and is never
    recomputed from today's policy.
    """

    stage: str | None
    requires_accelerator: bool
    accelerator_requirement: AcceleratorRequirement | None
    execution_class: ExecutionClass
    resources: ResolvedResources
    policy_revision: str
    reason_code: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """The full projection, including the resolved fields it was derived from."""
        return {
            **self.record(),
            "resources": self.resources.public_dict(),
            "resource_sources": dict(self.resources.sources),
        }

    def record(self) -> dict[str, Any]:
        """The persisted evidence: everything except the frozen resource snapshot."""
        return {
            "stage": self.stage,
            "requires_accelerator": self.requires_accelerator,
            "accelerator_requirement": (
                self.accelerator_requirement.to_dict() if self.accelerator_requirement is not None else None
            ),
            "execution_class": self.execution_class.to_dict(),
            "policy_revision": self.policy_revision,
            "reason_code": self.reason_code,
            "reason": self.reason,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any], resources: ResolvedResources) -> PlacementDecision:
        """Join a recorded decision to the frozen snapshot it resolved.

        The record is presentation evidence, so an unreadable one yields a typed
        rejection the caller can report rather than a partially reconstructed
        decision that reads as authoritative.
        """
        try:
            execution = record["execution_class"]
            requirement = record.get("accelerator_requirement")
            decision = cls(
                stage=record.get("stage"),
                requires_accelerator=bool(record["requires_accelerator"]),
                accelerator_requirement=(
                    AcceleratorRequirement.parse(requirement, owner="Recorded placement")
                    if requirement is not None
                    else None
                ),
                execution_class=ExecutionClass(
                    state=str(execution["state"]),
                    partition=execution.get("partition"),
                    device_class=str(execution.get("device_class") or ""),
                    device_count=int(execution.get("device_count") or 0),
                    qos=execution.get("qos"),
                    constraint=execution.get("constraint"),
                    account=execution.get("account"),
                    exclusive=bool(execution.get("exclusive")),
                ),
                resources=resources,
                policy_revision=str(record["policy_revision"]),
                reason_code=str(record["reason_code"]),
                reason=str(record["reason"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ResourceValidationError(f"Recorded placement decision is unreadable: {exc}") from exc
        if decision.reason_code not in _PLACEMENT_CODES:
            raise ResourceValidationError(f"Recorded placement reason {decision.reason_code!r} is not bounded")
        if ExecutionClass.from_resolved(resources).identifier != decision.execution_class.identifier:
            # The record and the snapshot are two halves of one decision; a
            # disagreement means one of them was edited, and neither is then
            # trustworthy as evidence of what was requested.
            raise ResourceValidationError(
                "Recorded placement decision does not describe its frozen resource snapshot"
            )
        return decision


def _reason_for(class_: ExecutionClass, requirement: AcceleratorRequirement | None) -> tuple[str, str]:
    if class_.state == "cpu":
        return PLACED_CPU, f"Placed in the CPU class on partition {class_.partition or 'the scheduler default'}."
    if requirement is not None and requirement.device_class is not None:
        return (
            PLACED_ACCELERATOR,
            (
                f"Placed in accelerator class {class_.device_class} "
                f"({class_.device_count} device(s)) on partition {class_.partition or 'the scheduler default'}."
            ),
        )
    return (
        PLACED_ACCELERATOR_UNTYPED,
        (
            f"Placed in the deployment's accelerator class on partition "
            f"{class_.partition or 'the scheduler default'}; the request does not name a device class."
        ),
    )


def verify_placement(
    resources: ResolvedResources,
    requirement: AcceleratorRequirement | None,
    *,
    requires_accelerator: bool,
) -> tuple[ExecutionClass, str, str]:
    """Check a resolved snapshot against the stage's declared requirement.

    The check runs *after* resolution because the resolved snapshot is the fact the
    scheduler will receive: verifying the class from it is what makes the invariant
    "a stage cannot silently request a resource outside its declared class" true of
    the request that is actually submitted.

    The partition is deliberately not re-checked: :func:`resolve_resources` owns the
    queue allowlist and the execution-class mapping, so a second check here would be
    a second opinion about the same fact.  Resolution's refusals are mapped to their
    bounded codes by :func:`_reason_code_for_policy_error`.

    A device *count* is checked only for a request that names a device class.  For a
    generic ``gpu:1`` request the count the deployment resolves is neither compared
    against nor derivable from a declaration, and a check that guessed at one would
    report a mismatch against a requirement nobody made.
    """
    class_ = ExecutionClass.from_resolved(resources)
    if not requires_accelerator:
        if class_.state == "accelerator":
            raise PlacementError(
                CPU_STAGE_REQUESTS_ACCELERATOR,
                "A stage that declares no accelerator requirement resolved to an accelerator class",
            )
        return class_, *_reason_for(class_, None)
    if class_.state == "cpu":
        raise PlacementError(
            ACCELERATOR_UNAVAILABLE,
            (
                f"This deployment resolved no accelerator class for a stage that requires device class "
                f"{requirement.device_class!r}"
                if requirement is not None and requirement.device_class is not None
                else "An accelerator-required stage resolved to a CPU class"
            ),
        )
    if requirement is not None and requirement.device_class is not None:
        if not class_.device_class:
            raise PlacementError(
                ACCELERATOR_CLASS_UNVERIFIED,
                (
                    f"The stage requires device class {requirement.device_class!r} but this deployment resolves the "
                    f"request to an untyped accelerator ({resources.gres!r}); configure a typed GRES for that class"
                ),
            )
        if class_.device_class != requirement.device_class:
            raise PlacementError(
                ACCELERATOR_CLASS_MISMATCH,
                (
                    f"The stage requires device class {requirement.device_class!r} but this deployment resolves it to "
                    f"{class_.device_class!r}; a device-specific requirement never falls back to another class"
                ),
            )
        if requirement.count is not None and class_.device_count != requirement.count:
            raise PlacementError(
                ACCELERATOR_COUNT_MISMATCH,
                (
                    f"The stage requires {requirement.count} accelerator device(s) but this deployment resolves "
                    f"{class_.device_count} of {class_.device_class}"
                ),
            )
    return class_, *_reason_for(class_, requirement)


def place_resolved(
    resources: ResolvedResources,
    *,
    stage: str | None,
    requires_accelerator: bool,
    requirement: AcceleratorRequirement | None,
    policy: PlacementPolicy,
) -> PlacementDecision:
    """Record and verify the placement of an already-resolved stage.

    This is the function every submission path uses.  The resources are the frozen
    snapshot the worker will validate, so the decision is derived from the exact
    request that is submitted rather than from a re-resolution that could differ.
    """
    if requirement is not None and not requires_accelerator:
        raise PlacementError(
            CPU_STAGE_REQUESTS_ACCELERATOR,
            "A stage declares an accelerator requirement but requires no accelerator",
        )
    class_, reason_code, reason = verify_placement(
        resources, requirement, requires_accelerator=requires_accelerator
    )
    return PlacementDecision(
        stage=stage,
        requires_accelerator=requires_accelerator,
        accelerator_requirement=requirement,
        execution_class=class_,
        resources=resources,
        policy_revision=policy.revision,
        reason_code=reason_code,
        reason=reason,
    )


def place_stage(
    resolve: Callable[..., ResolvedResources],
    *,
    owner: str,
    stage: str | None,
    requires_accelerator: bool,
    requirement: AcceleratorRequirement | None,
    policy: PlacementPolicy,
    default_timeout_seconds: int | None = None,
) -> PlacementDecision:
    """Resolve one stage through the canonical policy and record its placement.

    ``resolve`` is the deployment's own resolver
    (:meth:`revocompute.manage_db.ManageDatabase.resolve_task_resources`), taken as
    a callable so this module never owns a second resolution path.
    """
    try:
        resources = resolve(
            owner,
            requires_gpu=requires_accelerator,
            default_timeout_seconds=default_timeout_seconds,
        )
    except PlacementError:
        raise
    except ResourceValidationError as exc:
        raise PlacementError(
            _reason_code_for_policy_error(exc, requires_accelerator=requires_accelerator, requirement=requirement),
            str(exc),
        ) from exc
    return place_resolved(
        resources,
        stage=stage,
        requires_accelerator=requires_accelerator,
        requirement=requirement,
        policy=policy,
    )


def _reason_code_for_policy_error(
    error: ResourceValidationError,
    *,
    requires_accelerator: bool,
    requirement: AcceleratorRequirement | None,
) -> str:
    """Classify a resolver rejection into the bounded placement vocabulary.

    A rejection is the resolver refusing to build the request, so the reason names
    what could not be built: the deployment's queue, or the accelerator class the
    stage asked for.  The classification reads the *kind* of refusal — and, where
    the kind is "this request cannot be placed as declared", whether the work needs
    an accelerator — never its wording, so a bounded code cannot change because
    someone edited a sentence.  Nothing here re-checks a request the resolver
    accepted; a resolved snapshot is verified against the requirement by
    :func:`verify_placement`.
    """
    if isinstance(error, QueueResolutionError):
        return QUEUE_UNKNOWN
    if isinstance(error, ExecutionClassMismatchError):
        return ACCELERATOR_CLASS_MISMATCH if requires_accelerator else QUEUE_UNKNOWN
    if isinstance(error, AcceleratorClassUnavailableError):
        if requirement is not None and requirement.device_class is not None:
            return ACCELERATOR_CLASS_MISMATCH
        return ACCELERATOR_UNAVAILABLE
    return ACCELERATOR_UNAVAILABLE if requires_accelerator else QUEUE_UNKNOWN



@dataclass(frozen=True, slots=True)
class SubmissionPlacement:
    """Every stage's placement for one submission, plus its frozen snapshots.

    This is the submission-time planning result: the decisions an operator later
    reads, and the snapshots the worker and the live-test identity consume.  Both
    come from the same resolution, so a decision can never describe a request other
    than the one that was submitted.
    """

    primary: ResolvedResources | None
    stage_resources: dict[str, ResolvedResources]
    primary_decision: PlacementDecision | None
    stage_decisions: dict[str, PlacementDecision]

    @property
    def decisions(self) -> dict[str, PlacementDecision]:
        return dict(self.stage_decisions)

    def public_input_fields(self) -> dict[str, Any]:
        """The immutable snapshot fields written into a Task's ``input_form``."""
        return {
            "resource_policy": self.primary.public_dict() if self.primary is not None else None,
            "resource_policies": {name: policy.public_dict() for name, policy in self.stage_resources.items()},
            "placement_decision": self.primary_decision.record() if self.primary_decision is not None else None,
            "placement_decisions": {
                name: decision.record() for name, decision in self.stage_decisions.items()
            },
        }


def stage_requirements(task_type: Any) -> list[tuple[str, str | None, bool, AcceleratorRequirement | None]]:
    """Every placeable profile of one task, in submission order.

    A workflow's profiles are its stages (a CPU preparation stage never requests an
    accelerator, and a calculation stage may require a device class); a
    single-stage task has one profile, named after the task itself.
    """
    if task_type.workflow:
        return [
            (
                stage.name,
                stage.name,
                bool(stage.requires_gpu),
                getattr(stage, "accelerator_requirement", None),
            )
            for stage in task_type.workflow
        ]
    return [
        (
            task_type.name,
            None,
            bool(task_type.gpus),
            getattr(task_type, "accelerator_requirement", None),
        )
    ]


def resolve_submission_placement(manage_db: Any, task_type: Any, runner: Any) -> SubmissionPlacement:
    """Place every stage of one submission through the canonical resolver.

    The one submission-time planning call: each profile is resolved by the
    deployment's own resolver and immediately recorded, so the decision and the
    frozen snapshot it describes always come from the same resolution.
    """
    if manage_db is None:
        return SubmissionPlacement(primary=None, stage_resources={}, primary_decision=None, stage_decisions={})
    timeout = getattr(runner, "max_runtime_seconds", None)
    decisions: dict[str, PlacementDecision] = {}
    resources: dict[str, ResolvedResources] = {}
    primary_decision: PlacementDecision | None = None
    for owner, stage, requires_accelerator, requirement in stage_requirements(task_type):
        decision = place_stage(
            manage_db.resolve_task_resources,
            owner=owner,
            stage=stage,
            requires_accelerator=requires_accelerator,
            requirement=requirement,
            policy=placement_policy(manage_db, owner),
            default_timeout_seconds=timeout,
        )
        if stage is None:
            primary_decision = decision
        else:
            decisions[stage] = decision
            resources[stage] = decision.resources
    return SubmissionPlacement(
        primary=primary_decision.resources if primary_decision is not None else None,
        stage_resources=resources,
        primary_decision=primary_decision,
        stage_decisions=decisions,
    )


def explain_placement(manage_db: Any, task_type: Any, runner: Any) -> dict[str, Any]:
    """Answer "where would this stage be placed, and why?" without submitting.

    Reuses the canonical planning logic above: the projection is the decision
    record itself, so the dry run and the submission can never disagree, and an
    impossible placement is reported as its bounded reason rather than as an
    exception at the scheduler boundary.
    """
    try:
        placement = resolve_submission_placement(manage_db, task_type, runner)
    except PlacementError as exc:
        return {
            "task_type": task_type.name,
            "placeable": False,
            "reason_code": exc.reason_code,
            "reason": str(exc),
            "decisions": [],
        }
    except ResourceValidationError as exc:
        return {
            "task_type": task_type.name,
            "placeable": False,
            "reason_code": QUEUE_UNKNOWN,
            "reason": str(exc),
            "decisions": [],
        }
    decisions = (
        [placement.primary_decision]
        if placement.primary_decision is not None
        else list(placement.stage_decisions.values())
    )
    return {
        "task_type": task_type.name,
        "placeable": True,
        "reason_code": None,
        "reason": None,
        "decisions": [decision.to_dict() for decision in decisions],
    }


__all__ = [
    "ACCELERATOR_CLASS_MISMATCH",
    "ACCELERATOR_CLASS_UNVERIFIED",
    "ACCELERATOR_COUNT_MISMATCH",
    "ACCELERATOR_UNAVAILABLE",
    "CPU_STAGE_REQUESTS_ACCELERATOR",
    "PLACED_ACCELERATOR",
    "PLACED_ACCELERATOR_UNTYPED",
    "PLACED_CPU",
    "QUEUE_UNKNOWN",
    "AcceleratorRequirement",
    "ExecutionClass",
    "PlacementDecision",
    "PlacementError",
    "PlacementPolicy",
    "SubmissionPlacement",
    "deployment_policy_revision",
    "explain_placement",
    "place_resolved",
    "place_stage",
    "placement_policy",
    "resolve_submission_placement",
    "stage_requirements",
    "verify_placement",
]
