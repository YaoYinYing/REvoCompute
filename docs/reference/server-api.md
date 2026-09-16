# REvoCompute Server API

The checked-in `revocompute/static/openapi.json` is the authoritative API
contract. The interactive contract is served at `/api-docs` and the JSON
document at `/openapi.json`.

## Core Routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/compute/api/types` | Compact enabled TaskType catalog and access state |
| `GET` | `/compute/api/gpu-credit` | Current user's UTC-month GPU balance and immutable history |
| `GET` | `/compute/api/types/{name}` | One task's scientific, input, and access contract |
| `GET` | `/compute/api/task-parameters/{task_type}` | Anonymous canonical Draft 2020-12 parameter schema |
| `GET` | `/skills.md` | Stable anonymous agent API bootstrap guide |
| `POST` | `/compute/api/preflight/{task_type}` | Validate a prospective task without durable or queue side effects |
| `POST` | `/compute/api/post` | Submit a validated task |
| `GET` | `/compute/api/running/{task_id}` | Status and execution trace |
| `POST` | `/compute/api/cancel/{task_id}` | Cancel an owned task |
| `DELETE` | `/compute/api/delete/{task_id}` | Delete one owned task |
| `POST` | `/compute/api/delete` | Batch-delete owned tasks |
| `GET` | `/compute/api/results/{task_id}` | Result manifest and archive state |
| `GET` | `/compute/api/results/{task_id}/artifacts/{path}` | Authorized artifact/range response |
| `POST` | `/compute/api/results/{task_id}/archive` | Request an asynchronous ZIP |
| `GET` | `/compute/api/download/{task_id}` | Download a completed ZIP |

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

Recovering a lost GPU finish callback is intentionally minimal and requires no
Slurm accounting service. The normal path settles from REvoCompute's own
allocation record; after a restart, an unsettled allocation gets one best-effort
`scontrol show job <jobid>` query. If the controller still exposes a terminal
state plus a trustworthy runtime, usage is settled from that evidence;
otherwise the allocation is marked for review and never estimated or charged.
`sacct`, SlurmDBD, JobComp, and QOS are not dependencies of GPU accounting.

## Task Preflight

`POST /compute/api/preflight/{task_type}` accepts the same multipart input,
role, artifact-reference, workspace, and `params[...]` fields as submission,
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

The response is the schema itself, including declarations such as:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "num_diffusion_samples": {
      "type": "integer",
      "default": 5,
      "minimum": 1,
      "maximum": 100,
      "description": "Number of structure samples generated by the diffusion head for each model seed."
    }
  }
}
```

This abbreviated example is not maintained as a parameter inventory. The
actual response is generated from the owning `task.yaml`. Discovery is
anonymous; authentication, entitlement, readiness, and validation are enforced
when a Task is submitted and executed.

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
