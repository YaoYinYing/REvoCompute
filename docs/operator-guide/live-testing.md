# Live Testing and Receipts

Live acceptance is an end-to-end target-host test, not a unit-test substitute.
It must use the production TaskDefinition and ExecutionPlan, the configured
worker identity, Slurm submission, the exact candidate Apptainer SIF, parser,
artifact paths, mounts, and resource policy. The test workspace and database
are isolated from production records.

```bash
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh live-test \
  --runner <family> --collection smoke
```

The report records the case, effective UID/GID, scheduler user/job, SIF hash,
runtime and task identities, policy digest, timing, resource observations,
logs, parsed outputs, and artifact acceptance. A PASS receipt is promotable
only when every required case passes and its hashes still match the candidate.
Never edit or hand-create a receipt. GitHub-hosted CI may mock OS/HPC
boundaries, but it cannot establish target-cluster readiness.

The deployment operator and production service identity are intentionally
different. `live-test` is invoked by the deployment account (for example,
`yinying`), then delegates the scientific task to the running Compose worker,
which executes as the configured `RUNNER_UID:RUNNER_GID` (for example,
`revodesign` 129:137). The worker submits the real Slurm/Apptainer task and
returns execution UID/GID and scheduler-user evidence. A promotable PASS must
show both the configured service identity and scheduler username; operators do
not log in as the service account or use `sudo`.
