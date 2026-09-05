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
family `test.yaml` digest, public configuration digest, and every required
smoke case. Failed builds and tests leave the active artifact untouched.

Build provenance records the family/version, definition and declared-input
hashes, Apptainer version, resulting SIF hash, and timestamp. It contains no
credentials and has no Docker image ID.

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

`prepare` and `live-test` do not stop the healthy deployment. Run them as the
deployment account, never via `sudo`. The live worker must run on the actual
Slurm/Apptainer installation with production mounts, weights, databases,
resource policies, and licensed access available.

## Restart modes

| Mode | Server action | Runner action |
|---|---|---|
| `dev` | Build local server images, then Compose up | Validate active artifacts; `--build-sif` may stage direct candidates |
| `prod` | Pull configured server images, then Compose up | Validate active artifacts; no Runner image pull |
| `prepared` | Validate local server images and Compose before stop | Validate provenance and exact receipts, then promote staged candidates |

`--dry-run` is restart-only. `--keep-gateway` keeps Nginx serving maintenance
while the application services stop. `--server-only` is accepted by `build`.
`--use-proxy` affects server Docker builds; direct definitions obtain their
build environment from Apptainer and the deployment account.

## Safety and storage

The controller takes a per-environment deployment lock. It materializes the
selected family trees plus shared `docker/runners/common` inputs into the
server instance, validates access policies and paths, and stages SIFs in the
deployment image directory. Builds use a `.next.build` temporary target and an
atomic rename. Reports live under `images/live-tests/<family>/`; receipts live
under `images/receipts/<family>.json`.

Prepared preflight occurs before service shutdown. Missing server images,
invalid Compose, stale SIF provenance, or an absent/mismatched candidate
receipt aborts activation without promoting the candidate.

The deployment’s external auth, management, task, result, and workspace stores
retain their existing ownership and backup rules. The live worker creates an
isolated test database/workspace and copies only immutable fixtures from
`tests/data`; it does not alter production task records.

## Failure diagnosis

Live reports use stable categories: `BUILD_FAILURE`,
`SIF_VALIDATION_FAILURE`, `TEST_CONFIGURATION_FAILURE`, `RESOURCE_MISSING`,
`INPUT_SEED_FAILURE`, `SUBMISSION_FAILURE`, `RUNTIME_FAILURE`, `TIMEOUT`,
`RESULT_PARSING_FAILURE`, and `ARTIFACT_ACCEPTANCE_FAILURE`.

GitHub-hosted CI may mock only OS/HPC boundaries to check orchestration. It
does not write PASS receipts and is not evidence of target-cluster readiness.
Only the target-host `live-test` command can issue a promotable receipt.
