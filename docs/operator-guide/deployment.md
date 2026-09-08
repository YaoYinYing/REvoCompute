# Deployment Lifecycle

This page explains the lifecycle and points to the [deployment control
reference](deployment-control.md) for the authoritative command and option
semantics. The operator account invokes the controller; service and scheduler
identity are configured separately and must be validated before activation.

## Lifecycle

1. **Prepare** materializes server-owned configuration and selected Runner
   families. With `--build-sif`, direct Apptainer candidates are built while the
   healthy deployment remains online.
2. **Inspect** runs strict Doctor checks and verifies mounts, access policies,
   definitions, provenance, and resource policy. Fix the owning contract when a
   check fails; do not bypass it with a manual status value.
3. **Live-test** executes the production TaskDefinition through Slurm and
   Apptainer using an isolated test workspace. Only a complete, current receipt
   for the exact candidate can support promotion.
4. **Promote** uses `restart --mode=prepared`. Preflight runs before services
   stop; candidates are atomically activated only when hashes and receipts
   match. Otherwise the active SIF and services remain unchanged.
5. **Operate** with `runner-status --all`, scheduled maintenance, backups, and
   log rotation. Revalidation is required after changing code, task schemas,
   resource policy, mounts, or runtime inputs.

## Maintenance window

Prepared activation places the gateway in maintenance mode for the short stop,
start, and health-check window. New submissions are rejected during that
window; already-running tasks are allowed to finish. If preflight fails, leave
maintenance, retain the previous artifact, and investigate the reported stage.

## Minimal command sequence

```bash
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh prepare \
  --enabled-runners=<family> --build-sif
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh live-test \
  --runner <family> --collection smoke
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh runner-status --all
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh restart --mode=prepared
```

CI documentation builds validate links and syntax only. They do not create
target-host receipts or prove production readiness.
