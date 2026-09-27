# TODO — PR #30 Final Stabilization Before Squash Merge

Target PR: **#30 — Persistent multi-input Runner execution and adaptive OOM recovery**

Current reviewed head: `e5651f1`

## Goal

Finish PR #30 without redesigning the implementation.

The persistent multi-input execution model, resource observations, recovery ladders, heterogeneous-device handling, restart persistence, and live GPU acceptance are already substantially complete.

This pass should address only the remaining correctness gaps:

1. generic runtime/validation errors must not enter the OOM recovery path;
2. proactive `avoid` guidance must preserve model/runtime identity through runner binding;
3. regression tests must cover both cases;
4. all CI must remain green;
5. then squash-merge PR #30.

Do not expand the PR into additional scheduler, UI, batching, or infrastructure work.

---

# 1. Fix Runtime Error Classification

## Problem

The generic exception path in:

```text
docker/runners/common/persistent_runner.py
```

currently treats a non-CUDA unexpected exception as:

```text
FAILED_RESOURCE
```

and may continue through the resource fallback ladder.

Conceptually, the current behavior is:

```text
unexpected exception
↓
CUDA fault?
├── yes → FAILED_RUNTIME / runtime restart path
└── no  → FAILED_RESOURCE
          ↓
          resource fallback retry
```

This is incorrect.

Runner plugins already explicitly classify recoverable OOM conditions as:

```text
OUTCOME_OOM
```

which become:

```text
WorkItemError(FAILED_RESOURCE)
```

Therefore, an exception that reaches the generic `except Exception` branch has **not** been classified as a recoverable resource failure.

Examples include:

```text
output validation failure
malformed generated artifact
filesystem/write failure
unexpected upstream exception
model/runtime bug
post-processing failure
```

None of these should trigger a smaller batch/sample group merely because they happened during a GPU task.

---

## Required Behavior

Use this classification:

```text
Explicit OOM / FAILED_RESOURCE
    → record resource observation
    → bounded resource fallback
    → retry if another declared fallback exists

CUDA context / illegal-memory / unrecoverable CUDA runtime fault
    → FAILED_RUNTIME
    → optionally restart runtime within max_runtime_restarts
    → do not consume the resource fallback ladder as though this were OOM

Any other unexpected exception
    → FAILED_RUNTIME
    → fail this work item immediately
    → continue remaining work items
```

The generic path must **never infer `FAILED_RESOURCE` solely because the error is not a CUDA fault**.

---

## Desired Control Flow

Conceptually:

```python
try:
    attempt_item(...)
except WorkItemError as error:
    if error.state == FAILED_RESOURCE:
        record resource failure
        retry through declared fallback ladder
    else:
        fail item
except Exception as error:
    record runtime error

    if is_unrecoverable_cuda_fault(error):
        fail item as FAILED_RUNTIME
        optionally restart runtime
    else:
        fail item as FAILED_RUNTIME

    continue with remaining work items
```

Do not retry ordinary runtime/validation exceptions under a different resource plan.

---

## Observation Consistency

Ensure the item state and resource observation agree.

Do not allow:

```text
observation:
    outcome = error

final item status:
    FAILED_RESOURCE
```

for the same ordinary runtime exception.

A non-resource exception should produce:

```text
observation:
    outcome = error

item:
    FAILED_RUNTIME
```

---

# 2. Add Regression Tests for Runtime Classification

Add a persistent-runner regression where:

```text
default attempt
↓
inference itself does not report OOM
↓
validation/runtime step raises ValueError or RuntimeError
```

Verify:

```text
item status == FAILED_RUNTIME
attempt count == 1
no fallback execution occurs
remaining work items continue
```

Use a fake plugin whose fallback ladder contains multiple plans so the test proves that none are consumed.

Also verify that a true explicit OOM still does:

```text
default
→ FAILED_RESOURCE
→ fallback
```

so the fix does not break normal adaptive recovery.

---

# 3. Preserve Model/Runtime Identity in `avoid` Guidance

## Problem

Historical evidence is now grouped by:

```text
runner
model_revision
runtime_fingerprint
```

which correctly prevents observations from different revisions/runtimes from being pooled during evidence construction.

However, after `_avoidance_scope()` selects one qualified scope, `guidance_for()` currently publishes profile entries containing only device identity:

```text
device_model
total_vram_mb
known_failing_plans
avoid_scale_at_or_above
```

The following identity is lost:

```text
model_revision
runtime_fingerprint
```

Then the runner's `PlanSequence.bind_device()` matches only:

```text
device model
VRAM
```

This means evidence from one model/runtime can still be applied to another model/runtime running on the same GPU.

Example:

```text
Historical evidence:

ESMFold2 fast
runtime fp-fast
A100 40 GB
→ enough successes
→ OOM boundary learned
```

Later:

```text
New task:

ESMFold2 standard
runtime fp-standard
A100 40 GB
```

If the guidance profile contains only:

```text
A100 40 GB
```

the standard model may bind the fast model's learned failure region.

That is unsafe proactive adaptation.

---

# 4. Extend Guidance Profile Identity

Each proactive guidance profile should retain enough identity to prove that the evidence applies to the running execution.

Recommended shape:

```json
{
  "runner": "esmfold2",
  "model_revision": "...",
  "runtime_fingerprint": "...",
  "device_model": "NVIDIA A100 ...",
  "total_vram_mb": 40960,
  "known_failing_plans": ["..."],
  "avoid_scale_at_or_above": 2000
}
```

`runner` may be redundant inside a runner-owned task, but including it makes the profile self-describing and easier to inspect.

At minimum retain:

```text
model_revision
runtime_fingerprint
device_model
total_vram_mb
```

---

# 5. Bind Guidance After Runtime Initialization

The actual runtime fingerprint and device are only reliable after the runner has initialized its runtime.

Therefore, proactive guidance binding should conceptually occur after:

```text
initialize_runtime()
↓
plugin.model_revision available
plugin.runtime_fingerprint available
plugin.device_profile(runtime) available
↓
bind matching guidance profile
```

Match all relevant fields:

```text
profile.model_revision == plugin.model_revision
profile.runtime_fingerprint == plugin.runtime_fingerprint
profile.device_model == allocated_device.model
profile.total_vram_mb == allocated_device.total_vram_mb
```

If no exact profile matches:

```text
known_failing = empty
avoid threshold = none
```

and execution falls back to normal behavior:

```text
default execution
+
reactive recovery if stage permits it
```

Never borrow the closest profile.

---

# 6. Keep `recover` Behavior Unchanged

The current deployed GPU task families use:

```text
stage: recover
```

The model/runtime identity fix must not disrupt the normal recovery path.

For `recover`:

```text
default execution
↓
actual OOM
↓
runner-owned fallback ladder
```

No proactive profile matching is necessary to begin the task.

The additional identity checks apply primarily to:

```text
stage: avoid
```

---

# 7. Add Cross-Revision Regression Coverage

The existing tests correctly check that evidence is not pooled across revisions/runtimes during historical aggregation.

Add the missing end-to-end guidance-binding case.

Create two independently qualified profiles on the same physical GPU class.

Example:

```text
fast / fp-fast / A100-40G
    4+ valid successes
    OOM boundary at scale X

standard / fp-standard / A100-40G
    4+ valid successes
    no OOM
```

Generate guidance.

Then instantiate/bind as:

```text
model_revision = standard
runtime_fingerprint = fp-standard
device = A100-40G
```

Verify:

```text
fast failure threshold is NOT applied
```

Also test:

```text
model_revision = fast
runtime_fingerprint = fp-fast
device = A100-40G
```

and verify:

```text
fast guidance IS applied
```

Add a runtime-fingerprint variant:

```text
same model revision
same GPU
different runtime fingerprint
```

and confirm stale runtime evidence is not proactively bound.

---

# 8. Guidance Construction Should Support Multiple Valid Scopes

Avoid a design where `_avoidance_scope()` returns whichever qualified scope happens to appear first.

Historical storage may legitimately contain:

```text
esmfold2 / fast / fp-A
esmfold2 / standard / fp-B
simplefold / model-X / fp-C
...
```

If more than one exact scope has enough evidence, guidance should be able to publish all valid scopes relevant to the runner family.

Conceptually:

```text
resource_guidance
└── profiles
    ├── fast / fp-A / A100-40G
    ├── fast / fp-A / L20-48G
    ├── standard / fp-B / A100-40G
    └── ...
```

The runner then selects the exact profile after allocation and runtime initialization.

Do not rely on dict/history insertion order to decide which model/runtime receives proactive knowledge.

---

# 9. Keep Resource Evidence Durable

Do not change the current persistence model unnecessarily.

Raw resource observations remain the source of truth:

```text
resource_observations
```

Derived guidance can be rebuilt after server restart.

The required restart behavior remains:

```text
server/container restart
↓
persistent observation rows remain
↓
guidance reconstructed from store
↓
resource knowledge preserved
```

Do not introduce a separate heavyweight estimator service.

---

# 10. Re-run the Relevant Test Matrix

After both fixes, run all existing required CI.

Required green jobs:

```text
REvoComputeTests
ServerComposeFullStack
BrowserContracts
RunnerScientificAcceptance
REvoCompute Documentation
```

Also run the focused tests covering:

```text
persistent runner lifecycle
OOM fallback behavior
generic runtime failure classification
resource observation ingest
guidance construction
cross-device isolation
cross-revision isolation
cross-runtime isolation
all-failed process exit
resume/restart behavior
```

---

# 11. Live Acceptance

The previous live acceptance already validated freshly built SIFs for:

```text
example
simplefold
esmfold2
```

Do not repeat expensive live inference merely for code paths that are completely server-side unless the fixes affect the runner execution path.

Because the P1 changes runner exception handling, perform at least a lightweight live/smoke validation that:

```text
normal SimpleFold execution succeeds
normal ESMFold2 execution succeeds
```

There is no need to deliberately corrupt real GPU outputs if the regression test exercises the failure branch deterministically.

---

# 12. Review Thread Cleanup

The four original Codex findings have been fixed in code.

After confirming the current implementation and regression coverage, resolve/comment on those old review threads so PR state reflects reality.

Then resolve the two final findings:

```text
generic non-OOM exception classification
model/runtime identity preservation in avoid guidance
```

Do not leave stale unresolved P1/P2 threads when squash-merging unless GitHub tooling prevents resolution; if so, leave a final PR comment mapping each finding to its fix commit/tests.

---

# 13. Do Not Pull the `--no-home` Regression Into PR #30

The remaining fleet-readiness regression:

```text
apptainer --no-home
```

originates from main / security PR #29 and is not part of PR #30's persistent-execution implementation.

Do not broaden PR #30 to fix it unless it directly blocks validation of this branch.

Handle it separately with a focused change:

```text
revocompute/job/runners/slurm_runner.py

remove --no-home
retain --containall
```

but first preserve or add a regression test proving:

```text
container HOME is writable
container writes do not leak into host HOME
```

That fix should be reviewed independently from PR #30.

---

# 14. Merge Gate

PR #30 is ready for squash merge when:

```text
✓ generic non-OOM exceptions become FAILED_RUNTIME
✓ generic runtime failures do not consume resource fallbacks
✓ explicit OOM still triggers bounded recovery
✓ proactive guidance carries model_revision
✓ proactive guidance carries runtime_fingerprint
✓ runner binds guidance by model/runtime/device identity
✓ multiple qualified historical scopes cannot contaminate each other
✓ missing matching profile means no proactive avoidance
✓ all regression tests pass
✓ all required CI is green
✓ PR documentation matches the final behavior
```

No additional architectural cleanup is required for this PR.

Do not refactor `PersistentRunner` merely for abstraction quality.

Do not add UI work.

Do not add cluster-placement logic.

Do not introduce heavier estimator dependencies.

Once these gates are satisfied, **squash-merge PR #30**.