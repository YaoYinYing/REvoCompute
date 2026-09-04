# REvoCompute Server API

The checked-in [`openapi.json`](../revocompute/static/openapi.json) is the
authoritative API contract. The interactive contract is served at `/api-docs`
and the JSON document at `/openapi.json`.

## Core Routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/compute/api/types` | Enabled task and runtime metadata |
| `GET` | `/compute/api/types/{name}` | One task's schema and controls |
| `POST` | `/compute/api/post` | Submit a validated task |
| `GET` | `/compute/api/running/{task_id}` | Status and execution trace |
| `POST` | `/compute/api/cancel/{task_id}` | Cancel an owned task |
| `DELETE` | `/compute/api/delete/{task_id}` | Delete one owned task |
| `POST` | `/compute/api/delete` | Batch-delete owned tasks |
| `GET` | `/compute/api/results/{task_id}` | Result manifest and archive state |
| `GET` | `/compute/api/results/{task_id}/artifacts/{path}` | Authorized artifact/range response |
| `POST` | `/compute/api/results/{task_id}/archive` | Request an asynchronous ZIP |
| `GET` | `/compute/api/download/{task_id}` | Download a completed ZIP |

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
