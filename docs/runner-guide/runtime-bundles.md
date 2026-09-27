# Runtime Bundles

A Runner executes in two layers, and the split is the architecture:

> **Build the environment; mount the orchestration.**

The **SIF** is the environment: base OS, CUDA/runtime ABI, Python environment,
pinned upstream software, compiled libraries, and immutable package
dependencies. It is built by `apptainer build` from the family's `.def` and
changes only when the environment changes.

The **Runtime Bundle** is the orchestration: REvoCompute-owned executable code —
the shared runtime helpers under `common/runtime/` and each family's `run.sh`
and adapters. It is a read-only, content-addressed snapshot materialized from
the repository at deployment time and bind-mounted into the container at
`/opt/revocompute/runtime`.

External resources — databases, model weights, checkpoints — are neither. They
are operator-managed and declared in `runner.yaml` as ordinary mounts.

## Declaring an overlay

`plugin.yaml` declares the bundle's contents; nothing is inferred:

```yaml
runtime:
  image_artifact: example_v1.sif
  definition: example.def
  build_inputs: [example/requirements.lock]   # SIF inputs: the environment
  runtime_overlay:                            # mounted: the orchestration
    - common/runtime/
    - example/run.sh
    - example/analyze.py
  entrypoint: [bash, /opt/revocompute/runtime/example/run.sh]
```

Paths are repository-relative beneath the Runner tree (`docker/runners/`), and
both files and directories are allowed. Within the mounted bundle a path keeps
its repository-relative position, so `common/runtime/task_context.sh` is at
`/opt/revocompute/runtime/common/runtime/task_context.sh` in the container.

A path must not appear in both lists: one file cannot have two identities, and
Doctor rejects the overlap. If the mounted code needs a package the image does
not ship, that is an environment change — add it to a lock file in
`build_inputs` and rebuild the SIF. A Runtime Bundle is never a package manager.

## Identity

A family's **Runtime Bundle Identity** is a SHA-256 over its declared sources
only: the normalized path, the file contents, and the executable bit. Timestamps
and ownership never participate, so two checkouts of one revision on two
machines — with different umasks — agree. A family that declares no overlay has
no bundle.

Identity is family-specific. A change in `common/runtime/persistent_runner.py`
changes every family that declares it; a change in `simplefold/finalize.py`
changes SimpleFold and nothing else.

## Task pinning

The submission path resolves the family's active bundle from the deployment's
activation index and records the exact digest in the immutable `task.json`:

```json
{"runtime_bundle": {"sha256": "sha256:…", "path": "/…/runtime-bundles/sha256-…"}}
```

The Slurm adapter resolves *that* digest when it launches the allocation and
binds it read-only at `/opt/revocompute/runtime`. It never resolves `current`,
never re-reads the mutable runner tree, and fails closed if the pinned bundle is
missing. A task queued under bundle A therefore keeps executing A even when a
deployment activates B before Slurm starts it.

## Freshness

| Change | Identity | Required action |
| --- | --- | --- |
| `.def`, a dependency lock, a `build_inputs` file | Build | Rebuild the SIF, then live-test |
| A `runtime_overlay` file | Runtime Bundle | Keep the SIF; repeat the live test |
| Task execution contract, `test.yaml`, resources | Execution Contract | Keep the SIF; repeat the live test |
| Display name, summary, citation, UI hint | Presentation | Deploy only |

`runner-status` reports which one moved:

```text
SIF: CURRENT
Runtime bundle: STALE
Reason: Runtime bundle changed; reuse the current SIF and rerun the live test
Next action: reuse current SIF and rerun live-test
```

A PASS receipt binds the exact `(SIF, runtime bundle)` pair, so a receipt issued
for one bundle never authorizes another. A bundle becomes eligible for a new
submission only after its own receipt passes and the activation index is
published; candidate materialization during a live test never changes what a
queued task or the running deployment resolves.

## Storage, retention, and GC

Bundles live in a deployment-owned store — by default
`${SERVER_DIR}/../runtime-bundles`, overridable with `RUNTIME_BUNDLE_DIR`. It is
a sibling of the image store, deliberately outside `${SERVER_DIR}`, because the
Runner tree is atomically replaced on every deployment and a bundle a queued
task pinned must not be deleted with it.

Snapshots are immutable and content-addressed, so they accumulate. Pruning runs
on the deployment path only — never during execution — and retains a superseded
bundle for `RUNTIME_BUNDLE_RETENTION_DAYS` (default 14) before removing it. A
bundle that is active, prepared, or pinned by a queued or running task is never
removed; leaking an old snapshot is always preferable to deleting code a Task
still needs.

## Security

Runtime overlays are not ordinary operator mounts and are never writable or
user-configurable:

- sources are repository files only — never uploaded Task content;
- absolute paths, `..`, backslash spellings, symlinks, and duplicate
  declarations are rejected;
- the container destination is one reserved namespace,
  `/opt/revocompute/runtime`, which a `runner.yaml` mount cannot target;
- the mount is always read-only.

## Migrating a family

Move REvoCompute-owned executable files out of `%files` and `build_inputs` into
`runtime_overlay`, point the entrypoint and any in-image path default at
`/opt/revocompute/runtime/…`, and reduce `%test` to environment validity — the
CUDA/PyTorch ABI, compiled-extension imports, pinned upstream resources. Do not
import overlay modules from `%test`: they no longer exist in the image. A SIF
may still bake code that is genuinely ABI-coupled, compiled, or generated during
the build; record why next to the manifest when it does.
