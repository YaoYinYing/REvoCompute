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

## GPU Credits

GPU accounting uses integer GPU-seconds; 60 GPU-seconds equal one displayed
credit. Each user receives a lazy, idempotent grant of 60,000 GPU-seconds for
each UTC calendar month. A new period starts at its configured allowance rather
than adding to the previous balance, so unused credits and overdrafts do not
roll over.

Only active Slurm GPU allocation time is charged. Upload, preflight, Celery,
queue, and CPU-stage time are free. A positive balance admits an allocation;
that allocation may finish with an overdraft, but the next GPU allocation is
blocked until the current-period balance becomes positive. An allocation's
complete usage is charged to the UTC month in which the allocation started; the
period is never split across a month boundary.

Immediately before approving a real GPU allocation, the worker atomically
checks the current server-published account, GPU-permission, entitlement, and
credit projection in the compute database, plus the deployment-owned Runner
build/live-test attestation. Revocation and account-disable operations deny the
authorization projection before changing authentication state, while grants
are projected only after the authoritative authentication transaction
succeeds. The worker never opens the authentication database.

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

`GET /compute/api/user-metrics?window=7d|30d|90d|quarter` is a bounded,
read-only aggregation over the authenticated user's own persisted Tasks; the
response never includes another user's Tasks (default window `30d`). The
response reports submitted / completed / failed counts, success rate, CPU and
GPU Task counts, GPU minutes (one credit is one GPU-minute), runner/TaskType
distribution, total and median runtime, and a bounded per-day activity series.

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
