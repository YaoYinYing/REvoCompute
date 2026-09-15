# SLURM + Apptainer Deployment

The worker submits `srun` jobs that run Apptainer SIFs on SLURM compute
nodes. This page is the step-by-step enablement checklist and runtime
architecture reference. For the deployment lifecycle itself, see
[Deployment Lifecycle](deployment.md).

The server uses a SLURM + Apptainer runner backend. The worker submits `srun`
jobs that run Apptainer containers on SLURM compute nodes.

## Maintainer Workflow — Step by Step

This is the checklist for enabling a task type on a SLURM deployment.

### Step 1: Prerequisites on the deployment host

The host running the server containers must have:

- **SLURM client** — `srun`, `squeue`, `scancel`, `sacct`, `sinfo` (bind-mounted into the worker)
- **MUNGE** — `/run/munge` socket + `libmunge.so.2` (SLURM authentication)
- **Apptainer** — on PATH if using `--build-sif`, or at least on the SLURM compute nodes
- **SLURM config** — `/etc/slurm-llnl/` accessible to the worker (host networking)

Verify connectivity from the worker container after startup:
```bash
docker exec server-slurm-worker-1 srun --version
docker exec server-slurm-worker-1 sinfo
```

### Step 2: Create the `.env` file

Copy an existing SLURM env and customise:

```bash
cp .env.production.v7-slurm .env.production.v8-custom
```

Key SLURM-specific variables:

| Variable | Purpose |
|----------|---------|
| `COMPOSE_PROJECT_NAME` | **Must differ from production** (e.g. `server-slurm`). Compose isolation prevents one deployment from interfering with another. |
| `SERVER_IMAGE` | **Must differ from production** (e.g. `revodesign-revocompute-server-slurm`). Image tag collision would overwrite the wrong image. |
| `PORT` | Choose a free host port (e.g. `8081`). |
| `SLURM_ALLOWED_QUEUES` | Comma-separated partition names visible in `/compute/configuration` (e.g. `normal,gpu`). |
| `REVOCOMPUTE_SCRATCH_BACKEND` | Per-task container `/tmp` backing: `disk` (default, task workspace) or `ram` (private node-local `/dev/shm` directory). |

RAM scratch is disposable node-local state, not part of task recovery. The
allocation wrapper removes it on normal exit. At the start of each later RAM
allocation on the same node, directories older than 24 hours are removed only
when their recorded Slurm job ID is absent from `squeue`; missing markers and
scheduler-query failures are retained for operator inspection.
| `ENABLED_TASKRUNNERS` | Comma-separated list of additional task types beyond `gremlin` (e.g. `pythia_ddg`). |
| `CONFIG_DIR` | Path to the deployed runner plugin/configuration tree. |
| `REDIS_URL` | `redis://redis:6379/0` for bridge containers; `redis://127.0.0.1:6380/0` for host-networked worker (set in `docker-compose.slurm.yml`). |

Use `--keep-gateway` on `restart` to block submissions and leave the Nginx
gateway running while Redis, web, maintenance, and worker services are rebuilt.
The gateway serves the static maintenance page throughout the downtime instead
of returning an origin 502.

For faster, disk-free SIF builds, both Apptainer paths may use a RAM-backed
filesystem such as `/dev/shm`. Create private directories as the deployment
user, then add them to the env file:

```bash
mkdir -p /dev/shm/revodesign-apptainer-cache /dev/shm/revodesign-apptainer-tmp
chmod 700 /dev/shm/revodesign-apptainer-cache /dev/shm/revodesign-apptainer-tmp
```

```dotenv
APPTAINER_CACHEDIR=/dev/shm/revodesign-apptainer-cache
APPTAINER_TMPDIR=/dev/shm/revodesign-apptainer-tmp
```

Check capacity with `df -h /dev/shm`; RAM-backed files disappear after reboot,
and the cache is only used while building SIFs.

### Step 3: Configure the executor and runtime families

Declare the family runtime beside its tasks in `plugin.yaml`:

```yaml
runtime:
  image_artifact: pythia_ddg_v1.sif
  definition: pythia_ddg.def
  build_inputs: [pythia_ddg/run.sh, common/task_context.sh, common/task_context.py]
  entrypoint: [bash, /app/revocompute/run.sh]
```

Fields `mounts`, `env`, `max_runtime_seconds`, and `defaults` work identically
for both executors and remain in the corresponding runner YAML. Executor,
container runtime, SIF path, GPU requirement, and SLURM resources do not belong
in runner YAML.

Per-task SLURM resource directives (partition, cpus-per-task, mem, time,
gres, etc.) are configured via the admin UI at `/compute/configuration` and
stored in `manage.sqlite` — not in the YAML.

### Step 4: Create the `.def` file

Each runtime family declares its exact Apptainer definition path in
`plugin.yaml`. The restart helper rejects missing definitions; it
does not guess with `find`.

```def
Bootstrap: docker
From: python:3.12-slim

%post
    # install the pinned upstream program and declared family inputs

%runscript
    exec bash /app/revocompute/run.sh "$@"
```

`Bootstrap: docker` may pull an upstream OCI base, but the `.def` performs the
authoritative installation and Apptainer writes the SIF directly. There is no
Runner Dockerfile or daemon-local Runner image in the production flow.

The `prime` family serves two distinct model contracts. **Pro-Prime OGT
prediction** uses the pinned `AI4Protein/ProPrime_650M_OGT_Prediction` snapshot
at `PRIME_MODEL_DIR`. **PRIME DMS** uses the pinned `AI4Protein/Prime_690M`
snapshot at `PRIME_DMS_MODEL_DIR`, matching the upstream
`notebooks/run_proteingym.ipynb` scoring rule. One input sequence produces an
exhaustive single-substitution DMS CSV. If the upload contains multiple FASTA
records or files, the first sequence is the reference and each remaining
sequence is scored as a supplied combinatorial variant; all substitutions'
log-probability differences are summed.

The older `prime_base.pt` file belongs to the legacy `Prime_1` mutant-effect
implementation. It is preserved for rollback and provenance, but renaming it
to `checkpoint.pt` neither makes it an OGT checkpoint nor makes it equivalent
to the immutable Hugging Face snapshots used by these production tasks.

The shared `mpnn` family pins a commit-identical fork of the official
`dauparas/ProteinMPNN` repository.
**ProteinMPNN** uses its vanilla (or explicitly selected CA-only) checkpoints;
**SolubleMPNN** is a distinct task that passes the upstream
`--use_soluble_model` flag and permits only the published `v_48_010` and
`v_48_020` soluble checkpoints. HyperMPNN, LigandMPNN, and ThermoMPNN-D remain
separate task contracts in the same dependency image. **LASErMPNN** also uses
this CPU family for ligand-conditioned sequence and side-chain design. It
accepts multiple protonated PDB/mmCIF snapshots, preserves nested upload paths,
and exposes the upstream all-data default and paper-analysis checkpoints as
explicit choices; arbitrary checkpoint paths and key-mismatch bypasses remain
server controlled.

The `easifa` family uses the pinned official EasIFA2 Core single-prediction
interface, not the legacy EasIFA dataset benchmark. Its read-only checkpoint
mount contains only `all_features`, `wo_reactions`, and `rxn_model` directories
from the pinned `xiaoruiwang/EasIFA2.0_Metadata` revision. A structure without
reaction SMILES selects `wo_reactions`; supplying `reactants>>products` selects
`all_features`. Checkpoint paths and CUDA device selection remain operator
controlled. Each successful task publishes the complete upstream JSON plus an
`active_sites.csv` residue table for manifest-first preview and download.

### Step 5: Build, live-test, and activate SIFs

Inspect current active-Runner readiness before changing anything:

```bash
REVODESIGN_SERVER_ENV=.env.production.v7-slurm bash run/restart.sh runner-status --all
REVODESIGN_SERVER_ENV=.env.production.v7-slurm \
  bash run/restart.sh runner-status --runner alphafold3 --json
```

Readiness is derived, never set by an operator. `NOT_CONFIGURED` means Doctor
must be fixed; `NOT_BUILT` means the active SIF is absent; `BUILD_STALE` means
the definition, family version, declared build inputs, or build provenance
changed; `NOT_VALIDATED` means the current build has no receipt; and
`VALIDATION_STALE` means its receipt no longer matches the active SIF or the
current runtime, Task, or `test.yaml` identity. `READY` requires strict
family-contract validation, a current active SIF, and every required smoke case
passing for that exact identity.

Status inspection is read-only. It does not build, repair, submit work, or
inspect a staged `.sif.next` as the active Runner. Readiness is also independent
of a user's access entitlement and transient Slurm/GPU availability.

Prepare changed family SIFs while the healthy stack
remains up. SIFs stage as `<sif>.next`; unchanged families are skipped:

```bash
REVODESIGN_SERVER_ENV=.env.production.v7-slurm \
  bash run/restart.sh prepare \
    --enabled-runners=family \
    --build-sif
```

Then run the real acceptance path:

```bash
REVODESIGN_SERVER_ENV=.env.production.v7-slurm bash run/restart.sh live-test --runner family
```

Then activate the prepared artifacts without rebuilding:

```bash
REVODESIGN_SERVER_ENV=.env.production.v7-slurm \
  bash run/restart.sh restart --mode=prepared --keep-gateway
```

For a focused single-family iteration, a manual build from the family's exact
registry `definition` remains available:

```bash
apptainer build --fakeroot /absolute/images/family_v1.sif \
  docker/runners/family/family.def
```

Verify `${CONFIG_DIR}/.deploy-stamp` after the restart. The complete backup,
validation, sizing, and activation sequence is in the
[operations guide](task-adapters.md).

### Step 6: Configure per-task SLURM resources

After startup, go to `/compute/configuration` and set per-task-type SLURM
parameters: partition, cpus-per-task, memory, time limit, GRES, etc.  These
are stored in `manage.sqlite` in the server directory and become `--option=value`
flags on the `srun` command line.

### Step 7: Verify

Submit a test task and monitor:

```bash
# Watch SLURM queue
squeue --name=revocomput_

# Check task status via API
curl -H "Authorization: Bearer <token>" \
  "http://<server>:<port>/compute/api/running/<task_md5>"
```

## docker-compose.slurm.yml

The override file adds:

- **worker** → `network_mode: host` (needed to reach the SLURM controller)
- **worker** → bind-mounted SLURM tools (`srun`, `sbatch`, `squeue`, `scancel`, `sacct`, `sinfo`)
- **worker** → bind-mounted MUNGE socket + library (SLURM authentication)
- **redis** → published on `6380:6379` (host `:6379` is occupied; worker uses `REDIS_URL=redis://127.0.0.1:6380/0`)
- **web, worker, maintenance** → `CONFIG_DIR` mounted read-only

## Architecture

```
Worker (host network)                   SLURM controller
  │                                         │
  ├─ srun bash _slurm_wrapper.sh ──────────►│
  │                                         │
  │     SLURM compute node                  │
  │       ├─ apptainer run --nv *.sif       │
  │       │   ├─ /mnt/revocompute/<user>/inputs  (snapshot, ro) │
  │       │   ├─ /mnt/revocompute/<user>/outputs (task-owned, rw)│
  │       │   └─ DB mounts (ro, from YAML)  │
  │       │                                 │
  │       └─ stdout/stderr → srun pipes → worker threads
  │                                         │
  └─ Popen.wait() → exit code               │
```

## SIF Image Build (Manual)

When the staged auto-build isn't suitable, build a single SIF manually from
the family's exact `definition`:

```bash
# Build directly using the family's exact definition, then inspect and test
apptainer build --fakeroot /path/to/pythia_ddg_v1.sif \
  docker/runners/pythia_ddg/pythia_ddg.def
apptainer inspect /path/to/pythia_ddg_v1.sif
apptainer test /path/to/pythia_ddg_v1.sif
```

`prepare --build-sif` is the standard production rebuild: it stages each stale
SIF as `<sif>.next`; a later prepared restart atomically promotes it after
`down`.

## Runtime Size Gate

Do not estimate savings from definition text. After building on the designated
Linux builder, record the compressed SIF bytes:

```bash
python tools/audit_runtime_sizes.py \
  --runners-dir "${CONFIG_DIR}/runners" \
  --require-all \
  --json > runtime-sizes.json
```

The command only inspects artifacts already present; it never pulls, builds,
or runs them. Compare the JSON with the previous production release before
activation. Runtime-family sharing reduces the number of distinct artifacts;
the MPNN family additionally omits inference-unused CUDA stub, Triton,
torchvision, and torchaudio wheels. Removing build tools in a later Docker
layer is not counted as a size optimization because earlier layer bytes remain.

## GPU Privilege Gating

Users must have `allow_gpu_use=true` (toggled by admins via the User Control
page) to submit task types whose family/task manifest requires GPUs. This
is enforced at submission time — unprivileged users receive 403 before the
job is enqueued.

## slurm_job_id Persistence

The allocation wrapper writes `REVODESIGN_JOB_ID=<numeric-id>` as its first
stdout line. The worker stores that real SLURM ID in the `slurm_job_id` column
of the tasks table so cancellation and restart recovery can address the
allocation directly. Composed tasks additionally persist all stage handles and
states in `workflow_state`; `slurm_job_id` remains the currently active handle.

## Live Output

The `SlurmJob` class captures `srun` stdout/stderr via `subprocess.Popen`
pipes in background threads. `REVODESIGN_STAGE:` markers are parsed from
stdout in real time and forwarded to the stage callback, preserving live
progress updates for Slurm tasks.
