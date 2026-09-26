# REvoCompute TODO — Persistent Multi-Input Execution and Adaptive OOM Recovery

## Goal

Extend the REvoCompute Runner execution model to support:

1. **Persistent multi-input execution**
   - One task may contain multiple independent work items.
   - Expensive model/runtime initialization occurs once per task.
   - Work items are processed continuously within the same runner process where supported.
   - Completed work items are persisted independently and are not recomputed after interruption.

2. **Adaptive OOM recovery**
   - Runners start with their upstream/default execution parameters.
   - A lightweight CPU-side VRAM estimator observes runtime behavior without interfering with successful tasks.
   - When CUDA OOM occurs, a resource planner automatically retries using semantically equivalent lower-memory execution settings.
   - Once sufficient evidence exists for a known failure region, the planner may proactively avoid configurations that are already known to OOM.
   - Resource adaptation must never silently change the scientific computation requested by the user.

This work should initially target **ESMFold and SimpleFold**, while establishing generic infrastructure that other runners may reuse.

---

# 1. Execution Model

## 1.1 Separate Task, Work Item, Worker, and Runtime

Refactor the execution model so that these concepts are explicit:

```text
Task
    A single user submission.

Work Item
    One independently executable input inside the task.

Worker
    The process executing work items.

Runtime
    Expensive reusable state owned by the worker, such as:
    - loaded model weights
    - CUDA context
    - database/index state
    - compiled kernels
    - initialized inference modules
```

A task may contain one or many work items.

A worker may fail and restart without invalidating already completed work items.

A work-item failure must not automatically imply whole-task failure.

Do not introduce distributed worker infrastructure, Triton, Ray, Temporal, or another scheduler.

---

# 2. Persistent Multi-Input Execution

## 2.1 Add Multi-Input Task Support

Allow compatible runners to receive multiple inputs in a single REvoCompute task.

Initial supported forms should include FASTA or an equivalent normalized sequence collection.

Example normalized representation:

```json
{
  "items": [
    {
      "id": "protein_001",
      "sequence": "M..."
    },
    {
      "id": "protein_002",
      "sequence": "M..."
    }
  ]
}
```

Requirements:

- preserve input identifiers;
- reject duplicate or unsafe identifiers;
- normalize identifiers before creating filesystem paths;
- preserve original input ordering in metadata;
- allow execution ordering to differ internally if future scheduling requires it.

---

## 2.2 Persistent Runtime Lifecycle

Introduce or formalize a runner lifecycle similar to:

```text
prepare()
    ↓
initialize_runtime()
    ↓
process(item_001)
    ↓
process(item_002)
    ↓
process(item_003)
    ↓
...
    ↓
finalize()
```

`initialize_runtime()` should contain expensive initialization that should occur once per task.

Examples:

```text
load model weights
move model to GPU
initialize tokenizer
initialize auxiliary modules
initialize CUDA runtime
load indexes/databases
```

Do not reload the model between successfully processed work items.

---

## 2.3 Preserve Upstream Execution Models

Do not reimplement batching where upstream tools already provide suitable behavior.

### ESMFold

Prefer upstream-supported bulk FASTA execution and existing memory-control parameters where compatible with the current runner.

Support upstream batching behavior rather than manually spawning one ESMFold process per sequence.

### SimpleFold

Preserve the upstream model lifecycle where models are initialized once and multiple structures are processed afterward.

Do not convert each FASTA entry into an independent process invocation.

---

# 3. Work-Item State Model

Each work item should have an explicit state.

Minimum states:

```text
PENDING
RUNNING
SUCCEEDED
FAILED_INPUT
FAILED_RESOURCE
FAILED_RUNTIME
CANCELLED
```

Optional internal state:

```text
COMMITTING
```

The task state should be derived from item states.

Suggested task-level outcomes:

```text
SUCCESS
PARTIAL_SUCCESS
FAILED
CANCELLED
CANCELLED_PARTIAL
```

Examples:

```text
500 / 500 succeeded
→ SUCCESS

497 succeeded, 3 irreducible OOM failures
→ PARTIAL_SUCCESS

0 succeeded, all invalid
→ FAILED
```

Do not mark an entire multi-input task as failed solely because one work item failed.

---

# 4. Durable Per-Item Results

## 4.1 Atomic Result Commit

Each work item must write into a temporary location first.

Example:

```text
outputs/
├── .tmp/
│   └── protein_001/
└── protein_002/
```

After successful completion and validation:

```text
outputs/.tmp/protein_001/
    ↓ atomic rename
outputs/protein_001/
```

A final output directory must mean:

> this work item completed and its required artifacts passed validation.

A partially written directory must never be mistaken for a completed result.

---

## 4.2 Resume Semantics

On task restart:

1. read the task manifest;
2. inspect already committed item outputs;
3. validate completed results where necessary;
4. skip successful items;
5. resume unfinished items.

Example:

```text
001 SUCCESS
002 SUCCESS
003 RUNNING when worker died
004 PENDING
```

Restart behavior:

```text
001 skip
002 skip
003 retry/resume
004 execute
```

The same mechanism should support:

- runner crash;
- CUDA context restart;
- node interruption;
- Slurm requeue;
- server restart where sufficient task state exists.

---

# 5. Task Manifest

Introduce a machine-readable task manifest.

Suggested structure:

```json
{
  "version": 1,
  "task_id": "...",
  "runner": "simplefold",
  "created_at": "...",
  "items": [
    {
      "id": "protein_001",
      "status": "SUCCEEDED",
      "attempts": 1,
      "output_path": "outputs/protein_001",
      "started_at": "...",
      "finished_at": "...",
      "resource_events": []
    }
  ]
}
```

Requirements:

- update atomically;
- survive worker restart;
- do not rely solely on process memory;
- make writes idempotent where possible;
- do not duplicate completed outputs after retries.

---

# 6. Progress Reporting

Do not use stdout as the only progress mechanism.

Expose structured progress:

```text
total_items
completed_items
failed_items
pending_items
current_item
current_attempt
```

Example UI/API state:

```text
217 / 500 completed
3 failed
1 running
279 pending
Current: protein_221
```

Partial results should become available as soon as individual work items complete.

Do not require the entire task to finish before completed structures can be viewed or downloaded.

---

# 7. OOM Handling

## 7.1 Default Path Must Remain Unmodified

The normal execution path is:

```text
upstream/default parameters
        ↓
execute
        ↓
success
        ↓
record resource observations
        ↓
continue
```

The resource planner must **not** alter successful executions simply because it predicts that another configuration might be more efficient.

Default runner behavior remains authoritative unless resource adaptation is required.

---

## 7.2 OOM Is a Recoverable Item-Level Event

On CUDA OOM:

```text
OOM
 ↓
record event
 ↓
release transient tensors
 ↓
garbage collection where appropriate
 ↓
clear safe CUDA caches where appropriate
 ↓
ask Resource Planner for an equivalent lower-memory execution plan
 ↓
retry within bounded limits
```

Do not immediately restart the whole REvoCompute task.

Do not automatically restart the whole Slurm job.

---

## 7.3 Worker Restart Is a Last-Resort Recovery Mechanism

Restart the worker/runtime only when the CUDA process appears unhealthy or continued execution is unsafe.

Examples may include:

```text
CUDA illegal memory access
CUDA context corruption
repeated allocator failure after cleanup
subsequent trivial operations failing
runtime-specific unrecoverable GPU errors
```

Recovery:

```text
checkpoint task state
↓
terminate worker
↓
destroy CUDA context
↓
restart worker
↓
reload model
↓
resume unfinished items
```

Already completed items must not be recomputed.

---

# 8. Bounded Recovery

Every adaptive retry path must have a finite retry budget.

Example:

```text
default
↓ OOM
fallback level 1
↓ OOM
fallback level 2
↓ OOM
FAILED_RESOURCE
```

Never implement an unbounded:

```text
while OOM:
    retry()
```

Record each attempt and fallback.

Example:

```json
{
  "attempt": 2,
  "reason": "CUDA_OOM",
  "previous_plan": "...",
  "new_plan": "...",
  "peak_reserved_vram_mb": 22134
}
```

---

# 9. Preserve Scientific Semantics

This is a hard constraint.

The scheduler may change **how** the requested computation is executed.

It must not silently change **what** computation was requested.

## Allowed automatic resource adaptations

Examples:

```text
batch size reduction
token-budget reduction where semantics remain equivalent
splitting one batch into several batches
splitting requested samples into smaller execution groups
chunk size changes where mathematically supported
CPU offload
work-item execution order
memory-efficient backend selection if numerically compatible
```

Example:

```text
5 requested samples

5 at once
→ OOM

2 + 2 + 1
→ allowed
```

The user still receives five requested samples.

## Do not change silently

Examples:

```text
number of requested samples
number of recycles
model version
scientifically meaningful model parameters
user-selected seeds
precision when it materially changes requested behavior
MSA/template usage
requested input content
```

Example:

```text
samples = 5
→ samples = 2
```

is not resource adaptation and must not happen automatically.

---

# 10. Determinism and Seeds

Resource adaptation must preserve deterministic sample identity where the underlying runner permits it.

If five samples were requested:

```text
sample_0 → seed_0
sample_1 → seed_1
sample_2 → seed_2
sample_3 → seed_3
sample_4 → seed_4
```

Splitting:

```text
5
→ 2 + 2 + 1
```

must not silently regenerate a different seed mapping.

Record the effective seed for each resulting artifact.

---

# 11. Resource Observation

Create a lightweight resource observation layer.

For each execution attempt, record useful features such as:

```text
runner
runner version
model version
GPU model/class
GPU total memory
runtime fingerprint
sequence length
sequence count
batch size
sample count
recycle count where applicable
chunk size
precision
offload mode
peak allocated VRAM
peak reserved VRAM
runtime
success / OOM
fallback used
```

Not every runner needs every feature.

Use a runner-specific feature extractor where necessary.

---

# 12. VRAM Estimator

## 12.1 Purpose

The estimator exists to support OOM recovery and eventually avoid already learned OOM regions.

It must not become a general-purpose scheduler.

It must remain lightweight and CPU-only.

Hard constraint:

```text
VRAM estimator must never require GPU resources.
```

---

## 12.2 Cold Start

The estimator starts with default parameters / baseline heuristics.

During normal operation:

```text
successful execution
↓
observe only
↓
record actual peak VRAM
```

Do not alter execution.

The estimator should accumulate useful observations before being trusted for proactive intervention.

---

## 12.3 Learning Target

Prefer predicting resource demand instead of only classifying OOM.

Useful targets:

```text
expected peak VRAM
conservative upper-bound VRAM
P90/P95 peak VRAM estimate
```

OOM observations should be retained as censored constraints:

```text
required_vram > available_vram
```

Do not discard OOM events as unusable samples.

---

## 12.4 Initial Model

Keep the first implementation intentionally small.

Suitable candidates include:

```text
polynomial / ridge regression
gradient-boosted trees
small MLP
```

A small neural network is acceptable, but do not introduce a large ML framework requirement solely for the estimator if an existing dependency or simpler model is sufficient.

If a neural network is used, it should remain tiny and CPU-only.

Example conceptual model:

```text
features
↓
small hidden layer
↓
small hidden layer
↓
VRAM prediction
```

---

## 12.5 Hybrid Baseline + Learned Residual

Prefer a hybrid design where appropriate:

```text
baseline_vram = analytical_or_empirical_function(features)

correction = learned_model(features)

predicted_vram =
    baseline_vram + correction
```

This improves cold-start behavior and reduces unsafe extrapolation.

---

# 13. Estimator Intervention Policy

The estimator should begin in observation mode.

Conceptual states:

```text
OBSERVE
RECOVER
AVOID_KNOWN_FAILURE
```

### OBSERVE

Default state.

Successful tasks:

```text
run unchanged
record data
```

### RECOVER

Entered after an OOM.

The planner uses available observations and fallback rules to generate a safer equivalent plan.

### AVOID_KNOWN_FAILURE

After repeated evidence establishes that a parameter region reliably exceeds available VRAM, the planner may avoid reproducing an already known failure.

Do not intentionally trigger the same well-characterized OOM on every future task.

Use conservative confidence thresholds.

Unknown/extrapolated regions should fall back to safe heuristics rather than trusting an overconfident learned prediction.

---

# 14. Resource Planner

Keep the planner separate from the estimator.

Architecture:

```text
ExecutionObserver
       │
       ↓
 VRAMEstimator
       │
       ↓
ResourcePlanner
       │
       ↓
ExecutionPlan
```

Responsibilities:

### ExecutionObserver

Collect actual execution data.

### VRAMEstimator

Estimate memory demand.

### ResourcePlanner

Choose an equivalent lower-memory execution configuration.

The estimator must not directly mutate runner parameters.

This separation is required for debuggability.

---

# 15. Runner-Specific Fallback Policies

Generic infrastructure should support runner-specific adaptation rules.

Do not encode runner names throughout server core logic.

Prefer runner metadata or a runner-owned policy implementation.

Example conceptual metadata:

```yaml
execution:
  multi_input: true
  persistent_runtime: true
  partial_results: true
  resume: true

resource_adaptation:
  oom_recovery: true
  policy: runner_defined
```

---

# 16. ESMFold Initial Policy

Investigate and preserve upstream-supported mechanisms.

Potential equivalent memory adaptations include:

```text
reduce effective batch/token budget
process fewer sequences together
adjust chunk size
CPU offload where supported
```

Do not silently modify biological/scientific inputs.

Prefer upstream mechanisms over custom tensor-level reimplementations.

---

# 17. SimpleFold Initial Policy

Preserve upstream model initialization once per task.

Ensure multiple FASTA inputs are processed within the same initialized runtime where upstream design permits.

Treat:

```text
number of proteins
```

and:

```text
samples per protein
```

as separate resource dimensions.

When sample multiplicity causes OOM:

```text
N samples together
→ split into equivalent smaller groups
```

while preserving:

```text
total requested samples
sample identities
seeds
result metadata
```

---

# 18. Resource History Storage

Keep storage simple.

A local SQLite database or equivalent lightweight persistent store is sufficient initially.

Possible schema:

```text
resource_observations
- id
- runner
- runner_version
- model_version
- runtime_fingerprint
- gpu_class
- feature_json
- peak_allocated_vram
- peak_reserved_vram
- runtime_seconds
- outcome
- error_class
- created_at
```

Do not introduce an external database solely for this subsystem.

---

# 19. Runtime Fingerprinting

Resource observations may become invalid when the runtime changes.

Include enough information to distinguish materially different execution environments.

Examples:

```text
runner version
model revision
PyTorch/JAX version
CUDA version
attention backend
precision
GPU architecture
major inference implementation version
```

Do not necessarily discard all old data after every minor change.

Define a compatibility fingerprint that can evolve later.

---

# 20. Cancellation

Support graceful cancellation at work-item boundaries.

Preferred default:

```text
cancel requested
↓
finish or safely abort current item
↓
do not start another item
↓
persist manifest
↓
finalize partial results
```

Provide force termination separately if needed.

A cancelled multi-input task may retain all completed outputs.

---

# 21. Partial Results

Completed outputs should be available before the task ends.

Result Workspace should be capable of representing:

```text
✓ completed item
⟳ running item
○ pending item
✕ failed item
```

Do not block access to successful structures because later work items remain pending.

---

# 22. Output Provenance

Every work item should have enough provenance to reproduce its computation.

Recommended metadata:

```text
runner version
model version
input hash
parameters
effective execution plan
requested seeds
effective seeds
resource fallback events
start time
finish time
```

Distinguish:

```text
requested parameters
```

from:

```text
execution-only resource adaptations
```

---

# 23. Slurm Compatibility

Design item-level durability so that future or existing low-priority Slurm jobs can safely survive requeue/preemption.

Do not make Slurm requeue a requirement for the first implementation, but ensure the runner can:

```text
restart
load manifest
skip completed items
resume unfinished items
```

This is necessary for long batch tasks running under lower-priority QoS.

---

# 24. Do Not Implement Yet

Explicitly keep these outside the current scope:

```text
Triton Inference Server
Ray
Temporal
cross-task persistent GPU workers
shared model pools
multi-node distributed inference
iteration-level continuous batching
custom CUDA schedulers
general-purpose cluster resource prediction
aggressive throughput optimization before OOM evidence exists
```

Do not turn this task into a new orchestration framework.

---

# 25. Tests

Add tests for the generic execution model and both initial runners.

## Multi-input execution

Verify:

```text
model/runtime initialized once
multiple inputs processed
each output committed independently
final task summary correct
```

## Resume

Simulate:

```text
items 1–3 complete
worker terminates during item 4
task restarts
```

Verify:

```text
1–3 are not recomputed
4 resumes/retries
remaining items execute
```

## Partial failure

Simulate one invalid or failed item among successful items.

Verify:

```text
remaining items continue
task becomes PARTIAL_SUCCESS
```

## OOM recovery

Mock or inject a deterministic OOM.

Verify:

```text
default plan fails
planner receives OOM
fallback is generated
bounded retry occurs
successful retry continues subsequent items
```

## Irreducible OOM

Verify:

```text
all allowed fallbacks exhausted
item → FAILED_RESOURCE
remaining items continue
```

## Scientific semantics

Verify automatic adaptation never changes:

```text
requested sample count
seed identities
scientifically meaningful parameters
model selection
```

## Atomic outputs

Kill execution during output generation.

Verify incomplete temporary output is not interpreted as success.

## Estimator behavior

Verify:

```text
successful tasks do not trigger parameter modification
observations are recorded
known OOM evidence can inform future recovery
estimator remains CPU-only
```

---

# 26. Documentation

Update Runner Protocol documentation to explain:

```text
single-input runners
multi-input runners
persistent runtime lifecycle
work-item state
partial success
resume semantics
OOM recovery
resource adaptation boundaries
scientific parameter preservation
```

Provide a minimal reference/example runner implementing:

```text
initialize once
process several work items
commit outputs individually
resume from manifest
```

Avoid making the example dependent on a large model.

---

# 27. Implementation Order

Implement in this order:

```text
1. Work-item abstraction and manifest
2. Multi-input task parsing
3. Persistent runner lifecycle
4. Atomic per-item output commit
5. Resume and partial-success semantics
6. Structured progress reporting
7. ESMFold continuous/bulk execution
8. SimpleFold continuous execution
9. Resource observation collection
10. Explicit OOM classification
11. Runner-specific bounded fallback policies
12. CPU-only VRAM estimator
13. Learned known-failure avoidance
14. UI exposure for per-item progress and partial results
```

Do not start from the estimator.

The execution lifecycle and durable item state must exist first.

---

# Acceptance Criteria

This work is complete when the following scenario works reliably:

```text
User submits many sequences to ESMFold or SimpleFold.

The runner starts once.
The model is loaded once.
Multiple inputs are processed continuously.
Completed outputs become available independently.

Normal executions use upstream/default parameters unchanged.

If an item causes CUDA OOM:
    the event is recorded;
    the planner chooses an equivalent lower-memory execution plan;
    retry is bounded;
    successful recovery continues the task;
    irreducible failure affects only that item.

If the worker must restart:
    completed work is preserved;
    the model is reloaded;
    unfinished work resumes.

The CPU-only VRAM estimator learns from observed runs without consuming GPU resources or controlling successful executions.

Automatic adaptation never changes the scientific computation requested by the user.
```

The resulting implementation should remain small, runner-oriented, testable, and compatible with the existing REvoCompute architecture.
---

# 28. Appended Constraints (this revision)

These instructions were added after the design above was written. They are
binding and narrow the implementation; they do not replace earlier sections.

## 28.1 Keep the estimator a lightweight control-plane component

- Do **not** add PyTorch, JAX, TensorFlow, Triton, Ray, or any other ML/runtime
  framework to the REvoCompute **server** image for this feature.
- Prefer the smallest numerical dependency already present. NumPy is already
  present and a NumPy-only implementation is sufficient.
- Acceptable estimator families: polynomial/ridge regression, recursive/online
  regression, gradient-free fitted models, or a very small hand-written MLP.
  Do not add a heavyweight dependency because the component "learns".
- Treat this as system identification, not deep learning. Learn a
  low-dimensional mapping:

```text
runner/model/runtime/GPU + sequence length + batch size + sample count
    + relevant execution parameters
  -> observed peak VRAM / OOM boundary
```

- Keep the scope narrow: persistent multi-input execution, item-level
  checkpoint/resume, partial success, bounded OOM recovery, lightweight VRAM
  observation and learning. Do not grow this into a generic inference server,
  global cluster scheduler, cross-task model pool, or research-grade learned
  scheduler.
- Review the server image dependency graph while implementing. If the estimator
  work would introduce a substantial or compiled dependency, stop and replace
  it with a lighter implementation unless that dependency already exists for
  another justified server-side purpose.

## 28.2 Intervention policy and separation of responsibilities

- The estimator must be able to answer **unknown / low-confidence /
  out-of-distribution** instead of always returning a trusted value. A
  prediction carries an expected value, a conservative upper bound, and
  confidence/applicability. Outside the learned domain the planner falls back
  to conservative heuristics rather than trusting extrapolation.
- Not every observation is equally valid training data. Interference from other
  GPU users, background allocations, or runtime instability can contaminate an
  observation. Preserve such observations for diagnostics but exclude or
  down-weight them for estimator updates.
- Separate stable workload demand from transient device availability. Never
  learn "low free VRAM because another process is running" as "this workload
  needs more VRAM".
- Prefer the factored form:

```text
predicted total VRAM = runtime/model baseline + workload-dependent incremental VRAM
```

- Measurement happens **inside the runner**, using the framework that owns the
  GPU allocations (PyTorch memory statistics for PyTorch runners, the
  equivalent for other runtimes). The server consumes a normalized observation
  schema and must not install PyTorch/JAX to collect measurements.
- Persist a normalized observation schema distinguishing: baseline memory after
  runtime/model initialization; peak task/process memory; peak allocated and
  reserved memory where available; outcome (success / OOM); device profile;
  runtime and model fingerprint; workload and execution features; and
  observation quality/confidence.
- The estimator must support runtime/model evolution. Old observations stay
  historical but must not remain equally authoritative after model revisions,
  backend changes, framework upgrades, or CUDA changes. Runtime fingerprints
  and compatibility rules demote stale observations to a weaker prior instead
  of silently contaminating a new execution profile.
- Rollout is staged and explicit/configurable:

```text
OBSERVE   collect data only; never modify successful execution
RECOVER   use estimator/planner only after a real OOM
AVOID     after sufficient high-confidence evidence, proactively skip
          configurations already known unsafe for the same workload/device/
          runtime profile
```

  The system must be runnable in observation-only mode.
- Fallback policy stays **runner-owned**. The estimator may say a configuration
  is unsafe; it must not invent runner parameters or scientific adaptations.
  Each runner declares the resource adaptations valid for it and the planner
  chooses only among those. No `if runner == "esmfold": ...` branches in server
  core; use runner-provided metadata/policy hooks.
- The knowledge base distinguishes **known-safe**, **uncertain**, and
  **known-failure** regions. The practical question is not arbitrary numerical
  precision but whether a plan is safe to attempt, uncertain and therefore
  conservative, or already known to exceed the envelope.
- The subsystem stays inspectable: it must be possible to explain, from
  recorded observations and policy decisions, why a plan was allowed, adapted,
  or rejected. No opaque learned scheduler.

## 28.3 Heterogeneous FASTA inputs and the ExecutionQueue

- Handle highly heterogeneous FASTA explicitly, e.g. 100 sequences from 100 to
  3000 aa.
- Add an `ExecutionQueue` / planning layer between normalized Work Items and the
  persistent Runner runtime. Its first responsibility is a stable execution
  order and applying already-learned resource constraints — not sophisticated
  tensor batching.
- For sequence runners, length-aware ordering or bucketing is allowed so that
  extremely short and extremely long sequences need not execute strictly in
  FASTA order. Original input order is preserved in metadata and result
  presentation even when execution order differs.
- The initial optimization target stays **persistent serial execution**: load
  the runtime once, process many Work Items continuously, commit each result
  independently, continue after item-level failures.
- True heterogeneous tensor batching is not a prerequisite. Use upstream-native
  batching only where it already exists and is safe.
- The ResourcePlanner may split one requested computation into several
  semantically equivalent groups (`5 samples -> 2 + 2 + 1`) provided the
  complete requested output set, seeds, and scientific parameters are
  preserved.
- Once sufficient historical evidence establishes a known OOM region for the
  same runner/runtime/GPU class, do not deliberately repeat that configuration
  on every future task. The estimator stays passive for ordinary successful
  workloads but may proactively avoid a well-characterized failure region.
- Intended end-to-end behavior:

```text
FASTA -> normalized Work Items -> ExecutionQueue -> one persistent
model/runtime -> item-by-item execution -> atomic result commit ->
resource observation -> bounded OOM adaptation when needed -> continue
remaining items -> final SUCCESS/PARTIAL_SUCCESS summary
```

## 28.4 Heterogeneous GPU clusters

- Do not assume a task always runs on the same GPU model or VRAM class. Slurm
  may place the same submission on different device types across runs.
- Estimate `workload + execution configuration + device/runtime profile ->
  expected peak VRAM`. Device information is a first-class estimator input, not
  incidental metadata.
- Define a `DeviceProfile` with stable properties of the actually allocated
  device: vendor/model/class; architecture / compute capability; total VRAM;
  MIG profile where applicable.
- Keep dynamic device state out of the estimator model. Introduce or reuse a
  `DeviceObserver` for runtime facts: the GPU actually assigned to the current
  job, currently available/free VRAM, relevant device health/runtime state.
- Separation:

```text
VRAMEstimator    predicts expected memory for a workload on a device/runtime profile
DeviceObserver   reports the allocated device and its currently available memory
ResourcePlanner  compares required vs available and chooses an equivalent plan
```

- Do not train or key models by physical GPU identity such as `node01:gpu0`.
  Devices of the same relevant class share observations. Prefer a profile key
  of `runner + model revision + GPU class + VRAM class + runtime fingerprint`,
  simple enough that equivalent devices share data.
- Do not fully isolate device classes. Shared workload behavior is learned
  globally with device-specific corrections or residuals layered on top, so a
  new GPU class starts from a conservative global baseline:

```text
predicted_vram = shared_workload_model(features) + device_specific_correction(device_profile)
```

  This need not be a neural network; keep it lightweight and CPU-only.
- The actual device profile is determined **after Slurm allocation / runner
  startup**, not at submission time. The runner detects the assigned GPU and
  selects the appropriate resource profile before execution.
- Scope limits for this phase: one allocated GPU per persistent worker; do not
  pool multi-GPU VRAM; no heterogeneous-cluster placement optimization; the
  estimator does not choose Slurm GPU types or partitions. A future native
  multi-GPU runner is a separate device/execution profile, not an extension of
  single-GPU assumptions.
- The estimator remains passive during ordinary successful execution.
  Device-aware estimation improves OOM recovery and known-failure avoidance; it
  is not a second cluster scheduler.

## 28.5 Appended interface decisions (this revision)

These follow from §28.1–§28.4 and are binding:

- The runner side stays **stdlib-only**. No NumPy, no estimator copy, and no
  PyTorch/JAX measurement shim inside the runner image beyond the framework the
  runner already needs. Measurement uses the framework that already owns the
  GPU allocations; the runner publishes a normalized observation line.
- The estimator and planner live in `revocompute/resource_model.py` on the
  server, which computes `resource_guidance` from stored observations and
  embeds it in the immutable `task.json`. The runner enforces the guidance; it
  never re-derives it.
- Input role cardinality counts **files**. One FASTA file in the `sequence`
  role may carry many sequences, and each record is an independent work item.
  The runner normalizes records into work items and rejects duplicate or unsafe
  identifiers before any filesystem path is created.
- The server never imports a runner-tree module. The durable `work_items.json`
  name and format are part of the frozen interface, read on both sides.
- The rollout stage has exactly one owner: the runner's `resource_adaptation`
  declaration in its owning manifest.
