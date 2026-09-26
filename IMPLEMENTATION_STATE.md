# Persistent Multi-Input Execution and Adaptive OOM Recovery — Implementation State

- Branch: `feat/persistent-multi-input-execution`
- Design: `TODO.md` (sections 1–27, plus appended constraints in §28)
- Protocol: `LONG_TASK_HANDLING.md`

## Architecture freeze (single source of truth)

Three separated responsibilities, one implementation each:

| Component | Owner | Where it runs |
| --- | --- | --- |
| `VRAMEstimator` | `revocompute/resource_model.py` | server worker (ingest/guidance) only |
| `DeviceObserver` | runner, via its framework's own memory API | runner, after Slurm allocation |
| `ResourcePlanner` | server, projected as `resource_guidance`; enforced by the runner | server computes, runner enforces |

`revocompute/resource_model.py` is the only implementation, and it is
**server-side only**. The runner measures with the framework that owns its GPU
allocations, enforces the plan order the server sends it, and imports no part of
the estimator — `docker/runners/common/persistent_runner.py` is standard library
only and no runner image ships NumPy for this feature. Dependencies of the
server module: **stdlib + NumPy only.** No PyTorch/JAX/TF/Triton/Ray
in the server image for this feature.

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
- **Rollout stage** (`observe | recover | avoid`) is configurable and defaults to
  `observe` for deployment.

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
    "stage": "observe",
    "fallback_plans": [{"label": "...", "title": "...", "adjustments": {...}}]
  },
  "resource_guidance": {
    "stage": "observe",
    "plan_order": ["", "label-a", "label-b"],
    "known_failing_plans": [],
    "avoid_scale_at_or_above": null
  }
}
```

`resource_adaptation` is projected from the owning `task.yaml`, which is the sole
authoritative source; every plan is validated through `FallbackPlan.parse_all`, so
a plan that would change a scientific parameter is rejected at discovery. The
runner enforces enforcement **locally and stdlib-only**: it never imports the
estimator, never needs NumPy, and never invents an adjustment.

`resource_guidance` is that enforcement's whole input, computed by
`revocompute/resource_model.py` (`guidance_for`) from the stored observations
(newest-first, capped at `OBSERVATION_LIMIT` rows per runner family).
`plan_order` is the attempt→plan sequence (`""` is the default upstream path).
In `observe` it is just `[""]`. `known_failing_plans` / `avoid_scale_at_or_above`
are populated only in `avoid` stage, from OOM evidence alone: a plan is
"established failing" only when it has OOM rows for this profile and no success,
and the scale threshold is the smallest workload scale observed to OOM. Below
`MIN_OBSERVATIONS` usable successes the evidence cannot speak for the profile at
all, so both stay empty and the runner falls back to plain bounded recovery.

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
- [x] Redeployed with `--use-proxy`; live Runner tests as `tester`.
- [x] Three-agent review pass; valid findings acted on.
- [ ] Push branch, open PR.

## Evidence (this revision)

```text
uv run --no-sync python -m pytest tests/ -q (non-browser)  -> 1375 passed, 19 skipped
uv run --no-sync python -m pytest tests/runners tests/test_resource_model.py
        tests/server/test_resource_adaptation.py             -> 281 passed, 13 skipped
uv run --no-sync python -m revocompute doctor --runner <family> --strict
        (example, simplefold, esmfold2)                    -> OK, no diagnostics
uv run --no-sync mkdocs build --strict                     -> built clean
bash -n on every changed run.sh                            -> clean
uv run --no-sync python revocompute/resource_model.py      -> self-check passed
uv run --no-sync python docker/runners/common/*.py         -> self-check passed
```

### Live Slurm/Apptainer acceptance (2026-09-27, A100-PCIE-40GB)

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
participating families. The other 27 enabled families are untouched by this
change; their own `VALIDATION_STALE`/`BUILD_STALE` readiness predates it.

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
