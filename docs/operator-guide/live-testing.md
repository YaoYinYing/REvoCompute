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

For `--all`, the controller builds the one-off server worker image once at
the start of the invocation, then reuses it for each family. Each family is
still validated and executed against its own exact Apptainer SIF; a server
image rebuild is not a substitute for SIF acceptance. If the worker image is
already prepared, the command proceeds directly to the per-family Slurm
tests.

The report records the case, effective UID/GID, scheduler user/job, SIF hash,
runtime and task identities, policy digest, timing, resource observations,
logs, parsed outputs, and artifact acceptance. A PASS receipt is promotable
only when every required case passes and its hashes still match the candidate.
Never edit or hand-create a receipt. GitHub-hosted CI may mock OS/HPC
boundaries, but it cannot establish target-cluster readiness.

The deployment operator and production service identity are intentionally
different. `live-test` is invoked by the deployment account (for example,
`yinying`), then delegates the scientific task to a one-off Compose worker
created from the candidate server image. It inherits the production worker
service boundary and executes as the configured `RUNNER_UID:RUNNER_GID` (for
example, `revodesign` 129:137). The candidate worker submits the real
Slurm/Apptainer task and returns execution UID/GID plus per-job scheduler-user
evidence. A promotable PASS must show the configured service identity and
`revodesign` for every required Slurm job; operators do not log in as the
service account or use `sudo`.
