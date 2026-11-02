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
  build_inputs: []                            # SIF inputs: the environment
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

`build_inputs` is an inventory of environment files, not a required non-empty
field: the `.def` and the recorded builder already form the build identity, so a
family with no other declared input writes `build_inputs: []` (AlphaFold 3
does). The field is never removed from the schema.

A path must not appear in both lists: one file cannot have two identities, and
Doctor rejects the overlap. Containment counts, not just an exact spelling — an
overlay directory claims every file beneath it, so a lock file inside a declared
overlay directory cannot also be a build input. If the mounted code needs a
package the image does not ship, that is an environment change — add it to a
lock file in `build_inputs` and rebuild the SIF. A Runtime Bundle is never a
package manager.

### Entrypoint resolution

A migrated family's entrypoint must resolve an overlay-delivered executable
under the reserved mount:
`/opt/revocompute/runtime/<repository-relative path>`. If the entrypoint names
a path that maps into the overlay namespace, that file must be declared in the
same overlay. Any other spelling of an overlay-delivered executable — a legacy
`/app/revocompute/<file>`, a different absolute path, a relative path, or a
shell-wrapped word — is refused when the overlay delivers that executable (same
repository-relative path or basename), because it would start baked or missing
code while the bundle identity claims the snapshot ran. A family that declares
its own `<source-directory>/run.sh` must start that exact mount path: another
executable, or a wrapper that only passes the declared script as an argument,
is refused. The accepted forms are the mount path as the command, a shell word
followed by the mount path, `env` assignments then a shell word and the mount
path, and `<shell> -c 'exec <mount>'`. Interpreter and `env` options are refused
rather than parsed, so spell the script directly. An entrypoint that does not name overlay content — an unmigrated
family whose overlay carries only shared helpers, or an executable that
genuinely belongs to the image — is accepted unchanged.

Doctor and the registry apply this rule during validation, so a half-migrated
manifest fails before deployment rather than at launch.

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

The submission path resolves each referenced family's active bundle from the
deployment's activation index and records the exact digests in the immutable
`task.json`, keyed by family:

```json
{"runtime_bundles": {"gremlin": "sha256:…", "simplefold": "sha256:…"}}
```

A single-family Task records one entry. A stage dispatched in a family resolves
that family's digest from the map.

The digest is the identity; the store directory is derived from it, so a
relocated bundle store cannot leave a stale path inside a pinned task. The Slurm
adapter resolves *that* digest when it launches the allocation and binds the
resulting directory read-only at `/opt/revocompute/runtime`. It never resolves
`current`, never re-reads the mutable runner tree, and fails closed if the pinned
bundle is missing or if a family that declares an overlay was submitted without
one. A task queued under bundle A therefore keeps executing A even when a
deployment activates B before Slurm starts it.

## Change impact

The four identity classes are owned by
[Runner Family Protocol](runner-family-protocol.md#identity-classes). This is
the detailed change list:

| Change | Rebuild SIF | Re-run live-test |
| --- | ---: | ---: |
| Apptainer `.def` | Yes | Yes |
| Requirements or lockfile copied into the image | Yes | Yes |
| Family code still copied into the image | Yes | Yes |
| `runtime.runtime_overlay` path (shared helper or family adapter) | No | Yes |
| Task argument forwarding or execution-affecting default | No | Yes |
| Task input/output execution contract | No | Yes |
| Result-view source selectors or acceptance-relevant mapping | No | Yes |
| `expected_files.yaml` logical-output contract | No | Yes |
| Which directory owns a Task's result contract (its `expected_files.yaml` and `storyboard/`) | No | Yes |
| Runtime entrypoint declaration or `runner.yaml` mounts/env/limits | No | Yes |
| Effective resource policy | No | Yes |
| Access-policy identification or entitlement requirement | No | Yes |
| Runner-owned input-workspace module, styles, schema, backend module, or backend role binding | No | Yes |
| `test.yaml` case, fixture, or required coverage | No | Yes |
| Display name, summary, `use_when`, or help text | No | No |
| Citation or documentation link | No | No |
| Result-view titles, labels, units, scales, or axis hints | No | No |
| UI, layout, viewer, or category hint | No | No |
| `family.version` release metadata alone | No | No |

Runner-owned workspace assets are server-side executable code, not image
content: they are loaded from the Runner tree at request time and are absent
from the SIF. They therefore follow the execution-contract row, while only
files copied into the image belong in Build Identity.

`common/runtime/` is shared code: 41 of the 43 shipped families declare it in
`runtime_overlay`. Editing any file under `common/runtime/` changes the Runtime
Bundle digest of all 41 families and invalidates their receipts, far beyond the
family the edit appears to touch. Plan a shared-helper change as a fleet
revalidation, not a single-family update.

`family.version` identifies the family release for display and audit. It is not
an automatic build or validation input. If image construction consumes a
version value, the file or recipe that supplies that value must participate in
Build Identity; changing that actual input then drives the rebuild.

For each new file or field, ask in order:

1. Is it REvoCompute-owned executable code the container runs? Put it in
   `runtime.runtime_overlay` — the SIF keeps the environment, the bundle
   supplies the orchestration.
2. Can changing it alter SIF contents or other code baked into the SIF? Put the
   file in `runtime.build_inputs`.
3. Can changing it alter how Core invokes, validates, resources, or accepts the
   computation? It belongs to Execution Contract Identity.
4. Can changing it only alter what a user sees? It belongs to Presentation
   Identity.

Freshness is evaluated before activation. Readiness compares the digest of the
checked-out overlay sources with the digest the activation index publishes, so
an edit to a declared `runtime_overlay` source is stale even when no deployment
has run since the edit. `runner-status` reports which identity moved:

```text
Build provenance: CURRENT
Runtime bundle: STALE
Reason: Runtime bundle changed; reuse the current SIF and rerun the live test
Next action: reuse current SIF and rerun live-test
```

The status is `VALIDATION_STALE` with `reason=RUNTIME_BUNDLE_CHANGED`. A family
that declares an overlay but has no published binding is never `READY`: a new
submission has no digest to pin. Readiness and submission refuse that family
until a receipt authorizes a binding.

A PASS receipt binds the exact `(SIF, runtime bundle)` pair, so a receipt issued
for one bundle never authorizes another.

## Activation

Candidate materialization and activation are separate. `live-test` snapshots
the candidate overlay without publishing it, so a test can pin the exact digest
it will validate while queued tasks and the running deployment keep resolving
the prior binding.

Activation is receipt-gated. `setup` and `restart` publish a *changed* binding
only when a valid live-test receipt covers that exact family, bundle digest, SIF
build provenance, configuration, and test definition. Without one they keep the
prior binding and the family reads stale; a failed live test never activates
anything. The normal path is the live-test's own post-PASS activation: once
every selected family's required cases pass, it publishes exactly the digests
that were validated, never a freshly recomputed digest, so a source edit
between validation and activation cannot bind code the receipt did not cover.

Composed acceptance binds the companion identities it actually ran: when
families are selected in the same live-test pass, the receipt records their
candidate bundle digests, while an unselected companion keeps its published
digest (together with its SIF and build provenance). A later companion identity
change invalidates the composed receipt, and a missing companion record refuses
before submission rather than running an unproven stage input.

## Rolling back

Rollback is an activation-index switch to an earlier immutable, already accepted
snapshot — never a rebuild, rewrite, or prune:

```bash
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh rollback-bundle \
  --runner <family> --digest <sha256:...>
```

The target must still verify as a materialized snapshot and a valid live-test
receipt must authorize that family and digest for the active SIF, build
provenance, configuration, and test definition. Any refusal leaves the index
byte-identical and has no side effects; both the superseded and restored
snapshots remain available. See
[Deployment Control commands](../operator-guide/deployment-control.md#commands).

Rollback is durable. The controller records the choice as a per-family rollback
hold in the bundle store (`rollback.json`), so a later `setup` or `restart`
keeps the held digest active instead of re-materializing the newer checkout and
silently undoing the rollback. A successful full live-test PASS is the explicit
forward move: it clears the hold and activates the validated digest. A failed
live test leaves the hold untouched. A held digest whose snapshot is missing or
no longer verifies fails closed; a hold never bypasses snapshot or receipt
checks. An unreadable or malformed `rollback.json` also fails deployment closed
rather than silently dropping the operator's intent. Readiness validates the
held pair and reports READY or stale from its receipt rather than
`RUNTIME_BUNDLE_CHANGED` merely because the checkout has newer sources.

## SIF builds, worker images, and promotion

A scientific SIF build and a one-off Docker server/worker image build are
different events with different identities. The worker image is the deployment
orchestration boundary for a live test; building it is not a SIF rebuild and
does not authorize one. `prepare --build-sif` and `restart --build-sif` stage a
candidate, and `live-test` builds a missing or stale candidate before validating
it. Every path stages `<artifact>.next` without activating it. A later
`restart --mode=prepared` is the only SIF promotion path, and it is
maintainer-authorized; a candidate never replaces the active SIF because it
built or passed a test.

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
