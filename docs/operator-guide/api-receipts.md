# Production API Acceptance Receipts

A live test proves a *candidate* SIF on real Slurm before activation. A
production API acceptance receipt records what a **finished submission through
the public API** observably was, after the fact, from the running deployment's
own state. It is the machine-generated replacement for a hand-copied acceptance
narrative.

## What the receipt proves

The receipt is derived entirely from canonical state — the task store row, the
published `manifest.json`, the executor's own Slurm accounting, the deploy
stamp, and the bytes of every published artifact — so a reader can trace:

```text
exact deployment
  -> admitted task snapshot (role-resolved inputs and effective parameters)
  -> Slurm execution (job id, exit code, elapsed, peak memory)
  -> API-observed lifecycle (submitted -> started -> finished)
  -> ResultManifest v3 (views, logical files)
  -> exact published artifacts (path, size, re-computed sha256)
  -> factual observed summaries (scalar leaves of the published summary)
```

Every published artifact is re-hashed from the bytes on disk and compared with
the manifest that declares it, so the receipt refers to that exact result and
not to another task with similar numbers.

## What the receipt does not prove

- **Not scientific equivalence.** Hashing a production artifact proves the
  identity of that artifact; it does not establish agreement with a scientific
  reference. Summary observables are recorded as observed values, not compared
  against any pinned reference unless a separate comparator does so.
- **Not a Runner readiness or SIF validation.** That is `live-test` and
  `runner-status`. A receipt records one finished task; it authorizes nothing.
- **Not a scheduler author's claim.** Slurm resource facts come from the
  executor's `execution/*.resource.json`; when that evidence is absent the
  fields are `null` and the receipt says so.

## Capturing one

The operator path is read-only with respect to the deployment and takes only a
task id:

```bash
REVODESIGN_SERVER_ENV=/path/to/server.env \
  bash run/restart.sh api-receipt --task <task-id>
```

It reads `DB_PATH`, `RESULTS_FOLDER`, `CONFIG_DIR`, and `SERVER_BASE_URL` from
the selected environment file and writes the receipt to
`<CONFIG_DIR>/api-receipts/<task-id>.json`. It prints a one-screen summary and
exits non-zero when the receipt is incomplete or inconsistent.

The task must be a finished success with a published ResultManifest. A
non-terminal task, a manifest naming a different task, an artifact missing or
whose bytes disagree with the manifest, a missing deploy stamp, a nonzero Slurm
exit code, or a malformed/negative lifecycle interval are all recorded in the
receipt's `problems` list and make it `complete: false`; the generator never
reports `complete` over incomplete evidence.

Each deployment keeps its receipts on the host under
`<CONFIG_DIR>/api-receipts/<task-id>.json`. A family that wants an accepted
receipt reviewed with its own code checks the captured document into the runner
tree, for example `docker/runners/<family>/receipts/production-api-<task-id>.json`,
and makes no other change: the receipt is a document the tool produced, not a
second source of truth the repository maintains by hand.

## Receipt shape

`revocompute/api_receipt.py` builds and validates the document;
`run/revocompute_ctl/api_receipt.py` reads the deployment and persists it. The
document carries `receipt_version`, `kind`, `captured_at`, `task_id`, a
non-secret `host.endpoint_host`, `deployment`, `submission`, `scheduler`,
`lifecycle`, `result` (manifest identity, views, logical files, artifact
inventory), `observables`, `api_status_evidence`, `problems`, `complete`, and a
`receipt_digest` that is stable for the same evidence apart from `captured_at`
and the digest itself.

`deployment.runtime_sif_sha256` is the promoted SIF the task's Runner executed,
hashed from disk when the operator could reach it; it is `null` otherwise,
never a copied value. `deployment.commit`, `dirty`, and `mode` come from the
deploy stamp, so a localized deployment reports `dirty: true` and a reader knows
the tree is not exactly the named commit.

Reading a receipt back verifies it: `revocompute/api_receipt.py:parse_api_receipt`
recomputes `receipt_digest` over the document and fails closed when it disagrees
or is absent, so a tampered artifact hash or summary value cannot parse. Only the
volatile capture metadata (`captured_at`) and the digest itself are excluded from
the body, which is why editing `captured_at` alone is harmless.

The receipt never stores tokens, cookies, Authorization headers, passwords,
proxy credentials, or raw environment. Key names matching the project's secret
rules are dropped, and a credential-shaped value that arrived under any other
key is redacted and recorded as a problem.

## Reusing it for another Runner

Nothing in the generator special-cases a Runner. The receipt is resolved from
the task's own state: the manifest names the task type, its views, and its
logical files; the summary is located through the manifest's logical-file
projection (a logical id `summary`, or the artifact named `summary.json`);
scheduler facts are located by the executor's `execution/*.resource.json`
convention. Any Runner whose finished task publishes a ResultManifest v3 and
runs under the Slurm executor produces a receipt through the same command, with
no code change.
