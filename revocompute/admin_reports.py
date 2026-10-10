# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Admin read model: one bounded projection over facts the system already owns.

An Admin operator needs one place to answer "what is running, where was it placed,
what does it cost, is anything inconsistent, and who changed what".  The failure
mode this module exists to prevent is a reporting layer that grows its own ledger,
its own scheduler view, or its own readiness verdict and then disagrees with the
authority it was supposed to summarize.  So it owns no state and derives no second
answer: every field is read from the store that already owns it, and every field
says whether it was measured.

Where each answer comes from:

``task_store`` (:class:`revocompute.db.TaskDatabase`)
    Task rows, the append-only resource ledger, allocation facts, admission
    reservations, and data-lifecycle rows.
``revocompute.resource_ledger``
    the accounting vocabulary and pure arithmetic — units, entitlement, the
    reconciliation-drift value objects — so a projection and its consumer speak
    one set of names.
``revocompute.resource_lifecycle``
    the read-only consistency check.  Detection and navigation only: a drift
    record names a subject, a kind, and a detail, and nothing here repairs it.
``revocompute.placement``
    a *recorded* placement decision, read verbatim through
    :meth:`~revocompute.placement.PlacementDecision.from_record`.  A historical
    Task is never re-resolved: a decision recorded under last month's policy is
    reported as it was recorded, whatever today's configuration says.
``revocompute.runner_admin_view`` / ``runner_readiness``
    the derived Runner readiness verdict, when the caller supplies the deployment
    host view.  Readiness is derived, never stored, so this module asks the
    canonical evaluator instead of remembering a flag — and reports "not
    evaluated" rather than an empty fleet as "healthy".
``revocompute.operator_jobs``
    resolved Operator Job history, when the caller supplies the job store.

Three rules hold everywhere below:

1. **Unknown is never zero.**  A quantity nobody measured is ``None`` with a
   state or provenance label; a unit whose consumption was never measured is
   reported unmeasured with the canonical allowance beside it, and an allocation
   whose shape no one observed stays unknown.
2. **Every read is bounded.**  Each entry point takes an explicit ``limit`` whose
   ceiling is the canonical readers' own ceiling, plus explicit counts of what a
   bound cut off, so a large deployment degrades into a labelled truncation
   rather than an unbounded scan.
3. **This module is not an authority.**  It adds no OpenAPI surface, no route, no
   table, and no scheduler: an Admin HTTP handler authorizes the caller and calls
   these functions, and every refusal here is a typed
   :class:`AdminReportError` a handler maps to one bounded status code.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from revocompute import resource_ledger as rloan
from revocompute import resource_lifecycle as rlife
from revocompute.placement import PlacementDecision
from revocompute.resource_policy import ResourceValidationError, ResolvedResources
from revocompute.runner_admin_view import fleet_view

#: Default page size for every bounded read here.
DEFAULT_LIMIT = 50

#: The hard ceiling on one read.  It is deliberately the *canonical readers'*
#: ceiling (``TaskDatabase.list_ledger`` / ``list_policy_audit`` refuse above
#: 200), so this facade introduces no second bound a caller could probe for.
MAX_LIMIT = 200

#: Bound on Task rows one operations read considers before it stops scanning and
#: says so.  ``TaskDatabase.list_tasks`` reads the whole table, so the bound is
#: applied here rather than pretended away.
MAX_TASK_SCAN = 5000

#: Bound on the subjects one activity read fans out over, so "recent Admin
#: activity" cannot be turned into an unbounded per-user scan.
MAX_ACTIVITY_SUBJECTS = 500

#: The canonical execution states, spelled exactly as ``TaskDatabase`` spells
#: them.  The store owns the vocabulary (``VALID_STATUSES``) but not this
#: grouping, so it is named once here for every projection that needs it.
QUEUED_TASK_STATUSES = ("pending", "queued")
RUNNING_TASK_STATUSES = ("running",)
ACTIVE_TASK_STATUSES = QUEUED_TASK_STATUSES + RUNNING_TASK_STATUSES
FAILED_TASK_STATUSES = ("failed",)
FINISHED_TASK_STATUSES = ("finished",)

#: Placement projection states.  ``unrecorded`` is a real answer for a Task
#: submitted before placement decisions existed, and it is never a guessed class.
PLACEMENT_RECORDED = "recorded"
PLACEMENT_UNRECORDED = "unrecorded"
PLACEMENT_UNREADABLE = "unreadable"

#: Per-unit projection states: whether the unit's consumption has actually been
#: *measured* (the ledger holds a consumption or ownership fact for it) or the
#: deployment has so far recorded only policy for the subject.
#:
#: The distinction matters because the canonical ledger records policy eagerly and
#: measurement only when something really ran: a freshly configured subject has an
#: allowance fact and no usage fact at all.  Reporting that subject's usage as ``0``
#: would claim it consumed nothing, which nobody observed; reporting it as unknown
#: is the same rule admission applies to an unsettled allocation.
UNIT_MEASURED = "measured"
UNIT_UNMEASURED = "unmeasured"

#: Ledger kinds that *measure* what a subject consumed or owns.  Every other kind
#: is policy — the period grant, an allowance change, an administrative adjustment
#: — which describes what a subject is allowed rather than what it did.
MEASUREMENT_KINDS = frozenset({rloan.LedgerKind.USAGE.value, rloan.LedgerKind.STORAGE_USAGE.value})


class AdminReportError(ValueError):
    """A refused Admin read: an unbounded or malformed argument.

    A typed refusal rather than a bare ``ValueError`` so a handler maps it to one
    bounded status code (400) and a test can assert the refusal instead of
    asserting a 500 the caller would have to debug from a stack trace.
    """


def _bounded_limit(limit: Any) -> int:
    """Clamp one requested page size, refusing a value that is not a page size.

    A page size above the ceiling is *clamped*, not refused: a client asking for
    more than the deployment serves has made no mistake the operator needs to act
    on, and the response names the ceiling so the page it received is not mistaken
    for everything that exists.  A value that is not a positive integer at all is
    a real error and is refused.
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise AdminReportError("limit must be an integer")
    if limit < 1:
        raise AdminReportError("limit must be a positive integer")
    return min(limit, MAX_LIMIT)


def parse_limit(raw: Any) -> int:
    """One requested ``limit`` query value as a page size, or a typed refusal."""
    if raw is None or raw == "":
        return DEFAULT_LIMIT
    text = str(raw).strip()
    if not text.isdigit():
        raise AdminReportError("limit must be a positive integer")
    return _bounded_limit(int(text))


def _optional_seconds(value: Any) -> float | None:
    """A timestamp as a float, or ``None`` when the store did not record one."""
    return None if value is None else float(value)


def _form_payload(task_row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Parse a Task row's ``input_form`` blob, or ``None`` when there is none.

    ``None`` is the honest answer for a Task older than the shape, and it is what
    makes every reader below report "unrecorded" instead of inventing a value.
    """
    if not task_row:
        return None
    raw = task_row.get("input_form")
    if not raw:
        return None
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _json_or_none(value: Any) -> Any:
    """A stored JSON text as a value, or ``None`` when it is absent or unreadable."""
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Placement: the recorded decision, never a re-resolution
# ---------------------------------------------------------------------------


def _placement_entry(
    record: Any, snapshot: Any, *, stage: str | None, provenance: str
) -> dict[str, Any]:
    """Join one recorded decision to its frozen snapshot, or say why it cannot.

    A record without its snapshot is *unreadable*, not unrecorded: the decision
    exists and disagrees with what is on hand, which is a different fact from a
    Task that never recorded one, and only one of the two is worth investigating.
    """
    base: dict[str, Any] = {
        "stage": stage,
        "provenance": provenance,
        "state": PLACEMENT_UNRECORDED,
        "execution_class_id": None,
        "reason_code": None,
        "reason": None,
        "policy_revision": None,
        "decision": None,
        "error": None,
    }
    if record is None:
        return base
    if snapshot is None:
        return {
            **base,
            "state": PLACEMENT_UNREADABLE,
            "error": "the recorded decision has no frozen resource snapshot to describe",
        }
    try:
        resources = ResolvedResources.from_snapshot(dict(snapshot))
        decision = PlacementDecision.from_record(dict(record), resources)
    except (ResourceValidationError, KeyError, TypeError, ValueError) as exc:
        return {**base, "state": PLACEMENT_UNREADABLE, "error": str(exc)}
    return {
        **base,
        "state": PLACEMENT_RECORDED,
        "execution_class_id": decision.execution_class.identifier,
        "reason_code": decision.reason_code,
        "reason": decision.reason,
        "policy_revision": decision.policy_revision,
        # The canonical projection of a decision, unaltered: the record it was
        # persisted as, joined to the resolved fields it was derived from.
        "decision": decision.to_dict(),
    }


def placement_projection(task_row: Mapping[str, Any], *, stage: str | None = None) -> dict[str, Any]:
    """The RECORDED placement of one Task (or one workflow stage), as recorded.

    The decision is read through :meth:`PlacementDecision.from_record` against the
    frozen snapshot stored beside it in ``input_form``.  Nothing here calls a
    resolver: a Task placed under an older policy reports that older class, that
    older policy revision, and that older reason, because those are the facts of
    what was requested.  A Task with no recorded decision reports
    ``state="unrecorded"`` — never a class guessed from today's configuration.
    """
    return _placement_entry(
        *(_placement_parts(task_row, stage=stage)),
        stage=stage,
        provenance=_placement_provenance(task_row, stage=stage),
    )


def _placement_parts(task_row: Mapping[str, Any], *, stage: str | None) -> tuple[Any, Any]:
    """The ``(record, snapshot)`` pair for one profile, or ``(None, None)``.

    Primary and stage profiles are read from the same ``input_form`` keys the
    submission path writes, so a caller cannot ask for a profile by a name the
    writer never used and be handed a different profile's decision.
    """
    form = _form_payload(task_row)
    if form is None:
        return None, None
    if stage is None:
        return form.get("placement_decision"), form.get("resource_policy")
    decisions = form.get("placement_decisions")
    policies = form.get("resource_policies")
    record = decisions.get(stage) if isinstance(decisions, Mapping) else None
    snapshot = policies.get(stage) if isinstance(policies, Mapping) else None
    return record, snapshot


def _placement_provenance(task_row: Mapping[str, Any], *, stage: str | None) -> str:
    """Where a profile's decision was read from, or why nothing was found there."""
    form = _form_payload(task_row)
    if form is None:
        return "input_form_missing"
    if stage is None:
        return "input_form.placement_decision"
    decisions = form.get("placement_decisions")
    if isinstance(decisions, Mapping) and stage in decisions:
        return f"input_form.placement_decisions[{stage}]"
    return "input_form.placement_decisions_missing"


def placement_projections(task_row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every profile of one Task: the primary decision plus each workflow stage.

    One parse of ``input_form`` per profile, so a Task's stages can never be
    reported against different snapshots of its own submission record — the pair
    read for a stage is the pair written for that stage.
    """
    projections = [placement_projection(task_row, stage=None)]
    form = _form_payload(task_row)
    decisions = form.get("placement_decisions") if form is not None else None
    if isinstance(decisions, Mapping):
        for name in sorted(decisions):
            projections.append(placement_projection(task_row, stage=str(name)))
    return projections


# ---------------------------------------------------------------------------
# Tasks: canonical status, timestamps, and where each was placed
# ---------------------------------------------------------------------------


#: The store's own status vocabulary, applied as groups here.  ``TaskDatabase``
#: owns the individual spellings (``STOP_POLLING_STATUSES`` and friends); this
#: module only needs the groupings a report reads.
DELETED_STATUSES = frozenset({"deleted:finshed", "deleted:cancel"})

_TERMINAL_STATUSES = frozenset(
    {
        "finished",
        "failed",
        "cancelled",
        "deleting:finished",
        "deleting:cancel",
        "cleaned:finished",
        "cleaned:cancel",
        *DELETED_STATUSES,
    }
)


def _placement_view(placement: Mapping[str, Any]) -> dict[str, Any]:
    """The compact placement summary one profile contributes to a Task row.

    A label, not a verdict: ``unrecorded`` and ``unreadable`` are reported as
    themselves, so an operator can tell a Task older than the decision record from
    a record that disagrees with its own frozen snapshot.
    """
    return {
        "stage": placement["stage"],
        "state": placement["state"],
        "execution_class_id": placement["execution_class_id"],
        "reason_code": placement["reason_code"],
        "reason": placement["reason"],
        "policy_revision": placement["policy_revision"],
    }


def _task_entry(task: Mapping[str, Any], placements: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One Task as an operator reads it, with every derived number labelled.

    ``queue_seconds``/``run_seconds`` are derived only from timestamps the store
    actually recorded, and are ``None`` — never ``0`` — when it recorded none: a
    Task still queued has no run time, and a Task whose row predates a timestamp
    has no queue time, and the two are different facts.  Every profile the Task
    recorded a decision for is listed, primary first, so a workflow's stages are
    visible beside the Task they belong to.
    """
    uploaded = _optional_seconds(task.get("uploaded_at"))
    started = _optional_seconds(task.get("started_at"))
    finished = _optional_seconds(task.get("finished_at"))
    status = str(task.get("status") or "").strip().lower()
    return {
        "task_id": str(task.get("md5sum") or ""),
        "task_type": task.get("task_type"),
        "status": status,
        "terminal": status in _TERMINAL_STATUSES,
        "owner": {"user_id": task.get("submitted_by_user_id"), "username": task.get("username")},
        "submitted_at": uploaded,
        "started_at": started,
        "finished_at": finished,
        "walltime_seconds": _optional_seconds(task.get("walltime")),
        "queue_seconds": (started - uploaded) if (started is not None and uploaded is not None) else None,
        "run_seconds": (finished - started) if (finished is not None and started is not None) else None,
        "slurm_job_id": task.get("slurm_job_id"),
        "error": task.get("error") or None,
        "placement": _placement_view(placements[0]),
        "placements": [_placement_view(item) for item in placements],
    }


def _duration_summary(entries: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    """A total and a maximum over the entries that actually carry the field.

    ``measured`` and ``unmeasured`` are reported beside the numbers so a total
    that covers three Tasks out of fifty is never read as the deployment's
    runtime.  With nothing measured, both numbers are ``None``: a zero total
    would be the claim that every Task took no time.
    """
    values = [float(entry[field]) for entry in entries if entry.get(field) is not None]
    if not values:
        return {
            "state": rloan.MeasurementState.UNKNOWN.value,
            "measured": 0,
            "unmeasured": len(entries),
            "total_seconds": None,
            "max_seconds": None,
        }
    return {
        "state": rloan.MeasurementState.MEASURED.value,
        "measured": len(values),
        "unmeasured": len(entries) - len(values),
        "total_seconds": round(sum(values), 3),
        "max_seconds": round(max(values), 3),
    }


def task_operations(
    task_store: Any,
    *,
    limit: int = DEFAULT_LIMIT,
    statuses: Iterable[str] | None = None,
    task_types: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Active, queued, running, and recently finished Tasks, newest first.

    The scan is bounded twice over: the store's ``list_tasks()`` result is walked
    at most :data:`MAX_TASK_SCAN` rows deep, and at most ``limit`` Tasks are
    returned.  Both bounds are reported (``scanned_tasks``, ``truncated``) so a
    page that cut something off says so instead of reading as the whole fleet.

    ``statuses`` and ``task_types`` narrow the page; they never narrow the counts,
    which cover the scanned window and are named ``*_in_window`` for that reason:
    this module has no global counter to read, and inventing one by scanning the
    whole table unbounded is exactly the shadow index it must not become.
    """
    page = _bounded_limit(limit)
    wanted = {str(item).strip().lower() for item in statuses} if statuses else None
    wanted_types = {str(item) for item in task_types} if task_types else None
    rows = list(task_store.list_tasks())
    truncated_scan = len(rows) > MAX_TASK_SCAN
    scanned = rows[:MAX_TASK_SCAN]
    entries: list[dict[str, Any]] = []
    counts = {
        "queued": 0,
        "running": 0,
        "active": 0,
        "finished": 0,
        "failed": 0,
        "recorded_analysis": 0,
    }
    failed_entries: list[dict[str, Any]] = []
    for task in scanned:
        status = str(task.get("status") or "").strip().lower()
        if status in DELETED_STATUSES:
            # A deleted Task is gone; its artifacts and its placement are not
            # operational state any Admin surface should resurrect.
            continue
        if status in QUEUED_TASK_STATUSES:
            counts["queued"] += 1
        if status in RUNNING_TASK_STATUSES:
            counts["running"] += 1
        if status in ACTIVE_TASK_STATUSES:
            counts["active"] += 1
        if status in FINISHED_TASK_STATUSES:
            counts["finished"] += 1
        if status in FAILED_TASK_STATUSES:
            counts["failed"] += 1
        if wanted is not None and status not in wanted:
            continue
        if wanted_types is not None and str(task.get("task_type")) not in wanted_types:
            continue
        placements = placement_projections(task)
        if any(item["state"] == PLACEMENT_RECORDED for item in placements):
            counts["recorded_analysis"] += 1
        entry = _task_entry(task, placements)
        entries.append(entry)
        if status in FAILED_TASK_STATUSES:
            failed_entries.append(entry)
    page_entries = entries[:page]
    recent_failures = sorted(
        failed_entries, key=lambda item: float(item.get("finished_at") or 0.0), reverse=True
    )[:10]
    return {
        "tasks": page_entries,
        "counts_in_window": counts,
        "limit_ceiling": MAX_LIMIT,
        "window": {
            "scanned_tasks": len(scanned),
            "scan_ceiling": MAX_TASK_SCAN,
            "truncated": truncated_scan or len(entries) > page,
            "limit": page,
            "limit_ceiling": MAX_LIMIT,
        },
        "recent_failures": [
            {"task_id": item["task_id"], "status": item["status"], "finished_at": item["finished_at"]}
            for item in recent_failures
        ],
        # Runtime and queue latency cover the Tasks on this page, and only the
        # ones whose canonical timestamps support the number.
        "runtime": _duration_summary(page_entries, "walltime_seconds"),
        "queue_latency": _duration_summary(page_entries, "queue_seconds"),
        "generated_at": time.time(),
    }


# ---------------------------------------------------------------------------
# Resources: allocation facts, entitlement pressure, durable storage
# ---------------------------------------------------------------------------


def _unit_measurement(entitlement: rloan.ComputeEntitlement | None) -> dict[str, Any]:
    """One unit's canonical position, with "not measured" kept distinct from zero.

    ``None`` — a subject the accounting path has never recorded a fact for — stays
    ``None`` throughout.  Turning it into ``0`` would claim the subject consumed
    nothing, which is a fact nobody observed.
    """
    if entitlement is None:
        return {
            "state": rloan.MeasurementState.UNKNOWN.value,
            "usage_complete": None,
            "used": None,
            "reserved": None,
            "unsettled_allocations": None,
            "unsettled_quantity": None,
            "evidence_sources": [],
        }
    return {
        "state": rloan.MeasurementState.MEASURED.value,
        "usage_complete": entitlement.usage_complete,
        "used": entitlement.used,
        "reserved": entitlement.reserved,
        "unsettled_allocations": entitlement.unsettled,
        "unsettled_quantity": entitlement.unsettled_quantity,
        "evidence_sources": list(entitlement.evidence_sources),
    }


def _pressure(entitlement: rloan.ComputeEntitlement, *, measured: bool) -> str:
    """The bounded admission-pressure label for one unit.

    Read off the canonical :attr:`ComputeEntitlement.remaining`, which already
    subtracts settled usage, live holds, and the worst case of every unsettled
    allocation — so this label can never be a second balance that disagrees with
    the number admission decides on.  A unit with no policy (``allowance is None``)
    is accounted but never gated, so it has no pressure to report.

    A unit nothing was ever measured in reports ``unknown_unmeasured`` even when
    policy exists: an allowance is what a subject may consume, and a balance read
    from it alone says nothing about what it did consume.
    """
    if not entitlement.enforced:
        return "ungated"
    if not measured:
        return "unknown_unmeasured"
    if not entitlement.usage_complete:
        return "unknown_unsettled"
    return "exhausted" if int(entitlement.remaining or 0) <= 0 else "available"


def _compute_class_breakdown(ledger_rows: Sequence[Mapping[str, Any]], *, period: str) -> list[dict[str, Any]]:
    """Per-resource-class usage for one ledger *window*, by recorded class.

    A class is a *report* of the one ledger, never a second balance: the
    deployment has a single allowance, so a per-class "remaining" would be a
    second answer that can contradict the decision admission actually made.  The
    buckets group the window's rows for *this* period by the class each row was
    recorded under, so they add back up to that period's recorded GPU usage.

    The empty bucket is rows whose request named *no* device class (a plain
    ``gpu:1``), which is a different fact from the class-agnostic allowance
    scope: ``TaskDatabase.class_usage`` reports the empty class as the
    every-class total, because the empty scope is the one balance admission
    decides on.  Both facts are true and are not the same number, so this
    projection reports the window it was given rather than claiming to be that
    reader.
    """
    usage: dict[str, int] = {}
    for row in ledger_rows:
        if str(row.get("unit")) != rloan.UNIT_GPU_SECOND:
            continue
        if str(row.get("kind")) != rloan.LedgerKind.USAGE.value:
            continue
        if period and str(row.get("period") or "") != period:
            continue
        resource_class = str(row.get("resource_class") or "")
        usage[resource_class] = usage.get(resource_class, 0) + int(row.get("quantity") or 0)
    return [
        {
            "resource_class": resource_class or None,
            "class_label": resource_class or "untyped",
            "used_gpu_seconds": -quantity,
        }
        for resource_class, quantity in sorted(usage.items())
    ]


def _storage_block(envelope: rloan.ResourceEnvelope, user_id: int, task_store: Any) -> dict[str, Any]:
    """Durable ownership for one subject: bytes owned, the effective limit, and state.

    The ceiling is the *effective* one — the subject's own policy resolved over
    the deployment default — because that is the number admission refuses on; a
    report that named the deployment default instead would disagree with the
    admission decision the moment an override exists.  ``policy.source`` names
    which of the three decisions produced it, so an operator can tell "no
    per-user override, the deployment default applies" from "an explicit grant of
    no ceiling".

    ``effective_limit_bytes is None`` means nothing caps this subject's storage;
    it does not mean a zero limit.  ``over_limit`` is only ``True`` or ``False``
    once a limit exists, because "over" is undefined without one.
    """
    storage = envelope.storage
    policy = task_store.storage_quota_policy(user_id)
    state = policy.state.value
    source = "per_user_override" if state != "inherit" else "deployment_default"
    limit = storage.soft_limit_bytes
    return {
        "logical_owned_bytes": storage.logical_owned_bytes,
        "effective_limit_bytes": limit,
        "remaining_bytes": storage.remaining_bytes,
        "over_limit": None if limit is None else storage.over_soft_limit,
        "policy": {
            "state": state,
            "source": source,
        },
    }


def _allocation_facts(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Allocation rows as recorded, with an unknown shape kept unknown.

    ``resource_count`` is ``NULL`` for exactly one real case — the scheduler
    proved a job held a node and nothing recorded how much of a unit — and a
    device total that included such a row would be a *lower bound* silently
    published as a total.  When any row of a unit has an unknown shape that
    unit's total is therefore ``None`` (the unknown case), while the count of
    unknown-shape rows is reported beside it: a zero total would be the false
    claim that nothing was allocated.
    """
    total_gpu: int | None = 0
    total_cpu: int | None = 0
    unknown_gpu = unknown_cpu = 0
    classes: dict[str, int] = {}
    for record in records:
        unit = str(record.get("unit") or "")
        count = record.get("resource_count")
        if count is None:
            if unit == rloan.UNIT_GPU_SECOND:
                unknown_gpu += 1
                total_gpu = None
            else:
                unknown_cpu += 1
                total_cpu = None
            continue
        if unit == rloan.UNIT_GPU_SECOND:
            # Once a row of this unit is unknown-shaped the unit's total is unknown
            # for good: adding a later known row back into ``None`` would publish a
            # lower bound as a total, and make the answer depend on row order.
            if total_gpu is not None:
                total_gpu += int(count)
            if int(count):
                resource_class = str(record.get("resource_class") or "")
                classes[resource_class] = classes.get(resource_class, 0) + int(count)
        elif unit == rloan.UNIT_CPU_CORE_SECOND:
            if total_cpu is not None:
                total_cpu += int(count)
    return {
        "allocated_gpu_devices": total_gpu,
        "allocated_cpu_cores": total_cpu,
        "unknown_shape_allocations": {"gpu_second": unknown_gpu, "cpu_core_second": unknown_cpu},
        "resource_class_devices": [
            {"resource_class": resource_class or None, "class_label": resource_class or "untyped", "devices": devices}
            for resource_class, devices in sorted(classes.items())
        ],
    }


def _measured_units(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    """Which accounting units the ledger window actually measured, not just allowed.

    A window that holds the period's grant and nothing else proves the subject was
    *configured*, not that it ever consumed anything, so measurement kinds are the
    test.
    """
    return {
        str(row.get("unit") or "")
        for row in rows
        if str(row.get("kind") or "") in MEASUREMENT_KINDS
    }


def _resource_operations_for_user(
    task_store: Any, user_id: int, *, limit: int
) -> dict[str, Any]:
    """One subject's complete resource position, projected from canonical reads."""
    envelope = task_store.resource_envelope(user_id)
    window = task_store.list_ledger(user_id, limit=limit)
    unsettled = [
        record
        for record in task_store.list_unsettled_allocations()[:MAX_TASK_SCAN]
        if int(record.get("subject_id") or 0) == int(user_id)
    ]
    # An allocation fact is a measurement of a resource, whether or not its
    # elapsed time has settled yet, so a live allocation makes its unit measured.
    measured = _measured_units(window) | {
        str(record.get("unit") or "") for record in unsettled
    }
    period = envelope.period
    units: list[dict[str, Any]] = []
    for entitlement in envelope.compute:
        is_measured = entitlement.unit in measured
        units.append(
            {
                "unit": entitlement.unit,
                "measured": is_measured,
                "enforced": entitlement.enforced,
                # Policy is the deployment's answer even before anything ran, and
                # it is the canonical one: the envelope already materialized the
                # period's base allowance.  It is reported as the readiness it is,
                # and it never stands in for a measurement.
                "allowance": entitlement.allowance,
                "resource_class": entitlement.resource_class,
                "state": UNIT_MEASURED if is_measured else UNIT_UNMEASURED,
                "pressure": _pressure(entitlement, measured=is_measured),
                "measurement": _unit_measurement(entitlement) if is_measured else _unit_measurement(None),
                # The canonical per-unit projection, so a consumer that needs the
                # raw fields does not re-derive what this module already read.
                "canonical": entitlement.to_dict(),
            }
        )
    unsettled_facts = [
        {
            "slurm_job_id": str(record.get("slurm_job_id") or ""),
            "task_id": str(record.get("task_id") or ""),
            "unit": str(record.get("unit") or ""),
            "resource_count": record.get("resource_count"),
            "unknown_shape": record.get("resource_count") is None,
            "status": str(record.get("status") or ""),
            "started_at": _optional_seconds(record.get("started_at")),
        }
        for record in unsettled
    ]
    lifecycle_rows = task_store.list_data_lifecycle(user_id=user_id, limit=limit)
    lifecycle_counts: dict[str, int] = {}
    for record in lifecycle_rows:
        state = str(record.get("state") or "")
        lifecycle_counts[state] = lifecycle_counts.get(state, 0) + 1
    return {
        "subject": {"subject_type": envelope.subject_type, "subject_id": envelope.subject_id},
        "period": period,
        # The canonical envelope, unaltered: the same projection the existing
        # Admin entitlement route serves, so an operator comparing the two can
        # never find a field this facade rounded differently.
        "canonical_envelope": envelope.to_dict(),
        "units": units,
        "allocation_facts": {
            **_allocation_facts(unsettled),
            "unsettled_allocations": unsettled_facts,
            "basis": "unsettled_allocation_rows",
        },
        "class_breakdown": {
            "classes": _compute_class_breakdown(window, period=period),
            "basis": "ledger_window",
            "window_limit": limit,
        },
        "storage": _storage_block(envelope, int(user_id), task_store),
        "ledger": {
            "entries": rloan.normalize_ledger_rows(window),
            "window_limit": limit,
            "basis": "append_only_ledger",
        },
        "durable_data": {
            "tasks": [
                {
                    "task_id": str(record.get("task_id") or ""),
                    "state": str(record.get("state") or ""),
                    "logical_bytes": int(record.get("logical_bytes") or 0),
                    "accounted_bytes": int(record.get("accounted_bytes") or 0),
                    "purged_at": _optional_seconds(record.get("purged_at")),
                    "error": record.get("error") or None,
                }
                for record in lifecycle_rows
            ],
            "state_counts": dict(sorted(lifecycle_counts.items())),
            "window_limit": limit,
        },
    }


def _canonical_subject_ids(task_store: Any, *, limit: int) -> tuple[list[int], bool]:
    """The subjects this deployment has canonical *facts* for, and whether it was cut.

    A subject is known when a canonical store already names it: a Task it owns, or
    a data-lifecycle row that charges it.  A subject known only through policy — an
    allowance set for a user who has never run anything — is deliberately *not*
    listed: policy says what a subject may do, not that there is anything to
    report about what it did, and emitting a row per configured user would turn
    this read into a scan of the user table.

    The fan-out is bounded by :data:`MAX_ACTIVITY_SUBJECTS` and the bound is
    reported, so an activity list or a resource roll cannot become an unbounded
    per-subject scan.
    """
    ordered: list[int] = []
    seen: set[int] = set()

    def add(subject_id: Any) -> None:
        value = int(subject_id or 0)
        if value > 0 and value not in seen:
            seen.add(value)
            ordered.append(value)

    for record in task_store.list_data_lifecycle(limit=limit):
        add(record.get("subject_id"))
    for record in task_store.list_tasks():
        add(record.get("submitted_by_user_id"))
        if len(ordered) > MAX_ACTIVITY_SUBJECTS:
            break
    return ordered[:MAX_ACTIVITY_SUBJECTS], len(ordered) > MAX_ACTIVITY_SUBJECTS


def _resource_operations_fleet(task_store: Any, *, limit: int) -> dict[str, Any]:
    """A bounded roll over the subjects this deployment has real facts for.

    Each subject's usage is summed with the canonical ledger arithmetic over its
    own rows, so the roll reports the same facts the per-subject view does rather
    than an average of them.
    """
    subject_ids, truncated = _canonical_subject_ids(task_store, limit=limit)
    subjects: list[dict[str, Any]] = []
    for subject_id in subject_ids[:limit]:
        window = task_store.list_ledger(subject_id, limit=10)
        measured = _measured_units(window)
        if not measured:
            continue
        gpu = rloan.summarize_ledger(window, unit=rloan.UNIT_GPU_SECOND)
        cpu = rloan.summarize_ledger(window, unit=rloan.UNIT_CPU_CORE_SECOND)
        subjects.append(
            {
                "subject_id": subject_id,
                "used_gpu_seconds": gpu["used"],
                "used_cpu_core_seconds": cpu["used"],
                "logical_owned_bytes": task_store.logical_owned_bytes(subject_id),
                "units_measured": sorted(measured),
            }
        )
    return {
        "subjects": subjects,
        "window": {
            "subjects_considered": len(subject_ids),
            "subjects_returned": len(subjects),
            "subjects_ceiling": MAX_ACTIVITY_SUBJECTS,
            "limit": limit,
            "truncated": truncated,
        },
        "generated_at": time.time(),
    }


def resource_operations(
    task_store: Any,
    user_id: int | None = None,
    *,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Per-subject CPU/GPU allocation facts, entitlement pressure, and durable storage.

    With ``user_id`` this is one subject's full position: the canonical
    :class:`~revocompute.resource_ledger.ResourceEnvelope` (which materializes the
    period's base allowance exactly as the existing Admin entitlement route
    does), the append-only ledger window behind it, the per-resource-class report,
    the durable-storage block, and the unresolved allocation facts.

    Without ``user_id`` it is a bounded roll over the subjects that have recorded
    facts, each summed with the canonical ledger arithmetic.

    A unit the ledger window holds no facts for is reported ``unrecorded`` with
    ``None`` for every quantity: "this deployment has recorded nothing for this
    subject in this unit" and "this subject used zero" are different facts, and
    only the first describes a subject nobody has measured.
    """
    page = _bounded_limit(limit)
    if user_id is None:
        return {
            "scope": "deployment",
            "limit_ceiling": MAX_LIMIT,
            **_resource_operations_fleet(task_store, limit=page),
        }
    return {
        "scope": "subject",
        "limit_ceiling": MAX_LIMIT,
        "limit": page,
        **_resource_operations_for_user(task_store, int(user_id), limit=page),
    }


# ---------------------------------------------------------------------------
# Platform integrity: detection and navigation, never repair
# ---------------------------------------------------------------------------

#: How one drift record maps onto an operator's next look.  Detection and
#: navigation only: the target is where the canonical Task or Run view already
#: lives, so an anomaly is one link from the context that explains it, and
#: nothing here decides what to do about it.
_DRIFT_NAVIGATION: dict[str, str] = {
    "allocation_without_task": "runner_fleet",
    "terminal_task_unsettled_allocation": "task",
    "purged_with_owned_bytes": "task",
    "stale_purge": "task",
    "lifecycle_without_task": "task",
    "owned_bytes_unmeasurable": "task",
    "charged_bytes_missing_on_disk": "task",
    "filesystem_data_not_accounted": "task",
    "stale_reservation": "task",
    "queued_reservation_without_request": "task",
}


def _drift_view(drift: rloan.ReconciliationDrift) -> dict[str, Any]:
    return {
        "kind": drift.kind,
        "subject": drift.subject,
        "detail": drift.detail,
        "repairable": drift.repairable,
        "navigation": {"target": _DRIFT_NAVIGATION.get(drift.kind, "task"), "subject": drift.subject},
    }


def _subsystem(state: str, *, reason: str | None = None, detail: str | None = None) -> dict[str, Any]:
    return {"state": state, "reason": reason, "detail": detail}


def _readiness_block(host: Any, database: Any) -> dict[str, Any]:
    """Deployed Runner families' derived readiness, or an explicit "not evaluated".

    Without a host view this module cannot derive a verdict, and it says so.  It
    deliberately does not fall back to an empty fleet: an empty list is
    indistinguishable from "every family is fine" and would turn a missing
    argument into a clean bill of health.
    """
    if host is None:
        return _subsystem(
            rloan.MeasurementState.UNKNOWN.value,
            reason="runner_host_view_unavailable",
            detail="No deployment host view was supplied, so Runner readiness was not evaluated.",
        )
    try:
        before = {
            row["runner_family"]: row["readiness"]["status"]
            for row in fleet_view(host, database=database, user_id=None)
            if isinstance(row.get("readiness"), Mapping)
        }
    except Exception as exc:  # defensive: a control-plane read must not fail the report
        return _subsystem(
            rloan.MeasurementState.UNKNOWN.value,
            reason="runner_readiness_evaluation_failed",
            detail=str(exc),
        )
    not_ready = {family: status for family, status in before.items() if status != "READY"}
    return {
        "state": "measured",
        "families": before,
        "not_ready": not_ready,
        "navigation": {"target": "runner_fleet", "subject": None},
    }


def _activity_block(operator_jobs: Any, *, limit: int) -> dict[str, Any]:
    """Resolved Operator Job history, or "not evaluated" when no store was given."""
    if operator_jobs is None:
        return _subsystem(
            rloan.MeasurementState.UNKNOWN.value,
            reason="operator_job_store_unavailable",
            detail="No Operator Job store was supplied; operator history was not read.",
        )
    jobs = operator_jobs.list_jobs(limit=limit)
    unresolved = [job for job in jobs if str(job.get("status")) in {"QUEUED", "RUNNING", "CANCELLING"}]
    return {
        "state": "measured",
        "jobs": [
            {
                "job_id": job.get("job_id"),
                "action": job.get("action"),
                "runner_family": job.get("runner_family"),
                "status": job.get("status"),
                "failure_category": job.get("failure_category"),
                "actor_user_id": job.get("actor_user_id"),
                "created_at": _optional_seconds(job.get("created_at")),
                "finished_at": _optional_seconds(job.get("finished_at")),
            }
            for job in jobs
        ],
        "unresolved_jobs": [job.get("job_id") for job in unresolved],
        "window_limit": limit,
    }


def platform_integrity(
    task_store: Any,
    *,
    host: Any = None,
    database: Any = None,
    operator_jobs: Any = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Bounded detection-and-navigation report over canonical consistency facts.

    Four independent sources, each reported with its own state so a missing one
    is never read as healthy:

    ``drift``
        :func:`revocompute.resource_lifecycle.detect_drift` — the read-only
        consistency check across allocations, lifecycle rows, and reservations.
        It is called with no ``owned_paths`` measurement, because a filesystem
        crawl is not this module's job; the filesystem-vs-accounting checks are
        therefore *not run* here and a separate, explicitly-supplied measurement
        owns them.
    ``scheduler_evidence``
        the allocations still awaiting an authoritative elapsed duration, which
        is the same fact for "the scheduler has not answered yet" and "the
        answer was not obtained".  It is reported as an unknown quantity, never
        as zero settled.
    ``runner_readiness``
        the derived per-family verdict, when a host view is supplied.
    ``operator``
        resolved Operator Job history, when a job store is supplied.

    There is deliberately no aggregate "health score": a single number would
    collapse an unknown source, an unrepairable drift, and a stale verdict into
    one figure that is no longer navigation.  ``state`` says whether anything
    was *detected*, and every anomaly carries the subject an operator opens next.
    """
    page = _bounded_limit(limit)
    timestamp = time.time()
    drift = rlife.detect_drift(task_store, now=timestamp)
    unsettled = task_store.list_unsettled_allocations()
    unknown_shape = [row for row in unsettled if row.get("resource_count") is None]
    return {
        "checked_at": timestamp,
        "state": "drift_detected" if drift else "no_drift_detected",
        "drift": {
            "records": [_drift_view(item) for item in drift[:page]],
            "total": len(drift),
            "limit": page,
            "truncated": len(drift) > page,
            "kinds": sorted({item.kind for item in drift}),
            "basis": "resource_lifecycle.detect_drift",
            "repair": "none — detection and navigation only",
        },
        "scheduler_evidence": {
            "unsettled_allocations": len(unsettled),
            "unknown_shape_allocations": len(unknown_shape),
            "state": (
                rloan.MeasurementState.UNKNOWN.value if unsettled else rloan.MeasurementState.MEASURED.value
            ),
            "reason": "authoritative_elapsed_time_unavailable" if unsettled else None,
            "detail": (
                "These allocations consumed resources and have no authoritative elapsed duration "
                "yet, so their usage is a lower bound rather than a settled number."
                if unsettled
                else "Every recorded allocation has settled."
            ),
            "subjects": [
                {
                    "slurm_job_id": str(row.get("slurm_job_id") or ""),
                    "task_id": str(row.get("task_id") or ""),
                    "unit": str(row.get("unit") or ""),
                    "status": str(row.get("status") or ""),
                    "unknown_shape": row.get("resource_count") is None,
                }
                for row in unsettled[:page]
            ],
            "basis": "resource_allocations",
            "navigation": {"target": "task", "subject": None},
        },
        "runner_readiness": _readiness_block(host, database),
        "operator": _activity_block(operator_jobs, limit=page),
    }


# ---------------------------------------------------------------------------
# Admin activity: who changed what, over which window
# ---------------------------------------------------------------------------


def _policy_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "activity": "policy",
        "subject_id": int(row.get("subject_id") or 0),
        "actor_user_id": row.get("actor_user_id"),
        "operation": str(row.get("operation") or ""),
        "unit": str(row.get("unit") or ""),
        "resource_class": str(row.get("resource_class") or ""),
        "before": _json_or_none(row.get("before_json")),
        "after": _json_or_none(row.get("after_json")),
        "reason": row.get("reason"),
        "created_at": _optional_seconds(row.get("created_at")),
    }


def _policy_activity(task_store: Any, *, limit: int, since: float | None) -> dict[str, Any]:
    """Policy mutations, read per subject because the canonical reader is per subject.

    ``TaskDatabase.list_policy_audit`` takes one subject, so a whole-deployment
    activity list is a bounded fan-out over the subjects that already have
    canonical rows.  The fan-out shares :func:`_canonical_subject_ids`, so a policy
    list and a resource roll see the same subjects under the same ceiling; the
    bound is reported as truncated when it is cut, and ``since`` is applied here
    because a window is the caller's question, not a property of the stored rows.
    """
    subject_ids, truncated = _canonical_subject_ids(task_store, limit=limit)
    entries: list[dict[str, Any]] = []
    for subject_id in subject_ids:
        for row in task_store.list_policy_audit(subject_id, limit=limit):
            entry = _policy_entry(row)
            if since is not None and (entry["created_at"] is None or entry["created_at"] < since):
                continue
            entries.append(entry)
    entries.sort(key=lambda item: float(item.get("created_at") or 0.0), reverse=True)
    return {
        "entries": entries[:limit],
        "total": len(entries),
        "window": {
            "subjects_scanned": len(subject_ids),
            "subjects_ceiling": MAX_ACTIVITY_SUBJECTS,
            "truncated": truncated or len(entries) > limit,
            "limit": limit,
            "since": since,
        },
        "basis": "resource_policy_audit",
    }


def admin_activity(
    task_store: Any,
    *,
    limit: int = DEFAULT_LIMIT,
    since: float | None = None,
    operator_jobs: Any = None,
) -> dict[str, Any]:
    """Bounded Admin/operator audit activity: policy mutations and Operator Jobs.

    Two append-only histories, one list.  Policy mutations come from
    ``resource_policy_audit`` (the canonical record of who changed an allowance,
    with the before/after values and the reason); operator actions come from the
    Operator Job store's resolved history.  ``since`` bounds the policy side by
    timestamp; the operator side is bounded by ``limit`` because its reader
    already orders newest-first.

    The operator block reports "not evaluated" rather than an empty list when no
    store is supplied — an empty history and an unread one are different facts.
    """
    page = _bounded_limit(limit)
    timestamp = time.time()
    if since is not None:
        since = float(since)
    policy = _policy_activity(task_store, limit=page, since=since)
    operator = _activity_block(operator_jobs, limit=page)
    operator_entries = (
        [
            {
                "activity": "operator_job",
                "job_id": job["job_id"],
                "runner_family": job["runner_family"],
                "action": job["action"],
                "status": job["status"],
                "actor_user_id": job["actor_user_id"],
                "failure_category": job["failure_category"],
                "created_at": job["created_at"],
            }
            for job in operator["jobs"]
        ]
        if operator["state"] == "measured"
        else []
    )
    merged = sorted(
        [*policy["entries"], *operator_entries],
        key=lambda item: float(item.get("created_at") or 0.0),
        reverse=True,
    )
    return {
        "activity": merged[:page],
        "policy": policy,
        "operator": operator,
        "limit": page,
        "limit_ceiling": MAX_LIMIT,
        "since": since,
        "generated_at": timestamp,
    }


__all__ = [
    "AdminReportError",
    "MAX_LIMIT",
    "PLACEMENT_RECORDED",
    "PLACEMENT_UNREADABLE",
    "PLACEMENT_UNRECORDED",
    "UNIT_UNMEASURED",
    "admin_activity",
    "parse_limit",
    "placement_projection",
    "placement_projections",
    "platform_integrity",
    "resource_operations",
    "task_operations",
]
