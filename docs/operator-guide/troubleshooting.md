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
