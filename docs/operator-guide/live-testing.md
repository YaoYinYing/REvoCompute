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
execution-contract identity, timing, resource observations,
logs, parsed outputs, and artifact acceptance. For a GPU case, PASS also
requires a settled allocation row whose Slurm job ID matches the execution,
whose GPU-seconds equal allocated GPUs times rounded-up allocation duration,
and whose append-only usage entry exactly matches the before/after credit
balance. Slurm accounting must record elapsed walltime, allocated CPUs, total
CPU time, and peak resident memory for every job. GPU jobs additionally require
the allocated GPU TRES plus peak GPU-memory and GPU-utilization observations.
A PASS receipt is promotable only when every required case passes and its
hashes still match the candidate.
Never edit or hand-create a receipt. GitHub-hosted CI may mock OS/HPC
boundaries, but it cannot establish target-cluster readiness.

Receipt contract changes invalidate prior PASS evidence even when the SIF and
Runner files are unchanged. Rerun `live-test` when `runner-status` reports
`VALIDATION_STALE`; old receipts are preserved as historical evidence but do
not authorize new submissions.

## What a PASS binds and activates

Before the cases run, `live-test` materializes the family's declared runtime
overlay as a candidate snapshot and pins that exact digest; it does not publish
it. A PASS names the exact `(SIF, Runtime Bundle)` pair together with its build
provenance, test definition, configuration, and composed companion identities.
Once every selected family's required cases pass, the command publishes exactly
the digests it validated and refreshes the deployment's admission attestation.
A failure publishes nothing: the prior binding remains and readiness keeps
reporting the family stale.

`setup` and `restart` apply the same gate to a changed binding. Without a valid
receipt for that exact family, digest, SIF build provenance, configuration, and
test definition they keep the prior binding; a deployment restart is never a
scientific acceptance.

A composed case binds the companion identities it actually ran: candidate
bundle digests for families selected in the same pass, and published digests
for unselected companions (with their SIF and build provenance). A later
companion identity change invalidates the composed receipt, and a missing
companion record refuses before submission. Stage every participating
family's candidate before a composed `live-test --all` pass (for example with
`prepare --build-sif`), or run the companion's live test first; a companion
`.next` staged only during the same pass can make the post-PASS gate refuse
activation even though every case passed.

A narrowed `--task` pass validates only the cases it selected. If its receipt
does not cover every required smoke case, activation is refused and the
command reports failure; rerun the full smoke collection.

## Bundle-only update

When only a `runtime_overlay` source changed, reuse the current SIF:

1. Confirm `runner-status --runner <family>` reports `VALIDATION_STALE` with
   `reason=RUNTIME_BUNDLE_CHANGED` and current SIF build provenance (see
   [Runner Readiness](runner-readiness.md#bundle-only-update)).
2. Run the family's live test. Do not run `prepare --build-sif`: no scientific
   SIF rebuild is needed. The one-off Docker worker image build at the start of
   the invocation is the orchestration boundary, not a SIF build.
3. On PASS the same invocation activates the exact validated snapshot; no
   separate deployment step is required. On failure the previous binding
   remains; correct the cause and rerun the live test.

```bash
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh runner-status \
  --runner <family>
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh live-test \
  --runner <family> --collection smoke
```

To return a family to an earlier accepted bundle without a rebuild or live
test, use `rollback-bundle` as listed under
[Deployment Control commands](deployment-control.md#commands).

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
