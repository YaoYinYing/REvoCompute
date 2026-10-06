# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Canonical resource accounting, entitlement, admission, and data-lifecycle vocabulary.

Four concepts are deliberately separate and none may overwrite another:

``accounting``
    append-only facts about what scarce resource was actually allocated or
    owned — allocated core-seconds, GPU-count x allocation-seconds in a named
    resource class, logical user-owned bytes.
``policy``
    what a subject is allowed to consume or retain (entitlement, allowance,
    soft quota).  Policy changes append new policy facts; they never rewrite a
    recorded allocation.
``telemetry``
    how effectively an allocation was used (GPU utilization, peak memory, queue
    delay).  Telemetry is never quota consumption.
``lifecycle``
    whether durable data is retained.  Orthogonal to the task's execution
    status: a finished computation stays finished when its data is archived or
    purged.

Everything here is stored in *base units* — integer seconds, bytes, and counts.
Hours, GiB, percentages, and "credits" exist only at projection boundaries.  A
measurement that could not be obtained is :data:`UNKNOWN` with its provenance,
never a fabricated zero: :class:`ComputeEntitlement.usage_complete` and its
``unsettled_quantity`` carry that distinction forward, and admission refuses on
the same reserve rather than admitting a subject as if nothing were running.

The durable ``(subject_type, subject_id)`` pair keeps the schema extensible to
project/lab subjects without implementing that hierarchy.  Only
:data:`SUBJECT_USER` is produced today.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Subjects and units
# ---------------------------------------------------------------------------

#: Only a user subject is implemented.  A future project/lab subject is a new
#: value, not a new ledger.
SUBJECT_USER = "user"
SUBJECT_TYPES = (SUBJECT_USER,)

#: Compute is recorded in auditable base units, never in an opaque "credit".
UNIT_GPU_SECOND = "gpu_second"
UNIT_CPU_CORE_SECOND = "cpu_core_second"
UNIT_STORAGE_BYTE = "storage_byte"
UNITS = (UNIT_GPU_SECOND, UNIT_CPU_CORE_SECOND, UNIT_STORAGE_BYTE)

#: Units whose facts are charged to a UTC calendar period.  Storage is durable
#: ownership, not consumption, so its balance spans every period.
PERIODIC_UNITS = (UNIT_GPU_SECOND, UNIT_CPU_CORE_SECOND)

#: Seconds per displayed GPU credit.  A projection unit, never a stored one.
SECONDS_PER_CREDIT = 60

_GRES_CLASS = re.compile(r"^gpu:(?:(?P<class>[A-Za-z][A-Za-z0-9_.-]*):)?(?P<count>[1-9][0-9]*)$")


def resource_class_for_gres(gres: str | None) -> str:
    """The resource class a Slurm GRES names, or ``""`` for the default class.

    ``gpu:a100:2`` keeps ``a100`` so a historical A100 allocation is never
    collapsed into an opaque GPU-hour; ``gpu:2`` is the scheduler's untyped
    request and belongs to the class-agnostic allowance.
    """
    if not gres:
        return ""
    match = _GRES_CLASS.fullmatch(str(gres).strip())
    return (match.group("class") or "") if match else ""


def units_for_gres(gres: str | None) -> int:
    """The accelerator count a GRES requests (``gpu:a100:2`` -> ``2``)."""
    if not gres:
        return 0
    match = _GRES_CLASS.fullmatch(str(gres).strip())
    return int(match.group("count")) if match else 0


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class LedgerKind(str, Enum):
    """What an append-only ledger row records.

    A hold is deliberately absent: an admission hold lives in the reservation
    table, which owns its own lifecycle and is the only representation of "this
    submission has staked a claim".  A settled resource is a fact; a hold is
    not.
    """

    MONTHLY_GRANT = "monthly_grant"
    ALLOWANCE_ADJUSTMENT = "allowance_adjustment"
    USAGE = "usage"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    REVERSAL = "reversal"
    ADMIN_RESET = "admin_reset"
    MIGRATION_ADJUSTMENT = "migration_adjustment"
    STORAGE_USAGE = "storage_usage"


#: Kinds that increase the effective allowance for a period.
ALLOWANCE_KINDS = (LedgerKind.MONTHLY_GRANT.value, LedgerKind.ALLOWANCE_ADJUSTMENT.value)

#: Kinds grouped as administrative corrections in a human-facing breakdown.
ADJUSTMENT_KINDS = (
    LedgerKind.ADMIN_ADJUSTMENT.value,
    LedgerKind.REVERSAL.value,
    LedgerKind.ADMIN_RESET.value,
    LedgerKind.MIGRATION_ADJUSTMENT.value,
)


class EvidenceSource(str, Enum):
    """Where an accounting fact came from.

    ``sacct``/SlurmDBD are optional, so a fact always names the evidence it was
    derived from and degrades to :data:`UNKNOWN` instead of a fabricated zero.
    """

    ALLOCATION_LIFECYCLE = "allocation_lifecycle"
    SLURM_LIVE = "slurm_live"
    SLURM_ACCOUNTING = "slurm_accounting"
    RUNNER_OBSERVATION = "runner_observation"
    RECONCILIATION = "reconciliation"
    POLICY = "policy"
    UNKNOWN = "unknown"


class MeasurementState(str, Enum):
    """Whether a quantity is a measured fact, an upper bound, or unknown."""

    MEASURED = "measured"
    UNKNOWN = "unknown"


class AllocationStatus(str, Enum):
    """Lifecycle of one recorded allocation."""

    ACTIVE = "active"
    SETTLED = "settled"
    REVIEW = "review"


class ReservationState(str, Enum):
    """Lifecycle of one admission hold."""

    HELD = "held"
    RELEASED = "released"
    EXPIRED = "expired"


class AdmissionReason(str, Enum):
    """Bounded reason code for an admission decision.

    Every value here is produced by a real refusal path.  A subject that does
    not exist is a 404 before admission is reached, so there is deliberately no
    "unknown subject" code: a vocabulary entry nothing can emit is a claim the
    system cannot make.
    """

    ADMITTED = "admitted"
    COMPUTE_EXHAUSTED = "compute_exhausted"
    STORAGE_SOFT_LIMIT = "storage_soft_limit"
    AUTHORIZATION_UNAVAILABLE = "authorization_unavailable"
    RUNNER_READINESS_UNAVAILABLE = "runner_readiness_unavailable"
    INFRASTRUCTURE_UNAVAILABLE = "infrastructure_unavailable"


class LedgerReason(str, Enum):
    """Bounded reason code stored on an append-only resource fact.

    One vocabulary for accounting, policy, and retention so a reason recorded in
    the ledger is comparable with an :class:`AdmissionReason` at a boundary
    (admin UI, ops log, and the future MCP projection) instead of being a free
    string that only the writer understands.
    """

    PERIOD_GRANT = "period_grant"
    ALLOWANCE_SET = "allowance_set"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    ADMIN_RESET = "admin_reset"
    ADMIN_RESET_ALL = "admin_reset_all"
    MIGRATED = "migrated"
    ACTUAL_ALLOCATION = "actual_allocation"
    SLURM_LIVE = "slurm_live"
    STORAGE_CHARGED = "storage_charged"
    STORAGE_RELEASED = "storage_released"


class ReservationReason(str, Enum):
    """Bounded reason code for the release (or living hold) of a reservation."""

    ADMISSION_RESERVED = "admission_reserved"
    ALLOCATION_STARTED = "allocation_started"
    DISPATCH_FAILED = "dispatch_failed"
    TASK_DELETED = "task_deleted"
    RELEASED = "released"
    EXPIRED = "expired"


class DataLifecycleState(str, Enum):
    """Retention state of one Task's durable data, orthogonal to execution."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETE_REQUESTED = "DELETE_REQUESTED"
    PURGING = "PURGING"
    PURGED = "PURGED"
    ERROR = "ERROR"


#: States a Task's data can still be deleted from.
DELETABLE_LIFECYCLE_STATES = (
    DataLifecycleState.ACTIVE.value,
    DataLifecycleState.ARCHIVED.value,
    DataLifecycleState.ERROR.value,
)

#: States in which the owned bytes are still charged to the subject.
CHARGED_LIFECYCLE_STATES = (
    DataLifecycleState.ACTIVE.value,
    DataLifecycleState.ARCHIVED.value,
    DataLifecycleState.DELETE_REQUESTED.value,
    DataLifecycleState.PURGING.value,
    DataLifecycleState.ERROR.value,
)

#: The per-call admission hold quantum, in base units.  A submission holds at
#: most this much of its remaining balance until the allocation settles, which
#: is what stops concurrent submissions from both consuming the final
#: entitlement without requiring a speculative output-size prediction.
DEFAULT_ADMISSION_QUANTUM: Mapping[str, int] = {
    UNIT_GPU_SECOND: 3600,
    UNIT_CPU_CORE_SECOND: 3600,
}

#: How long an unconsumed admission hold may live before reconciliation
#: releases it.  A hold only spans submit -> allocation start, so this bounds a
#: request that died in that window.
RESERVATION_TTL_SECONDS = 3600.0


# ---------------------------------------------------------------------------
# Entitlement, envelope, admission
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComputeEntitlement:
    """One (subject, unit, class) entitlement and its current position.

    Every entry in a :class:`ResourceEnvelope` is an *admission* scope: the
    class-agnostic GPU balance that admission actually decides on, plus the units
    this deployment records without gating.  ``allowance`` is ``None`` for an
    ungated unit: its usage is still recorded, audited, and reported, but no
    policy exists to admit or refuse it.

    A named resource class is a *report* of the same ledger
    (``TaskDatabase.class_usage``), never a second entitlement: the deployment
    has one allowance, so a per-class balance could disagree with the decision
    made against it and a consumer reading it would get a wrong "yes".

    ``unsettled`` counts allocations whose authoritative elapsed time is not yet
    known.  While it is non-zero the recorded usage is a *lower bound*, so
    :attr:`usage_complete` is ``False`` and an admission decision says so rather
    than pretending the balance is exact.
    """

    unit: str
    resource_class: str
    allowance: int | None
    used: int
    reserved: int
    unsettled: int = 0
    unsettled_quantity: int = 0
    evidence_sources: tuple[str, ...] = ()

    @property
    def enforced(self) -> bool:
        return self.allowance is not None

    @property
    def remaining(self) -> int | None:
        """Balance after settled usage, live holds, and unsettled worst case.

        ``unsettled_quantity`` is subtracted rather than omitted: an allocation
        whose authoritative elapsed time is not yet known has definitely
        consumed *something*, so a balance that ignored it would overstate the
        entitlement available to the next submission.
        """
        if self.allowance is None:
            return None
        return self.allowance - self.used - self.reserved - self.unsettled_quantity

    @property
    def usage_complete(self) -> bool:
        return self.unsettled == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "resource_class": self.resource_class,
            "enforced": self.enforced,
            "allowance": self.allowance,
            "used": self.used,
            "reserved": self.reserved,
            "unsettled_allocations": self.unsettled,
            "unsettled_quantity": self.unsettled_quantity,
            "remaining": self.remaining,
            "usage_complete": self.usage_complete,
            "evidence_sources": list(self.evidence_sources),
        }


@dataclass(frozen=True)
class StorageEntitlement:
    """Logical user-owned bytes, tracked separately from physical capacity.

    ``soft_limit_bytes`` is ``None`` when no durable quota is configured.  A
    successful computation that crosses a soft limit keeps its result; only
    *later* admission is restricted.
    """

    logical_owned_bytes: int
    soft_limit_bytes: int | None = None

    @property
    def remaining_bytes(self) -> int | None:
        return None if self.soft_limit_bytes is None else self.soft_limit_bytes - self.logical_owned_bytes

    @property
    def over_soft_limit(self) -> bool:
        return self.soft_limit_bytes is not None and self.logical_owned_bytes > self.soft_limit_bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_owned_bytes": self.logical_owned_bytes,
            "soft_limit_bytes": self.soft_limit_bytes,
            "remaining_bytes": self.remaining_bytes,
            "over_soft_limit": self.over_soft_limit,
        }


@dataclass(frozen=True)
class ResourceEnvelope:
    """The canonical per-subject position that downstream consumers project.

    ``compute`` carries only the scopes admission actually decides on.  The
    deployment has one allowance, so a per-class entry would be a second answer
    to "may this user run?" that can disagree with the decision itself; per-class
    detail is a *report* of the same ledger (``TaskDatabase.class_usage``) and is
    never an admission source.  Storage has exactly one representation,
    :attr:`storage` — it is durable ownership, not per-period consumption, so it
    is not also a compute entry.

    Placement (#60) consumes :attr:`compute`; Admin reporting (#61) aggregates
    the same ledger; MCP projects an admission result without owning accounting.
    """

    subject_type: str
    subject_id: int
    period: str
    compute: tuple[ComputeEntitlement, ...]
    storage: StorageEntitlement

    def compute_for(self, unit: str) -> ComputeEntitlement | None:
        """The authoritative entitlement for *unit*, or ``None`` if unrecorded."""
        return next((item for item in self.compute if item.unit == unit), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "period": self.period,
            "compute": [item.to_dict() for item in self.compute],
            "storage": self.storage.to_dict(),
        }


# ---------------------------------------------------------------------------
# Ledger arithmetic (pure)
# ---------------------------------------------------------------------------


def periods_for_unit(unit: str) -> bool:
    """Whether facts in *unit* are scoped to a UTC period."""
    return unit in PERIODIC_UNITS


def class_in_scope(resource_class: str, scoped_class: str) -> bool:
    """Whether a fact recorded under *resource_class* belongs to *scoped_class*.

    The class-agnostic scope (``""``) is the deployment's single allowance, so
    it covers every accelerator class: an ``a100`` second still consumes the
    balance it was admitted against.  A named scope is the per-class report,
    which selects the same facts filtered rather than reading a second ledger.
    """
    return scoped_class == "" or resource_class == scoped_class


def summarize_ledger(
    rows: Iterable[Mapping[str, Any]], *, unit: str, resource_class: str = "", period: str | None = None
) -> dict[str, int]:
    """Sum one (unit, class) position from append-only ledger rows.

    ``usage``/``storage_usage`` rows are stored negative (they consume), the
    monthly allowance and adjustments positive.  This is a pure projection of
    settled facts; an outstanding admission hold is a reservation row and is
    never conflated with consumption.
    """
    allowance = used = 0
    for row in rows:
        if str(row.get("unit")) != unit or not class_in_scope(
            str(row.get("resource_class") or ""), resource_class
        ):
            continue
        if period is not None and periods_for_unit(unit) and str(row.get("period")) != period:
            continue
        quantity = int(row.get("quantity") or 0)
        kind = str(row.get("kind") or "")
        if kind in ALLOWANCE_KINDS or kind in ADJUSTMENT_KINDS:
            allowance += quantity
        elif kind in (LedgerKind.USAGE.value, LedgerKind.STORAGE_USAGE.value):
            used -= quantity
    return {"allowance": allowance, "used": used, "remaining": allowance - used}


def admission_hold_quantity(remaining: int, unit: str, *, quantum: int | None = None) -> int:
    """The hold a submission takes from a positive remaining balance.

    Bounded by the policy quantum so a large balance still admits several
    concurrent submissions, and capped by the remaining balance so the *final*
    entitlement is held by exactly one submission.
    """
    if remaining <= 0:
        return 0
    limit = DEFAULT_ADMISSION_QUANTUM.get(unit, 0) if quantum is None else int(quantum)
    if limit <= 0:
        return remaining
    return min(remaining, limit)


# ---------------------------------------------------------------------------
# Projection formatting (boundary only)
# ---------------------------------------------------------------------------


def credits_from_seconds(seconds: int) -> float:
    """Displayed credits for a GPU-second quantity."""
    return seconds / SECONDS_PER_CREDIT


def gib_from_bytes(value: int) -> float:
    """Displayed GiB for a byte quantity."""
    return round(value / (1024**3), 3)


def hours_from_seconds(seconds: int) -> float:
    return round(seconds / 3600.0, 3)


# ---------------------------------------------------------------------------
# Data lifecycle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataLifecycleRecord:
    """One Task's durable-data retention state.

    ``logical_bytes`` is what the Task owns on disk; ``accounted_bytes`` is how
    much of that is currently charged to the subject in the ledger.  They are
    separate so a partial purge cannot release quota that was never charged,
    and a completed purge cannot release it twice.
    """

    task_id: str
    subject_type: str
    subject_id: int
    state: str
    logical_bytes: int = 0
    accounted_bytes: int = 0
    requested_by_user_id: int | None = None
    requested_at: float | None = None
    claimed_at: float | None = None
    purged_at: float | None = None
    error: str = ""
    updated_at: float = 0.0

    @property
    def charged(self) -> bool:
        return self.state in CHARGED_LIFECYCLE_STATES

    @property
    def releasable_bytes(self) -> int:
        """Bytes a completed purge may release: only what was charged."""
        return self.accounted_bytes if self.accounted_bytes > 0 else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "state": self.state,
            "logical_bytes": self.logical_bytes,
            "accounted_bytes": self.accounted_bytes,
            "requested_at": self.requested_at,
            "purged_at": self.purged_at,
            "error": self.error,
        }


@dataclass(frozen=True)
class ReconciliationDrift:
    """One detected inconsistency between persisted facts and reality."""

    kind: str
    subject: str
    detail: str
    repairable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "subject": self.subject, "detail": self.detail, "repairable": self.repairable}


@dataclass(frozen=True)
class ReconciliationReport:
    """The bounded outcome of one reconciliation pass, safe to repeat."""

    settled_allocations: int = 0
    review_allocations: int = 0
    active_allocations: int = 0
    expired_reservations: int = 0
    released_reservations: int = 0
    charged_tasks: int = 0
    purged_tasks: int = 0
    drift: tuple[ReconciliationDrift, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "settled_allocations": self.settled_allocations,
            "review_allocations": self.review_allocations,
            "active_allocations": self.active_allocations,
            "expired_reservations": self.expired_reservations,
            "released_reservations": self.released_reservations,
            "charged_tasks": self.charged_tasks,
            "purged_tasks": self.purged_tasks,
            "drift": [item.to_dict() for item in self.drift],
        }


def normalize_ledger_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """A stable, JSON-safe projection of ledger rows for API consumers."""
    return [
        {
            "id": int(row["id"]),
            "subject_type": str(row.get("subject_type") or SUBJECT_USER),
            "subject_id": int(row.get("subject_id") or 0),
            "period": str(row.get("period") or ""),
            "kind": str(row.get("kind") or ""),
            "unit": str(row.get("unit") or ""),
            "resource_class": str(row.get("resource_class") or ""),
            "quantity": int(row.get("quantity") or 0),
            "task_id": row.get("task_id"),
            "stage_id": row.get("stage_id"),
            "slurm_job_id": row.get("slurm_job_id"),
            "actor_user_id": row.get("actor_user_id"),
            "reason": row.get("reason"),
            "reason_code": row.get("reason_code"),
            "evidence_source": str(row.get("evidence_source") or EvidenceSource.UNKNOWN.value),
            "created_at": float(row.get("created_at") or 0.0),
        }
        for row in rows
    ]
