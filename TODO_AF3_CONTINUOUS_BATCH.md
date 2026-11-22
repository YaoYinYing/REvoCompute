# AF3 Continuous Batch Inference — Campaign TODO

Status: **Campaign handoff / not implemented**. This branch establishes a single-PR implementation scope; no runner functionality is claimed by the initial commit. The Commander must refresh the exact base and verify all contracts before implementation.

## Goal and scope

Deliver **one** integrated AF3 continuous-batch capability: accept independent AlphaFold 3 inputs, perform compatible CPU feature preparation, execute size-aware sequential GPU inference within a bounded Slurm allocation using a resident model process, and retain per-target results, recovery, and measured scientific/performance evidence. This replaces the previously proposed separate "Multi-Input Inference" and "Resident Batch Reliability" PRs.

The existing one-input `alphafold3` path must remain compatible. Do not expand this PR to AlphaPulldown integration, a general scheduler redesign, a permanent inference daemon, or cross-user/cross-task GPU pooling.

## 0. Exact-base reconnaissance and design decisions

- [ ] Fetch current `main`, active PRs, task/Runner contracts, integration tests, and relevant producer/consumer code; record exact base/head and any conflicts.
- [ ] Confirm how named input roles and cardinality map to immutable submission snapshots, upload validation, worker manifests, and existing result-workspace views.
- [ ] Compare the existing AF3 `features` / `model` / `full` / `prepare_only` / `model_only` execution modes with the batch design; preserve their semantics for single inputs.
- [ ] Review upstream pinned AlphaFold 3 `run_alphafold.py` multi-input support (`--input_dir`, model-runner lifetime, output naming, JAX cache, token buckets) against the **actual pinned image**, not a floating upstream branch.
- [ ] Study KosinskiLab AlphaPulldown `PredictionBatch` and AlphaPulldownSnakemake resident batching as reference implementations, without vendoring or treating their scheduler as authoritative for REvoCompute.
- [ ] Choose and document the smallest backward-compatible input contract. Prefer one owning AF3 task contract with multiple named specifications if current Core safely supports it; otherwise document the minimum alternative without duplicating scientific defaults across sibling manifests.
- [ ] Define the correct existing Task-level outcome mapping for complete, partial, canceled, and failed batches. Do not invent a platform-wide Task state or imply failed children succeeded.
- [ ] Keep the Independent Campaign Adviser active; have it challenge contract ownership, scientific validity, resource bounds, failure behavior, and security boundaries before implementation.

## 1. Immutable batch membership and scientific input semantics

- [ ] Accept a bounded collection of independent AF3 JSON documents, not a multi-chain complex accidentally treated as multiple independent jobs.
- [ ] Preserve exact user-provided bytes, source digests, AF3 dialect, logical names, seeds, and input-role provenance per member. Generate stable collision-free target identifiers; reject duplicate IDs and ambiguous output names.
- [ ] Validate AF3 JSON dialect and supported entity types without silently changing scientific meaning. A multi-seed input remains one logical member with multiple generated samples.
- [ ] Build a frozen, ordered membership manifest with digest, parameter policy, and immutable input references. Membership/order changes must invalidate incompatible recovery evidence.
- [ ] Disallow untrusted filesystem traversal, symlink escapes, unexpected file references, host paths, URLs, and unconstrained generated output names. Reconcile or reject JSON path-referenced MSA/template/CCD assets through the existing trusted-input model; do not silently grant new arbitrary-path capabilities.
- [ ] Bound batch size, total tokens/work, output size, CPU/RAM, GPU allocation, and walltime through canonical owner-defined limits and existing resource governance. Reject before costly execution when known bounds fail.

## 2. CPU feature preparation and reuse

- [ ] Reuse the existing AF3 CPU-only `features` stage and dataset/weights read-only mounts. Prepare and validate each member independently.
- [ ] Permit reusable prepared `*_data.json` only through trusted, immutable, typed artifacts and existing stage-input provenance. Preserve digest and original scientific parameters; never reuse features after incompatible changes.
- [ ] Define independent per-member feature-preparation success/failure. A failed member must not mislabel another member's feature output or cause false success.
- [ ] Preserve functional `prepare_only`, `model_only`, and `full` behavior for existing single-input tasks; explicitly define batch equivalents where supported rather than inventing undocumented fallback.

## 3. Resident inference and resource-aware grouping

- [ ] Execute a bounded group of compatible inputs under **one Slurm GPU allocation**, sequentially in a process that loads the model once. Do not implement a perpetual GPU daemon or nested Slurm submissions.
- [ ] Start with native AF3 multi-input resident execution as a baseline; if per-member failure isolation requires an adapter, keep it pinned and minimal, with no unreviewed upstream monkey-patching.
- [ ] Group members by compatible model/runtime parameters and input-size/compilation bucket; preserve original membership in the result mapping.
- [ ] Distinguish peak-memory budgeting (primarily the largest concurrently resident prediction plus runtime retention) from walltime/compute budgeting (aggregate across sequential predictions). Never size GPU memory simply by summing token counts.
- [ ] Use documented JAX persistent compilation cache/buckets when compatible; make cache identity, ownership, lifetime, and permissions explicit, and prevent untrusted cross-task write access.
- [ ] Include conservative safeguards for retained JAX/XLA memory, CUDA OOM, Slurm time limits, cancellation, preemption/requeue, and large heterogeneous input groups. Split or reject unsafe groups without changing scientific inputs.
- [ ] Ensure GPU authorization and the existing `alphafold3_noncommercial` entitlement apply to the entire batch; do not permit policy bypass via secondary paths.

## 4. Per-target checkpoint, resume, and failure semantics

- [ ] Track `pending / preparing / ready / running / succeeded / failed / skipped` as **batch-member records**, not new global Task states. Track attempt ID, effective parameters, timestamps, and diagnostics.
- [ ] Treat a member as completed only when validated artifacts and per-member manifest/digests have been published safely. Stage temporary outputs separately; never trust a filesystem marker alone.
- [ ] Make completion receipts and batch-index updates crash-consistent and idempotent; recovery must reconcile database, filesystem, and scheduler observations.
- [ ] Keep finished members across retry/restart when content, model version, inputs, scientific flags, and output contracts match. Retry incomplete/failed members without overwriting unrelated completed members.
- [ ] Make failure isolation explicit: Python-level per-member errors may be recoverable; OOM/CUDA/XLA process corruption may require terminating the group and scheduling a fresh process for remaining members. Do not promise a corrupted process can safely continue.
- [ ] Ensure API cancellation and scheduler cancellation terminate the allocation, preserve valid completed evidence, and never silently report full success.
- [ ] No duplicate Slurm allocations or double accounting after ambiguous submission/restart. Use established Composer and resource-governance seams, not a private second scheduler.

## 5. Results, UI, security, and provenance

- [ ] Keep individual mmCIF models, confidence/ranking files, terms-of-use evidence, and prepared features addressable per member using the Runner's existing artifact contract.
- [ ] Publish a deterministic batch summary (membership digest, counts, per-target outcomes and artifact pointers, software/image/dataset versions, seeds, execution policy and resource evidence). Show unknown resource measurements as unknown, never zero.
- [ ] Use existing result-workspace components and API projections for progress, filtering, target selection, confidence summaries, errors, and selective retry; avoid bespoke frontend metadata as a second source of truth.
- [ ] Preserve upload and publication trust boundaries. Refuse output symlinks, path escapes, special files, oversized trees, duplicate members/paths, and artifact publication races.
- [ ] Preserve operator-maintained restricted model parameters and databases, non-commercial notices, and auditability. Do not place weights or confidential administrative records in outputs or the repository.
- [ ] Attribute allocation-level GPU time to the actual Task; per-member estimates are derived evidence, not independently measured GPU charges.

## 6. Acceptance: real computation, scientific consistency, and performance

- [ ] Tests use real parser/contract and command/worker behavior, not tests that simply grep YAML or shell text. Exercise single-input regression and multi-input submission through the public API.
- [ ] Test at least: one valid member, multiple members, mixed molecular systems, multi-seed members, duplicate names, malformed JSON, path escape, missing assets, all failed, partially failed, empty/oversized batch, and scientific parameter incompatibility.
- [ ] Inject interruption after a completed member, worker restart, stale checkpoint, failed hash/publication, Slurm submission-response loss, canceled allocation, time limit, and out-of-memory conditions. Demonstrate no wrong attribution, ghost success, or duplicate expensive computation.
- [ ] Build the candidate pinned SIF and run normal API → worker → Slurm → Apptainer scientific acceptance on an authorized target host. Record exact tested HEAD/image digests, job IDs, logs, published structures, and operator-controlled weight/database identity without leaking sensitive artifacts.
- [ ] Compare isolated AF3 jobs versus resident batches with equivalent inputs, seeds, precision/scientific flags, hardware, and compilation-cache conditions. Report queue time, GPU allocation seconds, end-to-end walltime, per-member time, peak GPU/host memory, compiled buckets, cache hit behavior, and failure/recovery overhead.
- [ ] Verify corresponding predictions are scientifically equivalent within a stated comparison protocol; confidence and structure differences need interpretation, not merely matching filenames.
- [ ] Do **not** claim a speedup or turn batching on by default without measured evidence. Default opt-in until reliable operation is established.
- [ ] Have an independent Examiner verify real browser controls, per-target status, result exploration, failure rendering, and screenshots on the exact candidate head.
- [ ] Obtain independent Adviser review, address merge-blocking findings on PR threads, and complete the independent Campaign Acceptance Auditor pass at exact final head.
- [ ] Final cleanup: retire temporary root `TODO_AF3_CONTINUOUS_BATCH.md` and `DESIGN_AF3_CONTINUOUS_BATCH.md` by incorporating enduring truths into their owning contracts/docs. Verify CI, scientific receipts, and release claims. Do not merge or deploy without maintainer authorization.

## Stop conditions

Stop and post a concise PR blocker with evidence if the verified runtime cannot retain a model across independent predictions, compatibility cannot be maintained without uncontrolled Core changes, publication/recovery cannot be made trustworthy, or AF3 permissions/terms are unclear. A blocked scientific live test must remain **blocked**, not be represented as synthetic success.

## Coordination

Commander owns exact-head inventory, scope and Owner isolation, serialized integration, and control ledger. Domain Owners implement isolated changes. Independent Campaign Adviser challenges architecture and science; Examiner tests browser/science; Acceptance Auditor independently verifies the submitted exact-head result. The maintainer alone decides squash-merge and production deployment.
