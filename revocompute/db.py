# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""SQLite task tracker for compute jobs."""

from __future__ import annotations

import fcntl
import json
import logging
import math
import os
import re
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    create_engine,
    delete,
    desc,
    func,
    literal,
    or_,
    select,
    text,
    update,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, OperationalError

from revocompute import resource_ledger as rloan
from revocompute import resource_model as rm
from revocompute.operational_events import emit_event
from revocompute.schema_epoch import require_current_schema


DEFAULT_MONTHLY_GPU_SECONDS = 60_000

_MANIFEST_SHA256 = re.compile("[0-9a-f]{64}\\Z")


#: Default per-subject durable-storage ceiling, in logical bytes.  Soft: a
#: result that crosses it is preserved and only later admission is restricted.
DEFAULT_STORAGE_SOFT_LIMIT_BYTES = 100 * 1024**3

#: Tables whose legacy ``user_id`` column is replaced by the canonical
#: ``(subject_type, subject_id)`` pair.  The migration is additive and only
#: renames the column plus backfills the type; no quantity, kind, reason, or
#: timestamp is rewritten, so historical facts stay exactly as recorded.
_SUBJECT_TABLES = (
    "resource_ledger",
    "resource_allocations",
    "resource_policies",
    "data_lifecycle",
    "resource_policy_audit",
)

#: What makes one recorded resource observation the same event as another.
#: ``attempt`` and ``work_item`` are what keep a re-drained stdout log — REST
#: polls may re-read the runner's log — from appending duplicates, and the
#: measurements are included so two genuinely different readings of the same
#: item (a retry under a different fallback plan is a different ``plan_label``)
#: both survive.
RESOURCE_OBSERVATION_IDENTITY = (
    "task_id",
    "work_item",
    "attempt",
    "runner",
    "runtime_fingerprint",
    "outcome",
    "peak_reserved_mb",
    "baseline_mb",
    "plan_label",
)

_OBSERVATION_TEXT_COLUMNS = (
    "runner",
    "runner_version",
    "model_version",
    "runtime_fingerprint",
    "device_class",
    "vram_class",
    "outcome",
    "error_class",
    "quality",
    "plan_label",
    "task_id",
    "work_item",
)
_OBSERVATION_INT_COLUMNS = (
    "baseline_mb",
    "peak_allocated_mb",
    "peak_reserved_mb",
    "peak_process_mb",
    "available_mb",
    "attempt",
)
#: Newest rows kept per (runner, model_version, device_class).  The estimator
#: reads at most ``resource_observations.OBSERVATION_LIMIT`` rows for one
#: profile, so this is an order of magnitude more history than anything reads;
#: retention is a count rather than an age so it is deterministic for a chatty
#: runner and an idle one alike.  The cap is *stratified by device class*: a
#: homogeneous cluster churning rows for one common GPU must not evict the whole
#: history of a rarer class, which is the only evidence avoidance has for it.
RESOURCE_OBSERVATION_RETENTION = 5000


def _observation_device_classes(device: dict[str, Any]) -> tuple[str, str]:
    """Class keys for the stored device, computed by the estimator's own rule.

    A queryable copy of two :class:`resource_model.DeviceProfile` properties, so
    ``device_class``/``vram_class`` cannot drift from the estimator's grouping.
    The full device profile stays authoritative in ``device_profile_json``;
    ingest is on the execution path, so an unusable profile degrades to empty
    keys instead of raising.
    """
    try:
        profile = rm.DeviceProfile(
            vendor=str(device.get("vendor") or "nvidia"),
            model=str(device.get("model") or "unknown"),
            compute_capability=str(device.get("compute_capability") or ""),
            total_vram_mb=int(device.get("total_vram_mb") or 0),
        )
    except (TypeError, ValueError):
        return "", ""
    return profile.device_class, profile.vram_class


def _resource_observation_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project a runner observation onto the table's queryable columns.

    The full normalized JSON is stored alongside them, so the projection only
    needs to be good enough to select, filter, and dedupe on.
    """
    device = row.get("device") if isinstance(row.get("device"), dict) else {}
    features = row.get("features") if isinstance(row.get("features"), dict) else {}
    device_class, vram_class = _observation_device_classes(device)
    # The runner's wire vocabulary calls the model revision ``model_revision``;
    # the column name follows the resource-history schema (``model_version``),
    # so the projection maps between the two instead of storing a second copy.
    model_version = row.get("model_version") or row.get("model_revision") or ""
    # ``inf``/``nan`` in a memory field is meaningless, and an Integer column
    # cannot hold it at all: ``int(float('inf'))`` raises ``OverflowError``.
    # Rejecting non-finite numbers here keeps the projection total and keeps a
    # value the reader would turn into ``NaN`` out of the stored JSON.
    counts = {}
    for name in _OBSERVATION_INT_COLUMNS:
        value = row.get(name) or 0
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"resource observation {name} must be finite")
        counts[name] = max(0, int(value))
    runtime_seconds = float(row.get("runtime_seconds") or 0.0)
    if not math.isfinite(runtime_seconds):
        raise ValueError("resource observation runtime_seconds must be finite")
    values: dict[str, Any] = {
        **{name: str(row.get(name) or "")[:512] for name in _OBSERVATION_TEXT_COLUMNS},
        "model_version": str(model_version)[:512],
        **counts,
        "runtime_seconds": max(0.0, runtime_seconds),
        "device_class": device_class,
        "vram_class": vram_class,
        "device_profile_json": json.dumps(device, sort_keys=True),
        "feature_json": json.dumps(features, sort_keys=True),
        "observation_json": json.dumps(row, sort_keys=True),
    }
    return values


# How long one request may hold a Task-ID preparation claim before another
# request may take it over.  A claim lives only from the atomic acquire in the
# submit route to the ``pending`` row / ``celery_task_id`` that follows the
# filesystem preparation in the same request, so a live one is bounded by one
# request's own work.  The submit route refuses a body over 16 MiB, itself a
# ~2 s transfer, and the preparation copies the same bytes to disk, so 300 s is
# an order of magnitude of headroom; the ceiling to keep in mind is that a claim
# held past this window could be taken over mid-preparation.
PREPARATION_CLAIM_SECONDS = 300.0
# How long a claimed task may sit ``pending`` without being queued before the
# row is treated as abandoned.  The submit route dispatches immediately after it
# materializes, so this only bounds a request that died in that narrow gap.
PREPARATION_ABANDONED_SECONDS = 900.0


@dataclass(frozen=True)
class PreparationClaim:
    """The unambiguous outcome of trying to own one Task ID for preparation.

    Exactly one of these describes the acquire attempt:

    ``ACQUIRED``      this request now owns preparation of the ID; ``token``
                      must be presented to finish or release it.
    ``IN_PROGRESS``   another request holds a live preparation claim.
    ``ABANDONED``     the row's preparation claim lapsed without dispatch, and
                      this request has taken it over.
    ``DISPATCHED``    the row carries execution state, or a handle still owns a
                      possibly-live allocation.
    ``TERMINAL``      the row is settled (finished/failed/cancelled/cleanup
                      claim/deleted).
    ``UNOWNED``       a row with none of the above that can be re-prepared: a
                      task that failed while being prepared, or an active one
                      whose owning delivery died before it recorded anything.
    """

    outcome: str
    row: dict[str, Any] | None = None
    token: str | None = None

    def owned(self) -> bool:
        """Whether this request now owns preparation (and holds ``token``)."""
        return self.token is not None


class GPUCreditUnavailableError(RuntimeError):
    """Raised when a user may not start another GPU allocation."""


class GPUAuthorizationUnavailableError(RuntimeError):
    """Raised when current projected authorization denies a GPU allocation."""


class TaskIdReservedError(RuntimeError):
    """Raised when a write would overwrite a row whose Task ID is reserved.

    A terminal or claimed row still owns artifacts, a possibly-live allocation,
    or a resumable cleanup, and the Task ID is a pure function of the submitted
    content, so an identical resubmission re-derives the identical ID.
    Overwriting it in place would rewrite the row and let the submit path
    destroy and re-dispatch the state that row still owns.

    A Task ID being *prepared* is claimed through
    :meth:`TaskDatabase.claim_task_preparation` instead, which answers with the
    owning request rather than raising.
    """


class TaskDatabase:
    """Minimal SQLite-based task tracker for compute jobs."""

    DELETED_STATUSES = {"deleted:finshed", "deleted:cancel"}
    CLEANUP_STATUSES = {"cleaned:finished", "cleaned:cancel"}
    CLEANUP_CLAIM_STATUSES = {"deleting:finished", "deleting:cancel"}
    TERMINAL_STATUSES = DELETED_STATUSES | CLEANUP_STATUSES | CLEANUP_CLAIM_STATUSES | {"cancelled"}
    # Statuses for which no further transition is coming, including the settled
    # outcomes. Distinct from TERMINAL_STATUSES in both directions: it adds
    # finished/failed (which the runtime guard excludes because a task that has
    # not been finalized may still move), and it drops the deleting:* claim
    # statuses, which cleanup still advances to cleaned:*.
    STOP_POLLING_STATUSES = DELETED_STATUSES | CLEANUP_STATUSES | {"cancelled", "finished", "failed"}

    VALID_STATUSES = {
        "pending",
        "queued",
        "running",
        "finished",
        "failed",
        "cancelled",
        "deleting:finished",
        "deleting:cancel",
        "cleaned:finished",
        "cleaned:cancel",
        "deleted:finshed",
        "deleted:cancel",
    }

    def __init__(
        self,
        path: str,
        *,
        monthly_gpu_seconds: int = DEFAULT_MONTHLY_GPU_SECONDS,
        storage_soft_limit_bytes: int = DEFAULT_STORAGE_SOFT_LIMIT_BYTES,
    ):
        if monthly_gpu_seconds < 0:
            raise ValueError("monthly_gpu_seconds must be non-negative")
        if storage_soft_limit_bytes < 0:
            raise ValueError("storage_soft_limit_bytes must be non-negative")
        self.path = os.path.abspath(path)
        self._monthly_seconds = monthly_gpu_seconds
        self._storage_soft_limit = storage_soft_limit_bytes
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.path}",
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        self.metadata = MetaData()
        self.tasks_table = Table(
            "tasks",
            self.metadata,
            Column("md5sum", String(32), primary_key=True),
            Column("filename", String, nullable=False),
            Column("file_path", String, nullable=False),
            Column("uploaded_at", Float, nullable=False),
            Column("started_at", Float),
            Column("finished_at", Float),
            Column("walltime", Float),
            Column("status", String, nullable=False),
            Column("is_binary", Integer, nullable=False),
            Column("source_ip", String),
            Column("user_agent", String),
            Column("username", String),
            Column("local user", String, key="local_user"),
            Column("request_headers", Text),
            Column("run_stage", String),
            Column("error", Text),
            Column("celery_task_id", String),
            Column("task_type", String, nullable=False),
            Column("input_form", Text),
            Column("slurm_job_id", String),
            Column("container_id", String),
            Column("workflow_state", Text),
            Column("storage_key", String, nullable=False),
            Column("submitted_by_user_id", Integer, nullable=False),
            Column("artifact_provenance", Text, nullable=False, default="[]"),
        )
        Index("idx_tasks_uploaded_at", self.tasks_table.c.uploaded_at)
        Index("idx_tasks_submitter", self.tasks_table.c.submitted_by_user_id, self.tasks_table.c.uploaded_at)
        # Who currently owns preparation of a Task ID.  Separate from ``tasks``
        # because that primary key means "a task exists with this ID" — a claim
        # must not insert one, or the submit path's pre-check would answer the
        # request it is serving as an existing task.
        self.prep_claims_table = Table(
            "task_preparation_claims",
            self.metadata,
            Column("md5sum", String(32), primary_key=True),
            Column("token", String(32), nullable=False),
            Column("acquired_at", Float, nullable=False),
        )
        # One append-only ledger for every subject and unit.  Compute facts are
        # scoped to a UTC period and carry their resource class; durable storage
        # facts are ownership rather than consumption, so their period is empty.
        # There is deliberately no separate CPU or storage ledger: the ``unit``
        # and ``resource_class`` columns keep them apart without a second source
        # of truth.  Names retained from the GPU-credit era are aliases on the
        # table objects, not a second table.
        self.resource_ledger_table = Table(
            "resource_ledger",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("subject_type", String, nullable=False, default=rloan.SUBJECT_USER),
            Column("subject_id", Integer, nullable=False),
            Column("period", String(7), nullable=False, default=""),
            Column("kind", String, nullable=False),
            Column("unit", String, nullable=False),
            Column("resource_class", String, nullable=False, default=""),
            Column("quantity", Integer, nullable=False),
            Column("task_id", String(32)),
            Column("stage_id", String),
            Column("slurm_job_id", String),
            Column("actor_user_id", Integer),
            Column("reason", Text),
            Column("reason_code", String),
            Column("evidence_source", String, nullable=False, default=rloan.EvidenceSource.UNKNOWN.value),
            Column("idempotency_key", String, nullable=False, unique=True),
            Column("created_at", Float, nullable=False),
        )
        Index(
            "idx_resource_ledger_subject_unit",
            self.resource_ledger_table.c.subject_type,
            self.resource_ledger_table.c.subject_id,
            self.resource_ledger_table.c.unit,
            self.resource_ledger_table.c.id,
        )
        Index(
            "idx_resource_ledger_period",
            self.resource_ledger_table.c.subject_id,
            self.resource_ledger_table.c.period,
            self.resource_ledger_table.c.id,
        )
        Index("idx_resource_ledger_task", self.resource_ledger_table.c.task_id)
        # Policy is a current value, never a rewrite of history: a policy change
        # appends a ledger fact and updates this row.
        self.resource_policies_table = Table(
            "resource_policies",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("subject_type", String, nullable=False, default=rloan.SUBJECT_USER),
            Column("subject_id", Integer, nullable=False),
            Column("unit", String, nullable=False),
            Column("resource_class", String, nullable=False, default=""),
            Column("allowance", Integer, nullable=False, default=0),
            Column("updated_by_user_id", Integer),
            Column("updated_at", Float, nullable=False),
        )
        Index(
            "idx_resource_policies_subject",
            self.resource_policies_table.c.subject_type,
            self.resource_policies_table.c.subject_id,
            self.resource_policies_table.c.unit,
            self.resource_policies_table.c.resource_class,
            unique=True,
        )
        # Every allocation of a scarce resource, whatever its unit.  A row's
        # ``resource_count`` is what the scheduler allocated *in that unit's own
        # terms* — GPUs for ``gpu_second``, CPU cores for ``cpu_core_second`` —
        # so a historical A100 second is never collapsed into an opaque GPU
        # second and a CPU core-second is never a utilization figure.
        #
        # ``(slurm_job_id, unit)`` is the identity: one Slurm allocation is one
        # GPU fact *and one CPU fact*, because an allocation consumes both and
        # they are separate accounting units.  A CPU-only allocation is the GPU
        # row with a zero ``resource_count``, so "every Slurm allocation"
        # answers without a second table.
        #
        # ``resource_count`` is NULL for exactly one case: an allocation the
        # scheduler's own per-job output file proves happened but whose resource
        # shape no one recorded, because the job was killed between "allocated a
        # node" and its first statement.  NULL is "unknown", never a zero — a
        # zero would be the false claim that the job held no GPUs, which
        # settlement would then charge as no usage at all.  Such a row is marked
        # for review and is never settled to a number.
        self.resource_allocations_table = Table(
            "resource_allocations",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("subject_type", String, nullable=False, default=rloan.SUBJECT_USER),
            Column("subject_id", Integer, nullable=False),
            Column("task_id", String(32), nullable=False),
            Column("stage_id", String, nullable=False),
            Column("slurm_job_id", String, nullable=False),
            Column("unit", String, nullable=False),
            Column("resource_class", String, nullable=False, default=""),
            Column("resource_count", Integer, nullable=True),
            Column("started_at", Float, nullable=False),
            Column("finished_at", Float),
            Column("quantity", Integer),
            Column("status", String, nullable=False),
            # The grant decision, kept on the allocation fact itself.  ``NULL``
            # denial means this allocation was admitted; a value names why the
            # scientific command was refused.  It records the policy outcome
            # without ever erasing the scheduler fact — a denied allocation is
            # still an allocation and is still settled.
            Column("denial_reason", String),
            # The bounded vocabulary value for that denial (`compute_exhausted`,
            # `authorization_unavailable`, ...), separate from the free-form
            # reason: a caller acts on a comparable code, not on a message.
            Column("denial_code", String),
            # When the grant decision was made, or ``NULL`` while the allocation
            # is a bare observation no admission decision has considered yet.
            # It separates "recorded, not yet adjudicated" from "admitted", so an
            # observation written before a crash is adjudicated on the retry
            # rather than read as an admission nobody made.
            Column("adjudicated_at", Float),
            Column("evidence_source", String, nullable=False, default=rloan.EvidenceSource.ALLOCATION_LIFECYCLE.value),
            Column("ledger_entry_id", Integer),
        )
        Index(
            "idx_resource_allocations_job_unit",
            self.resource_allocations_table.c.slurm_job_id,
            self.resource_allocations_table.c.unit,
            unique=True,
        )
        Index(
            "idx_resource_allocations_task_stage",
            self.resource_allocations_table.c.task_id,
            self.resource_allocations_table.c.stage_id,
        )
        Index(
            "idx_resource_allocations_status",
            self.resource_allocations_table.c.status,
            self.resource_allocations_table.c.started_at,
        )
        Index(
            "idx_resource_allocations_subject",
            self.resource_allocations_table.c.subject_id,
            self.resource_allocations_table.c.unit,
        )
        # Admission reservations.  A reservation is a claim on entitlement a
        # submission has staked but not yet consumed, in one of two ownership
        # modes: ``held`` between the admission decision and the dispatch of the
        # Slurm request (reclaimable after a TTL, since a crash there is
        # recoverable), and ``queued`` from the moment that request exists
        # (scheduler-owned, released only by a canonical transition — never by a
        # wall-clock timeout, because a genuinely queued request may wait longer
        # than any bound and its entitlement must not be handed to a second
        # submission).
        self.resource_reservations_table = Table(
            "resource_reservations",
            self.metadata,
            Column("id", String(32), primary_key=True),
            Column("subject_type", String, nullable=False, default=rloan.SUBJECT_USER),
            Column("subject_id", Integer, nullable=False),
            Column("unit", String, nullable=False),
            Column("resource_class", String, nullable=False, default=""),
            Column("quantity", Integer, nullable=False),
            Column("task_id", String(32), nullable=False),
            Column("state", String, nullable=False),
            Column("reason_code", String),
            Column("created_at", Float, nullable=False),
            # The pre-dispatch TTL, and only that: ``None`` on a scheduler-owned
            # reservation, which has no wall-clock expiry at all.
            Column("expires_at", Float),
            Column("dispatched_at", Float),
            # The scheduler's own name for the request, written in the same
            # transaction that makes the reservation scheduler-owned.  A queued
            # reservation therefore always carries the identity that proves a
            # request can still exist, so no maintenance pass can read a missing
            # identity as "there is nothing to wait for" during the dispatch
            # window — the two facts are one row, not two writes.
            Column("scheduler_job_id", String),
            Column("released_at", Float),
        )
        # One live reservation per Task: a resubmission that already staked its
        # entitlement cannot take a second one, and the database, not a read,
        # says so.  Both ownership modes are "live" — the difference is who may
        # release them, not whether they are outstanding.
        Index(
            "idx_resource_reservations_live_task",
            self.resource_reservations_table.c.task_id,
            unique=True,
            sqlite_where=text("state IN ('held', 'queued')"),
        )
        Index(
            "idx_resource_reservations_state",
            self.resource_reservations_table.c.state,
            self.resource_reservations_table.c.expires_at,
        )
        # A wrapper-authored receipt: the earliest compute-node evidence that the
        # wrapper was running, written the instant the allocation exists.
        #
        # It is NOT a second accounting fact — it is a *claim* that a restart
        # folds into the canonical ``resource_allocations`` rows through the same
        # idempotent, ``slurm_job_id``-keyed observation the live path uses, and
        # the row is removed in the same transaction that makes the fact durable.
        # What it exists for is the case the database cannot cover on its own: a
        # Slurm allocation is created by the scheduler, not by a DB write, so a
        # worker that dies before its first write would otherwise lose a real
        # allocation entirely.  The receipt carries it across that boundary.
        self.resource_receipts_table = Table(
            "resource_receipts",
            self.metadata,
            Column("id", String(96), primary_key=True),
            Column("task_id", String(32), nullable=False),
            Column("stage_id", String, nullable=False, default=""),
            Column("slurm_job_id", String, nullable=False),
            # The wrapper's own clock stamp, kept as the run's start floor.
            Column("observed_at", Float, nullable=False),
            # The shape the wrapper was started with, taken from the scheduler's
            # own view (SLURM_CPUS_PER_TASK / SLURM_GPUS_ON_NODE), so recovery
            # needs no server-side policy lookup to reconstruct the allocation.
            Column("cpus", Integer, nullable=False, default=0),
            Column("gpus", Integer, nullable=False, default=0),
            Column("resource_class", String, nullable=False, default=""),
            Column("authority", String, nullable=False, default=rloan.SUBJECT_USER),
        )
        Index(
            "idx_resource_receipts_job",
            self.resource_receipts_table.c.slurm_job_id,
        )
        # Retention state of one Task's durable data.  Deliberately separate
        # from ``tasks.status``: a finished computation stays finished when its
        # data is later archived or purged.
        self.data_lifecycle_table = Table(
            "data_lifecycle",
            self.metadata,
            Column("task_id", String(32), primary_key=True),
            Column("subject_type", String, nullable=False, default=rloan.SUBJECT_USER),
            Column("subject_id", Integer, nullable=False),
            Column("state", String, nullable=False, default=rloan.DataLifecycleState.ACTIVE.value),
            Column("logical_bytes", Integer, nullable=False, default=0),
            Column("accounted_bytes", Integer, nullable=False, default=0),
            Column("charge_revision", Integer, nullable=False, default=0),
            Column("requested_by_user_id", Integer),
            Column("requested_at", Float),
            Column("claimed_at", Float),
            Column("purged_at", Float),
            Column("error", Text, nullable=False, default=""),
            Column("updated_at", Float, nullable=False),
        )
        Index(
            "idx_data_lifecycle_state",
            self.data_lifecycle_table.c.state,
            self.data_lifecycle_table.c.updated_at,
        )
        Index(
            "idx_data_lifecycle_subject",
            self.data_lifecycle_table.c.subject_id,
            self.data_lifecycle_table.c.state,
        )
        # Administrative policy/allowance mutations are auditable records with
        # actor, before/after, reason, and request correlation.  They are never
        # deletions of the facts they change.
        self.resource_policy_audit_table = Table(
            "resource_policy_audit",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("subject_type", String, nullable=False, default=rloan.SUBJECT_USER),
            Column("subject_id", Integer, nullable=False),
            Column("actor_user_id", Integer, nullable=False),
            Column("operation", String, nullable=False),
            Column("unit", String, nullable=False, default=""),
            Column("resource_class", String, nullable=False, default=""),
            Column("before_json", Text, nullable=False, default="{}"),
            Column("after_json", Text, nullable=False, default="{}"),
            Column("reason", Text),
            Column("request_id", String),
            Column("idempotency_key", String, nullable=False, unique=True),
            Column("created_at", Float, nullable=False),
        )
        Index(
            "idx_resource_policy_audit_subject",
            self.resource_policy_audit_table.c.subject_id,
            self.resource_policy_audit_table.c.id,
        )
        self.gpu_authorizations_table = Table(
            "gpu_authorizations",
            self.metadata,
            Column("user_id", Integer, primary_key=True),
            Column("account_enabled", Integer, nullable=False),
            Column("allow_gpu_use", Integer, nullable=False),
            Column("entitlements", Text, nullable=False),
            Column("updated_at", Float, nullable=False),
        )
        # Runner-reported execution observations.  A separate table because the
        # ``tasks`` schema is frozen: ``require_current_schema`` rejects a DB
        # whose tasks table lacks a declared column, so the only safe addition
        # is a new table.  ``attempt``/``work_item`` are part of the dedupe key
        # so a re-drained stdout log (REST polls re-read it) cannot append a
        # second copy of one attempt.
        self.resource_observations_table = Table(
            "resource_observations",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("runner", String, nullable=False),
            Column("runner_version", String, nullable=False, default=""),
            Column("model_version", String, nullable=False, default=""),
            Column("runtime_fingerprint", String, nullable=False, default=""),
            Column("device_class", String, nullable=False, default=""),
            Column("vram_class", String, nullable=False, default=""),
            Column("device_profile_json", Text, nullable=False, default="{}"),
            Column("feature_json", Text, nullable=False, default="{}"),
            Column("baseline_mb", Integer, nullable=False, default=0),
            Column("peak_allocated_mb", Integer, nullable=False, default=0),
            Column("peak_reserved_mb", Integer, nullable=False, default=0),
            Column("peak_process_mb", Integer, nullable=False, default=0),
            Column("available_mb", Integer, nullable=False, default=0),
            Column("runtime_seconds", Float, nullable=False, default=0.0),
            Column("outcome", String, nullable=False, default=""),
            Column("error_class", String, nullable=False, default=""),
            Column("quality", String, nullable=False, default=""),
            Column("plan_label", String, nullable=False, default=""),
            Column("task_id", String, nullable=False, default=""),
            Column("work_item", String, nullable=False, default=""),
            Column("attempt", Integer, nullable=False, default=0),
            Column("observation_json", Text, nullable=False, default="{}"),
            Column("created_at", Float, nullable=False),
        )
        # One attempt has one observation.  The unique index makes the dedupe a
        # database fact rather than a read-then-write race: every poll that
        # re-drains the same stdout line inserts nothing.
        Index(
            "idx_resource_observations_attempt",
            *(
                getattr(self.resource_observations_table.c, name)
                for name in RESOURCE_OBSERVATION_IDENTITY
            ),
            unique=True,
        )
        Index(
            "idx_resource_observations_runner_model",
            self.resource_observations_table.c.runner,
            self.resource_observations_table.c.model_version,
            self.resource_observations_table.c.id,
        )
        Index(
            "idx_resource_observations_runner_fingerprint",
            self.resource_observations_table.c.runner,
            self.resource_observations_table.c.runtime_fingerprint,
            self.resource_observations_table.c.id,
        )
        # Live per-item progress and the runner's task outcome, as reported on
        # stdout.  Deliberately NOT ``tasks.workflow_state``: that column is the
        # workflow engine's durable per-stage record, and a resumable workflow
        # reads it back to decide what to run next.  A runner signal has a
        # different meaning and lifetime, so sharing the column would make it
        # two facts at once and let a progress write corrupt a workflow resume.
        # There is deliberately no foreign key to ``tasks``: the id is reused by
        # an identical resubmission, so the row's lifetime is tied to the task's
        # and :meth:`delete_task` removes both together.
        self.task_progress_table = Table(
            "task_execution_progress",
            self.metadata,
            Column("task_id", String(32), primary_key=True),
            Column("progress_json", Text, nullable=False, default="{}"),
            Column("outcome", String, nullable=False, default=""),
            Column("updated_at", Float, nullable=False),
        )
        # The publication identity of a finalized result manifest, in canonical
        # server-owned state.  The result directory belongs to the runner's
        # Unix identity, so a digest recorded *inside* it would be written and
        # rewritten by the same principal that writes the manifest: a
        # post-finalization replacement could then supply its own size and
        # SHA-256 declarations and self-authorize a new publication.  This row
        # is the only record of what Core published that the Runner-writable
        # tree cannot rewrite, so it is what makes "the manifest on disk is
        # still the publication Core finalized" an answerable question.
        #
        # A separate table rather than columns on ``tasks`` for the same reason
        # as the tables above: ``require_current_schema`` rejects a database
        # whose ``tasks`` table lacks a declared column, so a fresh table is
        # the addition that cannot invalidate an existing deployment's row set.
        # No foreign key, for the reason recorded on ``task_progress_table``:
        # an identical resubmission reuses the id, so the row's lifetime is the
        # task's, and :meth:`delete_task` removes both together.
        self.result_publications_table = Table(
            "result_publications",
            self.metadata,
            Column("task_id", String(32), primary_key=True),
            Column("manifest_sha256", String(64), nullable=False),
            Column("manifest_size", Integer, nullable=False),
            Column("revision", Integer, nullable=False, default=1),
            Column("published_at", Float, nullable=False),
            # The logical-storage charge this publication owes, and the state of
            # that charge.
            #
            # A publication and its accounting are one fact with two effects, and
            # the write that anchors the manifest is the only server-owned moment
            # at which both the result's identity and its size are known: the
            # result tree belongs to the runner's Unix identity, so its size can
            # never be re-derived later from the tree itself.  Splitting the
            # charge into a second write leaves the window this column closes —
            # bytes published and anchored, the charge missing, and nothing
            # durable that says a charge is owed.
            #
            # ``charge_state = 'pending'`` is *not charged yet*, which is exactly
            # the case a reconciliation pass repairs; a successful charge records
            # the amount and the state ``charged``.  A charge the purge already
            # released is ``released`` and is never repaired: those bytes were
            # freed, and the lifecycle — not this column — decided that.
            Column("charge_bytes", Integer, nullable=True),
            Column("charge_state", String, nullable=False, server_default="pending"),
            Column("charged_at", Float, nullable=True),
        )
        self._initialize()

    def _initialize(self) -> None:
        with self.engine.begin() as conn:
            self._safe_apply_pragmas(conn)
            require_current_schema(
                conn,
                {"tasks": {column.name for column in self.tasks_table.columns}},
                database_name="task database",
                forbidden_columns={"tasks": {"scope_type", "scope_id"}},
            )
        # Every process of a multi-process deployment runs this startup pass at
        # once, so the whole pass is serialized on the database file itself: the
        # schema must be created, the legacy tables copied, and those tables
        # dropped as one exclusive unit.  SQLite transactions cannot give that —
        # ``BEGIN IMMEDIATE`` serializes writers but a peer's committed
        # ``DROP TABLE`` is still visible to a statement that has already been
        # parsed, and a peer's uncommitted DDL is not visible to a reader at all,
        # so one process can commit "resource_ledger exists" while another is
        # still creating it and then fail to resolve the name.  The file lock
        # makes the existence any process observes remain true for the whole
        # pass, which is the property every step here relies on.
        with self._startup_lock():
            with self.engine.begin() as conn:
                try:
                    self.metadata.create_all(conn, checkfirst=True)
                except OperationalError as exc:
                    # A peer that predates the startup lock — an older release
                    # still rolling out — can still race ``create_all``.  The
                    # loser observes an "already exists" error, which is benign.
                    if "already exists" not in str(exc).lower():
                        raise
                    logging.warning("TaskDatabase metadata already present, skipping creation")
                self._migrate_subject_columns(conn)
                self._migrate_resource_columns(conn)
            # The legacy copy normalizes idempotency keys in place, so it must
            # run before the append-only guards exist, and under the same lock
            # so nothing can re-create the legacy tables between the copy and
            # the drop.
            self._migrate_legacy_gpu_tables()
            with self.engine.begin() as conn:
                self._install_append_only_guards(conn)

    @contextmanager
    def _startup_lock(self):
        """Serialize the whole startup pass across processes on this database.

        The lock is a file ``fcntl.flock`` beside the database rather than a
        database lock: it is held for the duration of the pass, it is released
        by the kernel if the process dies, and it needs no schema of its own.  It
        guards a startup-only, short, finite section, so waiting is bounded and
        cannot deadlock against the database's own locks.
        """
        lock_path = f"{self.path}.startup.lock"
        directory = os.path.dirname(lock_path) or "."
        os.makedirs(directory, exist_ok=True)
        with open(lock_path, "a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _legacy_key(key: str, user_id: int) -> str:
        """Translate one pre-canonical ledger key into its canonical spelling.

        The rename is not cosmetic: the canonical writers look up their
        idempotency keys, so a copied row under the old spelling would make the
        canonical writer append a *second* monthly grant or a second usage fact
        for the same event.  Every old key shape is mapped here, and an
        unrecognised key keeps a stable prefixed form rather than colliding.
        """
        if key.startswith("monthly_grant:user:"):
            return key
        if key.startswith("monthly_grant:"):
            _, _, period = key.partition(":")
            _, _, period = period.partition(":")
            return f"monthly_grant:user:{user_id}:class:-:{period}"
        if key.startswith("usage:gpu_second:"):
            return key
        if key.startswith("usage:"):
            return f"usage:gpu_second:{key.split(':', 1)[1]}"
        if key.startswith("allowance_adjustment:user:"):
            return key
        if key.startswith("allowance_adjustment:"):
            return f"allowance_adjustment:user:{key.split(':', 1)[1]}"
        if key.startswith("admin_adjustment:user:"):
            return key
        if key.startswith("admin_adjustment:"):
            return f"admin_adjustment:user:{key.split(':', 1)[1]}"
        if key.startswith("admin_reset:user:"):
            return key
        if key.startswith("admin_reset:"):
            return f"admin_reset:user:{key.split(':', 1)[1]}"
        return f"legacy:{key}"

    def _migrate_resource_columns(self, conn) -> None:
        """Widen the reservation/allocations shape without rewriting history.

        Two additive changes from the released revision, each only ever
        *widening* a constraint so every recorded fact keeps its meaning:

        * ``resource_allocations`` identifies an allocation by
          ``(slurm_job_id, unit)`` instead of ``slurm_job_id`` alone, because one
          Slurm allocation now records both its GPU and its CPU core-second
          facts;
        * ``resource_reservations`` gains ``dispatched_at`` and nullable
          ``expires_at``, so a scheduler-owned commitment has no wall-clock
          expiry at all, and its live-reservation uniqueness covers both
          ownership modes.

        A third change widens ``resource_allocations.resource_count`` to nullable
        for a scheduler-log-only observation whose shape was never recorded.

        These are constraint changes SQLite cannot apply in place, so each table
        is rebuilt — rename, drop the superseded indexes, recreate in the current
        shape, copy every column unchanged, drop the old table — under the
        startup lock, in one transaction.  A database already carrying the
        widened shape is untouched, and no quantity, kind, timestamp, or reason
        is rewritten.
        """
        inspector = sa_inspect(conn)
        tables = set(inspector.get_table_names())
        if "resource_allocations" in tables:
            indexes = {index["name"] for index in inspector.get_indexes("resource_allocations")}
            columns = {
                column["name"]: bool(column["nullable"])
                for column in inspector.get_columns("resource_allocations")
            }
            if (
                "idx_resource_allocations_job_unit" not in indexes
                or "denial_reason" not in columns
                or "denial_code" not in columns
                or "adjudicated_at" not in columns
                # A row whose shape is unknown records NULL, which the released
                # NOT NULL column cannot hold.  Widening is the only migration a
                # recorded fact needs here: every existing count keeps its value.
                or not columns.get("resource_count", False)
            ):
                self._rebuild_table(conn, self.resource_allocations_table)
        if "result_publications" in tables:
            columns = {column["name"] for column in inspector.get_columns("result_publications")}
            if "charge_state" not in columns:
                # The charge state is the default for a publication that predates
                # this column: it was published, and whether it was charged is
                # exactly what reconciliation will now establish — so the
                # conservative answer is "pending", never "charged".
                conn.exec_driver_sql(
                    "ALTER TABLE result_publications "
                    "ADD COLUMN charge_bytes INTEGER DEFAULT NULL"
                )
                conn.exec_driver_sql(
                    "ALTER TABLE result_publications "
                    "ADD COLUMN charge_state VARCHAR NOT NULL DEFAULT 'pending'"
                )
                conn.exec_driver_sql(
                    "ALTER TABLE result_publications "
                    "ADD COLUMN charged_at FLOAT DEFAULT NULL"
                )
        if "resource_reservations" in tables:
            columns = {column["name"] for column in inspector.get_columns("resource_reservations")}
            indexes = {index["name"] for index in inspector.get_indexes("resource_reservations")}
            if (
                "dispatched_at" not in columns
                or "scheduler_job_id" not in columns
                or "idx_resource_reservations_live_task" not in indexes
            ):
                self._rebuild_table(conn, self.resource_reservations_table)

    @staticmethod
    def _rebuild_table(conn, table) -> None:
        """Recreate *table* in its current shape, copying every stored column.

        A column the old table has is carried verbatim — so a pre-dispatch hold
        keeps its ``expires_at`` TTL across the upgrade — and a column it does
        not have is new, so it backfills to ``NULL``: there is no recorded
        dispatch or release for a row written before those columns existed, and
        inventing one would be a fact the system never observed.  The old
        indexes drop with the renamed table, so the recreated ones cannot collide
        with a superseded definition of the same name.
        """
        existing = {column["name"] for column in sa_inspect(conn).get_columns(table.name)}
        legacy = f"{table.name}_legacy"
        for index in sa_inspect(conn).get_indexes(table.name):
            name = index["name"]
            if name.startswith("sqlite_autoindex"):
                continue  # an UNIQUE column constraint's index drops with its table
            conn.exec_driver_sql(f"DROP INDEX IF EXISTS {name}")
        conn.exec_driver_sql(f"ALTER TABLE {table.name} RENAME TO {legacy}")
        table.create(conn, checkfirst=True)
        new_names = [column.name for column in table.columns]
        targets = ", ".join(new_names)
        sources = ", ".join(name if name in existing else "NULL" for name in new_names)
        conn.exec_driver_sql(f"INSERT INTO {table.name} ({targets}) SELECT {sources} FROM {legacy}")
        conn.exec_driver_sql(f"DROP TABLE {legacy}")

    def _migrate_legacy_gpu_tables(self) -> None:
        """Copy pre-canonical GPU history into the canonical resource tables.

        Bounded and history-preserving: every recorded GPU-second fact moves to
        ``resource_ledger`` as a ``gpu_second`` row, every allocation to
        ``resource_allocations``, and every per-user allowance to
        ``resource_policies``.  Quantities, kinds, actors, reasons, and
        timestamps are copied unchanged — only the subject pair, the unit, and
        the idempotency-key spelling are normalized — so a policy change still
        never rewrites the past.  The legacy tables are dropped only after the
        copy, so an interrupted migration is simply retried on the next start.

        Runs inside :meth:`_startup_lock`, which is what makes "the legacy tables
        are present" a stable observation for the whole copy: a peer's committed
        ``DROP TABLE`` cannot interleave, and a peer's half-created destination
        table cannot be observed as finished.  One transaction then makes the
        copy itself atomic, so a failure leaves the legacy tables in place and
        the next start retries.
        """
        with self.engine.begin() as conn:
            self._copy_legacy_gpu_tables(conn)

    def _copy_legacy_gpu_tables(self, conn) -> None:
        inspector = sa_inspect(conn)
        tables = set(inspector.get_table_names())
        if "gpu_credit_ledger" in tables:
            conn.exec_driver_sql(
                "INSERT INTO resource_ledger "
                "(id, subject_type, subject_id, period, kind, unit, resource_class, quantity, "
                " task_id, stage_id, slurm_job_id, actor_user_id, reason, reason_code, "
                " evidence_source, idempotency_key, created_at) "
                "SELECT id, 'user', user_id, period, kind, 'gpu_second', '', gpu_seconds, "
                " task_id, stage_id, slurm_job_id, actor_user_id, reason, ?, "
                " CASE WHEN kind = 'usage' THEN 'allocation_lifecycle' ELSE 'policy' END, "
                " idempotency_key, created_at FROM gpu_credit_ledger",
                (rloan.LedgerReason.MIGRATED.value,),
            )
            rows = conn.exec_driver_sql(
                "SELECT id, subject_id, idempotency_key FROM resource_ledger WHERE reason_code = ?",
                (rloan.LedgerReason.MIGRATED.value,),
            ).all()
            for row_id, user_id, key in rows:
                conn.exec_driver_sql(
                    "UPDATE resource_ledger SET idempotency_key = ? WHERE id = ?",
                    (self._legacy_key(str(key), int(user_id)), int(row_id)),
                )
            conn.exec_driver_sql("DROP TABLE gpu_credit_ledger")
        if "gpu_allocations" in tables:
            conn.exec_driver_sql(
                "INSERT INTO resource_allocations "
                "(id, subject_type, subject_id, task_id, stage_id, slurm_job_id, unit, "
                " resource_class, resource_count, started_at, finished_at, quantity, status, "
                " evidence_source, ledger_entry_id) "
                "SELECT id, 'user', user_id, task_id, stage_id, slurm_job_id, 'gpu_second', "
                " '', gpu_count, started_at, finished_at, gpu_seconds, status, "
                "'allocation_lifecycle', ledger_entry_id FROM gpu_allocations"
            )
            conn.exec_driver_sql("DROP TABLE gpu_allocations")
        if "gpu_credit_policies" in tables:
            conn.exec_driver_sql(
                "INSERT INTO resource_policies "
                "(subject_type, subject_id, unit, resource_class, allowance, "
                " updated_by_user_id, updated_at) "
                "SELECT 'user', user_id, 'gpu_second', '', monthly_gpu_seconds, "
                " updated_by_user_id, updated_at FROM gpu_credit_policies"
            )
            conn.exec_driver_sql("DROP TABLE gpu_credit_policies")

    @staticmethod
    def _migrate_subject_columns(conn) -> None:
        """Rename legacy per-table ``user_id`` columns to the canonical subject.

        A pre-existing GPU-credit database holds real usage history.  Rewriting
        or discarding it would violate "an administrative change never rewrites
        the past", so the migration is a rename plus a backfill of the subject
        type: every stored quantity, kind, reason, actor, and timestamp is left
        exactly as recorded.  A database that already carries the canonical
        columns is untouched, and one without the legacy name is simply created
        fresh by ``create_all``.
        """
        inspector = sa_inspect(conn)
        existing_tables = set(inspector.get_table_names())
        for table in _SUBJECT_TABLES:
            if table not in existing_tables:
                continue
            columns = {column["name"] for column in inspector.get_columns(table)}
            if "subject_id" not in columns and "user_id" in columns:
                conn.exec_driver_sql(f"ALTER TABLE {table} RENAME COLUMN user_id TO subject_id")
                columns = (columns - {"user_id"}) | {"subject_id"}
            if "subject_type" not in columns:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN subject_type VARCHAR NOT NULL DEFAULT '{rloan.SUBJECT_USER}'"
                )
            if "subject_id" in columns:
                conn.exec_driver_sql(
                    f"UPDATE {table} SET subject_type = '{rloan.SUBJECT_USER}' WHERE subject_type IS NULL OR subject_type = ''"
                )

    @staticmethod
    def _install_append_only_guards(conn) -> None:
        """Resource facts are append-only: no UPDATE and no DELETE, ever."""
        for operation in ("UPDATE", "DELETE"):
            trigger = f"prevent_resource_ledger_{operation.lower()}"
            conn.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {operation} ON resource_ledger "
                "BEGIN SELECT RAISE(ABORT, 'resource ledger is append-only'); END"
            )

    @staticmethod
    def _safe_apply_pragmas(conn) -> None:
        conn.exec_driver_sql("PRAGMA busy_timeout=30000;")
        # During dockerized server tests, concurrent web/worker startup can briefly
        # contend on the same SQLite file. Retrying PRAGMA setup avoids process
        # exit on transient lock without changing DB semantics.
        for attempt in range(3):
            try:
                conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
                conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
                return
            except OperationalError as exc:
                if "database is locked" not in str(exc).lower():
                    raise
                if attempt == 2:
                    logging.warning(
                        "SQLite pragma initialization is locked; proceeding with default pragmas for this process."
                    )
                    return
                time.sleep(0.2 * (attempt + 1))

    @staticmethod
    def _normalize_task_row(row: dict) -> dict:
        normalized = dict(row)
        if "local user" in normalized and "local_user" not in normalized:
            normalized["local_user"] = normalized["local user"]
        return normalized

    def _ensure_status(self, status: str) -> None:
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid task status {status}")

    @classmethod
    def _is_deleted_status(cls, status: Any) -> bool:
        return str(status or "").strip().lower() in cls.DELETED_STATUSES

    def upsert_task(self, task_id: str | None = None, *, refuse_reserved: bool = False, **fields) -> None:
        """Write one task row, named or derived.

        Callers that *name* an ID — a live-test fixture, a re-seed — pass a
        complete row.  The submit path *derives* the ID and passes
        ``refuse_reserved=True`` while holding the preparation claim (see
        :meth:`claim_task_preparation`): that claim is what makes the ID this
        request's to write, and the guard below is what keeps a row that
        appeared in the meantime — a named write, a re-seed — intact.
        Ownership is never inferred from a row read earlier in the request.
        """
        supplied_id = fields.pop("md5sum", None)
        if task_id is not None and supplied_id is not None and task_id != supplied_id:
            raise ValueError("Conflicting task ids")
        md5sum = task_id or supplied_id
        if not md5sum:
            raise ValueError("Task id is required")
        if not fields:
            return
        status = fields.get("status")
        if status:
            self._ensure_status(status)
        # A row that is terminal or holds a cleanup claim still owns artifacts,
        # a possibly-live allocation, or a resumable cleanup, and the Task ID is
        # a pure function of the submitted content — so an identical
        # resubmission re-derives the identical ID.  Overwriting the row whose
        # ID that is would destroy and re-dispatch the state it still owns.
        #
        # ``refuse_reserved=True`` runs the write through a guarded UPDATE
        # inside one transaction, so the refusal is atomic against a concurrent
        # status change.  (A SELECT-then-INSERT would not be — SQLite's deferred
        # BEGIN takes no write lock until the INSERT.  A ``WHERE`` on the
        # upsert's DO UPDATE clause does not work either: SQLite evaluates the
        # INSERT arm's NOT NULL constraints before resolving the conflict, and
        # these callers pass a partial row.)
        if refuse_reserved:
            # A row that still carries a resource handle owns an allocation the
            # scheduler may not have stopped, even when its status is not
            # terminal: orphan recovery records ``failed`` *without* confirming
            # cancellation, leaving ``slurm_job_id`` set on a job that may still
            # be running.
            guard = and_(
                self.tasks_table.c.md5sum == md5sum,
                self.tasks_table.c.status.notin_(tuple(self.TERMINAL_STATUSES)),
                self.tasks_table.c.slurm_job_id.is_(None),
                self.tasks_table.c.container_id.is_(None),
            )
            with self.engine.begin() as conn:
                if conn.execute(update(self.tasks_table).where(guard).values(**fields)).rowcount == 1:
                    return
                if conn.execute(select(self.tasks_table.c.md5sum).where(self.tasks_table.c.md5sum == md5sum)).first():
                    raise TaskIdReservedError(f"Task id {md5sum} is reserved by a terminal or claimed task")
                # The row does not exist yet.  ``do_nothing`` turns a concurrent
                # create between the SELECT and this INSERT into a 0-rowcount
                # answer rather than an IntegrityError surfacing as a 500.
                created = sqlite_insert(self.tasks_table).values(md5sum=md5sum, **fields).on_conflict_do_nothing()
                if conn.execute(created).rowcount != 1:
                    raise TaskIdReservedError(f"Task id {md5sum} was created concurrently")
            return
        stmt = sqlite_insert(self.tasks_table).values(md5sum=md5sum, **fields)
        stmt = stmt.on_conflict_do_update(
            index_elements=[self.tasks_table.c.md5sum],
            set_={col: getattr(stmt.excluded, col) for col in fields},
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def claim_task_preparation(
        self,
        md5sum: str,
        *,
        now: float | None = None,
        lease_seconds: float = PREPARATION_CLAIM_SECONDS,
        abandoned_seconds: float = PREPARATION_ABANDONED_SECONDS,
    ) -> PreparationClaim:
        """Atomically try to own one Task ID for preparation.

        The claim row is inserted with a conditional upsert: the INSERT arm
        always wins an absent row, and the DO UPDATE arm carries
        ``WHERE acquired_at <= now - lease_seconds``, so exactly one of two
        concurrent first submissions inserts and the other updates nothing and
        gets a 0-rowcount.  No earlier read takes part in ownership.

        ``acquired_at`` is the caller's clock, which is authoritative in the
        sense that every *decision on the row* reads it back: the guard
        compares two values the same process family wrote, and a leaked claim
        is reclaimed on a later clock, never on a stale one.

        What the claimed task row says then classifies and disposes the
        outcome: ``ACQUIRED`` for a row that is awaiting preparation (absent,
        abandoned, or unowned), ``DISPATCHED`` for one that carries dispatch
        state or a resource handle, ``IN_PROGRESS`` for one another request is
        actively working, ``TERMINAL`` for a settled row.  Every branch that
        does not acquire drops the claim it just took, in the same transaction,
        so a losing request leaves nothing behind.
        """
        now = time.time() if now is None else now
        token = secrets.token_hex(16)
        acquire = sqlite_insert(self.prep_claims_table).values(md5sum=md5sum, token=token, acquired_at=now)
        acquire = acquire.on_conflict_do_update(
            index_elements=[self.prep_claims_table.c.md5sum],
            set_={"token": acquire.excluded.token, "acquired_at": acquire.excluded.acquired_at},
            where=self.prep_claims_table.c.acquired_at <= now - lease_seconds,
        )
        with self.engine.begin() as conn:
            claimed = conn.execute(acquire).rowcount == 1
            row = conn.execute(select(self.tasks_table).where(self.tasks_table.c.md5sum == md5sum)).mappings().first()
            if not claimed:
                return PreparationClaim("IN_PROGRESS", self._normalize_task_row(row) if row else None)
            if row is not None:
                row = self._normalize_task_row(row)
                if row.get("slurm_job_id") or row.get("container_id"):
                    self._release_preparation_claim(conn, md5sum, token)
                    return PreparationClaim("DISPATCHED", row)
                if row["status"] == "pending":
                    if row.get("celery_task_id"):
                        self._release_preparation_claim(conn, md5sum, token)
                        return PreparationClaim("DISPATCHED", row)
                    if now - float(row.get("uploaded_at") or now) < abandoned_seconds:
                        self._release_preparation_claim(conn, md5sum, token)
                        return PreparationClaim("IN_PROGRESS", row)
                    # Old enough that its request cannot still be dispatching it,
                    # and it never got dispatch state: the claim lapsed before
                    # dispatch, so re-preparing it destroys nothing live.  The
                    # decision is safe without a re-check because taking the
                    # claim wrote the row and so holds SQLite's write lock for
                    # the rest of this transaction.  The row is then re-prepared
                    # from scratch, so any runner progress it once reported goes
                    # with it: ``pending`` means "not yet executed", and a
                    # surviving ``PARTIAL_SUCCESS`` row would be read back as
                    # this attempt's progress.
                    conn.execute(self.task_progress_table.delete().where(self.task_progress_table.c.task_id == md5sum))
                    return PreparationClaim("ABANDONED", row, token)
                if row["status"] == "queued":
                    # A queued row is owned by whatever path queued it: either
                    # actively dispatching or already dispatched.  Re-preparing
                    # it would wipe the snapshot a live allocation is reading,
                    # so it is never recovered here — the resubmission answers
                    # with the queued row.
                    self._release_preparation_claim(conn, md5sum, token)
                    return PreparationClaim(
                        "DISPATCHED" if row.get("celery_task_id") else "IN_PROGRESS", row
                    )
                if row["status"] in self.TERMINAL_STATUSES:
                    self._release_preparation_claim(conn, md5sum, token)
                    return PreparationClaim("TERMINAL", row)
                # Active, but with no dispatch state and no resource handle: a
                # task whose owning delivery died.  Re-preparing it destroys
                # nothing a live allocation is reading, so it is owned and
                # re-prepared like an abandoned row (whose stale progress row
                # is cleared for the same reason).
                conn.execute(self.task_progress_table.delete().where(self.task_progress_table.c.task_id == md5sum))
                return PreparationClaim("UNOWNED", row, token)
            return PreparationClaim("ACQUIRED", None, token)

    def _release_preparation_claim(self, conn, md5sum: str, token: str) -> None:
        """Drop this request's claim, within the caller's transaction.

        Token-guarded, so releasing can never drop a claim another request has
        since acquired (a takeover after this one lapsed).
        """
        conn.execute(
            delete(self.prep_claims_table).where(
                self.prep_claims_table.c.md5sum == md5sum,
                self.prep_claims_table.c.token == token,
            )
        )

    def release_task_preparation(self, md5sum: str, *, token: str) -> None:
        """Drop one preparation claim this request still holds."""
        with self.engine.begin() as conn:
            self._release_preparation_claim(conn, md5sum, token)

    def update_task(self, md5sum: str, **fields) -> bool:
        if not fields:
            return False
        status = fields.get("status")
        if status:
            self._ensure_status(status)
        stmt = update(self.tasks_table).where(self.tasks_table.c.md5sum == md5sum).values(**fields)
        # Terminal tasks (deleted / cancelled) must stay terminal.
        # Ignore late worker writes (running/finished/run_stage, etc.)
        # that would otherwise resurrect tasks after user deletion or
        # cancellation.
        if status is None or (not self._is_deleted_status(status)):
            stmt = stmt.where(self.tasks_table.c.status.notin_(tuple(self.TERMINAL_STATUSES)))
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def claim_task_recovery(self, md5sum: str, *, expected_status: str) -> bool:
        """Atomically move one orphaned active task out of recovery scans."""
        if expected_status not in {"queued", "running"}:
            return False
        stmt = (
            update(self.tasks_table)
            .where(
                self.tasks_table.c.md5sum == md5sum,
                self.tasks_table.c.status == expected_status,
            )
            .values(status="pending")
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def claim_task_execution(self, md5sum: str) -> bool:
        """Atomically claim one not-yet-started task for a single execution.

        A ``pending`` row is claimable, and the claim moves it to ``queued`` in
        the same statement, so of every dispatch of one task id exactly one wins
        and owns that task's single allocation.  Entering a claimed row would
        re-prepare (and wipe) the running snapshot and launch a second
        allocation.

        A ``queued`` row with no execution record — no ``celery_task_id``, no
        ``slurm_job_id`` and no ``started_at`` — is re-claimable: that is a task
        whose owning delivery died before it began, so a re-dispatch is the only
        way it can ever run.  The recovery scan reports such a row as lost
        rather than re-enqueuing it, and the submit route answers a repeat
        submission of the same content as already-queued, so without this the
        row would sit in ``queued`` forever.  The status predicate stays the
        mutex: only one claim can win, so a re-dispatch racing the live runner
        still loses.
        """
        stmt = (
            update(self.tasks_table)
            .where(
                self.tasks_table.c.md5sum == md5sum,
                or_(
                    self.tasks_table.c.status == "pending",
                    and_(
                        self.tasks_table.c.status == "queued",
                        self.tasks_table.c.celery_task_id.is_(None),
                        self.tasks_table.c.slurm_job_id.is_(None),
                        self.tasks_table.c.started_at.is_(None),
                    ),
                ),
            )
            .values(status="queued")
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def claim_task_cancellation(self, md5sum: str, **fields) -> bool:
        """Atomically cancel a task only while it remains active."""
        stmt = (
            update(self.tasks_table)
            .where(
                self.tasks_table.c.md5sum == md5sum,
                self.tasks_table.c.status.in_(("pending", "queued", "running")),
            )
            .values(status="cancelled", **fields)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def claim_task_cleanup(
        self,
        md5sum: str,
        *,
        expected_status: str,
        expected_finished_at: float,
        claim_status: str,
    ) -> bool:
        """Atomically claim one unchanged terminal task for artifact deletion."""
        if claim_status not in self.CLEANUP_CLAIM_STATUSES:
            raise ValueError(f"Invalid cleanup claim status {claim_status}")
        stmt = (
            update(self.tasks_table)
            .where(
                self.tasks_table.c.md5sum == md5sum,
                self.tasks_table.c.status == expected_status,
                self.tasks_table.c.finished_at == expected_finished_at,
            )
            .values(status=claim_status, celery_task_id=None)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def complete_task_cleanup(self, md5sum: str, *, claim_status: str, cleaned_status: str, **fields) -> bool:
        """Finish a claimed cleanup without overwriting a replacement task."""
        if claim_status not in self.CLEANUP_CLAIM_STATUSES:
            raise ValueError(f"Invalid cleanup claim status {claim_status}")
        if cleaned_status not in self.CLEANUP_STATUSES | self.DELETED_STATUSES:
            raise ValueError(f"Invalid cleaned status {cleaned_status}")
        stmt = (
            update(self.tasks_table)
            .where(
                self.tasks_table.c.md5sum == md5sum,
                self.tasks_table.c.status == claim_status,
            )
            .values(status=cleaned_status, celery_task_id=None, **fields)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def get_task(self, md5sum: str) -> dict | None:
        stmt = select(self.tasks_table).where(self.tasks_table.c.md5sum == md5sum)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        return self._normalize_task_row(row) if row else None

    def list_tasks(self) -> list[dict]:
        stmt = select(self.tasks_table).order_by(desc(self.tasks_table.c.uploaded_at))
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [self._normalize_task_row(row) for row in rows]

    def count_user_active_tasks(self, user_id: int) -> int:
        """Count pending, queued, and running tasks for a user."""
        stmt = (
            select(func.count())
            .select_from(self.tasks_table)
            .where(
                self.tasks_table.c.submitted_by_user_id == user_id,
                self.tasks_table.c.status.in_(["pending", "queued", "running"]),
            )
        )
        with self.engine.connect() as conn:
            return conn.execute(stmt).scalar() or 0

    def project_gpu_authorization(
        self,
        user_id: int,
        *,
        account_enabled: bool,
        allow_gpu_use: bool,
        entitlements: dict[str, float | None],
        updated_at: float | None = None,
    ) -> None:
        """Publish auth-owned GPU eligibility for worker-side final checks."""
        stmt = sqlite_insert(self.gpu_authorizations_table).values(
            user_id=user_id,
            account_enabled=int(account_enabled),
            allow_gpu_use=int(allow_gpu_use),
            entitlements=json.dumps(entitlements, sort_keys=True, separators=(",", ":")),
            updated_at=time.time() if updated_at is None else updated_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[self.gpu_authorizations_table.c.user_id],
            set_={
                "account_enabled": stmt.excluded.account_enabled,
                "allow_gpu_use": stmt.excluded.allow_gpu_use,
                "entitlements": stmt.excluded.entitlements,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def deny_gpu_authorization(self, user_id: int) -> None:
        """Fail closed before an auth-side revoke, disable, or deletion."""
        self.project_gpu_authorization(
            user_id,
            account_enabled=False,
            allow_gpu_use=False,
            entitlements={},
        )

    def require_gpu_authorization(
        self,
        user_id: int,
        *,
        required_entitlements: tuple[str, ...] = (),
        at: float | None = None,
    ) -> None:
        """Require a current projected permission at GPU allocation time."""
        with self.engine.connect() as conn:
            self._require_gpu_authorization(conn, user_id, required_entitlements, at)

    def _require_gpu_authorization(
        self,
        conn,
        user_id: int,
        required_entitlements: tuple[str, ...],
        at: float | None,
    ) -> None:
        row = conn.execute(
            select(self.gpu_authorizations_table).where(
                self.gpu_authorizations_table.c.user_id == user_id
            )
        ).mappings().one_or_none()
        if row is None or not row["account_enabled"] or not row["allow_gpu_use"]:
            raise GPUAuthorizationUnavailableError("GPU access is not currently authorized")
        effective_at = time.time() if at is None else at
        try:
            entitlements = json.loads(row["entitlements"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise GPUAuthorizationUnavailableError("GPU authorization projection is invalid") from exc
        if not isinstance(entitlements, dict):
            raise GPUAuthorizationUnavailableError("GPU authorization projection is invalid")
        for entitlement in required_entitlements:
            if entitlement not in entitlements:
                raise GPUAuthorizationUnavailableError("Required Runner entitlement is unavailable")
            expires_at = entitlements[entitlement]
            if expires_at is not None and float(expires_at) <= effective_at:
                raise GPUAuthorizationUnavailableError("Required Runner entitlement has expired")

    def delete_task(self, md5sum: str) -> None:
        """Remove one task row and the per-task rows that describe it.

        One operation, not two: the task id is derived from the submitted
        content, so a later identical submission reuses the id, and an orphaned
        progress row would then surface as its progress.  Observations go with
        it for the same reason and one sharper one: the dedupe identity includes
        ``task_id``, so a surviving row from the deleted attempt would silently
        suppress the re-submitted attempt's identical first row.
        """
        with self.engine.begin() as conn:
            conn.execute(self.tasks_table.delete().where(self.tasks_table.c.md5sum == md5sum))
            conn.execute(self.task_progress_table.delete().where(self.task_progress_table.c.task_id == md5sum))
            conn.execute(
                self.result_publications_table.delete().where(
                    self.result_publications_table.c.task_id == md5sum
                )
            )
            conn.execute(
                self.resource_observations_table.delete().where(
                    self.resource_observations_table.c.task_id == md5sum
                )
            )

    @staticmethod
    def _gpu_period(at: float | None = None) -> str:
        return datetime.fromtimestamp(
            time.time() if at is None else at, timezone.utc
        ).strftime("%Y-%m")

    def _period_for_unit(self, unit: str, at: float) -> str:
        """The period a settled fact belongs to: a UTC month, or none at all.

        Consumption units are charged against the month they occurred in;
        durable ownership spans every period and therefore has no period.
        """
        return self._gpu_period(at) if rloan.periods_for_unit(unit) else ""

    def _ensure_monthly_grant(
        self, conn, user_id: int, period: str, resource_class: str, created_at: float
    ) -> None:
        """Append the period's base allowance once, from current policy."""
        allowance = conn.execute(
            select(self.resource_policies_table.c.allowance).where(
                self.resource_policies_table.c.subject_type == rloan.SUBJECT_USER,
                self.resource_policies_table.c.subject_id == user_id,
                self.resource_policies_table.c.unit == rloan.UNIT_GPU_SECOND,
                self.resource_policies_table.c.resource_class == resource_class,
            )
        ).scalar_one_or_none()
        stmt = sqlite_insert(self.resource_ledger_table).values(
            subject_type=rloan.SUBJECT_USER,
            subject_id=user_id,
            period=period,
            kind=rloan.LedgerKind.MONTHLY_GRANT.value,
            unit=rloan.UNIT_GPU_SECOND,
            resource_class=resource_class,
            quantity=self._monthly_seconds if allowance is None else int(allowance),
            task_id=None,
            stage_id=None,
            slurm_job_id=None,
            actor_user_id=None,
            reason="UTC calendar-month allowance",
            reason_code=rloan.LedgerReason.PERIOD_GRANT.value,
            evidence_source=rloan.EvidenceSource.POLICY.value,
            idempotency_key=f"monthly_grant:user:{user_id}:class:{resource_class or '-'}:{period}",
            created_at=created_at,
        )
        conn.execute(
            stmt.on_conflict_do_nothing(
                index_elements=[self.resource_ledger_table.c.idempotency_key]
            )
        )

    # -- Canonical accounting, policy, and admission -------------------------
    #
    # Everything below derives its answer from append-only ledger facts plus
    # the live reservation table.  Nothing is cached and nothing is rewritten:
    # a policy change appends a new fact, and an administrative correction is
    # an ``admin_adjustment``/``admin_reset`` entry, never a deletion.

    @property
    def monthly_gpu_seconds(self) -> int:
        """Default monthly GPU allowance applied where no policy row exists."""
        return self._monthly_seconds

    @property
    def storage_soft_limit_bytes(self) -> int:
        """Default soft durable-storage ceiling, in logical bytes."""
        return self._storage_soft_limit

    def _period_totals(self, user_id: int, period: str, resource_class: str) -> dict[str, int]:
        with self.engine.connect() as conn:
            return self._ledger_totals_in_connection(conn, user_id, period, resource_class)

    def _period_usage(self, user_id: int, period: str, resource_class: str) -> int:
        return -self._period_totals(user_id, period, resource_class).get(rloan.LedgerKind.USAGE.value, 0)

    def _period_adjustments(self, user_id: int, period: str, resource_class: str) -> int:
        return self._administrative_adjustments(self._period_totals(user_id, period, resource_class))

    def compute_entitlement(
        self,
        user_id: int,
        *,
        unit: str = rloan.UNIT_GPU_SECOND,
        at: float | None = None,
    ) -> rloan.ComputeEntitlement:
        """The canonical per-(subject, unit) admission position, as a typed value.

        The entry is always the class-agnostic scope, because the deployment has
        exactly one GPU allowance and it spans every accelerator class: a typed
        ``a100`` second and an untyped one draw on the same balance.  This method
        is therefore the only place that answers "may this user run?", and every
        consumer gets the answer admission acts on.

        Per-class detail is real and stays where it belongs — on the ledger rows,
        reported by :meth:`class_usage` — but it is not an entitlement: a
        per-class remaining balance would let a consumer read a confident "yes"
        at one class while admission refuses at the shared balance.
        """
        checked_at = time.time() if at is None else at
        enforce = unit == rloan.UNIT_GPU_SECOND
        period = self._gpu_period(checked_at) if rloan.periods_for_unit(unit) else ""
        with self.engine.begin() as conn:
            if enforce:
                self._ensure_monthly_grant(conn, user_id, period, "", checked_at)
            rows = conn.execute(
                select(self.resource_ledger_table).where(
                    self.resource_ledger_table.c.subject_type == rloan.SUBJECT_USER,
                    self.resource_ledger_table.c.subject_id == user_id,
                    self.resource_ledger_table.c.unit == unit,
                )
            ).mappings().all()
            reserved = conn.execute(
                select(func.coalesce(func.sum(self.resource_reservations_table.c.quantity), 0)).where(
                    self.resource_reservations_table.c.subject_id == user_id,
                    self.resource_reservations_table.c.unit == unit,
                    self.resource_reservations_table.c.state.in_(rloan.COMMITTED_RESERVATION_STATES),
                )
            ).scalar_one()
            unsettled, unsettled_quantity = self._unsettled_in_connection(
                conn, user_id, unit, "", checked_at
            )
        totals = rloan.summarize_ledger(rows, unit=unit, resource_class="", period=period or None)
        sources = tuple(sorted({str(row["evidence_source"]) for row in rows if row["evidence_source"]}))
        return rloan.ComputeEntitlement(
            unit=unit,
            resource_class="",
            allowance=totals["allowance"] if enforce else None,
            used=totals["used"],
            reserved=int(reserved),
            unsettled=int(unsettled),
            unsettled_quantity=int(unsettled_quantity),
            evidence_sources=sources,
        )

    def class_usage(self, user_id: int, *, gres: str, period: str | None = None) -> int:
        """GPU-seconds one subject actually consumed in one resource class.

        A *report* of recorded facts, never a balance: what a class cost is
        knowable, while what a class is *allowed* is not a per-class question.
        """
        resource_class = rloan.resource_class_for_gres(gres)
        totals = self._period_totals(user_id, period or self._gpu_period(), resource_class)
        return -totals.get(rloan.LedgerKind.USAGE.value, 0)

    def _unsettled_in_connection(
        self, conn, user_id: int, unit: str, resource_class: str, now: float, exclude_slurm_job_id: str | None = None
    ) -> tuple[int, int]:
        """Unsettled allocations: how many, and a conservative base-unit reserve.

        An allocation whose authoritative elapsed time is unavailable has
        definitely consumed something, so it is never treated as zero.  The
        reserve is a *base-unit* quantity — the same unit the allocation will be
        settled in — so it is an upper bound on what settlement will charge:
        ``max(quantum, resource_count * elapsed)``.  The quantum is applied to the
        final quantity, not to the count, because one GPU running for ten seconds
        is ten GPU-seconds, not ten quantum-multiples of the scheduler window.  A
        run long enough for ``count * elapsed`` to pass the quantum reserves its
        own elapsed quantity instead, so the reserve is never smaller than the
        usage that will replace it.

        A genuinely unknown shape (``resource_count`` is ``None``) keeps a
        non-zero reserve scaled by the elapsed time it has been running: the
        allocation really held something for that long, and a naive
        ``max(quantum, 0 * elapsed)`` would collapse it to zero and re-create
        exactly the free computation the unknown-is-not-zero rule forbids.

        ``exclude_slurm_job_id`` drops one allocation from the reserve.  The
        allocation-start decision uses it for the allocation it is deciding,
        which already exists as a fact by then: counting it here would make every
        start refuse itself, because an ACTIVE allocation reserves usage before it
        has any elapsed time to settle from.
        """
        conditions = [
            self.resource_allocations_table.c.subject_id == user_id,
            self.resource_allocations_table.c.unit == unit,
            self.resource_allocations_table.c.status.in_(
                (rloan.AllocationStatus.ACTIVE.value, rloan.AllocationStatus.REVIEW.value)
            ),
        ]
        if exclude_slurm_job_id is not None:
            conditions.append(self.resource_allocations_table.c.slurm_job_id != exclude_slurm_job_id)
        rows = conn.execute(
            select(
                self.resource_allocations_table.c.resource_count,
                self.resource_allocations_table.c.started_at,
            ).where(*conditions)
        ).all()
        if not rows:
            return 0, 0
        quantum = int(rloan.DEFAULT_ADMISSION_QUANTUM.get(unit, 0))
        total = 0
        for count, started_at in rows:
            # The same second count settlement will charge with: a whole-second
            # ceiling, floored at one so an allocation that has only just started
            # still reserves a positive base-unit quantity.
            elapsed = max(1, math.ceil(max(0.0, now - float(started_at))))
            if count is None:
                # An unknown shape reserves the quantum for every second it has
                # held the resource: it definitely consumed *something*, so it is
                # never admitted against as if it held nothing, and the floor
                # grows with the elapsed time it has been running.
                total += quantum * elapsed
                continue
            observed = max(0, int(count)) * elapsed
            total += max(quantum, observed)
        return len(rows), total

    def storage_entitlement(self, user_id: int) -> rloan.StorageEntitlement:
        """Logical owned bytes for one subject, with its configured soft ceiling."""
        return rloan.StorageEntitlement(
            logical_owned_bytes=self.logical_owned_bytes(user_id),
            soft_limit_bytes=self._storage_soft_limit or None,
        )

    def resource_envelope(self, user_id: int, *, at: float | None = None) -> rloan.ResourceEnvelope:
        """The canonical per-subject position that later consumers project.

        ``compute`` carries the scopes admission decides on: the class-agnostic
        GPU balance (the one allowance, which already spans every accelerator
        class) and each ungated unit this deployment records.  A per-class entry
        is deliberately absent — it would be a second, potentially contradicting
        answer to "may this user run?", and a consumer reading it could be told
        yes while admission says no.  Class detail stays available as a filtered
        report via :meth:`class_usage`.

        Storage is reported once, as :attr:`ResourceEnvelope.storage`.  It is
        durable ownership rather than per-period consumption, so mirroring it as
        a ``storage_byte`` compute entry would publish two numbers that diverge
        the moment a result is republished with a different size.
        """
        checked_at = time.time() if at is None else at
        return rloan.ResourceEnvelope(
            subject_type=rloan.SUBJECT_USER,
            subject_id=user_id,
            period=self._gpu_period(checked_at),
            compute=(
                self.compute_entitlement(user_id, unit=rloan.UNIT_GPU_SECOND, at=checked_at),
                self.compute_entitlement(user_id, unit=rloan.UNIT_CPU_CORE_SECOND, at=checked_at),
            ),
            storage=self.storage_entitlement(user_id),
        )

    def cpu_core_second_summary(self, user_id: int, *, at: float | None = None) -> dict[str, Any]:
        """CPU core-seconds one subject was allocated in one UTC month.

        Allocation-based, not utilization-based: it reports the same settled
        ``usage`` facts :meth:`compute_entitlement` reads for the
        ``cpu_core_second`` unit, never the ``/usr/bin/time`` figures the runner
        wrapper reports.  ``unsettled_allocations`` is the unknown-is-not-zero
        distinction at the reporting boundary — those allocations definitely
        consumed something and have not been charged yet.
        """
        checked_at = time.time() if at is None else at
        entitlement = self.compute_entitlement(
            user_id, unit=rloan.UNIT_CPU_CORE_SECOND, at=checked_at
        )
        return {
            "user_id": user_id,
            "period": self._gpu_period(checked_at),
            "used_cpu_core_seconds": entitlement.used,
            "used_cpu_hours": rloan.cpu_hours_from_core_seconds(entitlement.used),
            "unsettled_allocations": entitlement.unsettled,
            "unsettled_cpu_core_seconds": entitlement.unsettled_quantity,
            "usage_complete": entitlement.usage_complete,
            "evidence_sources": list(entitlement.evidence_sources),
        }

    def gpu_credit_summary(
        self, user_id: int, *, at: float | None = None
    ) -> dict[str, Any]:
        """Return a balance derived from append-only entries for one UTC month."""
        checked_at = time.time() if at is None else at
        period = self._gpu_period(checked_at)
        resource_class = rloan.resource_class_for_gres(None)
        with self.engine.begin() as conn:
            self._ensure_monthly_grant(conn, user_id, period, "", checked_at)
        totals = self._period_totals(user_id, period, resource_class)
        return {
            "user_id": user_id,
            "period": period,
            "monthly_grant_gpu_seconds": self._effective_monthly_allowance(totals),
            "usage_gpu_seconds": -totals.get(rloan.LedgerKind.USAGE.value, 0),
            "adjustment_gpu_seconds": self._administrative_adjustments(totals),
            "remaining_gpu_seconds": self.compute_entitlement(user_id, at=checked_at).remaining,
        }

    @staticmethod
    def _effective_monthly_allowance(totals: dict[str, int]) -> int:
        """Configured allowance currently effective for one period."""
        return totals.get(rloan.LedgerKind.MONTHLY_GRANT.value, 0) + totals.get(
            rloan.LedgerKind.ALLOWANCE_ADJUSTMENT.value, 0
        )

    @staticmethod
    def _administrative_adjustments(totals: dict[str, int]) -> int:
        """Administrative compensations that are not the monthly allowance.

        ``admin_reset`` is grouped with adjustments so the displayed breakdown
        (allowance + adjustments - usage) still sums to the derived balance.
        """
        return sum(totals.get(kind, 0) for kind in rloan.ADJUSTMENT_KINDS)

    def set_compute_allowance(
        self,
        *,
        user_id: int,
        monthly_gpu_seconds: int,
        actor_user_id: int,
        idempotency_key: str,
        updated_at: float | None = None,
    ) -> dict[str, Any]:
        """Set current/future allowance while preserving an append-only ledger."""
        if monthly_gpu_seconds < 0 or monthly_gpu_seconds > 10_000_000:
            raise ValueError("monthly_gpu_seconds must be between 0 and 10000000")
        timestamp = time.time() if updated_at is None else updated_at
        period = self._gpu_period(timestamp)
        durable_key = f"allowance_adjustment:user:{user_id}:{idempotency_key}"
        reason = f"Monthly allowance set to {monthly_gpu_seconds} GPU-seconds"
        # BEGIN IMMEDIATE closes the read-compute-insert race: without it two
        # concurrent updates each read the same stale allowance and append
        # deltas that sum to more than either admin intended.
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                prior = conn.execute(
                    select(self.resource_ledger_table).where(
                        self.resource_ledger_table.c.idempotency_key == durable_key
                    )
                ).mappings().one_or_none()
                if prior is not None:
                    if prior["reason"] != reason or prior["actor_user_id"] != actor_user_id:
                        raise ValueError("idempotency_key was already used for a different allowance")
                    conn.commit()
                    return dict(prior)
                self._ensure_monthly_grant(conn, user_id, period, "", timestamp)
                current_allowance = conn.execute(
                    select(func.sum(self.resource_ledger_table.c.quantity)).where(
                        self.resource_ledger_table.c.subject_id == user_id,
                        self.resource_ledger_table.c.unit == rloan.UNIT_GPU_SECOND,
                        self.resource_ledger_table.c.period == period,
                        self.resource_ledger_table.c.kind.in_(rloan.ALLOWANCE_KINDS),
                    )
                ).scalar_one() or 0
                delta = monthly_gpu_seconds - int(current_allowance)
                self._upsert_policy(
                    conn,
                    user_id=user_id,
                    resource_class="",
                    allowance=monthly_gpu_seconds,
                    actor_user_id=actor_user_id,
                    timestamp=timestamp,
                )
                self._write_policy_audit(
                    conn,
                    user_id=user_id,
                    actor_user_id=actor_user_id,
                    operation="set_compute_allowance",
                    before_json={"allowance": int(current_allowance)},
                    after_json={"allowance": monthly_gpu_seconds},
                    reason=reason,
                    idempotency_key=durable_key,
                    timestamp=timestamp,
                    unit=rloan.UNIT_GPU_SECOND,
                )
                result = conn.execute(
                    sqlite_insert(self.resource_ledger_table).values(
                        subject_type=rloan.SUBJECT_USER,
                        subject_id=user_id,
                        period=period,
                        kind=rloan.LedgerKind.ALLOWANCE_ADJUSTMENT.value,
                        unit=rloan.UNIT_GPU_SECOND,
                        resource_class="",
                        quantity=delta,
                        actor_user_id=actor_user_id,
                        reason=reason,
                        reason_code=rloan.LedgerReason.ALLOWANCE_SET.value,
                        evidence_source=rloan.EvidenceSource.POLICY.value,
                        idempotency_key=durable_key,
                        created_at=timestamp,
                    )
                )
                row = conn.execute(
                    select(self.resource_ledger_table).where(
                        self.resource_ledger_table.c.id == result.inserted_primary_key[0]
                    )
                ).mappings().one()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return dict(row)

    def _upsert_policy(
        self,
        conn,
        *,
        user_id: int,
        resource_class: str,
        allowance: int,
        actor_user_id: int,
        timestamp: float,
    ) -> None:
        policy = sqlite_insert(self.resource_policies_table).values(
            subject_type=rloan.SUBJECT_USER,
            subject_id=user_id,
            unit=rloan.UNIT_GPU_SECOND,
            resource_class=resource_class,
            allowance=allowance,
            updated_by_user_id=actor_user_id,
            updated_at=timestamp,
        ).on_conflict_do_update(
            index_elements=[
                self.resource_policies_table.c.subject_type,
                self.resource_policies_table.c.subject_id,
                self.resource_policies_table.c.unit,
                self.resource_policies_table.c.resource_class,
            ],
            set_={
                "allowance": allowance,
                "updated_by_user_id": actor_user_id,
                "updated_at": timestamp,
            },
        )
        conn.execute(policy)

    def _write_policy_audit(
        self,
        conn,
        *,
        user_id: int,
        actor_user_id: int,
        operation: str,
        before_json: dict[str, Any],
        after_json: dict[str, Any],
        reason: str | None,
        idempotency_key: str,
        timestamp: float,
        unit: str = "",
        resource_class: str = "",
    ) -> None:
        conn.execute(
            sqlite_insert(self.resource_policy_audit_table)
            .values(
                subject_type=rloan.SUBJECT_USER,
                subject_id=user_id,
                actor_user_id=actor_user_id,
                operation=operation,
                unit=unit,
                resource_class=resource_class,
                before_json=json.dumps(before_json, sort_keys=True),
                after_json=json.dumps(after_json, sort_keys=True),
                reason=reason,
                idempotency_key=f"policy_audit:{idempotency_key}",
                created_at=timestamp,
            )
            .on_conflict_do_nothing(index_elements=[self.resource_policy_audit_table.c.idempotency_key])
        )

    def require_compute_entitlement(
        self, user_id: int, *, at: float | None = None
    ) -> dict[str, Any]:
        """Fail when the current UTC-month balance cannot admit a new allocation."""
        summary = self.gpu_credit_summary(user_id, at=at)
        if summary["remaining_gpu_seconds"] <= 0:
            raise GPUCreditUnavailableError("GPU credit balance is exhausted")
        return summary

    def adjust_compute_account(
        self,
        *,
        user_id: int,
        gpu_seconds: int,
        actor_user_id: int,
        reason: str,
        idempotency_key: str,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        """Append an adjustment, returning the prior row on an identical retry."""
        if gpu_seconds == 0:
            raise ValueError("gpu_seconds must be non-zero")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("reason is required")
        timestamp = time.time() if created_at is None else created_at
        period = self._gpu_period(timestamp)
        durable_key = f"admin_adjustment:user:{user_id}:{idempotency_key}"
        stmt = sqlite_insert(self.resource_ledger_table).values(
            subject_type=rloan.SUBJECT_USER,
            subject_id=user_id,
            period=period,
            kind=rloan.LedgerKind.ADMIN_ADJUSTMENT.value,
            unit=rloan.UNIT_GPU_SECOND,
            resource_class="",
            quantity=gpu_seconds,
            task_id=None,
            stage_id=None,
            slurm_job_id=None,
            actor_user_id=actor_user_id,
            reason=normalized_reason,
            reason_code=rloan.LedgerReason.ADMIN_ADJUSTMENT.value,
            evidence_source=rloan.EvidenceSource.POLICY.value,
            idempotency_key=durable_key,
            created_at=timestamp,
        ).on_conflict_do_nothing(index_elements=[self.resource_ledger_table.c.idempotency_key])
        with self.engine.begin() as conn:
            self._ensure_monthly_grant(conn, user_id, period, "", timestamp)
            conn.execute(stmt)
            self._write_policy_audit(
                conn,
                user_id=user_id,
                actor_user_id=actor_user_id,
                operation="admin_adjustment",
                before_json={},
                after_json={"gpu_seconds": gpu_seconds},
                reason=normalized_reason,
                idempotency_key=durable_key,
                timestamp=timestamp,
                unit=rloan.UNIT_GPU_SECOND,
            )
            row = conn.execute(
                select(self.resource_ledger_table).where(
                    self.resource_ledger_table.c.idempotency_key == durable_key
                )
            ).mappings().one()
        expected = (user_id, gpu_seconds, actor_user_id, normalized_reason)
        actual = (row["subject_id"], row["quantity"], row["actor_user_id"], row["reason"])
        if actual != expected:
            raise ValueError("idempotency_key was already used for a different adjustment")
        return dict(row)

    # -- Administrative GPU-credit reset ------------------------------------
    #
    # A reset restores a user's current-period remaining balance to that
    # user's effective monthly allowance by appending one compensating
    # ``admin_reset`` ledger entry.  It never deletes usage, rewrites grants,
    # or touches GPU permission.
    #
    # Batch correlation for the "reset all users" operation reuses the
    # append-only ledger's unique ``idempotency_key`` column instead of adding
    # a new column (which would demand a migration for every existing
    # database).  Each entry stores ``admin_reset:{batch_id}:{user_id}``, so
    # one batch is exactly the set of rows sharing the ``batch_id`` prefix.

    @staticmethod
    def _normalize_admin_reason(reason: str) -> str:
        if not isinstance(reason, str):
            raise ValueError("reason is required")
        normalized = reason.strip()
        if not normalized:
            raise ValueError("reason is required")
        if len(normalized) > 1000:
            raise ValueError("reason must be at most 1000 characters")
        return normalized

    def _ledger_totals_in_connection(self, conn, user_id: int, period: str, resource_class: str = "") -> dict[str, int]:
        """Sum one GPU-second period by ledger kind, optionally for one class.

        A *report*: an empty class sums every class (the allowance scope) and a
        named class selects the facts recorded under it.  Neither decides
        admission — that is :meth:`compute_entitlement`, always at the
        allowance scope.
        """
        stmt = (
            select(
                self.resource_ledger_table.c.kind,
                func.sum(self.resource_ledger_table.c.quantity),
            )
            .where(
                self.resource_ledger_table.c.subject_id == user_id,
                self.resource_ledger_table.c.unit == rloan.UNIT_GPU_SECOND,
                self.resource_ledger_table.c.period == period,
            )
            .group_by(self.resource_ledger_table.c.kind)
        )
        if resource_class:
            stmt = stmt.where(self.resource_ledger_table.c.resource_class == resource_class)
        rows = conn.execute(stmt).all()
        return {str(kind): int(total or 0) for kind, total in rows}

    def _reset_account_in_connection(
        self,
        conn,
        *,
        user_id: int,
        actor_user_id: int,
        reason: str,
        durable_key: str,
        batch_id: str | None,
        timestamp: float,
    ) -> dict[str, Any]:
        """Compute the compensating delta and append it inside one transaction."""
        period = self._gpu_period(timestamp)
        self._ensure_monthly_grant(conn, user_id, period, "", timestamp)
        prior = (
            conn.execute(
                select(self.resource_ledger_table).where(
                    self.resource_ledger_table.c.idempotency_key == durable_key
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior is not None:
            if prior["actor_user_id"] != actor_user_id or prior["reason"] != reason:
                raise ValueError("idempotency_key was already used for a different reset")
            totals = self._ledger_totals_in_connection(conn, user_id, period)
            remaining = sum(totals.values())
            delta = int(prior["quantity"])
            return {
                "user_id": user_id,
                "period": period,
                "batch_id": batch_id,
                "monthly_allowance_gpu_seconds": self._effective_monthly_allowance(totals),
                "previous_remaining_gpu_seconds": remaining - delta,
                "reset_delta_gpu_seconds": delta,
                "remaining_gpu_seconds": remaining,
                "changed": delta != 0,
                "entry_id": int(prior["id"]),
            }

        totals = self._ledger_totals_in_connection(conn, user_id, period)
        allowance = self._effective_monthly_allowance(totals)
        remaining = sum(totals.values())
        delta = allowance - remaining
        # A no-op reset still persists a zero-value marker row.  It contributes
        # nothing to the derived balance, but it durably reserves the
        # idempotency key so a later retry cannot perform a new reset after the
        # balance has changed, and it keeps the key reserved against reuse with
        # a different actor/reason.
        result = conn.execute(
            sqlite_insert(self.resource_ledger_table).values(
                subject_type=rloan.SUBJECT_USER,
                subject_id=user_id,
                period=period,
                kind=rloan.LedgerKind.ADMIN_RESET.value,
                unit=rloan.UNIT_GPU_SECOND,
                resource_class="",
                quantity=delta,
                task_id=None,
                stage_id=None,
                slurm_job_id=None,
                actor_user_id=actor_user_id,
                reason=reason,
                reason_code=rloan.LedgerReason.ADMIN_RESET.value,
                evidence_source=rloan.EvidenceSource.POLICY.value,
                idempotency_key=durable_key,
                created_at=timestamp,
            )
        )
        self._write_policy_audit(
            conn,
            user_id=user_id,
            actor_user_id=actor_user_id,
            operation="admin_reset",
            before_json={"remaining": remaining},
            after_json={"remaining": remaining + delta},
            reason=reason,
            idempotency_key=durable_key,
            timestamp=timestamp,
            unit=rloan.UNIT_GPU_SECOND,
        )
        return {
            "user_id": user_id,
            "period": period,
            "batch_id": batch_id,
            "monthly_allowance_gpu_seconds": allowance,
            "previous_remaining_gpu_seconds": remaining,
            "reset_delta_gpu_seconds": delta,
            "remaining_gpu_seconds": remaining + delta,
            "changed": delta != 0,
            "entry_id": int(result.inserted_primary_key[0]),
        }

    def reset_compute_account(
        self,
        *,
        user_id: int,
        actor_user_id: int,
        reason: str,
        idempotency_key: str,
        at: float | None = None,
    ) -> dict[str, Any]:
        """Restore one user's current-period balance to their effective allowance."""
        normalized_reason = self._normalize_admin_reason(reason)
        timestamp = time.time() if at is None else at
        # Individual resets are scoped by user so the same client key can be
        # reused for different users without colliding.
        durable_key = f"admin_reset:user:{idempotency_key}:{user_id}"        # BEGIN IMMEDIATE closes the read-compute-insert race against a
        # concurrent GPU settlement on the same SQLite database.
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                result = self._reset_account_in_connection(
                    conn,
                    user_id=user_id,
                    actor_user_id=actor_user_id,
                    reason=normalized_reason,
                    durable_key=durable_key,
                    batch_id=None,
                    timestamp=timestamp,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return result

    def reset_all_compute_accounts(
        self,
        *,
        user_ids: Iterable[int],
        actor_user_id: int,
        reason: str,
        idempotency_key: str,
        at: float | None = None,
    ) -> dict[str, Any]:
        """Restore every listed current user to their own effective allowance.

        All per-user entries are written in one transaction: either the whole
        batch commits or nothing does.  ``batch_id`` is embedded in each
        ledger row's idempotency key, so a retry with the same operation key
        finds the existing rows and appends nothing.
        """
        normalized_reason = self._normalize_admin_reason(reason)
        timestamp = time.time() if at is None else at
        period = self._gpu_period(timestamp)
        batch_id = f"reset-batch:{idempotency_key}"
        considered = changed = unchanged = total_delta = 0
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                for user_id in user_ids:
                    result = self._reset_account_in_connection(
                        conn,
                        user_id=int(user_id),
                        actor_user_id=actor_user_id,
                        reason=normalized_reason,
                        durable_key=f"admin_reset:user:{batch_id}:{int(user_id)}",
                        batch_id=batch_id,
                        timestamp=timestamp,
                    )
                    considered += 1
                    if result["changed"]:
                        changed += 1
                        total_delta += int(result["reset_delta_gpu_seconds"])
                    else:
                        unchanged += 1
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {
            "period": period,
            "batch_id": batch_id,
            "users_considered": considered,
            "users_changed": changed,
            "users_unchanged": unchanged,
            "total_delta_gpu_seconds": total_delta,
        }

    def record_resource_observation(self, row: dict[str, Any]) -> int | None:
        """Append one runner-reported observation; idempotent per attempt.

        Returns the row id, or ``None`` when an identical observation is already
        stored (or the row is malformed).  Ingest is on the execution path — a
        re-drained stdout line must not raise into the poll loop — so this is
        total and never propagates a storage error.
        """
        try:
            values = {
                "id": None,
                **_resource_observation_row(row),
                "created_at": float(row.get("created_at") or time.time()),
            }
            if not values["runner"]:
                # Without a runner the row can never be selected by the
                # estimator's profile key, so it is noise, not history.
                return None
            identity = {name: values[name] for name in RESOURCE_OBSERVATION_IDENTITY}
            # The root fix for "guidance dies on one poisoned row": a row the
            # reader cannot round-trip is never stored in the first place, so
            # the stored set and the published set stay the same set.  The
            # reader's failure surface is the untrusted payload's own shapes,
            # so this catches whatever ``from_dict`` raises on them.
            rm.ResourceObservation.from_dict(row)
        except Exception:  # untrusted payload: dropped and logged, never raised
            logging.warning("Discarding malformed resource observation")
            return None
        try:
            with self.engine.begin() as conn:
                existing = conn.execute(
                    select(self.resource_observations_table.c.id).where(
                        *(getattr(self.resource_observations_table.c, name) == value for name, value in identity.items())
                    )
                ).first()
                if existing is not None:
                    return None
                result = conn.execute(sqlite_insert(self.resource_observations_table).values(**values))
                inserted = int(result.inserted_primary_key[0])
        except (OperationalError, IntegrityError) as exc:
            # A concurrent worker may have inserted the same identity between
            # the SELECT and the INSERT; the unique index rejects the loser.
            if "unique" not in str(exc).lower():
                logging.warning("Could not record resource observation: %s", exc)
            return None
        self._trim_resource_observations(values["runner"], values["model_version"])
        return inserted

    def _trim_resource_observations(self, runner: str, model_version: str) -> None:
        """Keep the newest :data:`RESOURCE_OBSERVATION_RETENTION` rows *per device class*.

        Bounded retention, applied on write so no maintenance daemon is needed:
        the estimator reads only the newest :data:`OBSERVATION_LIMIT`-ish rows
        for one (runner, model_version), so older rows are history nothing reads.
        A count cap (rather than an age cap) is what keeps it deterministic
        under both a chatty runner and an idle month.

        The cap is stratified by ``device_class`` so a busy common GPU cannot
        evict a rarer class' entire history for the same runner/model — each
        class keeps its own newest rows.  Evidence that does not even name a
        class (a runner that could not report one) is trimmed on its own.
        """
        profile = (
            self.resource_observations_table.c.runner == runner,
            self.resource_observations_table.c.model_version == model_version,
        )
        try:
            with self.engine.begin() as conn:
                classes = conn.execute(
                    select(self.resource_observations_table.c.device_class).where(*profile).distinct()
                ).scalars()
                for device_class in classes:
                    cutoff = conn.execute(
                        select(self.resource_observations_table.c.id)
                        .where(*profile, self.resource_observations_table.c.device_class == device_class)
                        .order_by(desc(self.resource_observations_table.c.id))
                        .limit(1)
                        .offset(RESOURCE_OBSERVATION_RETENTION - 1)
                    ).scalar()
                    if cutoff is None:
                        continue
                    conn.execute(
                        delete(self.resource_observations_table).where(
                            *profile,
                            self.resource_observations_table.c.device_class == device_class,
                            self.resource_observations_table.c.id < cutoff,
                        )
                    )
        except OperationalError as exc:
            # Retention is housekeeping: a locked database must not fail ingest.
            logging.warning("Could not trim resource observations: %s", exc)

    def record_task_progress(
        self,
        task_id: str,
        *,
        progress: dict[str, Any] | None = None,
        outcome: str | None = None,
    ) -> None:
        """Record the runner's latest progress payload and/or task outcome.

        Only the fields a caller supplies are advanced, so a later progress
        line never clears an outcome already reported.
        """
        if not task_id:
            return
        fields: dict[str, Any] = {"updated_at": time.time()}
        if progress is not None:
            fields["progress_json"] = json.dumps(progress, sort_keys=True)
        if outcome is not None:
            fields["outcome"] = str(outcome)
        stmt = sqlite_insert(self.task_progress_table).values(
            task_id=task_id,
            progress_json=fields.get("progress_json", "{}"),
            outcome=fields.get("outcome", ""),
            updated_at=fields["updated_at"],
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[self.task_progress_table.c.task_id],
            set_={
                key: getattr(stmt.excluded, key)
                for key in ("progress_json", "outcome", "updated_at")
                if key in fields
            },
        )
        try:
            with self.engine.begin() as conn:
                conn.execute(stmt)
        except OperationalError as exc:
            # Progress is a live-view convenience; losing one update must never
            # fail the poll loop that is tracking the allocation.
            logging.warning("Could not record execution progress for %s: %s", task_id, exc)

    def get_task_progress(self, task_id: str) -> dict[str, Any] | None:
        stmt = select(self.task_progress_table).where(self.task_progress_table.c.task_id == task_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        if row is None:
            return None
        record = dict(row)
        record["progress"] = json.loads(record.pop("progress_json") or "{}")
        return record

    def record_result_publication(
        self,
        task_id: str,
        *,
        manifest_sha256: str,
        manifest_size: int,
        published_at: float,
        charge_bytes: int | None = None,
    ) -> int:
        """Anchor one finalized result manifest's identity in server-owned state.

        The anchor is written in the same transaction that would record any
        earlier revision of the same task's manifest, and it carries an
        advancing ``revision`` rather than a bare digest: a re-publish (the
        failed-task report, or a second finalization of a recovered job) is a
        new revision of *this* task's publication, and a later consumer reads
        the newest one.  The digest is validated here rather than trusted, so a
        caller cannot anchor a value the reader could never match.
        """
        digest = str(manifest_sha256 or "").strip().lower()
        if not _MANIFEST_SHA256.fullmatch(digest):
            raise ValueError("manifest_sha256 must be a hex SHA-256 digest")
        if not isinstance(manifest_size, int) or isinstance(manifest_size, bool) or manifest_size < 0:
            raise ValueError("manifest_size must be a non-negative integer")
        if charge_bytes is not None and (
            not isinstance(charge_bytes, int) or isinstance(charge_bytes, bool) or charge_bytes < 0
        ):
            raise ValueError("charge_bytes must be a non-negative integer")
        # The charge this publication owes, recorded in the same write as its
        # identity.  Zero bytes is already paid (there is nothing to charge), so
        # it is born ``charged``; anything else is born ``pending`` and stays so
        # until the lifecycle row records the charge.  Republishing resets it:
        # bytes that came back are quota the subject holds again, exactly as a
        # ``PURGED`` lifecycle row re-opens on republication.
        charge_state = "charged" if charge_bytes == 0 else "pending"
        with self.engine.begin() as conn:
            revision = conn.execute(
                select(self.result_publications_table.c.revision).where(
                    self.result_publications_table.c.task_id == task_id
                )
            ).scalar_one_or_none()
            stmt = sqlite_insert(self.result_publications_table).values(
                task_id=task_id,
                manifest_sha256=digest,
                manifest_size=manifest_size,
                revision=(int(revision) + 1) if revision is not None else 1,
                published_at=published_at,
                charge_bytes=charge_bytes,
                charge_state=charge_state,
                charged_at=published_at if charge_state == "charged" else None,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[self.result_publications_table.c.task_id],
                set_={
                    "manifest_sha256": stmt.excluded.manifest_sha256,
                    "manifest_size": stmt.excluded.manifest_size,
                    "revision": stmt.excluded.revision,
                    "published_at": stmt.excluded.published_at,
                    "charge_bytes": stmt.excluded.charge_bytes,
                    "charge_state": stmt.excluded.charge_state,
                    "charged_at": stmt.excluded.charged_at,
                },
            )
            conn.execute(stmt)
        return (int(revision) + 1) if revision is not None else 1

    def get_result_publication(self, task_id: str) -> dict[str, Any] | None:
        """Return the anchored publication identity for one task, if any."""
        stmt = select(self.result_publications_table).where(self.result_publications_table.c.task_id == task_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        return dict(row) if row else None

    def charge_data_ownership(
        self, task_id: str, *, user_id: int, logical_bytes: int = 0, at: float | None = None
    ) -> str:
        """Record a published result's ownership in ONE guarded transition.

        The charge and the decision that it is still allowed are the same
        transaction, serialized against the purge by ``BEGIN IMMEDIATE``, because
        a check outside it races: a caller that reads "the data is still owned",
        has a purge land, and then charges would re-open a ``PURGED`` row and bill
        a subject for bytes that are gone.

        Returns ``"charged"`` when this call created the row and appended its
        ``storage_usage`` fact; ``"already_charged"`` when the Task's ownership is
        already on record (nothing is written, so a repeated pass cannot
        double-charge; the logical size is refreshed from this caller's own
        measurement when it differs); and ``"released"`` when the lifecycle is
        deletion-ward, ``ERROR`` (an interrupted removal a later pass retries), or
        ``PURGED`` -- nothing is written, because those bytes are gone or on their
        way out, and a deletion that already happened is not re-opened by a
        charge. ``"unowned"`` closes an ownerless pending publication without a
        lifecycle row or ledger charge, under the same deletion guard.
        """
        timestamp = time.time() if at is None else at
        size = max(0, int(logical_bytes))
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            existing = (
                conn.execute(
                    select(self.data_lifecycle_table).where(self.data_lifecycle_table.c.task_id == task_id)
                )
                .mappings()
                .one_or_none()
            )
            outcome = self._charge_data_ownership_in_connection(
                conn, task_id, existing, user_id=user_id, size=size, timestamp=timestamp
            )
            conn.commit()
        return outcome

    def _charge_data_ownership_in_connection(
        self, conn, task_id: str, existing, *, user_id: int, size: int, timestamp: float
    ) -> str:
        """The guarded body of :meth:`charge_data_ownership`, inside its transaction."""
        if existing is not None and str(existing["state"]) not in (
            rloan.DataLifecycleState.ACTIVE.value,
            rloan.DataLifecycleState.ARCHIVED.value,
        ):
            return "released"
        if user_id <= 0:
            conn.execute(
                update(self.result_publications_table)
                .where(
                    self.result_publications_table.c.task_id == task_id,
                    self.result_publications_table.c.charge_state == "pending",
                )
                .values(charge_state="unowned")
            )
            return "unowned"
        if existing is None:
            claimed = conn.execute(
                sqlite_insert(self.data_lifecycle_table)
                .values(
                    task_id=task_id,
                    subject_type=rloan.SUBJECT_USER,
                    subject_id=user_id,
                    state=rloan.DataLifecycleState.ACTIVE.value,
                    logical_bytes=size,
                    accounted_bytes=size,
                    charge_revision=1,
                    updated_at=timestamp,
                )
                .on_conflict_do_nothing(index_elements=[self.data_lifecycle_table.c.task_id])
            )
            if not claimed.rowcount:
                # Another writer got there first: its charge is the fact.
                return "already_charged"
            self._append_storage_fact(
                conn,
                user_id=user_id,
                task_id=task_id,
                quantity=-size,
                reason="Durable result published",
                reason_code=rloan.LedgerReason.STORAGE_CHARGED.value,
                idempotency_key=f"storage_usage:{task_id}:1",
                timestamp=timestamp,
            )
            return "charged"
        if int(existing["logical_bytes"]) != size:
            # A recomputation that found a different size updates the logical
            # fact.  The ledger fact stays as charged until a purge releases
            # exactly it, so no pass can double-count.
            conn.execute(
                update(self.data_lifecycle_table)
                .where(self.data_lifecycle_table.c.task_id == task_id)
                .values(logical_bytes=size, updated_at=timestamp)
            )
        return "already_charged"

    def list_pending_storage_publications(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Anchored publications whose logical-storage charge has not been recorded.

        A publication whose bytes are already gone (``released``) is excluded by
        the state itself, never by re-deriving anything: the lifecycle owns that
        decision, and this reader only answers "which publications still owe a
        charge".
        """
        if limit < 1 or limit > 5000:
            raise ValueError("limit must be between 1 and 5000")
        stmt = (
            select(self.result_publications_table)
            .where(self.result_publications_table.c.charge_state == "pending")
            .order_by(self.result_publications_table.c.published_at)
            .limit(limit)
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    def mark_publication_charged(self, task_id: str, *, charge_bytes: int, at: float) -> bool:
        """Record that one publication's logical bytes are now charged.

        Guarded on the ``pending`` state, so a repeated repair pass — or a repair
        racing the live publisher — records the charge once.  The amount is the
        publisher's own measurement, never re-derived from the tree.
        """
        stmt = (
            update(self.result_publications_table)
            .where(
                self.result_publications_table.c.task_id == task_id,
                self.result_publications_table.c.charge_state == "pending",
            )
            .values(charge_bytes=max(0, int(charge_bytes)), charge_state="charged", charged_at=at)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def mark_publication_released(self, task_id: str) -> bool:
        """Close a publication's charge because the lifecycle released its bytes."""
        stmt = (
            update(self.result_publications_table)
            .where(
                self.result_publications_table.c.task_id == task_id,
                self.result_publications_table.c.charge_state != "released",
            )
            .values(charge_state="released")
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def list_resource_observations(
        self,
        *,
        runners: tuple[str, ...] = (),
        model_versions: tuple[str, ...] = (),
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return stored observations newest first, filtered by runner/model."""
        if limit < 1 or limit > 2000:
            raise ValueError("limit must be between 1 and 2000")
        stmt = select(self.resource_observations_table)
        if runners:
            stmt = stmt.where(self.resource_observations_table.c.runner.in_(tuple(runners)))
        if model_versions:
            stmt = stmt.where(self.resource_observations_table.c.model_version.in_(tuple(model_versions)))
        stmt = stmt.order_by(desc(self.resource_observations_table.c.id)).limit(limit)
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    def list_reset_batch(self, batch_id: str) -> list[dict[str, Any]]:
        """Return the ledger rows written by one administrative reset batch."""
        prefix = f"admin_reset:user:{batch_id}:"
        stmt = (
            select(self.resource_ledger_table)
            .where(self.resource_ledger_table.c.idempotency_key.like(f"{prefix}%"))
            .order_by(self.resource_ledger_table.c.id)
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    def list_ledger(
        self,
        user_id: int,
        *,
        unit: str | None = None,
        period: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent immutable append-only facts for one subject, newest first.

        One reader for every unit: a compute fact and a durable-ownership fact
        are the same kind of row, so scoping by unit is a filter rather than a
        separate ledger.  ``period`` applies only to the periodic units; storage
        ownership spans every period and is returned regardless.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        stmt = select(self.resource_ledger_table).where(
            self.resource_ledger_table.c.subject_type == rloan.SUBJECT_USER,
            self.resource_ledger_table.c.subject_id == user_id,
        )
        if unit is not None:
            stmt = stmt.where(self.resource_ledger_table.c.unit == unit)
        if period is not None:
            stmt = stmt.where(
                or_(
                    self.resource_ledger_table.c.period == period,
                    self.resource_ledger_table.c.unit == rloan.UNIT_STORAGE_BYTE,
                )
            )
        stmt = stmt.order_by(desc(self.resource_ledger_table.c.id)).limit(limit)
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    def list_compute_ledger(
        self, user_id: int, *, period: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """The GPU-compute projection of one subject's ledger, newest first."""
        return self.list_ledger(user_id, unit=rloan.UNIT_GPU_SECOND, period=period, limit=limit)

    def list_policy_audit(self, user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return administrative policy mutations for one subject, newest first."""
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        stmt = (
            select(self.resource_policy_audit_table)
            .where(
                self.resource_policy_audit_table.c.subject_type == rloan.SUBJECT_USER,
                self.resource_policy_audit_table.c.subject_id == user_id,
            )
            .order_by(desc(self.resource_policy_audit_table.c.id))
            .limit(limit)
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    def record_allocation_start(
        self,
        *,
        user_id: int,
        task_id: str,
        stage_id: str,
        slurm_job_id: str,
        cpu_cores: int,
        gpu_count: int = 0,
        started_at: float | None = None,
        required_entitlements: tuple[str, ...] | None = None,
        denied_reason: str | None = None,
        gres: str = "",
    ) -> dict[str, Any]:
        """Record the instant a real Slurm allocation becomes observable.

        One Slurm allocation is recorded as one fact per accounting unit it
        consumed — a ``gpu_second`` fact when it holds GPUs, and always a
        ``cpu_core_second`` fact, because every Slurm allocation is an allocation
        of CPU cores.  They share a start instant and settle from the same
        authoritative elapsed duration, and their ``resource_count`` is what the
        scheduler allocated *in that unit's own terms*: GPUs for the GPU fact,
        CPU cores for the CPU fact.  CUDA percent and ``/usr/bin/time`` figures
        are utilization telemetry and are deliberately nowhere here.

        Recording the fact and deciding admission are two separate steps, on
        purpose.  The allocation rows are written first, unconditionally and
        idempotently (keyed by ``slurm_job_id``), because the scheduler holding
        the resources is a fact that exists whether or not this subject is
        allowed to run the scientific command: a policy decision must never
        rewrite it into "no allocation".  The quota/permission decision then runs
        in the same ``BEGIN IMMEDIATE`` transaction as a *grant* that either

        * succeeds — the Task's admission authority is honored (a live reserved
          hold of its own is not counted against it; every other Task's committed
          reservation and every unsettled allocation still constrains the
          balance), the reservation is consumed, and the allocation proceeds; or
        * is denied — the grant is reported as a separate fact
          (``granted=False`` plus the reason), the allocation rows stay ACTIVE so
          the resources actually held are still settled, and the caller withholds
          the scientific command.  A denied Task still owes for what its wrapper
          held while the gate was resolved and terminated.

        ``gres`` is preserved as the GPU fact's resource class, so a historical
        A100 second is never collapsed into an anonymous GPU-second; it is
        admitted against the deployment's single class-agnostic allowance, which
        spans every class.

        Returns the ``gpu_second`` fact (a zero-count row when the allocation
        holds no GPU), extended with ``granted``, ``reason_code``,
        ``remaining_gpu_seconds``, and ``admitted_by_reservation``;
        :meth:`list_task_allocations` returns every unit's facts.
        """
        if gpu_count < 0:
            raise ValueError("gpu_count must be non-negative")
        if cpu_cores < 1:
            raise ValueError("cpu_cores must be positive")
        resource_class = rloan.resource_class_for_gres(gres)
        timestamp = time.time() if started_at is None else started_at
        actual, granted = None, True
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = (
                    conn.execute(
                        select(self.resource_allocations_table).where(
                            self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                            self.resource_allocations_table.c.unit == rloan.UNIT_GPU_SECOND,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if existing.get("resource_count") is None:
                        # A weaker source proved only that the job held a node;
                        # this caller now reports the real shape, so it replaces
                        # the unknown per unit.  Nothing is settled here — the
                        # elapsed time still comes from reconciliation — and the
                        # strongest evidence available is recorded on the fact.
                        for unit, count in (
                            (rloan.UNIT_GPU_SECOND, gpu_count),
                            (rloan.UNIT_CPU_CORE_SECOND, cpu_cores),
                        ):
                            conn.execute(
                                update(self.resource_allocations_table)
                                .where(
                                    self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                                    self.resource_allocations_table.c.unit == unit,
                                )
                                .values(
                                    resource_count=count,
                                    resource_class=(
                                        resource_class if unit == rloan.UNIT_GPU_SECOND else ""
                                    ),
                                )
                            )
                        existing = (
                            conn.execute(
                                select(self.resource_allocations_table).where(
                                    self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                                    self.resource_allocations_table.c.unit
                                    == rloan.UNIT_GPU_SECOND,
                                )
                            )
                            .mappings()
                            .one()
                        )
                    self._assert_allocation_identity(
                        existing, user_id=user_id, task_id=task_id, stage_id=stage_id,
                        gpu_count=gpu_count, resource_class=resource_class,
                    )
                    if existing.get("adjudicated_at") is not None:
                        # Already decided — by an earlier identical start or by a
                        # retry.  The decision is recorded on the fact, so it is
                        # re-read here rather than made again against a balance
                        # the first decision already moved.
                        denial = existing.get("denial_reason")
                        recorded = dict(existing)
                        recorded["granted"] = denial is None
                        recorded["reason_code"] = (
                            str(existing.get("denial_code") or denial)
                            if denial
                            else rloan.AdmissionReason.ADMITTED.value
                        )
                        recorded["remaining_gpu_seconds"] = 0
                        recorded["admitted_by_reservation"] = False
                        conn.commit()
                        return recorded
                    # No decision yet: this row is the runner observation that the
                    # wrapper was executing, written before the admission
                    # decision (possibly before a crash).  The fact exists; the
                    # grant is decided now, below, without inserting a second set.
                else:
                    # The allocation FACT comes first, before any policy: the
                    # scheduler already handed these resources over, so the rows
                    # exist whether or not this subject may proceed.  Writing them
                    # here rather than after the decision is what keeps a denied
                    # Task from being recorded as "no allocation".
                    self._insert_allocation_facts(
                        conn,
                        user_id=user_id,
                        task_id=task_id,
                        stage_id=stage_id,
                        slurm_job_id=slurm_job_id,
                        gpu_count=gpu_count,
                        cpu_cores=cpu_cores,
                        resource_class=resource_class,
                        timestamp=timestamp,
                    )
                granted, reason_code, remaining, adjudicated = self._grant_allocation_in_connection(
                    conn,
                    user_id=user_id,
                    task_id=task_id,
                    slurm_job_id=slurm_job_id,
                    gpu_count=gpu_count,
                    required_entitlements=required_entitlements,
                    denied_reason=denied_reason,
                    timestamp=timestamp,
                )
                actual = dict(
                    conn.execute(
                        select(self.resource_allocations_table).where(
                            self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                            self.resource_allocations_table.c.unit == rloan.UNIT_GPU_SECOND,
                        )
                    )
                    .mappings()
                    .one()
                )
                # Mark the decision on the fact.  This is what distinguishes
                # "adjudicated and admitted" from "observed, not yet decided", so
                # a retry of this same call — after a crash, a duplicate callback,
                # or a workflow re-entry — reads the decision instead of making a
                # second one against a balance the first already moved.
                conn.execute(
                    update(self.resource_allocations_table)
                    .where(self.resource_allocations_table.c.slurm_job_id == slurm_job_id)
                    .values(adjudicated_at=timestamp)
                )
                # The allocation FACT exists now, so the reservation has done its
                # job: it covered the submission until the allocation started,
                # and the allocation — not the reservation — is what the balance
                # is charged for from here on.  This does not depend on the
                # grant: a denial does not put the scheduler's resources back,
                # so the claim this submission made is consumed either way, and
                # a denied Task is settled for what its wrapper actually held.
                self._release_reservation_in_connection(
                    conn,
                    task_id=task_id,
                    reason_code=rloan.ReservationReason.ALLOCATION_STARTED.value,
                    released_at=timestamp,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        # Whether the decision was re-read from a recorded fact or just made, the
        # fact's own denial is the answer the caller acts on.
        denied = actual.get("denial_reason") is not None
        recorded = dict(actual)
        recorded["granted"] = granted and not denied
        recorded["reason_code"] = (
            str(actual.get("denial_code") or actual.get("denial_reason")) if denied else reason_code
        )
        recorded["remaining_gpu_seconds"] = remaining if not denied else 0
        recorded["admitted_by_reservation"] = adjudicated if not denied else False
        return recorded

    def observe_allocation_start(
        self,
        *,
        user_id: int,
        task_id: str,
        stage_id: str,
        slurm_job_id: str,
        cpu_cores: int,
        gpu_count: int = 0,
        started_at: float | None = None,
        gres: str = "",
    ) -> dict[str, Any]:
        """Record that the wrapper was observed executing in a Slurm allocation.

        The wrapper prints its own ``$SLURM_JOB_ID`` only from inside the
        allocation, so this observation is the earliest authoritative
        compute-node execution evidence — stronger than the queued ``srun``
        stderr banner, which merely names a request.  It is written *before* and
        independently of any admission decision, so a process death between the
        observation and the grant can never erase the fact that resources were
        occupied: the rows are ``slurm_job_id``-keyed and idempotent, and a
        restart finds them unsettled and settles them from scheduler evidence.

        The exact elapsed duration is not known here, so the rows carry
        ``quantity = NULL`` and the ``runner_observation`` provenance — an
        unknown, never a zero.  :meth:`record_allocation_start` later promotes
        the same rows to their full lifecycle provenance and makes the grant
        decision; neither call creates a second fact.

        ``slurm_job_id`` is the allocation identity and is required: an
        observation with nothing to key it to could not be settled or
        de-duplicated.  It is written together with the per-unit rows.
        """
        if gpu_count < 0:
            raise ValueError("gpu_count must be non-negative")
        if cpu_cores < 1:
            raise ValueError("cpu_cores must be positive")
        resource_class = rloan.resource_class_for_gres(gres)
        timestamp = time.time() if started_at is None else started_at
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = (
                    conn.execute(
                        select(self.resource_allocations_table).where(
                            self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                            self.resource_allocations_table.c.unit == rloan.UNIT_GPU_SECOND,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if existing.get("resource_count") is None:
                        # A weaker source (the scheduler's own output file) proved
                        # only that the job held a node.  The shape this caller
                        # reports now is the stronger fact, so it replaces the
                        # unknown per unit — but nothing is settled here: the
                        # elapsed time still comes from reconciliation, exactly as
                        # for any other observation.
                        for unit, count in (
                            (rloan.UNIT_GPU_SECOND, gpu_count),
                            (rloan.UNIT_CPU_CORE_SECOND, cpu_cores),
                        ):
                            conn.execute(
                                update(self.resource_allocations_table)
                                .where(
                                    self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                                    self.resource_allocations_table.c.unit == unit,
                                )
                                .values(
                                    resource_count=count,
                                    resource_class=resource_class if unit == rloan.UNIT_GPU_SECOND else "",
                                    evidence_source=rloan.EvidenceSource.RUNNER_OBSERVATION.value,
                                    status=rloan.AllocationStatus.ACTIVE.value,
                                )
                            )
                        conn.commit()
                        return dict(existing)
                    self._assert_allocation_identity(
                        existing, user_id=user_id, task_id=task_id, stage_id=stage_id,
                        gpu_count=gpu_count, resource_class=resource_class,
                    )
                    # The fact is durable, so the compute-node receipt that
                    # carried it here has done its job: dropping it in this same
                    # transaction is what keeps a restart from folding the same
                    # receipt in twice.
                    conn.execute(
                        delete(self.resource_receipts_table).where(
                            self.resource_receipts_table.c.task_id == task_id
                        )
                    )
                    conn.commit()
                    return dict(existing)
                self._insert_allocation_facts(
                    conn,
                    user_id=user_id,
                    task_id=task_id,
                    stage_id=stage_id,
                    slurm_job_id=slurm_job_id,
                    gpu_count=gpu_count,
                    cpu_cores=cpu_cores,
                    resource_class=resource_class,
                    timestamp=timestamp,
                    evidence_source=rloan.EvidenceSource.RUNNER_OBSERVATION.value,
                )
                # The reservation is handed to the scheduler in the same commit
                # as the observation: the two facts are written together so that
                # no durable state has a scheduler-owned reservation without the
                # allocation its own job id proves.  Idempotent — a Task whose
                # reservation was already queued or consumed keeps its current
                # state, and the observation is unaffected.
                conn.execute(
                    update(self.resource_reservations_table)
                    .where(
                        self.resource_reservations_table.c.task_id == task_id,
                        self.resource_reservations_table.c.state == rloan.ReservationState.HELD.value,
                    )
                    .values(
                        state=rloan.ReservationState.QUEUED.value,
                        reason_code=rloan.ReservationReason.DISPATCHED.value,
                        dispatched_at=timestamp,
                        scheduler_job_id=str(slurm_job_id),
                        expires_at=None,
                    )
                )
                # A wrapper-authored receipt taken from the compute node is the
                # one authoritative record that survives the worker's death.
                # The allocation fact above is now durable, so the receipt has
                # done its job; removing it here is what makes the reconciliation
                # idempotent — a restart either finds a receipt (and folds it in)
                # or finds the fact, never both.
                conn.execute(
                    delete(self.resource_receipts_table).where(
                        self.resource_receipts_table.c.task_id == task_id
                    )
                )
                row = (
                    conn.execute(
                        select(self.resource_allocations_table).where(
                            self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                            self.resource_allocations_table.c.unit == rloan.UNIT_GPU_SECOND,
                        )
                    )
                    .mappings()
                    .one()
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return dict(row)

    def allocation_row_exists(self, slurm_job_id: str) -> bool:
        """Whether any allocation fact — settled, active, or review — exists."""
        stmt = select(self.resource_allocations_table.c.id).where(
            self.resource_allocations_table.c.slurm_job_id == slurm_job_id
        )
        with self.engine.connect() as conn:
            return conn.execute(stmt).first() is not None

    # -- wrapper-authored execution receipts ---------------------------------

    def record_allocation_receipt(
        self,
        *,
        task_id: str,
        stage_id: str,
        slurm_job_id: str,
        observed_at: float,
        cpus: int,
        gpus: int,
        gres: str = "",
        authority: str = rloan.SUBJECT_USER,
    ) -> dict[str, Any]:
        """Persist the compute node's own record that the wrapper was running.

        The wrapper writes this file the moment it is inside the allocation, and
        for a worker that died before any other write it is the only surviving
        evidence that the physical allocation ever existed.  It is keyed by
        ``task_id`` so exactly one receipt per Task exists, and it is cleared once
        the canonical allocation rows are written.

        ``observed_at`` is the wrapper's own stamp and is kept as a fact about
        when the run began, not rewritten to the recovery time.
        """
        resource_class = rloan.resource_class_for_gres(gres)
        # The wrapper's stamp is taken on the compute node; a clock that is
        # ahead of this server's must not date a receipt into the future where a
        # later reconciliation would read it as an allocation that has not
        # started.
        observed_at = min(float(observed_at), time.time())
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    select(self.resource_receipts_table).where(
                        self.resource_receipts_table.c.task_id == task_id
                    )
                ).mappings().first()
                if row is not None:
                    # A receipt naming a different job is a replaced allocation:
                    # the latest observation for this Task wins, so a restart
                    # reconstructs the one allocation that was actually running.
                    # The same job keeps its first stamp — the earliest evidence
                    # of when the run began.
                    if str(row["slurm_job_id"]) != str(slurm_job_id):
                        conn.execute(
                            update(self.resource_receipts_table)
                            .where(self.resource_receipts_table.c.task_id == task_id)
                            .values(
                                slurm_job_id=str(slurm_job_id),
                                stage_id=stage_id,
                                observed_at=observed_at,
                                cpus=cpus,
                                gpus=gpus,
                                resource_class=resource_class,
                                authority=authority,
                            )
                        )
                else:
                    conn.execute(
                        sqlite_insert(self.resource_receipts_table).values(
                            id=f"{task_id}:{slurm_job_id}",
                            task_id=task_id,
                            stage_id=stage_id,
                            slurm_job_id=str(slurm_job_id),
                            observed_at=observed_at,
                            cpus=int(cpus),
                            gpus=int(gpus),
                            resource_class=resource_class,
                            authority=authority,
                        )
                    )
                row = conn.execute(
                    select(self.resource_receipts_table).where(
                        self.resource_receipts_table.c.task_id == task_id
                    )
                ).mappings().one()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return dict(row)

    def list_allocation_receipts(self) -> list[dict[str, Any]]:
        """Every receipt whose allocation fact has not been reconciled yet."""
        stmt = select(self.resource_receipts_table).order_by(
            self.resource_receipts_table.c.observed_at
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    def allocation_receipt_exists(self, slurm_job_id: str) -> bool:
        """Whether a receipt names this job, i.e. the node proved it was held."""
        stmt = select(self.resource_receipts_table.c.id).where(
            self.resource_receipts_table.c.slurm_job_id == str(slurm_job_id)
        )
        with self.engine.connect() as conn:
            return conn.execute(stmt).first() is not None

    def discard_allocation_receipt(self, task_id: str) -> None:
        """Drop a Task's receipt once its allocation fact is durable."""
        with self.engine.begin() as conn:
            conn.execute(
                delete(self.resource_receipts_table).where(
                    self.resource_receipts_table.c.task_id == task_id
                )
            )

    def observe_allocation_receipt(
        self, receipt: dict[str, Any], *, user_id: int, stage_id: str | None = None, gres: str = ""
    ) -> dict[str, Any]:
        """Fold one wrapper receipt into the canonical allocation fact.

        The receipt is consumed idempotently into the same ``slurm_job_id``-keyed
        observation the live path writes — never into a second row family — and
        the receipt row is dropped in the same transition that makes the fact
        durable.  Recovering the same receipt twice, or recovering one the runner
        already committed, therefore produces exactly one allocation.

        ``stage_id`` falls back to the receipt's own record and ``gres`` to the
        class it reported; the caller can supply the class from the Task's own
        resource snapshot when the node could not name one.
        """
        observed = self.observe_allocation_start(
            user_id=user_id,
            task_id=str(receipt["task_id"]),
            stage_id=stage_id if stage_id is not None else str(receipt.get("stage_id") or ""),
            slurm_job_id=str(receipt["slurm_job_id"]),
            cpu_cores=max(1, int(receipt.get("cpus") or 0)),
            gpu_count=int(receipt.get("gpus") or 0),
            started_at=float(receipt["observed_at"]),
            gres=gres or str(receipt.get("resource_class") or ""),
        )
        return observed

    @staticmethod
    def _assert_allocation_identity(
        existing, *, user_id: int, task_id: str, stage_id: str, gpu_count: int, resource_class: str
    ) -> None:
        """Fail closed if a Slurm job id is reused for a different allocation."""
        expected = (user_id, task_id, stage_id, gpu_count, resource_class)
        actual = (
            existing["subject_id"],
            existing["task_id"],
            existing["stage_id"],
            existing["resource_count"],
            existing["resource_class"],
        )
        if actual != expected:
            raise ValueError(
                "Slurm job ID is already associated with a different GPU allocation"
            )

    def _insert_allocation_facts(
        self,
        conn,
        *,
        user_id: int,
        task_id: str,
        stage_id: str,
        slurm_job_id: str,
        gpu_count: int | None,
        cpu_cores: int | None,
        resource_class: str,
        timestamp: float,
        evidence_source: str = rloan.EvidenceSource.ALLOCATION_LIFECYCLE.value,
    ) -> None:
        """Write one ACTIVE fact per accounting unit the allocation held.

        ``evidence_source`` names what the writer actually observed: the
        allocation lifecycle, or the bare runner observation that the wrapper was
        executing before any admission decision was made.

        A ``None`` count records an *unknown* shape rather than a zero — the
        scheduler's own output file proves the job held a node, but nothing says
        how much of either unit it held.  Such a row is left for review and is
        never settled to a number; a zero would be the false claim that the job
        held none of that unit.
        """
        for unit, count, klass in (
            (rloan.UNIT_GPU_SECOND, gpu_count, resource_class),
            (rloan.UNIT_CPU_CORE_SECOND, cpu_cores, ""),
        ):
            conn.execute(
                sqlite_insert(self.resource_allocations_table).on_conflict_do_nothing(
                    index_elements=[
                        self.resource_allocations_table.c.slurm_job_id,
                        self.resource_allocations_table.c.unit,
                    ]
                ).values(
                    subject_type=rloan.SUBJECT_USER,
                    subject_id=user_id,
                    task_id=task_id,
                    stage_id=stage_id,
                    slurm_job_id=slurm_job_id,
                    unit=unit,
                    resource_class=klass,
                    resource_count=count,
                    started_at=timestamp,
                    finished_at=None,
                    quantity=None,
                    status=rloan.AllocationStatus.ACTIVE.value,
                    evidence_source=evidence_source,
                    denial_reason=None,
                    denial_code=None,
                    adjudicated_at=None,
                    ledger_entry_id=None,
                )
            )

    def observe_unknown_shape_allocation(
        self,
        *,
        user_id: int,
        task_id: str,
        slurm_job_id: str,
        started_at: float,
        stage_id: str = "",
    ) -> dict[str, Any]:
        """Record that an allocation happened, with no shape anyone observed.

        The scheduler's own per-job output file is created the instant a job is
        allocated a node, so it survives a kill that lands between "allocated a
        node" and the job's first statement — the one window no in-job mechanism
        can cover.  What it proves is exactly one thing: a scheduler job held
        real resources.  It says nothing about how many GPUs or cores, so the
        facts it produces carry a NULL ``resource_count`` and are marked for
        review: an unknown, never a zero, and never a number invented from a
        policy default.

        Idempotent on ``slurm_job_id`` like every other observation, and it never
        overwrites a fact a stronger source already recorded.
        """
        if user_id <= 0:
            raise ValueError("user_id must be positive")
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                existing = (
                    conn.execute(
                        select(self.resource_allocations_table).where(
                            self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                            self.resource_allocations_table.c.unit == rloan.UNIT_GPU_SECOND,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    conn.commit()
                    return dict(existing)
                self._insert_allocation_facts(
                    conn,
                    user_id=user_id,
                    task_id=task_id,
                    stage_id=stage_id,
                    slurm_job_id=slurm_job_id,
                    gpu_count=None,
                    cpu_cores=None,
                    resource_class="",
                    timestamp=started_at,
                    evidence_source=rloan.EvidenceSource.SCHEDULER_LOG.value,
                )
                conn.execute(
                    update(self.resource_allocations_table)
                    .where(self.resource_allocations_table.c.slurm_job_id == slurm_job_id)
                    .values(status=rloan.AllocationStatus.REVIEW.value)
                )
                # The reservation is handed to the scheduler in the same commit:
                # the request exists, its job id proves the scheduler owns it, and
                # the hold must stop being a pre-dispatch hold a timer may free.
                conn.execute(
                    update(self.resource_reservations_table)
                    .where(
                        self.resource_reservations_table.c.task_id == task_id,
                        self.resource_reservations_table.c.state == rloan.ReservationState.HELD.value,
                    )
                    .values(
                        state=rloan.ReservationState.QUEUED.value,
                        reason_code=rloan.ReservationReason.DISPATCHED.value,
                        dispatched_at=started_at,
                        scheduler_job_id=str(slurm_job_id),
                        expires_at=None,
                    )
                )
                row = (
                    conn.execute(
                        select(self.resource_allocations_table).where(
                            self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                            self.resource_allocations_table.c.unit == rloan.UNIT_GPU_SECOND,
                        )
                    )
                    .mappings()
                    .one()
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return dict(row)

    def _grant_allocation_in_connection(
        self,
        conn,
        *,
        user_id: int,
        task_id: str,
        slurm_job_id: str,
        gpu_count: int,
        required_entitlements: tuple[str, ...] | None,
        denied_reason: str | None,
        timestamp: float,
    ) -> tuple[bool, str, int, bool]:
        """Decide whether a recorded allocation may run the scientific command.

        Returns ``(granted, reason_code, remaining, admitted_by_reservation)``.
        A denial is a *fact about the grant*, not a rollback: it is recorded on
        the allocation rows so the resources the wrapper held are still settled
        under the reason the Task was stopped, and the caller withholds the
        command.  Permission (#55 authorization) and quota are both checked here;
        a CPU-only allocation (``gpu_count == 0``) needs no quota decision.

        ``denied_reason`` is the caller's own pre-decision — a runner that is not
        ready, checked outside this store — so it denies here under the same rule
        and records the reason it was refused.
        """
        if denied_reason is not None:
            # The caller's own pre-decision (a runner that is not ready) denies
            # any allocation, GPU or CPU: the reason is recorded and the fact
            # stands for what was actually held.
            self._record_denial_in_connection(
                conn,
                slurm_job_id=slurm_job_id,
                reason=denied_reason,
                reason_code=rloan.AdmissionReason.RUNNER_READINESS_UNAVAILABLE.value,
            )
            return False, rloan.AdmissionReason.RUNNER_READINESS_UNAVAILABLE.value, 0, False
        if gpu_count < 1:
            return True, rloan.AdmissionReason.ADMITTED.value, 0, False
        if required_entitlements is not None:
            try:
                self._require_gpu_authorization(conn, user_id, required_entitlements, timestamp)
            except GPUAuthorizationUnavailableError as exc:
                self._record_denial_in_connection(
                    conn,
                    slurm_job_id=slurm_job_id,
                    reason=str(exc),
                    reason_code=rloan.AdmissionReason.AUTHORIZATION_UNAVAILABLE.value,
                )
                return False, rloan.AdmissionReason.AUTHORIZATION_UNAVAILABLE.value, 0, False
        try:
            remaining, adjudicated = self._authorize_allocation_start_in_connection(
                conn, user_id=user_id, task_id=task_id, at=timestamp, slurm_job_id=slurm_job_id
            )
        except GPUCreditUnavailableError as exc:
            self._record_denial_in_connection(
                conn,
                slurm_job_id=slurm_job_id,
                reason=str(exc),
                reason_code=rloan.AdmissionReason.COMPUTE_EXHAUSTED.value,
            )
            return False, rloan.AdmissionReason.COMPUTE_EXHAUSTED.value, 0, False
        return True, rloan.AdmissionReason.ADMITTED.value, remaining, adjudicated

    def _record_denial_in_connection(
        self, conn, *, slurm_job_id: str, reason: str, reason_code: str | None = None
    ) -> None:
        """Write the denial onto the allocation rows, without erasing the fact.

        ``reason_code`` stores the bounded vocabulary value the caller acts on;
        the free-form ``reason`` is kept as the human-readable detail.  A
        release/reservation decision needs one canonical, comparable code, never
        a message string.
        """
        values: dict[str, Any] = {"denial_reason": reason[:512]}
        if reason_code is not None:
            values["denial_code"] = reason_code
        conn.execute(
            update(self.resource_allocations_table)
            .where(
                self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                self.resource_allocations_table.c.status == rloan.AllocationStatus.ACTIVE.value,
            )
            .values(**values)
        )

    def settle_allocation(
        self, slurm_job_id: str, *, finished_at: float | None = None
    ) -> dict[str, Any]:
        """Append actual usage once per unit and return the ``gpu_second`` fact.

        The elapsed duration is measured here from the recorded allocation start,
        which is exactly the authoritative elapsed duration the scheduler-side
        settlement passes in, so both entry points charge the same CPU
        core-seconds and GPU-seconds.
        """
        timestamp = time.time() if finished_at is None else finished_at
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self.resource_allocations_table).where(
                    self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                    self.resource_allocations_table.c.unit == rloan.UNIT_GPU_SECOND,
                )
            ).mappings().one_or_none()
        if row is None:
            raise ValueError(f"Unknown Slurm allocation: {slurm_job_id}")
        elapsed_seconds = max(0, math.ceil(timestamp - float(row["started_at"])))
        return self.settle_allocation_elapsed(
            slurm_job_id,
            elapsed_seconds=elapsed_seconds,
            finished_at=timestamp,
        )

    def settle_allocation_elapsed(
        self,
        slurm_job_id: str,
        *,
        elapsed_seconds: int,
        finished_at: float | None = None,
        evidence_source: str = rloan.EvidenceSource.ALLOCATION_LIFECYCLE.value,
    ) -> dict[str, Any]:
        """Settle every unit of one allocation from one authoritative elapsed time.

        Usage is recorded per unit from the *allocation*, never from utilization:
        ``resource_count`` is what the scheduler allocated (GPUs for
        ``gpu_second``, cores for ``cpu_core_second``) and ``elapsed_seconds`` is
        the authoritative allocation duration, so a GPU Task and a CPU-only Task
        are each charged for exactly what they held.

        Idempotent by construction: each unit's fact has its own
        ``usage:<unit>:<slurm_job_id>`` key, and a unit already settled is left
        exactly as recorded — a lost response, a retried callback, and a
        reconciliation pass all observe the same single fact.  Each unit carries
        its own status, so ``mark_allocation_for_review`` marking one unknown
        leaves the other settleable and no unit is ever charged a fabricated
        zero.
        """
        if elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be non-negative")
        timestamp = time.time() if finished_at is None else finished_at
        with self.engine.begin() as conn:
            rows = (
                conn.execute(
                    select(self.resource_allocations_table)
                    .where(self.resource_allocations_table.c.slurm_job_id == slurm_job_id)
                    .order_by(self.resource_allocations_table.c.unit)
                )
                .mappings()
                .all()
            )
            if not rows:
                raise ValueError(f"Unknown Slurm allocation: {slurm_job_id}")
            gpu_row = None
            for row in rows:
                if str(row["unit"]) == rloan.UNIT_GPU_SECOND:
                    gpu_row = row
                if row["status"] == rloan.AllocationStatus.SETTLED.value:
                    continue
                if row["resource_count"] is None:
                    # The allocation's shape was never recorded — the scheduler's
                    # own output file proves it held a node, but nothing says how
                    # many GPUs or cores it held.  Charging it would invent a
                    # quantity, and charging it zero would report a real
                    # allocation as no usage at all, so it is left for an
                    # operator: the elapsed time is known now, but the fact it
                    # would multiply is not.
                    conn.execute(
                        update(self.resource_allocations_table)
                        .where(self.resource_allocations_table.c.id == row["id"])
                        .values(
                            status=rloan.AllocationStatus.REVIEW.value,
                            evidence_source=evidence_source,
                        )
                    )
                    continue
                allocated = int(row["resource_count"])
                if allocated <= 0:
                    # The allocation held none of this unit — a CPU-only Task
                    # holds no GPU.  There is no consumption to record, and a
                    # zero-quantity usage fact would be a ledger row claiming a
                    # measurement where the truth is simply "none allocated".
                    conn.execute(
                        update(self.resource_allocations_table)
                        .where(self.resource_allocations_table.c.id == row["id"])
                        .values(
                            finished_at=timestamp,
                            quantity=0,
                            status=rloan.AllocationStatus.SETTLED.value,
                            evidence_source=evidence_source,
                            ledger_entry_id=None,
                        )
                    )
                    continue
                quantity = allocated * elapsed_seconds
                idempotency_key = f"usage:{row['unit']}:{slurm_job_id}"
                result = conn.execute(
                    sqlite_insert(self.resource_ledger_table)
                    .values(
                        subject_type=rloan.SUBJECT_USER,
                        subject_id=row["subject_id"],
                        period=self._period_for_unit(row["unit"], float(row["started_at"])),
                        kind=rloan.LedgerKind.USAGE.value,
                        unit=row["unit"],
                        resource_class=row["resource_class"],
                        quantity=-quantity,
                        task_id=row["task_id"],
                        stage_id=row["stage_id"],
                        slurm_job_id=slurm_job_id,
                        actor_user_id=None,
                        reason="Actual Slurm allocation time",
                        reason_code=rloan.LedgerReason.ACTUAL_ALLOCATION.value,
                        evidence_source=evidence_source,
                        idempotency_key=idempotency_key,
                        created_at=timestamp,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[self.resource_ledger_table.c.idempotency_key]
                    )
                )
                if result.rowcount:
                    ledger_id = result.inserted_primary_key[0]
                else:
                    ledger_id = conn.execute(
                        select(self.resource_ledger_table.c.id).where(
                            self.resource_ledger_table.c.idempotency_key == idempotency_key
                        )
                    ).scalar_one()
                conn.execute(
                    update(self.resource_allocations_table)
                    .where(self.resource_allocations_table.c.id == row["id"])
                    .values(
                        finished_at=timestamp,
                        quantity=quantity,
                        status=rloan.AllocationStatus.SETTLED.value,
                        evidence_source=evidence_source,
                        ledger_entry_id=ledger_id,
                    )
                )
            settled = (
                conn.execute(
                    select(self.resource_allocations_table).where(
                        self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                        self.resource_allocations_table.c.unit == rloan.UNIT_GPU_SECOND,
                    )
                )
                .mappings()
                .one_or_none()
            )
        if settled is not None:
            return dict(settled)
        # No GPU fact exists for this job (it was recorded by the migrated
        # CPU-only path), so answer with the unit that does.
        return dict(rows[0])

    def mark_allocation_for_review(self, slurm_job_id: str) -> bool:
        """Expose the units of one allocation whose authoritative elapsed time is unavailable.

        Returns whether the allocation had anything left to review, and marks
        every unsettled unit — an unknown elapsed duration is a fact about the
        allocation, not about one of its units, so a GPU fact and a CPU fact that
        shared the allocation must not disagree about it.
        """
        stmt = (
            update(self.resource_allocations_table)
            .where(
                self.resource_allocations_table.c.slurm_job_id == slurm_job_id,
                self.resource_allocations_table.c.status != rloan.AllocationStatus.SETTLED.value,
            )
            .values(status=rloan.AllocationStatus.REVIEW.value)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount >= 1

    def list_unsettled_allocations(self) -> list[dict[str, Any]]:
        """Every unit fact still awaiting its authoritative elapsed duration.

        Ordered by allocation start and then by unit, so a caller reading
        ``[0]`` gets the ``cpu_core_second`` fact of the allocation, exactly as
        it got the sole fact before the CPU unit existed.
        """
        stmt = (
            select(self.resource_allocations_table)
            .where(
                self.resource_allocations_table.c.status.in_(
                    (rloan.AllocationStatus.ACTIVE.value, rloan.AllocationStatus.REVIEW.value)
                )
            )
            .order_by(
                self.resource_allocations_table.c.started_at,
                self.resource_allocations_table.c.unit,
                self.resource_allocations_table.c.id,
            )
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    def list_task_allocations(self, task_id: str) -> list[dict[str, Any]]:
        """Return allocation audit rows for one Task, ordered by allocation start."""
        stmt = (
            select(self.resource_allocations_table)
            .where(self.resource_allocations_table.c.task_id == task_id)
            .order_by(self.resource_allocations_table.c.started_at, self.resource_allocations_table.c.id)
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    # -- Admission reservations ---------------------------------------------

    @staticmethod
    def _reservation_id() -> str:
        return secrets.token_hex(16)

    def reserve_compute_admission(
        self,
        *,
        user_id: int,
        task_id: str,
        gres: str = "",
        at: float | None = None,
        ttl_seconds: float = rloan.RESERVATION_TTL_SECONDS,
        reason_code: str = rloan.ReservationReason.ADMISSION_RESERVED.value,
    ) -> dict[str, Any]:
        """Take a race-safe pre-dispatch admission reservation for one Task, or refuse.

        The decision and the reservation are one ``BEGIN IMMEDIATE`` transaction,
        so a remaining-quota check is never a read-then-act race: two concurrent
        submissions competing for the final entitlement cannot both take it.
        The reservation is bounded by policy (see
        :func:`resource_ledger.admission_hold_quantity`) and capped by the
        remaining balance, so the *last* unit of entitlement admits exactly one
        submission and the other gets an explicit refusal instead of being
        dispatched anyway.

        What comes back is a *pre-dispatch* reservation: it carries the TTL that
        bounds the submit-to-dispatch window, and it stops being TTL-reclaimable
        the moment the Slurm request is dispatched
        (:meth:`record_reservation_dispatch`).  Counting it as committed
        entitlement is what keeps a second submission from re-taking the final
        unit while this one is still on its way to the scheduler.

        The allowance is deployment-wide, so the decision is made on the
        class-agnostic scope: a request for ``a100`` consumes the same balance a
        request for an untyped GPU would, and the requested class is preserved on
        the reservation and the resulting allocation rather than opening a
        per-class budget.  ``gres`` is therefore recorded, not enforced.
        """
        timestamp = time.time() if at is None else at
        resource_class = rloan.resource_class_for_gres(gres)
        period = self._gpu_period(timestamp)
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                self._ensure_monthly_grant(conn, user_id, period, "", timestamp)
                rows = conn.execute(
                    select(self.resource_ledger_table).where(
                        self.resource_ledger_table.c.subject_type == rloan.SUBJECT_USER,
                        self.resource_ledger_table.c.subject_id == user_id,
                        self.resource_ledger_table.c.unit == rloan.UNIT_GPU_SECOND,
                        self.resource_ledger_table.c.period == period,
                    )
                ).mappings().all()
                totals = rloan.summarize_ledger(
                    rows, unit=rloan.UNIT_GPU_SECOND, resource_class="", period=period
                )
                committed = self._committed_reservation_quantity_in_connection(
                    conn, user_id, rloan.UNIT_GPU_SECOND
                )
                remaining = int(totals["remaining"]) - committed
                # Unsettled usage is a known lower bound, not a zero.  The hold
                # is taken against the balance *after* reserving the worst case
                # of what is already running, so a user whose authoritative
                # elapsed time is still unknown is never admitted as if they had
                # consumed nothing.
                _, unsettled = self._unsettled_in_connection(
                    conn, user_id, rloan.UNIT_GPU_SECOND, "", timestamp
                )
                remaining -= unsettled
                quantity = rloan.admission_hold_quantity(remaining, rloan.UNIT_GPU_SECOND)
                if quantity <= 0:
                    conn.commit()
                    return {
                        "allowed": False,
                        "reason_code": rloan.AdmissionReason.COMPUTE_EXHAUSTED.value,
                        "reservation_id": None,
                        "quantity": 0,
                        "remaining": remaining,
                        "unsettled": unsettled,
                        "resource_class": resource_class,
                        "period": period,
                    }
                reservation_id = self._reservation_id()
                inserted = conn.execute(
                    sqlite_insert(self.resource_reservations_table)
                    .values(
                        id=reservation_id,
                        subject_type=rloan.SUBJECT_USER,
                        subject_id=user_id,
                        unit=rloan.UNIT_GPU_SECOND,
                        resource_class=resource_class,
                        quantity=quantity,
                        task_id=task_id,
                        state=rloan.ReservationState.HELD.value,
                        reason_code=reason_code,
                        created_at=timestamp,
                        expires_at=timestamp + ttl_seconds,
                        dispatched_at=None,
                        scheduler_job_id=None,
                        released_at=None,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[self.resource_reservations_table.c.task_id],
                        index_where=text("state IN ('held', 'queued')"),
                    )
                )
                if not inserted.rowcount:
                    # This Task already holds entitlement.  Answering with a
                    # bounded refusal keeps the caller on its decision path: a
                    # resubmission of a Task whose hold is still live is exactly
                    # the case the caller already knows how to report.
                    conn.commit()
                    return {
                        "allowed": False,
                        "reason_code": rloan.AdmissionReason.COMPUTE_EXHAUSTED.value,
                        "reservation_id": None,
                        "quantity": 0,
                        "remaining": remaining,
                        "unsettled": unsettled,
                        "resource_class": resource_class,
                        "period": period,
                    }
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {
            "allowed": True,
            "reason_code": reason_code,
            "reservation_id": reservation_id,
            "quantity": quantity,
            "remaining": remaining - quantity,
            "unsettled": unsettled,
            "resource_class": resource_class,
            "period": period,
        }

    def _committed_reservation_quantity_in_connection(self, conn, user_id: int, unit: str) -> int:
        """Live entitlement staked by this subject, in *unit*.

        Both ownership modes count: a pre-dispatch reservation the submitter is
        still dispatching and a scheduler-owned queued commitment are the same
        claim on the balance, and a balance that counted only one of them would
        hand the final entitlement out twice.
        """
        return int(
            conn.execute(
                select(func.coalesce(func.sum(self.resource_reservations_table.c.quantity), 0)).where(
                    self.resource_reservations_table.c.subject_id == user_id,
                    self.resource_reservations_table.c.unit == unit,
                    self.resource_reservations_table.c.state.in_(rloan.COMMITTED_RESERVATION_STATES),
                )
            ).scalar_one()
        )

    def record_reservation_dispatch(
        self, *, task_id: str, slurm_job_id: str, at: float | None = None
    ) -> bool:
        """Hand a Task's reservation to the scheduler: held -> queued.

        Called once the Slurm request actually exists.  After this the
        reservation has no wall-clock expiry — it is owned by that Task until a
        canonical transition releases it — because the request may legitimately
        wait in the scheduler's queue for longer than any TTL, and reclaiming it
        meanwhile would let a competing submission consume entitlement the
        queued request is about to use.

        ``slurm_job_id`` is written in the same statement as the state change, so
        a queued reservation is never observable without the scheduler identity
        that justifies it.  That is what makes the maintenance reclaim safe: a
        pass reading this row always sees the request's own name, so it can never
        mistake a mid-dispatch window for "no request exists".  Idempotent and
        race-safe: only a live ``held`` row transitions, and a second call for an
        already-queued or already-released Task is a no-op returning ``False``.
        """
        timestamp = time.time() if at is None else at
        with self.engine.begin() as conn:
            result = conn.execute(
                update(self.resource_reservations_table)
                .where(
                    self.resource_reservations_table.c.task_id == task_id,
                    self.resource_reservations_table.c.state == rloan.ReservationState.HELD.value,
                )
                .values(
                    state=rloan.ReservationState.QUEUED.value,
                    reason_code=rloan.ReservationReason.DISPATCHED.value,
                    dispatched_at=timestamp,
                    scheduler_job_id=str(slurm_job_id),
                    expires_at=None,
                )
            )
            return result.rowcount == 1

    def _authorize_allocation_start_in_connection(
        self, conn, *, user_id: int, task_id: str, at: float, slurm_job_id: str
    ) -> tuple[int, bool]:
        """Admit one allocation start against the balance *without* its own hold.

        A live reservation owned by *task_id* is this Task's admission authority:
        the hold that got the submission past admission is not also a competing
        claim on the same balance, so a Task holding the final entitlement is
        never refused by its own reservation.  Every OTHER committed reservation
        (another Task's hold or queued commitment) and every unsettled allocation
        still counts, so the atomic decision is as strict as admission was.

        With no live hold for this Task — a reservation that expired while the
        request waited, or a later workflow stage whose predecessor already
        consumed one — the current balance is re-evaluated here in the same
        transaction that writes the allocation, and the allocation is refused
        rather than charged against a balance that cannot cover it.

        Returns ``(remaining_from_this_decision, own_hold_is_authority)``, which
        the caller reports: the pair says both what the balance looked like and
        whether the Task was admitted on its own reservation or on permission
        that had to be re-established.

        Called inside ``BEGIN IMMEDIATE``, so the answer and the rows it
        authorizes are one decision: no separate reader can see a different
        entitlement than the one this transition acted on.
        """
        period = self._gpu_period(at)
        self._ensure_monthly_grant(conn, user_id, period, "", at)
        rows = conn.execute(
            select(self.resource_ledger_table).where(
                self.resource_ledger_table.c.subject_type == rloan.SUBJECT_USER,
                self.resource_ledger_table.c.subject_id == user_id,
                self.resource_ledger_table.c.unit == rloan.UNIT_GPU_SECOND,
                self.resource_ledger_table.c.period == period,
            )
        ).mappings().all()
        totals = rloan.summarize_ledger(rows, unit=rloan.UNIT_GPU_SECOND, resource_class="", period=period)
        own_hold = conn.execute(
            select(func.coalesce(func.sum(self.resource_reservations_table.c.quantity), 0)).where(
                self.resource_reservations_table.c.task_id == task_id,
                self.resource_reservations_table.c.unit == rloan.UNIT_GPU_SECOND,
                self.resource_reservations_table.c.state.in_(rloan.COMMITTED_RESERVATION_STATES),
            )
        ).scalar_one()
        other_holds = conn.execute(
            select(func.coalesce(func.sum(self.resource_reservations_table.c.quantity), 0)).where(
                self.resource_reservations_table.c.subject_id == user_id,
                self.resource_reservations_table.c.unit == rloan.UNIT_GPU_SECOND,
                self.resource_reservations_table.c.state.in_(rloan.COMMITTED_RESERVATION_STATES),
                self.resource_reservations_table.c.task_id != task_id,
            )
        ).scalar_one()
        _, unsettled = self._unsettled_in_connection(
            conn, user_id, rloan.UNIT_GPU_SECOND, "", at, exclude_slurm_job_id=slurm_job_id
        )
        remaining = int(totals["remaining"]) - int(other_holds) - int(unsettled)
        # A live reservation owned by this Task is its authority — but only
        # while the position it was admitted against still stands.  ``own_hold``
        # is excluded from ``remaining``, so it is added back for the test: the
        # Task is fine as long as its own unit (plus whatever is left, if that
        # is positive) covers the negative side, which is the overdraft case the
        # account deliberately allows.  When other work of the same subject has
        # since spent the balance the Task was admitted on, the hold no longer
        # buys anything and the start falls through to the refusal rather than
        # charging a balance that cannot cover it — the same answer an identical
        # start without a hold gets.
        if int(own_hold) > 0:
            position = remaining + int(own_hold)
            if position >= 0:
                return remaining, True
        if remaining <= 0:
            raise GPUCreditUnavailableError("GPU credit balance is exhausted")
        return remaining, False

    def _release_reservation_in_connection(
        self, conn, *, task_id: str, reason_code: str, released_at: float
    ) -> bool:
        """Release one Task's live reservation, whichever ownership mode it holds.

        A release is a canonical transition (allocation started, dispatch failed,
        Task deleted, or an explicit release) and applies to a pre-dispatch hold
        and a queued commitment alike; only a TTL expiry is restricted to the
        pre-dispatch state.
        """
        result = conn.execute(
            update(self.resource_reservations_table)
            .where(
                self.resource_reservations_table.c.task_id == task_id,
                self.resource_reservations_table.c.state.in_(rloan.COMMITTED_RESERVATION_STATES),
            )
            .values(state=rloan.ReservationState.RELEASED.value, reason_code=reason_code, released_at=released_at)
        )
        return result.rowcount == 1

    def release_reservation(
        self, *, task_id: str, reason_code: str = rloan.ReservationReason.RELEASED.value, at: float | None = None
    ) -> bool:
        """Release this Task's live hold.  Idempotent: a second call is a no-op.

        The hold is a claim on entitlement a submission has not consumed, so
        releasing it is a real admission fact and is reported as one.  A no-op
        release emits nothing: there was no live claim to give back.
        """
        timestamp = time.time() if at is None else at
        with self.engine.begin() as conn:
            released = self._release_reservation_in_connection(
                conn, task_id=task_id, reason_code=reason_code, released_at=timestamp
            )
        if released:
            emit_event(
                "resource.admission.released",
                task_id=task_id,
                reason_code=reason_code,
            )
        return released

    def list_reservations(
        self, *, user_id: int | None = None, state: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 2000:
            raise ValueError("limit must be between 1 and 2000")
        stmt = select(self.resource_reservations_table)
        if user_id is not None:
            stmt = stmt.where(self.resource_reservations_table.c.subject_id == user_id)
        if state is not None:
            stmt = stmt.where(self.resource_reservations_table.c.state == state)
        stmt = stmt.order_by(desc(self.resource_reservations_table.c.created_at)).limit(limit)
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    def expire_stale_reservations(
        self, *, now: float | None = None, unadopted_tasks: Iterable[str] | None = None
    ) -> int:
        """Reclaim lapsed *pre-dispatch* reservations.  Safe to run repeatedly.

        Only a ``held`` reservation has a wall-clock expiry: it spans
        submit -> dispatch, and a submission that died in that window would
        otherwise keep entitlement nothing can consume.  A ``queued``
        reservation is scheduler-owned and deliberately has no expiry — the
        Slurm request it belongs to may still be waiting, so reclaiming it on a
        timer would hand the same entitlement to a second submission.  Those are
        reclaimed by :meth:`reclaim_queued_reservation` against scheduler
        evidence instead.

        A ``held`` reservation whose Task already has a wrapper receipt is a
        third case: the compute node proved the wrapper was running, so the
        allocation is real even though the dispatch write never happened.  The
        timer must not expire it — it is handed to the receipt reconciliation
        instead, which records the allocation and settles it.

        ``unadopted_tasks`` is that third case's *surviving* form: the Task ids
        whose host-only ``allocation.receipt`` file is still on disk, reported by
        the pass that walked the allocation namespace.  It is needed here because
        the durable receipt row is only written once a worker has *adopted* the
        file, and the whole point of the file is the window before that.  A hold
        whose receipt exists but has not yet been adopted is still a real
        allocation, so it is excluded from expiry exactly as an adopted one is.
        """
        timestamp = time.time() if now is None else now
        receipted = {str(row["task_id"]) for row in self.list_allocation_receipts()}
        receipted.update(str(task_id) for task_id in (unadopted_tasks or ()) if task_id)
        with self.engine.begin() as conn:
            conditions = [
                self.resource_reservations_table.c.state == rloan.ReservationState.HELD.value,
                self.resource_reservations_table.c.expires_at.is_not(None),
                self.resource_reservations_table.c.expires_at <= timestamp,
            ]
            if receipted:
                conditions.append(
                    self.resource_reservations_table.c.task_id.notin_(receipted)
                )
            result = conn.execute(
                update(self.resource_reservations_table)
                .where(*conditions)
                .values(state=rloan.ReservationState.EXPIRED.value, released_at=timestamp)
            )
            return result.rowcount

    def list_queued_reservations(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Scheduler-owned commitments, oldest first: the ones only evidence may free."""
        stmt = (
            select(self.resource_reservations_table)
            .where(self.resource_reservations_table.c.state == rloan.ReservationState.QUEUED.value)
            .order_by(self.resource_reservations_table.c.created_at)
            .limit(limit)
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    def list_task_reservations(self, task_id: str) -> list[dict[str, Any]]:
        """Every reservation of one Task, newest first: its admission evidence.

        A Task has at most one live row; the earlier ones are the history of how
        it was admitted, released, or reclaimed, and they stay readable here
        rather than being rewritten by the transition that replaced them.
        """
        stmt = (
            select(self.resource_reservations_table)
            .where(self.resource_reservations_table.c.task_id == task_id)
            .order_by(desc(self.resource_reservations_table.c.created_at))
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    def reclaim_queued_reservation(
        self, *, task_id: str, reason_code: str = rloan.ReservationReason.RELEASED.value, at: float | None = None
    ) -> bool:
        """Free a scheduler-owned commitment that evidence proves is abandoned.

        This is the only way a ``queued`` reservation can stop being committed
        without a canonical allocation/delete/dispatch transition, so the caller
        is responsible for the evidence: the scheduler has proved the request no
        longer exists (a terminal or unknown ``scontrol`` state), or the
        reconciliation believes this Task is an abandoned pre-dispatch crash
        with no scheduler request at all.  ``reason_code`` records which evidence
        it was, so the release stays auditable.  Idempotent and race-safe.
        """
        timestamp = time.time() if at is None else at
        with self.engine.begin() as conn:
            result = conn.execute(
                update(self.resource_reservations_table)
                .where(
                    self.resource_reservations_table.c.task_id == task_id,
                    self.resource_reservations_table.c.state == rloan.ReservationState.QUEUED.value,
                )
                .values(state=rloan.ReservationState.RELEASED.value, reason_code=reason_code, released_at=timestamp)
            )
            return result.rowcount == 1

    def list_live_reservations(self, *, limit: int = 2000) -> list[dict[str, Any]]:
        """Every committed reservation, whichever ownership mode it holds.

        Reconciliation reads this rather than only the queued ones: a hold that
        lapsed while its submission was still on its way to the scheduler is a
        separate decision (scheduler evidence says whether the request ever
        existed), and the two must not be conflated into one timeout.
        """
        stmt = (
            select(self.resource_reservations_table)
            .where(self.resource_reservations_table.c.state.in_(rloan.COMMITTED_RESERVATION_STATES))
            .order_by(self.resource_reservations_table.c.created_at)
            .limit(limit)
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    # -- Data lifecycle -----------------------------------------------------

    def get_data_lifecycle(self, task_id: str) -> dict[str, Any] | None:
        stmt = select(self.data_lifecycle_table).where(self.data_lifecycle_table.c.task_id == task_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        return dict(row) if row else None

    def ensure_data_lifecycle(
        self,
        task_id: str,
        *,
        user_id: int,
        logical_bytes: int = 0,
        at: float | None = None,
        allow_reopen: bool = False,
    ) -> dict[str, Any]:
        """Register one Task's durable data and charge its logical ownership once.

        The size is the *logical* ownership fact, never a directory-size guess
        at charge time.  A first registration appends one ``storage_usage`` fact
        and records how much was charged (``accounted_bytes``), which is what a
        later purge may release — so a partial purge frees nothing it was not
        charged for, and a completed purge frees it exactly once.

        Republishing after a purge re-opens the Task's data: a ``PURGED`` row is
        a lifecycle *state*, not a tombstone, and bytes that are back on disk must
        be charged again or the user gets quota for free.  Each charge carries a
        monotonic charge revision, so a re-charge is a distinct idempotent fact
        rather than a duplicate of the first one.

        ``allow_reopen`` is the explicit publication transition for a Task whose
        bytes really came back after a purge: only a caller that has established
        that may re-open a ``PURGED`` row and charge it again.  Every other
        caller -- a live publication charge, a repair pass -- uses the guarded
        :meth:`charge_data_ownership` instead, because an unconditional reopen
        would let a stale charge re-open a deletion that already happened.
        """
        if user_id <= 0:
            raise ValueError("Data ownership requires an owning user")
        if not allow_reopen:
            self.charge_data_ownership(task_id, user_id=user_id, logical_bytes=logical_bytes, at=at)
            record = self.get_data_lifecycle(task_id)
            if record is None:
                raise RuntimeError("The guarded ownership transition yielded no lifecycle row")
            return record
        timestamp = time.time() if at is None else at
        size = max(0, int(logical_bytes))
        with self.engine.begin() as conn:
            existing = (
                conn.execute(
                    select(self.data_lifecycle_table).where(self.data_lifecycle_table.c.task_id == task_id)
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                # Two workers can publish the same Task concurrently.  The
                # loser must not raise: the insert is conditional on the row
                # still being absent, and whoever loses simply re-reads the
                # winner's row (and does not charge a second time).
                claimed = conn.execute(
                    sqlite_insert(self.data_lifecycle_table)
                    .values(
                        task_id=task_id,
                        subject_type=rloan.SUBJECT_USER,
                        subject_id=user_id,
                        state=rloan.DataLifecycleState.ACTIVE.value,
                        logical_bytes=size,
                        accounted_bytes=size,
                        charge_revision=1,
                        updated_at=timestamp,
                    )
                    .on_conflict_do_nothing(index_elements=[self.data_lifecycle_table.c.task_id])
                )
                if not claimed.rowcount:
                    existing = (
                        conn.execute(
                            select(self.data_lifecycle_table).where(
                                self.data_lifecycle_table.c.task_id == task_id
                            )
                        )
                        .mappings()
                        .one()
                    )
                else:
                    self._append_storage_fact(
                        conn,
                        user_id=user_id,
                        task_id=task_id,
                        quantity=-size,
                        reason="Durable result published",
                        reason_code=rloan.LedgerReason.STORAGE_CHARGED.value,
                        idempotency_key=f"storage_usage:{task_id}:1",
                        timestamp=timestamp,
                    )
                    existing = (
                        conn.execute(
                            select(self.data_lifecycle_table).where(
                                self.data_lifecycle_table.c.task_id == task_id
                            )
                        )
                        .mappings()
                        .one()
                    )
                return dict(existing)
            if str(existing["state"]) == rloan.DataLifecycleState.PURGED.value:
                # The data came back.  Charge the new ownership under the next
                # charge revision, so the purge's release stays a fact of history
                # and this is a new fact rather than a rewrite of it.
                revision = int(existing["charge_revision"]) + 1
                conn.execute(
                    update(self.data_lifecycle_table)
                    .where(
                        self.data_lifecycle_table.c.task_id == task_id,
                        self.data_lifecycle_table.c.state == rloan.DataLifecycleState.PURGED.value,
                    )
                    .values(
                        state=rloan.DataLifecycleState.ACTIVE.value,
                        logical_bytes=size,
                        accounted_bytes=size,
                        charge_revision=revision,
                        purged_at=None,
                        updated_at=timestamp,
                    )
                )
                if size:
                    self._append_storage_fact(
                        conn,
                        user_id=user_id,
                        task_id=task_id,
                        quantity=-size,
                        reason="Durable result republished",
                        reason_code=rloan.LedgerReason.STORAGE_CHARGED.value,
                        idempotency_key=f"storage_usage:{task_id}:{revision}",
                        timestamp=timestamp,
                    )
            elif int(existing["logical_bytes"]) != size:
                # A recomputation that finds a different size updates the
                # logical fact.  The ledger fact stays as charged until a purge
                # releases exactly it, so no reconciliation pass can double-count.
                conn.execute(
                    update(self.data_lifecycle_table)
                    .where(self.data_lifecycle_table.c.task_id == task_id)
                    .values(logical_bytes=size, updated_at=timestamp)
                )
            row = (
                conn.execute(
                    select(self.data_lifecycle_table).where(self.data_lifecycle_table.c.task_id == task_id)
                )
                .mappings()
                .one()
            )
        return dict(row)

    def _append_storage_fact(
        self,
        conn,
        *,
        user_id: int,
        task_id: str,
        quantity: int,
        reason: str,
        reason_code: str,
        idempotency_key: str,
        timestamp: float,
    ) -> None:
        conn.execute(
            sqlite_insert(self.resource_ledger_table)
            .values(
                subject_type=rloan.SUBJECT_USER,
                subject_id=user_id,
                period="",
                kind=rloan.LedgerKind.STORAGE_USAGE.value,
                unit=rloan.UNIT_STORAGE_BYTE,
                resource_class="",
                quantity=quantity,
                task_id=task_id,
                stage_id=None,
                slurm_job_id=None,
                actor_user_id=None,
                reason=reason,
                reason_code=reason_code,
                evidence_source=rloan.EvidenceSource.ALLOCATION_LIFECYCLE.value,
                idempotency_key=idempotency_key,
                created_at=timestamp,
            )
            .on_conflict_do_nothing(index_elements=[self.resource_ledger_table.c.idempotency_key])
        )

    def claim_data_deletion(
        self,
        task_id: str,
        *,
        user_id: int,
        actor_user_id: int | None = None,
        at: float | None = None,
    ) -> bool:
        """Move one Task into ``DELETE_REQUESTED``, durably, before any deletion.

        The state write is the claim: a crash after it leaves a resumable
        deletion rather than an intact tree whose row still reads ``ACTIVE``.
        Idempotent for a row already awaiting or in purge.
        """
        timestamp = time.time() if at is None else at
        terminal = (
            rloan.DataLifecycleState.DELETE_REQUESTED.value,
            rloan.DataLifecycleState.PURGING.value,
        )
        with self.engine.begin() as conn:
            existing = (
                conn.execute(
                    select(self.data_lifecycle_table).where(self.data_lifecycle_table.c.task_id == task_id)
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                conn.execute(
                    sqlite_insert(self.data_lifecycle_table).values(
                        task_id=task_id,
                        subject_type=rloan.SUBJECT_USER,
                        subject_id=user_id,
                        state=rloan.DataLifecycleState.DELETE_REQUESTED.value,
                        logical_bytes=0,
                        accounted_bytes=0,
                        charge_revision=0,
                        requested_by_user_id=actor_user_id,
                        requested_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                return True
            if existing["state"] in terminal:
                return False
            result = conn.execute(
                update(self.data_lifecycle_table)
                .where(
                    self.data_lifecycle_table.c.task_id == task_id,
                    self.data_lifecycle_table.c.state.notin_(terminal),
                )
                .values(
                    state=rloan.DataLifecycleState.DELETE_REQUESTED.value,
                    requested_by_user_id=actor_user_id,
                    requested_at=timestamp,
                    updated_at=timestamp,
                )
            )
            return result.rowcount == 1

    def begin_data_purge(self, task_id: str, *, at: float | None = None) -> bool:
        """Claim a ``DELETE_REQUESTED`` Task for destructive work."""
        timestamp = time.time() if at is None else at
        stmt = (
            update(self.data_lifecycle_table)
            .where(
                self.data_lifecycle_table.c.task_id == task_id,
                self.data_lifecycle_table.c.state == rloan.DataLifecycleState.DELETE_REQUESTED.value,
            )
            .values(state=rloan.DataLifecycleState.PURGING.value, claimed_at=timestamp, updated_at=timestamp)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def complete_data_purge(self, task_id: str, *, at: float | None = None) -> bool:
        """Mark a ``PURGING`` Task ``PURGED`` and release exactly its charged bytes.

        Quota is freed only here — after the owned bytes are actually gone — and
        only by the amount the ledger was charged.  A partial purge that never
        reaches this point frees nothing, so it cannot create phantom free
        quota; a repeated call is a no-op because the state guard admits it once.
        """
        timestamp = time.time() if at is None else at
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    select(self.data_lifecycle_table).where(self.data_lifecycle_table.c.task_id == task_id)
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["state"] != rloan.DataLifecycleState.PURGING.value:
                return False
            charged = int(row["accounted_bytes"])
            revision = int(row["charge_revision"]) + 1
            # Both the release and the PURGED write are conditional on the row
            # still being PURGING, inside one transaction.  Two concurrent
            # completions therefore append the fact at most once: the loser
            # observes no row and returns False instead of freeing the quota a
            # second time.
            if charged:
                # INSERT ... SELECT: the release exists only if the row is still
                # PURGING at the moment SQLite evaluates it, and the same
                # condition gates the PURGED write below, inside this one
                # transaction.  Two concurrent completions therefore append the
                # fact at most once — the loser inserts no row and returns False
                # rather than freeing the quota a second time.
                release_from = select(
                    literal(rloan.SUBJECT_USER),
                    literal(int(row["subject_id"])),
                    literal(""),
                    literal(rloan.LedgerKind.STORAGE_USAGE.value),
                    literal(rloan.UNIT_STORAGE_BYTE),
                    literal(""),
                    literal(charged),
                    literal(task_id),
                    literal(None),
                    literal(None),
                    literal(None),
                    literal("Owned bytes purged"),
                    literal(rloan.LedgerReason.STORAGE_RELEASED.value),
                    literal(rloan.EvidenceSource.ALLOCATION_LIFECYCLE.value),
                    literal(f"storage_usage:{task_id}:{revision}"),
                    literal(timestamp),
                ).select_from(self.data_lifecycle_table).where(
                    self.data_lifecycle_table.c.task_id == task_id,
                    self.data_lifecycle_table.c.state == rloan.DataLifecycleState.PURGING.value,
                )
                released = conn.execute(
                    sqlite_insert(self.resource_ledger_table)
                    .from_select(
                        ["subject_type", "subject_id", "period", "kind", "unit", "resource_class",
                         "quantity", "task_id", "stage_id", "slurm_job_id", "actor_user_id",
                         "reason", "reason_code", "evidence_source", "idempotency_key", "created_at"],
                        release_from,
                    )
                    .on_conflict_do_nothing(index_elements=[self.resource_ledger_table.c.idempotency_key])
                )
                if not released.rowcount:
                    return False
            completed = conn.execute(
                update(self.data_lifecycle_table)
                .where(
                    self.data_lifecycle_table.c.task_id == task_id,
                    self.data_lifecycle_table.c.state == rloan.DataLifecycleState.PURGING.value,
                )
                .values(
                    state=rloan.DataLifecycleState.PURGED.value,
                    logical_bytes=0,
                    accounted_bytes=0,
                    charge_revision=revision,
                    purged_at=timestamp,
                    updated_at=timestamp,
                    error="",
                )
            )
            if completed.rowcount:
                # The purge is the authority on these bytes, so it also closes the
                # publication's charge marker in the same transaction: the bytes
                # are gone, and a repair pass must never re-charge a release the
                # lifecycle already made.
                conn.execute(
                    update(self.result_publications_table)
                    .where(
                        self.result_publications_table.c.task_id == task_id,
                        self.result_publications_table.c.charge_state != "released",
                    )
                    .values(charge_state="released")
                )
            return completed.rowcount == 1

    def mark_data_lifecycle_error(self, task_id: str, *, error: str, at: float | None = None) -> bool:
        """Record a purging Task that could not be completed, without freeing quota."""
        timestamp = time.time() if at is None else at
        stmt = (
            update(self.data_lifecycle_table)
            .where(
                self.data_lifecycle_table.c.task_id == task_id,
                self.data_lifecycle_table.c.state == rloan.DataLifecycleState.PURGING.value,
            )
            .values(state=rloan.DataLifecycleState.ERROR.value, error=str(error)[:2000], updated_at=timestamp)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def requeue_data_lifecycle(self, task_id: str, *, at: float | None = None) -> bool:
        """Return a failed purge to ``DELETE_REQUESTED`` so a later pass retries it."""
        timestamp = time.time() if at is None else at
        stmt = (
            update(self.data_lifecycle_table)
            .where(
                self.data_lifecycle_table.c.task_id == task_id,
                self.data_lifecycle_table.c.state == rloan.DataLifecycleState.ERROR.value,
            )
            .values(state=rloan.DataLifecycleState.DELETE_REQUESTED.value, updated_at=timestamp)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def reclaim_stale_purge(self, task_id: str, *, at: float | None = None) -> bool:
        """Return an abandoned ``PURGING`` claim to ``DELETE_REQUESTED``.

        The caller owns the staleness decision — it is the only party that knows
        how long a purge may legitimately run — and this is the transaction that
        makes the reclaim durable.  Without it an interrupted purge can never be
        retried: ``begin_data_purge`` requires ``DELETE_REQUESTED``, so a worker
        that died between its claim and its completion would hold its subject's
        quota forever.
        """
        timestamp = time.time() if at is None else at
        stmt = (
            update(self.data_lifecycle_table)
            .where(
                self.data_lifecycle_table.c.task_id == task_id,
                self.data_lifecycle_table.c.state == rloan.DataLifecycleState.PURGING.value,
            )
            .values(state=rloan.DataLifecycleState.DELETE_REQUESTED.value, updated_at=timestamp)
        )
        with self.engine.begin() as conn:
            return conn.execute(stmt).rowcount == 1

    def list_data_lifecycle(
        self, *, user_id: int | None = None, states: tuple[str, ...] = (), limit: int = 500
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 5000:
            raise ValueError("limit must be between 1 and 5000")
        stmt = select(self.data_lifecycle_table)
        if user_id is not None:
            stmt = stmt.where(self.data_lifecycle_table.c.subject_id == user_id)
        if states:
            stmt = stmt.where(self.data_lifecycle_table.c.state.in_(tuple(states)))
        stmt = stmt.order_by(self.data_lifecycle_table.c.updated_at).limit(limit)
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings().all()]

    def logical_owned_bytes(self, user_id: int) -> int:
        """Logical user-owned durable bytes, from the lifecycle rows themselves."""
        with self.engine.connect() as conn:
            return int(
                conn.execute(
                    select(func.coalesce(func.sum(self.data_lifecycle_table.c.logical_bytes), 0)).where(
                        self.data_lifecycle_table.c.subject_id == user_id,
                        self.data_lifecycle_table.c.state.in_(rloan.CHARGED_LIFECYCLE_STATES),
                    )
                ).scalar_one()
            )
