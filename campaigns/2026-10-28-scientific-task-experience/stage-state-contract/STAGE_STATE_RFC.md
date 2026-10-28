# RFC — durable execution-stage state

> Status: accepted for implementation in PR #118. Scope: Core only. No Runner
> protocol change, no stage-selection UI, no artifact reuse (PR #119).

## Problem

A Task's ``status`` and ``run_stage`` were written from three places: the
worker before dispatch, Core's allocation callbacks, and the Runner's
``REVODESIGN_STAGE:`` stdout markers. The workflow composer also wrote
``tasks.status = "queued"`` before every allocation, so a Task that had
completed its CPU preparation stage fell back to ``queued`` while its GPU stage
waited in the scheduler queue. Nothing durable recorded *which allocation* ran,
under which attempt, with which resources, or why it ended. stdout was the
de-facto authority for phase transitions.

## Entities

| Entity | Identity | Authority | Lifetime |
| --- | --- | --- | --- |
| **Task** | ``tasks.md5sum`` | Core | Submission → terminal outcome |
| **StageDefinition** | owning ``task.yaml`` ``workflow[i]`` | Server (manifest) | Immutable |
| **StageRun / attempt** | ``(task_id, stage_index, attempt)`` | Core | One allocation attempt |
| **Scheduler allocation** | ``slurm_job_id`` | Slurm + Core accounting | One ``srun`` request |
| **Progress observation** | stdout marker | Runner, advisory | Within one allocation |
| **Artifact publication** | anchored manifest | Core | After the final StageRun |

A Task with no manifest workflow has exactly one implicit StageDefinition: the
Task type itself (``stage_index = 0``). Every allocation therefore has a
StageRun; a workflow Task has one StageRun per workflow stage per attempt.

StageRun is the only authority for "which stage is queued/running" and for why
an attempt ended. ``tasks.status`` is a projection of the whole workflow
outcome, not of the current allocation. stdout markers remain optional,
diagnostic progress detail (``tasks.run_stage`` and the execution-progress
rows); they never create, advance, or settle a StageRun.

## Stage statuses and transitions

```text
NOT_STARTED ──> READY ──> QUEUED ──> RUNNING ──> COMPLETED
     │            │          │          │
     │            │          │          ├──────> FAILED
     │            │          │          ├──────> CANCELLED
     │            │          │          └──────> INTERRUPTED
     │            │          └──────────────────> FAILED / CANCELLED / INTERRUPTED
     │            └─────────────────────────────> SKIPPED / CANCELLED / FAILED
     └──────────────────────────────────────────> SKIPPED / CANCELLED
```

Allowed transitions are enforced in the database write, not by a read-then-write
check. Terminal statuses (``COMPLETED``, ``FAILED``, ``CANCELLED``,
``INTERRUPTED``, ``SKIPPED``) have no outgoing transition, so a late log line,
a stale callback, or a duplicate worker can never regress an attempt.

``READY`` exists in the vocabulary for the interval between "previous stage
committed" and "allocation submitted". The Core writer creates an attempt
directly in ``QUEUED`` immediately before submission, so ``READY`` is legal but
not currently persisted.

### Retries

One attempt is one allocation attempt. A retry after ``INTERRUPTED`` (worker
loss) or an operator re-dispatch creates the next attempt number; the previous
attempt stays terminal and is never edited. A duplicate dispatch finds the
existing live attempt (``QUEUED``/``RUNNING``) and reuses it. The unique index on
``(task_id, stage_index, attempt)`` and the partial unique index on
``(task_id, stage_index)`` for live attempts make both properties database
facts.

## Task status projection

| Situation | ``tasks.status`` | Stage view |
| --- | --- | --- |
| No allocation yet | ``pending`` / ``queued`` | first stage ``QUEUED`` once dispatch begins |
| Any stage allocation running | ``running`` | that stage ``RUNNING``, earlier ``COMPLETED`` |
| Previous stages done, next stage queued | ``running`` | next stage ``QUEUED`` |
| Last stage completed and results published | ``finished`` | all ``COMPLETED`` |
| Any stage failed / task failed | ``failed`` | failing stage ``FAILED`` with a reason code |
| User cancellation | ``cancelled`` | active stage ``CANCELLED`` (or ``INTERRUPTED``) |

The transition to ``running`` happens at the allocation-started boundary
(``allocation_started_callback``), the same boundary that admits the
allocation. Between stages the Task stays ``running``: only the StageRun is
``QUEUED``.

## Boundary ownership

| Transition | Written by |
| --- | --- |
| attempt ``QUEUED`` | ``_run_compute_workflow`` / ``_run_compute_job`` immediately before ``job.submit()`` |
| scheduler handle attached | allocation ``dispatched`` callback (scheduler accepted the request) |
| ``RUNNING`` + Task ``running`` | allocation ``started`` callback (allocation observable on a node) |
| ``COMPLETED`` / ``FAILED`` | Core after ``job.poll()`` returns its outcome |
| ``INTERRUPTED`` | Core recovery when the owning worker disappeared |
| ``CANCELLED`` | Core cancellation claim and the worker observing cancellation |

Allocation accounting keeps its existing authority: the durable reservation is
consumed when the allocation starts, and the GPU/CPU ledger settles from the
allocation's measured lifetime. StageRun rows never move entitlement or charge
anything; they only describe execution. A stage attempt that never obtained an
allocation produces no ledger fact, and a duplicate callback for the same
``slurm_job_id`` stays idempotent through the existing allocation identity.

## Idempotency and evidence monotonicity

* Attempt creation is ``BEGIN IMMEDIATE``: reuse the live attempt, otherwise
  insert ``max(attempt) + 1``.
* Ownership and settlement writes are guarded by the legal-predecessor set, so
  they are idempotent and monotonic under duplicate dispatch, late markers,
  stale callbacks, worker loss, and a crash between stage completion and the
  next dispatch.
* A crash after the allocation ends but before ``COMPLETED`` is recorded leaves
  the attempt ``RUNNING``; recovery marks it ``INTERRUPTED`` and the next
  attempt re-runs the stage. Core cannot claim a completion it never observed.

## Compatibility

``tasks.workflow_state`` remains a compatibility projection written by the same
Core transitions. It is authoritative only for historical rows that predate
StageRun records; new rows are read from the StageRun table. The API reports the
source (``record`` vs ``legacy``) instead of silently mixing the two. Historical
rows are never backfilled: there is no evidence of attempts, resources, or end
reasons to invent.

## API projection

The status and list payloads gain a ``stages`` object:

```json
{
  "stages": {
    "source": "record",
    "total": 2,
    "completed": 1,
    "current": {"index": 1, "name": "model", "display_name": "Model", "status": "QUEUED", "attempt": 1, "reason_code": null},
    "items": [
      {"index": 0, "name": "features", "display_name": "Features", "status": "COMPLETED", "attempt": 1, "started_at": "...", "ended_at": "...", "reason_code": null, "planned_resources": {"cpus": 8, "requires_gpu": false, "...": "..."}},
      {"index": 1, "name": "model", "display_name": "Model", "status": "QUEUED", "attempt": 1, "started_at": null, "ended_at": null, "reason_code": null, "planned_resources": {"cpus": 8, "requires_gpu": true, "...": "..."}}
    ]
  }
}
```

Task-level state stays in the existing ``status`` field, so old clients keep
working unchanged. Reason codes are a bounded Core vocabulary, never scheduler
stderr.

## Explicit non-goals

* No generic DAG engine, conditional stages, or fan-out.
* No Runner-protocol requirement for stage markers.
* No stage selection, artifact reuse, or partial re-run UI.
* No rewrite of Slurm placement, reservations, or the resource ledger.
