# Composable Scientific Execution Architecture

> **Status: ACTIVE CAMPAIGN — PARTIALLY DELIVERED.**
> PR #130 is activated as an exclusive single-PR campaign under Protocol v1.6.
> Delivered in this PR: the versioned graph compiler and typed stage ports, the
> submission-frozen graph, stage artifact identity verified as a consumer stages it,
> fork/join readiness with branch isolation (executed serially), produced-artifact
> binding into a consumer stage's declared input role, cross-family stage
> references with per-family readiness, bundles and dispatch, one composed
> cross-family Task Type (PSSM-MSA → GREMLIN_LH), the graph-aware API projection,
> the `[Stage] [Status]` results surface with browser evidence from CI, and
> target-host live acceptance for AlphaFold 3, PSSM-GREMLIN, and GREMLIN_LH —
> including a real composed run whose consumer stage resolves only the verified
> stage input document (the receipts live in the deployment, not in this
> repository; the dated record is the PR #130 thread). Not delivered: concurrent
> branch execution and editable
> user Pipelines (the compiler and validation are shared; there is no composition
> API or editor). Sections below describe the target contract; treat undelivered
> parts as design, not capability. This page does not authorize a production
> deployment, database migration, or SIF promotion.
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

The GREMLIN fit is recomputed on every attempt. Its outputs sit in a tree that
survives retries, and this Runner cannot bind the runtime image Apptainer opens:
the execution contract carries a path, and a promotion can replace the file
behind it. Reusing a previous fit would therefore publish bytes no attempt can
attribute to its own image, so the stage removes its declared outputs and fits
again. A checkpoint becomes admissible only when the attempt carries an
immutable, content-addressed image identity; that work is tracked separately.

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

### Cross-family stage references (delivered contract)

A workflow stage may name the Runner Family that executes it:

~~~yaml
workflow:
- name: msa_preparation
  family: gremlin            # registered runtime family; defaults to the task's own
  outputs:
  - {name: alignment, type: a3m_alignment, path: "alignment/*.a3m"}
~~~

Rules the code enforces:

- `family` is identifier-validated in the owning task manifest. A deployment
  that names its enabled families cannot run a stage anywhere else, so a Task
  whose stage needs another family is not registered (one warning) while every
  other Task still loads; a narrowed deployment tree need not contain that
  family at all. A deployment that enables every family is validated against
  the runner tree instead, and a stage naming no real family is refused.
- Submission resolves every referenced family, requires each family's access
  policy to admit the user, requires each family's submission admission
  evidence to be ready, and pins one Runtime Bundle per referenced family. One
  refusal rejects the whole submission before any allocation.
- GPU eligibility is graph-aware: if any stage in any referenced family
  requires an accelerator, the user needs GPU access.
- Dispatch resolves each node's runtime image, entrypoint, mounts,
  RunnerConfig, access-policy entitlements and pinned bundle from that node's
  family. The composing Task's runtime is the default only for stages that
  omit `family`.
- Resource policy remains resolved by Task/stage name; placement keeps using
  the composing runner's timeout default.
- The frozen graph records each node's resolved family id. The family's SIF
  image and entrypoint are not part of the digest, so re-deploying an image
  does not change a submitted Task's frozen graph. A promotion between
  submission and execution therefore runs the new image under that graph; the
  Runtime Bundle is pinned into the submission, the image is the deployment's.

Cross-family references are additive to the existing single-family manifest:
a task that omits `family` keeps its current meaning.

### Produced-artifact binding (delivered contract)

A stage input that is not a `graph:` role consumes a specific producer port:

~~~yaml
workflow:
- name: msa
  requires_gpu: false
  requires_network: false
  stage_markers: [hhblits]
  outputs:
  - {name: alignment, type: alignment, path: "msa/*.i90c75_aln.fas"}
- name: fit
  family: gremlin_lh
  requires_gpu: false
  requires_network: false
  stage_markers: [gremlin]
  inputs:
  - {name: alignment, type: alignment, from: "<task>.msa:alignment"}
~~~

Rules the code enforces:

- The consumer's input name is the Runner's input role, the port types must
  match, and a required consumer input cannot bind an optional producer output.
  A port binds by logical type; the consumer's accepted upload formats constrain
  what a user may upload, never what a producer publishes.
- Before the consumer owns a stage attempt, the Server resolves the attempt the
  producer completed in this execution, requires `COMPLETED` with its recorded
  artifact identity,
  matches the producer port's declared paths, re-verifies every file's size and
  sha256 against that identity, and copies the files into a server-owned stage
  input directory outside the shared output tree.
- A role is a set. A producer port that publishes several files (one per chain,
  for example) becomes a role directory with the layout below the port's static
  prefix preserved; the server-written document lists every verified file and
  names the file itself when the role is exactly one artifact. An optional port
  that matched nothing leaves the consumer's optional role undeclared; a
  required port that matched nothing refuses the stage.
- The stage container binds that directory read-only and receives
  `TASK_STAGE_INPUTS`; a Runner re-hashes the artifact before use. Single-stage
  Tasks and `graph:` role inputs are unchanged. An adapter that resolves its role
  from that document consumes only the verified copy (both GREMLIN families do);
  an adapter that still reads the producer's published files from the task output
  tree keeps its own integrity check, and the AF3 model stage is the present
  example. Server admission is identical for both.
- A missing, changed, or unverifiable producer artifact refuses the stage before
  any attempt or allocation (`stage_input_unavailable`, `stage_input_invalid`).
  The identity describes the whole artifact: a file it names that no declared
  port publishes any more refuses the stage instead of narrowing what the
  consumer is handed. The Task output tree stays mounted for every stage, so
  this is not a confinement boundary: the copy the role resolves is the
  verified one, and integrity rests on the Runner resolving that role from the
  document rather than on mount isolation.
- The live-test harness enables and mounts every family a composed Task's graph
  names, so one isolated invocation exercises a stage that runs in a companion
  family instead of recording its case as omitted.
- The composed acceptance is content-bound, never path-bound: it records each
  companion's sha256, direct-build provenance and runtime bundle, so promoting a
  validated candidate to its active path keeps the acceptance that covered its
  bytes.
- A live-test scope that cannot run every case its `test.yaml` declares omits
  them from the plan and publishes those Tasks in the admission evidence; only
  their submissions are refused, so a family's remaining Tasks stay available
  and one narrow invocation cannot authorize the composed path it skipped.
- Known limitations. A stage's declared outputs live in the Task's shared output
  tree, so a re-attempt settles the files present there. The Server executes
  every declared stage in each execution, except a stage with no StageRun record
  whose legacy `workflow_state` entry claims completion, which is refused as
  `stage_output_unverified`. No attempt records the runtime image it ran, so a
  Runner keeps the published bytes attributable to its attempt by deleting or
  rewriting every declared output rather than reusing what it finds. The GREMLIN
  PSSM and AlphaFold 3 runners delete theirs first, and the GREMLIN-LH fit
  rewrites each one; caching inside an upstream tool's own image is outside this
  contract. The composed live acceptance runs CPU cases with accounting
  disabled, so it exercises the artifact handoff and submission admission, not
  the allocation-time readiness gate, which each family's own acceptance covers.
- A new execution executes every stage. No attempt records the runtime image it
  ran, so a completion from an earlier execution cannot be attributed to this
  execution's image; reusing it could attribute another image's artifact to this
  attempt. A consumer still re-hashes the producer's recorded identity when it
  stages the artifact, so a changed file never silently feeds it.

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
