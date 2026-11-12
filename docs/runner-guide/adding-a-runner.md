# Adding a Runner

This is the walkthrough. [Runner Family Protocol](runner-family-protocol.md)
owns the normative lifecycle and release gate; the linked pages own their
fields.

Use the CPU-only `docker/runners/example/` family as the structural reference
for a conventional Runner. It is a complete,
fast path through plugin discovery, named inputs, Task parameters, execution,
artifact acceptance, Result Workspace views, and a ResultStoryboard without
weights, databases, network access, or a GPU.

## Classify the change

Classify every changed Runner file or manifest field before building or
deploying it. The four identity classes are owned by
[Runner Family Protocol](runner-family-protocol.md#identity-classes), and the
detailed per-file change list is owned by
[Runtime Bundles](runtime-bundles.md#change-impact). The table is not repeated
here.

## 1. Copy the Example Runner

Copy `docker/runners/example/` to `docker/runners/<family>/`. Rename the
definition file and replace every `example` family identity. Do not keep fields
whose semantics do not apply to the new runtime.

Before implementation, record:

- upstream repository and full pinned revision;
- software, model, and data licenses;
- official command-line usage example;
- expected named inputs and scientific outputs;
- weights or database requirements;
- CPU, GPU, host-memory, GPU-memory, walltime, and network requirements;
- one canonical, minimal scientific test case.

These are the minimum facts an AI coding agent must establish from primary
sources and present for review. A README alone is not sufficient evidence for
scientific behavior; do not invent undocumented modes or dependency versions.

### Review upstream capabilities before adapting

Read the publication and supplement where relevant, the **exact pinned**
revision, its CLI/API help, examples, tests, release notes, and model
documentation. Keep four evidence levels distinct: what the paper claims, what
the pinned implementation can execute, what a newer release adds, and what a
real run on the target host produced. Cite a revision-specific URL, path, or
line reference for each user-relevant scientific operation.

For each operation, establish its accepted inputs, scientific mode,
prerequisites, parameters that change the experiment, produced artifacts, and
observed evidence. Compare that with the family's registered Task(s) and
classify it as **exposed and verified**, **implemented but hidden**,
**missing**, **intentionally excluded**, **unavailable at the pinned
version**, **unverified**, or **broken**. Give every operation that is not
exposed and verified a scientific, security, licensing, resource, or
maintenance reason. A CLI switch is not automatically a scientific operation.

Operations with the same scientific meaning may share one `task.yaml` with
validated parameters and conditional inputs; operations with different
required input roles or outputs need their own Task in the same family. Keep
the mapping in the owning family; [Runner Family Protocol](runner-family-protocol.md#ownership)
owns the Core boundary and [Task Contract](task-contract.md) owns the manifest.

For example, suppose the pinned upstream writes `predictions/<id>/scores.json`
beside its structures, but the Task's `expected_files.yaml` matches only
`predictions/**/*.cif`. The pinned code produces the scores, but the Task
neither declares nor exposes them, so they are **implemented but hidden**.
Read the output code to establish what the file contains, decide whether it
carries scientific meaning, then either declare a result role and a smoke
assertion for it or record why it is **intentionally excluded**. Apply the
same check to a parameter: a flag the pinned CLI accepts but the Task never
exposes is also **implemented but hidden**.

Keep a durable investigation in the family `README.md` or
`SCIENTIFIC_TRACEABILITY.md`; otherwise record it in the PR discussion.
[Scientific traceability](index.md#scientific-traceability) owns that record
pattern, and [Test Plan](test-plan.md#scientific-mode-coverage) owns the
evidence that turns a classification into verified.

### Check versions before upgrading

Compare the commit or release the runtime actually deploys with the latest
official **stable** release, not an assumed latest branch. Read intervening
release notes and breaking changes, and check weights, databases, terms,
Python/CUDA/ABI dependencies, output schemas, API behavior, and target-host
resources. Reconcile any `upstream.json` with the actual build inputs; a tag,
package version, checkpoint, and SIF are distinct identities.

An available release is a candidate, not a mandate. Record **upgrade now**,
**retain**, **blocked**, or **defer**, with the reason, for every reviewed
release. Upgrade only when a useful, supportable change is shown with
compatible resources, real execution, and scientific result evidence;
otherwise preserve the pin and state what evidence would reopen the decision.
Every such change still follows the existing change-impact and target-host
acceptance gates.

## 2. Define `plugin.yaml`

Set a stable family ID and version. Declare the direct Apptainer definition,
image artifact, every local build input, the runtime entrypoint, the runtime
overlay, and each Task manifest. Pin all upstream source revisions and
dependency inputs used by the definition. See [Plugin Manifest](plugin-manifest.md).

Separate the two executable lists deliberately:

- `runtime.build_inputs` names what the SIF *installs* — dependency locks,
  patches, and sources baked into the image. Changing one means the environment
  changed, so the SIF must be rebuilt.
- `runtime.runtime_overlay` names REvoCompute-owned executable code the
  container *mounts* — shared helpers and family adapters. Changing one means
  the orchestration changed, so the SIF stays current. See
  [Runtime Bundles](runtime-bundles.md).

Copy the Example Runner, whose SIF is a bare Python base image with a reserved
mount point and no REvoCompute code at all.

`runtime.build_inputs` is a correctness boundary, not an inventory of convenient
files. It must name every mutable repository file whose content is copied into,
imported by, executed from, or otherwise materially affects the SIF, unless the
content is already captured by the definition or another declared immutable
digest. Paths must be unique regular files within the Runner tree. Do not add
unrelated files just because they share the directory, and do not rely on an
automatic dependency scanner; the explicit list is the reviewable contract.

An omitted executable input is dangerous. If `predict.py` stays baked into the
image but is absent from `build_inputs`, editing it leaves build provenance
unchanged, so an old SIF can be reported as current and continue running old
scientific code. Review `%files`, install/copy commands, imported local modules,
patches, and generated helpers against the list before building. Better: stop
baking it at all and declare it as a runtime overlay.

Create a new family when ABI, accelerator, license, or dependency isolation
requires it. Do not add the family to a Core registry; production discovers the
family from its plugin manifest.

## 3. Define `task.yaml`

Treat the owning Task manifest as the complete scientific API. Declare every
input as a named role with a stable role ID, logical type, accepted formats, and
cardinality. Declare every user-facing parameter with Draft 2020-12 JSON Schema,
including its description, type, constraints, and default or required status.
See [Task Contract](task-contract.md).

The server projects this contract through the Task APIs and resolves defaults
once. Do not repeat parameter defaults or help text in `runner.yaml`, shell
scripts, frontend code, adapters, tests, or documentation.

Declare `requires_network: true` if any code path the Task can take — with
server-validated defaults, not only when a user opts in — reaches the network.
The declaration is enforced, not advisory: a Task that does not declare it runs
with no network namespace at all, so the default is that an undeclared
download fails rather than silently succeeding. Understating the capability
both mispresents the Task in the type API and the submission UI and breaks the
running Task.

The declaration grants reachability; it does not provision assets. Every
external file a runtime path loads must be mounted and verified, or fetched
through a bounded, classified retry. A process-level offline flag is a
guarantee only when its cache already contains the asset. An implicit asset
that is missing otherwise fails after expensive setup, or silently disables a
feature. Make the dependency explicit and exercise the path in the family's
smoke plan; see [Test Plan](test-plan.md#scientific-mode-coverage).

## 4. Implement `run.sh`

Resolve inputs by role with `task_input` or `task_inputs`, and read resolved
parameters with `_parse_param`. Keep immutable inputs read-only and write every
generated file beneath the supplied output directory. Emit declared
`REVODESIGN_STAGE:<id>` markers around meaningful execution phases.

Scientific parsing, preparation, and output semantics stay in the family.
Security preflight stays in Core, and the Runner must not introduce a second
upload-acceptance path.

When one Task can contain many independent work items — several records in one
FASTA, for example — the family drives the shared persistent lifecycle instead
of a single-shot script. Call `execute_task` from
`common/runtime/persistent_runner.py` with a plugin that loads the runtime once,
executes one work item per record, and commits each item into its own
directory; see [Persistent Execution](persistent-execution.md) and copy the
Example Runner. The shared module reaches the container through
`runtime.runtime_overlay`, not through the image.

Declare Result Workspace views in `task.yaml`. Add `expected_files.yaml` and a
`storyboard/` only when the results benefit from stable logical
file identities or task-specific composition. Storyboards receive only
manifest-approved artifacts and should delegate file rendering to server
services. Register a view that presents structures through the declared
confidence metadata rather than a filename heuristic; see
[Structure Presentation Contract](structure-presentation.md).

### Where a Task's result contract lives

A Task's result contract is owned by exactly one directory, and that directory
is decided by what the Task's own deployment directory ships — never by the
shape, name, or count of any published result file:

```text
docker/runners/<family>/expected_files.yaml                    family-scoped contract
docker/runners/<family>/storyboard/                            family-scoped Storyboard
docker/runners/<family>/tasks/<task-id>/expected_files.yaml    Task-scoped contract
docker/runners/<family>/tasks/<task-id>/storyboard/            Task-scoped Storyboard
```

A Task whose own `tasks/<task-id>/` directory ships an `expected_files.yaml` is
resolved **entirely** from that directory, its Storyboard included. Every other
Task — one that ships no `expected_files.yaml` of its own — is resolved from the
family root. A Task never takes its logical files from one directory and its
Storyboard from another, and a family-scoped Storyboard is never applied to a
Task that declares its own tree. A task directory that ships a `storyboard/`
without its own `expected_files.yaml` is a contract error, not a fallback:
Storyboard assets are deployment-controlled trusted code that must be declared
beside the tree they present.

Use the **family scope** while every Task in the family publishes the same
output tree, and move one Task to its **own scope** when its outputs diverge —
that is the whole migration:

```bash
git mv docker/runners/<family>/expected_files.yaml docker/runners/<family>/tasks/<task-id>/
git mv docker/runners/<family>/storyboard          docker/runners/<family>/tasks/<task-id>/
```

A family may therefore mix scopes: `docker/runners/foundry/` keeps its
family-scoped fold contract while
`docker/runners/foundry/tasks/foundry_rfd3_design/` (and the RFD3NA twin) own a
compressed-design contract, because that TaskType writes `<example_id>_model_<n>.cif.gz`
where its sibling writes `<example_id>_model.cif`. Migrate a Task only when its
own declared outputs prove the difference — never widen a family pattern to
cover a task whose real output was not observed. The other Tasks in the family
keep their routing, their output identity, and their scientific replay
unchanged: this is a positional rule, so nothing is inferred from a filename at
result time.

## 5. Define `test.yaml`

Add a deterministic fixture under `tests/data/` and the required smoke cases.
[Test Plan](test-plan.md) owns the declaration and collection rules; keep each
case small enough for routine target-host execution while exercising real
parsing and artifact acceptance.

Add pytest coverage only for executable family logic such as parsers, command
builders, normalizers, or postprocessors. Do not write tests that merely read
and restate YAML, shell, definition, or documentation text.

A family with executable adapter logic should ship one focused **contract test** under
`docker/runners/<family>/tests/fast/`; a declarative family may ship none. The test executes the family's real entrypoint against a
`task.json` and proves the Runner consumes the declared named input role and the
server-resolved parameters, rather than positional files or environment values.
`docker/runners/example/tests/fast/test_analyze.py` is the canonical reference to copy.

## 6. Run Doctor

Validate discovery and contracts from the repository root:

```bash
python -m revocompute doctor \
  --config-root docker/runners \
  --runner <family> \
  --strict
```

Doctor must pass before a build. It validates the plugin/task graph, parameter
schema, workspace references, and smoke-plan coverage; it does not prove that
the scientific runtime executes correctly.

## 7. Build the SIF

Build the definition directly from `docker/runners/` so relative `%files`
sources match the declared build inputs:

```bash
cd docker/runners
apptainer build /tmp/<family>.sif <family>/<family>.def
apptainer inspect /tmp/<family>.sif
apptainer test /tmp/<family>.sif
```

The `%test` section should perform inexpensive import, executable, version, and
CPU/GPU-backend checks. A direct build is the first runtime gate, not a
substitute for the production live test.

## 8. Run the smoke/live test

On the target host, stage the exact SIF and execute the family test plan through
the production API, worker, Slurm, Apptainer, and result-finalization path:

```bash
REVODESIGN_SERVER_ENV=/path/server.env \
  bash run/restart.sh prepare --enabled-runners=<family> --build-sif
REVODESIGN_SERVER_ENV=/path/server.env \
  bash run/restart.sh live-test --runner <family> --collection smoke
```

The run must exercise the real parser and artifact contract. A local execution
or mocked scheduler test cannot issue promotable readiness evidence, and green
CI is not HPC scientific acceptance.

## 9. Inspect the receipt

Review the live-test report and Runner status. Confirm every required case,
output check, and resource observation passed and that the receipt is bound to
the exact SIF, Runtime Bundle digest, build provenance, test plan, validation
contract, and public configuration:

```bash
REVODESIGN_SERVER_ENV=/path/server.env \
  bash run/restart.sh runner-status --runner <family> --json
```

Record effective walltime, CPU, host memory, GPU memory, and GPU utilization.
Use those observations to set durable resource limits rather than estimates.
A narrowed `--task` pass is not promotion evidence when it omitted a required
smoke case; rerun the full `smoke` collection.

## 10. Promote and activate

Activation is maintainer-authorized and is separate from merge. Promote only the
prepared, receipt-backed candidate:

```bash
REVODESIGN_SERVER_ENV=/path/server.env \
  bash run/restart.sh restart --mode=prepared
```

For an overlay family, the PASS in step 8 already published the Runtime Bundle
digest it validated; the prepared restart promotes the SIF. A passed live test,
a green CI run, or a merged pull request does not promote the SIF by itself.

After activation, confirm that `/compute/api/types` exposes the TaskType and
that `/compute/api/task-parameters/<task-type>` matches its owning manifest.
With deployment authorization, submit the canonical fixture once through the
public API and verify status, immutable inputs, logs, manifest, artifact
download, and result rendering. `READY` does not grant access or authorize a
submission.

## Advanced families

Keep the first adaptation on the standard path above. Use the focused guides
when the runtime actually needs an advanced capability:

- [Runner Family Protocol](runner-family-protocol.md) for lifecycle and receipt identity;
- [Runtime Bundles](runtime-bundles.md) for immutable runtime delivery and task pinning;
- [Runner Weights and Model Assets](model-resources.md) for large immutable resources;
- [Access Policy](access-policy.md) for restricted software or data;
- [Docking Runners](docking-runners.md) for molecular preparation and associations;
- [Result View Plugin Contract](../developer-guide/result-view-plugins.md) for custom result protocols;
- [Input and Result Workspace](../developer-guide/input-result-workspace.md) for custom workspace capabilities;
- [Operations and Task Adapters](../operator-guide/task-adapters.md) for multi-stage and unusual adapter behavior.

GPU tasks must additionally pin a CUDA-compatible base and wheel stack, prove
GPU visibility in `%test`, and record accelerator utilization during live
acceptance. Network-requiring stages, databases, and unusual parsers need an
explicit security and provenance review before they become part of the Task
contract.

The Example Runner is also the minimal reference for the persistent multi-item
lifecycle: `analyze.py` normalizes the FASTA into work items and drives
`execute_task`, so one Task produces one committed directory per record, resumes
from `work_items.json`, and keeps the remaining records successful when one
fails. See [Persistent Execution](persistent-execution.md) for the protocol,
the work-item states, and the resource-adaptation boundaries.
