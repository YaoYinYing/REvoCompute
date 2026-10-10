# TODO — Resource Governance Completion

## Context

This PR intentionally collapses the remaining Resource Governance work into one coherent completion PR rather than reopening old planning PRs #60 and #61 separately.

The canonical foundations are already on `main`:

- #55: Runner readiness/control plane and safe Admin operator actions;
- #56/#67: current Admin/frontend visual language;
- #59 + #66: canonical resource ledger, quota/admission, storage lifecycle, reconciliation and drift facts;
- existing scheduler-neutral `ExecutionPlan`, typed `ResolvedResources`, Slurm adapter, and operational events.

Old #60 (deterministic placement) and #61 (Admin resource/activity reports) were closed without implementation. Their design intent is absorbed here.

Governing pipeline:

> requirements → admission → deterministic placement → Slurm execution → accounting/lifecycle → Admin projection

Admin reporting must project canonical facts; it must never become another source of truth.

## Phase 0 — Fix the current Runner Fleet 404 before adding more Admin surface

The frontend router and navigation already treat `/compute/runner_fleet` as a protected Admin page, and the Fleet API already exists, but Flask does not register the page entry.

Implement the missing server page route with the same authorization/shell behavior as the other Admin pages.

Add a **server-owned page-route parity contract** covering every Admin destination declared by the frontend shell:

- `/compute/runner_fleet`
- `/compute/user_control`
- `/compute/configuration`
- `/compute/logs`

Required behavior:

- admin: frontend shell is reachable;
- authenticated non-admin: 403 shell boundary;
- anonymous: existing authentication boundary;
- direct navigation and browser refresh must work without Playwright stubbing the HTML route into existence.

Adjust browser fixtures so they do not mask a missing production page route. The test harness may still isolate APIs, but route existence must be tested by the server.

## Phase 1 — Deterministic stage-level placement

Complete the intent of old #60 without building a second scheduler.

Boundary:

> REvoCompute decides **what resources/queue class a stage should request and why**. Slurm decides **when and on which eligible node it runs**.

### 1. Separate requirements from deployment-local names

Represent workload requirements independently from concrete partition/QoS names.

At minimum cover:

- CPU count;
- memory;
- runtime bound;
- CPU-only vs accelerator-required;
- accelerator count;
- accelerator/resource class when explicitly required;
- constraints/capabilities that are semantically necessary;
- scratch or other existing hard execution requirements when already represented by the Runner contract.

Do not bake this deployment's `cpu`, `normal`, GPU model, or host names into Runner scientific manifests.

### 2. Add typed execution-class / placement policy

Deployment configuration maps canonical requirements to local Slurm fields:

- partition;
- QoS;
- GRES;
- constraint;
- account;
- nodes/ntasks;
- time;
- any already-supported scheduler field.

CPU-only stages must resolve without GPU GRES and preferentially target the configured CPU execution class.

GPU stages must require an explicit compatible accelerator execution class. High-VRAM/device-specific requirements must not silently fall back to an incompatible generic queue.

Unknown or impossible placement fails before submission with a bounded, machine-readable reason.

Do **not** implement fair-share, aging, backfill, priority scoring, or a shadow scheduler. Admission belongs to REvoCompute; fairness remains Slurm's responsibility.

### 3. Persist the resolved decision

Every submitted stage must retain enough immutable evidence to answer later:

- what requirements were declared;
- what policy/config revision was used;
- which execution class/queue was selected;
- which concrete Slurm resources were resolved;
- why that decision was made.

Use the thinnest shared decision semantics that fit the existing architecture. A small `DecisionRecord`-like contract is acceptable if it prevents validation/admission/placement/reporting from inventing incompatible receipt shapes, but do not create a generic workflow/event framework.

Historical Tasks must display their **recorded** decision; never recompute old placement from today's policy.

### 4. Dry-run / explainability

Expose a bounded operator/developer projection that can answer “where would this stage be placed and why?” without submitting a Slurm job.

Reuse canonical planning logic. No separate Admin-only placement engine.

### 5. Mockable acceptance

Placement tests must not require a real GPU, production Runner SIF, or physical multi-partition cluster.

Use synthetic CPU/GPU Runner requirements and mock Slurm/deployment capabilities to prove:

- CPU work does not request GPU;
- GPU work cannot land in CPU-only execution classes;
- typed/high-VRAM requirements refuse incompatible classes;
- stage-specific workflow placement works;
- policy changes do not rewrite historical plans;
- invalid/unknown configuration fails closed.

## Phase 2 — Admin operational read-model and reports

Complete the intent of old #61 **after** canonical placement facts exist.

### 1. One projection over canonical truth

Consume, do not duplicate:

- #55 Runner readiness/operator-job state;
- #59/#66 resource ledger, reservations, quota, storage lifecycle and reconciliation;
- persisted placement decisions from Phase 1;
- Task state and Slurm job identity;
- bounded operational events where they are the canonical observation.

Do not create a reporting-owned policy engine, lifecycle state machine, scheduler database, or shadow resource ledger.

### 2. Platform Integrity / drift

Provide an actionable integrity summary centered on inconsistencies, not vanity metrics.

At minimum surface bounded counts/details for available canonical drift classes such as:

- scheduler/task drift;
- storage/accounting drift;
- pending/unsettled allocation evidence;
- pending publication/storage charges;
- lifecycle purge errors/orphans;
- readiness/evidence problems where already represented by #55.

First version is **detection and navigation**, not automatic repair.

### 3. Resource and queue operations view

Admin should be able to inspect:

- CPU/GPU resource consumption in base facts with UI formatting;
- quota/entitlement pressure;
- durable storage ownership and lifecycle pressure;
- queue/placement distribution;
- queued/running/failed task counts and latency/runtime summaries where canonical timestamps support them;
- why a Task/stage was placed into a queue;
- Task → placement decision → Slurm job → allocation/accounting linkage;
- top bounded failure/reason categories.

Prefer time windows and bounded pagination. Add CSV/JSON export only where it is cheap and uses the same query/projection.

### 4. Admin actions remain adjustments, never fact rewriting

If this surface exposes quota/resource operations:

- administrative allowances/credits are auditable adjustments;
- never provide “reset history to zero” semantics that erase actual consumption;
- preserve existing safe typed operator-job pattern for mutations;
- reporting pages remain read models.

### 5. Frontend integration

Use the current Cared-for Precision / post-#56/#67 visual language.

Do not turn every fact into a card. Prioritize:

- fleet/integrity overview;
- dense readable operational tables/registers;
- clear warning states;
- direct links from anomalies to the canonical Task/Runner/operator context.

Responsive desktop/tablet/mobile behavior is required.

## Phase 3 — Cross-system decision/accounting invariants

Where the existing models already support it, make these invariants executable:

- unknown measurement is never displayed/accounted as zero;
- resource accounting facts are append-only/auditable;
- quota/admission and scheduler fairness remain separate;
- placement cannot silently request a resource outside admitted/declared requirements;
- Admin reports cannot derive a second answer that disagrees with canonical ledger/lifecycle/placement state;
- historical decisions retain the policy/evidence identity that produced them.

Do not expand into project/lab quota hierarchy, billing, autoscaling, cross-cluster federation, or a new analytics stack.

## Failure-injection gates

Add deterministic cases for:

- two submissions competing for the last admissible resource reservation;
- policy revision changing while an already-submitted Task retains its frozen placement;
- Slurm submission succeeds but response/worker path is interrupted without duplicate submission;
- scheduler evidence temporarily unavailable;
- accounting/reconciliation facts unknown rather than zero;
- storage purge/reconciliation drift appearing in Admin integrity view;
- Runner Fleet direct page refresh (the current 404 regression).

Reuse #66's established accounting/reconciliation semantics rather than reopening them.

## Interaction with active #71

#71 owns Runner test-location/CI architecture. This PR owns placement and Admin behavior.

If #71 lands first:

- rebase/reconcile only affected test paths and CI lanes;
- preserve Runner-family scientific test ownership;
- do not absorb #71's test-architecture scope.

If this PR lands first, #71 must classify/move any new tests according to its ownership rules without changing their semantics.

## Acceptance gates

- server page-route parity tests;
- placement policy/unit tests using synthetic CPU/GPU/multistage cases;
- persisted-decision/history tests;
- Admin API/read-model tests;
- browser tests against real server page-route existence rather than HTML-route masking;
- reconciliation/drift/failure-injection tests;
- strict docs build;
- exact-head required CI;
- fresh merge-grade review focused on scheduler/accounting/persistence/control-plane boundaries.

The final review must explicitly demonstrate:

1. `/compute/runner_fleet` is no longer 404 on direct authenticated Admin navigation;
2. CPU and GPU stages resolve through deterministic policy without hard-coded deployment queue names;
3. the recorded placement explains why a queue was selected;
4. Admin reports project the same canonical facts as ledger/lifecycle/readiness/placement;
5. no new source of truth or shadow scheduler was introduced.

Delete this `TODO.md` before final review. Record exact frozen-head evidence in the PR thread.

Do not merge.
