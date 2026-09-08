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
