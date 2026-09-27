# Immutable Runner Runtime Overlay — Implementation State

- Branch: `feat/runtime-overlay`
- Design: `TODO.md` (sections 1–29)
- Protocol: `LONG_TASK_HANDLING.md`

## Architecture (single source of truth)

Three artifact classes with three identities, each with its own freshness:

| Artifact | What it owns | Identity | Change ⇒ |
| --- | --- | --- | --- |
| SIF | OS / CUDA / Python / libraries / pinned upstream / build-time inputs | Build Identity (`definition` + `build_inputs` + builder version) | `BUILD_STALE` |
| Runtime bundle | REvoCompute-owned executable code (`common/runtime/*`, family `run.sh` + adapters) | Runtime Bundle Identity (content-addressed digest of exactly the paths that family declares) | SIF stays current, `VALIDATION_STALE` |
| External resources | databases / weights / checkpoints | operator-owned (`runner.yaml.mounts`) | neither |

Execution Contract Identity and Presentation Identity are unchanged from the
Runner change-impact contract; Runtime Bundle Identity sits between Build and
Execution Contract: it is computed from repository source, and it participates
in the receipt.

Guiding rule: **build the environment; mount the orchestration.**

### Ownership

| Component | Owner |
| --- | --- |
| `runtime_overlay` schema | `revocompute/plugins`, `revocompute/task_types` |
| bundle digest + materialization | `revocompute/runtime_bundle.py` (server-importable, stdlib only) |
| deployment-side digest/validation | `run/revocompute_ctl/registry.py` |
| task pinning | `task.json` `runtime_bundle` key (server) → `SlurmJob` bind (adapter) |
| GC | `run/revocompute_ctl/` (deployment-owned store only) |

### Frozen interfaces

`plugin.yaml` `runtime` gains one key (additive):

```yaml
runtime:
  image_artifact: example_v1.sif
  definition: example.def
  build_inputs: [example/requirements.lock]     # SIF inputs only
  runtime_overlay:                              # repository-relative, beneath docker/runners/
    - common/runtime/
    - example/run.sh
    - example/analyze.py
  entrypoint: [bash, /opt/revocompute/runtime/example/run.sh]
```

Materialized container layout: `/opt/revocompute/runtime/<repository-relative path>`.
Mount: `--bind <bundle>:/opt/revocompute/runtime:ro`, reserved, never user-supplied.

`task.json` (runner protocol v4 — additive; every existing key keeps its meaning):

```json
{
  "runtime_bundle": {"sha256": "sha256:...", "path": "/mnt/data/.../runtime-bundles/sha256-..."}
}
```

Resource adaptations, OOM policy, and every scientific parameter are unchanged
by this refactor.

## Completion checklist

Phase 1 — inventory and design validation
- [x] Read `CLAUDE.md`, `LONG_TASK_HANDLING.md`, runner-guide contracts, `TODO.md`.
- [x] Inventory every family's `%files`, `build_inputs`, and `common/*` usage.
- [x] Decide the migration scope: shared helpers migrate for every family;
      full end-to-end (SIF + bundle + receipt + launch) migrates for
      Example/SimpleFold/ESMFold2; the fleet rebuild is deferred and recorded.

Phase 2 — generic contracts
- [ ] `revocompute/runtime_bundle.py`: manifest parsing, path safety, deterministic
      hashing, materialization, GC eligibility — stdlib only.
- [ ] `runtime_overlay` accepted by `PluginManifest`/`load_plugin_families`/`discover_plugins`.
- [ ] Doctor detects every §18 condition.

Phase 3 — reference implementation migration
- [ ] `common/runtime/` subtree created; import paths updated.
- [ ] Example Runner: SIF is environment only; adapter runs from the bundle.

Phase 4 — production dependency switch
- [ ] Task submission pins the bundle digest into `task.json`.
- [ ] `SlurmJob` binds the pinned bundle read-only at `/opt/revocompute/runtime`.
- [ ] Missing bundle fails closed before submission.

Phase 5 — bulk migration
- [ ] Shared helpers removed from every family's `build_inputs`/`%files`.
- [ ] SimpleFold and ESMFold2 migrated end-to-end.

Phase 6 — old architecture removal
- [ ] No `common/<helper>` reference remains in `build_inputs`, `%files`, or `%test`.
- [ ] No compatibility copies of a helper in two locations.

Phase 7 — doctor / architecture validation
- [ ] Identity tests: hashing, freshness, pinning, receipt, launch, lifecycle.

Phase 8 — full regression verification
- [ ] `make test`, strict MkDocs, shell syntax checks.
- [ ] Live acceptance: Example (CPU), SimpleFold and ESMFold2 (GPU).

## Evidence

(populated as phases land)

## Progress log

### 2026-09-27 — Phase 1: inventory and design validation

- 31 of 31 families bake `common/task_context.sh` + `common/task_context.py`;
  eight also bake `common/verify_model_asset.sh`; three bake the persistent
  lifecycle (`common/persistent_runner.py`, `common/work_items.py`).
- Deployed instance: `SERVER_DIR=/mnt/data/srv/revodesign/server-slurm/server`,
  images at `.../server-slurm/images`, so the bundle store's natural sibling is
  `.../server-slurm/runtime-bundles`.
- The worker sees `SERVER_DIR`, `docker/runners`, and `images` as the same host
  paths the compute node does, so a digest-pinned host path resolves identically
  off-cluster — bundling remains the right rule regardless.
- Scope decision (user): migrate the shared helpers out of every family's Build
  Identity now; migrate Example/SimpleFold/ESMFold2 end-to-end; do not rebuild
  the fleet this session. Non-migrated families report `BUILD_STALE` honestly
  until rebuilt.
