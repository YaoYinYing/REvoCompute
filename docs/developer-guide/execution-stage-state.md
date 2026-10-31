# Execution Stage State

This page defines the durable execution-stage state contract implemented by
PR #118: `stage_runs` is the only stage authority and `tasks.workflow_state` is
its compatibility projection. Runner protocol changes, stage-selection UI, and
artifact reuse are separate.

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

**Retries.** One attempt = one allocation attempt. A launch claim on the attempt
row is taken before the job adapter exists, so a duplicate or resumed dispatch
finds the live attempt and starts no second ``srun``. Worker-loss recovery
(``INTERRUPTED``) or re-dispatch creates the next attempt; terminal attempts are
never edited. Recovery cancels every allocation the Task row or its attempts
name. When a claim recorded no handle, or a cancellation cannot be confirmed,
the Task stays running with the explanation instead of failing over a possibly
live allocation, and cancelling the Task settles the claim. An adapter that
stopped its own process before the scheduler returned an identity holds the
gate the same way, so such a Task also waits for the operator even when no
allocation may be billable. An allocation known only from adopted scheduler
evidence — a host log or wrapper receipt — is not named by the Task row, so
stopping it remains a scheduler-side action. A
duplicate StageRun open finds and reuses the live attempt because of the partial
unique index. Attempt identity is the stage *name*, not its
manifest position, so reordering or inserting a stage keeps the existing
attempt's identity and numbers the next one per stage; a stage that has never
run can take an index another stage already used without colliding. Duplicate
*execution* of a Task is prevented by the existing ``claim_task_execution``
mutex, not by StageRun uniqueness alone.

A new execution never reuses a stage completed by an earlier execution. A
``COMPLETED`` row is current only when it carries a ``runtime_image_sha256``
that equals the Task's submission pin for that stage's family. An attempt
records that digest only through the guarded completion update below, so a
legacy row with ``NULL``, a malformed value, or a different observation is
history rather than evidence. Every declared stage therefore executes again and
the composer reuses only attempts it completed itself; a consumer stages from
that fresh attempt. The reuse refusal for a stage with no record at all whose
legacy ``workflow_state`` entry claims completion remains: that completion has
no artifact identity, so the stage fails ``stage_output_unverified``.

### Runtime image observation

A managed-Slurm submission records ``runtime_images: {family: "sha256:<hex>"}``
in the immutable ``task.json`` and mirrors the map onto the Task row; a
deployment that applies no Runner admission decision opens no SIF and pins
nothing. The digest is resolved once by ``runtime_image_for_submission`` and is
an observation of the bytes at the path this attempt opens, never a claim that
the path is immutable. Resolving the pin is not acceptance: admission also
requires the deployment's live-test authority
(``receipt_valid_for_artifact``) to prove a current, passed acceptance for
exactly those bytes: receipt contract version, every required passed case,
build provenance, test-definition, configuration and Runtime Bundle identity,
and execution identity. A missing, failed, partial, stale or wrong-family
receipt, or READY evidence describing a different SIF, refuses the submission
before Task creation and scheduler side effects.

The Slurm wrapper re-hashes the SIF immediately before it invokes Apptainer,
writes a schema-2 receipt binding Task, StageAttempt, family, Slurm job ID,
expected digest and observed digest, and refuses a mismatch without executing
the container. That receipt is a separate file from the schema-1 allocation
receipt, so ``_notify_dispatched`` adopting and deleting the allocation receipt
cannot remove the observation. Reads are non-destructive and the file is
retained across a worker crash, so recovery can still see it.

The adapter compares the observation's expected and observed digests, the
attempt's identity and the Slurm job id with the family pin in the immutable
snapshot, and passes the result to ``finish_stage_attempt``, which writes
``stage_runs.runtime_image_sha256`` only inside the guarded ``COMPLETED`` update
and only when expected equals observed. The store itself enforces that equality
against what its caller validated; it does not re-read the snapshot. Missing,
malformed, mismatched, or legacy ``NULL`` evidence is refused; attempt creation
never writes the column. This gate proves the wrapper observed the pinned bytes
immediately before exec, not that Apptainer executed them: promotion can still
rename a different SIF onto the path between the hash and the exec
(``run/revocompute_ctl/promotion.py:91-105``). That rename window is an open
limitation until an execution holds immutable bytes. Closing it needs more than
a store-backed resolver: submission discards the resolved path and launch opens
``execution_plan.image`` from ``runtime.slurm_image``, so a store must also
resolve a pin to its held path at launch, or publish digest-addressed image
paths. ``task.json``, the column, and the wrapper check stay the same either
way. A queued Task whose pinned active SIF no longer hashes to its pin fails
closed and must be resubmitted; it is never silently launched on the promoted
bytes. Tasks queued before runtime images were pinned carry no
``runtime_images`` map: their wrapper refuses to start Apptainer and they fail
closed, so they are resubmitted rather than run unpinned.

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
| ``COMPLETED`` / ``FAILED`` | Core after ``job.poll()``; ``COMPLETED`` also writes the wrapper-observed image digest |
| ``runtime_image_sha256`` | the guarded ``COMPLETED`` update, from the schema-2 wrapper receipt |
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

Each stage also carries ``dependency``, which answers whether the stage's graph
inputs are available and is independent of the scheduler ``status``:
``completed`` (latest attempt completed and, when the stage declares outputs,
its recorded identity names files that are still published), ``blocked`` (the
stage or an ancestor failed, per the recorded blocked-stage diagnostic and graph
edges), ``ready`` (every producer completed), or ``waiting`` otherwise. A
single-stage Task has no graph and reports ``completed``, ``blocked``, or
``ready`` from its own attempt.

``GET /compute/api/types/<name>`` includes ``execution_graph`` for workflow
Task Types: the same canonical ``ir_version``/``document``/``digest`` that
submission freezes. Single-stage Task Types omit the key.

Historical rows are never backfilled (there is no evidence of attempts to
invent). When a stage has no StageRun, the API reads that stage from the legacy
``workflow_state``; a Task with no records at all is labelled ``legacy``. A
record always wins for the stage it describes. Core boundaries (stage
completion, failure, cancellation, recovery) rewrite ``workflow_state`` from the
records for existing consumers. It is a best-effort projection: a crash can
leave it stale, but it is never the authority for a Task that has records.

## Non-goals

No Pipeline editor or user-authored graphs, conditional edges, per-stage
concurrency, Runner marker requirement, stage selection, or rewrite of
placement/reservations/ledger.
