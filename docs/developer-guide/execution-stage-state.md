# Execution Stage State

> Status: implemented by PR #118. Core owns stage state. No Runner protocol
> change, no stage-selection UI, no artifact reuse (PR #119).

## Problem

A Task's state was written by three authorities: the worker before dispatch,
Core's allocation callbacks, and the Runner's ``REVODESIGN_STAGE:`` stdout
markers. ``_run_compute_workflow`` also wrote ``tasks.status = "queued"`` before
every allocation, so a Task that had completed its CPU stage fell back to
``queued`` while its GPU stage waited. No store recorded *which attempt* ran a
stage, with which planned resources, or why it ended.

## Why the existing stores cannot be the authority

``tasks.workflow_state`` is a single JSON-text compatibility column. It is keyed
by stage name, overwritten by read-modify-write, and has no uniqueness,
transition, or ownership constraint, so duplicate workers can lose an update and
a stale writer can regress a completed stage. It also does not exist for
single-stage Tasks. It can be kept as a **derived projection**, not extended
into the authority.

``resource_allocations`` records **accounting facts** keyed by
``(slurm_job_id, unit)``. It cannot represent a stage attempt before a scheduler
allocation exists (queued dispatch, submission failure, or an attempt that never
got an allocation), carries no attempt number, and has no planned-resource
request. Extending it would put execution state into the ledger's identity.

The missing fact is therefore: *one durable, uniquely-identified stage attempt
that exists before, during, and after a scheduler allocation, with a monotonic
lifecycle.* That needs database-enforced attempt identity, so a ``stage_runs``
table is required. `stage_runs` is the **only** stage authority;
`workflow_state` is written from it as a compatibility mirror, and
`resource_allocations` remains the accounting authority.

## Entities

| Entity | Identity | Authority |
| --- | --- | --- |
| Task | ``tasks.md5sum`` | Core |
| StageDefinition | owning ``task.yaml`` ``workflow[i]`` | Server manifest |
| **StageRun / attempt** | ``(task_id, stage_name, attempt)`` | **Core, durable**; ``stage_index`` is the manifest position stored with the attempt |
| Scheduler allocation | ``slurm_job_id`` | Slurm; accounting in ``resource_allocations`` |
| Progress observation | stdout marker | Runner, advisory |
| Artifact publication | anchored manifest | Core |

A Task with no manifest workflow has one implicit StageDefinition: the Task type
itself at ``stage_index = 0``. stdout markers stay optional progress detail
(``tasks.run_stage``, execution-progress rows); they never create, advance, or
settle a StageRun.

## Statuses and transitions

```text
NOT_STARTED -> QUEUED -> RUNNING -> COMPLETED
     |            |         |- FAILED
     |            |         |- CANCELLED
     |            |         \- INTERRUPTED
     |            \- COMPLETED (missed start) / FAILED / CANCELLED / INTERRUPTED
     \- CANCELLED
```

Transitions are enforced by each guarded UPDATE's predicate (the legal-predecessor
set); attempt identity is enforced by unique indexes. Terminal statuses
(``COMPLETED``, ``FAILED``, ``CANCELLED``, ``INTERRUPTED``) have no outgoing
edge, so late markers and stale/duplicate callbacks cannot regress an attempt.
``NOT_STARTED`` is not stored: it is what the API reports for a declared stage
with no record, and every attempt opens directly in ``QUEUED``. A future stage
selector adds its own skipped state together with the writer that produces it;
the contract does not pre-declare one.

**Retries.** One attempt = one allocation attempt. Worker-loss recovery
(``INTERRUPTED``) or re-dispatch creates the next attempt; terminal attempts are
never edited. A duplicate StageRun open finds and reuses the live attempt because
of the partial unique index. Attempt identity is the stage *name*, not its
manifest position, so reordering or inserting a stage resumes the existing
attempt and numbers the next one per stage; a stage that has never run can take
an index another stage already used without colliding. Duplicate *execution* of
a Task is prevented by the existing ``claim_task_execution`` mutex, not by
StageRun uniqueness alone.

## Task status projection

| Situation | ``tasks.status`` | Stage view |
| --- | --- | --- |
| No allocation yet | ``queued`` | first attempt ``QUEUED`` |
| Any allocation running | ``running`` | that stage ``RUNNING`` |
| Prior stage done, next queued | ``running`` | next ``QUEUED`` (no task regression) |
| Last stage done, results published | ``finished`` | all ``COMPLETED`` |
| Stage failed | ``failed`` | failing stage ``FAILED`` + reason code |
| Cancelled | ``cancelled`` | active stage ``CANCELLED`` |

Task ``running`` is written at the allocation-started boundary — the same
boundary that admits the allocation — never from stdout.

## Boundary ownership

| Transition | Writer |
| --- | --- |
| attempt ``QUEUED`` | workflow/job composer immediately before ``job.submit()`` |
| scheduler handle | allocation ``dispatched`` callback |
| ``RUNNING`` + Task ``running`` | allocation ``started`` callback |
| ``COMPLETED`` / ``FAILED`` | Core after ``job.poll()`` |
| ``INTERRUPTED`` | Core recovery when the owning worker vanished |
| ``CANCELLED`` | Core cancellation claim and the worker observing it |

Accounting is unchanged: admission consumes the reservation at allocation start
and the GPU/CPU ledger settles from measured allocation lifetime. StageRun rows
never move entitlement; an attempt without an allocation creates no ledger fact,
and duplicate callbacks stay idempotent through ``slurm_job_id``.

A failed attempt's reason comes from the adapter instance whose ``poll()``
produced that outcome, never from the Task-level diagnostics row. That row is
overwritten by the next stage or attempt, so borrowing it would attribute one
allocation's failure to another; when the adapter reports no reason, the attempt
is settled as ``allocation_failed``.

## Evidence monotonicity

Attempt creation runs under ``BEGIN IMMEDIATE`` (so "reuse the live attempt or
insert the next one" is one serialized decision); every transition is a single
guarded UPDATE whose predicate is the legal-predecessor set. Duplicate dispatch,
late markers, stale callbacks, worker loss, transient ``squeue`` failure, and a
crash between stage completion and the next dispatch are therefore no-ops or
forward transitions. A crash after the allocation ends but before ``COMPLETED``
is recorded leaves the attempt ``RUNNING``; recovery marks it ``INTERRUPTED`` and
re-runs the stage — Core never claims a completion it did not observe.

## API and migration

The status payload gains ``stages``: overall source (``record`` | ``legacy``),
total, completed, current stage, and per-stage status/source/attempt/timestamps/
reason/semantic planned resources (``source`` is ``record``, ``legacy``, or
``definition``). Existing fields are unchanged, so old clients keep working; the
list payload omits the per-stage detail rather than issuing one query per Task.

Historical rows are never backfilled (there is no evidence of attempts to
invent). When a stage has no StageRun, the API reads that stage from the legacy
``workflow_state``; a Task with no records at all is labelled ``legacy``. A
record always wins for the stage it describes. Core boundaries (stage
completion, failure, cancellation, recovery) rewrite ``workflow_state`` from the
records for existing consumers. It is a best-effort projection: a crash can
leave it stale, but it is never the authority for a Task that has records.

## Non-goals

No DAG engine, conditional/fan-out stages, Runner marker requirement, stage
selection, artifact reuse, or rewrite of placement/reservations/ledger.
