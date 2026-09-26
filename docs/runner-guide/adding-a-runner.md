# Adding a Runner

Use the CPU-only `docker/runners/example/` family as the structural reference
for a conventional Runner. It is a complete,
fast path through plugin discovery, named inputs, Task parameters, execution,
artifact acceptance, Result Workspace views, and a ResultStoryboard without
weights, databases, network access, or a GPU.

## Runner change-impact model

Classify every changed Runner file or manifest field before building or
deploying it. The three identities have different consequences:

- **Build Identity** is the direct Apptainer definition plus every mutable
  repository file declared by `runtime.build_inputs`. A change means rebuild
  the SIF, run its checks, and live-test the exact candidate before promotion.
- **Execution Contract Identity** is the parsed configuration that determines
  accepted inputs and parameters, argument and stage behavior, expected
  outputs, effective resources, runtime invocation, and live-test coverage. A
  change keeps the existing SIF but makes its live-test receipt stale.
- **Presentation Identity** is user-facing metadata that cannot alter execution,
  such as display names, summaries, help text, citations, category labels, and
  UI hints. A presentation-only change needs the normal server/config
  deployment, but neither a SIF rebuild nor a new live-test.

This is the canonical change-impact matrix:

| Change | Rebuild SIF | Re-run live-test |
| --- | ---: | ---: |
| Apptainer `.def` | Yes | Yes |
| Requirements or lockfile copied into the image | Yes | Yes |
| `run.sh` or other entrypoint code copied into the image | Yes | Yes |
| Preprocessing, scientific wrapper, or postprocessing code inside the image | Yes | Yes |
| Shared runtime helper copied into the image | Yes | Yes |
| Task argument forwarding or execution-affecting default | No | Yes |
| Task input/output execution contract | No | Yes |
| Result-view source selectors or acceptance-relevant mapping | No | Yes |
| `expected_files.yaml` logical-output contract | No | Yes |
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

`family.version` identifies the family release for display and audit. It is not
an automatic build or validation input. If image construction consumes a
version value, the file or recipe that supplies that value must participate in
Build Identity; changing that actual input then drives the rebuild.

For each new file or field, ask in order:

1. Can changing it alter SIF contents or code executed inside the SIF? Put the
   file in Build Identity.
2. Can changing it alter how Core invokes, validates, resources, or accepts the
   computation? Put the field in Execution Contract Identity.
3. Can changing it only alter what a user sees? It belongs to Presentation
   Identity.

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

These are also the minimum facts an AI coding agent needs. Give the agent those
facts and direct it to the Example Runner; do not ask it to infer contracts from
an upstream README or invent dependency versions.

## 2. Define `plugin.yaml`

Set a stable family ID and version. Declare the direct Apptainer definition,
image artifact, every local build input, the runtime entrypoint, and each Task
manifest. Pin all upstream source revisions and dependency inputs used by the
definition. See [Plugin Manifest](plugin-manifest.md).

`runtime.build_inputs` is a correctness boundary, not an inventory of convenient
files. It must name every mutable repository file whose content is copied into,
imported by, executed from, or otherwise materially affects the SIF, unless the
content is already captured by the definition or another declared immutable
digest. Paths must be unique regular files within the Runner tree. Do not add
unrelated files just because they share the directory, and do not rely on an
automatic dependency scanner; the explicit list is the reviewable contract.

An omitted executable input is dangerous. If `predict.py` is baked into the
image but absent from `build_inputs`, editing it leaves build provenance
unchanged, so an old SIF can be reported as current and continue running old
scientific code. Review `%files`, install/copy commands, imported local modules,
patches, generated helpers, and shared runtime helpers against the list before
building.

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
`docker/runners/common/persistent_runner.py` with a plugin that loads the
runtime once, executes one work item per record, and commits each item into its
own directory; see [Persistent Execution](persistent-execution.md) and copy the
Example Runner.

Declare Result Workspace views in `task.yaml`. Add `expected_files.yaml` and a
family-owned `storyboard/` only when the results benefit from stable logical
file identities or task-specific composition. Storyboards receive only
manifest-approved artifacts and should delegate file rendering to server
services. Register a view that presents structures through the declared
confidence metadata rather than a filename heuristic; see
[Structure Presentation Contract](structure-presentation.md).

## 5. Define `test.yaml`

Add a deterministic fixture under `tests/data/` and a required smoke case for
every TaskType in the family. Group fixture paths by named role and provide
parameters accepted by the Task schema. Keep the case small enough for routine
target-host execution while exercising real parsing and artifact acceptance.
See [Test Plan](test-plan.md).

Add pytest coverage only for executable family logic such as parsers, command
builders, normalizers, or postprocessors. Do not write tests that merely read
and restate YAML, shell, definition, or documentation text.

Every family also ships one focused **contract test** under
`tests/runners/<family>/`. It executes the family's real entrypoint against a
`task.json` and proves the Runner consumes the declared named input role and the
server-resolved parameters, rather than positional files or environment values.
`tests/runners/example/test_analyze.py` is the canonical reference to copy.

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
or mocked scheduler test cannot issue promotable readiness evidence.

## 9. Inspect the receipt

Review the live-test report and Runner status. Confirm every required case,
output check, and resource observation passed and that the receipt is bound to
the exact SIF, build provenance, test plan, validation contract, and public
configuration:

```bash
REVODESIGN_SERVER_ENV=/path/server.env \
  bash run/restart.sh runner-status --runner <family> --json
```

Record effective walltime, CPU, host memory, GPU memory, and GPU utilization.
Use those observations to set durable resource limits rather than estimates.

## 10. Promote

Activate only the prepared, receipt-backed candidate:

```bash
REVODESIGN_SERVER_ENV=/path/server.env \
  bash run/restart.sh restart --mode=prepared
```

After activation, confirm that `/compute/api/types` exposes the TaskType and
that `/compute/api/task-parameters/<task-type>` matches its owning manifest.
Submit the canonical fixture once through the public API and verify status,
immutable inputs, logs, manifest, artifact download, and result rendering.

## Advanced families

Keep the first adaptation on the standard path above. Use the focused guides
when the runtime actually needs an advanced capability:

- [Runner Family Protocol](runner-family-protocol.md) for lifecycle and receipt identity;
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
