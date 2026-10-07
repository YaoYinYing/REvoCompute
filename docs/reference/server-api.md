# REvoCompute Server API

The checked-in `revocompute/static/openapi.json` is the authoritative API
contract. The interactive contract is served at `/api-docs` and the JSON
document at `/openapi.json`.

## API model

`revocompute/static/openapi.json` is the authoritative machine-readable
description of the **public client API**: the paths, HTTP methods,
request/response shapes, and schemas that clients and agents should rely on. It
is a curated contract rather than an exhaustive dump of every registered Flask
route. This page explains the model behind that surface and deliberately does not
restate a route table, which would silently drift from the authoritative
document.

Browse the interactive contract at `/api-docs`, fetch the JSON at
`/openapi.json`, or generate a local inventory directly from it:

```bash
curl -s https://<host>/openapi.json \
  | python -c "import json,sys; [print(m.upper(), p) for p, ops in json.load(sys.stdin)['paths'].items() for m in ops if m in {'get','post','put','delete','patch'}]"
```

The surface groups into a few concepts rather than one flat list:

- **Discovery and bootstrap** — the compact enabled Task catalog, one Task's
  scientific/input/access contract, the canonical parameter schema, the
  anonymous agent guide, and the current user's GPU balance.
- **Submission** — Core-owned preflight and submission, which validate
  transport, logical roles, the declarative Task contract, and current
  admission before any Runner-owned code runs.
- **Execution** — status and execution trace, cancellation, and deletion for
  owned Tasks.
- **Results** — the result manifest, authorized artifact and range responses,
  asynchronous archive requests, and completed archive downloads.
- **Administration** — GPU-credit adjustments, allowances and resets, Runner
  access policies and requests, and the operational log surface.

Each area is described below at the level of semantics; the OpenAPI document
owns its exact paths, parameters, and response schemas.

## Browser authentication and legal resources

Browser presentation is frontend-owned, while authentication and legal source
data remain server-owned. `GET /compute/api/auth/registration` reports the two
bounded registration capabilities: whether self-registration is enabled and
whether an email service is available. CAPTCHA creation, registration,
forgot-password requests, and verification resend remain explicit auth APIs.

Password-reset and email-verification links carry one opaque `token` query
parameter to the frontend routes. Loading those routes does not validate the
token or mutate an account. The frontend submits the unchanged token to
`POST /compute/api/auth/reset-password` or
`POST /compute/api/auth/verify-email`; the server alone validates token class,
signature, expiry, user state, and token version where applicable.

`GET /compute/api/legal/terms` returns the bounded canonical Markdown from
`revocompute/legal/TERMS_OF_SERVICE.md` together with a content-derived SHA-256
version. The repository document is the only legal-text source; clients render
that text without enabling arbitrary embedded HTML.

## Resource Entitlement

`GET /compute/api/resource-entitlement` returns the authenticated user's
canonical resource envelope; the administrator counterpart
`GET /compute/api/auth/admin/users/{user_id}/resource-entitlement` returns the
same shape for one user. This is the single projection for resource state:
placement, reporting, and other consumers read it rather than re-deriving a
balance from the ledger.

Everything is reported in base units — integer seconds, bytes, and counts —
with a `unit` field naming which. Four concepts stay separate: **accounting**
records what was actually allocated or owned; **policy** is what a subject may
consume or retain; **telemetry** describes how effectively an allocation was
used and is never quota consumption; **lifecycle** is whether durable data is
retained, independent of the Task's execution status.

The envelope contains:

- `compute`: one entry per unit admission decides on, always for the
  class-agnostic scope. GPU compute (`gpu_second`) is the enforced unit today;
  CPU core-seconds is recorded and reported with `enforced: false` and
  `allowance: null`. The deployment has one GPU allowance spanning every
  accelerator class, so the `gpu_second` entry is the single authority on "may
  this user run?" — a per-class balance could report a confident `yes` for one
  class while admission refuses at the shared balance. Per-class detail (a Slurm
  GRES class such as `a100`) stays a *report* of the same ledger, never a second
  entitlement.
- `storage`: `logical_owned_bytes` — user-facing quota consumption, measured
  from a Task's published result manifest — kept separate from physical
  filesystem capacity. It appears exactly once; mirroring it as a
  `storage_byte` compute entry would publish two numbers for one fact, and they
  diverge the moment a result is republished with a different size.
  `soft_limit_bytes` is a policy ceiling; a successful computation that crosses
  it keeps its scientific result and only later admission — of any Task, GPU or
  CPU — is refused.

### Accounting facts are append-only

Compute and durable-ownership facts share one append-only ledger. Database
triggers reject `UPDATE` and `DELETE` on it, so an administrative change is an
appended compensating entry, never a rewrite: allowance changes, adjustments,
and resets add rows, and the derived balance is a sum. Storage ownership is
charged once when a result is published and released once when a purge
completes, each with a unique idempotency key so a retry changes nothing.

### Unknown is not zero

Usage whose authoritative measurement has not arrived is reported as unknown,
not as zero. `used` counts only settled facts, while `unsettled_allocations`
counts allocations with no authoritative elapsed time yet and
`unsettled_quantity` is a conservative reserve for them; `remaining` already
subtracts that reserve, and `usage_complete` is `false` while any allocation is
unsettled. Admission applies the same rule, so a user with running work is not
admitted as if that work had consumed nothing. Each ledger fact also records an
`evidence_source` (`allocation_lifecycle`, `slurm_live`, `slurm_accounting`,
`runner_observation`, `reconciliation`, `policy`, or `unknown`).

When a lost GPU finish callback cannot be resolved from controller evidence, the
allocation stays unsettled and is left for review; it is never estimated and
never charged as zero.

## Data Lifecycle

Durable data has its own lifecycle, orthogonal to the Task's execution status: a
finished computation stays finished when its data is later archived or purged.
States are `ACTIVE`, `ARCHIVED`, `DELETE_REQUESTED`, `PURGING`, `PURGED`, and a
bounded `ERROR` for a purge that failed.

Deletion is a transaction, never "remove the files, then mark deleted". The
Task moves to `DELETE_REQUESTED` durably before any filesystem work, one worker
claims it into `PURGING`, and the quota that was charged is released only when
the owned bytes are actually gone. A crash anywhere in that sequence leaves a
resumable deletion, and a failed purge keeps the charge and its error so a later
pass can retry it. A partial purge therefore frees nothing, and a completed purge
releases exactly the bytes it charged, once. Recovery re-enters *from the durable
state*, so a stale `PURGING` row is reclaimed and retried and a worker that died
between its claim and its completion cannot hold a subject's quota forever.
`PURGED` is a lifecycle state rather than a tombstone, so a result published
again after a purge is charged again.

Deletion and publication cannot resurrect each other. A Task whose data is in a
deletion-ward lifecycle state is not republished by a worker that is still
finishing: the durable lifecycle row wins over the worker's result tree, so a
delete that lands mid-finalization is not re-materialized and re-charged.

Automatic age-based purge is not enabled by default. An operator can turn on the
`resource-maintenance` periodic task with `RESOURCE_MAINTENANCE_SECONDS` (see
the configuration reference); it finishes *authorized* deletions and runs a
bounded reconciliation pass, and it never decides on its own that data is old
enough to delete.

## GPU Credits

GPU accounting is the displayed projection of the `gpu_second` entitlement
above; 60 GPU-seconds equal one displayed credit. Each user receives a lazy,
idempotent grant of 60,000 GPU-seconds for each UTC calendar month. A new period
starts at its configured allowance rather than adding to the previous balance,
so unused credits and overdrafts do not roll over.

Only active Slurm GPU allocation time is charged. Upload, preflight, Celery,
queue, and CPU-stage time are free. A positive balance admits an allocation;
that allocation may finish with an overdraft, but the next GPU allocation is
blocked until the current-period balance becomes positive. An allocation's
complete usage is charged to the UTC month in which the allocation started; the
period is never split across a month boundary.

An allocation records one fact per accounting unit it held: a `gpu_second`
fact for the GPUs, and always a `cpu_core_second` fact, because every Slurm
allocation is an allocation of CPU cores. Both are `allocated units × the same
authoritative allocation elapsed time`, both settle idempotently under their own
key, and both keep the raw base unit. They are allocation facts, never
utilization: the CPU-seconds and peak-memory numbers the runner wrapper reports
are telemetry and are deliberately not the accounting fact.

Admission takes a reservation before dispatch, and that reservation is the
Task's own authority at allocation start: the hold which admitted a submission
is not also counted against it, so a Task holding the period's final second is
never refused by its own reservation. Every *other* Task's committed reservation
and every unsettled allocation still counts against the balance. A reservation
has two ownership modes: a pre-dispatch hold with a TTL, and a scheduler-owned
commitment, from the moment the Slurm request exists, which no wall-clock
timeout may reclaim because the request may legitimately still be queued. The
commitment records the scheduler's own job id in the same write that makes it
scheduler-owned, so a reservation is never queued without the identity that
names its request, and reconciliation decides whether to free it from that
identity and the scheduler's answer — never from a Task-row handle that is
persisted separately, and never from elapsed time. A commitment the scheduler
proves is gone is released by that evidence, but a commitment over a request
that already has a recorded allocation is settled from that evidence instead:
the claim is consumed by the allocation, never handed back as if nothing ran.

### The allocation fact and the admission grant are separate

The scheduler handing over resources is a fact; whether a subject may run the
scientific command is a policy decision. The two are recorded separately, so a
policy outcome can never rewrite the scheduler's fact. Recording the allocation
writes one active fact per accounting unit first, unconditionally and
idempotently, keyed by the scheduler's job id. The grant decision then runs in
the same transaction and records its outcome *on* that fact: `granted`, a
bounded `denial_code`, and the instant it was adjudicated. A denied allocation
stays active and is still settled for what the wrapper actually held; the
scientific command is withheld, not the fact erased. Running out of credit, an
unavailable authorization, or a runner that is not ready are all denials of the
grant, never of the allocation. A retry — after a crash, a duplicate callback,
or a workflow re-entry — reads the recorded decision instead of making a second
one against a balance the first already moved.

Knowing a scheduler job id is not the same as holding an allocation. The
wrapper publishes its job id as soon as it starts, and that identity alone
dispatches — moves the reservation from held to queued. Only evidence that the
allocation is actually running starts accounting: the wrapper confirms from the
scheduler's own state that its job is `RUNNING` and reports that before it runs
the scientific command. A request that waits in the queue, or is cancelled
before it ever runs, therefore charges nothing and holds nothing after the
release, however long it waited.

The wrapper printing its *own* job id is itself execution evidence, because it
can only do so from inside the allocation. But the allocation is created by the
scheduler, not by anything the worker writes, so the fact has to survive outside
the worker process. The wrapper's first statement — before any gate wait, any
output, and any scientific work — atomically writes a *receipt* (`slurm_job_id`,
the compute node's own `observed_at`, and the resources the scheduler granted
it) into the host-only directory that is never bind-mounted into the container.
Only then does it emit its job-id line. The scheduler starts the allocation
before the wrapper runs, so a node killed between those two instants still
leaves a receipt whenever the wrapper got as far as its first statement; the
only remaining gap is the window between the scheduler starting the job and the
wrapper executing, which no in-job mechanism can close and which the receipt
schema is dated to make visible.

Recovery keys on the receipt, not on the log line, and a receipt is a claim about
a scheduler job, so it is corroborated against the scheduler before anything is
recorded: a receipt for a job the scheduler owns is folded into the one
`slurm_job_id`-keyed allocation fact, idempotently, and settled from the
scheduler's elapsed time; a receipt for a job the scheduler does not report
records nothing and is kept for an operator rather than silently discarded. A
reservation whose request has a receipt is never expired or reclaimed as though
the allocation had not happened, and a claim the balance cannot cover still
withholds the command while its allocation is settled for what was held.

Ownership of the receipt moves monotonically. The worker reads the file, records
it as a server-owned receipt row, and writes the allocation fact; only once that
successor is durable does the runner delete the file, and an unlink failure is
harmless because the same claim is adopted again on the next pass. A worker that
dies between the read and the write leaves the file exactly where it is, so
restart reconciliation walks the host-only allocation namespace (`<results
root>/users/<storage key>/tasks/<task id>.allocation/allocation.receipt`),
corroborates each surviving claim against the scheduler, records it, and deletes
the file only after that adoption succeeds. There is therefore no sequence of
failures in which a real allocation has neither its file, its receipt row, nor
its canonical fact, and a malformed or uncorroborated receipt is never deleted —
an anomalous durable observation stays inspectable.

The observation and the scheduler-owned reservation transition are one atomic
store write, so there is no durable state in which a request is queued with a
scheduler identity but without the allocation its own job id proves. The
observation carries unknown elapsed time, never zero, and the later start
completes the same fact under full lifecycle provenance. A wrapper whose
execution evidence cannot be persisted is torn down rather than released: the
scientific command never runs on an allocation whose fact was not recorded.

Immediately before approving a real GPU allocation, the worker atomically
checks the current server-published account, GPU-permission, entitlement, and
credit projection in the compute database, plus the deployment-owned Runner
build/live-test attestation. Revocation and account-disable operations deny the
authorization projection before changing authentication state, while grants
are projected only after the authoritative authentication transaction
succeeds. The worker never opens the authentication database. Runner readiness
is availability evidence for whether the infrastructure can run the allocation;
it never becomes the source of quota or accounting truth.

Administrators can inspect a user's accounting at
`GET /compute/api/auth/admin/users/{user_id}/gpu-credit` and append a reasoned,
idempotent adjustment at the corresponding `/adjustments` route. Adjustments
are compensating entries: historical grant, usage, and adjustment rows are
immutable.

`PUT /compute/api/auth/admin/users/{user_id}/gpu-credit/allowance` sets a
per-user monthly policy. It applies to future UTC-month grants, and an
immutable allowance delta makes the new amount effective in the current
period without rewriting prior ledger rows.

`POST /compute/api/auth/admin/users/{user_id}/gpu-credit/reset` restores one
user's current-period remaining balance to that user's effective monthly
allowance, in either direction. It appends one `admin_reset` ledger entry: a
compensating delta when a change is needed, or a durable zero-value marker when
the balance is already at the allowance. The marker contributes nothing to the
derived balance but reserves the idempotency key, so a later retry cannot apply
a new reset after the balance changes. Zero-value markers are hidden from the
user's own history and retained in the administrative audit view. Reset never
erases GPU usage history: usage and prior adjustments are never modified or
deleted, and GPU permission (`allow_gpu_use`) is independent of the reset.

`POST /compute/api/auth/admin/gpu-credit/reset` applies the same operation
independently to every current non-deleted account, respecting per-user
allowance overrides rather than normalizing to the default. Both endpoints
require a human-readable administrator reason and an idempotency key; an
identical retry reuses the original entry, and one global reset writes all
per-user entries in a single transaction sharing one `batch_id`.

Recovering a lost GPU finish callback is intentionally minimal and requires no
Slurm accounting service. The normal path settles from REvoCompute's own
allocation record; after a restart, an unsettled allocation gets one best-effort
`scontrol show job <jobid>` query. If the controller still exposes a terminal
state plus a trustworthy runtime, usage is settled from that evidence;
otherwise the allocation is marked for review and never estimated or charged.
`sacct`, SlurmDBD, JobComp, and QOS are not dependencies of GPU accounting.

## User Metrics

`GET /compute/api/user-metrics?window=daily|weekly|quarterly|yearly` is a
read-only aggregation over the authenticated user's own persisted Tasks; the
response never includes another user's Tasks. The window selects both the span
and the activity bucket period: `daily` covers 30 days, `weekly` 30 weeks,
`quarterly` 8 quarters, and `yearly` every calendar year the user has Tasks in.
The default window is `daily`. The response reports submitted / completed /
failed counts, success rate, CPU and GPU Task counts, GPU minutes (one credit
is one GPU-minute), runner/TaskType distribution, total and median runtime, and
an activity series bucketed by that period.

Each activity point is the ISO start date of its bucket (the first day of the
week, quarter, or year) with a Task count; empty buckets are reported as zero.
GPU classification resolves through the TaskType contract, and the period
boundaries are resolved server-side. The endpoint reads existing Task rows and
their GPU allocation records; it maintains no analytics table and writes
nothing. An unknown window is rejected with `400`.

## Task Preflight

`POST /compute/api/preflight/{task_type}` accepts the same multipart input,
role, workspace, and `params[...]` fields as submission,
with the TaskType supplied by the path. It runs the same authoritative Core
security, contract, and current admission path as `POST /compute/api/post`.
A passing response contains normalized parameters and safe role/format/path
summaries. Preflight never creates a durable Task or Task ID, retains uploaded
bytes, consumes GPU credits, or queues compute work. Submission always reruns
the checks; clients must not treat an earlier result as an admission token.

Preflight is Core-owned and generic: it validates transport, format, logical
roles, the declarative Task contract, and current admission using server-owned
code only. Runner-owned workspace normalization and validation entrypoints are
part of real Task preparation and are never invoked by the read-only preflight
endpoint. A successful preflight therefore proves that no Runner-owned Python
entrypoint ran. Uploaded files and the `workspace` document both pass the same
bounded Core JSON policy before any Runner code can inspect them.

## Runner Access

Authenticated clients can inspect effective runner access at
`GET /compute/api/access` and submit an access request with
`POST /compute/api/access/requests`. Administrators can inspect policy summaries,
policy details, and access events under `/compute/api/auth/admin/access/*`, and
clear a user's policy suspension with
`/compute/api/auth/admin/users/{user_id}/access/{policy_id}/clear-suspension`.

The OpenAPI document (contract version `3.1.0`) defines the `RunnerAccess`,
`ResultManifest`, and `Artifact` schemas. Clients should treat manifest artifact
roles and the server-provided task JSON Schema as opaque contract data rather than
reconstructing scientific semantics locally.

## Task Parameter Reference

`GET /compute/api/task-parameters/{task_type}` requires no authentication and
returns the `parameters` mapping from the enabled TaskType's owning
`task.yaml` as JSON Schema. The response preserves each property's JSON Schema
type, default or required status, enum/range/format constraints, and scientific
description. Unknown and disabled TaskTypes return `404`.

This endpoint is the stable machine-readable parameter reference.
`GET /compute/api/types/{name}` links to it with `parameters_url` and does not
embed a duplicate schema. Clients must not maintain a second parameter registry
or infer help text from parameter names.

For example, a client may inspect a restricted Task contract before logging in:

```bash
curl https://<host>/compute/api/task-parameters/alphafold3
```

The response is the schema itself. It looks like this in shape, with the
parameter names, defaults, and bounds supplied by the owning `task.yaml` rather
than reproduced here:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "<parameter_name>": {
      "type": "<json-schema type>",
      "default": "<owning task.yaml default>",
      "minimum": "<owning task.yaml minimum>",
      "maximum": "<owning task.yaml maximum>",
      "description": "<owning task.yaml description>"
    }
  }
}
```

This is an explicitly schematic shape, not a parameter inventory. The actual
response is generated from the owning `task.yaml`, so read live values from
`GET /compute/api/task-parameters/{task_type}` instead of copying them into
documentation. Discovery is anonymous; authentication, entitlement, readiness,
and validation are enforced when a Task is submitted and executed.

## Agent Capability Discovery

`GET /skills.md` is an anonymous, stable `text/markdown` API navigation guide.
It points agents to `/openapi.json` for HTTP protocol details,
`/compute/api/types` for the compact enabled Task catalog, the selected
`/compute/api/types/{name}` resource for scientific detail, and
`/compute/api/task-parameters/{task_type}` for the canonical parameter schema.
It does not enumerate TaskTypes, readiness, resources, or parameters. Accepted
submissions return `task_id`, `status_url`, and `results_url`; status responses
remain focused on execution state, and the result manifest is the terminal
artifact-discovery step. Submission still requires normal authentication and
authorization.

Task IDs are content-derived: the ID is a digest of the task type, the
normalized parameters, and the input hashes, so resubmitting identical content
addresses the existing Task rather than creating a second one. `POST
/compute/api/post` answers a resubmission with `302` and the existing follow-up
payload when that Task is `finished`, `202` when it is `pending`, `queued`,
`running`, or `deleting:*`, and `409` with the existing task's `status` when it
is terminal or holds a cleanup claim — `cancelled`, `deleted:*`, `cleaned:*`.
Task IDs are therefore not recycled: a terminal Task keeps its ID, and a new
run of the same method uses the changed parameter or input that gives it a
different content hash.
