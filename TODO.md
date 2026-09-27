# TODO — PR #30 Stabilization

Target PR: **#30 — Persistent multi-input Runner execution and adaptive OOM recovery**

Current reviewed head: `f42ccf4636`

The objective of this pass is **correctness and closure**, not further architectural expansion.

Do not redesign the existing `PersistentRunner` merely for elegance. Preserve working multi-input execution, atomic item commits, resume behavior, partial success, ESMFold 2 / SimpleFold migrations, and the current Runner Protocol unless a correctness issue requires a change.

Do not introduce Triton, Ray, JAX, PyTorch, TensorFlow, a second scheduler, cross-task warm workers, or true heterogeneous tensor batching.

---

# 1. Resolve the Current PR Review Blockers

## 1.1 All-failed tasks must exit non-zero

Address the existing P1 finding in `docker/runners/common/persistent_runner.py`.

Current problem:

```text
all work items fail
→ derive_outcome() == FAILED
→ runner returns normally
→ process exit code 0
→ SlurmJob reports COMPLETED
→ tasks.status may become finished
```

Required behavior:

```text
all items failed
→ preserve work_items.json
→ preserve per-item failure information
→ emit REVODESIGN_TASK_OUTCOME:FAILED
→ runner process exits non-zero
→ server task status becomes failed
```

A `PARTIAL_SUCCESS` task must continue to exit successfully.

Add regression tests proving that:

```text
1 success + 1 failure → process success / PARTIAL_SUCCESS
0 success + N failures → process failure / FAILED
```

Ensure result finalization does not discard the durable per-item manifest merely because the runner exits non-zero.

---

## 1.2 Make every declared fallback reachable

Address the existing P1 finding for ESMFold 2.

`max_item_attempts` includes the default execution attempt.

Therefore:

```text
N fallback plans
require at least
1 + N attempts
```

Do not allow a manifest to declare fallback plans that its attempt budget can never reach.

Preferred behavior:

- derive the default attempt budget automatically from the number of declared fallback plans; or
- reject invalid manifests during task-type discovery when an explicit budget is smaller than `1 + fallback_count`.

Do not silently truncate the fallback ladder.

Add generic protocol tests for this invariant.

---

## 1.3 Preserve successful peak-memory measurements

Address the existing P1 finding in `persistent_runner.py`.

The framework-provided peak values returned by `run_item()` must survive through `_execute()` / `attempt_item()` into the emitted `ResourceObservation`.

Do not replace a completed attempt's peak measurement with a later call to `runtime_usage()` after the inference tensors or peak counters have already changed.

For both success and OOM paths, an observation must describe the resource behavior of **that execution attempt**, not the allocator state after it.

Add a regression test where:

```text
run_item peak = high
post-run current memory = low
```

and verify that the stored observation retains the high peak.

---

## 1.4 Scope proactive avoidance by the actual resource profile

Address the existing P2 finding.

Never aggregate OOM evidence from all devices/runtime profiles in one runner family into one `avoid_scale_at_or_above`.

The following must not contaminate each other:

```text
SimpleFold / L20 48 GB
SimpleFold / A100 40 GB
SimpleFold / A100 80 GB

different model revisions
different runtime fingerprints
different materially relevant backends
```

At minimum, learned avoidance evidence must be scoped by:

```text
runner
model revision
runtime fingerprint
GPU class
VRAM class
```

Physical GPU identity such as `node01:gpu0` must not be part of the profile.

Because the actual GPU is only known **after Slurm allocation**, do not pretend that the server can select one concrete device-specific profile at submission time.

Prefer a profile-indexed guidance representation that the runner can select from after detecting the actual allocated device.

Unknown profiles must fall back to:

```text
default execution
+
reactive bounded recovery
```

rather than borrowing an unrelated device's unsafe threshold.

---

# 2. Resolve Rollout-Stage Semantics

There is currently a semantic inconsistency:

`ResourcePlanner` treats `observe` as no recovery after OOM, while `PersistentRunner` currently allows reactive fallback after OOM even when the declared stage is `observe`.

Choose one model and enforce it everywhere.

Use:

```text
OBSERVE
    collect observations only
    never change execution

RECOVER
    default execution remains untouched
    after a real OOM, use bounded runner-declared fallback plans

AVOID
    all RECOVER behavior
    plus proactive skipping of configurations that are already known unsafe
```

This matches the intended deployment model:

```text
successful default run
→ never modified

actual OOM
→ automatic recovery in RECOVER/AVOID

well-established known OOM region
→ proactive adaptation only in AVOID
```

Update:

- `ResourcePlanner`
- `PlanSequence`
- `guidance_for`
- runner tests
- server tests
- protocol documentation
- `IMPLEMENTATION_STATE.md`

The mode must have one clear owner.

For the current feature, ESMFold 2 and SimpleFold should use `recover` if automatic OOM recovery is intended to be active by default.

Do not hide recovery behavior behind an `observe` label.

---

# 3. Fix the Fallback Ladders

Fallbacks must progress toward **lower peak-memory pressure**.

The current ordering is not consistently monotonic.

For sample multiplicity, prefer:

```text
default
→ moderate grouping reduction
→ one sample at a time
→ stronger backend/offload fallback
```

rather than:

```text
default
→ one sample
→ two samples
```

because increasing concurrency after the one-sample plan fails cannot normally improve memory usage.

## SimpleFold

For multi-sample requests, prefer:

```text
default multiplicity
→ sample_group_size = 2
→ sample_group_size = 1
```

Skip plans that are a no-op for the current item.

Example:

```text
requested num_samples = 1

sample_group_size = 2
sample_group_size = 1
```

must not consume pointless retries if both resolve to the same effective execution as the default.

## ESMFold 2

Make the fallback sequence monotonic.

A reasonable sequence is conceptually:

```text
default
→ samples_two_at_a_time
→ samples_one_at_a_time
→ samples_one_at_a_time + reference kernels
```

Do not make the final `reference_kernels` plan accidentally restore the original high sample concurrency unless that behavior is explicitly justified.

Fallback plans are independent mappings, not cumulative deltas, so combined low-memory states must be declared explicitly.

Add tests over `num_diffusion_samples = 1, 2, 4, 8`.

---

# 4. Make Resource Observations Describe the Effective Execution

The estimator currently receives the requested `sample_count`, while sample-group fallbacks may execute only a subset concurrently.

That makes different memory plans appear identical to the estimator.

Example:

```text
requested samples = 8

default:
concurrent samples = 8

fallback:
2 + 2 + 2 + 2
```

The workload observation must distinguish those executions.

Separate:

```text
requested scientific workload
```

from:

```text
effective concurrent execution shape
```

For resource estimation, record at least:

```text
sequence_length
sequence_count
effective batch size
effective concurrent sample/group size
chunk/token settings when applicable
offload mode when applicable
kernel/backend mode when materially relevant
```

Preserve the original requested sample count separately for provenance.

Do not teach the estimator that an 8-sample request executed as `2+2+2+2` has the same instantaneous memory shape as eight simultaneous samples.

Update the feature schema and tests accordingly.

---

# 5. Do Not Let the Estimator Reject a Fallback Using the Default Plan's Features

`ResourcePlanner.decide()` currently predicts memory from one `WorkloadFeatures` object and then evaluates a fallback plan without necessarily projecting that fallback's adjustments into the prediction features.

That is unsafe.

A lower-memory fallback must be evaluated using its **effective execution features**.

Do not do:

```text
predict(default execution)
→ predicted too large
→ reject lower-memory fallback
```

Instead:

```text
candidate fallback
→ derive effective execution features
→ estimate candidate resource demand
→ compare candidate estimate with available VRAM
```

If the server cannot reliably evaluate a runner-owned adjustment, it must not invent semantics for it.

For this PR, correctness is more important than forcing numerical prediction into every decision.

A safe implementation may use deterministic runner-owned fallback ordering for reactive recovery and reserve estimator-driven candidate ranking for execution features that have a well-defined generic projection.

---

# 6. Decide What the Numerical Estimator Actually Does in Production

At the reviewed head, `VRAMEstimator` and `ResourcePlanner` have substantial implementation and tests, but the production submission path currently builds `resource_guidance` through `guidance_for(...)`.

I did not find a production path that calls `VRAMEstimator.predict()` / `ResourcePlanner.decide()` to select the actual runner plan.

Do not leave an ambiguous half-connected architecture.

Choose and document one of these outcomes for this PR:

## Preferred minimal closure

Use the persisted resource history for:

```text
reactive bounded recovery
+
profile-scoped known-failure avoidance
```

and treat the numerical estimator as a resource-analysis component until candidate-plan feature projection is sound.

Do not claim in the PR description that numerical predictions actively choose execution plans if they do not.

OR, if numerical planning is kept active in this PR:

- project every candidate plan into effective resource features;
- scope it to the actual allocated device/runtime profile;
- prove the production call path with integration tests.

Do not add a bidirectional live model-serving protocol between the server and Slurm runner merely to satisfy this item.

---

# 7. Fix Observation Quality / Interference Detection

Review the current runner-side classification:

```text
peak_process_mb > available_mb * 1.05
→ interference
```

This compares different quantities and can classify a legitimate run as interference.

After model initialization:

```text
baseline process memory
```

is already resident, while:

```text
available VRAM
```

usually excludes that baseline.

Therefore a valid task may have:

```text
peak_process > free_at_start
```

while its **incremental** workload memory still fits entirely in the free space.

Prefer recording raw facts:

```text
total VRAM
baseline process/runtime VRAM
free VRAM before item
peak process/reserved/allocated VRAM
```

and deriving observation quality server-side.

If interference detection remains automatic, base it on a defensible estimate such as external occupancy at baseline rather than comparing total process peak with free memory.

Do not exclude legitimate high-memory successful observations from training.

Add a regression test resembling:

```text
total        = 40 GB
baseline     = 10 GB
free         = 30 GB
peak process = 35 GB
incremental  = 25 GB
```

This is not interference merely because `35 > 30`.

---

# 8. Preserve Scientific Seed Semantics Across Resource Adaptation

Revisit the current grouping strategy that re-seeds groups with values such as:

```text
item_seed + group_index
```

Resource adaptation must not silently redefine the requested stochastic experiment.

The invariant should be:

```text
the logical sample identities and effective seeds are stable
regardless of whether samples are executed together or split into groups
```

Either:

1. define deterministic per-sample seeds before execution and use the same seeds under default and fallback grouping; or
2. preserve the upstream RNG stream exactly while splitting execution.

Do not merely record changed seeds after adaptation and call the computation equivalent.

Add a deterministic test comparing the sample identity/seed mapping under:

```text
N samples together
```

and:

```text
the same N samples split into smaller execution groups
```

The execution grouping may change; the requested sample identities must not.

---

# 9. Persistence Across Server / Container Restart

The durable source of truth should remain the observation database.

Current resource observations already survive process/container restart when the task database volume survives.

Do not require a separate heavyweight model-state service.

The expected behavior is:

```text
restart
→ load persisted observations
→ rebuild lightweight estimator/profile state
→ continue learning
```

`VRAMEstimator.save/load()` may remain useful for tests or caching, but production correctness must not depend on an estimator JSON file living inside the container filesystem.

If a derived estimator cache is introduced:

- store it outside the container writable layer;
- version it by model/schema/runtime compatibility;
- treat it as disposable;
- rebuild it from raw observations if absent or incompatible.

Add a restart/rebuild test proving that known safe/failure knowledge survives a new estimator/server instance.

---

# 10. Heterogeneous-Cluster Retention

Resource history retention should not allow one common GPU class to evict all observations for a rarer class.

Review retention currently scoped primarily by runner/model.

Prefer retention that preserves useful evidence by resource profile, or use a stratified cap.

At minimum ensure that:

```text
many L20 observations
```

do not erase all useful:

```text
A100 / H100
```

history for the same runner/model.

Keep retention bounded.

---

# 11. CI: Close the Current Full-Stack Failure

Current head status:

```text
REvoCompute Documentation     PASS
BrowserContracts              PASS
RunnerScientificAcceptance    PASS
REvoComputeTests              PASS
ServerComposeFullStack        FAIL
```

The failing full-stack job currently reaches:

```text
AssertionError:
infrastructure readiness == UNAVAILABLE
reason:
No compute worker responded.
```

First rerun after the branch fixes.

If reproducible, determine whether this is:

- an actual worker startup regression;
- a startup/readiness race;
- a fixed timeout that is now too short.

Do not weaken readiness assertions merely to make CI green.

If it is a startup race, use bounded polling for the worker to become ready rather than a one-shot readiness assertion.

All required CI must be green before merge.

---

# 12. Repeat Live Acceptance After the Fixes

Repeat real Slurm/Apptainer acceptance for:

```text
example
simplefold
esmfold2
```

On at least one real GPU.

In addition to current smoke tests, explicitly exercise:

## Multi-input success

```text
several FASTA records
→ one runtime load
→ independent committed outputs
→ SUCCESS
```

## Partial input failure

```text
one invalid record
→ FAILED_INPUT for that item
→ remaining items continue
→ PARTIAL_SUCCESS
```

## All-item failure

```text
all items fail
→ work_items.json preserved
→ runner exits non-zero
→ server task status failed
→ outcome FAILED
```

## Injected OOM recovery

Use a deterministic test hook if a real OOM is undesirable:

```text
default attempt
→ OOM
→ correct lower-memory fallback
→ success
```

Verify the observation records the actual successful peak.

## Irreducible OOM

```text
all valid fallback plans exhausted
→ FAILED_RESOURCE for item
→ remaining items continue
```

---

# 13. Update PR Documentation to Match Reality

After implementation stabilizes, update:

```text
PR body
TODO.md
IMPLEMENTATION_STATE.md
persistent-execution.md
runner protocol docs
```

Remove claims that are not true in the production call path.

Document:

- exact rollout-stage semantics;
- effective resource-feature semantics;
- device-profile scoping;
- restart/rebuild behavior;
- whether numerical estimator prediction is active or observational;
- monotonic runner-owned fallback behavior;
- all-failed task exit semantics.

Do not keep “architecture freeze” statements that contradict the code after these fixes.

---

# 14. Keep These Out of PR #30

Do not expand the current PR into:

```text
true heterogeneous tensor batching
dynamic throughput optimization for every successful item
cross-task warm model workers
GPU placement selection for Slurm
multi-GPU VRAM pooling
new inference-server infrastructure
large ML dependencies
```

Persistent serial execution remains the primary execution model.

The system may learn resource behavior without trying to optimize every normal run.

---

# 15. Immediate Follow-Up PR: Admin Visibility

After PR #30 is stable, add Admin visibility in a separate UI-focused PR.

Place deployment policy under:

```text
Admin
→ Configuration
→ Resources
→ Adaptive Resource Management
```

The first version should expose policy, not estimator internals.

Useful controls/status:

```text
mode: Disabled / Observe / Recover / Avoid
observation count
known resource profiles
last observation/update
resource adaptation enabled/disabled
```

Do not expose regression coefficients, neural-network weights, or training internals.

Also expose runner capabilities on Runner Detail:

```text
Multi-input
Persistent runtime
Resume
Partial results
OOM recovery
Adaptive resource support
```

Task Detail should expose adaptation history when an intervention occurred.

A larger Resource Intelligence dashboard can wait until enough production observations exist.

---

# Merge Gate

I will not squash-merge PR #30 until:

- all current Codex review threads are addressed or explicitly rejected with evidence;
- all-item failure correctly propagates to task failure;
- fallback attempt budgets cannot make declared plans unreachable;
- successful peak-memory observations are correct;
- profile-specific avoidance cannot leak across GPUs/runtime fingerprints;
- rollout-stage semantics are consistent;
- fallback ladders are monotonic and no-op plans are skipped;
- effective execution features distinguish resource adaptations;
- observation quality does not discard legitimate successful runs;
- seed/sample identity remains stable under grouping adaptation;
- all required CI is green;
- live acceptance is repeated after the final fixes;
- PR documentation matches the actual production behavior.