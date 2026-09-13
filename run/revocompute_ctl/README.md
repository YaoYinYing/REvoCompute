# Server Control Module

`run/revocompute_ctl` is the deployment boundary for a REvoCompute server
instance. It owns environment loading, runner-family materialization, image
preflight, Compose orchestration, storage preparation, maintenance transitions,
and deploy stamps. It does not define scientific tasks or runner semantics.

## Control flow

```text
restart.sh
  -> EnvState / command parsing
  -> preserve/finalize in-flight work through the current worker
  -> stop the current services
  -> atomically materialize enabled docker/runners/<family> trees
  -> discover and validate the new snapshot and deployment artifacts
  -> build/pull, activate, start, reconcile, and write a deploy stamp
```

The materialized `SERVER_DIR/docker/runners` tree is the server instance
snapshot. An existing empty tree is authoritative and represents zero enabled
families; the controller must not silently fall back to the source checkout.
Every service receives this path as a read-only mount and `RUNNERS_DIR`; a
mutable `RUNNER_SOURCE_ROOT` is only read after the old stack has stopped.
Updating the checkout therefore cannot change TaskType discovery for a running
instance. If the current worker cannot cancel scheduler jobs and preserve task
state, restart aborts before Compose stops anything. New-revision validation
failures are explicit and leave the stack stopped for operator correction.

## Supported execution contract

Scientific execution is always `SlurmExecutor` plus an Apptainer container.
Runner manifests provide SIF metadata and task-owned execution plans; the
controller translates those declarations into deployment/build operations but
does not add native or host execution fallbacks. Docker Compose builds and
runs server services only; Runner SIFs build directly with Apptainer.

## Common commands

```bash
REVODESIGN_SERVER_ENV=/path/server.env bash run/restart.sh setup
REVODESIGN_SERVER_ENV=/path/server.env bash run/restart.sh prepare --enabled-runners=<family> --build-sif
REVODESIGN_SERVER_ENV=/path/server.env bash run/restart.sh live-test --runner <family>
REVODESIGN_SERVER_ENV=/path/server.env bash run/restart.sh restart --mode=prepared
REVODESIGN_SERVER_ENV=/path/server.env bash run/restart.sh down
```

Keep environment files private (`0600`) and never include credentials in
commands, logs, deploy stamps, or reports. Validate changed controller code
with `bash -n run/restart.sh` and the focused process-isolation/restart tests.
