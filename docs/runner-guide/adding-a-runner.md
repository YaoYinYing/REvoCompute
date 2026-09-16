# Adding a Runner

Use the CPU-only `docker/runners/example/` family as the structural reference
for a conventional Runner. It is a complete,
fast path through plugin discovery, named inputs, Task parameters, execution,
artifact acceptance, Result Workspace views, and a ResultStoryboard without
weights, databases, network access, or a GPU.

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

## 4. Implement `run.sh`

Resolve inputs by role with `task_input` or `task_inputs`, and read resolved
parameters with `_parse_param`. Keep immutable inputs read-only and write every
generated file beneath the supplied output directory. Emit declared
`REVODESIGN_STAGE:<id>` markers around meaningful execution phases.

Scientific parsing, preparation, and output semantics stay in the family.
Security preflight stays in Core, and the Runner must not introduce a second
upload-acceptance path.

Declare Result Workspace views in `task.yaml`. Add `expected_files.yaml` and a
family-owned `storyboard/` only when the results benefit from stable logical
file identities or task-specific composition. Storyboards receive only
manifest-approved artifacts and should delegate file rendering to server
services.

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
