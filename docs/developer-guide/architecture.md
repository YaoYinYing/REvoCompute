# Architecture

REvoCompute has four boundaries: the HTTP/API layer authenticates and
authorizes; the Core builds a validated TaskDefinition and ExecutionPlan; the
worker submits that plan to Slurm and Apptainer; and the family parser accepts
typed outputs into isolated storage. Redis/Celery transport work but do not own
scientific rules.

Core owns the generic plugin, task, execution, resource, artifact, and
readiness grammar, together with orchestration and validation mechanisms.
Runner families own their TaskTypes, scientific parameter vocabulary,
scientific constants, runtime contract, parser and result semantics,
storyboard/workspace extensions, and family access-policy contribution. A new
family with new scientific vocabulary must not require Core knowledge of its
runner or task IDs.

Every user-facing parameter is fully declared in the owning `task.yaml`,
including type, default or required semantics, constraints, and a meaningful
scientific description. Core projects that declaration unchanged through the
anonymous `GET /compute/api/task-parameters/<task-type>` Draft 2020-12 JSON
Schema endpoint and through the task form contract; it does not own a parallel
parameter-help registry.

The anonymous `/skills.md` resource is a stable API bootstrap guide. It directs
agents to OpenAPI for protocol truth and to the dynamic Task discovery and
parameter-schema APIs; it never enumerates the fleet or becomes a separate
scientific declaration.

Admission checks the shared current readiness evidence before durable side
effects, while access entitlement and transient scheduler capacity remain
separate decisions. This separation keeps Core generic and makes provenance,
receipts, and recovery auditable.

## Ownership Boundary

REvoCompute owns user identity, Runner access and readiness, Task execution,
immutable user-owned Task storage, result manifests, Artifacts, and provenance.
Task ownership is directly user-based through immutable identities such as
`submitted_by_user_id` and the immutable user `storage_key`.

REvoCompute does not own Projects, Project membership or roles, Project
storage, invitations, visibility, or collaboration lifecycle. A future
independent Project Dashboard may reference stable REvoCompute Task and
Artifact identities, but must own its own membership, collection, role,
sharing, and presentation model.

The conceptual integration boundary is the Task ID; submitting/owner identity;
TaskType; task status; result manifest; artifact logical path; artifact metadata
and digest; authorized artifact retrieval; and artifact provenance. This
boundary does not introduce Project APIs, Project ACLs, sharing tables,
compatibility abstractions, generic scope objects, or cross-user artifact reuse.

## Plugin and runtime family discovery

The server discovers task types and runtime families from plugin manifests.
Adding a new compute task selects a family-owned runtime; several compatible
task types can share one SIF without duplicating dependency stacks:

| File | Owner | Contains |
|------|-------|----------|
| `docker/runners/<runtime-family>/plugin.yaml` | Developer | Family runtime metadata and task-manifest contributions |
| `docker/runners/<runtime-family>/tasks/` | Developer | Task I/O contracts and constrained parameters |
| `docker/runners/<runtime-family>/runner.yaml` | Operator (per-machine) | One machine-specific mounts/environment/defaults config shared by the family |
| `config/access_policies/<policy-id>.yaml` | Operator/developer | Portable entitlement, request, notice, and license metadata for a restricted family |
| `docker/runners/<runtime-family>/<family>.def` | Developer | Authoritative direct SIF build for the family |
| Runtime family `definition` | Developer | Exact Apptainer definition path used for its SIF |

The server loads the plugin tree at startup from `RUNNERS_DIR`, which Compose
sets to `${SERVER_DIR}/docker/runners` after the controller materializes the
selected families. `ENABLED_TASKRUNNERS` selects the exact family set to
materialize; an empty value enables every discovered family, and there is no
implicitly enabled family.

Each runner container follows a standard contract (protocol v3):
- Sees one immutable task snapshot at `/mnt/revocompute/<user-storage-key>/inputs/`
  and task-owned results at `/mnt/revocompute/<user-storage-key>/outputs/`. Concurrent
  tasks have isolated host snapshots even though their virtual paths match.
- Emits `REVODESIGN_STAGE:<marker>` on stdout for progress tracking
- Is invoked as `run.sh -i <inputs>/task.json -o <outputs>`; the snapshot's
  `task.json` carries task id/type, `params`, and named `inputs`; each role
  contains records with mounted path, format, logical type, hash, and validation
  metadata. Environment variables carry nothing user-shaped — only
  `TASK_MANIFEST`, the backslash-free manifest path (apptainer's
  `APPTAINERENV_*` forwarding mangles backslash runs, so params never travel
  through the environment).
- Sources `task_context.sh` (next to `run.sh`, `TASK_CONTEXT_SRC`-overridable)
  for `_parse_param`, `task_input <role>`, and `task_inputs <role>`, backed by
  `task_context.py`.
- Runs as non-root `--user` (identity from `RUNNER_UID`/`RUNNER_GID` in `.env`)

The create-task page selects from the compact `GET /compute/api/types` catalog,
then builds a scientific experiment protocol from
`GET /compute/api/types/<name>` plus its linked canonical parameter schema. Its
version-3 form definition groups local,
declarative capabilities into meaningful `input_workspace.steps`; the submitted
workspace document remains version 2. Plugins compose file roles, pasted
sequences, structure inspection, residue/region controls, typed parameters, and
a final review. A simple FASTA task therefore stays small, while RFdiffusion or
PLACER can expose a guided multi-file structure workflow without task-name
conditionals in the page orchestrator. Specialized varieties, such as the
RFdiffusion region/contig builder, remain separate statically loaded plugins.
The anonymous `GET /compute/api/task-parameters/<task-type>` route exposes the
canonical Draft 2020-12 parameter schema directly from the owning
`task.yaml`; clients should consume it instead of maintaining parameter names,
defaults, constraints, or descriptions independently.

Capability YAML selects only plugin IDs shipped by the server. Unknown plugins,
unknown options, executable snippets, and remote plugin URLs are rejected at
registry load. Browser validation is advisory: accepted extensions, safe
relative paths, upload limits, parameters, resource policy, and runner command
construction remain authoritative on the server. The repository-root
`TODO_PLUGGABLE_INPUT_RESULT_UI.md` backlog tracks the remaining migration and
hardening work.

## Server stack and package boundaries

The server stack contains:

- `web`: Flask + Gunicorn API/UI service
- `maintenance`: APScheduler process for registration digests, result cleanup,
  database backups, and log rotation
- `worker`: Celery worker for background jobs
- `redis`: Celery broker/backend
- versioned runtime-family SIFs: launched on demand by the worker; they are
  not long-lived Compose services

**Alternative executor (SLURM + Apptainer):** When the deployment
configuration selects `job_executor: slurm` and
`container_runtime: apptainer`, the worker dispatches every task via `srun` +
Apptainer instead of Docker. See [SLURM + Apptainer](../operator-guide/slurm-deployment.md).

Scientific Python dependencies used by GREMLIN scripts belong to the runner's
`docker/runners/pssm_gremlin/GREMLIN.yml`; they are not installed into the web and worker package.

Periodic jobs follow this package boundary:

```text
revocompute/maintenance/
├── model.py                 # PeriodicTask interface
├── manager.py               # imports task objects and calls register()
└── tasks/
    ├── admin_digest.py      # self-configuring admin_digest_task
    ├── database_backup.py   # consistent task/user SQLite snapshots
    ├── log_rotation.py      # ZIP rotation and total-size pruning
    └── result_cleanup.py    # self-configuring result_cleanup_task
```

Each task object owns its environment configuration, enabled state, callable,
maximum instances, trigger, and `scheduler.add_job` arguments.

The web container submits tasks through Redis; web, maintenance, and worker
services have no Docker socket or user-database overlap.
