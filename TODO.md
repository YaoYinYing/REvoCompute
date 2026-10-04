# Workflow Stage Marker Correctness

## Objective

Fix the workflow `stage_markers` contract so every marker emitted by a composed
Runner can be observed as task progress and every declared marker has one
well-defined workflow owner.

The current loader checks only that each workflow stage's marker list is a
non-empty subset of the task-level `stage_markers`. It does **not** require:

- complete coverage;
- unique ownership;
- preservation of task-level marker order.

AlphaFold 3 exposes the defect today.

Its task declares:

```text
data_pipeline
feature_validation
inference
output_validation
```

and `run.sh` emits all four, but the workflow declares only:

```text
features -> data_pipeline
model    -> inference
```

During composed execution REvoCompute replaces the TaskType with a stage-local
TaskType containing only that stage's declared markers. Consequently
`feature_validation` and `output_validation` are emitted by the Runner but
silently ignored by the stage parser, and `run_stage` / the running trace
cannot represent those real phases.

Fix the generic contract and then correct the affected manifest. Do not add an
AlphaFold-3-specific runtime workaround.

---

## 0. Campaign position

This is a **Wave 1** PR.

It is implementation-independent from the production-receipt PR, but it touches
Runner execution contracts and may invalidate live-validation identity for any
manifest corrected here. Treat receipt invalidation as a correctness feature,
not something to bypass.

Do not borrow another PR's deployment lease.

---

## 1. Establish the intended invariant

For a task **without** `workflow`, the existing ordered task-level
`stage_markers` behavior remains unchanged.

For a task **with** `workflow`, require the workflow marker declarations to
form an exact ordered partition of task-level `stage_markers`:

```text
concatenate(workflow[i].stage_markers for workflow stages in order)
==
list(task.stage_markers.keys())
```

This single invariant implies:

- every declared marker belongs to a workflow stage;
- no marker is silently omitted;
- no marker is owned by two stages;
- workflow-stage marker order matches the task's user-visible order.

If repository semantics reveal a legitimate case that cannot satisfy this exact
partition, document that case and design the smallest explicit alternative.
Do not silently weaken the contract back to subset-only validation.

---

## 2. Loader validation

Strengthen the canonical task/workflow loader.

Malformed workflow declarations must fail closed during discovery with an error
that identifies the task and the specific mismatch.

Cover at least:

- omitted task-level marker;
- duplicated marker across stages;
- marker reordered across workflow stages;
- unknown marker;
- empty stage marker list;
- valid exact ordered partition.

Keep error handling declarative and generic.

Do not add runtime repair that guesses which workflow stage owns an omitted
marker.

---

## 3. Correct AlphaFold 3

Update the AlphaFold 3 task manifest so the workflow reflects the markers its
real `run.sh` emits.

The intended semantic grouping is:

```text
features:
    data_pipeline
    feature_validation

model:
    inference
    output_validation
```

Verify those markers are emitted by the corresponding `-s features` and
`-s model` execution paths.

Do not rename the markers unless a real semantic mismatch requires it; preserving
stable marker keys is preferable.

---

## 4. Runtime observation

Prove the composed runtime can observe every declared marker.

Tests should exercise the real stage parsing/callback boundary rather than only
asserting YAML text.

For each composed stage verify:

- allocation start may still emit the first stage marker as the current
  liveness behavior;
- subsequent emitted `REVODESIGN_STAGE:<marker>` lines advance `run_stage`;
- duplicate marker lines do not create duplicate progress transitions;
- a marker belonging to another workflow stage is not accepted by the active
  stage;
- completing a stage settles on its final declared marker;
- the next workflow stage begins at its own first marker;
- the final task state exposes the final task-level marker.

Keep the existing "stage callback failure must not mask execution status"
behavior.

---

## 5. Running trace semantics

Verify `_build_running_trace` and any API/frontend projection driven by
`run_stage` remain coherent with the corrected marker sequence.

For an AlphaFold 3 task, a running trace must be able to represent all four
phases in order rather than skipping the two validation phases.

Do not redesign the Dashboard or Result UI in this PR.

---

## 6. Validation identity and receipts

`stage_markers` and workflow marker ownership participate in the Runner
execution/validation contract.

Therefore:

- confirm the corrected manifest changes the appropriate
  `configuration_digest`;
- do not preserve or rewrite an old PASS receipt as though the execution
  contract were unchanged;
- if the affected Runner is enabled on an available target and release readiness
  requires it, re-run the appropriate live acceptance under the Campaign
  deployment lease;
- if it cannot be live-run on the current target, record that limitation
  explicitly rather than fabricating evidence.

Do not broaden the PR into unrelated AlphaFold 3 readiness work.

---

## 7. Fleet audit

There are currently only a small number of composed workflow task types.

Audit every task manifest that declares `workflow` against the new invariant.

Correct only genuine marker ownership defects surfaced by that audit.

Do not reformat unrelated manifests or touch single-stage/non-workflow Runner
markers merely for consistency.

---

## 8. Required tests

Add focused tests to the canonical task loader and execution path.

At minimum:

```text
valid exact partition                      PASS
omitted marker                             FAIL discovery
duplicated marker                          FAIL discovery
out-of-order marker partition              FAIL discovery
unknown marker                             FAIL discovery
AF3 features sees data_pipeline
AF3 features sees feature_validation
AF3 model sees inference
AF3 model sees output_validation
run_stage progresses through all markers
configuration identity changes when ownership changes
```

Run the focused task-type, Slurm/composer, AlphaFold 3 protocol, validation
identity, and server projection tests affected by the change.

Run the repository non-browser gate appropriate to the touched code and
`git diff --check`.

If documentation changes, run `mkdocs build --strict`.

---

## 9. Scope exclusions

Do **not**:

- add Runner-name branches to the scheduler;
- redesign the workflow composer;
- redesign task status storage;
- change ResultManifest;
- change scientific parameters;
- rename stage markers just to make tests easier;
- mask stale live-validation receipts;
- refactor unrelated Runner manifests;
- perform general frontend polish.

---

## 10. Definition of done

The PR is complete when the following statement is mechanically true:

> For every composed task, the ordered task-level stage marker sequence is
> exactly partitioned across its ordered workflow stages, and every marker the
> Runner emits for the active stage can advance the canonical task
> `run_stage`.

AlphaFold 3 must no longer emit `feature_validation` or
`output_validation` into a runtime that cannot observe them.
