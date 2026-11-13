# Reproducing a Live Runner Task

These are operator/developer techniques for reproducing a delivered runner Task
on the host when the original result tree is owned by the service account. The
goal is a local, read-only investigation of the exact inputs and runtime that
produced a result — not a change to the production Task, its snapshot, or its
permissions.

The owning contracts remain [Task Contract](../runner-guide/task-contract.md),
[Execution Model](execution-model.md), and [Test Plan](../runner-guide/test-plan.md).
This page records only the mechanics that those pages do not.

## 1. Start from the immutable Task snapshot

A Task snapshot lives under the deployment's workspace tree:

```text
<server-root>/server/workspaces/users/<user>/tasks/<task-id>/inputs/task.json
```

`task.json` is the authoritative reproduction record: role-resolved inputs with
SHA-256, parameters, and the pinned runtime bundle and image digests. Read it
before looking at any result. Do not reconstruct parameters from a log or from
memory.

The result tree is separate:

```text
<server-root>/server/results/users/<user>/tasks/<task-id>/
```

It is not an input snapshot. Never copy a repaired or re-derived file back into
either tree.

## 2. Read service-owned results through the web container

Result trees are commonly mode `700` under the service account even when the
Task workspace grants the operator a named ACL. The web container runs as that
account, so a read-only copy out is possible without changing host permissions:

```bash
docker ps --format '{{.Names}}\t{{.Image}}'
# Identify the deployment's web service from the image; the Task worker is not
# the reader, and container names vary by Compose project.
docker cp <web-container>:<absolute-result-path> <local-destination>
```

`docker cp` copies; it does not mount or modify the source. Verify the copy
against the artifact hash in `manifest.json` before using it, for example:

```bash
sha256sum <local-destination>
```

Treat this as an operator convenience on a host you already administer. It is
not an access-policy mechanism and must not be used to read another user's data
outside an authorized investigation.

## 3. Use the pinned runtime, not the current deployment

`task.json` records `runtime_images` and `runtime_bundles`. Reproduce with those
digests. Running the current default image can silently change upstream code,
dependency versions, or the adapter's behavior, which defeats the comparison.

Prefer a direct Apptainer invocation when the Task worker, API credentials, or
queue are not part of the question:

```bash
apptainer exec --nv --containall --cleanenv \
  --bind <inputs>:/workspace/inputs:ro \
  --bind <outputs>:/workspace/outputs:rw \
  <pinned-image-or-sif> <runner-command>
```

Record the exact command. The adapter's `command.txt` is the expected shape.

## 4. Reconcile representation only on a copy

A structure produced by one model is not automatically the starting structure
another model's atom-order validator accepts. Two recurring cases:

- **Sequence-built systems omit terminal `OXT`.** A full all-atom CIF that keeps
  `OXT` fails the exact atom match. Remove only the terminal `OXT` atoms on a
  copy, record the before/after SHA-256, and keep the original immutable. The
  Task contract owns the user-facing refusal rule.
- **A CIF may carry no `_struct_conn` or branched entities.** When upstream
  needs an explicit system, derive the system YAML from the source specification's
  entities (chain IDs, types, ligand codes) and record it as a separate
  provenance artifact. It does not replace the original input.

Report the reconciliation as a representation change, not as a structural edit.
Never minimize, protonate, renumber, or otherwise alter coordinates while
reconciling atom identity.

## 5. Stage offline caches Task-locally

A runner that resolves assets through a library's cache can still be offline,
but only if the cache layout is exact. For Hugging Face:

```text
$HF_HOME/hub/models--<org>--<repo>/refs/main
$HF_HOME/hub/models--<org>--<repo>/snapshots/<revision>/<asset>
```

`refs/main` contains the 40-character commit and **no trailing newline**. A
different revision string, or a newline, makes the cache miss and the lookup
fail under `HF_HUB_OFFLINE=1`. Stage the cache in Task scratch or a private
working directory; do not make the authoritative weight mount writable merely to
silence a cache lookup.

Only the stage that needs the asset should require it. See
[Runner Weights and Model Assets](../runner-guide/model-resources.md) for the
read-only mount and provisioning rules.

## 6. Verify the delivered artifacts, then state the caveats

Minimum checks after a successful run:

```text
task_finished present and empty
command.txt matches the intended parameters
topology atom count equals samples.xtc atom count
frame count equals the requested sample count
frame count × atoms matches the expected trajectory shape
lag and coordinates are finite
physicality.json reports one result per endpoint
```

Also record the resource envelope (GPU model and peak memory, CPU time, wall
time) and any upstream limitation that affected the science. Two examples that
are easy to miss:

- A ligand absent from the steering dictionary is silently skipped, not an
  error; the run remains valid but without ligand-specific constraints.
- A physicality checker may cover protein chains only; do not report its result
  as covering ligands.

Endpoints sampled at one lag are independent samples, not a time-ordered
trajectory. Keep that distinction in the reproduction report.
