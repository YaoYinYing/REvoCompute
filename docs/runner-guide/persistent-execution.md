# Persistent Execution

A Runner family executes one Task as one or more **work items**. This page
describes that execution model: the lifecycle the Runner drives, the durable
state a restarted worker resumes from, and the one way a Runner may change *how*
a requested computation runs without changing *what* was requested. The
Example Runner (`docker/runners/example/`) is the minimal working reference.

A single-input Task still uses this path when its one input carries many work
items — one FASTA file with many records is the common case. A family that
executes one indivisible item keeps the standard entrypoint in
[Adding a Runner](adding-a-runner.md) and can ignore this page.

## Files and work items

Input-role cardinality in the owning `task.yaml` counts **files**, not
sequences. One FASTA in the `sequence` role may carry many records, and every
record is an independent work item: the Runner normalizes records into work
items, rejects duplicate or unsafe identifiers before any filesystem path is
created, and keeps the original input order in the durable manifest.

A work item is the unit of execution, of durability, and of failure. The shared
lifecycle lives in `docker/runners/common/persistent_runner.py` and the FASTA
normalization helpers in `docker/runners/common/work_items.py`; both are copied
into a participating image. A family supplies the science through a plugin:

```text
initialize_runtime()                 # once per task: model, weights, context, indexes
run_item(item, plan, work_dir)       # one work item, into a private directory
finalize()                           # release the runtime
```

`initialize_runtime` runs once per task. The runtime is not reloaded between
successfully processed items; an item that requires a runtime restart is the
exception, described under *Bounded recovery* below. A family entrypoint is a
thin adapter: read `task.json`, build the work items and the execution config,
call `execute_task`.

## Work-item state and task outcome

Each work item carries one state in `work_items.json`:

```text
PENDING  RUNNING  SUCCEEDED  FAILED_INPUT  FAILED_RESOURCE  FAILED_RUNTIME  CANCELLED
```

The task outcome is derived from those states and is published as
`REVODESIGN_TASK_OUTCOME:<outcome>` and in the results manifest; `tasks.status`
is unchanged.

| Item states | Task outcome |
| --- | --- |
| all `SUCCEEDED` | `SUCCESS` |
| some `SUCCEEDED`, some failed | `PARTIAL_SUCCESS` |
| none `SUCCEEDED`, all failed | `FAILED` |
| work unfinished, or `CANCELLED` items | `CANCELLED_PARTIAL` |

A failing work item fails only itself. The Runner records the failure, keeps the
queue moving, and commits every item that succeeded, so a Task with one bad
record still delivers the rest. A family classifies a failure by raising
`WorkItemError` with a failed state or by returning a non-success outcome from
`run_item`; either way an irreducible item ends as `FAILED_RESOURCE` after its
bounded retry budget is spent.

Partial results become available as each item commits: a completed item's
artifacts can be read and downloaded while the rest of the task is still
running or pending.

## Durable state and resume

```text
outputs/work_items.json   authoritative item state; written atomically
outputs/<item>/           committed item artifacts
outputs/.tmp/<item>/      in flight; never a valid result
```

`work_items.json` is written atomically and is the authority, not process
memory, so a restarted worker resumes from it: committed items are skipped and
their artifacts are never recomputed, unfinished items run again, and item order
in the file stays the original input order. Committed items survive a Runner
crash, a CUDA-context restart, a node interruption, and a Slurm requeue.

An item's artifacts are written to `.tmp/<item>/` and renamed into `<item>/`
only after the family's `validate_item` accepts them. A final directory
therefore always means "this item completed and its artifacts passed
validation"; a killed run leaves staging behind, never a published partial
result.

## Execution queue

`ExecutionQueue` sits between the normalized work items and the runtime. It
first owns a stable execution order and honors resource limits already learned
for the runner/device profile; it is deliberately not a tensor batcher.
Persistent serial execution — load the runtime once, process items continuously
— is the optimization target.

For sequence workloads the queue orders by decreasing length: the longest item
runs early, so a long-tail OOM surfaces while the queue still has room to adapt.
Membership in a length bucket is a ratio of the previous boundary, and items of
comparable length stay adjacent. Execution order never changes what the user
sees: metadata and result presentation keep the original input order.

## Resource adaptation boundaries

A fallback plan may change only execution-only settings:

```text
sample_group_size  batch_size  token_budget  chunk_size
cpu_offload  kernel_backend  cache_clear
```

Nothing scientifically meaningful may change. The requested sample count,
recycles, model and version, user-selected seeds, precision where it changes
the requested behavior, MSA/template usage, and input content are outside the
vocabulary by construction: `FallbackPlan` rejects any adjustment outside that
set when the manifest loads, so a Runner cannot declare — and the planner cannot
pick — an adaptation that alters the requested computation. A bounded retry that
splits five requested samples into `2 + 2 + 1` still returns five samples, with
the same seed identities and the effective seed recorded per artifact.

## Responsibilities and frozen interfaces

Three responsibilities stay separate, with one implementation each:

| Component | Owner | Where it runs |
| --- | --- | --- |
| `VRAMEstimator` | `revocompute/resource_model.py` | server worker |
| `DeviceObserver` facts | the runner | runner, after Slurm allocation |
| `ResourcePlanner` | `revocompute/resource_model.py` | server; the runner enforces its decision |

The server owns the learned model and the `resource_observations` knowledge
base, and embeds a `resource_guidance` block (`plan_order`,
`known_failing_plans`, `avoid_scale_at_or_above`) in the immutable `task.json`.
The runner measures, reports the `DeviceObserver` facts the server cannot
obtain — the GPU actually assigned, its free memory — and enforces the guidance
bounded by the plans its own manifest declares. The runner never imports the
estimator and never invents an adjustment, which keeps every runner image
standard library only.

Fallback policy is runner-owned, declared as `resource_adaptation` in the owning
`task.yaml` and projected into `task.json`:

```yaml
resource_adaptation:
  stage: observe
  fallback_plans:
  - label: split
    title: One sample group at a time
    adjustments: {sample_group_size: 1}
```

Server core contains no `if runner == ...` branch. The estimator may say a
configuration is unsafe; it may not say what to do about it.

## Rollout stages

```text
observe   collect observations only; a successful execution is never modified
recover   consult the planner only after a real OOM
avoid     additionally skip a configuration already established as unsafe
          for the same workload/device/runtime profile
```

The owning `task.yaml` declares the stage, and `observe` is the deployment
default. In `observe` the default path is the only path: attempt 0 uses the
upstream parameters unchanged, and an OOM is recorded rather than retried into
a fallback. `recover` walks the declared plans in order within a finite budget;
`avoid` may start an attempt at a declared plan when the server has applicable
evidence that the default is a known failure for this profile. With too little
evidence the runner falls back to plain bounded recovery rather than trusting an
extrapolated prediction.

## Progress, observations, outcome on stdout

A persistent runner publishes three additive channels; unknown lines are
ignored by the server.

```text
REVODESIGN_PROGRESS:{"total_items","completed_items","failed_items","pending_items","current_item","current_attempt"}
REVODESIGN_OBSERVATION:{<normalized ResourceObservation>}
REVODESIGN_TASK_OUTCOME:SUCCESS|PARTIAL_SUCCESS|FAILED|CANCELLED_PARTIAL
```

Progress is emitted after each item, so stdout is not the only progress channel.
The observation line carries one normalized record per attempt: `runner`,
`runner_version`, `model_revision`, `runtime_fingerprint`, `device` (vendor,
model, compute capability, total VRAM, MIG profile), `features` (sequence
length, sequence count, batch size, sample count, parameters), `baseline_mb`,
`peak_allocated_mb`, `peak_reserved_mb`, `peak_process_mb`, `available_mb`,
`outcome`, `error_class`, `runtime_seconds`, `plan_label`, `work_item`,
`attempt`, and `quality`. Measurement happens inside the runner, using the
framework that owns the GPU allocations; the server installs no ML framework to
collect it. A successful run whose peak exceeds the device's free memory is
reported as `interference` and excluded from training, so another process's
memory is never learned as this workload's demand.

## Bounded recovery

Recovery is finite: the default path, then each declared plan in order, then
`FAILED_RESOURCE` for that item. There is no unbounded retry loop, and every
attempt is recorded with its plan label and observed peaks. When the CUDA
context itself is unhealthy the runner takes the last-resort path — checkpoint
state, rebuild the runtime, resume the unfinished items — bounded by
`max_runtime_restarts`. Already committed items are not recomputed.
