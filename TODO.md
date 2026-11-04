# Stage Selection and Artifact Reuse — Campaign TODO

> Successor to closed planning PR #119; source requirements preserved in
> [#130's preserved-requirements record](https://github.com/YaoYinYing/REvoCompute/pull/130#issuecomment-6490641559).
> Base: `main` `6d726f54`. **Draft implementation. NO MERGE.** Remove this file before final review.

## Objective

Let a scientist submit FULL, PREPARE_ONLY or MODEL_ONLY for a Runner Task **only where the pinned
upstream supports that split**, and let MODEL_ONLY consume a typed, provenance-bound artifact from an
earlier authorized run. One graph, one StageRun authority — no second DAG and no compatibility workflow.

## Grounded facts (verified on this base)

- `revocompute/execution_graph.py` compiles `task.yaml` `workflow:` into a frozen `CompiledGraph`; ports
  are typed and edges bind `producer:port`.
- `revocompute/task_types/__init__.py` loads `workflow`, `inputs`, and `outputs`; AF2
  (`docker/runners/alphafold/tasks/alphafold/task.yaml`) and AF3
  (`docker/runners/alphafold3/tasks/predict/task.yaml`) declare `features -> model` and already invoke
  distinct upstream entrypoints (`-s features`, `-s model`).
- `revocompute/task_runtime.py:_materialize_stage_inputs` already copies a producer's verified artifacts
  into a consumer's `stage_inputs` with digest re-verification. Cross-Task reuse does not exist.
- `stage_runs` is the only stage authority (`docs/developer-guide/execution-stage-state.md`).

## M0 — upstream proof and contract declaration

- [ ] Re-verify in the pinned AF2/AF3 source that `features` and `model` are independently runnable and
      that supplied MSA/templates bypass search without skipping mandatory featurization. Record the exact
      upstream files/commands in the PR thread.
- [x] Declare supported modes in the owning `task.yaml` (no Core mode registry): stage selection and
      project the declaration through the Task Type API. AF2/AF3 declare `full` and `prepare_only`.
- [ ] Refuse MODEL_ONLY on a Task whose upstream cannot consume prepared features (for example OpenDDE)
      rather than inventing a split.

## M1 — one graph, selected subset

- [x] Extend graph compilation to accept a declared mode and omit only stages the manifest permits. The
      graph digest covers the selection; a mode that drops a required producer is refused.
- [x] Omitted stages create no `StageRun`, no reservation, no allocation and no GPU requirement; admission
      and placement follow the selected stages.
- [ ] `FULL` must produce byte-identical stage inputs/parameters to today's all-stage path.
- [ ] Keep `stage_runs` the sole writer; do not add a mode-specific status authority.

## M2 — typed cross-Task artifact reuse

- [ ] Submission accepts a reference to a completed artifact: source Task (owned by the caller), stage,
      output port, and immutable digest. The server re-verifies ownership, completion, runtime/model
      identity, type, and digest before any allocation.
- [ ] Bind the verified artifact into the consumer stage through the existing `stage_inputs` mechanism;
      never let a user path or filename decide identity.
- [ ] Refuse with a named reason: stale/superseded artifact, wrong type or port, producer failed,
      different structure/sequence or chain mapping, incompatible model/runtime identity, not owned by
      caller, quarantined/expired.
- [ ] Preserve the original producing Task and its `ResultManifest`; reuse is a new provenance edge, not a
      mutation.
- [ ] Accounting: a reused stage is not billed again; a stage attempt that never got an allocation creates
      no ledger fact.

## M3 — UI and API

- [x] Create-Task exposes only manifest-declared modes and submits the selected intent.
- [ ] Show the required artifacts and compute before submission, and offer the caller's validated
      reusable artifacts for MODEL_ONLY.
- [ ] Result/API surface shows per-stage mode, omission reason, source artifact provenance and the reused
      identity.
- [ ] Browser tests cover available/unavailable modes and refusal states.

## Acceptance

- [ ] Mutation-sensitive tests: removing each reuse check fails its test.
- [ ] AF2/AF3 FULL parity on pinned fixtures; PREPARE_ONLY publishes verified reusable artifacts and opens
      no GPU allocation; MODEL_ONLY refuses mismatched identity and accepts a matching one.
- [ ] Interrupted/resumed stage recovers idempotently without duplicate publication or allocation.
- [ ] Exact-head CI, independent Adviser, and Campaign Acceptance Auditor PASS. Real AF2/AF3 target-host
      receipt is a release gate, not a CI substitute.

## Non-goals

No unrestricted DAG/pipeline editor, no user-authored executable, no invented upstream stage splits, no
second stage writer, no viewer-driven output conversion.
