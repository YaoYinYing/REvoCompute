# Atomic Runner Families

Each directory under `docker/runners/` is a self-contained, deployable Runner
Family. Adding or removing one family must require no change under Core
(`revocompute/`) or to `config/task_types.yaml`.

## Required tree

```text
<family>/
  plugin.yaml                 # identity and contribution declarations
  runner.yaml                 # machine mounts, environment, limits
  Dockerfile                  # reproducible runner image
  <family>.def                # Apptainer definition using docker-daemon image
  run.sh                      # task dispatcher and output contract
  tasks/<task>/task.yaml      # task schema, workspace, execution/output metadata
  workspace/<editor>/         # optional advanced input editor
    index.js
    style.css                  # optional
    schema.json                # optional configuration schema
  policies/*.yaml              # optional runner-owned access policies
  storyboard/                  # optional task-owned presentation assets
```

## Manifest metadata

`plugin.yaml` must provide `api_version`, a unique `id`, `version`, and a
`runtime` mapping with `docker_image`, `slurm_image`, `dockerfile`,
`definition`, and `entrypoint`. Paths are relative to the family directory;
`slurm_image` is an absolute deployment target. Declare every contribution in
`contributions`, including `tasks`, `runtime_families`, `runner_configs`,
`input_workspace_plugins`, and `access_policies` as applicable.

Workspace descriptors identify an opaque local editor id, its module asset,
optional stylesheets, and optional JSON Schema. Task manifests reference that
local id in `input_workspace`; they never name a JavaScript path. The server
validates and serves only declared, family-relative assets.

Task metadata owns the user contract: Draft 2020-12 parameter `schema`, input
extensions and workspace steps, execution arguments/builders, workflow stages,
output/artifact roles, parser and storyboard references, citations, and
resource/policy requirements. `runner.yaml` owns deployment mounts,
environment, and limits. Policies and advanced scientific semantics stay with
the family that interprets them.

## Build and verify

From the repository root, validate the family and its links with:

```bash
python -m revocompute doctor --config-root docker/runners --runner <family> --strict
```

Build the Docker image with the repository controller so UID/GID and pinned
arguments are applied, then prepare the matching Apptainer SIF from the family
definition. A server setup materializes the complete family tree into
`SERVER_DIR/docker/runners`; production discovery uses that immutable snapshot,
not the source checkout.

An atomic family must disappear cleanly when its directory is removed: tasks,
runtime metadata, workspace editors, policies, assets, and storyboards must all
stop being discoverable without Core edits.

## Adaptation workflow

1. Inventory the upstream tool before writing server code. Record the source
   repository and pinned commit, license and access conditions, supported CUDA
   minor version, model weights, databases, input/output formats, expected
   CPU/GPU/memory, and a minimal reproducible input.
2. Create one family directory and keep every scientific fact inside it. Use a
   family for tasks that genuinely share one isolated image and operational
   dependencies; do not use it as a catalog for unrelated tools.
3. Build and run the image directly with the minimal input. The entrypoint must
   accept the server task manifest and output directory, return the tool's exit
   status, and write at least one non-empty declared artifact on success.
4. Add the task manifest and JSON Schema, then run Doctor before wiring UI.
5. Add optional policy, workspace, parser, and storyboard contributions. Test
   each link and the removal case.
6. Materialize the family through `restart.sh setup`/`prepare`; verify from the
   deployed tree after making the source checkout unavailable.

## `plugin.yaml` reference

```yaml
api_version: 1
id: example-family
version: "1"
runtime:
  docker_image: organization/example-runner:version
  slurm_image: /absolute/deployment/images/example_v1.sif
  dockerfile: Dockerfile
  definition: example.def
  entrypoint: [bash, /app/revocompute/run.sh]
  access_policy: example_license       # optional contributed policy ID
tasks:
  - tasks/predict/task.yaml
access_policies:                       # optional family-relative documents
  - policies/license.yaml
contributions:
  access_policies: [example_license]
  input_workspace_plugins:
    - id: advanced-editor
      module: workspace/advanced-editor/index.js
      styles: [workspace/advanced-editor/style.css]
      configuration_schema: workspace/advanced-editor/schema.json
```

`id` is the stable family identity and is independent of the directory name.
`version` versions the bundled contract. `api_version` selects the supported
plugin protocol. `docker_image` is the OCI build/pull name; `slurm_image` is the
host SIF activation path. The `.def` file must use `Bootstrap: docker-daemon`
and the same tagged Docker image. `entrypoint` becomes the task-owned
`ExecutionPlan.command`. Never declare a host/native execution mode.

Every path except `slurm_image` is family-relative. Absolute paths, traversal,
symlink escape, missing files, duplicate contribution identities, and
undeclared assets are rejected. Local workspace IDs are namespaced by family,
so two independent families may both contribute `advanced-editor`.

## `task.yaml` reference

A task normally declares:

```yaml
id: example_predict
display_name: Example prediction
category: structure_prediction
summary: Short catalog description.
use_when: Scientific selection guidance.
input_summary: What the researcher supplies.
output_summary: What the run produces.
input_extension: .fasta
input_extensions: [.fasta, .fa]
primary_input_extensions: [.fasta, .fa]
min_input_files: 1
max_input_files: 1
gpus: true
requires_network: false
runner_args: [predict]
schema:
  $schema: https://json-schema.org/draft/2020-12/schema
  type: object
  additionalProperties: false
  properties:
    iterations: {type: integer, minimum: 1, maximum: 10, default: 1}
input_workspace:
  steps:
    - id: input
      title: Provide input
      capabilities:
        - plugin: files
          id: source_files
        - plugin: advanced-editor
          id: scientific_plan
          options: {}
workflow:
  - name: predict
    display_name: Prediction
    requires_gpu: true
stage_markers:
  predict: Prediction
```

Use standard JSON Schema keywords for all parameter constraints and formats.
Core validates it with Draft 2020-12 and format checking and derives generic UI
controls from it. Do not require a Core branch for a parameter, task ID, runner
ID, or plugin ID. Fixed scientific command semantics belong in `runner_args` or
a runner-owned execution builder. Scheduler concerns such as partitions and
allocated resources remain server infrastructure.

Input Workspace steps are presentation order; each capability references a
generic Core primitive or a contribution declared by the same family. Advanced
editor options are validated against its contributed schema. Browser output is
untrusted: a runner-owned backend normalizer/serializer must enforce scientific
semantics before execution.

## `runner.yaml` reference

`runner.yaml` contains deployment-specific data only:

```yaml
mounts:
  - host_path: /srv/databases/example
    container_path: /opt/databases/example
    mode: ro
env:
  EXAMPLE_DATABASE: /opt/databases/example
max_runtime_seconds: 3600
```

Do not put task definitions, categories, schemas, commands, policy meanings, or
presentation metadata here. Mount the narrowest required host paths read-only
unless the tool truly needs writes. Never mount credentials or a user's home.

## Outputs and presentation

Define output selectors, parsers, artifact roles, and storyboard/views in the
task tree. Parsers translate raw tool files into generic artifact descriptors;
Core transports files but does not infer scientific meaning from filenames.
Every storyboard source role must be emitted by its parser, and every declared
asset must exist inside the family. Include DOI/title citation metadata and
resolve checked-in BibTeX with the repository citation tool rather than typing
records from memory.

## Policies

Runner licenses and access restrictions are family contributions. Put policy
documents under `policies/`, declare their IDs, and reference the stable ID from
`runtime.access_policy`. Core understands generic approval, entitlement,
suspension, and scope only. Removing the family must remove the policy; never
copy its meaning into central Python or configuration.

## Acceptance checklist

- `python -m revocompute doctor --config-root docker/runners --runner <id> --strict`
- focused contract tests for manifest fields, schema, execution plan, outputs,
  policy links, workspace assets, and storyboard roles
- real Docker run with a minimal safe input and recorded walltime/CPU/host
  memory/GPU memory/GPU utilization
- SLURM plus Apptainer run through the public API, with status, logs, manifest,
  and artifacts inspected through that API
- materialized-tree test proving no source-checkout dependency
- removal test proving all family contributions disappear
- `make test`, `make test-cov`, relevant Docker/Compose smoke gates, shell syntax,
  and rendered Compose validation

See `OPERATIONS_AND_TASK_ADAPTER_GUIDE.md`, `RUNNER_ACCESS.md`, and
`RUNTIME_FAMILIES.md` for operational contracts that complement this guide.
