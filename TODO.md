# Admin Resource Operations and Activity Reports

## Objective

Build an Admin operational read-model that joins REvoCompute's canonical Task,
resource, placement, scheduler, storage, and audit facts into one useful control
surface.

The governing rule is:

> **Admin reporting may project and explain canonical facts; it must not become
> another source of truth.**

This PR is deliberately downstream of the Resource Accounting/Data Lifecycle
and deterministic Slurm Placement PRs, and it must integrate with PR #55's safe
Admin Runner control plane rather than creating a competing Admin architecture.

The result should let an operator answer, from the Web UI and typed APIs:

- who is consuming or waiting for resources;
- what is running and where it was planned to run;
- why a Task was admitted/rejected/placed/blocked;
- which users are near quota;
- how CPU/GPU allocations and utilization differ;
- where durable storage is growing;
- which Runners/workloads fail or wait unusually often;
- whether database, scheduler, accounting, and filesystem truth has drifted;
- what Admin/operator actions recently changed policy or state.

## Dependencies and ownership

This PR should not finalize until the following canonical sources are stable:

- PR #55: Runner readiness/control/operator jobs and Admin security model;
- Resource Accounting/Data Lifecycle PR: resource ledger, quota/policy,
  storage ownership/lifecycle, reconciliation/drift facts;
- deterministic Slurm Placement PR: persisted stage `ExecutionPlan` and
  placement reason/policy identity;
- PR #56: final frontend visual language, if it lands first.

PR #57 MCP is not an Admin surface and must not gain these operator capabilities.

Do not duplicate any of these owners in a reporting-specific database.

## Read-model architecture

### 1. Define one canonical Admin projection layer

Create typed server-side report/query models over canonical persisted state.

The report layer may denormalize/project for efficient reads, but every metric
must identify its authoritative source and semantic definition.

Do not make browser code:

- query SQLite directly;
- parse `squeue`/`sacct` output;
- inspect filesystem paths;
- recompute quota;
- reverse-engineer `srun` argv;
- infer Runner readiness.

All such facts must arrive through bounded, authorized server APIs.

### 2. Near-real-time and historical views are different

Support two time scales:

**Operational/live**

- Tasks pending/queued/running;
- current Slurm job/allocation identity;
- current placement/execution class;
- active CPU/GPU allocation counts by resource class;
- current user quota pressure;
- current storage pressure;
- reconciliation/drift warnings;
- Runner/readiness/infrastructure status from #55.

**Historical**

For bounded windows such as 24 h, 7 d, 30 d, and a bounded custom interval:

- submissions / completions / failures / cancellations;
- queue wait and runtime distributions;
- allocated CPU core-seconds;
- allocated GPU-seconds by resource class;
- utilization/peak telemetry where available;
- logical storage growth / purge volume;
- Runner/task-type throughput and failure rates;
- admission and placement rejection reason counts;
- Admin policy/control activity.

Do not force historical analytics through repeated live Slurm shell calls.

### 3. Metric semantics before charts

Every report metric needs a definition and tests.

At minimum distinguish:

- allocated GPU time from GPU utilization;
- allocated CPU time from CPU utilization;
- queue wait from execution runtime;
- logical user-owned bytes from physical filesystem usage;
- Task failure from validation/admission rejection;
- unknown telemetry from measured zero;
- Task execution state from data lifecycle state;
- Runner readiness from scheduler capacity.

The UI must label these distinctions. A pretty chart with an ambiguous
denominator is a bug.

## Admin information architecture

### 4. Overview

Provide a compact operational overview with real data, not decorative cards.

Candidate sections:

- active Tasks by lifecycle;
- current CPU/GPU allocations by class;
- queue/wait summary;
- users near or over quota;
- logical vs physical storage pressure;
- recent failure/rejection trends;
- platform integrity/drift count;
- Runner fleet status summary linked to #55.

Every summary must drill into the underlying filtered records.

### 5. Queue / execution view

Make the operator-visible chain explicit:

```
User / Task
  → admission decision
  → stage ExecutionPlan
  → Slurm job
  → current/terminal allocation
  → accounting settlement
```

Show enough context to answer:

- why this stage targeted this execution class/partition;
- requested CPU/memory/GPU class;
- Slurm job ID and state;
- queue/pending reason when reliably available;
- submission/queue/start/end times;
- whether accounting is settled;
- whether the persisted plan and actual allocation disagree.

Do not merely embed an `squeue` clone.

### 6. Users / quota view

For each user expose authorized Admin projections of:

- effective entitlement/quota;
- current period CPU/GPU accounting;
- GPU resource-class breakdown;
- durable logical storage ownership;
- concurrency where modeled;
- quota pressure / exceeded state;
- utilization telemetry separately from charged/allocated resources;
- recent adjustment/policy history.

Authorized policy mutation UI may call the canonical Resource PR endpoints.
Changes must require explicit confirmation where material and must preserve
actor/before/after/reason audit evidence.

Do not expose these data to ordinary users beyond their own existing resource
projection.

### 7. Workload / Runner view

Aggregate by Runner family/task type without redefining readiness.

Useful facts include:

- submission volume;
- success/failure/cancel counts;
- queue wait distribution;
- runtime distribution;
- CPU/GPU allocation totals;
- GPU class distribution;
- utilization/peak observations when available;
- common bounded failure/rejection reasons;
- link to canonical #55 readiness/control detail.

Do not rank scientific quality from operational metrics.

### 8. Storage / lifecycle view

Expose:

- logical owned bytes by user/task/data state;
- physical deployment capacity/pressure where canonical evidence exists;
- active/archive/purge lifecycle counts;
- largest owned Task footprints;
- recent growth and released bytes;
- failed/partial cleanup;
- orphan/missing/drift records from reconciliation.

Do not allow arbitrary filesystem browsing.

### 9. Platform Integrity / drift

Treat inconsistency as first-class Admin information.

Surface bounded records such as:

- DB says running but scheduler job is absent;
- active allocation has terminal Slurm evidence but is unsettled;
- persisted artifact accounting differs from owned files;
- Task marked purged but owned bytes remain;
- Task owns manifest artifacts that are missing;
- stale reservations;
- persisted ExecutionPlan differs from observed allocation in a material way.

The first version may be detection/reporting only. Do not auto-repair ambiguous
drift merely because the report found it.

Where #55 or the Resource PR exposes a typed safe repair primitive, the Admin
view may link/invoke it with existing authorization/audit semantics.

### 10. Activity / audit report

Provide an Admin-only activity stream based on canonical operational/audit
events, including where available:

- quota/policy changes;
- accounting adjustments;
- placement-policy changes;
- data lifecycle purge/archive requests;
- bounded repair/reconciliation actions;
- Runner operator jobs from #55;
- meaningful submission/admission failures.

Do not turn this into raw log tailing. Events need bounded types, timestamps,
actor/subject identity, outcome, and correlation IDs.

Do not expose secrets, API keys, raw authorization headers, arbitrary environment
values, or unbounded user payloads.

## Filtering, time, and export

Support bounded filters for useful dimensions such as:

- time window;
- user;
- task type / Runner family;
- Task lifecycle;
- data lifecycle;
- resource class;
- execution class/partition projection;
- outcome/reason code;
- drift category.

Use UTC internally and show clear timestamps.

Provide a bounded machine-readable export (JSON and/or CSV) for Admin reports
where useful. Export must use the same filtered projection and authorization as
the UI; do not create a separate raw-database dump endpoint.

Large result sets require pagination/aggregation limits. A report request must
not become an unbounded table scan or memory dump.

## Performance and freshness

Do not make the Admin page itself a scheduler load generator.

- cache/aggregate historical queries where justified;
- bound live scheduler refresh frequency;
- reuse canonical scheduler observation/reconciliation services;
- expose last-updated / evidence freshness where data can become stale;
- degrade individual panels when one evidence source is unavailable rather than
  failing the whole Admin surface.

Near-real-time polling is sufficient; WebSocket/SSE infrastructure is not a
goal unless already justified by existing architecture.

## Security / authorization

Admin reporting is sensitive.

Merge gates must prove:

- every Admin report/API requires canonical Admin authorization;
- ordinary users cannot enumerate other users, Tasks, quotas, job IDs, storage,
  or audit events through these endpoints;
- filter/export parameters are typed and bounded;
- no report endpoint permits arbitrary SQL, shell, argv, path, or environment
  injection;
- operator actions use the existing typed #55/resource/placement primitives,
  never browser-supplied shell commands;
- event/audit views redact secrets and bound payload size;
- CSRF/auth semantics remain consistent with existing Admin APIs.

## Frontend

Use the merged #56 visual language rather than inventing a separate "monitoring
dashboard" aesthetic.

Prioritize information hierarchy and dense scientific/operations work:

- tables where exact records matter;
- charts only where time/distribution adds information;
- no decorative gauges with invented thresholds;
- explicit unknown/stale/partial states;
- responsive tablet/desktop behavior; mobile may simplify density without
  hiding critical warnings;
- accessibility for status, tables, filters, and charts.

Use the existing frontend fixture/browser harness with canonical report
fixtures. Frontend fixtures prove rendering/interaction only; server report
tests prove metric semantics.

## Failure / integrity semantics

Test at least:

- `sacct` unavailable while persisted accounting still exists;
- scheduler query temporarily unavailable;
- utilization missing but allocation known;
- quota source available but storage reconciliation stale;
- one report panel fails while others remain useful;
- large time windows are rejected/bounded;
- concurrent policy changes while report data is refreshed;
- stale ExecutionPlan vs live scheduler observation;
- partial purge/drift records;
- admin adjustment followed by historical query;
- user deletion/disable does not destroy historical attribution;
- unknown is rendered as unknown, never zero.

## Tests / evidence

Merge gates include:

1. report-query unit tests with fixed canonical fixtures;
2. metric-definition tests for allocation/utilization/wait/runtime/storage;
3. authorization and cross-user enumeration negatives;
4. bounded filter/pagination/export tests;
5. drift/integrity projection tests;
6. dependency-contract tests against #55 Resource and Placement APIs;
7. OpenAPI/schema generation checks;
8. frontend fixture/browser acceptance across overview, queue, users, storage,
   integrity, and activity;
9. light/dark and responsive acceptance consistent with #56;
10. performance/bounded-query assertions for representative large fixture sets;
11. repeated xdist tests for report/cache/shared-state races.

A target-host screenshot/storyboard may supplement review but is not evidence of
metric correctness.

## Non-goals

- a second Task/resource database;
- direct Slurm scheduling/fair-share logic;
- direct shell/squeue/sacct execution from browser input;
- arbitrary filesystem browser;
- generic Grafana/Prometheus replacement;
- billing/invoicing;
- scientific quality ranking;
- automatic ambiguous drift repair;
- user-facing social/activity feed;
- MCP Admin/operator capabilities;
- another frontend architecture rewrite.

## Acceptance

At the exact final head, an Admin can trace a resource-consuming Task from user
and admission through ExecutionPlan, Slurm allocation, accounting settlement,
artifact/storage ownership, and data lifecycle; can understand current pressure
and bounded historical trends; can identify quota pressure and platform drift;
and can audit material Admin/operator actions without leaving the canonical
control plane.

Every displayed metric has a tested semantic definition and authoritative
source. Missing evidence is explicit. Ordinary users cannot access Admin
reporting. Repository-required server/browser/documentation/security gates and
the three-way pre-final review cell pass.

Reach `READY_FOR_FINAL_REVIEW`.

Do not merge.
