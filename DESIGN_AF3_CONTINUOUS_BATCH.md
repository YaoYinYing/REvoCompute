# Design intent: AlphaFold 3 Continuous Batch Inference

**Status:** Architectural handoff for one draft Campaign PR. Not an implementation claim.

## Why this is one PR

Multi-input execution is not production-ready without per-target identities, crash recovery, resource bounds, and trustworthy result publication. The implementation and validation therefore form **one** acceptance boundary. AlphaPulldown is a separate, downstream scientific-workflow integration and is explicitly out of scope.

## Existing repository boundary (recheck before coding)

At campaign creation the REvoCompute `alphafold3` runtime family exposes a single named `specification` input (`alphafold3_specification`, JSON, cardinality 1), a CPU-only `features` stage, and a GPU `model` stage. The Runner currently uses `run_alphafold.py --json_path=<one input>`, finds exactly one processed `*_data.json`, and checks its SHA-256 before inference. The family has `alphafold3_noncommercial` access control and read-only weight/database mounts. It supports full, prepare-only and model-only/reused-features execution. The current upstream revision is pinned in `docker/runners/alphafold3/upstream.json`; no changes should float to upstream HEAD.

Existing owners to inspect:
- `docker/runners/alphafold3/tasks/predict/task.yaml`: scientific input, parameter, workflow, and result semantics.
- `docker/runners/alphafold3/run.sh`: runner entrypoint and current single-input stage logic.
- `docker/runners/alphafold3/plugin.yaml`, `runner.yaml`, `upstream.json`: runtime identity, mounts and restricted access.
- `docs/operator-guide/runner-configuration.md`: Composer/Slurm placement and stage semantics.
- `CLAUDE.md` and `docs/agents/single-pr-campaign.md`: ownership, tests, evidence, and review gates.

**Invariant:** A batch is one user's immutable scientific submission containing multiple **independent** AF3 prediction members, not one giant AF3 complex, and not a service where unrelated users' tasks are secretly coalesced.

## Proposed separation of concerns

```text
User / BioNuTA / upload
  -> named, bounded, immutable AF3 input collection
  -> Server admission + entitlement + resource policy (existing authority)
  -> frozen batch membership (unique IDs, hashes, seeds, parameters)
  -> Composer features stage [CPU-only; per-member validation/reuse]
  -> validated processed-input artifacts
  -> Composer model stage [Slurm GPU allocation]
       -> trusted bounded batch manifest
       -> resident AF3 model process (sequential members)
       -> per-member checkpoint + validated candidate outputs
  -> secure publication / typed artifact manifest
  -> existing result workspace + batch aggregate summary
```

The **scheduler unit** is an allocation/stage, while the **scientific unit** is a prediction member; the public-facing Task remains the authorized, accountable parent. No second scheduler, no nested `sbatch`, and no permanent GPU service.

### Public input contract

Prefer extending the existing task's named `specification` role cardinality to a bounded collection if real Core/UI consumers preserve the one-input path. Alternative: a separate batch task type in the same family **only** if required by demonstrated compatibility constraints; source scientific parameters from one canonical owner rather than manually duplicating defaults. The Commander must present the compatibility decision before implementation.

The input contract must preserve each document's identity, original bytes, SHA-256, dialect, chain composition, random seeds, and supplied MSA/template content. Filename and order are not scientific identifiers. For independently predicted members, each AF3 JSON remains a distinct upstream fold job; within a JSON, multiple chains are one prediction. AF3 Server-dialect top-level lists must be handled under the pinned upstream converter's actual semantics; avoid interpreting list entries as unrelated user Task roles.

File-backed JSON paths (`unpairedMsaPath`, `pairedMsaPath`, `templates[].mmcifPath` and equivalent) are a trust boundary. Do not treat a JSON reference as permission to read arbitrary shared filesystem paths or URLs. Validate against the existing role-based immutable snapshot mechanism, explicitly reject unsupported references, and document any preserved single-task limitations rather than silently broadening them.

### Prepared features and execution

The CPU stage should produce one independently validated processed AF3 JSON per member and record digest plus compatible database/model/data-pipeline identity. Reusing a prepared feature requires a typed trusted artifact and compatibility proof, not a matching filename. If this requires changes to `model_only` support, keep the single-input behavior intact and state the batch feature-reuse limitations precisely.

Upstream AlphaFold 3 has native multi-input `--input_dir`, per-input sequential execution and a resident model-runner lifetime in a single invocation. Use this as the starting performance baseline. Its single process should not be conflated with strong error isolation: a Python exception may be recoverable, whereas a fatal GPU/XLA fault requires ending the process/allocation. If native CLI behavior aborts on the first invalid member, consider a minimal pinned adapter at the **Runner-owned** seam; do not fork a second AF3 implementation or claim that a shell loop over new Python processes is resident execution.

Keep a verified batch manifest that maps stable member IDs to staged, sandbox-contained JSON paths and dedicated output directories. Create all paths within a trusted attempt workspace. The execution wrapper must not take user-provided shell commands, output locations or raw `--input_dir` paths.

### Batching policy

Members may be grouped by compatible model runner, scientific flags, effective seeds, sequence token count and AF3 compilation buckets. Groups should be deterministic for a pinned input manifest and policy revision. Batch size and time are bounded by explicit operator policy. A group performs **sequential** inference: expected peak GPU memory primarily depends on the largest active prediction plus XLA/model allocator retention, while time depends on the sum of predictions and compilation. This is not a claim of guaranteed GPU memory reclamation between members.

A first practical mode can use one batch allocation when the bounded batch fits. If limits require multiple allocations/groups, keep those child executions under the same parent Task and canonical Composer lifecycle; do not create a private queue. A batch must never bypass AF3 non-commercial authorization, GPU admission, Slurm fairness, or operator budget. Recording resource usage at the allocation level is authoritative; any per-member attribution is an estimate, not fabricated direct measurement.

The JAX compilation cache is an optimization, not a correctness prerequisite. Prefer isolated permissions and digest-based versioning. Benchmark cold cache, warm cache, isolated jobs, and one resident process with the same supported hardware, model, input sets and scientific parameters.

### Results and recovery contract

Each member needs a stable logical ID, frozen input fingerprint, effective scientific flags/seeds, attempt history, validated structure and confidence files, source model and database identity, and an explicit outcome. Member progress is finer-grained evidence below the existing Task state machine; never introduce a new global `PARTIAL_SUCCESS` state without architectural review.

Suggested conceptual output organization (not a mandate to change existing result globs):

```text
features/<member-id>/..._data.json
modeling/<member-id>/..._model.cif
modeling/<member-id>/..._summary_confidences.json
reports/batch-membership.json
reports/batch-summary.json
```

Only a validated and published artifact manifests as completed. Crash between a filesystem write and database update must reconcile on retry; a file's existence does not imply success. The batch summary must distinguish succeeded, failed, skipped, and not yet attempted members. Retry only the affected members if frozen input/science/runtime identities remain compatible. For fatal resident-process failures, restart with a new process rather than continuing to use a potentially damaged GPU runtime.

Never overwrite successful outputs to make a retry easier. Preserve original per-member artifacts and evidence in the current results model, with a secure publication walker and bounded storage quota. A failing member must not cause the entire batch to be reported as successful; check the current Task terminal-state contract before selecting the user-visible mapping.

### Evidence before merging

The PR is not merge-ready merely because JSON upload and a loop work. Required evidence includes single-input compatibility, native/resident multi-input scientific output, failure and restart injection, cancellation, per-member artifact retrieval in the existing UI, exact-head Slurm/Apptainer live run, and a transparent speed/peak-memory comparison against an isolated-job control. Where GPU live validation is blocked, report **blocked**, not **passed**.

Use the Campaign Protocol: isolated implementation owners; Independent Campaign Adviser; independent browser/science Examiner; independent final Campaign Acceptance Auditor with exact-head verdict. Technical findings live in PR threads. Commander integrates and coordinates. Maintainer retains squash-merge and production-promotion authority.

## Relevant external designs

- [Official AlphaFold 3 input interface](https://github.com/google-deepmind/alphafold3/blob/main/docs/input.md) — directory of JSON inputs and dialect behavior.
- [Official AlphaFold 3 performance guide](https://github.com/google-deepmind/alphafold3/blob/main/docs/performance.md) — reusable data-pipeline results, JAX cache, compilation buckets and memory.
- [AlphaPulldown resident PredictionBatch](https://github.com/KosinskiLab/AlphaPulldown/blob/main/alphapulldown/prediction/prediction_batch.py) — adapter/session/individual job abstraction and per-job outcomes.
- [AlphaPulldownSnakemake batching](https://github.com/KosinskiLab/AlphaPulldownSnakemake/blob/main/README.md#batching-small-jobs-into-one-slurm-job) — size-aware grouping, process lifetime, and restart tradeoffs.

These are references, not permission to share restricted AF3 assets, bypass upstream terms, or embed an independent Snakemake/Slurm orchestration layer inside REvoCompute.
