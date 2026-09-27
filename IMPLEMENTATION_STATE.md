# Persistent Multi-Input Execution and Adaptive OOM Recovery — Implementation State

- Branch: `feat/persistent-multi-input-execution`
- Design: `TODO.md` (sections 1–27, plus appended constraints in §28)
- Protocol: `LONG_TASK_HANDLING.md`

## Architecture (single source of truth)

Three separated responsibilities, one implementation each:

| Component | Owner | Where it runs |
| --- | --- | --- |
| `VRAMEstimator` / `ResourcePlanner` | `revocompute/resource_model.py` | server worker; resource analysis, not on the production planning path |
| device observation | runner, via its framework's own memory API | runner, after Slurm allocation |
| guidance projection (`guidance_for`) | `revocompute/resource_model.py` | server computes `resource_guidance`; the runner enforces it |

`revocompute/resource_model.py` is the only implementation, and it is
**server-side only**. The runner measures with the framework that owns its GPU
allocations, enforces the plan order it declares (filtered by the server's
`plan_order`), and imports no part of the estimator —
`docker/runners/common/persistent_runner.py` is standard library only and no
runner image ships NumPy for this feature. Dependencies of the server module:
**stdlib + NumPy only.** No PyTorch/JAX/TF/Triton/Ray in the server image for
this feature.

Production planning is **observational**: the submission path builds
`resource_guidance` with `guidance_for` from persisted observation rows.
`VRAMEstimator.predict` / `ResourcePlanner.decide` are tested resource-analysis
components that do not select execution plans in production; a numerical
prediction returns only when candidate plans can be projected into the effective
resource features they would execute.

Runner-side persistent execution lives in one shared module,
`docker/runners/common/persistent_runner.py`, copied into participating images.

### Boundaries (frozen)

- **Input**: one FASTA in the declared `sequence` role may contain many records.
  Work-item normalization (record → Work Item with stable id, original index,
  length) happens **in the runner**. No server input-contract change for record
  count; `validate_fasta` already permits many records.
- **Durable task manifest**: `outputs/work_items.json`, written atomically by the
  runner, is the authoritative per-item state. The server reads it live (the
  result dir is the same host path the worker sees) and at finalization.
- **No new columns on existing tables.** `require_current_schema` rejects a DB
  whose `tasks` table lacks declared columns, so the only safe additions are new
  tables (`resource_observations`).
- **Task outcome** (`SUCCESS | PARTIAL_SUCCESS | FAILED | CANCELLED_PARTIAL`) is
  derived from item states and published in the results manifest as `outcome`
  (`null` for a task that has no per-item manifest) and in the running payload
  as `outcome` once reported. The `tasks.status` vocabulary is unchanged
  (`finished`/`failed`/`cancelled`) — a PARTIAL_SUCCESS task is finalized as
  `finished` — so no status-machine migration is required.
- **Per-item progress** is read live from the runner's `work_items.json`; the
  runner's own `REVODESIGN_PROGRESS` line is recorded on the task row and is the
  fallback for a task whose result directory is no longer readable.
- **Fallback policy is runner-owned**: declared as `resource_adaptation` metadata
  in the owning `task.yaml`, parsed by `task_types`. Server core
  contains no `if runner == ...` branch, and the runner's own implementation
  realizes only the adjustment keys it declares.
- **Rollout stage** (`observe | recover | avoid`) is owned by the owning
  `task.yaml`; the dataclass default is `observe`. ESMFold 2 and SimpleFold
  declare `recover`, since automatic OOM recovery is intended to be active for
  them; the Example runner stays `observe`. `observe` never changes execution —
  no proactive skip and no reactive fallback after a real OOM. `recover` leaves
  the default path untouched and walks the declared fallbacks after a real OOM.
  `avoid` adds proactive skipping of a profile-scoped known-failing plan or
  scale.
- **Only a classified shortage spends a fallback.** An explicitly classified
  OOM (`OUTCOME_OOM` / `WorkItemError(FAILED_RESOURCE)`) retries through the
  declared ladder within the bounded budget. An unrecoverable CUDA-context fault
  fails the item `FAILED_RUNTIME` and rebuilds the runtime within
  `max_runtime_restarts`. Any other unexpected exception fails the item
  `FAILED_RUNTIME` immediately and consumes no fallback: the ladder lowers
  instantaneous memory, so it cannot fix a non-memory failure.

### Estimator model (frozen, NumPy only)

```text
predicted_total = baseline(model_scale)            # runtime/model residency
                + shared_workload(features)        # one fit per runner/model group
                + device_correction(device_class)  # residual, per device class
```

Prediction returns `expected`, `upper_bound`, `confidence`, `applicable`, and an
explainability `basis`. Outside the learned domain → `applicable=False` and the
planner uses conservative heuristics. OOM rows are censored constraints
(`required > available`), never discarded. Observations carry a
`runtime_fingerprint`; a fingerprint mismatch demotes them to a weaker prior.

### Frozen wire interfaces (do not change without updating this section)

`task.json` (runner protocol v4 — additive; every existing key keeps its meaning):

```json
{
  "version": 4,
  "task_id": "...",
  "task_type": "...",
  "params": {"<name>": "<value>"},
  "inputs": {"<role>": [{"original_name", "path", "relative_path", "format",
                         "logical_type", "sha256", "validation"}]},
  "execution": {"batch_size": 1, "max_item_attempts": 3, "max_runtime_restarts": 1},
  "execution_queue": {"ratios": [1.5, 2.0]},
  "resource_adaptation": {
    "stage": "recover",
    "fallback_plans": [{"label": "...", "title": "...", "adjustments": {...}}]
  },
  "resource_guidance": {
    "stage": "recover",
    "plan_order": ["", "label-a", "label-b"],
    "profiles": [
      {"runner": "esmfold2", "model_revision": "fast", "runtime_fingerprint": "fp-1",
       "device_model": "A100-PCIE-40GB", "total_vram_mb": 40960,
       "known_failing_plans": ["label-a"], "avoid_scale_at_or_above": 900}
    ]
  }
}
```

`resource_adaptation` is projected from the owning `task.yaml`, which is the sole
authoritative source; every plan is validated through `FallbackPlan.parse_all`, so
a plan that would change a scientific parameter is rejected at discovery. The
runner enforces it **locally and stdlib-only**: it never imports the estimator,
never needs NumPy, and never invents an adjustment.

`resource_guidance` is that enforcement's whole input, computed by
`revocompute/resource_model.py` (`guidance_for`) from the stored observations
(newest-first, capped at `OBSERVATION_LIMIT` rows per runner family).
`plan_order` is the attempt→plan sequence (`""` is the default upstream path) and
always lists every declared plan; it is the same in every stage, because the
stage decides what the order is *used* for, not what it contains. `profiles` is
populated only in `avoid`, one entry per exact `(model_revision,
runtime_fingerprint, device_model, total_vram_mb)`, because neither the concrete
GPU nor the full runtime identity is known at submission time — the runner binds
the entry matching its own revision, fingerprint, and the device it was actually
allocated after Slurm allocation and runtime initialization
(`PlanSequence.bind_identity`). Every qualified scope is published, so no profile
is selected by insertion order, and an unmatched revision, runtime, or device
gets the default path plus bounded recovery rather than another profile's
threshold.
Within a profile a plan is "established failing" only when it has OOM rows and no
usable success; the scale threshold is the smallest *requested* workload scale
observed to OOM, in the units the runner compares (`length × sequence_count ×
sample_count × batch_size`). Evidence is scoped to the exact `(runner,
model_revision, runtime_fingerprint)` triple: with no triple that has
`MIN_OBSERVATIONS` usable successes and an OOM row, `profiles` stays empty and
the runner falls back to plain bounded recovery.

The runner history itself stays server-side; `resource_guidance` is its only
projection into `task.json`, so no raw observation rows are shipped to the Slurm
job. `params` and `inputs` are unchanged, so a runner that ignores the new keys
behaves exactly as before.

The family's own `work-items.json` config file (one per task, written by the
family entrypoint from the FASTA plus `task.json`) is passed to
`persistent_runner.execute_task` and is internal to the runner image.

Runner → server stdout channels (all additive; unknown lines are ignored):

```text
REVODESIGN_PROGRESS:{"total_items","completed_items","failed_items","pending_items","current_item","current_attempt"}
REVODESIGN_OBSERVATION:{<normalized ResourceObservation>}
REVODESIGN_TASK_OUTCOME:SUCCESS|PARTIAL_SUCCESS|FAILED|CANCELLED_PARTIAL
```

Durable per-item state (runner-written, server-read — no DB column):

```text
outputs/work_items.json   # authoritative item state, atomic writes
outputs/<item>/           # committed item artifacts (rename from outputs/.tmp/<item>/)
outputs/.tmp/             # in-flight staging only; never a valid result
```

The server reads `work_items.json` live for per-item progress and at
finalization for the standardized task outcome. `tasks.status` stays
`finished`/`failed`/`cancelled`; the derived outcome is published in the results
manifest (and the running payload) as `outcome`, so no status-machine migration
is introduced.

Progress and outcome are recorded in the new `task_execution_progress` table
keyed by task id, never in `tasks.workflow_state`: that column is the workflow
engine's durable per-stage record and a resumable workflow reads it back to
decide what to run next, so sharing it would make one column mean two things and
let a progress write corrupt a workflow resume.

## Completion checklist

- [x] `revocompute/resource_model.py`: `DeviceProfile`, `WorkloadFeatures`,
      `ResourceObservation`, `VramPrediction`, `VRAMEstimator`,
      `ResourcePlanner`, `FallbackPlan`, staged rollout, explainability.
- [x] `resource_observations` table + store, ingest, dedupe, quality weighting.
- [x] Runner-declared fallback policy parsed from the owning manifest.
- [x] `docker/runners/common/persistent_runner.py`: Work Item states,
      `ExecutionQueue` (length-bucketed stable order), persistent runtime
      lifecycle, atomic per-item commit, resume from `work_items.json`,
      bounded OOM recovery, observation emission.
- [x] SimpleFold: multi-record FASTA, model loaded once, per-item commit/resume,
      OOM fallback (`num_samples` grouping), pLDDT preserved.
- [x] ESMFold 2: multi-record FASTA, model loaded once, per-item commit/resume,
      OOM fallback (sample grouping / reference kernels), sample identity
      preserved.
- [x] Server: guidance into `task.json`, observation ingest, live per-item
      progress, partial-success outcome in the manifest. UI exposure is
      API-level: the dashboard and running payload carry the per-item progress
      and outcome, and the Result Workspace renders whatever artifacts the
      finalized manifest publishes.
- [x] Example runner: minimal reference implementation of the lifecycle.
- [x] Docs: `docs/runner-guide/persistent-execution.md` — multi-input, lifecycle,
      item state, resume, OOM recovery, adaptation boundaries.
- [x] Tests: multi-input, resume, partial failure, per-record input rejection,
      OOM recovery, irreducible OOM, scientific semantics, atomic outputs,
      estimator behaviour. (The "architecture gates" earlier claimed here were
      never tests that existed — the separation is enforced by construction:
      the runner module imports stdlib only and the server module imports NumPy
      only, and neither imports the other.)
- [x] Full `make test`, strict MkDocs, shell syntax checks.
- [x] Three-agent review pass; valid findings acted on.
- [x] PR review pass (Codex, PR #30): four findings verified and fixed.
- [x] Stabilization pass (TODO.md §1–§13): consistent stage semantics,
      profile-scoped guidance selected after allocation, monotonic ladders with
      no-op plans skipped, effective per-attempt features, raw observation
      facts, grouping-independent sample seeds, stratified retention,
      restart-rebuild from the store. Three more review passes ran over it and
      their valid findings were fixed in `c253584` and the commit after it.
- [x] Final closure pass (TODO.md of this revision §1–§13): the generic
      exception path no longer infers `FAILED_RESOURCE` for a non-CUDA error —
      only an explicitly classified OOM spends a fallback — and every `avoid`
      profile carries `runner`/`model_revision`/`runtime_fingerprint` alongside
      the device, with `PlanSequence.bind_identity` matching all four after
      runtime initialization.

## Evidence (this revision)

```text
python -m pytest tests/ -q -m "not browser" -n 4 --dist=load
                                                           -> 1430 passed, 19 skipped
python -m pytest tests/runners tests/test_resource_model.py
        tests/server/test_resource_adaptation.py           -> 306 passed, 13 skipped
mkdocs build --strict                                      -> built clean
bash -n on every changed run.sh                            -> clean
python revocompute/resource_model.py                       -> self-check passed
python docker/runners/common/*.py                          -> self-check passed
```

### Live Slurm/Apptainer acceptance (2026-09-27, A100-PCIE-40GB)

The acceptance below was recorded before the stabilization pass, which changed
the build inputs of both GPU families (`common/persistent_runner.py`, the family
entrypoints, and their `task.yaml` files). Those receipts therefore no longer
match the current tree and the three families read `VALIDATION_STALE`/
`BUILD_STALE` until the acceptance is repeated; the previous multiple-input,
partial-failure, and all-failure live behavior is unchanged by the pass.

```text
live-test --runner example    --use-proxy  -> PASS (smoke, 21s, job 55805)
live-test --runner simplefold --use-proxy  -> PASS (2 smoke cases, jobs 55847/55859)
live-test --runner esmfold2   --use-proxy  -> PASS (2 smoke cases, jobs 55978/55989)
```

Each family's candidate SIF was built directly with Apptainer from its `.def`,
validated on the target host, run through real Slurm, received a receipt, and
was promoted into the active image; `runner-status` then reports all three
READY. The multi-record cases exercised the persistent lifecycle end to end:
one model load per task, one committed directory per record, and (for ESMFold 2)
`peak_process_mb` 13094 against `available_mb` 26849 recorded as `valid`.

Two further runs through the public API as `tester`:

```text
3-record FASTA (all valid)     -> finished, outcome SUCCESS, 3 committed items
2-record FASTA (one bad symbol)-> finished, outcome PARTIAL_SUCCESS
                                  good_chain SUCCEEDED, bad_symbol FAILED_INPUT
                                  ("sequence contains unsupported residues: Z")
```

Both wrote `work_items.json` in original input order, left no `.tmp` staging in
the result tree (verified directly), and landed as rows in
`resource_observations` (runner `esmfold2`, device class `nvidia/A100`, VRAM
class `40GiB`, plan label `""`) and `task_execution_progress` (`SUCCESS`,
`PARTIAL_SUCCESS`). The `task.json` the job received carried
`resource_guidance.plan_order` derived from the owning manifest and no
`observations` key.

That live pass also found and fixed the one real defect in this revision: the
persistent-runner refactor had assigned `ESMFOLD_CCD_PATH`, while upstream's
`conformers.load_ccd` reads `ESMCFOLD_CCD_PATH`. With the correct name unset,
the input builder fell back to a Hugging Face download that the image's
`HF_HUB_OFFLINE=1` turns into a hard failure — ESMFold 2 failed before its first
work item until commit `852eccc` restored the name and pinned it with a test.

Still not evidenced: nothing in this revision is now unvalidated for the three
participating families beyond the build receipts noted above. The other 27
enabled families are untouched by this change; their own
`VALIDATION_STALE`/`BUILD_STALE` readiness predates it.

## PR review pass (Codex, PR #30)

Four findings, each independently verified against the code before acting on it:

1. **All-failed tasks exited 0** (P1, confirmed, but not where the reviewer
   pointed). The defect was not in `PersistentTask.run()` — it was that only the
   Example family consulted the derived outcome, so ESMFold 2 and SimpleFold
   returned 0 for `FAILED`, wrote `task_finished`, and were published as
   `finished` with no successful work item. Fixed with one shared
   `exit_code_for`, now used by all three entrypoints, and pinned by a new test
   per family at the `run.sh` boundary (`FAILED` → non-zero, no
   `task_finished`, `work_items.json` still written). `PARTIAL_SUCCESS` still
   exits 0: it is a real result, and the derived outcome is what distinguishes it.
2. **The retry budget could strand a declared plan** (P1, confirmed by running
   the real `PlanSequence`). `max_item_attempts: 3` allowed only the default
   path plus two fallbacks, so ESMFold 2's third plan (`reference_kernels`) was
   unreachable — contradicting the invariant commit `79f65b8` had just added.
   The server also always projects the key with a default of 1, so the
   computed-default branch was unreachable in production. The budget is now a
   floor (`max(declared, plans + 1)`), and the self-check covers a manifest that
   declares a budget *below* its own plan count.
3. **Successful GPU rows lost their peaks** (P1, confirmed). `_execute` unpacked
   the framework's high-water counters and discarded them; `attempt_item` then
   re-read current allocator residency, so every successful ESMFold 2 /
   SimpleFold row reported `incremental_mb == 0` — the estimator's training
   target was empty for the only rows that are training data. The success path
   now returns the measured peaks and stores them, as the failure path already
   did.
4. **Avoidance guidance was not profile-scoped** (P2, confirmed). Rows were
   aggregated across model revision, runtime fingerprint, and device class, so
   one OOM under a larger model could establish a threshold that made the runner
   skip a safe default for an unrelated one — while the estimator's own
   `known_failure_envelope` already scopes correctly. `guidance_for` now selects
   every qualified scope and publishes the full identity with each entry, and
   `PlanSequence.bind_identity` binds on it. Latent today (no deployed task
   declares `avoid`), fixed before one can.

A fifth finding was investigated and **not** a branch defect: the
`ServerComposeFullStack` CI job fails intermittently with
`celery_worker: worker_unavailable`. The same signature has failed and re-run
green on `main` (run 36142245566) and on the merged PR #29, and the readiness
check had no bounded wait for the worker — `_wait_for_server` only proves the
web process serves pages. `tests/full_stack_smoke.py` now retries the refresh
within a deadline, which bounds the race without weakening the assertion.

## Progress log

### 2026-09-26 — Phase 1: inventory and design validation

- Read `CLAUDE.md`, `LONG_TASK_HANDLING.md`, runner-guide contracts, and the
  full `TODO.md`; appended the mid-flight constraints as `TODO.md` §28.
- Mapped the server path: input roles/cardinality (`io_contracts.py`,
  `routes.py:_validate_role_counts`), `task.json` build (`routes.py:1950`),
  result manifest (`task_runtime.py:_finalize_results_manifest`), result routes,
  stage-marker progress (`run_stage` only), status vocabulary (`db.py`), and the
  Slurm/Apptainer adapter (`slurm_runner.py`).
- Confirmed the durable manifest and per-item subdirectory approach needs **no**
  server schema migration: new tables only.
- Confirmed the runner mounts its output dir from the same host path the worker
  reads, so a runner-written `work_items.json` is observable live.
- Upstream sources pinned locally for design reference:
  `apple/ml-simplefold@c7a5570` and `Biohub/esm@bf343ba` (ESMFold 2).

### Active phase

### 2026-09-27 — Phase 4: review, live acceptance, final state

- Three independent review passes ran over the branch (runner lifecycle,
  estimator/planner, docs-and-example). Valid findings were fixed in `79f65b8`,
  `81b18ec`, and `2e5aae4`; the docs corrections landed there too. Notable:
  a per-record input envelope was being enforced during *normalization*, so one
  unsupported symbol failed the whole task with no `work_items.json` — the
  opposite of every family's own `task.yaml`. It now fails that item alone.
- Two carried-but-unread interfaces were removed rather than documented: the
  `observations` key on the wire (guidance is the estimator's only projection)
  and `execution_queue.constraints` (the queue only orders). Deleting beat
  keeping a second source of truth for evidence that never arrived.
- Live acceptance (see Evidence) passed for example/simplefold/esmfold2 on real
  Slurm/Apptainer; readiness is READY for all three and unchanged for the rest.
- `852eccc` fixed the `ESMCFOLD_CCD_PATH` typo the live run exposed.

Phase 3 — reference implementation migration:

- `docker/runners/common/work_items.py` landed: FASTA-record → work-item
  normalization and `task.json` → `execute_task` config assembly, stdlib only.
- Server slice landed: `task.yaml` `execution`/`execution_queue`/
  `resource_adaptation` parsed into `TaskType`; new `resource_observations` and
  `task_execution_progress` tables; `revocompute/resource_observations.py`
  ingest/projection; `task.json` v4 projection in the submit route and the live
  test executor; stdout progress/observation/outcome ingestion in the Slurm
  adapter (in `poll()`'s `finally`, so it runs for failed jobs too; a job with
  no task store — a recovery/manual call — simply records nothing); live
  per-item progress in the running payload and dashboard; per-item list plus
  standardized `outcome` in the finalized manifest.
- `revocompute/resource_observations.py` is imported by `routes` before the task
  runtime, so it takes the task store as an explicit `store=` argument instead
  of importing it lazily at call time: reaching back for the module global
  re-enters a partially initialized application from inside a request and
  silently breaks task-type discovery in the worker. Store-taking is also the
  honest signature — the caller owns the store that its task row lives in.
- ESMFold 2 family migration: persistent runtime, per-item commit, declared
  fallback plans, multi-record smoke case. SimpleFold followed, and the Example
  family was rebuilt as the minimal reference implementation.

### 2026-09-26 — Phase 2: generic contracts landed

- `revocompute/resource_model.py` — estimator, planner, device profile,
  observation schema, stages. NumPy-only, self-checked.
- `docker/runners/common/persistent_runner.py` — lifecycle, ExecutionQueue,
  atomic commit, resume, bounded recovery, runtime restart, derived outcome.
  Stdlib-only by design; the estimator stays server-side.
- Server-held config (`resource_adaptation`) and learned enforcement
  (`resource_guidance`) are separate keys with separate owners: the owning
  `task.yaml` declares the stage and the fallback vocabulary; `guidance_for`
  computes what the evidence says about them.
