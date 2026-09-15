# Runner Configuration and Resource Policy

Machine-local `runner.yaml` owns mounts, environment, and limits; the
owning `task.yaml` owns user-facing parameter semantics. Resource policy
is resolved before upload persistence and snapshotted per task.

Database paths and resource limits no longer live in `.env`. Each runner
family has one deployment YAML at `docker/runners/<runtime-family>/runner.yaml`:

```yaml
# docker/runners/pssm_gremlin/runner.yaml — deployment-specific host paths
mounts:
  - host_path: "/mnt/db/uniref30_uc30/UniRef30_2022_02"
    container_path: "/opt/db/uniref30"
    mode: "ro"
  - host_path: "/mnt/db/uniref90"
    container_path: "/opt/db/uniref90"
    mode: "ro"
env:
max_runtime_seconds: 7200
```

The checked-in `/mnt/db` paths are production defaults; provision those paths
or override the host paths in the deployed runner YAML when using another
host. Do not put database paths in `.env`. Each family task manifest declares
the portable runtime-to-task mapping, accepted input set, stage markers, result
patterns, and typed parameter contract. The owning `task.yaml` is the sole
authoritative source of user-facing parameter vocabulary and semantics;
`runner.yaml` contains no user-facing defaults. Missing family or task
manifests fail closed.

`CONFIG_DIR` must point to the deployed plugin/configuration tree. In Docker
deployments, set it to the corresponding baked-in source/config path.

Runtime identity is family-owned in `docker/runners/<family>/plugin.yaml`:

```yaml
runtime:
  image_artifact: gremlin_v1.sif
  definition: gremlin.def
  build_inputs: [pssm_gremlin/run.sh, common/task_context.sh, common/task_context.py]
  entrypoint: [bash, /app/revocompute/run.sh]
```

Production uses `job_executor: slurm` with `container_runtime: apptainer`, and
every runtime family must resolve an absolute SIF artifact. Startup fails
before stopping the current deployment when required config or existing SIFs
are missing.

Per-task-type SLURM resource directives (partition, cpus-per-task, mem, time,
gres, etc.) are configured via the admin UI at `/compute/configuration` and
stored in `manage.sqlite` — not in the YAML.  The web process can seed them
on first launch via `sqlite3`.

## Canonical task resource policy

The admin UI stores one portable policy for CPU cores, memory, and maximum
runtime. Per-task values override global defaults. SLURM-only placement fields
(partition, GRES, nodes, tasks, QOS, account, constraint, and exclusivity) are
resolved afterward.

Resolution happens before upload persistence. The accepted policy is stored in
the task's `input_form` record, validated again by the worker, and passed to the
selected launcher. This prevents a queued task from changing because an admin
edits defaults later.

For SLURM, the policy always produces explicit `--cpus-per-task`, `--mem`,
`--time`, `--nodes`, and `--ntasks` arguments. GPU task types receive a
validated GRES (default `gpu:1`) and Apptainer `--nv`; CPU task types cannot
carry a per-task GPU GRES and never inherit a global GPU GRES. Configured
partitions must belong to `slurm_allowed_queues`. The allocated CPU count is
then forwarded into Apptainer's thread-control environment.

For Docker, the same CPU and memory values become `nano_cpus` and `mem_limit`,
thread-control variables are set consistently, GPU jobs request one device,
and a watchdog kills work that exceeds the snapshotted runtime. Invalid fields
fail closed in the admin API and again at submission/launch rather than being
silently discarded.

## Ordered workflows

A task type may declare an ordered `workflow` whose stages reuse the same
runtime family and immutable task snapshot. The worker acts as a lightweight
Composer: it submits one existing `Job` at a time, validates that allocation's
outputs through the runner contract, persists the stage/job state, and releases
the next stage only after success. Each stage has an independently snapshotted
resource policy in the configuration UI.

```text
Submission -> Composer -> [CPU: MSA + features] -> [GPU: model + relax] -> Results
                           | features.pkl/A3M     | ranked structure
                           +---- persisted --------+
```

AlphaFold2 and ColabFold/AlphaFold2 are independent composed tasks. `alphafold`
uses the mounted local databases for feature construction; `colabfold_af2`
uses the public ColabFold MMseqs2 service and mounted
`/mnt/db/weights/alphafold/colabfold` parameters. Each persists its CPU-stage
output before local GPU inference and optional Amber relaxation. Restarts
cancel only the active allocation and resume at the first incomplete stage.

AlphaFold 3 is a third, independent runtime family. It accepts the current
upstream AlphaFold 3 JSON contract and runs a CPU-only data pipeline followed
by GPU inference. The immutable handoff is the job-derived `*_data.json` under
the task result tree; prediction outputs remain in a separate modeling tree.
The production image pins upstream revision
`c0f97eda2f1f482fd94d3a38bece18c7069b4a5c`. The site's historical
`/repo/alphafold3` `native-run` branch is only an operator reference for the
local database layout and is not image source code.

AlphaFold 3 databases and model parameters are operator-managed read-only
mounts declared in `docker/runners/alphafold3/runner.yaml`; they are never copied into
images, task workspaces, or results. Submission requires both the requestable
`alphafold3_noncommercial` Runner entitlement and the independent
`allow_gpu_use` permission. The source code is Apache-2.0 licensed, while the
model parameters and generated outputs have separate upstream terms. An
entitlement records operator authorization and is not a determination of legal
eligibility. See the current official [AlphaFold 3 Model Parameters Terms of
Use](https://github.com/google-deepmind/alphafold3/blob/main/WEIGHTS_TERMS_OF_USE.md).
