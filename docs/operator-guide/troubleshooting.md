# Troubleshooting and Recovery

Classify the first failing lifecycle stage and fix its owning contract. Common
live-test categories are `BUILD_FAILURE`, `SIF_VALIDATION_FAILURE`,
`TEST_CONFIGURATION_FAILURE`, `RESOURCE_MISSING`, `INPUT_SEED_FAILURE`,
`SUBMISSION_FAILURE`, `RUNTIME_FAILURE`, `TIMEOUT`,
`RESULT_PARSING_FAILURE`, and `ARTIFACT_ACCEPTANCE_FAILURE`.

Inspect the report, worker log, Slurm job output, and SIF provenance; redact
secrets before sharing diagnostics. Re-run only the affected preparation or
test stage, then verify the full receipt before promotion. A failed prepared
restart leaves the prior active SIF in place. If services are unhealthy,
retain maintenance mode, restore the last known-good Compose/SIF pair, and
confirm health and task persistence before accepting new work. Never fabricate
READY, bypass Doctor, or overwrite receipts to recover availability.

## Operator executor unavailable

**Symptom.** The Admin fleet view shows `Operator executor unavailable`, the
mutating actions are disabled, and `POST .../operator/actions` returns a `503`
with code `executor_unavailable` and a reason. Readiness, capacity, access, and
history stay available.

Diagnose it without touching production artifacts:

1. Read the reason in the UI or in the `503` response. It names the missing
   artifact by role -- `run/restart.sh`, `REVODESIGN_SERVER_ENV`, or the
   deployment env file -- and never an absolute host path, so it is safe to
   paste into a report.
2. Decide which deployment this is. On a Docker Compose deployment the web
   process runs in a container: it ships no Docker and no Apptainer, and the
   host checkout is not mounted, so the executor is unavailable by design. See
   [Fleet Operations](fleet-operations.md#degraded-mode). This is not a fault;
   run mutations with `run/restart.sh` on the host.
3. On a host deployment whose server process sits beside the checkout, inspect
   the same deployment from that process's own environment:

```bash
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh runner-status --all
```

4. Correct that process's view of the deployment (expose the checkout beside
   the deployment env file, or set `REVODESIGN_SERVER_ENV` for the service),
   then restart normally.

Never make the executor reachable by adding the Docker socket to web, mounting
the host checkout or root filesystem, or letting a request supply a command or
path. The boundary is fail-closed for that reason, and the CLI already covers
every host mutation.

## Every SIF reads BUILD_STALE in the Admin view

**Symptom.** The Admin fleet view reports `BUILD_STALE` /
`BUILD_PROVENANCE_STALE` for families that `run/restart.sh runner-status` on the
host reports as current.

**Cause.** A build identity includes the Apptainer version that performed the
build. A server process that cannot run Apptainer contributes an empty builder,
which is a *different* builder, so its derived identity cannot match the
recorded one. The host controller shares its observation on every `up`
(see
[Deployment Control](deployment-control.md#the-recorded-apptainer-builder));
a split like this means the running containers did not receive it.

**Action.** Do not rebuild. Restart through `run/restart.sh` on the host so the
observation is shared, then re-check. If the host also has no Apptainer, the
build cannot be proven current from either process and the state is honest --
produce the artifact on the building host. See
[Runner Readiness](runner-readiness.md#why-the-admin-view-can-report-build_stale-while-the-cli-says-otherwise).

## Network and proxy issues

If `docker compose` failed due to network issues, try this:

1. Add proxy settings to your `/etc/systemd/system/docker.service.d/http-proxy.conf` file
2. Reload systemd service: `sudo systemctl daemon-reload`
3. Restart docker: `sudo systemctl restart docker`
4. Rerun restart scripts or `docker compose` commands under non-root user

A proper `http-proxy.conf` file might look like this:

```text
[Service]
Environment="HTTP_PROXY=http://proxy-user:proxy-password@proxy.internal:8080"
Environment="HTTPS_PROXY=http://proxy-user:proxy-password@proxy.internal:8080"
Environment="ALL_PROXY=http://proxy-user:proxy-password@proxy.internal:8080"
Environment="NO_PROXY=localhost,127.0.0.1,192.168.0.0/16,localhost,127.0.0.1,10.96.0.0/12,192.168.59.0/24,192.168.49.0/24,192.168.39.0/24,192.168.67.0/24,172.17.0.0/24,192.168.0.0/16,100.87.0.0/16,192.168.75.0/24,192.168.194.0/24,192.168.67.2"
```
