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
