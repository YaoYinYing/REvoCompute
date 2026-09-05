# Server Control Module

`run/revocompute_ctl` is the deployment boundary for a REvoCompute server
instance. It owns environment loading, runner-family materialization, image
preflight, Compose orchestration, storage preparation, maintenance transitions,
and deploy stamps. It does not define scientific tasks or runner semantics.

## Control flow

```text
restart.sh
  -> EnvState / command parsing
  -> materialize enabled docker/runners/<family> trees
  -> discover and validate plugin manifests
  -> validate Docker images and (SLURM mode) Apptainer SIFs
  -> validate storage, identity, and rendered Compose model
  -> stop/activate/start services and write a deploy stamp
```

The materialized `SERVER_DIR/docker/runners` tree is the server instance
snapshot. An existing empty tree is authoritative and represents zero enabled
families; the controller must not silently fall back to the source checkout.
Prepared-mode validation completes before shutdown so a missing image, invalid
policy, unsafe asset, or storage/Compose error leaves a healthy deployment up.

## Supported execution contract

Scientific execution is always `SlurmExecutor` plus an Apptainer container.
Runner manifests provide image metadata and task-owned execution plans; the
controller translates those declarations into deployment/build operations but
does not add native or host execution fallbacks. Docker is used to build and
run server services and to build runner images, not as a second scientific
execution backend.

## Common commands

```bash
REVODESIGN_SERVER_ENV=/path/server.env bash run/restart.sh setup
REVODESIGN_SERVER_ENV=/path/server.env bash run/restart.sh prepare --enabled-runners=<family> --build-sif
REVODESIGN_SERVER_ENV=/path/server.env bash run/restart.sh restart --mode=prepared
REVODESIGN_SERVER_ENV=/path/server.env bash run/restart.sh down
```

Keep environment files private (`0600`) and never include credentials in
commands, logs, deploy stamps, or reports. Validate changed controller code
with `bash -n run/restart.sh` and the focused process-isolation/restart tests.
