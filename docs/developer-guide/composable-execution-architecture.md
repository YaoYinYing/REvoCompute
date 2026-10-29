# Composable Scientific Execution Architecture

> **Status: ACTIVE CAMPAIGN DESIGN RECORD — NOT YET IMPLEMENTED.**
> PR #130 is activated as an exclusive single-PR campaign under Protocol v1.6.
> This page stays non-normative until it is reconciled with the delivered code
> and approved at final merge review; in conflict, current executable contracts
> and `CLAUDE.md` remain authoritative until cutover. It does not authorize a
> production deployment, database migration, or SIF promotion.
>
> **Activation baseline:** main at 36e30afa234595d8af09bf7aa3818b9bb6d06487;
> Protocol v1.6. The live activation record is the PR #130 thread.

## Intent and non-negotiable principles

REvoCompute should offer **one scientific graph architecture**, shared by
curated Task Types and user-composed Pipelines, with **two deployment-selectable
execution backends**: a minimal native DAG implementation and an optional
Nextflow integration. Do not ship two separate task/pipeline schedulers.

1. **Task Type is a published, precomposed Pipeline.** Pipeline is the
   editable composition experience. Both compile to the same validated,
   immutable execution graph; neither has a private execution semantics.
2. **Runner Family (Runner Fleet identity)** owns the deployable image/SIF,
   definition, pinned dependencies, runtime overlay, build evidence, license
   conditions, operator mounts and readiness. A Family exposes reusable
   Stage Definitions; it does **not** have to own the whole Task Type.
3. **Stage Definition** is the smallest independently executable scientific
   unit: typed file/parameter inputs, bounded resources, exact runtime
   entrypoint, typed artifact outputs, and log/error/debug-evidence contract.
   It may execute several commands internally. Distinguish Definition from
   **StageRun** (the immutable graph node's execution instance) and
   **StageAttempt** (one independently identifiable retry/allocation).
4. **Status** presented alongside each Stage describes scheduler/execution
   progress (not submitted / queued / running / settling). A separately
   validated scientific outcome (completed / failed / cancelled / blocked)
   MUST NOT be inferred solely from Slurm COMPLETED or a log marker.
   The UI renders [stage] [status] consistently for Task Types and Pipelines.
5. **Graph ownership** resides in the REvoCompute control plane:
   authorization, typed edges, resource policy, immutable graph identity,
   artifact custody, scientific validation and accounting. A selected backend
   owns scheduling and submission for **that deployment**, not both.
6. **No legacy marker compatibility layer.** Retire REVODESIGN_STAGE stdout
   as a Stage-definition or StageRun authority, along with old ordered-marker
   partition constraints and consumers. Optional *progress observations* may
   survive only as a new explicitly non-authoritative, bounded protocol.
7. **Build from mature dependencies**, not a generic in-house workflow
   framework. Native is intentionally minimal; Nextflow must be evaluated
   with genuine Slurm/accounting integration before its backend is enabled.

## Canonical entities and identities

| Entity | Owner / identity | Core invariant |
| --- | --- | --- |
| RunnerFamily | Fleet + immutable runtime/build digest | SIF/definition, Runtime Bundle, operator readiness; a family may expose many stages |
| StageDefinition | Family-qualified stable ID + contract revision | Typed inputs, params, output ports, resource class, entrypoint and scientific validation |
| TaskType | Curated graph template ID + revision | Precomposed DAG with validated choices; may reference stages from several families |
| Pipeline | User-composed graph document + revision | Same graph language and compiler as TaskType; editability is the only distinction |
| ExecutionPlan | Graph digest and immutable source snapshot | Resolved Stage versions, edge bindings, params, runtime digests and policy decisions |
| TaskRun | One submitted ExecutionPlan + owner | User-visible aggregate with bounded authorization and retention |
| StageRun | TaskRun ID + immutable node ID | One logical graph-node execution; never conflated with workflow display index |
| StageAttempt | StageRun ID + monotonically allocated attempt ID | Unique backend allocation/submission identity; terminal attempts immutable |
| Artifact | Content digest + type/role + owner provenance | Immutable, validated output bound to exactly one producing attempt |
| Allocation | Backend + external scheduler ID + attempted Stage | Scheduler evidence and accountable runtime, not a scientific completion oracle |

Avoid duplicating facts currently owned by Runner task.yaml, plugin.yaml,
runner.yaml, the StageRun store, Resource Ledger, ResultManifest, or OpenAPI.
Audit existing tables and APIs before creating replacements. Existing StageRun
transaction and accounting correctness should be migrated, not discarded.

## Stage file contract (Unix-like, but not filesystem authority)

A Stage consumes **immutable, server-approved** input files, parameters and
artifact bindings; runs one pinned executable entrypoint from one Family;
produces an isolated output namespace plus a reproducible evidence bundle:

- Inputs: materialized, immutable file/metadata snapshot (or authorized
  content-addressed references), normalized parameters and their schema
  revision, source artifact digests, effective runtime and resource identity.
- Execution: launch and allocation evidence, bounded stdout/stderr, structured
  error category, timeout/cancellation evidence and attempt identity.
- Outputs: declared scientific artifacts with type, validation policy,
  manifest path, size/digest, confidence/coverage where applicable, and an
  explicit completeness verdict; untrusted Runner bytes never define paths
  or permissions.
- Debug record: input and command provenance sufficient to reproduce without
  copying shared DBs/model weights, credentials or private cross-user data.
  Redaction and operator-controlled retention remain mandatory.

The DB is authority for concurrent lifecycle transitions and ledger custody.
Files are portable evidence, NOT an alternative transactional status store.
Stage publication is confined, bounded, checked for malicious symlinks/hardlink
escapes/FIFO/path traversal and safely committed, including crash races.

## Graph grammar and compilation

Define **one server-owned, versioned graph IR**, independent of Nextflow DSL
and of any frontend library. The frontend submits data, not arbitrary
Python/Groovy/Shell or host paths.

The minimum validated graph includes:
- nodes: unique node ID, fully qualified StageDefinition reference+revision,
  constrained parameter bindings and declared resources;
- ports: named, strongly typed input/output Artifact roles (file format alone
  is insufficient for scientific compatibility);
- edges: source node/port -> destination node/port, explicit optionality,
  cardinality, role/version/sequence/chain mapping and conversion policy;
- graph inputs/outputs, declared graph-level required outcomes, stable
  ordering for deterministic presentation (not for execution authority);
- conditional inclusion/omission resolved at **compile time** from validated
  inputs and published TaskType choices, with an auditable omitted-node reason;
- bounded graph-size, maximum fan-out/depth, cost budget and resource-admission
  constraints. Dynamic user-authored DAG expansion is OUT of the first version.

At submission, reject cycles, dangling ports, ambiguous types, conflicting
user permissions, unavailable/unauthorized Family revisions, incompatible
artifact identity, invalid resources, unsupported backend capabilities and
unbounded generated work. Freeze the compiled graph, stage versions, image
and runtime digests, input checksums, policy revision and parameter decisions.
Never silently substitute an updated model or different MSA after submission.

All edge fan-out/fan-in semantics require atomic validated publication:
downstream stages become eligible only when their *specific* required input
artifacts are complete and authorized. A failed independent branch retains
other branches' valid artifacts. Retry must never duplicate publication.

## Scheduling and state

- Dependency state (WAITING/READY/BLOCKED) is distinct from scheduler
  observation (NOT_SUBMITTED/QUEUED/RUNNING/SETTLING) and scientific outcome.
  Present one useful [Stage] [Status] row with details on demand; do not invent
  a single overloaded enum that obscures scheduler vs scientific outcomes.
- StageRun/attempt transitions and cancellation are monotonic, transactional
  and idempotent. A Slurm completion needs result validation before scientific
  COMPLETED; zero-output success must fail closed.
- Backends receive immutable resolved execution facts, not mutable profiles.
  Every submission has a stable idempotency key. Recover submit-success /
  response-lost without making a second Slurm allocation or double-charging.
- Slurm retains node selection, placement fairness, job order and backfill.
  REvoCompute applies its entitlement/admission/quota policy before any
  schedulable work; it does NOT recreate the Slurm scheduler.
- Explicit resource consumption is tied to real allocation evidence and
  reconciled independently of task success. Unavailable sacct is UNKNOWN,
  not zero cost. Reservations and actuals require durable settlement.

## Pluggable deployment backends

The operator selects one backend for the entire deployment. A Task submitter
cannot switch backend or evade policy. This is a deployment setting, not two
competing schedulers in one live workflow.

Example intent (not a finalized settings schema):

~~~yaml
execution:
  backend: native  # native | nextflow
~~~

### Native backend — minimal reference implementation

Use existing Core-owned Slurm execution, StageRun, allocation callbacks,
reservation/accounting, isolated artifacts and cancellation infrastructure.
Implement the smallest **durable dependency scheduler** sufficient for a
bounded compiled DAG: ready-node claiming, branching, joins, terminal
propagation, retry/recovery, cancellation and observable stage statuses.

Do not implement a Groovy/Python DSL parser, arbitrary task-generated DAGs,
cluster fairness, a new distributed queue, a second ledger, or Nextflow's
whole feature set. Preserve tests from #118 and current GPU Credit governance.

### Nextflow backend — optional, gated integration

REvoCompute compiles the same validated ExecutionPlan into an immutable,
server-generated Nextflow DSL2 workflow/config using only allowlisted Stage
templates and pinned Family SIFs. No user-supplied executable DSL is accepted.
Nextflow handles DAG scheduling and process submission for this deployment.
REvoCompute retains scientific policy, authorization, immutable manifests,
artifact publication and **one authoritative resource ledger**.

**Feasibility stop gate before enabling Nextflow:**
- Prove that stage-level Admission and Quota decisions are enforced *before*
  every Nextflow->Slurm submission (including retry and resume). Nextflow's
  ordinary cpus/memory/time/queue directives are NOT substitutes for the
  REvoCompute credit and entitlement ledger.
- Choose and demonstrate an enforceable integration mechanism; compare
  documented native Slurm executor hooks, pre-submit controls and a custom
  Executor plugin if unavoidable. A hypothetical hook is NOT proof of safety.
  Document its maintenance and Java/Groovy costs.
- Guarantee a single authorized Slurm submitter, stable job mapping,
  cancellation ownership, reconciliation after crash, counter drift and
  duplicate event delivery. Avoid a second independent retry/accounting truth.
- Show pinned, offline-capable Nextflow version/plugins, SIF selection and
  controlled work directories. Nextflow cache/-resume must not bypass
  REvoCompute's artifact identity, access checks, billing rules or results
  validation. A cache hit requires explicit provenance/charge policy.
- Document failure semantics of Nextflow errorStrategy/retry, native Slurm
  states, partial outputs and canceled graphs. Pass exactly the same platform
  contracts and scientific tests as Native.

If these proofs fail, Nextflow remains **disabled / unsupported**; do not
silently bypass policy, ship a fake adapter, or lower acceptance standards to
finish the PR. Escalate an explicit maintainer go/no-go decision.

Nextflow official references to pin and verify at implementation:
- https://www.nextflow.io/docs/latest/executor.html
- https://www.nextflow.io/docs/latest/container.html#apptainer
- https://docs.seqera.io/nextflow/plugins/developing-plugins
- https://docs.seqera.io/nextflow/reference/process/directives

### Backend capability matrix (current decision)

| Requirement | Native | Nextflow |
| --- | --- | --- |
| Server-generated command and image only | yes | yes (generated DSL2) |
| Admission before the scientific command runs | yes (wrapper grant gate) | unknown — no server round trip before `sbatch` |
| Per-allocation ledger identity | yes (`slurm_job_id`) | needs mapping from Nextflow task hash to job id |
| Cancellation ownership | yes (server owns the handle) | Nextflow owns submission; cancellation is indirect |
| Crash reconciliation | yes (StageRun attempt + recovery) | requires controller-crash reconciliation, unproven |
| Offline pinned runtime | yes (SIF) | requires offline Nextflow plus Java plugin build |

**Verdict: Nextflow is disabled.** Its Slurm executor has no pre-submit
hook, so meeting the admission and accounting invariant needs a custom
executor plugin (Java/Groovy) with a second submit path. That is a separate
integration with its own maintenance and offline-installation cost, and neither
the runtime nor a pinned release is installed here. This deployment runs the
native backend. Reopening the question requires the spike exit criteria named
in the PR thread — not a documentation change.

## Scientific acceptance examples

1. **AF2/AF3**: split only genuine upstream-supported MSA/search, feature
   preparation and inference units. Verified compatible supplied MSA may omit
   searching but MUST NOT silently omit required feature preparation. MSA-only
   and model-only variants must publish only valid selected outputs with
   truthful resource usage. Do not assert OpenDDE's internal phases can be
   independently launched until proven against pinned upstream.
2. **Cross-family GREMLIN_LH**: FASTA -> MSA preparation from PSSM-GREMLIN
   Family -> scientific alignment validation/transformation -> GREMLIN_LH
   Family. Alternatively a supplied, authorized compatible A3M/FASTA can
   enter the latter stage directly. Verify equal-length/multiple-sequence
   semantics, chain/sequence identity and provenance, not filename alone.
3. **PSSM-GREMLIN fork**: one FASTA feeds HHblits/HHfilter/GREMLIN branch
   and independent PSI-BLAST/PSSM branch. The scheduler can run both
   concurrently if admitted, or serially under constrained resources.
   One branch's failure does not delete an already validated output of the
   other. Final Task outcome follows the graph's required output policy.

A Runner census must inventory all existing Fleet Families, Task Types,
task.yaml workflow/stage_markers, actual entrypoints and stdout markers,
possible science splits, output role integrity and live evidence. Do not
force every progress step into a separately billed StageRun. Refactor only
where independent execution with typed artifacts is scientifically valid.

## Security, governance, and operational cutover

- Only server-generated commands and stage definitions; never execute user
  strings, expose arbitrary filesystem paths, or allow Pipeline composition
  to bypass family access, runner policy, model licensing or download policy.
- Same Task/Stage/Artifact contract for both backends and identical server
  validation. Failed authorization must fail before GPU or Slurm consumption.
- No backward-compatibility execution shim for legacy REVODESIGN_STAGE or
  single-Family workflow schema. **A breaking, explicitly approved cutover**
  drains/cancels and reconciles old active work, freezes historical records
  read-only, migrates all active callers atomically, and starts the new
  contract on a clean version boundary. Existing scientific artifacts and
  legitimate historical audit records must not be silently rewritten.
- Backend replacement is a separate operator migration: never pretend a
  running workflow can resume interchangeably in Native and Nextflow.
  Record backend identity with every TaskRun and StageAttempt.
- No production SIF promotion, server restart, live destructive migration,
  external service installation or cluster policy change without explicit
  maintainer/operator authorization.

## Acceptance: no claims from CI alone

All modes require negative/positive regression evidence for:
- Graph cycles, invalid typed edges, missing or corrupt artifacts, stale
  revisions, cross-user links, orphan/resumed jobs and multiple writers.
- Parallel fork/join, partial branch failures, skipped/search-supplied
  modes, retries, cancellation, interruption, restart recovery and idempotent
  publication/accounting.
- Tenant admission under concurrency, no unauthorized GPU allocation, Slurm
  submit-response loss, sacct outage, unavailable quota facts and backend
  cancellation convergence.
- Real native Slurm/Apptainer scientific cases and the *same* accepted graphs
  through Nextflow in an isolated authorized test environment. Exact receipt
  identity includes stage/graph/runtime/asset/backend versions.
- Actual browser [stage] [status] rendering for curated Task Types and editable
  Pipelines, and honest user error/status vocabulary.
- Independent architecture/scientific/security review, Examiner evidence,
  Campaign Acceptance Auditor at exact final head, current-main C3 full
  merge-grade verification, docs/API schema coherence and subtraction of all
  legacy/duplicate paths.

## Exclusive execution gate

This is a **large exclusive single-PR campaign**. Activation required that every
other PR in `YaoYinYing/REvoCompute` was MERGED or CLOSED and that the
maintainer then issued an explicit start instruction; both held at activation
(main `36e30af`, no other open PR). A later PR that needs to proceed alongside
this work is a maintainer decision, not a Commander one.

After activation, this PR owns the architectural write scope exclusively;
subagents may work in isolated worktrees *under this one PR* with serialized
integration. No competing product PR may implement/merge overlapping changes.
Independent Campaign Adviser, separate Examiner and final Acceptance Auditor
remain required. Only the maintainer decides squash merge and production
promotion.

## Documentation lifecycle

Maintain a PR-local root TODO.md and IMPLEMENTATION_STATE.md only while
active. Retire both before READY_FOR_FINAL_REVIEW. This canonical design
page must be reconciled with delivered code and existing architecture,
execution-model, runner and operator pages, not remain an aspirational duplicate.
Do not leave nested campaigns/date workstream scratch artifacts in main.
