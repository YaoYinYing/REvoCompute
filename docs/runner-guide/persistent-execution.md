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
items, rejects duplicate or unsafe identifiers before any work-item path is
created, and keeps the original input order in the durable manifest.

A work item is the unit of execution, of durability, and of failure. The shared
lifecycle lives in `docker/runners/common/runtime/persistent_runner.py` and the FASTA
normalization helpers in `docker/runners/common/runtime/work_items.py`; both reach a
participating container through its `runtime.runtime_overlay` declaration — an
immutable, content-addressed [Runtime Bundle](runtime-bundles.md) mounted
read-only at `/opt/revocompute/runtime`, not baked into the image. A family
supplies the science through a plugin:

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
`REVODESIGN_TASK_OUTCOME:<outcome>` and in the results manifest. The
`tasks.status` vocabulary is unchanged — no new status is introduced — but the
derived outcome does reach it through the process status:

| Item states | Task outcome | Runner exit | `tasks.status` |
| --- | --- | --- | --- |
| all `SUCCEEDED` | `SUCCESS` | 0 | `finished` |
| some `SUCCEEDED`, some failed | `PARTIAL_SUCCESS` | 0 | `finished` |
| none `SUCCEEDED`, all failed | `FAILED` | non-zero | `failed` |
| work unfinished, or `CANCELLED` items | `CANCELLED_PARTIAL` | non-zero | `failed` |

A task with no successful work item is a failed task, so the family entrypoint
exits non-zero for it (`persistent_runner.exit_code_for`): the wrapper's exit
code is what the server turns into `tasks.status`, and returning 0 there would
publish a failed experiment as `finished` for every consumer that reads only the
status. `PARTIAL_SUCCESS` is a real result and exits 0; the derived outcome is
what distinguishes it.

A failing work item fails only itself. The Runner records the failure, keeps the
queue moving, and commits every item that succeeded, so a Task with one bad
record still delivers the rest.

Only an explicitly classified memory shortage consumes the fallback ladder. A
family reports it either by raising `WorkItemError` with `FAILED_RESOURCE` or by
returning the `OUTCOME_OOM` outcome from `run_item`; that item then records the
peak it reached and retries through the declared plans within its bounded
budget. Two other failures do not: an unrecoverable CUDA-context fault (an
illegal memory access, a lost context) fails the item as `FAILED_RUNTIME` and
rebuilds the runtime within `max_runtime_restarts`, and any other unexpected
exception — an output-validation failure, a malformed artifact, a write error, a
model bug — fails the item as `FAILED_RUNTIME` immediately. Neither may spend a
fallback plan: the ladder lowers instantaneous memory, so it cannot fix a
failure that is not about memory, and retrying a smaller plan merely repeats the
same error at a different shape.

A record that violates a *transport* rule — no residues, data before the first
header, a duplicate identifier that would collide on one output directory — is
still a task-level rejection: nothing can be scheduled from a FASTA the framing
layer cannot read consistently. A record that violates the *family's* scientific
envelope — an unsupported residue symbol, a length beyond what the model
supports — is not: the family describes it per item (`record_problem`) and fails
that item alone.

Partial results become available as each item commits, but only through the
result directory itself. The results API is served from the manifest published
at finalization, and `GET /compute/api/results/<id>` redirects to the running
endpoint until the task reaches `finished`/`failed`, so a partially completed
item is not yet downloadable over HTTP. Live per-item progress — counts and the
current item — is available while running.

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

`ExecutionQueue` sits between the normalized work items and the runtime. It owns
a stable execution order — deliberately not a tensor batcher. Persistent serial
execution — load the runtime once, process items continuously — is the
optimization target.

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

The adaptation vocabulary changes only *how* a request is executed, never a
requested scientific parameter: the requested sample count, recycles, model and
version, user-selected seeds, precision where it changes the requested behavior,
MSA/template usage, and input content are outside the vocabulary by construction.
`FallbackPlan` rejects any adjustment outside that set when the manifest loads, so
a Runner cannot declare — and the planner cannot pick — an adaptation that adds a
requested parameter the user did not set. A bounded retry that splits five
requested samples into `2 + 2 + 1` still returns five samples, with the same
per-sample seed identities recorded per artifact: sample `j` always carries
`item_seed + j`, and each execution group is seeded from its first sample. That
keeps the split inspectable and reproducible, but it is **not** a claim of
equivalence: the samples inside one group share that group's stochastic stream,
so a split run's coordinates differ from the single-draw baseline's. Every plan is
therefore classified by its scientific impact before it is offered:

```text
resource_only        changes only how the requested computation is executed
numerical_backend    may change floating behavior (a kernel-backend switch)
scientific_output    changes the result itself (a different stochastic stream
                     per sample, or a different requested computation)
unsafe               names a scientific parameter; never taken automatically
```

`sample_group_size` is `scientific_output`, **not** `resource_only`: the samples
inside one group share that group's stochastic stream, so the same requested
samples come out with *different coordinates* under a different grouping — the
split keeps the requested sample count and the seed declaration, but it is a
change to the scientific result and is reported as one, never as a neutral
resource knob. `cache_clear`, `batch_size`, `chunk_size`, `token_budget`, and
`cpu_offload` are `resource_only`; `kernel_backend` is `numerical_backend`; and a
plan naming anything else is `unsafe` — the server rejects such a declaration and
the runner additionally refuses it at the boundary (dropping it before the ladder
is walked and recording it in the task summary), so a malformed or injected plan
can never mutate the scientific execution.

A declared ladder must be monotone in *instantaneous* pressure: each plan draws
the same requested samples under strictly lower concurrency, so the last rung
never restores the multiplicity that failed. A plan whose effective execution
equals the default's, or an earlier plan's, is a no-op for that work item — with
one requested sample, "two at a time" and "one at a time" are the same draw. The
runner drops such plans before the ladder is walked, so a no-op consumes no
attempt. Whether a plan is a no-op is the family's own knowledge: it reports a
canonical key for the execution a plan realizes (`effective_plan_key`), and the
lifecycle compares keys rather than guessing from the adjustment names.

## Responsibilities and frozen interfaces

Three responsibilities stay separate, with one implementation each:

| Component | Owner | Where it runs |
| --- | --- | --- |
| `VRAMEstimator` | `revocompute/resource_model.py` | server worker |
| device observation | the runner | runner, after Slurm allocation |
| guidance projection | `revocompute/resource_model.py` | server; the runner enforces it |

The server owns the observation knowledge base and embeds a `resource_guidance`
block (`plan_order`, and — only in `avoid` — a `profiles` list) in the immutable
`task.json`. The runner measures and reports the device facts the server cannot
obtain on its own — the GPU actually assigned, its free memory — and enforces
the guidance bounded by the plans its own manifest declares. The runner never
imports the estimator and never invents an adjustment, which keeps every runner
image standard library only.

`VRAMEstimator` and `ResourcePlanner` are tested resource-analysis components,
but they do not select execution plans in production: guidance is observational,
derived from persisted rows by `guidance_for`. A numerical prediction is a
research tool until a candidate plan can be projected into the effective
resource features it would actually execute.

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
observe   collect observations only, never change execution — no proactive
          skip and no reactive fallback after a real OOM
recover   leave the default path untouched; after a real OOM, use bounded
          runner-declared fallback plans
avoid     all recover behaviour, plus proactive skipping of a configuration
          already established as unsafe for the same profile
```

The owning `task.yaml` declares the stage, and `observe` is the deployment
default. In `observe` the default path is the only path: attempt 0 uses the
upstream parameters unchanged, and an OOM fails that item with no retry into a
fallback — recovery is itself an execution change, so it belongs to `recover`.
`recover` leaves the default path untouched and walks the declared plans in
order within a finite budget after a real OOM; `avoid` additionally starts an
attempt at a declared plan when the profile's evidence says the default is a
known failure at this item's scale. With too little evidence the runner falls
back to plain bounded recovery rather than borrowing another profile's threshold.

Avoidance is a positive claim that a configuration *will* fail, so the evidence
behind it is scoped to the profile that produced it: a `profiles` entry is
published only from rows matching the same runner, model revision, and runtime
fingerprint, and each entry carries that identity. Stored rows span every
revision, runtime, and device a family has run on, so an OOM under a larger
model, a different runtime, or a smaller GPU cannot establish a threshold for an
unrelated one. Every qualified scope is published — a family that has learned
boundaries for both `fast` and `standard` sends both — and the runner selects
among them after allocation, so no profile is chosen by insertion order.

The concrete GPU is unknown at submission time, so a device-specific threshold
cannot be chosen then. The server therefore publishes one entry per exact
`(model revision, runtime fingerprint, device model, total VRAM)`:

```json
{"runner": "esmfold2", "model_revision": "...", "runtime_fingerprint": "...",
 "device_model": "A100-PCIE-40GB", "total_vram_mb": 40960,
 "known_failing_plans": ["split"], "avoid_scale_at_or_above": 900}
```

The runner binds the entry matching its own model revision, runtime fingerprint,
and the device it was actually allocated, after the runtime has loaded and the
fingerprint is answerable. No entry matching all four means the default path plus
plain bounded recovery — an unknown device, a changed runtime, or a different
model revision never borrows another profile's threshold. Guidance is
observational: the server's numerical estimator does not choose execution plans.

The retry budget is a floor, not a cap: the default path plus each declared
plan is always reachable, however small `max_item_attempts` is, so a declared
fallback can never be stranded by a manifest's own budget.

## Recovery provenance

An item's `work_items.json` entry carries two bounded evidence accumulators
beside its state. `resource_events` is the normalized observation per attempt,
which the server's estimator ingests. `recovery` is one record per attempt naming
the plan and the *scientific-impact class* of the recovery action, the
resource-only settings the attempt applied, and the *effective scientific
parameter set* it executed — so requested-versus-effective is reconstructible per
item and attempt without reading scheduler logs.

Every automatic recovery action carries exactly one class:

```text
resource_only        changes only how the computation runs, not the result
numerical_backend    may change floating behavior (a kernel-backend switch)
scientific_output    changes the result itself (a different stochastic stream
                     per sample, or a different requested computation)
unsafe               names a scientific parameter; never taken automatically
```

The class comes from one shared vocabulary of execution-only adjustment keys, and
the most impactful key in a plan decides the whole action: `cache_clear`,
`batch_size`, `chunk_size`, `token_budget`, and `cpu_offload` are `resource_only`;
`sample_group_size` is `scientific_output` (the samples inside a group share that
group's stochastic stream, so the requested samples come out with different
coordinates); `kernel_backend` is `numerical_backend`; and any key outside that set
— a sample count, a seed, a model — is `unsafe`. The server republishes each
item's per-attempt records and its aggregated `recovery_action` in the results
manifest, so a reviewer sees whether the requested science survived recovery from
the scientific result surface itself, not from logs.

For ESMFold 2 and SimpleFold, the grouping rungs (`samples_two_at_a_time`,
`samples_one_at_a_time`) are reported as `scientific_output`, and ESMFold 2's
`reference_kernels` rung — which changes both the grouping and the backend — is
reported as `scientific_output` too, since the grouping change dominates. The
requested sample count and the per-sample seed declaration are untouched by every
rung, and the effective set records the grouping and stream seeds the attempt
actually ran, so a split run never reads as equivalent to the baseline. A family
that lets a plan set `kernel_backend` — the one parameter that is both
user-selected and a resource key — also records the executed value in the
effective set, so that divergence is visible rather than hidden.

The **Mock GPU Example Runner** (`docker/runners/mock_gpu_example/`) is the
CPU-only reference for this whole page. It drives the real lifecycle against a
configurable pseudo-device and a deterministic pseudo-model, so every section
above — per-item identity, resume, bounded recovery, recovery classification,
unsafe-plan refusal, and the server projection — can be exercised without a GPU,
model, weights, or production SIF. It is a test/reference artifact and makes no
scientific claim about any real model.

## Progress, observations, outcome on stdout

A persistent runner publishes three additive channels; unknown lines are
ignored by the server.

```text
REVODESIGN_PROGRESS:{"total_items","completed_items","failed_items","pending_items","current_item","current_attempt"}
REVODESIGN_OBSERVATION:{<normalized resource observation>}
REVODESIGN_TASK_OUTCOME:SUCCESS|PARTIAL_SUCCESS|FAILED|CANCELLED_PARTIAL
```

Progress is emitted after each item, so stdout is not the only progress channel.
The observation line carries one normalized record per attempt: `runner`,
`runner_version`, `model_revision`, `runtime_fingerprint`, `device` (vendor,
model, compute capability, total VRAM, MIG profile), `features` (sequence
length, sequence count, batch size, requested `sample_count`, effective
`concurrent_samples`, and any material execution-only `parameters`), plus
`baseline_mb`, `peak_allocated_mb`, `peak_reserved_mb`, `peak_process_mb`,
`available_mb`, `outcome`, `error_class`, `runtime_seconds`, `plan_label`,
`work_item`, and `attempt`. `sample_count` is the requested scientific
multiplicity — provenance — while `concurrent_samples` is how many samples this
attempt actually ran simultaneously, so an 8-sample request executed as
`2+2+2+2` is not recorded as having eight samples' instantaneous shape. The
three peak fields come from the framework's high-water counters at the moment
the item finished — never from the allocator's residency afterwards, which
would report every successful item as having grown by nothing. Measurement
happens inside the runner, using the framework that owns the GPU allocations;
the server installs no ML framework to collect it. The runner reports raw
facts; the server derives observation quality and stores the rows, projecting
them into its own estimator and sending the runner only the resulting
`resource_guidance`, never the raw history. A successful run whose *incremental*
growth exceeds the device's free memory at start is derived as `interference`
and excluded from training, so another process's memory is never learned as this
workload's demand — while a legitimate run whose total peak exceeds the free
memory but whose growth fits it stays valid.

## Bounded recovery

Recovery is finite: the default path, then each declared plan in order, then
`FAILED_RESOURCE` for that item. There is no unbounded retry loop, and every
attempt is recorded with its plan label and observed peaks. Only a classified
OOM walks that ladder (see *Work-item state and task outcome*); a generic
exception fails its item `FAILED_RUNTIME` without consuming a plan. When the
CUDA context itself is unhealthy the runner takes the last-resort path — fail
the item whose allocation was lost, rebuild the runtime, and continue with the
remaining items — bounded by `max_runtime_restarts`. A runtime that cannot be
rebuilt leaves the remaining items on the exhausted context rather than aborting
a task whose other items may still succeed. Already committed items are not
recomputed.
