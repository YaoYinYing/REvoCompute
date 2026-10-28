# TODO — refactor(core): authoritative execution-stage state and transitions

> **Status:** Implemented on `campaign/2026-10-28-stage-state-contract`; PR Draft, no merge authorization. See `IMPLEMENTATION_STATE.md`.
> **Baseline when drafted:** `17e80ed1dbd00f1389f3ec7047e5661b85ed52eb` (2026-10-28); revalidate against the exact head at implementation.
> **Scope:** Replace stdout marker authority with durable stage-execution records and truthful per-allocation state, preserving Core admission, accounting, cancellation and recovery semantics.

## Objective
Replace stdout marker authority with durable stage-execution records and truthful per-allocation state, preserving Core admission, accounting, cancellation and recovery semantics.

## Grounded starting facts
- Current AF2 and AF3 Task manifests already contain `features` and `model` WorkflowStage entries.
- `task_runtime._run_compute_workflow` sets Task `status=queued` before each allocation, causing apparent top-level state rollback.
- `REVODESIGN_STAGE:` stdout events are parsed by `_stages.py` and the Slurm reader; they are progress observations, not authoritative phase transitions.
- `workflow_state` exists as a JSON field; resource-ledger allocations already record stage IDs.

## Implementation checklist
- [x] Write a concise durable state-machine RFC inside this PR before modifying Core; distinguish Task, StageDefinition, StageRun/attempt, scheduler allocation, progress observation and artifact publication.
- [x] Define stage statuses at least NOT_STARTED / READY / QUEUED / RUNNING / COMPLETED / FAILED / CANCELLED / INTERRUPTED / SKIPPED and explicit legal transitions, including retries.
- [x] Define `Task.status` as a projection from the overall workflow outcome, not merely the transient status of the current Slurm allocation; between stages Task remains active while next StageRun queues.
- [x] Persist execution-stage identity, task id, attempt, stage index/name, scheduler handle, planned resources, started/ended timestamps, reason and evidence; choose minimal schema migration consistent with current DB patterns.
- [x] Preserve `workflow_state` compatibility and migration for queued/running/historical tasks; distinguish old progress markers from new authoritative stage runs.
- [x] Replace runner stdout marker callbacks as state authority with state transitions at Core scheduler/submission/settlement boundaries; stdout remains optional within-stage progress detail.
- [x] Define exactly-once/idempotent StageRun attempt creation, commit/settlement and diagnostic linkage under worker loss, retry and scheduler reconciliation.
- [x] Keep stage/attempt evidence monotonic: late log lines or stale worker updates must not regress completed/cancelled states.
- [x] Keep existing quota reservations and stage-specific allocation GPU-second ledgers authoritative; forbid double billing or free allocation during transitions.
- [x] Expose an API projection that separately reports task-level state, current stage, completed stages, per-stage queue/running state and stable reason codes; preserve old clients during migration.
- [x] Use only a thin design-appropriate abstraction; avoid a generic DAG engine or arbitrary workflow framework.
- [x] Instrument meaningful events without leaking scheduler internals or unsanitized logs; document state examples.

## Test and acceptance checklist
- [x] AF3 features COMPLETE → model QUEUED → model RUNNING → overall COMPLETE, with no task-level regression to QUEUED.
- [x] Model allocation can queue for an extended period after features without falsely reporting all computation finished.
- [ ] Timeout, cancellation at every boundary, failed feature phase, failed model phase, interrupted worker and orphan Slurm job have correct reconciliation.
- [x] Duplicate dispatch, late marker, stale callback, transient squeue failure and crash between stage completion and next dispatch do not duplicate StageRun or charge.
- [ ] CPU features remain GPU-credit-free; GPU model charges only actual allocation; diagnostics map to correct attempt.
- [ ] Migration tests for historical tasks; API browser integration tests and real Slurm evidence where available; exact-head CI. (Migration test done; browser lane and real Slurm evidence deferred to the Commander's serialized live-test window.)

## Explicit non-goals
- Do not implement MSA-only/model-only UI or artifact reuse in this PR.
- Do not rewrite Slurm scheduling policy, resource ledger, Trust Boundary, or attempt DAGs.
- Do not make generic stdout stage markers a required Runner protocol.

## Dependency and integration policy
Foundational PR. Must merge and pass independent system review before `stage-selection-reuse` PR can land.

## Review protocol and handoff
- [x] Read `CLAUDE.md`, `LONG_TASK_HANDLING.md`, the Single-PR Campaign Protocol and this TODO before coding.
- [ ] Appoint one PR owner; preserve an independent Campaign Adviser and strict worktree/write ownership.
- [x] Create or update `IMPLEMENTATION_STATE.md` alongside this TODO when substantive implementation begins; track progress, exact tests and outstanding blockers.
- [x] Validate exact head, identify adjacent open/merged PRs and avoid rewriting canonical functionality or introducing parallel sources of truth.
- [ ] Post detailed technical findings and regressions to this PR's review threads; report owner/adviser status to Commander.
- [ ] Include fail-path tests, relevant docs, migration/read-only compatibility where needed, and no unverifiable performance or science claims.
- [ ] Keep PR draft until implementation is complete, exact-head CI/review evidence exists and maintainer accepts the scope.
