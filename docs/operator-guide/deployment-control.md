# REvoCompute deployment control

`run/restart.sh` controls a Docker Compose server and direct Apptainer Runner
artifacts. Docker remains responsible for Redis, web, worker, gateway, and
maintenance services. Scientific Runner families have no Docker build stage.

## Artifact flow

```text
family .def + declared build inputs
  -> apptainer build --fakeroot <artifact>.next.build
  -> atomic <artifact>.next
  -> apptainer inspect/test
  -> normal Task request -> ExecutionPlan -> real Slurm -> exact candidate SIF
  -> normal result parsing and artifact contracts
  -> exact-hash PASS receipt
  -> prepared restart atomically promotes <artifact>.next
```

A candidate never replaces the active SIF merely because it built. Promotion
requires a receipt matching the candidate SHA-256, build-provenance digest,
family `test.yaml` and fixture digest, execution-contract digest, and every required
smoke case. Failed builds and tests leave the active artifact untouched.

Build provenance records family and release metadata for audit, plus the
definition and declared-input hashes, Apptainer version, resulting SIF hash,
and timestamp. Build freshness uses only actual image inputs; changing
`family.version` alone does not stale the SIF. Evidence contains no credentials
and has no Docker image ID. See the canonical
[Runner change-impact model](../runner-guide/adding-a-runner.md#runner-change-impact-model).

## Runner readiness

Runner readiness is a deterministic view over the active SIF and existing
evidence. It is not stored as a mutable flag and querying it does not build,
test, promote, or repair anything.

```bash
# Concise table for every enabled family
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh runner-status --all

# Detailed single-family status, or stable machine-readable output
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh runner-status --runner alphafold3
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh runner-status --runner alphafold3 --json
```

| Status | Meaning | Next action |
|---|---|---|
| `NOT_CONFIGURED` | Strict-equivalent Doctor contract checks fail | Fix the reported contract and run Doctor again |
| `NOT_BUILT` | The active production SIF is absent | Run `prepare --build-sif` for the family |
| `BUILD_STALE` | Active SIF provenance differs from the definition or declared build inputs | Rebuild and validate a candidate |
| `NOT_VALIDATED` | Current active SIF has no live receipt | Run `live-test --runner <family>` |
| `VALIDATION_STALE` | Build is current, but the receipt differs from the execution/test/resource identity or required smoke coverage | Keep the SIF and rerun the live-test |
| `READY` | Doctor passes and the exact current active SIF passed all required current smoke cases | None |

`runner-status` evaluates `<artifact>.sif`, not a staged
`<artifact>.sif.next`. `READY` does not grant a user access to a restricted
Runner and does not imply an idle GPU, short queue, or currently available
Slurm partition. Authorization and transient scheduler health remain separate.

The exact freshness action is therefore:

- `BUILD_STALE`: run `prepare --build-sif`, live-test the candidate, then
  promote it with a prepared restart.
- `VALIDATION_STALE`: do not rebuild; live-test the current SIF against the
  current execution contract, then deploy normally.
- `READY` after a presentation-only change: do not rebuild or live-test; deploy
  the server/config change normally.

## Commands

```bash
# Build the server web/worker images with Docker Compose
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh build

# Directly build selected candidate SIFs while production remains up
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh prepare \
  --build-sif --enabled-runners=gremlin

# Real target-cluster acceptance of an exact candidate
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh live-test \
  --runner gremlin --collection smoke

# Alternatives: select a TaskType or every family
bash run/restart.sh live-test --task gremlin
bash run/restart.sh live-test --all --collection smoke

# Validate first, then stop/start and promote receipted candidates
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh restart --mode=prepared
```

`prepare` and `live-test` do not stop or recreate the healthy deployment. Run
them as the deployment account, never via `sudo`; the deployment operator is
not required to be the production service account. Live-test builds or selects
the candidate server image, then delegates the scientific path to a one-off
worker container from that candidate image. The container inherits the worker
service boundary and executes as the configured service identity. The
candidate worker must run on the actual
Slurm/Apptainer installation with production mounts, weights, databases,
resource policies, and licensed access available.

## Restart modes

| Mode | Server action | Runner action |
|---|---|---|
| `dev` | Build local server images, then Compose up | Validate active artifacts; `--build-sif` may stage direct candidates |
| `prod` | Pull configured server images, then Compose up | Validate active artifacts; no Runner image pull |
| `prepared` | Preserve current tasks, stop, then validate local server images and Compose | Copy the new snapshot, validate provenance and exact receipts, then promote staged candidates |

`--dry-run` is restart-only. `--keep-gateway` keeps Nginx serving maintenance
while the application services stop. `--server-only` is accepted by `build`.
`--use-proxy` supplies the configured build-time proxy to server Docker builds
and direct Apptainer definitions. Runtime images should still clear proxy
variables unless their scientific contract explicitly requires network access.

## Safety and storage

The controller takes a per-environment deployment lock. A running instance uses
only its materialized `SERVER_DIR/docker/runners` snapshot, mounted read-only
into web, worker, and maintenance services. Repository changes and
`RUNNER_SOURCE_ROOT` updates cannot mutate it. During restart, the controller
first asks the current worker to preserve/finalize in-flight work; any sweep or
scheduler-cancellation failure aborts before `compose down`. After shutdown it
atomically copies the selected family trees plus shared
`docker/runners/common` inputs into the new instance snapshot, validates access
policies and paths, and stages SIFs in the deployment image directory. Builds
use a `.next.build` temporary target and an atomic rename. Reports live under
`images/live-tests/<family>/`; build records
records live under `images/evidence/<family>/<sif-sha256>.build.json`; receipts
add a validation-contract digest before `.receipt.json`.

Prepared new-revision preflight occurs after service shutdown, so it cannot
load newer manifests into older running Python code. Missing server images,
invalid Compose, stale SIF provenance, or an absent/mismatched candidate
receipt aborts activation without starting an inconsistent stack.

The deployment’s external auth, management, task, result, and workspace stores
retain their existing ownership and backup rules. The live worker creates an
isolated test database/workspace and copies only immutable fixtures from
`tests/data`; it does not alter production task records.

## Failure diagnosis

Live reports use stable categories: `BUILD_FAILURE`,
`SIF_VALIDATION_FAILURE`, `TEST_CONFIGURATION_FAILURE`, `RESOURCE_MISSING`,
`INPUT_SEED_FAILURE`, `SUBMISSION_FAILURE`, `RUNTIME_FAILURE`, `TIMEOUT`,
`RESULT_PARSING_FAILURE`, `ARTIFACT_ACCEPTANCE_FAILURE`,
`RESOURCE_OBSERVATION_FAILURE`, and `GPU_ACCOUNTING_FAILURE`.

GitHub-hosted CI may mock only OS/HPC boundaries to check orchestration. It
does not write PASS receipts and is not evidence of target-cluster readiness.
Only the target-host `live-test` command can issue a promotable receipt.

## Helper script walkthrough

### Recommended helper script

No sudo required.

```bash
# initialize the env file and print detected Docker socket group
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh setup

# development: down + local build using host UID/GID + up
REVODESIGN_SERVER_ENV=.env.local bash run/restart.sh restart --mode=dev

# production: down + pull configured Docker Hub images + up without building
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh restart --mode=prod

# prepared production: preflight local images/SIFs/config, then down + up only
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh restart --mode=prepared

# subcommands
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh build
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh up
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh down
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh reload
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh reset-passwd <username>
```

`restart` defaults to `--mode=dev` for backward compatibility. Only the
`--mode=value` spelling is accepted, and mode is independent from the selected
environment file:

- `REVODESIGN_SERVER_ENV` selects paths, secrets, and resource settings.
- `--mode=dev` builds the server image locally, then starts with
  `--no-build`. This is the authoritative development workflow and preserves
  host UID/GID ownership for writable bind mounts.
- `--mode=prod` pulls the configured server images, then
  starts with `--no-build`. It requires `RUNNER_USERNAME` and `RUNNER_GROUP` to
  resolve on the host, and rejects an explicit `RUNNER_UID` or `RUNNER_GID` that
  does not match those account records.
- `--mode=prepared` activates locally prepared production artifacts. Before it
  stops anything, it verifies server Docker images, every required SIF and
  candidate receipt, runner files, auth-storage separation, and the
  rendered Compose model. It performs no build or pull, starts with
  `--no-build`, and waits for all five Compose services to report running.
- `job_executor: slurm` in the selected registry automatically merges
  `docker-compose.slurm.yml`, bind-mounts SLURM client tools + MUNGE, and
  validates SIF images. The admin database controls whether submissions are
  enabled.
- `prepare --build-sif` stages each stale SIF as `<sif>.next` while the stack
  stays up; a later `restart --mode=prepared` atomically replaces it after
  `down` (requires Apptainer on PATH). Candidates without a target-cluster
  smoke receipt are never promoted.

Provision production bind-mounted directories as writable by the configured
service UID/GID. This identity contract provides non-root execution and
compatible file ownership; it is not a container-escape boundary. The worker's
Docker socket access still grants effective Docker-daemon/host-level authority.

Create a writable `AUTH_DIR` before the first start. The web process creates
`${AUTH_DIR}/users.sqlite3` with the current schema. Existing databases must
already match that schema; server setup does not migrate them.

Personal task ownership/storage is a destructive development-state epoch.
For the one-time upgrade, stop REvoCompute and deliberately reset the test-era
user and task databases plus old workspace/results roots, and archive or delete
the retired `${SERVER_DIR}/collaboration.sqlite3`; then start the new release
and recreate users. Project, member, and invitation rows are not converted.
Startup validates the current schemas and fails with reset instructions when
old state is found; it never migrates or deletes retired state. An ordinary
restart never resets current databases or user storage. See
[Personal Task Storage and Artifacts](personal-task-storage.md#persistent-state-epoch)
for the canonical epoch procedure.

### Equivalent Docker Compose commands

These commands are equivalent only after `users.sqlite3` contains an account.
On a fresh installation, use the helper script's `up` or `restart` command so
it can generate and pass transient bootstrap credentials. A direct Compose
startup with an empty user database is rejected.

Development mode:

```bash
docker compose -f docker-compose.yml --env-file .env.local down
docker compose -f docker-compose.yml --env-file .env.local build web worker
docker compose -f docker-compose.yml --env-file .env.local up --no-build -d redis web gateway maintenance worker
```

Production mode:

```bash
docker compose -f docker-compose.yml --env-file .env.production down
docker compose -f docker-compose.yml --env-file .env.production pull web gateway
docker compose -f docker-compose.yml --env-file .env.production up --no-build -d redis web gateway maintenance worker
```

### Zero-downtime Gunicorn reload

```bash
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh reload
```
