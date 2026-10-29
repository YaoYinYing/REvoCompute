# TODO — Composable Scientific Execution Architecture

> **ACTIVATED — EXCLUSIVE SINGLE-PR CAMPAIGN.** Activated 2026-10-29 on main
> 36e30afa234595d8af09bf7aa3818b9bb6d06487 under Protocol v1.6, after the live
> open-PR list contained no other PR and the maintainer issued the start
> instruction. Implementation, tests and isolated worktrees are authorized under
> this PR only; production deployment, restart, destructive migration, SIF
> promotion and squash merge are not.
>
> Permanent proposal: docs/developer-guide/composable-execution-architecture.md
> Normative agent guidance: CLAUDE.md, docs/agents/long-task-handling.md,
> docs/agents/single-pr-campaign.md and current Protocol.
> This root TODO is ephemeral and MUST be removed before final merge.

## 0 — Exclusive activation / stop gate

- [x] Keep PR **Draft** and the Commander control state **PARKED** until
      activation instructions arrived.
- [x] Do not appoint implementers, start technical worktrees, run the feasibility
      spike, mutate source, change Fleet, submit Slurm work or install Nextflow
      during the parked period.
- [x] Check GitHub's LIVE complete list of Open PRs in YaoYinYing/REvoCompute.
      At activation the only open PR was #130 itself; #119, #122, #123, #124,
      #125, #126 and #128 were closed or merged.
- [x] Verify **the set of Open PRs excluding this PR is empty**.
- [x] Get an **explicit new maintainer start instruction** after that check.
- [x] Record activation date, current main SHA, Protocol revision,
      single-PR ownership, allowed live-test budget, backend feasibility gates
      and a compact dependency/ownership ledger in IMPLEMENTATION_STATE.md.
- [ ] Appoint scoped independent reviewers, Examiner, and a final disinterested
      Campaign Acceptance Auditor. Integrate all implementation under this one
      PR; isolated worktrees permitted only after activation.
- [ ] If another PR needs to proceed during exclusive execution, stop,
      escalate to the maintainer, and explicitly re-plan the exclusivity.
      Do not grant a subagent a unilateral exception.

**Gate 0 verdict: MET at main `36e30af`.**

## 1 — Evidence-first architectural feasibility

- [ ] Inventory main implementation and all Fleet manifests with the *latest*
      current-base code; update the proposal based on findings.
- [ ] Produce a table of each Runner Family, provided task types, declared
      stage markers/workflow, entrypoints, real subprocess stages, typed input
      files, output roles, intermediate artifact identities, runtime images
      and scientific tests. Distinguish intra-allocation progress from
      independently executable scientific stages.
- [ ] Reconcile #118's StageRun transaction/attempt/liveness semantics,
      legacy task/workflow_state, Slurm Adapter, ResultManifest, reservations,
      credits, resource policy, cancellation and worker recovery.
- [ ] Pin a maintained Nextflow release and exact plugin/runtime versions;
      run the minimum integration feasibility experiment in an isolated,
      authorized environment. Validate genuine per-process admission,
      GPU quota enforcement, Slurm job ownership, cancellation and restart
      recovery before promising the backend can be enabled.
- [ ] Record formal options for Nextflow's native Slurm Executor versus a
      custom plugin/controlled submission adapter. Measure cost and
      maintenance, especially loss of response after Slurm submission.
- [ ] Obtain independent Adviser challenge: can any Nextflow path bypass
      REvoCompute admission/accounting or create a competing execution truth?
      If yes, BLOCK Nextflow enablement, not merely document the risk.
- [ ] Define backend capability matrix, explicit unsupported cases and an
      isolated operator cutover design.
- [ ] Make the go/no-go feasibility decision explicit in the PR thread,
      including real evidence, expected failures and unresolved gaps.

## 2 — Single scientific graph and stage contracts

- [ ] Define stable identities and versioning for RunnerFamily,
      StageDefinition, TaskType (curated Pipeline), Pipeline (editable),
      ExecutionPlan, TaskRun, StageRun, StageAttempt, Artifact and Allocation.
- [ ] Make reusable StageDefinition owned by its Runner Family and not
      hardcoded to exactly one Task Type; stage ports have typed/validated
      file + parameter input and result/log/error/debug output contracts.
- [ ] Specify one versioned server-owned Graph IR and immutable execution
      snapshot for **both Task Types and Pipelines**. Validate node uniqueness,
      references, edge types, cycles, fan-in/out, branch completion and bounds.
- [ ] Freeze input digests, contract/revision, runtime/SIF/build/provenance
      digests, effective parameter values and resource policy revision at
      submit; source file names alone do not establish compatibility.
- [ ] Define typed Artifact Port bindings, including sequence/chain/MSA/
      model-version semantics and mandatory transformations where verified.
      Confined publication, ownership and validation precede downstream use.
- [ ] Derive selected paths and node omissions from validated user inputs;
      do not launch a no-op Slurm job to simulate a skipped MSA/search stage.
- [ ] Provide a lossless read-only historical audit and explicit breaking
      execution-schema migration plan. Do not implement legacy marker shims.

## 3 — Native DAG backend (deployment default)

- [ ] Implement the minimum durable ready-node scheduler using existing
      Slurm Adapter, StageRun transaction identities and credit ledger.
      No second batch scheduler, generic DSL or duplicate state store.
- [ ] Prove deterministic dependencies, concurrent eligible branches,
      fan-in joins, missing/failed branch handling, retries, cancellation,
      terminal monotonicity and restart recovery with multi-worker races.
- [ ] Preserve GPU allocation-start evidence, immutable allocation handle,
      resource reservation/admission and exactly-once ledger settlement
      under submit-response loss and repeated callbacks.
- [ ] Do not infer science success from Slurm COMPLETED: each Stage output
      must independently pass the owning result contract.
- [ ] Record the backend and exact attempt identity on every stored TaskRun,
      StageRun, allocation and evidence receipt.

## 4 — Nextflow backend (optional, capability gated)

- [ ] Build a validated Graph IR -> pinned, server-generated Nextflow DSL2
      translation. Only allowlisted Stage templates/params and preapproved
      runtime SIFs; never execute user-provided Groovy/Shell or arbitrary paths.
- [ ] Integrate with **one** authoritative resource governance ledger and
      explicit pre-submit per-Stage admission. No task may be submitted to
      Slurm when unauthorized, unfunded or unaccounted.
- [ ] Demonstrate single owner of actual Slurm submit/retry/cancel,
      idempotency/reconciliation, per-allocation metering, sacct-unavailable
      states and bounded recovery after engine/controller crash.
- [ ] Test Nextflow errorStrategy, retry, resume/cache, skipped stages,
      partial results and stale artifacts against REvoCompute's policies.
      A cache hit is never unconditionally billable or authorized.
- [ ] Confirm offline deployment and pinned Nextflow/plugins/Apptainer config,
      shared working directories, GPU allocation shape and no runtime fetches.
- [ ] Keep Nextflow disabled if independent integration review cannot prove
      stage-level admission/accounting. Do not ship a placeholder "supported"
      backend that silently weakens security.
- [ ] Provide deployment selection (native | nextflow), startup capability
      checks, config/operator docs and a controlled backend-switch procedure
      that drains old active work; no cross-backend live resume promise.

## 5 — Runner fleet and science migration

- [ ] Migrate all affected family/task contracts in the **same** breaking
      architectural cutover. Remove REVODESIGN_STAGE parser, manifest
      stage_markers partition constraints, run_stage-based execution authority
      and obsolete paths/tests with a subtraction audit.
- [ ] Do not preserve Runner-specific legacy compatibility for PSSM-GREMLIN.
      Retain progress only through an explicitly non-authoritative replacement
      when useful; do not mistake HHfilter for an independent Slurm Stage.
- [ ] **AF2/AF3**: verify actual upstream separation of MSA/search,
      feature preparation and model inference; correct supplied-MSA
      bypass, preparation-only and model-only identity/provenance.
- [ ] **GREMLIN_LH**: cross-Family path from sequence through a valid
      MSA-producing Stage, including verified A3M normalization, then
      GREMLIN_LH fit; permit direct valid user MSA.
- [ ] **PSSM-GREMLIN**: independent HHblits and PSI-BLAST paths can
      run concurrently when admitted, or serially if the scheduler delays
      one; retaining validated outputs of a successful branch on sibling
      failure; preserve expected coupling/PSSM semantics.
- [ ] **OpenDDE**: assert independent execution modes only on actual pinned
      upstream evidence; do not invent MSA-only entrypoints.
- [ ] Every affected Family's SIF/runtime bundle is rebuilt or revalidated
      according to changed bytes, with safe read-only mounts, asset identities,
      negative tests and scoped live receipts. No indiscriminate rebuilds.

## 6 — APIs, UI, and consistent [Stage] [Status] rendering

- [ ] One graph-aware Task Type API and one user Pipeline composition API
      using the same authoritative server Graph IR and validation errors.
      No separate frontend scientific parameter/default registry.
- [ ] UI shows [Stage] [scheduler status] and separately exposes
      validation/outcome details for both curated Task Types and Pipelines.
      Pending dependency is not Slurm QUEUED; Slurm COMPLETED is not
      scientifically validated COMPLETED.
- [ ] Edit/preview typed graph edges, backend-unavailable features and
      conditional skips before immutable submission.
- [ ] Preserve accessible results workspace and bounded logs/errors,
      provenance, attempt history and artifact download authorization.
- [ ] Update OpenAPI and generated client only from server-owned schemas;
      browser acceptance covers both light and dark theme, keyboard use,
      cancellation, restart and negative graph-refusal paths.

## 7 — Adversarial / integration acceptance

- [ ] Graph: cycle, dangling/mismatched port, duplicate node, unauthorized
      Family, incompatible MSA, wrong model version, bad chain mapping,
      hidden skip, malformed prior artifact and graph bound exceedance.
- [ ] Scheduler: two workers claim same Stage, parallel fork/join,
      failed sibling, exhausted admission, cancel/complete race, retry,
      absent submit reply, Slurm terminal state between polls, worker restart.
- [ ] Resources: concurrent GPU quota, reservations, no-start allocation,
      duplicate settlement, policy revision drift, sacct outage/UNKNOWN,
      partial cancellation and operator-controlled deletion.
- [ ] Filesystem: traversal, symlink/hardlink escapes, FIFO/sockets, large
      or truncated Runner output, malformed manifest, duplicate scientific
      record identities, unauthorized cross-user Artifact.
- [ ] Native and Nextflow execute the **same** representative graph cases,
      yield consistent scientific result contracts, final statuses and
      ledger semantics; explicit unsupported Nextflow capability is rejected
      *before* scheduling.
- [ ] Real pinned Slurm/Apptainer scientific acceptance receipts, no invented
      GPU evidence; replay bundles/fixtures are useful but labeled honestly.
- [ ] Run focused test suites and required full make test, documentation,
      BrowserContracts, Compose and impacted Runner tests at exact head.
- [ ] Independent review rounds with concrete counterexamples and targeted
      mutation-sensitive regressions. Reviewer/Examiner/Adviser evidence
      goes to this single PR's canonical thread.

## 8 — Controlled exclusive cutover and final cleanup

- [ ] Plan downtime/worker drain; detect all old in-flight tasks, reconcile
      Slurm allocations and credit facts, either complete or explicitly
      cancel, preserve older Task records read-only.
- [ ] Retire old execution contract in one switch without permanent adapter
      and without silently altering historical provenance.
- [ ] Do not perform production deployment, DB destructive migration,
      server restart, image promotion or SIF replacement without separate
      explicit maintainer/operator approval.
- [ ] Subtraction: obsolete WorkflowStage marker-based state, duplicate
      adapters, redundant schema/transport fields and stale documentation
      really removed. The proposal is not completed by adding new modules.
- [ ] Update canonical architecture, execution model, operator,
      Runner guide, scientific contract inventory, API and testing docs.
- [ ] Remove this root **TODO.md** and temporary IMPLEMENTATION_STATE.md
      before declaring READY, under Protocol v1.6. No nested Campaign
      scratch files in merged main.
- [ ] Examiner confirms actual UI and results; Independent Campaign
      Adviser challenges architecture, scientific and scope assumptions;
      separate final Campaign Acceptance Auditor independently checks
      complete submitted tree, exact head, receipts, security, regression,
      cleanup and PR claims.
- [ ] Commander submits only READY_FOR_FINAL_REVIEW with explicit risks
      and exact SHA. **Only maintainer can authorize squash merge.**

## Explicit non-goals

- No Python/Groovy/Shell code supplied by users as a Pipeline definition.
- No custom general-purpose DSL engine or native Nextflow replacement.
- No reimplementation of Slurm scheduling/fair-share/backfill.
- No duplicate per-backend scientific contract or credit ledger.
- No cross-backend live resume without a proven migration mechanism.
- No backward-compatible execution shim preserving REVODESIGN_STAGE.
- No implementation activity before the exclusive activation gate.
