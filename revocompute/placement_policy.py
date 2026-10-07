# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic stage-level placement planning.

REvoCompute decides *what resources a stage should request*; Slurm decides
*when and where an admitted job runs*.  This module owns the first half of that
boundary and nothing else: it turns one stage's normalized workload requirement
into one concrete Slurm resource request, and explains that decision with a
bounded, machine-readable vocabulary.

The separation it enforces is the point.  A Runner or task contract may say
"this stage needs CUDA and this many devices" — facts that travel with the
science.  It may not say "partition=gpu-a100" — a fact that belongs to one
deployment.  Deployment-local naming lives in a typed placement policy made of
*execution classes* (``cpu``, ``gpu-standard``, ``mixed``, ...), which an
operator declares and which this module matches deterministically.

One precedence model, stated once (see :func:`resolve_placement`):

1. an explicit Admin per-task/stage override, for the field it names, which may
   refine or strengthen a placement — never remove a hard requirement;
2. the matched execution class, for every placement field the override left;
3. the requirement's accelerator identity, which decides eligibility and is
   never relaxed by a fallback;
4. bounded execution-only parameters, which never reach a placement field.

The request this produces is a :class:`~revocompute.resource_policy.ResolvedResources`
— the canonical resource contract from the accounting work — so the system has
exactly one resource model.  What this module adds is the *decision record*:
:class:`PlacementPlan`, persisted before dispatch and historical fact once the
scheduler owns the request.

The record is deliberately not named ``ExecutionPlan``: that identifier already
means the container execution contract (image/command/mounts) in
:mod:`revocompute.job`, and one name may not mean two things.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from revocompute.resource_ledger import units_for_gres
from revocompute.resource_policy import ResolvedResources

ACCELERATOR_NONE = "none"
ACCELERATOR_CUDA = "cuda"
ACCELERATORS = (ACCELERATOR_NONE, ACCELERATOR_CUDA)

_MEMORY_MB_RE = re.compile(r"^([1-9][0-9]*)([KMGTP])?$")
#: A Slurm GRES accelerator class name as ``slurm_gres`` normalizes it.
_ACCELERATOR_CLASS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")

# -- bounded reason vocabulary ------------------------------------------------

#: A CPU-only stage resolved against a deployment execution class.
PLACEMENT_RESOLVED_CPU = "placement_resolved_cpu"
#: A stage with an explicit accelerator requirement resolved against one.
PLACEMENT_RESOLVED_ACCELERATOR = "placement_resolved_accelerator"
#: The first eligible class was refused (its partition left the allowed
#: surface) and the policy's next declared fallback was taken.
PLACEMENT_FALLBACK_APPLIED = "placement_fallback_applied"
#: The deployment declares no execution classes, so the canonical per-task
#: resource policy *is* the placement.  Recorded, never inferred silently.
PLACEMENT_UNMANAGED = "placement_unmanaged"
#: No placement rule produced a partition, so Slurm's own default applies.
#: Recorded explicitly rather than left indistinguishable from a choice.
PLACEMENT_SCHEDULER_DEFAULT = "placement_scheduler_default"
#: No declared class can hold this stage.
NO_VALID_PLACEMENT = "no_valid_placement"
#: The stage requires an accelerator and no declared class provides one.
REQUIRED_ACCELERATOR_UNAVAILABLE = "required_accelerator_unavailable"
#: A configured partition is outside the deployment's allowed Slurm surface.
PARTITION_NOT_ALLOWED = "partition_not_allowed"
#: A configured value would remove or weaken a hard stage requirement.
RESOURCE_OVERRIDE_CONFLICT = "resource_override_conflict"
#: The declared policy cannot be used as written.
PLACEMENT_POLICY_INVALID = "placement_policy_invalid"

REASON_CODES = frozenset(
    {
        PLACEMENT_RESOLVED_CPU,
        PLACEMENT_RESOLVED_ACCELERATOR,
        PLACEMENT_FALLBACK_APPLIED,
        PLACEMENT_UNMANAGED,
        PLACEMENT_SCHEDULER_DEFAULT,
        NO_VALID_PLACEMENT,
        REQUIRED_ACCELERATOR_UNAVAILABLE,
        PARTITION_NOT_ALLOWED,
        RESOURCE_OVERRIDE_CONFLICT,
        PLACEMENT_POLICY_INVALID,
    }
)

#: A plan is written ``planned`` before dispatch, becomes ``submitted`` once the
#: scheduler owns the request, and is ``superseded`` only by an explicit
#: deterministic replan of a stage that was never dispatched.
PLAN_STATE_PLANNED = "planned"
PLAN_STATE_SUBMITTED = "submitted"
PLAN_STATE_SUPERSEDED = "superseded"
PLAN_STATES = frozenset({PLAN_STATE_PLANNED, PLAN_STATE_SUBMITTED, PLAN_STATE_SUPERSEDED})


class PlacementError(ValueError):
    """Placement could not be decided; the category is machine-readable."""

    reason_code = PLACEMENT_POLICY_INVALID

    def __init__(self, message: str, *, reason_code: str | None = None):
        super().__init__(message)
        if reason_code is not None:
            if reason_code not in REASON_CODES:
                raise ValueError(f"Unknown placement reason code: {reason_code!r}")
            self.reason_code = reason_code


class PlacementPolicyInvalid(PlacementError):
    """The declared policy cannot be used: unknown class, bad field, cycle."""

    reason_code = PLACEMENT_POLICY_INVALID


class NoValidPlacement(PlacementError):
    """No declared execution class can satisfy this stage."""

    reason_code = NO_VALID_PLACEMENT


class RequiredAcceleratorUnavailable(PlacementError):
    """The stage requires an accelerator and the policy provides none."""

    reason_code = REQUIRED_ACCELERATOR_UNAVAILABLE


class PartitionNotAllowed(PlacementError):
    """A partition is outside the deployment's allowed Slurm surface."""

    reason_code = PARTITION_NOT_ALLOWED


class ResourceOverrideConflict(PlacementError):
    """A configured value contradicts a hard stage requirement."""

    reason_code = RESOURCE_OVERRIDE_CONFLICT


def memory_to_mb(value: str) -> int:
    """Convert a Slurm memory string (``16G``) into whole mebibytes.

    Binary units, matching Slurm's own reading of ``--mem`` suffixes.  ``K`` and
    ``M`` both floor to whole MiB: sub-MiB precision has no meaning for a fit
    check.
    """
    match = _MEMORY_MB_RE.fullmatch(str(value).strip().upper())
    if match is None:
        raise PlacementPolicyInvalid(f"Unsupported memory value: {value!r}")
    amount = int(match.group(1))
    suffix = match.group(2)
    factors = {"": 0, "K": 0, "M": 0, "G": 10, "T": 20, "P": 30}
    return amount * (1 << factors[suffix])


@dataclass(frozen=True, slots=True)
class WorkloadRequirement:
    """What a stage needs, independent of any deployment's naming.

    Every field is a fact about the work (or about the Runner contract that
    describes it), never about the site that will run it.
    """

    cpus: int = 1
    memory_mb: int = 4096
    max_runtime_seconds: int = 86400
    accelerator: str = ACCELERATOR_NONE
    gpu_count: int = 0
    min_vram_mb: int = 0
    exclusive: bool = False
    requires_network: bool = False

    def __post_init__(self) -> None:
        if self.accelerator not in ACCELERATORS:
            raise PlacementPolicyInvalid(f"Unknown accelerator kind: {self.accelerator!r}")
        if self.accelerator == ACCELERATOR_NONE and self.gpu_count:
            raise PlacementPolicyInvalid("A CPU-only requirement cannot request accelerators")
        if self.accelerator == ACCELERATOR_CUDA and self.gpu_count < 1:
            raise PlacementPolicyInvalid("An accelerator requirement must request at least one device")
        if self.cpus < 1 or self.memory_mb < 1 or self.max_runtime_seconds < 1:
            raise PlacementPolicyInvalid("A workload requirement must be positive")

    @property
    def requires_accelerator(self) -> bool:
        return self.accelerator != ACCELERATOR_NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpus": self.cpus,
            "memory_mb": self.memory_mb,
            "max_runtime_seconds": self.max_runtime_seconds,
            "accelerator": self.accelerator,
            "gpu_count": self.gpu_count,
            "min_vram_mb": self.min_vram_mb,
            "exclusive": self.exclusive,
            "requires_network": self.requires_network,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkloadRequirement:
        unknown = set(payload) - set(cls.__dataclass_fields__)
        if unknown:
            raise PlacementPolicyInvalid(f"Unknown workload requirement fields: {sorted(unknown)}")
        try:
            return cls(**dict(payload))
        except TypeError as exc:
            raise PlacementPolicyInvalid(f"Invalid workload requirement: {exc}") from exc

    @classmethod
    def from_resolved(
        cls,
        resolved: ResolvedResources,
        *,
        requires_network: bool = False,
        min_vram_mb: int = 0,
    ) -> WorkloadRequirement:
        """Normalize the canonical resource snapshot into a workload requirement.

        The accelerator question is answered by the task/stage contract
        (``requires_gpu``), the only authority for it — never by a partition
        name, a Runner family name, or a leftover override.
        """
        gpu_count = units_for_gres(resolved.gres) if resolved.requires_gpu else 0
        return cls(
            cpus=int(resolved.cpus),
            memory_mb=memory_to_mb(resolved.memory),
            max_runtime_seconds=int(resolved.max_runtime_seconds),
            accelerator=ACCELERATOR_CUDA if resolved.requires_gpu else ACCELERATOR_NONE,
            gpu_count=gpu_count,
            min_vram_mb=int(min_vram_mb),
            exclusive=bool(resolved.exclusive),
            requires_network=bool(requires_network),
        )


@dataclass(frozen=True, slots=True)
class PlacementClass:
    """One deployment-local execution class.

    ``cpus`` / ``memory_mb`` / ``vram_mb`` are the capacity this class
    guarantees, so a larger requirement skips it and lands on a class declared
    for it.  ``accelerator_class`` is the deployment's own Slurm GRES class name
    (``a100``); empty means the scheduler's untyped ``gpu``, which is the honest
    request when nothing genuinely requires a model.
    """

    name: str
    partition: str
    accelerator: str = ACCELERATOR_NONE
    accelerator_class: str = ""
    qos: str | None = None
    account: str | None = None
    constraint: str | None = None
    exclusive: bool = False
    cpus: int | None = None
    memory_mb: int | None = None
    vram_mb: int | None = None
    fallback_classes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.name, "placement class name")
        if self.accelerator not in ACCELERATORS:
            raise PlacementPolicyInvalid(f"Placement class {self.name!r} has an unknown accelerator")
        if not self.partition:
            raise PlacementPolicyInvalid(
                f"Placement class {self.name!r} must name a partition; placement is never left to Slurm's default"
            )
        _identifier(self.partition, f"placement class {self.name!r} partition")
        if self.accelerator == ACCELERATOR_NONE and self.accelerator_class:
            raise PlacementPolicyInvalid(f"CPU placement class {self.name!r} cannot name an accelerator class")
        if self.accelerator_class and not _ACCELERATOR_CLASS_RE.fullmatch(self.accelerator_class):
            raise PlacementPolicyInvalid(f"Placement class {self.name!r} has an invalid accelerator class name")
        for value, label in ((self.cpus, "cpus"), (self.memory_mb, "memory_mb"), (self.vram_mb, "vram_mb")):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise PlacementPolicyInvalid(f"Placement class {self.name!r} {label} must be a positive integer")
        if self.accelerator == ACCELERATOR_NONE and self.vram_mb is not None:
            raise PlacementPolicyInvalid(f"CPU placement class {self.name!r} cannot declare VRAM capacity")

    def eligible_for(self, requirement: WorkloadRequirement) -> bool:
        """Whether this class is the right kind of resource and large enough."""
        if self.accelerator != requirement.accelerator:
            return False
        if self.cpus is not None and requirement.cpus > self.cpus:
            return False
        if self.memory_mb is not None and requirement.memory_mb > self.memory_mb:
            return False
        if self.vram_mb is not None and requirement.min_vram_mb > self.vram_mb:
            return False
        return True

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "accelerator": self.accelerator,
            "partition": self.partition,
            "accelerator_class": self.accelerator_class,
            "qos": self.qos,
            "account": self.account,
            "constraint": self.constraint,
            "exclusive": self.exclusive,
            "cpus": self.cpus,
            "memory_mb": self.memory_mb,
            "vram_mb": self.vram_mb,
            "fallback_classes": list(self.fallback_classes),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PlacementClass:
        unknown = set(payload) - set(cls.__dataclass_fields__)
        if unknown:
            raise PlacementPolicyInvalid(f"Unknown placement class fields: {sorted(unknown)}")
        data = dict(payload)
        raw_fallbacks = data.get("fallback_classes", ())
        if isinstance(raw_fallbacks, (str, bytes)) or not isinstance(raw_fallbacks, Sequence):
            raise PlacementPolicyInvalid(f"Placement class {data.get('name')!r} fallback_classes must be a list")
        data["fallback_classes"] = tuple(
            _identifier(item, "fallback class name") for item in raw_fallbacks
        )
        for field_name in ("qos", "account", "constraint"):
            if field_name in data and data[field_name] is not None and str(data[field_name]).strip() == "":
                data[field_name] = None
        if "name" in data:
            data["name"] = _identifier(data["name"], "placement class name")
        if "partition" in data:
            data["partition"] = _identifier(data["partition"], f"placement class {data.get('name')!r} partition")
        try:
            return cls(**data)
        except TypeError as exc:
            raise PlacementPolicyInvalid(f"Invalid placement class: {exc}") from exc


@dataclass(frozen=True, slots=True)
class PlacementPolicy:
    """The deployment's declared mapping from requirements to local resources.

    ``revision`` orders policy changes and ``policy_digest`` identifies content,
    so a persisted plan is readable against the exact policy that produced it.
    """

    revision: int = 0
    classes: tuple[PlacementClass, ...] = ()
    updated_at: float = 0.0
    updated_by_user_id: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise PlacementPolicyInvalid("Placement policy revision must be a non-negative integer")
        names = [cls_.name for cls_ in self.classes]
        if len(names) != len(set(names)):
            duplicate = sorted({name for name in names if names.count(name) > 1})
            raise PlacementPolicyInvalid(f"Duplicate placement class name(s): {', '.join(duplicate)}")
        known = set(names)
        for cls_ in self.classes:
            for fallback in cls_.fallback_classes:
                if fallback not in known:
                    raise PlacementPolicyInvalid(
                        f"Placement class {cls_.name!r} falls back to undeclared class {fallback!r}"
                    )
                if fallback == cls_.name:
                    raise PlacementPolicyInvalid(f"Placement class {cls_.name!r} cannot fall back to itself")
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        """Refuse a fallback cycle: an unbounded ordered walk is not a policy."""
        graph = {cls_.name: cls_.fallback_classes for cls_ in self.classes}
        state: dict[str, int] = {}

        def visit(name: str) -> None:
            if state.get(name) == 1:
                raise PlacementPolicyInvalid(f"Placement fallback cycle through class {name!r}")
            if state.get(name) == 2:
                return
            state[name] = 1
            for neighbour in graph.get(name, ()):
                visit(neighbour)
            state[name] = 2

        for name in graph:
            visit(name)

    @property
    def declared(self) -> bool:
        return bool(self.classes)

    @property
    def policy_digest(self) -> str:
        """Content identity, independent of revision and operator metadata."""
        from revocompute.serialization import canonical_digest

        return canonical_digest({"classes": [cls_.public_dict() for cls_ in self.classes]})

    def class_named(self, name: str) -> PlacementClass:
        for cls_ in self.classes:
            if cls_.name == name:
                return cls_
        raise PlacementPolicyInvalid(f"Unknown placement class: {name!r}")

    def candidates_for(self, requirement: WorkloadRequirement) -> tuple[PlacementClass, ...]:
        """The ordered classes to consider for one requirement.

        The first eligible class in declared order is the primary choice; the
        fallbacks it declares follow, breadth-first and in order.  Every
        candidate must also be eligible, which is what makes "fall back to the
        mixed partition" unable to become "fall back to CPU because the GPU
        queue was busy" — an accelerator requirement is never met by a CPU
        class, whatever an operator declared.
        """
        primary = next((cls_ for cls_ in self.classes if cls_.eligible_for(requirement)), None)
        if primary is None:
            return ()
        ordered: list[PlacementClass] = [primary]
        seen = {primary.name}
        pending = list(primary.fallback_classes)
        while pending:
            name = pending.pop(0)
            if name in seen:
                continue
            seen.add(name)
            candidate = self.class_named(name)
            if not candidate.eligible_for(requirement):
                continue
            ordered.append(candidate)
            pending.extend(candidate.fallback_classes)
        return tuple(ordered)

    def public_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "policy_digest": self.policy_digest,
            "updated_at": self.updated_at,
            "updated_by_user_id": self.updated_by_user_id,
            "declared": self.declared,
            "classes": [cls_.public_dict() for cls_ in self.classes],
        }

    @classmethod
    def validate(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        allowed_queues: Sequence[str] = (),
        revision: int = 0,
        updated_at: float = 0.0,
        updated_by_user_id: int | None = None,
    ) -> PlacementPolicy:
        """Validate a proposed policy document against the deployment's surface.

        Fails closed: a class naming a partition outside ``allowed_queues`` is
        refused here rather than at dispatch, so a typo can never silently
        become a job waiting in a queue nobody reads.
        """
        if raw is None:
            return cls(revision=revision, updated_at=updated_at, updated_by_user_id=updated_by_user_id)
        if not isinstance(raw, Mapping) or set(raw) - {"classes"}:
            raise PlacementPolicyInvalid("A placement policy contains only a classes list")
        raw_classes = raw.get("classes", [])
        if isinstance(raw_classes, (str, bytes)) or not isinstance(raw_classes, Sequence):
            raise PlacementPolicyInvalid("Placement policy classes must be a list")
        policy = cls(
            revision=revision,
            classes=tuple(PlacementClass.from_dict(item) for item in raw_classes),
            updated_at=updated_at,
            updated_by_user_id=updated_by_user_id,
        )
        allowed = tuple(allowed_queues or ())
        if allowed:
            for cls_ in policy.classes:
                if cls_.partition not in allowed:
                    raise PartitionNotAllowed(
                        f"Placement class {cls_.name!r} names partition {cls_.partition!r}, "
                        "which is not in the deployment's allowed queue list"
                    )
        return policy


def _identifier(value: Any, field: str) -> str:
    """Normalize one deployment-local identifier, rejecting anything unsafe."""
    from revocompute.resource_policy import ResourceValidationError, _name

    try:
        return _name(value, field)
    except ResourceValidationError as exc:
        raise PlacementPolicyInvalid(str(exc)) from exc


def _from_override(resolved: ResolvedResources, field_name: str) -> bool:
    """Whether a resolved field came from an explicit per-task or global value.

    ``resource_policy.resolve_resources`` already labels every field's origin,
    so placement asks the canonical resolver instead of re-reading the admin
    configuration into a second, potentially disagreeing answer.
    """
    source = str(resolved.sources.get(field_name, "default"))
    return source.startswith(("task:", "global:"))


def _class_gres(requirement: WorkloadRequirement, cls_: PlacementClass) -> str:
    """The GRES one class requests for an accelerator requirement."""
    suffix = f":{cls_.accelerator_class}" if cls_.accelerator_class else ""
    return f"gpu{suffix}:{requirement.gpu_count}"


def _apply_class(
    requirement: WorkloadRequirement,
    resolved: ResolvedResources,
    cls_: PlacementClass,
    *,
    allowed_queues: Sequence[str],
) -> ResolvedResources:
    """Fold one execution class into the canonical snapshot.

    Only fields an Admin did not name are supplied by the class, which is the
    precedence model stated once: an override refines, the class fills, and the
    requirement decides eligibility.  A value that would contradict a hard
    requirement raises rather than returning a weakened request.
    """
    qualified = frozenset(allowed_queues or ()) or None
    partition = resolved.partition if _from_override(resolved, "partition") else cls_.partition
    if partition is None:
        partition = cls_.partition
    if qualified is not None and partition not in qualified:
        raise PartitionNotAllowed(f"Partition {partition!r} is not in the deployment's allowed queue list")

    override_gres = _from_override(resolved, "gres")
    if requirement.requires_accelerator:
        if override_gres:
            declared = units_for_gres(resolved.gres)
            if declared < requirement.gpu_count:
                raise ResourceOverrideConflict(
                    f"The configured GRES {resolved.gres!r} requests {declared} device(s) but the stage "
                    f"requires {requirement.gpu_count}"
                )
            gres = resolved.gres
        else:
            gres = _class_gres(requirement, cls_)
    else:
        if resolved.gres:
            # A CPU-only stage never carries accelerator GRES.  The canonical
            # resolver refuses a per-task GRES here too; this catches a request
            # that reached placement already formed.
            raise ResourceOverrideConflict("A CPU-only stage cannot carry accelerator GRES")
        gres = None

    sources = dict(resolved.sources)
    sources["partition"] = sources.get("partition", "default") if _from_override(resolved, "partition") else (
        f"placement:{cls_.name}"
    )
    sources["gres"] = (
        sources.get("gres", "default")
        if override_gres
        else (f"placement:{cls_.name}" if requirement.requires_accelerator else "not-required")
    )
    for field_name, class_value in (
        ("qos", cls_.qos),
        ("account", cls_.account),
        ("constraint", cls_.constraint),
    ):
        sources[field_name] = sources.get(field_name, "default") if _from_override(resolved, field_name) else (
            "placement" if class_value is not None else "not-required"
        )
    sources["exclusive"] = sources.get("exclusive", "default") if _from_override(resolved, "exclusive") else (
        "placement" if cls_.exclusive else "not-required"
    )

    return replace(
        resolved,
        partition=partition,
        gres=gres,
        qos=resolved.qos if _from_override(resolved, "qos") else cls_.qos,
        account=resolved.account if _from_override(resolved, "account") else cls_.account,
        constraint=resolved.constraint if _from_override(resolved, "constraint") else cls_.constraint,
        exclusive=resolved.exclusive if _from_override(resolved, "exclusive") else cls_.exclusive,
        sources=sources,
    )


@dataclass(frozen=True, slots=True)
class PlacementDecision:
    """The resolved placement of one stage, with its explanation.

    Identity-free: it says what was decided for a requirement, not which stage
    it was decided for.  :class:`PlacementPlan` binds it to a stage.
    """

    requirement: WorkloadRequirement
    resolved: ResolvedResources
    matched_class: str
    reason_code: str
    notes: tuple[str, ...]
    policy_revision: int
    policy_digest: str

    def __post_init__(self) -> None:
        if self.reason_code not in REASON_CODES:
            raise PlacementPolicyInvalid(f"Unknown placement reason code: {self.reason_code!r}")

    @property
    def plan_digest(self) -> str:
        """Content identity of the decision, independent of when it was made."""
        from revocompute.serialization import canonical_digest

        return canonical_digest(
            {
                "requirement": self.requirement.to_dict(),
                "resolved": self.resolved.public_dict(),
                "matched_class": self.matched_class,
                "reason_code": self.reason_code,
                "policy_revision": self.policy_revision,
                "policy_digest": self.policy_digest,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement.to_dict(),
            "resolved": self.resolved.public_dict(),
            "resolved_sources": dict(self.resolved.sources),
            "matched_class": self.matched_class,
            "reason_code": self.reason_code,
            "notes": list(self.notes),
            "policy_revision": self.policy_revision,
            "policy_digest": self.policy_digest,
            "plan_digest": self.plan_digest,
        }


def _unmanaged_decision(
    requirement: WorkloadRequirement,
    resolved: ResolvedResources,
    policy: PlacementPolicy,
) -> PlacementDecision:
    """Placement for a deployment that declares no execution classes.

    The canonical per-task resource policy is then the placement: it already
    carries cpus/memory/time and whichever SLURM fields an operator configured,
    and it is what every deployment used before classes existed.  This outcome
    is recorded, never inferred — the reason code says the deployment declares
    no class, and Slurm's implicit default is named explicitly when nothing
    resolved a partition, so "no rule was applied" cannot be mistaken for a
    decision.
    """
    notes = [PLACEMENT_UNMANAGED]
    if resolved.partition is None:
        notes.append(PLACEMENT_SCHEDULER_DEFAULT)
    return PlacementDecision(
        requirement=requirement,
        resolved=resolved,
        matched_class="",
        reason_code=PLACEMENT_UNMANAGED,
        notes=tuple(notes),
        policy_revision=policy.revision,
        policy_digest=policy.policy_digest,
    )


def resolve_placement(
    requirement: WorkloadRequirement,
    resolved: ResolvedResources,
    policy: PlacementPolicy | None,
    *,
    allowed_queues: Sequence[str] = (),
) -> PlacementDecision:
    """Resolve one stage's workload requirement into a concrete Slurm request.

    Deterministic by construction: the same requirement, canonical snapshot,
    policy content, and allowed surface always produce the same decision and the
    same ``plan_digest``.  Where no class can be used the function fails closed
    with a bounded reason code rather than falling back to a partition Slurm
    happens to have.
    """
    if requirement.requires_accelerator and not resolved.requires_gpu:
        raise RequiredAcceleratorUnavailable(
            "A stage with an accelerator requirement has no resolved GPU resource snapshot"
        )
    policy = policy or PlacementPolicy()
    if not policy.declared:
        return _unmanaged_decision(requirement, resolved, policy)

    candidates = policy.candidates_for(requirement)
    if not candidates:
        if requirement.requires_accelerator:
            raise RequiredAcceleratorUnavailable(
                f"No declared execution class provides {requirement.accelerator} capacity for this "
                f"stage's {requirement.gpu_count} device(s)"
            )
        raise NoValidPlacement("No declared execution class can hold this stage's CPU and memory requirement")

    refused: list[str] = []
    for index, cls_ in enumerate(candidates):
        try:
            placed = _apply_class(requirement, resolved, cls_, allowed_queues=allowed_queues)
        except PartitionNotAllowed as exc:
            # A partition that left the allowed surface is exactly the stale
            # target the declared fallback chain exists for: recorded, and the
            # next declared candidate is tried.
            refused.append(f"{cls_.name}: {exc}")
            continue
        notes: list[str] = list(refused)
        if index:
            reason = PLACEMENT_FALLBACK_APPLIED
            notes.insert(0, f"{PLACEMENT_FALLBACK_APPLIED}: {candidates[0].name} -> {cls_.name}")
        elif requirement.requires_accelerator:
            reason = PLACEMENT_RESOLVED_ACCELERATOR
        else:
            reason = PLACEMENT_RESOLVED_CPU
        return PlacementDecision(
            requirement=requirement,
            resolved=placed,
            matched_class=cls_.name,
            reason_code=reason,
            notes=tuple(notes),
            policy_revision=policy.revision,
            policy_digest=policy.policy_digest,
        )
    detail = "; ".join(refused) if refused else "no eligible class"
    if refused and len(refused) == len(candidates):
        # Every candidate was refused for the same reason — its partition left
        # the allowed surface — so the precise code is reported rather than a
        # generic one.  The detail stays in the message so the operator sees
        # which class named which partition.
        raise PartitionNotAllowed(f"No declared execution class can place this stage ({detail})")
    raise NoValidPlacement(f"No declared execution class can place this stage ({detail})")


def explain_placement(
    requirement: WorkloadRequirement,
    resolved: ResolvedResources,
    policy: PlacementPolicy | None,
    *,
    allowed_queues: Sequence[str] = (),
) -> dict[str, Any]:
    """Resolve a requirement against policy without dispatching anything.

    A dry run returns the same decision real dispatch would consume for the same
    immutable inputs and policy revision.  A refusal returns its bounded reason
    code rather than raising, because an operator asking "why not" needs an
    answer, not a stack trace.
    """
    policy_revision = policy.revision if policy else 0
    policy_digest = policy.policy_digest if policy else ""
    try:
        decision = resolve_placement(requirement, resolved, policy, allowed_queues=allowed_queues)
    except PlacementError as exc:
        return {
            "placed": False,
            "reason_code": exc.reason_code,
            "message": str(exc),
            "policy_revision": policy_revision,
            "policy_digest": policy_digest,
            **decision_payload(None, requirement=requirement),
        }
    return {
        "placed": True,
        "reason_code": decision.reason_code,
        "message": "",
        **decision_payload(decision, requirement=requirement),
    }


def decision_payload(
    decision: PlacementDecision | None, *, requirement: WorkloadRequirement
) -> dict[str, Any]:
    """The shared projection both dry-run outcomes carry."""
    payload: dict[str, Any] = {"requirement": requirement.to_dict()}
    if decision is None:
        return payload
    payload.update(
        {
            "policy_revision": decision.policy_revision,
            "policy_digest": decision.policy_digest,
            "plan_digest": decision.plan_digest,
            "matched_class": decision.matched_class,
            "notes": list(decision.notes),
            "resolved": decision.resolved.public_dict(),
            "resolved_sources": dict(decision.resolved.sources),
        }
    )
    return payload


@dataclass(frozen=True, slots=True)
class PlacementPlan:
    """The immutable, explainable record of one stage's placement decision.

    Written before dispatch, and historical fact afterwards: a policy change
    affects future planning, never a job the scheduler already owns.  It carries
    enough to answer, without re-deriving anything, what the stage required,
    which rule matched, which local request was resolved, why, and which policy
    revision produced it.
    """

    task_id: str
    stage_id: str
    revision: int
    decision: PlacementDecision
    created_at: float
    state: str = PLAN_STATE_PLANNED
    #: When this worker began asking the scheduler for this plan's request.
    #: Separate from ``state`` on purpose: a plan with this set and no
    #: ``submitted_at`` is an unresolved submission, which is what a retry must
    #: surface rather than resolve by asking the scheduler again.
    submission_started_at: float | None = None
    submitted_at: float | None = None
    slurm_job_id: str | None = None

    def __post_init__(self) -> None:
        if self.state not in PLAN_STATES:
            raise PlacementPolicyInvalid(f"Unknown placement plan state: {self.state!r}")
        if not self.task_id or not self.stage_id:
            raise PlacementPolicyInvalid("A placement plan names both a task and a stage")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise PlacementPolicyInvalid("A placement plan revision starts at 1")

    @property
    def plan_digest(self) -> str:
        return self.decision.plan_digest

    @property
    def resolved(self) -> ResolvedResources:
        return self.decision.resolved

    @property
    def reason_code(self) -> str:
        return self.decision.reason_code

    @property
    def matched_class(self) -> str:
        return self.decision.matched_class

    @property
    def policy_revision(self) -> int:
        return self.decision.policy_revision

    @property
    def policy_digest(self) -> str:
        return self.decision.policy_digest

    @property
    def dispatched(self) -> bool:
        return self.state != PLAN_STATE_PLANNED

    @property
    def submission_unresolved(self) -> bool:
        """Whether a submission was attempted and its outcome was never recorded.

        This is the deliberately ambiguous window — ``srun`` was launched and
        this worker died before the scheduler's answer was persisted.  A
        negative answer here means "dispatchable, or genuinely resolved", and it
        is what makes a retry stop instead of launching a second request.
        """
        return self.submission_started_at is not None and self.submitted_at is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "stage_id": self.stage_id,
            "revision": self.revision,
            "state": self.state,
            "plan_digest": self.plan_digest,
            "created_at": self.created_at,
            "submission_started_at": self.submission_started_at,
            "submitted_at": self.submitted_at,
            "slurm_job_id": self.slurm_job_id,
            "submission_unresolved": self.submission_unresolved,
            **self.decision.as_dict(),
        }

    def to_record(self) -> dict[str, Any]:
        """The exact column payload persisted for this plan."""
        return {
            "task_id": self.task_id,
            "stage_id": self.stage_id,
            "revision": self.revision,
            "state": self.state,
            "plan_digest": self.plan_digest,
            "policy_revision": self.policy_revision,
            "policy_digest": self.policy_digest,
            "requirement_json": _dump(self.decision.requirement.to_dict()),
            "resolved_json": _dump(resolved_payload(self.decision.resolved)),
            "matched_class": self.matched_class,
            "reason_code": self.reason_code,
            "notes_json": _dump(list(self.decision.notes)),
            "created_at": self.created_at,
            "submission_started_at": self.submission_started_at,
            "submitted_at": self.submitted_at,
            "slurm_job_id": self.slurm_job_id,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> PlacementPlan:
        """Rebuild a plan from its stored columns without consulting any policy.

        Reading a historical plan must never ask today's policy what it meant.
        """
        decision = PlacementDecision(
            requirement=WorkloadRequirement.from_dict(_load(record.get("requirement_json")) or {}),
            resolved=resolved_from_payload(_load(record.get("resolved_json")) or {}),
            matched_class=str(record.get("matched_class") or ""),
            reason_code=str(record.get("reason_code") or PLACEMENT_UNMANAGED),
            notes=tuple(_load(record.get("notes_json")) or ()),
            policy_revision=int(record.get("policy_revision") or 0),
            policy_digest=str(record.get("policy_digest") or ""),
        )
        return cls(
            task_id=str(record["task_id"]),
            stage_id=str(record["stage_id"]),
            revision=int(record["revision"]),
            decision=decision,
            created_at=float(record["created_at"]),
            state=str(record.get("state") or PLAN_STATE_PLANNED),
            submission_started_at=record.get("submission_started_at"),
            submitted_at=record.get("submitted_at"),
            slurm_job_id=record.get("slurm_job_id"),
        )


def resolved_payload(resolved: ResolvedResources) -> dict[str, Any]:
    """The stored form of one resolved request, including field provenance.

    ``public_dict`` deliberately drops ``sources`` because it is the wire shape
    a Runner sees.  A *plan* is not that wire shape: it must be re-readable
    exactly, and the provenance of each field is part of what makes the decision
    explainable.  Reading a stored plan is therefore not allowed to depend on
    the admin configuration that produced it, or on today's values.
    """
    return {**resolved.public_dict(), "sources": dict(resolved.sources)}


def resolved_from_payload(payload: Mapping[str, Any]) -> ResolvedResources:
    """Rebuild a resolved request from its stored form, provenance included."""
    resolved = ResolvedResources.from_snapshot(dict(payload))
    sources = payload.get("sources")
    if isinstance(sources, Mapping):
        return replace(resolved, sources=dict(sources))
    return resolved


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _load(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        return raw
    return json.loads(raw)


def plan_task_stages(
    task_type: Any,
    resolved_single: ResolvedResources | None,
    resolved_stages: Mapping[str, ResolvedResources],
    policy: PlacementPolicy | None,
    *,
    allowed_queues: Sequence[str] = (),
) -> tuple[ResolvedResources | None, dict[str, ResolvedResources], dict[str, PlacementDecision]]:
    """Plan every dispatchable stage of one task, independently.

    A composed workflow is planned per stage, so a CPU preprocessing step is
    never collateral of a GPU inference step: each keeps its own requirement, its
    own matched class, and its own resolved request.  Returns the replaced
    canonical snapshots — which remain the transport to the worker — and the
    decision for each stage key.
    """
    decisions: dict[str, PlacementDecision] = {}
    placed_single: ResolvedResources | None = None
    if resolved_single is not None:
        requirement = WorkloadRequirement.from_resolved(
            resolved_single, requires_network=bool(getattr(task_type, "requires_network", False))
        )
        decision = resolve_placement(requirement, resolved_single, policy, allowed_queues=allowed_queues)
        decisions[task_type.name] = decision
        placed_single = decision.resolved

    placed_stages: dict[str, ResolvedResources] = {}
    for stage in getattr(task_type, "workflow", ()) or ():
        snapshot = resolved_stages.get(stage.name)
        if snapshot is None:
            raise NoValidPlacement(f"Workflow stage {stage.name!r} has no resource snapshot to place")
        requirement = WorkloadRequirement.from_resolved(
            snapshot, requires_network=bool(getattr(stage, "requires_network", False))
        )
        decision = resolve_placement(requirement, snapshot, policy, allowed_queues=allowed_queues)
        decisions[stage.name] = decision
        placed_stages[stage.name] = decision.resolved
    return placed_single, placed_stages, decisions


def build_placement_plan(
    decision: PlacementDecision,
    *,
    task_id: str,
    stage_id: str,
    revision: int = 1,
    created_at: float,
) -> PlacementPlan:
    """Bind one resolved decision to the stage identity it explains."""
    return PlacementPlan(
        task_id=task_id,
        stage_id=stage_id,
        revision=revision,
        decision=decision,
        created_at=created_at,
    )


__all__ = [
    "ACCELERATOR_CUDA",
    "ACCELERATOR_NONE",
    "ACCELERATORS",
    "NO_VALID_PLACEMENT",
    "PARTITION_NOT_ALLOWED",
    "PLACEMENT_FALLBACK_APPLIED",
    "PLACEMENT_POLICY_INVALID",
    "PLACEMENT_RESOLVED_ACCELERATOR",
    "PLACEMENT_RESOLVED_CPU",
    "PLACEMENT_SCHEDULER_DEFAULT",
    "PLACEMENT_UNMANAGED",
    "PLAN_STATES",
    "PLAN_STATE_PLANNED",
    "PLAN_STATE_SUBMITTED",
    "PLAN_STATE_SUPERSEDED",
    "REASON_CODES",
    "REQUIRED_ACCELERATOR_UNAVAILABLE",
    "RESOURCE_OVERRIDE_CONFLICT",
    "NoValidPlacement",
    "PartitionNotAllowed",
    "PlacementClass",
    "PlacementDecision",
    "PlacementError",
    "PlacementPlan",
    "PlacementPolicy",
    "PlacementPolicyInvalid",
    "RequiredAcceleratorUnavailable",
    "ResourceOverrideConflict",
    "WorkloadRequirement",
    "build_placement_plan",
    "explain_placement",
    "memory_to_mb",
    "plan_task_stages",
    "resolve_placement",
    "resolved_from_payload",
    "resolved_payload",
]
