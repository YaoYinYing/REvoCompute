# Persistent Multi-Input Execution and Adaptive OOM Recovery — Implementation State

- Branch: `feat/persistent-multi-input-execution`
- Design: `TODO.md` (sections 1–27, plus appended constraints in §28)
- Protocol: `LONG_TASK_HANDLING.md`

## Architecture freeze (single source of truth)

Three separated responsibilities, one implementation each:

| Component | Owner | Where it runs |
| --- | --- | --- |
| `VRAMEstimator` | `revocompute/resource_model.py` | server worker (ingest/guidance) **and** runner (in-process RECOVER) |
| `DeviceObserver` | `resource_model.py` + runner | runner, immediately after Slurm allocation |
| `ResourcePlanner` | `resource_model.py` | runner, bounded by runner-declared fallback plans |

`revocompute/resource_model.py` is the only implementation. It is copied into every
participating runner image as `/app/revocompute/resource_model.py` via
`docker/runners/common/`, so there is **no** second representation of the
estimator. Dependencies: **stdlib + NumPy only.** No PyTorch/JAX/TF/Triton/Ray
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
- **Task outcome** (`success | partial_success | failed | cancelled`) is derived
  from item states and published in the results manifest and the running
  payload. The `tasks.status` vocabulary is unchanged (`finished`/`failed`/
  `cancelled`), so no status-machine migration is required.
- **Fallback policy is runner-owned**: declared as `resource_adaptation` metadata
  in the owning `task.yaml`/`runner.yaml`, parsed by `task_types`. Server core
  contains no `if runner == ...` branch.
- **Rollout stage** (`observe | recover | avoid`) is configurable and defaults to
  `observe` for deployment.

### Estimator model (frozen, NumPy only)

```text
predicted_total = baseline(model_scale)            # runtime/model residency
                + shared_workload(features)        # global, all device classes
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
  "execution_queue": {"ratios": [1.5, 2.0], "constraints": {}},
  "resource_adaptation": {
    "stage": "observe",
    "fallback_plans": [{"label": "...", "title": "...", "adjustments": {...}}]
  },
  "observations": [{"<normalized ResourceObservation>": "..."}]
}
```

`resource_adaptation` is projected from the owning `task.yaml`, which is the sole
authoritative source. `observations` is a bounded projection of the server's
`resource_observations` table for the same runner family (newest first, capped).
`params` and `inputs` are unchanged, so a runner that ignores the new keys
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

## Completion checklist

- [ ] `revocompute/resource_model.py`: `DeviceProfile`, `WorkloadFeatures`,
      `ResourceObservation`, `VramPrediction`, `VRAMEstimator`,
      `ResourcePlanner`, `FallbackPlan`, staged rollout, explainability.
- [ ] `resource_observations` table + store, ingest, dedupe, quality weighting.
- [ ] Runner-declared fallback policy parsed from the owning manifest.
- [ ] `docker/runners/common/persistent_runner.py`: Work Item states,
      `ExecutionQueue` (length-bucketed stable order), persistent runtime
      lifecycle, atomic per-item commit, resume from `work_items.json`,
      bounded OOM recovery, observation emission.
- [ ] SimpleFold: multi-record FASTA, model loaded once, per-item commit/resume,
      OOM fallback (`num_samples` grouping), pLDDT preserved.
- [ ] ESMFold 2: multi-record FASTA, model loaded once, per-item commit/resume,
      OOM fallback (`batch`/token-budget splitting), sample identity preserved.
- [ ] Server: guidance into `task.json`, observation ingest, live per-item
      progress, partial-success outcome in the manifest, UI exposure.
- [ ] Example runner: minimal reference implementation of the lifecycle.
- [ ] Docs: Runner Protocol page for multi-input, lifecycle, item state, resume,
      OOM recovery, adaptation boundaries.
- [ ] Tests: multi-input, resume, partial failure, OOM recovery, irreducible OOM,
      scientific semantics, atomic outputs, estimator behaviour + architecture
      gates (no ML framework import in server, no runner-name branches in core).
- [ ] Full `make test`, strict MkDocs, shell syntax checks.
- [ ] Redeploy with `--use-proxy`; live Runner test as `tester`.
- [ ] Three-agent review pass; act on valid findings.
- [ ] Push branch, open PR.

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

Phase 2 — generic contracts (`resource_model.py`, `persistent_runner.py`).
