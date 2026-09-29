# TODO — Immutable Runner Runtime Overlay

## Goal

Refactor REvoCompute Runner packaging so that **REvoCompute-owned executable code is not baked into Runner SIF images by default**.

A Runner SIF should primarily describe an immutable execution environment:

- base operating system;
- CUDA/runtime ABI;
- Python environment;
- pinned upstream software;
- compiled libraries;
- immutable package dependencies;
- build-time resources required by that environment.

REvoCompute orchestration and adapter code should instead be delivered through an **immutable, content-addressed, read-only runtime bundle** mounted into the Runner container at execution time.

The guiding rule is:

> **Build the environment; mount the orchestration.**

This mechanism must be generic. It must not special-case `docker/runners/common/`, SimpleFold, ESMFold2, persistent execution, or any current Runner family.

---

# 1. Preserve the architecture boundaries

The finished Runner runtime consists of three independent artifact classes:

```text
SIF
  OS / CUDA / Python / libraries / upstream package
  immutable build-time dependencies
        +
Runtime Bundle
  REvoCompute common runtime helpers
  family adapter code
  preprocessors / normalizers / finalizers
        +
External Resources
  databases / model weights / checkpoints
```

These layers have different lifecycles and must not share one freshness identity.

Do not solve this by adding `docker/runners/common` to ordinary `runner.yaml.mounts`.

`runner.yaml.mounts` represents **operator-managed external resources** such as databases and checkpoints.

The runtime bundle represents **repository-owned executable code**. It must have its own provenance, validation, task pinning, and security rules.

---

# 2. Introduce Runtime Bundle Identity

Extend the existing identity model from:

```text
Build Identity
Execution Contract Identity
Presentation Identity
```

to:

```text
Build Identity
Runtime Bundle Identity
Execution Contract Identity
Presentation Identity
```

## Build Identity

Build Identity includes only inputs required to construct the SIF:

- Apptainer `.def`;
- dependency lock/requirements files used during image construction;
- build-time patches;
- source files compiled or installed into the image;
- pinned upstream source identity where represented by local build inputs;
- other files whose contents materially alter the resulting SIF;
- Apptainer builder identity/version as currently required.

Changing Build Identity must produce:

```text
BUILD_STALE
→ rebuild SIF
→ live-test exact SIF + runtime bundle
```

## Runtime Bundle Identity

Runtime Bundle Identity covers repository-owned executable files delivered at runtime rather than stored inside the SIF.

Examples include:

```text
common runtime helpers
run.sh
persistent_runner.py
work_items.py
task_context.py
task_context.sh
verify_model_asset.sh
prepare_input.py
normalize_results.py
finalize.py
pure-Python REvoCompute adapters
```

Changing Runtime Bundle Identity must produce:

```text
SIF remains current
→ validation receipt becomes stale
→ VALIDATION_STALE
→ live-test exact SIF + new runtime bundle
```

Do **not** add a new top-level `RUNTIME_STALE` readiness state unless implementation demonstrates a real operational need.

Expose the reason structurally, for example:

```json
{
  "state": "VALIDATION_STALE",
  "reason": "runtime_bundle_changed"
}
```

## Execution Contract Identity

Continue to cover execution-affecting configuration not contained in the runtime bundle:

- task execution schema;
- parameter/input/output semantics;
- runner configuration;
- effective resource configuration;
- adaptation policy;
- expected-file acceptance;
- live-test declaration and relevant fixtures;
- runtime invocation contract.

Changing it keeps the SIF but invalidates validation.

## Presentation Identity

Continue to exclude labels, descriptions, citations, UI hints and other presentation-only data from rebuild and live-test requirements.

---

# 3. Add a generic `runtime_overlay` manifest contract

Extend the Runner plugin schema with a generic runtime-overlay declaration.

The exact final schema may be adjusted during implementation, but the semantic model should resemble:

```yaml
runtime:
  image_artifact: simplefold_v1.sif
  definition: simplefold.def

  build_inputs:
    - simplefold/requirements.lock

  runtime_overlay:
    paths:
      - common/runtime/
      - simplefold/run.sh
      - simplefold/offline_predict.py
      - simplefold/finalize.py

  entrypoint:
    - bash
    - /opt/revocompute/runtime/simplefold/run.sh
```

Requirements:

- support both files and directories;
- paths are repository-relative beneath the Runner tree;
- preserve a deterministic relative path inside the materialized bundle;
- no absolute source path;
- no `..`;
- no backslash/path spelling ambiguity;
- no symlink escape;
- no duplicate normalized source;
- no destination collision;
- runtime-overlay sources must not be user-controlled;
- runtime-overlay mounts must always be read-only;
- the container destination must use one reserved REvoCompute namespace.

Prefer one fixed container root, for example:

```text
/opt/revocompute/runtime/
```

Do not expose arbitrary container mount destinations unless a demonstrated Runner requirement makes them necessary.

---

# 4. Separate executable `common` content from server-only `common`

Do not mount all of `docker/runners/common/` blindly.

That directory currently mixes different semantic layers.

Create a clear runtime subtree, for example:

```text
docker/runners/common/
├── runtime/
│   ├── persistent_runner.py
│   ├── work_items.py
│   ├── task_context.py
│   ├── task_context.sh
│   └── verify_model_asset.sh
└── policy/
    └── ...
```

Only executable code actually needed inside Runner containers belongs under `common/runtime/`.

Access policies, deployment metadata, documentation and other server-side files must not enter the runtime bundle merely because they share `common/`.

Update imports/source paths consistently.

Do not introduce compatibility copies that cause the same helper to exist permanently in two locations.

---

# 5. Materialize immutable content-addressed bundles

Never execute directly from:

```text
git checkout
SERVER_DIR/docker/runners/current
a mutable common directory
```

A running or queued task must never observe files changing beneath it.

Materialize Runtime Overlay declarations into immutable content-addressed snapshots.

Use a storage layout conceptually similar to:

```text
<deployment-artifact-root>/
└── runtime-bundles/
    ├── sha256-aaaaaaaa.../
    ├── sha256-bbbbbbbb.../
    └── ...
```

Do not store these bundles inside a directory that is atomically deleted/replaced when `materialize_runner_families()` installs a new server snapshot.

A reasonable default location is a deployment-owned sibling of the SIF/image store.

The location itself is implementation detail; the **digest**, not the path, is identity.

---

# 6. Define deterministic bundle hashing

Runtime Bundle Identity must be reproducible across machines and deployments.

For every declared source:

1. resolve beneath the Runner tree;
2. reject symlinks unless a later explicit contract safely defines them;
3. recursively enumerate directories;
4. sort by normalized POSIX relative path;
5. require regular files/directories only;
6. hash path + file contents + execution-relevant mode;
7. ignore mtime, uid, gid and other host-specific metadata.

At minimum, the executable bit must participate in identity.

Materialized permissions should be normalized, for example:

```text
directories: 0555
ordinary files: 0444
executable files: 0555
```

The runtime bundle itself is always mounted read-only.

Do not hash filesystem timestamps.

Do not let deployment umask change Runtime Bundle Identity.

---

# 7. Make Runtime Bundle Identity family-specific

Physical snapshots may deduplicate shared content, but Runner provenance must remain family-specific.

A change in:

```text
common/runtime/persistent_runner.py
```

should invalidate every family declaring that path.

A change in:

```text
simplefold/finalize.py
```

must not invalidate ESMFold2.

Compute each family's Runtime Bundle Identity from **only the overlay sources declared by that family**.

Do not hash the complete `docker/runners/` tree.

Do not hash unrelated files merely because they happen to share a directory.

---

# 8. Pin the bundle at task submission

This is a correctness requirement.

A queued Task submitted under runtime bundle `A` must continue to execute bundle `A`, even if deployment activates bundle `B` before Slurm starts the task.

Capture the exact runtime-bundle digest in the existing immutable task/execution snapshot.

Prefer extending the existing task execution envelope rather than adding another mutable lookup or database column.

Conceptually:

```json
{
  "runner_family": "simplefold",
  "sif_sha256": "...",
  "runtime_bundle_sha256": "...",
  "execution_contract_sha256": "..."
}
```

The worker must resolve the content-addressed directory from this digest.

Never resolve `latest` or `current` when launching the scientific allocation.

Fail closed if the referenced bundle is missing.

---

# 9. Bind the exact bundle into Apptainer

Extend the Slurm/Apptainer execution path so each job receives the pinned runtime bundle:

```text
apptainer exec
  --bind <bundle-path>:/opt/revocompute/runtime:ro
  ...
  <runner.sif>
```

The exact syntax should use the existing safe argument construction rather than shell interpolation.

The runtime mount must:

- be read-only;
- use a reserved target;
- reject collision with task workspace mounts;
- reject collision with database/checkpoint mounts;
- never be configurable by the user;
- never come from uploaded Task content;
- resolve to the digest-pinned bundle before submission.

Audit every path normalization step before passing values to Apptainer.

---

# 10. Keep Runner dependencies inside the SIF

Runtime Overlay does **not** make SIFs unnecessary.

Mounted Python/shell code may only depend on packages and libraries supplied by the SIF or Python standard library.

For example:

```text
finalize.py gains `import pandas`
```

when pandas is not present in the image means:

```text
requirements.lock changes
→ Build Identity changes
→ rebuild SIF
```

Do not dynamically install packages into runtime bundles.

Do not use runtime-overlay mounting as an implicit package manager.

Keep pinned upstream scientific runtimes inside the SIF when they are installed, compiled, ABI-sensitive, or otherwise part of the environment.

The intended distinction is:

```text
environment/upstream runtime → SIF
REvoCompute orchestration/adapter → Runtime Bundle
weights/databases → External Resources
```

---

# 11. Refactor `.def` files

Remove runtime-overlay files from `%files`.

For example, SimpleFold should eventually stop baking:

```text
simplefold/run.sh
simplefold/offline_predict.py
simplefold/finalize.py
common/persistent_runner.py
common/work_items.py
common/task_context.sh
common/task_context.py
```

into `/app/revocompute/`.

Its SIF should primarily install:

```text
CUDA runtime
Python environment
PyTorch
SimpleFold pinned source
ESM pinned source
OpenFold pinned source
dependency lock
```

Create the reserved runtime mount point during image construction if Apptainer requires it:

```text
/opt/revocompute/runtime
```

Change `%test` to test **environment validity**, not REvoCompute overlay modules.

Good SIF tests include:

```text
import torch
import upstream package
CUDA/PyTorch ABI checks
compiled-extension imports
required static upstream resource checks
```

Do not make SIF `%test` import `persistent_runner`, `work_items`, family adapters or other code that will no longer exist inside the image.

Those belong to runtime/live validation.

---

# 12. Update build provenance

Modify current build-provenance calculation in `run/revocompute_ctl/registry.py`.

`build_provenance_digest` must stop including runtime-overlay files.

A Runtime Overlay path must not simultaneously participate in:

```text
runtime.build_inputs
runtime.runtime_overlay
```

Reject this in Doctor/plugin validation.

Preserve current legacy build-evidence migration only where it remains safe.

Do not silently mark old SIF evidence current when the old image materially differs from the new environment contract.

Document the migration boundary.

---

# 13. Add runtime-bundle provenance to live-test receipts

A PASS receipt must bind together at least:

```text
runner family
SIF SHA-256
Build Identity digest
Runtime Bundle digest
Execution Contract / validation digest
test-plan digest
resource snapshots
relevant configured runtime identity
```

Live testing must exercise the **exact candidate bundle** that will later be activated.

A receipt produced against:

```text
SIF A + Runtime Bundle X
```

must not authorize:

```text
SIF A + Runtime Bundle Y
```

Prepared deployment must fail closed when those differ.

---

# 14. Do not hot-reload executable runtime code

Mounting code does not mean live mutation.

A deployment change should produce:

```text
source tree
→ materialize immutable bundle B
→ live-test B
→ receive PASS receipt
→ activate B for new submissions
```

Existing queued/running tasks pinned to A continue to use A.

Do not overwrite A.

Do not point running tasks at a mutable `current` symlink.

If an operator-facing `current` pointer is useful for inspection, it must never be the task execution identity.

---

# 15. Handle runtime-bundle garbage collection safely

Content-addressed snapshots will accumulate.

Add conservative GC rules.

Never delete a bundle that is:

- active for new submissions;
- a prepared candidate;
- referenced by a queued task;
- referenced by a running task;
- being used by a live test;
- within a deployment rollback/retention window.

Historical receipts may retain the bundle digest after bundle bytes are pruned, provided audit semantics remain clear.

Prefer leaking old small bundles temporarily over deleting executable code still referenced by a Task.

Do not make GC part of the critical execution path.

---

# 16. Preserve atomic deployment semantics

Integrate Runtime Bundle materialization with the existing prepared-deployment workflow.

Candidate creation must not mutate the currently active runtime tree.

Conceptually:

```text
materialize candidate bundle
→ validate
→ live-test exact bundle
→ stop/activate prepared deployment
→ make new bundle eligible for new Tasks
```

Any failure before activation leaves the current deployment unchanged.

The runtime-bundle implementation must preserve the existing maintenance/rollback guarantees.

---

# 17. Update readiness without expanding the state machine unnecessarily

Keep the existing operator-level readiness vocabulary where possible:

```text
NOT_CONFIGURED
NOT_BUILT
BUILD_STALE
NOT_VALIDATED
VALIDATION_STALE
READY
```

Examples:

```text
requirements.lock changed
→ BUILD_STALE

persistent_runner.py changed
→ VALIDATION_STALE
  reason=runtime_bundle_changed

task execution schema changed
→ VALIDATION_STALE
  reason=execution_contract_changed

label changed
→ READY
```

Expose component identities/reasons in `runner-status --json`.

Human-readable `runner-status` should make the required action obvious:

```text
SIF: CURRENT
Runtime bundle: STALE
Validation: STALE
Action: reuse current SIF and rerun live-test
```

---

# 18. Extend Doctor and manifest validation

Doctor must detect:

- invalid runtime-overlay schema;
- unsafe source paths;
- symlinks;
- duplicate paths;
- unavailable sources;
- path traversal;
- source outside Runner root;
- runtime-overlay/build-input overlap;
- reserved mount-target collision;
- invalid entrypoint path;
- runtime entrypoint absent from either SIF contract or runtime bundle;
- directories containing unsupported filesystem objects.

Do not automatically infer overlay dependencies by parsing imports.

The explicit manifest remains the reviewable contract.

---

# 19. Make Example Runner canonical again

Update `docker/runners/example/` first.

It should demonstrate the final architecture clearly.

Example Runner should contain:

```text
plugin.yaml
example.def
runtime adapter code
task manifest
test.yaml
README
```

Its SIF should contain only the execution environment.

Its REvoCompute adapter should execute exclusively from Runtime Overlay.

Document in the Example README:

```text
change .def / dependency → rebuild
change runtime adapter → no rebuild, revalidate
change task execution contract → no rebuild, revalidate
change presentation → neither
```

Use the Example Runner as the canonical developer reference after the migration.

---

# 20. Migrate PR #30 families

After Example passes, migrate:

```text
ESMFold2
SimpleFold
```

Move/remove from SIF Build Identity:

```text
common/persistent_runner.py
common/work_items.py
common/task_context.*
family run.sh where safe
family pure-Python adapters where safe
finalizers/normalizers where safe
```

Keep in SIF:

```text
requirements locks
upstream packages
CUDA/PyTorch environment
compiled/install-time sources
dependency artifacts
```

Verify persistent multi-input execution is behaviorally unchanged.

Verify OOM recovery semantics are unchanged.

Verify runtime identity/model identity semantics from PR #30 remain unchanged.

This PR must be a packaging/deployment refactor, not a resource-adaptation redesign.

---

# 21. Audit every existing Runner

Search all Runner definitions and plugin manifests for:

```text
common/task_context.*
common/verify_model_asset.sh
common/persistent_runner.py
common/work_items.py
/app/revocompute/*.py
/app/revocompute/*.sh
runtime.build_inputs
%files
```

Classify every baked local file as:

```text
ENVIRONMENT_BUILD_INPUT
RUNTIME_OVERLAY
REQUIRES_EXPLICIT_EXCEPTION
```

Migrate all shared `common/runtime` helpers out of SIFs.

This is required to gain the main benefit: a shared helper edit must not make dozens of SIFs `BUILD_STALE`.

Family-specific adapter code may be migrated in the same PR where mechanical and safe. If a family-specific file remains baked in, record why.

No silent exceptions.

---

# 22. Add an explicit exception rule

The default rule is:

> REvoCompute-owned Python/shell execution code belongs in Runtime Overlay.

Allow baking such code into a SIF only when there is a concrete reason, such as:

- code generation during image build;
- compilation;
- ABI coupling;
- install-time transformation;
- upstream package installation semantics;
- runtime cannot safely consume it from a read-only mount.

Document the reason close to the manifest/definition.

Do not allow “it was already copied there” as an exception.

---

# 23. Update testing

Add focused tests proving identity behavior.

At minimum:

### Hashing

- identical source content produces identical bundle digest;
- file ordering does not matter;
- mtime does not affect digest;
- uid/gid do not affect digest;
- content change changes digest;
- executable-bit change changes digest;
- symlinks are rejected;
- traversal is rejected.

### Freshness

- `.def` change → `BUILD_STALE`;
- requirements lock change → `BUILD_STALE`;
- `common/runtime/persistent_runner.py` change → SIF remains current + `VALIDATION_STALE`;
- family adapter change → SIF remains current + `VALIDATION_STALE`;
- execution contract change → `VALIDATION_STALE`;
- presentation change → remains `READY`.

### Task pinning

Prove:

```text
Task A submitted under bundle X
bundle Y activated
Task A still launches X
new Task B launches Y
```

### Receipt correctness

- receipt for bundle X rejects bundle Y;
- receipt for SIF A rejects SIF B;
- old runtime receipt cannot authorize new runtime code.

### Runtime launch

- Apptainer receives the exact digest-pinned source;
- bind is read-only;
- bind target is reserved;
- missing bundle fails closed;
- ordinary runner mounts cannot replace runtime-overlay destination.

### Lifecycle

- current bundle survives candidate creation;
- failed candidate validation does not alter active bundle;
- GC does not remove a referenced bundle.

---

# 24. Run live acceptance

After unit/integration tests pass, perform real target-host acceptance.

At minimum run:

```text
Example        CPU reference
SimpleFold     GPU + persistent execution
ESMFold2       GPU + persistent execution
```

For each family prove:

```text
existing SIF reused after runtime-code-only change
new runtime bundle materialized
runner-status reports VALIDATION_STALE, not BUILD_STALE
live-test runs exact SIF + bundle digest
PASS receipt records both identities
prepared activation succeeds
runner-status becomes READY
```

Then deliberately make a dependency/build change and prove:

```text
BUILD_STALE
```

still works.

---

# 25. Verify no scientific behavior changes

For migrated families compare before/after:

- commands presented to upstream software;
- parameters;
- environment variables;
- mounted model/database paths;
- output layout;
- result normalization;
- resource requests;
- persistent-execution semantics;
- random seeds;
- scientific artifacts.

Runtime Overlay is a packaging and provenance change.

Do not opportunistically rewrite scientific adapters while migrating them.

---

# 26. Update documentation

Update at minimum:

```text
docker/runners/README.md
docs/runner-guide/adding-a-runner.md
docs/runner-guide/runner-family-protocol.md
docs/runner-guide/plugin-manifest.md
docs/operator-guide/runner-configuration.md
docs/operator-guide/slurm-deployment.md
docs/operator-guide/deployment-control.md
Example Runner README
```

Replace the old rule:

> every executable local file copied into the SIF belongs in `build_inputs`

with the stronger classification:

> first decide whether the file belongs in the SIF at all.

Document:

```text
Build the environment; mount the orchestration.
```

Explain Runtime Bundle Identity and immutable task pinning.

Make clear that runtime overlays are not ordinary operator mounts and are never writable/user-configurable.

---

# 27. Remove obsolete assumptions

Search documentation, comments, tests and Runner code for assumptions such as:

```text
"Copied next to run.sh in every runner image"
"/app/revocompute/task_context.sh"
shared helper == build input
common == build-time input
```

Update or remove them.

Avoid compatibility shims that preserve both baked and mounted copies indefinitely.

After migration, one source must be authoritative.

---

# 28. Acceptance criteria

This work is complete only when all of the following hold:

- REvoCompute-owned shared runtime code can change without rebuilding unaffected SIFs.
- `common/runtime` is mounted from an immutable content-addressed snapshot.
- The mechanism supports arbitrary future repository-owned runtime-overlay paths and is not hard-coded to `common`.
- Tasks pin their exact runtime-bundle digest at submission.
- Running/queued tasks cannot switch bundles during deployment.
- SIF Build Identity excludes runtime-overlay code.
- Runtime Bundle Identity is included in live-test receipts and provenance.
- Runtime-bundle changes yield `VALIDATION_STALE`, not `BUILD_STALE`.
- Dependency/environment changes still yield `BUILD_STALE`.
- Runtime overlays are read-only and cannot be supplied or altered by users.
- Example, SimpleFold and ESMFold2 pass target-host live acceptance.
- Every existing Runner using shared `common` executable helpers has been audited and migrated or carries an explicit justified exception.
- Full non-browser tests pass.
- Documentation builds with `mkdocs build --strict`.
- Changed shell scripts pass syntax/static checks.
- No scientific output or parameter semantics change as part of this refactor.

---

# 29. Scope control

Do not combine this work with:

- new Runner integration;
- new OOM-estimator behavior;
- new batching semantics;
- scientific algorithm changes;
- UI redesign;
- database/weight relocation;
- Jupyter/workspace support.

Keep this PR focused on **Runner packaging, immutable runtime delivery, identity, provenance and freshness**.

The desired end state is simple:

```text
Change CUDA/PyTorch/upstream/dependency
→ rebuild SIF

Change REvoCompute Runner code
→ create new runtime bundle
→ reuse SIF
→ live-test

Change task execution contract
→ reuse SIF
→ live-test

Change presentation
→ deploy only
```